"""Authenticated, permission-filtered point-in-time official event read API."""

import os
from datetime import date
from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, Cookie, HTTPException, Query, Request

from autoaxe.adapters.contracts import Contract, Identifier, UtcTime
from autoaxe.domain.calendars import EventRevision
from autoaxe.domain.economic_linkage import LinkResult, LinkStatus
from autoaxe.domain.owner_access import is_configured_owner
from autoaxe.entrypoints.auth import SESSION_COOKIE
from autoaxe.entrypoints.auth import _dsn as identity_dsn
from autoaxe.infrastructure.event_store import query_event_links, query_events
from autoaxe.infrastructure.market_store import PermissionDenied
from autoaxe.infrastructure.sessions import authorize

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard-events"])


class OfficialCalendarView(Contract):
    title: str | None
    date_only: date | None
    status: Literal["confirmed", "unspecified", "tentative", "cancelled", "unsupported"]


class OfficialPeriodMatch(Contract):
    """A same-source, same-period reference, not a verified release vintage."""

    event_key: str
    revision: int
    scheduled_at: UtcTime | None
    date_only: date | None
    title: str | None
    available_at: UtcTime
    source_url: str


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
    calendar: OfficialCalendarView | None = None
    metric_id: str | None = None
    reference_period: str | None = None
    link_status: LinkStatus = "not_applicable"
    period_match: OfficialPeriodMatch | None = None


def event_view(event: EventRevision, link: LinkResult) -> OfficialEventView:
    match = link.schedule
    return OfficialEventView(
        event_key=event.event_key,
        source_id=event.source_id,
        revision=event.revision,
        actual=event.actual,
        forecast=event.forecast,
        previous=event.previous,
        unit=event.unit,
        scheduled_at=event.scheduled_at,
        released_at=event.released_at,
        first_seen_at=event.first_seen_at,
        available_at=event.available_at,
        source_url=event.source_url,
        calendar=OfficialCalendarView(
            title=event.calendar.title,
            date_only=event.calendar.date_only,
            status=event.calendar.status,
        )
        if event.calendar
        else None,
        metric_id=link.identity.metric_id if link.identity else None,
        reference_period=link.identity.reference_period if link.identity else None,
        link_status=link.status,
        period_match=OfficialPeriodMatch(
            event_key=match.event_key,
            revision=match.revision,
            scheduled_at=match.scheduled_at,
            date_only=match.calendar.date_only if match.calendar else None,
            title=match.calendar.title if match.calendar else None,
            available_at=match.available_at,
            source_url=match.source_url,
        )
        if match
        else None,
    )


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
            market.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            market.execute("SET LOCAL statement_timeout = '3s'")
            clock = market.execute("SELECT transaction_timestamp()").fetchone()
            assert clock is not None
            cutoff = as_of or clock[0]
            if cutoff > clock[0]:
                raise HTTPException(400, "future cutoff")
            private_use = is_configured_owner(grant.subject_ref)
            events = query_events(
                market,
                cutoff=cutoff,
                source_id=source_id,
                limit=limit,
                private_use=private_use,
            )
            links = query_event_links(market, events=events, cutoff=cutoff, private_use=private_use)
    except PermissionError as exc:
        raise HTTPException(401, "session invalid or insufficient scope") from exc
    except PermissionDenied as exc:
        raise HTTPException(403, "market event access denied") from exc
    except ValueError as exc:
        raise HTTPException(400, "invalid event query") from exc
    except psycopg.Error as exc:
        raise HTTPException(503, "event authority unavailable") from exc
    return OfficialEventsResponse(
        data=[event_view(e, links[(e.source_id, e.event_key)]) for e in events],
        meta=EventMeta(
            request_id=request.state.request_id,
            as_of=cutoff,
            source_scope=source_id,
            available_count=len(events),
        ),
    )
