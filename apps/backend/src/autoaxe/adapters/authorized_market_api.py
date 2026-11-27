"""Scoped BFF historical market read: approved sources only, never public."""

import os
from typing import Annotated

import psycopg
from fastapi import APIRouter, Cookie, HTTPException, Query, Request

from autoaxe.adapters.contracts import Contract, Identifier, UtcTime
from autoaxe.domain.catalog import catalog
from autoaxe.entrypoints.auth import SESSION_COOKIE
from autoaxe.entrypoints.auth import _dsn as identity_dsn
from autoaxe.infrastructure.authorized_market import authorized_observations
from autoaxe.infrastructure.market_store import PermissionDenied
from autoaxe.infrastructure.sessions import authorize

router = APIRouter(prefix="/api/v1/dashboard/authorized", tags=["dashboard-authorized"])


class AuthorizedPoint(Contract):
    event_key: str
    revision: int
    value: str | None
    quality: str
    source_event_at: UtcTime | None
    received_at: UtcTime
    available_at: UtcTime


class AuthorizedMeta(Contract):
    request_id: Identifier
    series_id: Identifier
    source_id: Identifier
    unit: str
    currency: str | None
    as_of: UtcTime
    permission: str = "approved_with_redistribution"


class AuthorizedSeriesPage(Contract):
    data: list[AuthorizedPoint]
    meta: AuthorizedMeta


@router.get(
    "/market/{series_id}",
    operation_id="listAuthorizedMarketObservations",
    response_model=AuthorizedSeriesPage,
)
def list_authorized_market_observations(
    series_id: str,
    request: Request,
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    as_of: UtcTime | None = None,
    limit: int = Query(100, ge=1, le=200),
) -> AuthorizedSeriesPage:
    entry = catalog().get(series_id)
    if not entry:
        raise HTTPException(404, "unknown market instrument")
    dsn = os.environ.get("AUTOAXE_MARKET_READ_DSN")
    if not dsn:
        raise HTTPException(503, "read-only market authority not configured")
    try:
        with psycopg.connect(identity_dsn(), connect_timeout=3) as app:
            authorize(app, session_id, required_scope="indicators:read")
        with psycopg.connect(dsn, connect_timeout=3) as market:
            clock = market.execute("SELECT clock_timestamp()").fetchone()
            assert clock is not None
            cutoff = as_of or clock[0]
            if cutoff > clock[0]:
                raise HTTPException(400, "future snapshot cutoff")
            rows = authorized_observations(market, series_id=series_id, cutoff=cutoff, limit=limit)
    except PermissionError as exc:
        raise HTTPException(401, "session invalid or insufficient scope") from exc
    except PermissionDenied as exc:
        raise HTTPException(403, "source redistribution not authorized") from exc
    except psycopg.Error as exc:
        raise HTTPException(503, "read-only market authority unavailable") from exc
    return AuthorizedSeriesPage(
        data=[
            AuthorizedPoint(
                event_key=row["source_event_key"],
                revision=row["revision"],
                value=str(row["value"]) if row["value"] is not None else None,
                quality=row["quality"],
                source_event_at=row["source_event_at"],
                received_at=row["received_at"],
                available_at=row["available_at"],
            )
            for row in rows
        ],
        meta=AuthorizedMeta(
            request_id=request.state.request_id,
            series_id=series_id,
            source_id=entry.source_id,
            unit=entry.unit,
            currency=entry.currency,
            as_of=cutoff,
        ),
    )
