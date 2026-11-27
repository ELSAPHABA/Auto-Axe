"""Rule-based standard expiry estimates, separate from contract evidence."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from autoaxe.domain.calendars import third_friday
from autoaxe.domain.equity_calendar import ReviewedCalendar
from autoaxe.domain.expiry_evidence import ET, check_candidate
from autoaxe.domain.types import utc_datetime

RULE_VERSION = "us_equity_quarterly_previous_session_v1"


@dataclass(frozen=True)
class ExpiryProjection:
    nominal_date: date
    estimated_date: date | None
    calendar_days: int | None
    equity_session_days: int | None
    calendar_version: str | None
    rule_version: str = RULE_VERSION


def project_expiry(nominal: date, as_of: datetime, calendar: ReviewedCalendar) -> ExpiryProjection:
    """Previous open US equity session; early closes count as open.

    This is a standard quarterly estimate, not a futures exchange calendar,
    active contract assertion, or proof of triple/quadruple witching.
    """
    check_candidate(nominal)
    today = utc_datetime(as_of).astimezone(ET).date()
    day = nominal
    try:
        for _ in range(8):
            if calendar.close("QLD", day, as_of=today) is not None:
                break
            day -= timedelta(days=1)
        else:
            raise ValueError("no open session")
        version = calendar.year("QLD", day, as_of=today).version
    except ValueError:
        return ExpiryProjection(nominal, None, None, None, None)
    days = (day - today).days
    count = None
    if 0 <= days <= 3660:
        try:
            count = sum(
                calendar.close("QLD", today + timedelta(days=i), as_of=today) is not None
                for i in range(1, days + 1)
            )
        except ValueError:
            pass
    return ExpiryProjection(nominal, day, days if days >= 0 else None, count, version)


def next_projection(as_of: datetime, calendar: ReviewedCalendar) -> ExpiryProjection:
    """Select by adjusted session, not UTC date or unadjusted Friday.

    If the next candidate lacks verified calendar coverage, return that
    candidate with an unknown estimate rather than skipping unknown dates.
    """
    today = utc_datetime(as_of).astimezone(ET).date()
    for year in range(today.year, min(today.year + 2, 10000)):
        for month in (3, 6, 9, 12):
            nominal = third_friday(year, month)
            if nominal < today:
                continue
            result = project_expiry(nominal, as_of, calendar)
            if result.estimated_date is None or result.estimated_date >= today:
                return result
    raise ValueError("no representable future quarterly candidate")
