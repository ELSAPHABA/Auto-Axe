"""Typed, authenticated, read-only PIT expiry calendar. No provider requests."""

import os
from dataclasses import asdict
from datetime import date
from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, Cookie, HTTPException, Request

from autoaxe.adapters.contracts import Contract, Identifier, UtcTime
from autoaxe.domain.calendars import FamilyState, Witching, witching_flags
from autoaxe.domain.equity_calendar import load_calendar
from autoaxe.domain.expiry_dte import (
    calendar_expiry_dte,
    calendar_witching_dte,
    product_session_dte,
)
from autoaxe.domain.expiry_evidence import ExpiryClassification, Family, Source, classify_reviewed
from autoaxe.domain.expiry_projection import next_projection, project_expiry
from autoaxe.domain.owner_access import is_configured_owner
from autoaxe.entrypoints.auth import SESSION_COOKIE
from autoaxe.entrypoints.auth import _dsn as identity_dsn
from autoaxe.infrastructure.expiry_session_store import query_calendar
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
    calendar_days_to_expiry: int | None = None
    trading_days_to_expiry: int | None = None


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


class ExpiryProjectionView(Contract):
    nominal_date: date
    estimated_date: date | None
    calendar_days: int | None
    equity_session_days: int | None
    calendar_version: str | None
    rule_version: str


class ExpiryCalendarResponse(Contract):
    projection: ExpiryProjectionView | None = None
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
    candidate_date: date | None = None,
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
            # Load the current pinned manifest, then filter each schedule by
            # review date in the calculator. A historical query must not fail
            # solely because another year was reviewed later.
            try:
                equity_calendar = load_calendar()
            except (OSError, ValueError) as exc:
                raise HTTPException(503, "equity calendar authority unavailable") from exc
            projection = (
                project_expiry(candidate_date, cutoff, equity_calendar)
                if candidate_date is not None
                else next_projection(cutoff, equity_calendar)
            )
            candidate_date = projection.nominal_date
            evidence = query_expiry(
                market,
                candidate_date=candidate_date,
                cutoff=cutoff,
                private_use=is_configured_owner(grant.subject_ref),
            )
            sessions = classify_reviewed(candidate_date, evidence, cutoff)
            evidence_views = []
            for record in evidence:
                claim = record.claim
                calendar = (
                    query_calendar(
                        market,
                        source_id=claim.source_id,
                        family=claim.family,
                        contract_ref=claim.contract_ref,
                        cutoff=cutoff,
                        private_use=is_configured_owner(grant.subject_ref),
                    )
                    if claim.contract_ref
                    else None
                )
                evidence_views.append(
                    ReviewedExpiryView.model_validate(
                        {
                            **asdict(record),
                            "calendar_days_to_expiry": calendar_expiry_dte(record, cutoff),
                            "trading_days_to_expiry": product_session_dte(record, calendar, cutoff),
                        }
                    )
                )
    except PermissionError as exc:
        raise HTTPException(401, "session invalid or insufficient scope") from exc
    except PermissionDenied as exc:
        raise HTTPException(403, "market expiry access denied") from exc
    except ValueError as exc:
        raise HTTPException(400, "invalid expiry query") from exc
    except psycopg.Error as exc:
        raise HTTPException(503, "expiry authority unavailable") from exc
    return ExpiryCalendarResponse(
        projection=ExpiryProjectionView.model_validate(asdict(projection)),
        evidence=evidence_views,
        sessions=[
            ExpirySessionView(
                session_date=s.session_date,
                event_type=s.event_type,
                family_status=s.family_status,
                conflicted=s.conflicted,
                **witching_flags(s.event_type),
                calendar_days_to_session=calendar_witching_dte(s, cutoff),
                trading_days_to_session=common_trading_days(s, evidence_views),
            )
            for s in sessions
        ],
        meta=ExpiryMeta(
            request_id=request.state.request_id, as_of=cutoff, candidate_date=candidate_date
        ),
    )


def common_trading_days(
    session: ExpiryClassification,
    evidence: list[ReviewedExpiryView],
) -> int | None:
    """Only publish aggregate DTE if every confirmed contract has the same count."""
    if session.conflicted:
        return None
    if session.event_type not in (Witching.TRIPLE, Witching.QUADRUPLE):
        return None
    counts = [
        row.trading_days_to_expiry
        for row in evidence
        if row.claim.session_date == session.session_date and row.claim.status == FamilyState.YES
    ]
    if not counts or None in counts or len(set(counts)) != 1:
        return None
    return counts[0]
