"""Private broker HTTP contract; inert until real server-side mTLS identity is verified.

DO NOT include this router in the public API. A trusted TLS gateway/ASGI server
must implement a verified certificate-to-principal binding; request headers
are never proof. Fixture tests may override the dependency explicitly.
"""

import os
from datetime import datetime
from typing import Annotated, Any, Literal

import psycopg
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from autoaxe.application.scrape_broker import (
    claim,
    complete,
    heartbeat,
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
    job_nonce: str
    lease_token: str


class ResultRequest(HeartbeatRequest):
    source_id: Literal["cnn", "pizzint", "dramexchange", "seibro", "naver"]
    adapter_version: int = Field(default=1, ge=1, le=1)
    candidates: list[dict[str, Any]] = Field(max_length=100)


def service_identity() -> str:
    """Deliberately unimplemented until verified mutual-TLS transport is deployed."""
    raise HTTPException(503, "verified scraper mTLS service identity unavailable")


def broker_dsn() -> str:
    dsn = os.environ.get("AUTOAXE_SCRAPE_BROKER_MARKET_DSN")
    if not dsn:
        raise HTTPException(503, "scrape broker database is not configured")
    return dsn


def create_broker_app() -> FastAPI:
    api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @api.post("/internal/v1/scrape/jobs/claim", response_model=LeaseResponse | None)
    def claim_job(
        body: ClaimRequest,
        identity: Annotated[str, Depends(service_identity)],
    ) -> LeaseResponse | None:
        if identity != "scraper-worker":
            raise HTTPException(403, "unrecognized service principal")
        try:
            with psycopg.connect(broker_dsn(), connect_timeout=3) as conn:
                lease = claim(conn, source=body.source_id, lease_seconds=body.lease_seconds)
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
        job_id: str,
        body: HeartbeatRequest,
        identity: Annotated[str, Depends(service_identity)],
    ) -> dict[str, str]:
        if identity != "scraper-worker":
            raise HTTPException(403, "unrecognized service principal")
        try:
            with psycopg.connect(broker_dsn(), connect_timeout=3) as conn:
                if not heartbeat(conn, job_id, body.lease_token, body.job_nonce):
                    raise HTTPException(409, "expired or revoked lease")
        except psycopg.Error as exc:
            raise HTTPException(503, "broker unavailable") from exc
        return {"status": "leased"}

    @api.post("/internal/v1/scrape/jobs/{job_id}/result")
    def submit_result(
        job_id: str,
        body: ResultRequest,
        identity: Annotated[str, Depends(service_identity)],
    ) -> dict[str, str]:
        if identity != "scraper-worker":
            raise HTTPException(403, "unrecognized service principal")
        try:
            with psycopg.connect(broker_dsn(), connect_timeout=3) as conn:
                state = complete(
                    conn,
                    job_id,
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

    return api


app = create_broker_app()
