"""Point-in-time calendar and evidence-based expiration classification."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from autoaxe.domain.types import decimal_string, utc_datetime

FAMILIES = ("EQUITY_OPTION", "INDEX_OPTION", "INDEX_FUTURE", "SINGLE_STOCK_FUTURE")


class FamilyState(StrEnum):
    YES = "YES"
    NO = "NO"
    UNKNOWN = "UNKNOWN"


class Witching(StrEnum):
    TRIPLE = "TRIPLE_WITCHING"
    QUADRUPLE = "QUADRUPLE_WITCHING"
    PENDING = "PENDING_VERIFICATION"
    NONE = "NONE"


def third_friday(year: int, month: int) -> date:
    if month not in (3, 6, 9, 12):
        raise ValueError("quarter month required")
    first = date(year, month, 1)
    return first + timedelta(days=(4 - first.weekday()) % 7 + 14)


def classify_witching(states: dict[str, FamilyState]) -> Witching:
    if set(states) != set(FAMILIES):
        raise ValueError("four family evidence required")
    core = [states[s] for s in FAMILIES[:3]]
    if FamilyState.NO in core:
        return Witching.NONE
    if FamilyState.UNKNOWN in core or states[FAMILIES[3]] == FamilyState.UNKNOWN:
        return Witching.PENDING
    return Witching.QUADRUPLE if states[FAMILIES[3]] == FamilyState.YES else Witching.TRIPLE


def witching_flags(typ: Witching) -> dict[str, bool | None]:
    if typ == Witching.PENDING:
        return {"is_triple": None, "is_quadruple": None}
    return {"is_triple": typ == Witching.TRIPLE, "is_quadruple": typ == Witching.QUADRUPLE}


@dataclass(frozen=True)
class CalendarEvidence:
    """Literal calendar metadata; a date-only entry is never a release timestamp."""

    title: str | None
    date_only: date | None
    status: Literal["confirmed", "unspecified", "tentative", "cancelled", "unsupported"]

    def __post_init__(self) -> None:
        if self.title is not None and (
            not isinstance(self.title, str)
            or not 1 <= len(self.title) <= 512
            or not self.title.isprintable()
        ):
            raise ValueError("invalid calendar title")
        if self.date_only is not None and type(self.date_only) is not date:
            raise ValueError("invalid calendar date")
        if self.status not in ("confirmed", "unspecified", "tentative", "cancelled", "unsupported"):
            raise ValueError("invalid calendar status")


@dataclass(frozen=True)
class EventRevision:
    event_key: str
    source_id: str
    scheduled_at: datetime | None
    released_at: datetime | None
    first_seen_at: datetime
    available_at: datetime
    actual: str | None
    forecast: str | None
    previous: str | None
    unit: str
    revision: int
    source_url: str
    calendar: CalendarEvidence | None = None

    def __post_init__(self) -> None:
        for stamp in (self.first_seen_at, self.available_at, self.scheduled_at, self.released_at):
            if stamp is not None:
                utc_datetime(stamp)
        if self.available_at < self.first_seen_at:
            raise ValueError("availability before first observation")
        if self.revision <= 0 or not self.event_key or not self.source_url.startswith("https://"):
            raise ValueError("invalid event evidence")
        if self.calendar is not None and (
            self.unit != "event"
            or self.actual is not None
            or self.released_at is not None
            or (self.calendar.date_only is not None and self.scheduled_at is not None)
        ):
            raise ValueError("calendar evidence must describe a schedule only")
        for value in (self.actual, self.forecast, self.previous):
            if value is not None:
                decimal_string(value)


def point_in_time(events: list[EventRevision], cutoff: datetime) -> list[EventRevision]:
    utc_datetime(cutoff)
    result: dict[tuple[str, str], EventRevision] = {}
    for event in events:
        if event.available_at > cutoff:
            continue
        key = (event.source_id, event.event_key)
        old = result.get(key)
        if old is None or event.revision > old.revision:
            result[key] = event
    return sorted(result.values(), key=lambda e: (e.scheduled_at or e.first_seen_at, e.event_key))


@dataclass(frozen=True)
class Guidance:
    accession: str
    cik: str
    fiscal_period: str
    metric: str
    accounting: Literal["GAAP", "ADJUSTED"]
    low: str | None
    high: str | None
    unit: str
    first_seen_at: datetime
    review_status: Literal["manual_review_required", "checked"]
    source_url: str

    def __post_init__(self) -> None:
        utc_datetime(self.first_seen_at)
        if (
            not self.accession
            or not self.fiscal_period
            or not self.source_url.startswith("https://")
        ):
            raise ValueError("missing evidence")
        for value in (self.low, self.high):
            if value is not None:
                decimal_string(value)
        if self.low is not None and self.high is not None:
            if Decimal(self.low) > Decimal(self.high):
                raise ValueError("invalid guidance range")
