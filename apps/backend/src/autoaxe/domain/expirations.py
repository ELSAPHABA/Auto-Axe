"""Explicit exchange-session expiration evidence; no naive calendar-day DTE."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from autoaxe.domain.calendars import (
    FAMILIES,
    FamilyState,
    Witching,
    classify_witching,
)
from autoaxe.domain.types import utc_datetime


@dataclass(frozen=True)
class ExpirationEvidence:
    family: Literal["EQUITY_OPTION", "INDEX_OPTION", "INDEX_FUTURE", "SINGLE_STOCK_FUTURE"]
    source_id: str
    contract: str
    nominal_expiration_at: datetime | None
    last_trade_at: datetime | None
    processing_at: datetime | None
    settlement_at: datetime | None
    effective_session_date: date | None
    first_seen_at: datetime
    source_url: str
    status: FamilyState

    def __post_init__(self) -> None:
        if (
            self.family not in FAMILIES
            or not self.contract
            or not self.source_url.startswith("https://")
        ):
            raise ValueError("invalid expiration evidence")
        for stamp in (
            self.nominal_expiration_at,
            self.last_trade_at,
            self.processing_at,
            self.settlement_at,
            self.first_seen_at,
        ):
            if stamp is not None:
                utc_datetime(stamp)
        if self.status == FamilyState.YES and (
            self.effective_session_date is None or self.last_trade_at is None
        ):
            raise ValueError("confirmed expiration needs trading-session evidence")


def trading_session_dte(
    as_of: datetime, effective_session_date: date | None, sessions: list[date]
) -> int | None:
    """Calculate from trusted actual exchange sessions including holiday adjustments."""
    utc_datetime(as_of)
    if effective_session_date is None or not sessions:
        return None
    if sessions != sorted(set(sessions)):
        raise ValueError("sessions must be complete, ordered and distinct")
    # End-of-session interpretation is caller-specific; count future *exchange sessions*.
    return len([day for day in sessions if as_of.date() < day <= effective_session_date])


def classify_expiration(
    evidence: list[ExpirationEvidence], session_date: date
) -> tuple[Witching, dict[str, FamilyState]]:
    """Missing official proof always becomes UNKNOWN, not implicit absence (NO)."""
    states = {family: FamilyState.UNKNOWN for family in FAMILIES}
    for item in evidence:
        if item.effective_session_date != session_date:
            continue
        if states[item.family] not in (FamilyState.UNKNOWN, item.status):
            raise ValueError("conflicting expiration evidence requires review")
        states[item.family] = item.status
    return classify_witching(states), states
