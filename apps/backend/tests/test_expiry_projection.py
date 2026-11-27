from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from autoaxe.domain.equity_calendar import ReviewedCalendar, load_calendar
from autoaxe.domain.expiry_projection import next_projection, project_expiry


def test_juneteenth_shift():
    result = project_expiry(
        date(2027, 6, 18), datetime(2027, 6, 16, 16, tzinfo=UTC), load_calendar()
    )
    assert result.estimated_date == date(2027, 6, 17)
    assert result.calendar_days == result.equity_session_days == 1


def test_normal_and_uncovered():
    now = datetime(2026, 12, 17, 16, tzinfo=UTC)
    calendar = load_calendar()
    assert project_expiry(date(2026, 12, 18), now, calendar).estimated_date == date(2026, 12, 18)
    assert project_expiry(date(2029, 3, 16), now, calendar).estimated_date is None


def test_consecutive_holidays_and_early_close():
    calendar = load_calendar()
    schedule = calendar.schedules["QLD", 2027]
    # Synthetic exceptional closure on Thursday; Wednesday early close
    # remains an open session. No real exchange closure is asserted.
    schedule = replace(
        schedule,
        holidays=schedule.holidays | {date(2027, 6, 17)},
        early=schedule.early | {date(2027, 6, 16)},
    )
    calendar = ReviewedCalendar({**calendar.schedules, ("QLD", 2027): schedule})
    result = project_expiry(date(2027, 6, 18), datetime(2027, 6, 14, 16, tzinfo=UTC), calendar)
    assert result.estimated_date == date(2027, 6, 16)
    assert result.calendar_days == result.equity_session_days == 2


def test_next_rolls_after_adjusted_date_using_et():
    calendar = load_calendar()
    # UTC is Friday but ET is still Thursday, the adjusted expiry.
    now = datetime(2027, 6, 18, 2, tzinfo=UTC)
    result = next_projection(now, calendar)
    assert result.estimated_date == date(2027, 6, 17)
    assert result.calendar_days == result.equity_session_days == 0
    after = datetime(2027, 6, 18, 4, tzinfo=UTC)
    assert next_projection(after, calendar).nominal_date == date(2027, 9, 17)
    past = project_expiry(date(2027, 6, 18), after, calendar)
    assert past.calendar_days is None and past.equity_session_days is None


def test_cross_year_and_missing_future_coverage():
    calendar = load_calendar()
    result = next_projection(datetime(2026, 12, 31, 16, tzinfo=UTC), calendar)
    assert result.nominal_date == date(2027, 3, 19)
    assert result.calendar_days == 78
    assert result.equity_session_days == 53
    result = next_projection(datetime(2028, 12, 29, 16, tzinfo=UTC), calendar)
    assert result.nominal_date == date(2029, 3, 16)
    assert result.estimated_date is result.calendar_days is result.equity_session_days is None


def test_unavailable_review_and_invalid_input():
    calendar = load_calendar()
    result = project_expiry(date(2027, 6, 18), datetime(2026, 11, 26, 16, tzinfo=UTC), calendar)
    assert result.estimated_date is None
    with pytest.raises(ValueError):
        project_expiry(date(2027, 6, 17), datetime(2027, 6, 16, tzinfo=UTC), calendar)
    with pytest.raises(ValueError):
        next_projection(datetime(2027, 6, 16), calendar)
