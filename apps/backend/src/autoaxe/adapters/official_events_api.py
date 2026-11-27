"""Authenticated, permission-filtered point-in-time official event read API."""

import os
from typing import Annotated

import psycopg
from fastapi import APIRouter, Cookie, HTTPException, Query, Request

from autoaxe.adapters.contracts import Contract, Identifier, UtcTime
from autoaxe.domain.owner_access import is_configured_owner
from autoaxe.entrypoints.auth import SESSION_COOKIE
from autoaxe.entrypoints.auth import _dsn as identity_dsn
from autoaxe.infrastructure.event_store import query_events
from autoaxe.infrastructure.market_store import PermissionDenied
from autoaxe.infrastructure.sessions import authorize

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard-events"])


class OfficialEventView(Contract):
    event_key: str
    source_id: Identifier
    revision: int
    actual: str | None
    forecast: str | None
    previous: str | None
    unit: str
    scheduled_at: UtcTime | None
    released_at: UtcTime | None
    first_seen_at: UtcTime
    available_at: UtcTime
    source_url: str


class EventMeta(Contract):
    request_id: Identifier
    as_of: UtcTime
    source_scope: str | None = None
    available_count: int


class OfficialEventsResponse(Contract):
    data: list[OfficialEventView]
    meta: EventMeta


@router.get(
    "/official-events",
    operation_id="listAuthorizedOfficialEvents",
    response_model=OfficialEventsResponse,
)
def list_authorized_official_events(
    request: Request,
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    source_id: str | None = None,
    as_of: UtcTime | None = None,
    limit: int = Query(50, ge=1, le=100),
) -> OfficialEventsResponse:
    read_dsn = os.environ.get("AUTOAXE_MARKET_READ_DSN")
    if not read_dsn:
        raise HTTPException(503, "market read authority not configured")
    try:
        with psycopg.connect(identity_dsn(), connect_timeout=3) as app:
            grant = authorize(app, session_id, required_scope="indicators:read")
        with psycopg.connect(read_dsn, connect_timeout=3) as market:
            clock = market.execute("SELECT clock_timestamp()").fetchone()
            assert clock is not None
            cutoff = as_of or clock[0]
            if cutoff > clock[0]:
                raise HTTPException(400, "future cutoff")
            events = query_events(
                market,
                cutoff=cutoff,
                source_id=source_id,
                limit=limit,
                private_use=is_configured_owner(grant.subject_ref),
            )
    except PermissionError as exc:
        raise HTTPException(401, "session invalid or insufficient scope") from exc
    except PermissionDenied as exc:
        raise HTTPException(403, "market event access denied") from exc
    except ValueError as exc:
        raise HTTPException(400, "invalid event query") from exc
    except psycopg.Error as exc:
        raise HTTPException(503, "event authority unavailable") from exc
    return OfficialEventsResponse(
        data=[
            OfficialEventView(
                event_key=e.event_key,
                source_id=e.source_id,
                revision=e.revision,
                actual=e.actual,
                forecast=e.forecast,
                previous=e.previous,
                unit=e.unit,
                scheduled_at=e.scheduled_at,
                released_at=e.released_at,
                first_seen_at=e.first_seen_at,
                available_at=e.available_at,
                source_url=e.source_url,
            )
            for e in events
        ],
        meta=EventMeta(
            request_id=request.state.request_id,
            as_of=cutoff,
            source_scope=source_id,
            available_count=len(events),
        ),
    )
