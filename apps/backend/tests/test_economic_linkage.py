"""Synthetic explicit-period calendars; no live calendar or release contract claim."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from autoaxe.adapters.macro_sources import parse_official_ics
from autoaxe.adapters.official_events_api import event_view
from autoaxe.domain.calendars import CalendarEvidence, EventRevision
from autoaxe.domain.economic_linkage import link_actuals, schedule_identities
from autoaxe.infrastructure.event_store import _event_from_row, query_event_links

NOW = datetime(2026, 11, 27, 6, tzinfo=UTC)
SCHEDULED = NOW - timedelta(days=2)
SEEN = NOW - timedelta(days=10)


def actual(source="bls", key="US_CPI:2026-10", unit="index"):
    return EventRevision(
        key,
        source,
        None,
        None,
        NOW,
        NOW,
        "123",
        None,
        None,
        unit,
        1,
        "https://example.test/official",
    )


def schedule(title="Consumer Price Index for October 2026", source="bls", key="calendar-1"):
    return EventRevision(
        key,
        source,
        SCHEDULED,
        None,
        SEEN,
        SEEN,
        None,
        None,
        None,
        "event",
        1,
        "https://example.test/calendar",
        CalendarEvidence(title, None, "confirmed"),
    )


def result(event, schedules, cutoff=NOW, **kwargs):
    return link_actuals([event], schedules, cutoff, **kwargs)[(event.source_id, event.event_key)]


@pytest.mark.parametrize(
    ("source", "key", "unit", "title"),
    [
        ("bls", "US_CPI:2026-10", "index", "Consumer Price Index for October 2026"),
        ("bls", "US_NONFARM_PAYROLL:2026-10", "thousand", "Employment Situation for October 2026"),
        ("bls", "US_UNEMPLOYMENT:2026-10", "percent", "Employment Situation for October 2026"),
        ("bea", "US_GDP:2026Q3", "percent_annual_rate", "Gross Domestic Product, 3rd Quarter 2026"),
        ("bea", "US_PCE:2026M10", "percent_mom", "Personal Income and Outlays, October 2026"),
        (
            "census",
            "US_RETAIL_SALES:2026-10",
            "percent_mom_sa",
            "Advance Monthly Sales for Retail and Food Services, October 2026",
        ),
    ],
)
def test_explicit_same_source_period(source, key, unit, title):
    event = actual(source, key, unit)
    calendar = schedule(title, source)
    linked = result(event, [calendar])
    assert linked.status == "period_match" and linked.schedule == calendar
    view = event_view(event, linked)
    assert view.scheduled_at is None and view.released_at is None
    assert view.period_match.scheduled_at == SCHEDULED
    assert view.actual == "123"


def test_no_fuzzy_cross_source_or_future_match():
    event = actual()
    for candidate in (
        schedule("Consumer Price Index"),
        schedule("Consumer Price Index for October 2026 (revision)"),
        schedule("Consumer Price Index for November 2026"),
        schedule(source="bea"),
        replace(schedule(), scheduled_at=NOW + timedelta(seconds=1)),
        replace(
            schedule(),
            first_seen_at=NOW + timedelta(seconds=1),
            available_at=NOW + timedelta(seconds=1),
        ),
    ):
        assert result(event, [candidate]).status == "unmatched"
    fred = actual("fred", "FED_TARGET_LOWER:2026-11-25", "percent")
    assert result(fred, [schedule("FOMC meeting", "fed")]).status == "not_applicable"
    assert result(replace(event, unit="percent"), [schedule()]).status == "not_applicable"


def test_pit_reschedule_cancellation_and_ambiguous_estimates():
    old = schedule()
    later = NOW + timedelta(days=1)
    cancelled = replace(
        old,
        revision=2,
        first_seen_at=later,
        available_at=later,
        calendar=replace(old.calendar, status="cancelled"),
    )
    assert result(actual(), [old, cancelled]).schedule == old
    assert result(actual(), [old, cancelled], later).status == "unmatched"
    revised = replace(
        old,
        revision=2,
        first_seen_at=later,
        available_at=later,
        scheduled_at=SCHEDULED + timedelta(hours=1),
    )
    assert result(actual(), [old, revised], later).schedule == revised
    assert result(actual(), [old, replace(old, event_key="other")]).status == "ambiguous"
    assert (
        result(actual(), [old], incomplete_sources=frozenset({"bls"})).status
        == "context_incomplete"
    )
    gdp = actual("bea", "US_GDP:2026Q3", "percent_annual_rate")
    advance = schedule("Gross Domestic Product, 3rd Quarter 2026 (Advance Estimate)", "bea")
    second = schedule("Gross Domestic Product, 3rd Quarter 2026 (Second Estimate)", "bea", "second")
    assert result(gdp, [advance, second]).status == "ambiguous"


def test_date_only_and_status_retained_without_midnight_inference():
    raw = (
        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:calendar-1\r\n"
        b"DTSTART;VALUE=DATE:20261125\r\nSUMMARY:Consumer Price Index for October 2026\r\n"
        b"STATUS:CONFIRMED\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    event = parse_official_ics(raw, SEEN, "bls")[0]
    assert event.scheduled_at is None and event.calendar.date_only == date(2026, 11, 25)
    matched = result(actual(), [event])
    assert matched.status == "period_match"
    view = event_view(actual(), matched)
    assert view.period_match.date_only == date(2026, 11, 25)
    assert view.period_match.scheduled_at is None
    recurring = parse_official_ics(
        raw.replace(b"STATUS:CONFIRMED", b"RRULE:FREQ=MONTHLY"), SEEN, "bls"
    )[0]
    assert schedule_identities(recurring) == ()
    cancelled = parse_official_ics(
        raw.replace(b"STATUS:CONFIRMED", b"STATUS:CANCELLED"), SEEN, "bls"
    )[0]
    assert schedule_identities(cancelled) == ()


def test_query_context_reconstructs_provenance_and_does_not_depend_on_page(monkeypatch):
    row = {
        "event_uid": "calendar-1",
        "source_id": "bls",
        "scheduled_at": SCHEDULED,
        "released_at": None,
        "first_seen_at": SEEN,
        "available_at": SEEN,
        "actual": None,
        "forecast": None,
        "previous": None,
        "unit": "event",
        "revision": 1,
        "source_url": "https://example.test/calendar",
        "provenance": {
            "calendar": {
                "title": "Consumer Price Index for October 2026",
                "date_only": None,
                "status": "confirmed",
            }
        },
    }
    assert _event_from_row(row) == schedule()
    assert _event_from_row(row | {"provenance": {}}).calendar is None
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.execute.return_value.fetchall.return_value = [row]
    monkeypatch.setattr(
        "autoaxe.infrastructure.event_store.verify_connection", lambda *a, **k: None
    )
    e = actual()
    links = query_event_links(conn, events=[e], cutoff=NOW, private_use=True)
    assert links[(e.source_id, e.event_key)].schedule == schedule()
    sql, params = cursor.execute.call_args.args
    assert "e.available_at<=%s" in sql and "r.allow_redistribution" in sql
    assert params == ("bls", NOW, True)
    cursor.execute.return_value.fetchall.return_value = [row] * 2001
    assert (
        query_event_links(conn, events=[e], cutoff=NOW)[("bls", e.event_key)].status
        == "context_incomplete"
    )
