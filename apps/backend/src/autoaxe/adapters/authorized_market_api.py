"""Scoped BFF historical market read: approved sources only, never public."""

import os
from datetime import date
from typing import Annotated

import psycopg
from fastapi import APIRouter, Cookie, HTTPException, Query, Request

from autoaxe.adapters.contracts import Contract, Identifier, Money, UtcTime
from autoaxe.domain.catalog import catalog
from autoaxe.domain.owner_access import is_configured_owner
from autoaxe.entrypoints.auth import SESSION_COOKIE
from autoaxe.entrypoints.auth import _dsn as identity_dsn
from autoaxe.infrastructure.authorized_market import authorized_observations
from autoaxe.infrastructure.market_store import PermissionDenied
from autoaxe.infrastructure.sessions import authorize

router = APIRouter(prefix="/api/v1/dashboard/authorized", tags=["dashboard-authorized"])


class DailyBar(Contract):
    session_date: date
    open: Money
    high: Money
    low: Money
    close: Money
    volume: Money
    features: dict[str, Money | None]


class AuthorizedPoint(Contract):
    event_key: str
    revision: int
    value: str | None
    quality: str
    source_event_at: UtcTime | None
    received_at: UtcTime
    available_at: UtcTime
    bar: DailyBar | None = None
    fundamentals: dict[str, Money | None] | None = None


class AuthorizedMeta(Contract):
    request_id: Identifier
    series_id: Identifier
    source_id: Identifier
    unit: str
    currency: str | None
    as_of: UtcTime
    permission: str
    collector_status: str | None = None
    collector_checked_at: UtcTime | None = None


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
            grant = authorize(app, session_id, required_scope="indicators:read")
        private_use = is_configured_owner(grant.subject_ref)
        with psycopg.connect(dsn, connect_timeout=3) as market:
            clock = market.execute("SELECT clock_timestamp()").fetchone()
            assert clock is not None
            cutoff = as_of or clock[0]
            if cutoff > clock[0]:
                raise HTTPException(400, "future snapshot cutoff")
            rows = authorized_observations(
                market,
                series_id=series_id,
                cutoff=cutoff,
                limit=limit,
                private_use=private_use,
            )
            health = (
                market.execute(
                    "SELECT status,checked_at FROM ops.collector_health WHERE series_id=%s",
                    (series_id,),
                ).fetchone()
                if entry.source_id == "pizzint"
                else None
            )
    except PermissionError as exc:
        raise HTTPException(401, "session invalid or insufficient scope") from exc
    except PermissionDenied as exc:
        raise HTTPException(403, "source not approved for this audience") from exc
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
                bar=DailyBar(
                    session_date=date.fromisoformat(row["metadata"]["session_date"]),
                    open=row["metadata"]["open"],
                    high=row["metadata"]["high"],
                    low=row["metadata"]["low"],
                    close=row["metadata"]["close"],
                    volume=row["metadata"]["volume"],
                    features={
                        k: v["value"] for k, v in row["metadata"].get("features", {}).items()
                    },
                )
                if series_id in {"NVDA_DAILY_OHLCV", "QLD_DAILY_OHLCV"}
                else None,
                fundamentals={
                    k: row["metadata"]["metrics"].get(k)
                    for k in ("per_ttm", "per_forward", "pbr", "roe_ratio")
                }
                if series_id in {"NVDA_FUNDAMENTALS", "QLD_FUNDAMENTALS"}
                else None,
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
            permission=(
                "approved_personal_education" if private_use else "approved_with_redistribution"
            ),
            collector_status=health[0] if health else None,
            collector_checked_at=health[1] if health else None,
        ),
    )
