"""Disabled-by-default OIDC BFF endpoints and PostgreSQL session authority."""

import base64
import hmac
import os
from urllib.parse import urlsplit

import httpx
import psycopg
from fastapi import APIRouter, Cookie, Header, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from autoaxe.application.oidc import OIDCConfig, begin, discover, finish
from autoaxe.infrastructure.sessions import authorize, revoke

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
SESSION_COOKIE = "__Host-autoaxe-sid"
STATE_COOKIE = "__Host-autoaxe-oidc-state"
CSRF_COOKIE = "__Host-autoaxe-csrf"


def _config() -> OIDCConfig:
    try:
        return OIDCConfig(
            issuer=os.environ["AUTOAXE_OIDC_ISSUER"],
            client_id=os.environ["AUTOAXE_OIDC_CLIENT_ID"],
            redirect_uri=os.environ["AUTOAXE_OIDC_REDIRECT_URI"],
            cipher_key=base64.urlsafe_b64decode(os.environ["AUTOAXE_SESSION_KEY"]),
            client_secret=os.environ.get("AUTOAXE_OIDC_CLIENT_SECRET"),
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(503, "OIDC not configured") from exc


def _dsn() -> str:
    value = os.environ.get("AUTOAXE_APP_RUNTIME_DSN")
    if not value:
        raise HTTPException(503, "session store not configured")
    return value


def _trusted_origin(request: Request, *, mutation: bool) -> None:
    origin = os.environ.get("AUTOAXE_PUBLIC_ORIGIN")
    if not origin or urlsplit(origin).scheme != "https":
        raise HTTPException(503, "HTTPS origin not configured")
    if mutation and not hmac.compare_digest(request.headers.get("origin", ""), origin):
        raise HTTPException(403, "Origin mismatch")


def _client() -> httpx.Client:
    return httpx.Client(timeout=8, follow_redirects=False, trust_env=False)


@router.get("/login", operation_id="startOidcLogin", include_in_schema=False)
def login(request: Request) -> Response:
    _trusted_origin(request, mutation=False)
    config = _config()
    try:
        with _client() as client:
            endpoints = discover(client, config)
        with psycopg.connect(_dsn()) as conn:
            target, state = begin(conn, config, endpoints)
    except (httpx.HTTPError, psycopg.Error, ValueError, PermissionError) as exc:
        raise HTTPException(503, "identity unavailable") from exc
    response = RedirectResponse(target, status_code=302)
    response.set_cookie(
        STATE_COOKIE,
        state,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
        max_age=300,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/callback", operation_id="finishOidcLogin", include_in_schema=False)
def callback(
    request: Request,
    code: str,
    state: str,
    browser_state: str | None = Cookie(None, alias=STATE_COOKIE),
) -> Response:
    _trusted_origin(request, mutation=False)
    if not browser_state or not hmac.compare_digest(browser_state, state):
        raise HTTPException(403, "OIDC state cookie mismatch")
    config = _config()
    try:
        with _client() as client:
            metadata = discover(client, config)
            with psycopg.connect(_dsn()) as conn:
                session_id, csrf = finish(conn, config, metadata, client, code, state)
    except (httpx.HTTPError, psycopg.Error, ValueError, PermissionError) as exc:
        raise HTTPException(403, "identity verification failed") from exc
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(STATE_COOKIE, path="/")
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=12 * 3600,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        httponly=False,
        secure=True,
        samesite="lax",
        max_age=12 * 3600,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/session", operation_id="currentWebSession")
def current_session(sid: str | None = Cookie(None, alias=SESSION_COOKIE)) -> dict:
    try:
        with psycopg.connect(_dsn(), connect_timeout=3) as conn:
            identity = authorize(conn, sid)
        return {
            "data": {"role": identity.role, "scopes": sorted(identity.scopes)},
            "meta": {"authenticated": True},
        }
    except PermissionError as exc:
        raise HTTPException(401, "session unavailable or unauthorized") from exc
    except psycopg.Error as exc:
        raise HTTPException(503, "session authority unavailable") from exc


@router.post("/logout", operation_id="revokeWebSession")
def logout(
    request: Request,
    session_id: str | None = Cookie(None, alias=SESSION_COOKIE),
    csrf_cookie: str | None = Cookie(None, alias=CSRF_COOKIE),
    csrf_header: str | None = Header(None, alias="X-CSRF-Token"),
) -> Response:
    _trusted_origin(request, mutation=True)
    if not csrf_header or not csrf_cookie or not hmac.compare_digest(csrf_header, csrf_cookie):
        raise HTTPException(403, "CSRF header/cookie mismatch")
    try:
        with psycopg.connect(_dsn(), connect_timeout=3) as conn:
            authorize(conn, session_id, csrf=csrf_header)
            assert session_id is not None
            revoke(conn, session_id)
    except PermissionError as exc:
        raise HTTPException(403, "invalid session or CSRF") from exc
    except psycopg.Error as exc:
        raise HTTPException(503, "session authority unavailable") from exc
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return response
