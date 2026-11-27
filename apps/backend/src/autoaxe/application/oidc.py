"""Keycloak OIDC Authorization Code + PKCE; secrets/tokens never reach browser storage."""

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from psycopg import Connection

from autoaxe.infrastructure.sessions import create_session, digest


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class OIDCConfig:
    issuer: str
    client_id: str
    redirect_uri: str
    cipher_key: bytes
    client_secret: str | None = None

    def __post_init__(self) -> None:
        issuer = urlsplit(self.issuer)
        redirect = urlsplit(self.redirect_uri)
        if (
            issuer.scheme != "https"
            or not issuer.hostname
            or issuer.username
            or issuer.password
            or issuer.port not in (None, 443)
            or issuer.query
            or issuer.fragment
            or self.issuer.endswith("/")
        ):
            raise ValueError("OIDC issuer must be exact trusted HTTPS origin/path")
        if (
            redirect.scheme != "https"
            or not redirect.hostname
            or redirect.query
            or redirect.fragment
            or not redirect.path.endswith("/auth/callback")
        ):
            raise ValueError("OIDC callback must be pinned HTTPS path")
        if not self.client_id or len(self.cipher_key) != 32:
            raise ValueError("OIDC client/key missing")


def _same_origin(url: str, issuer: str) -> bool:
    left, right = urlsplit(url), urlsplit(issuer)
    return (
        left.scheme == right.scheme == "https"
        and left.hostname == right.hostname
        and left.port == right.port
        and not left.username
        and not left.password
        and not left.fragment
    )


def _json(
    client: httpx.Client, url: str, *, issuer: str, post_data: dict[str, str] | None = None
) -> dict[str, Any]:
    if not _same_origin(url, issuer):
        raise PermissionError("OIDC endpoint not on configured issuer host")
    response = client.post(url, data=post_data) if post_data is not None else client.get(url)
    response.raise_for_status()
    if len(response.content) > 128_000:
        raise ValueError("oversized OIDC document")
    result: dict[str, Any] = response.json()
    if not isinstance(result, dict):
        raise ValueError("invalid OIDC response")
    return result


def discover(client: httpx.Client, config: OIDCConfig) -> dict[str, str]:
    url = config.issuer + "/.well-known/openid-configuration"
    metadata = _json(client, url, issuer=config.issuer)
    if metadata.get("issuer") != config.issuer:
        raise PermissionError("OIDC issuer mismatch")
    endpoints = {
        key: metadata.get(key) for key in ("authorization_endpoint", "token_endpoint", "jwks_uri")
    }
    if any(
        not isinstance(value, str) or not _same_origin(value, config.issuer)
        for value in endpoints.values()
    ):
        raise PermissionError("untrusted OIDC endpoint")
    return endpoints  # type: ignore[return-value]


def begin(conn: Connection[Any], config: OIDCConfig, metadata: dict[str, str]) -> tuple[str, str]:
    """Persist only hashed state/nonce and AES-GCM encrypted verifier."""
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    iv = secrets.token_bytes(12)
    encrypted = iv + AESGCM(config.cipher_key).encrypt(iv, verifier.encode("ascii"), None)
    conn.execute(
        """INSERT INTO identity.oidc_states(state_hash,nonce_hash,code_verifier_ciphertext,
        expires_at) VALUES (%s,%s,%s,clock_timestamp()+interval '5 minutes')""",
        (digest(state), digest(nonce), encrypted),
    )
    challenge = _b64(hashlib.sha256(verifier.encode("ascii")).digest())
    params = {
        "response_type": "code",
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "scope": "openid",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return metadata["authorization_endpoint"] + "?" + urlencode(params), state


def finish(
    conn: Connection[Any],
    config: OIDCConfig,
    metadata: dict[str, str],
    client: httpx.Client,
    code: str,
    state: str,
) -> tuple[str, str]:
    """One-time state consumption; signed issuer/audience/nonce verification precedes session."""
    if not code or len(code) > 4096 or not state or len(state) > 256:
        raise PermissionError("invalid OIDC callback")
    row = conn.execute(
        """SELECT nonce_hash,code_verifier_ciphertext FROM identity.oidc_states
        WHERE state_hash=%s AND consumed_at IS NULL AND expires_at>clock_timestamp()
        FOR UPDATE""",
        (digest(state),),
    ).fetchone()
    if not row:
        raise PermissionError("OIDC state expired/reused")
    conn.execute(
        "UPDATE identity.oidc_states SET consumed_at=clock_timestamp() WHERE state_hash=%s",
        (digest(state),),
    )
    encrypted = bytes(row[1])
    verifier = (
        AESGCM(config.cipher_key).decrypt(encrypted[:12], encrypted[12:], None).decode("ascii")
    )
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "code_verifier": verifier,
    }
    if config.client_secret is not None:
        data["client_secret"] = config.client_secret
    token = _json(client, metadata["token_endpoint"], issuer=config.issuer, post_data=data)
    id_token = token.get("id_token")
    if not isinstance(id_token, str) or len(id_token) > 16000:
        raise PermissionError("missing provider identity token")
    jwks = _json(client, metadata["jwks_uri"], issuer=config.issuer)
    header = jwt.get_unverified_header(id_token)
    if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
        raise PermissionError("unsupported OIDC signing key")
    keys = jwks.get("keys", [])
    selected = [key for key in keys if key.get("kid") == header["kid"]]
    if len(selected) != 1:
        raise PermissionError("unknown OIDC signing key")
    key = jwt.PyJWK.from_dict(selected[0]).key
    payload = jwt.decode(
        id_token,
        key,
        algorithms=["RS256"],
        audience=config.client_id,
        issuer=config.issuer,
        options={"require": ["iss", "sub", "aud", "iat", "exp", "nonce"]},
    )
    nonce = payload["nonce"]
    if not isinstance(nonce, str) or not hmac.compare_digest(digest(nonce), row[0]):
        raise PermissionError("OIDC nonce mismatch")
    subject = payload["sub"]
    if not isinstance(subject, str) or not subject or len(subject) > 256:
        raise PermissionError("invalid OIDC subject")
    return create_session(
        conn,
        config.issuer + "|" + subject,
        config.issuer,
        datetime.fromtimestamp(payload["exp"], tz=UTC),
    )
