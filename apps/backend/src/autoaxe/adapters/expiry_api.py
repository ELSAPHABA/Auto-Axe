"""Typed, authenticated, read-only PIT expiry calendar. No provider requests."""

import os
from dataclasses import asdict
from datetime import date
from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, Cookie, HTTPException, Request

from autoaxe.adapters.contracts import Contract, Identifier, UtcTime
from autoaxe.domain.calendars import FamilyState, Witching, witching_flags
from autoaxe.domain.expiry_evidence import ET, Family, Source, classify_reviewed
from autoaxe.domain.owner_access import is_configured_owner
from autoaxe.entrypoints.auth import SESSION_COOKIE
from autoaxe.entrypoints.auth import _dsn as identity_dsn
from autoaxe.infrastructure.expiry_store import query_expiry
from autoaxe.infrastructure.market_store import PermissionDenied
from autoaxe.infrastructure.sessions import authorize

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard-expiry"])


class ExpiryClaimView(Contract):
    candidate_date: date
    family: Family
    source_id: Source
    evidence_key: Identifier
    status: FamilyState
    session_date: date
    contract_ref: str | None
    nominal_expiry_date: date | None
    last_trade_at: UtcTime | None
    processing_at: UtcTime | None
    settlement_at: UtcTime | None
    settlement_basis: Literal["AM", "PM", "OTHER"] | None
    source_url: str
    evidence_ref: str
    family_coverage: bool
    last_trade_date: date | None = None
    processing_date: date | None = None
    settlement_date: date | None = None


class ReviewedExpiryView(Contract):
    claim: ExpiryClaimView
    revision: int
    first_seen_at: UtcTime
    available_at: UtcTime
    permission_version: int


class ExpirySessionView(Contract):
    session_date: date | None
    event_type: Witching
    family_status: dict[str, FamilyState]
    conflicted: bool
    is_triple: bool | None
    is_quadruple: bool | None
    calendar_days_to_session: int | None
    trading_days_to_session: int | None = None


class ExpiryMeta(Contract):
    request_id: Identifier
    as_of: UtcTime
    candidate_date: date
    schema_version: Literal[1] = 1


class ExpiryCalendarResponse(Contract):
    evidence: list[ReviewedExpiryView]
    sessions: list[ExpirySessionView]
    meta: ExpiryMeta


@router.get(
    "/expiry-calendar",
    operation_id="getAuthorizedExpiryCalendar",
    response_model=ExpiryCalendarResponse,
)
def get_expiry_calendar(
    request: Request,
    candidate_date: date,
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    as_of: UtcTime | None = None,
) -> ExpiryCalendarResponse:
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
            evidence = query_expiry(
                market,
                candidate_date=candidate_date,
                cutoff=cutoff,
                private_use=is_configured_owner(grant.subject_ref),
            )
            sessions = classify_reviewed(candidate_date, evidence, cutoff)
    except PermissionError as exc:
        raise HTTPException(401, "session invalid or insufficient scope") from exc
    except PermissionDenied as exc:
        raise HTTPException(403, "market expiry access denied") from exc
    except ValueError as exc:
        raise HTTPException(400, "invalid expiry query") from exc
    except psycopg.Error as exc:
        raise HTTPException(503, "expiry authority unavailable") from exc
    today = cutoff.astimezone(ET).date()
    return ExpiryCalendarResponse(
        evidence=[ReviewedExpiryView.model_validate(asdict(r)) for r in evidence],
        sessions=[
            ExpirySessionView(
                session_date=s.session_date,
                event_type=s.event_type,
                family_status=s.family_status,
                conflicted=s.conflicted,
                **witching_flags(s.event_type),
                calendar_days_to_session=(
                    (s.session_date - today).days
                    if s.session_date is not None
                    and s.session_date >= today
                    and s.event_type in (Witching.TRIPLE, Witching.QUADRUPLE)
                    else None
                ),
            )
            for s in sessions
        ],
        meta=ExpiryMeta(
            request_id=request.state.request_id, as_of=cutoff, candidate_date=candidate_date
        ),
    )
