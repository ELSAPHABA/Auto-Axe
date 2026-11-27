"""Authenticated, permission-gated company guidance read API."""

import os
from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, Cookie, HTTPException, Query, Request

from autoaxe.adapters.contracts import Contract, Identifier, Money, UtcTime
from autoaxe.domain.owner_access import is_configured_owner
from autoaxe.entrypoints.auth import SESSION_COOKIE
from autoaxe.entrypoints.auth import _dsn as identity_dsn
from autoaxe.infrastructure.document_store import query_guidance
from autoaxe.infrastructure.market_store import PermissionDenied
from autoaxe.infrastructure.sessions import authorize

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard-guidance"])


class GuidanceView(Contract):
    cik: str
    accession: str
    fiscal_period: str
    metric: str
    basis: Literal["GAAP", "ADJUSTED"]
    low: Money
    high: Money
    unit: str
    source_url: str
    issued_at: UtcTime | None
    first_seen_at: UtcTime
    available_at: UtcTime
    quality: Literal["manual_checked"] = "manual_checked"


class GuidanceMeta(Contract):
    request_id: Identifier
    as_of: UtcTime


class GuidancePage(Contract):
    data: list[GuidanceView]
    meta: GuidanceMeta


@router.get(
    "/corporate-guidance",
    operation_id="listAuthorizedCorporateGuidance",
    response_model=GuidancePage,
)
def guidance(
    request: Request,
    sid: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    cik: str | None = Query(None, pattern=r"^\d{10}$"),
    as_of: UtcTime | None = None,
    limit: int = Query(100, ge=1, le=200),
) -> GuidancePage:
    dsn = os.environ.get("AUTOAXE_MARKET_READ_DSN")
    if not dsn:
        raise HTTPException(503, "market read authority not configured")
    try:
        with psycopg.connect(identity_dsn(), connect_timeout=3) as app:
            grant = authorize(app, sid, required_scope="indicators:read")
        with psycopg.connect(dsn, connect_timeout=3) as market:
            market.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            market.execute("SET LOCAL statement_timeout = '3s'")
            clock = market.execute("SELECT transaction_timestamp()").fetchone()
            assert clock is not None
            cutoff = as_of or clock[0]
            if cutoff > clock[0]:
                raise HTTPException(400, "future cutoff")
            rows = query_guidance(
                market,
                cutoff=cutoff,
                private_use=is_configured_owner(grant.subject_ref),
                cik=cik,
                limit=limit,
            )
    except (PermissionError, UnicodeError) as exc:
        raise HTTPException(401, "session invalid or insufficient scope") from exc
    except PermissionDenied as exc:
        raise HTTPException(403, "market authority denied") from exc
    except psycopg.Error as exc:
        raise HTTPException(503, "market authority unavailable") from exc
    return GuidancePage(
        data=[GuidanceView.model_validate(row) for row in rows],
        meta=GuidanceMeta(request_id=request.state.request_id, as_of=cutoff),
    )
