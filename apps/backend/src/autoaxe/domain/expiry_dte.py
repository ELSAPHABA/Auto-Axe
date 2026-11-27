"""Date/session DTE only from reviewed, product-specific expiration evidence.

There is deliberately no exchange scraping or guessed session schedule here:
OCC/OIC and CME site terms restrict automated access. The existing reviewed
expiry import is the allowed local boundary. A separately verified complete
product-session calendar can be used by the pure calculator, but no such
calendar is fabricated from a cash-equity holiday schedule.
"""

from dataclasses import dataclass
from datetime import date, datetime

from autoaxe.domain.calendars import FamilyState, Witching
from autoaxe.domain.expiry_evidence import ET, ExpiryClassification, Family, ReviewedExpiry, Source
from autoaxe.domain.types import utc_datetime


@dataclass(frozen=True)
class ProductSessionCalendar:
    """An explicitly reviewed complete session list for one exact contract.

    Completeness and permission evidence are supplied by the verified importer,
    not inferred from the presence of dates or from a different product.
    """

    source_id: Source
    family: Family
    contract_ref: str
    permission_version: int
    coverage_start: date
    coverage_end: date
    sessions: tuple[date, ...]
    available_at: datetime
    evidence_ref: str

    def __post_init__(self) -> None:
        utc_datetime(self.available_at)
        if (
            self.permission_version < 1
            or not self.contract_ref.strip()
            or not self.evidence_ref.strip()
            or self.coverage_end < self.coverage_start
            or tuple(sorted(set(self.sessions))) != self.sessions
            or any(not self.coverage_start <= d <= self.coverage_end for d in self.sessions)
        ):
            raise ValueError("invalid reviewed product session calendar")


def _days(as_of: datetime, day: date | None) -> int | None:
    today = utc_datetime(as_of).astimezone(ET).date()
    return (day - today).days if day is not None and day >= today else None


def calendar_expiry_dte(record: ReviewedExpiry, as_of: datetime) -> int | None:
    """Calendar days to the reviewed effective session (not nominal expiry)."""
    utc_datetime(as_of)
    if record.available_at > as_of or record.claim.status != FamilyState.YES:
        return None
    return _days(as_of, record.claim.session_date)


def product_session_dte(
    record: ReviewedExpiry, calendar: ProductSessionCalendar | None, as_of: datetime
) -> int | None:
    """Count future sessions only if exact scope, PIT and coverage are proved."""
    if calendar_expiry_dte(record, as_of) is None or calendar is None:
        return None
    claim = record.claim
    today = as_of.astimezone(ET).date()
    target = claim.session_date
    if (
        calendar.available_at > as_of
        or calendar.source_id != claim.source_id
        or calendar.family != claim.family
        or calendar.contract_ref != claim.contract_ref
        or calendar.permission_version != record.permission_version
        or calendar.coverage_start > today
        or calendar.coverage_end < target
        or target not in calendar.sessions
    ):
        return None
    return sum(today < day <= target for day in calendar.sessions)


def calendar_witching_dte(session: ExpiryClassification, as_of: datetime) -> int | None:
    """Only a nonconflicting, classified simultaneous expiry has a witching DTE."""
    if session.conflicted or session.event_type not in (Witching.TRIPLE, Witching.QUADRUPLE):
        return None
    return _days(as_of, session.session_date)
