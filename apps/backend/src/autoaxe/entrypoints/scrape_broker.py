"""Private broker with direct mutually authenticated TLS (never trust HTTP headers)."""

import asyncio
import hashlib
import hmac
import os
import re
import ssl
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

import psycopg
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send
from uvicorn.protocols.http.h11_impl import H11Protocol

from autoaxe.application.scrape_broker import (
    claim,
    complete,
    fail,
    heartbeat,
    validate_candidates,
)
from autoaxe.infrastructure.market_store import PermissionDenied


class StrictDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ClaimRequest(StrictDTO):
    source_id: Literal["cnn", "pizzint", "dramexchange", "seibro", "naver"]
    lease_seconds: int = Field(default=30, ge=1, le=60)


class LeaseResponse(StrictDTO):
    job_id: str
    source_id: str
    adapter_version: int
    schema_version: int
    params: dict[str, str]
    job_nonce: str
    lease_token: str
    deadline_at: datetime
    lease_expires_at: datetime
    permission_version: int


class HeartbeatRequest(StrictDTO):
    job_nonce: str = Field(min_length=10, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")
    lease_token: str = Field(min_length=10, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")


class ResultRequest(HeartbeatRequest):
    source_id: Literal["cnn", "pizzint", "dramexchange", "seibro", "naver"]
    adapter_version: int = Field(default=1, ge=1, le=1)
    candidates: list[dict[str, Any]] = Field(max_length=100)


class FailureRequest(HeartbeatRequest):
    source_id: Literal["cnn", "dramexchange", "naver"]
    reason: Literal["http", "schema", "transport"]
    http_status: int | None = Field(default=None, ge=100, le=599)
    retry_header: str | None = Field(default=None, max_length=128)


MAX_REQUEST_BYTES = 262_144
_VERIFIED_PEER = object()
_PEER_KEY = "autoaxe.scrape.verified_peer"
HTTP_SOURCES = frozenset({"cnn", "dramexchange", "naver"})


def _allowed_fingerprints() -> tuple[str, ...]:
    pins = tuple(os.environ.get("AUTOAXE_SCRAPER_CERT_SHA256", "").lower().split(","))
    if not all(re.fullmatch(r"[0-9a-f]{64}", pin) for pin in pins) or len(pins) > 2:
        raise ValueError("configure one or two scraper certificate SHA256 fingerprints")
    return pins


class VerifiedTLSProtocol(H11Protocol):
    """Bind a per-connection ASGI app to the real, CA-verified TLS peer.

    Uvicorn's ordinary ASGI scope does not expose the client certificate.
    This protocol is used only by the dedicated TLS listener below.
    """

    def connection_made(self, transport: asyncio.Transport) -> None:  # type: ignore[override]
        super().connection_made(transport)
        tls = transport.get_extra_info("ssl_object")
        cert = None
        if isinstance(tls, (ssl.SSLObject, ssl.SSLSocket)):
            if tls.context.verify_mode == ssl.CERT_REQUIRED:
                cert = tls.getpeercert(binary_form=True)
        try:
            pins = _allowed_fingerprints()
        except ValueError:
            pins = ()
        if not cert or not any(
            hmac.compare_digest(hashlib.sha256(cert).hexdigest(), pin) for pin in pins
        ):
            transport.close()
            return
        original = self.app

        async def bound(scope: Scope, receive: Receive, send: Send) -> None:
            # The sentinel is injected in-process from the verified connection,
            # not copied from any header or forwarded proxy metadata.
            scope[_PEER_KEY] = _VERIFIED_PEER
            body = bytearray()
            try:
                async with asyncio.timeout(10):
                    while True:
                        message = await receive()
                        if message["type"] != "http.request":
                            return
                        body.extend(message.get("body", b""))
                        if len(body) > MAX_REQUEST_BYTES:
                            await JSONResponse({"detail": "request too large"}, 413)(
                                scope, receive, send
                            )
                            return
                        if not message.get("more_body", False):
                            break
            except TimeoutError:
                await JSONResponse({"detail": "request timeout"}, 408)(scope, receive, send)
                return

            async def replay() -> Message:
                return {"type": "http.request", "body": bytes(body), "more_body": False}

            await original(scope, replay, send)

        self.app = bound


def service_identity(request: Request) -> str:
    if request.scope.get(_PEER_KEY) is not _VERIFIED_PEER:
        raise HTTPException(503, "verified scraper mTLS service identity unavailable")
    return "scraper-worker"


def broker_dsn() -> str:
    dsn = os.environ.get("AUTOAXE_SCRAPE_BROKER_MARKET_DSN")
    if not dsn:
        raise HTTPException(503, "scrape broker database is not configured")
    return dsn


def create_broker_app() -> FastAPI:
    api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @api.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, __: RequestValidationError) -> JSONResponse:
        # Never echo rejected lease credentials or candidate payloads.
        return JSONResponse({"detail": "invalid broker request"}, 422)

    @api.post("/internal/v1/scrape/jobs/claim", response_model=LeaseResponse | None)
    def claim_job(
        body: ClaimRequest,
        identity: Annotated[str, Depends(service_identity)],
    ) -> LeaseResponse | None:
        if identity != "scraper-worker":
            raise HTTPException(403, "unrecognized service principal")
        if body.source_id not in HTTP_SOURCES:
            raise HTTPException(403, "source not enabled for generic HTTP worker")
        try:
            with psycopg.connect(broker_dsn(), connect_timeout=3) as conn:
                lease = claim(
                    conn,
                    source=body.source_id,
                    lease_seconds=body.lease_seconds,
                    scheduled_only=True,
                )
        except PermissionDenied as exc:
            raise HTTPException(403, "source permission denied") from exc
        except psycopg.Error as exc:
            raise HTTPException(503, "broker unavailable") from exc
        if lease is None:
            return None
        return LeaseResponse(
            job_id=lease.job_id,
            source_id=lease.source_id,
            params=lease.params,
            adapter_version=lease.adapter_version,
            schema_version=lease.schema_version,
            job_nonce=lease.nonce,
            lease_token=lease.lease_token,
            deadline_at=lease.deadline_at,
            lease_expires_at=lease.expires_at,
            permission_version=lease.permission_version,
        )

    @api.post("/internal/v1/scrape/jobs/{job_id}/heartbeat")
    def heartbeat_job(
        job_id: UUID,
        body: HeartbeatRequest,
        identity: Annotated[str, Depends(service_identity)],
    ) -> dict[str, str]:
        if identity != "scraper-worker":
            raise HTTPException(403, "unrecognized service principal")
        try:
            with psycopg.connect(broker_dsn(), connect_timeout=3) as conn:
                valid = heartbeat(conn, str(job_id), body.lease_token, body.job_nonce)
        except psycopg.Error as exc:
            raise HTTPException(503, "broker unavailable") from exc
        if not valid:
            # Commit the revoked state before returning the rejection.
            raise HTTPException(409, "expired or revoked lease")
        return {"status": "leased"}

    @api.post("/internal/v1/scrape/jobs/{job_id}/result")
    def submit_result(
        job_id: UUID,
        body: ResultRequest,
        identity: Annotated[str, Depends(service_identity)],
    ) -> dict[str, str]:
        if identity != "scraper-worker":
            raise HTTPException(403, "unrecognized service principal")
        if body.source_id not in HTTP_SOURCES:
            raise HTTPException(403, "source not enabled for generic HTTP worker")
        try:
            validate_candidates(body.source_id, body.candidates)
            with psycopg.connect(broker_dsn(), connect_timeout=3) as conn:
                state = complete(
                    conn,
                    str(job_id),
                    body.source_id,
                    body.lease_token,
                    body.job_nonce,
                    body.candidates,
                    adapter_version=body.adapter_version,
                )
        except PermissionDenied as exc:
            raise HTTPException(403, "scrape job identity or source permission denied") from exc
        except ValueError as exc:
            raise HTTPException(422, "invalid scrape result") from exc
        except psycopg.Error as exc:
            raise HTTPException(503, "broker unavailable") from exc
        return {"status": state}

    @api.post("/internal/v1/scrape/jobs/{job_id}/failure")
    def submit_failure(
        job_id: UUID,
        body: FailureRequest,
        identity: Annotated[str, Depends(service_identity)],
    ) -> dict[str, str]:
        if identity != "scraper-worker":
            raise HTTPException(403, "unrecognized service principal")
        try:
            with psycopg.connect(broker_dsn(), connect_timeout=3) as conn:
                state = fail(
                    conn,
                    str(job_id),
                    body.source_id,
                    body.lease_token,
                    body.job_nonce,
                    reason=body.reason,
                    http_status=body.http_status,
                    retry_header=body.retry_header,
                )
        except PermissionDenied as exc:
            raise HTTPException(403, "stale or unauthorized failure report") from exc
        except ValueError as exc:
            raise HTTPException(422, "invalid failure report") from exc
        except psycopg.Error as exc:
            raise HTTPException(503, "broker unavailable") from exc
        return {"status": state}

    return api


app = create_broker_app()


def main() -> None:
    """Only the private broker process loads client trust and server key material."""
    _allowed_fingerprints()
    uvicorn.run(
        app,
        host=os.environ.get("AUTOAXE_SCRAPE_BROKER_HOST", "127.0.0.1"),
        port=int(os.environ.get("AUTOAXE_SCRAPE_BROKER_PORT", "8443")),
        http=VerifiedTLSProtocol,
        ws="none",
        proxy_headers=False,
        ssl_certfile=os.environ["AUTOAXE_SCRAPE_BROKER_CERT"],
        ssl_keyfile=os.environ["AUTOAXE_SCRAPE_BROKER_KEY"],
        ssl_ca_certs=os.environ["AUTOAXE_SCRAPE_BROKER_CLIENT_CA"],
        ssl_cert_reqs=ssl.CERT_REQUIRED,
        limit_concurrency=16,
        timeout_keep_alive=2,
        access_log=False,
    )


if __name__ == "__main__":
    main()
