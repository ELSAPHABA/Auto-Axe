"""Offline fixtures reproduce the verified visible government calendar structure."""

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from autoaxe.adapters.official_calendar_html import (
    CENSUS_CALENDAR_URL,
    CENSUS_RETAIL_CALENDAR_URL,
    FED_CALENDAR_URL,
)
from autoaxe.adapters.official_releases import parse_release
from autoaxe.application.official_macro import OfficialSourceError
from autoaxe.application.official_poll import TASKS, fetch_release
from autoaxe.domain.economic_linkage import schedule_identities
from autoaxe.infrastructure.market_store import PermissionDenied

NOW = datetime(2026, 11, 27, 12, tzinfo=UTC)
CENSUS = b"""<html><h3>US Census Bureau: 2027 Economic Indicator Release Schedule: List View</h3>
<table><thead><tr><th>Indicator</th><th>Release Date</th><th>Time</th><th>Period Covered</th>
<th>A202701041000</th><th>A202611</th></tr></thead><tbody>
<tr><td><a href="/construction">Construction Spending (Construction Put in Place)</a></td>
<td>January 4, 2027</td><td>10:00 AM</td><td>November 2026</td>
<td>A202701041000</td><td>A202611</td></tr>
<tr><td>Advance Monthly Sales for Retail and Food Services</td>
<td>January 15, 2027</td><td>8:30 AM</td><td>December 2026</td>
<td>A202701150830</td><td>A202612</td></tr></tbody></table></html>"""
RETAIL = b"""<html><h2>Advance Monthly Retail Trade Report</h2>
<table><tr><th>Data Month</th><th>Release Date at 8:30 am</th></tr>
<tr><td>October 2026</td><td>November 17, 2026</td></tr>
<tr><td>February 2027</td><td>March 16, 2027</td></tr>
<tr><td>December 2027</td><td>To be announced at a later date</td></tr></table>
<h2>Monthly Retail Trade Report</h2><table>
<tr><th>Data Month</th><th>Release Date at 8:30 am for sales and<br>
10:00 am for inventories</th></tr>
<tr><td>October 2026</td><td>December 16, 2026</td></tr></table></html>"""
FED = b"""<html><h4>2026 FOMC Meetings</h4><div>January</div><div>27-28</div>
<div>Statement: <a>HTML</a></div><p>(Released February 18, 2026)</p>
<div>December</div><div>8-9<sup>*</sup></div>
<h4>2025 FOMC Meetings</h4><div>August</div><div>22 (notation vote)</div>
<h4>2027 FOMC Meetings</h4><div>January</div><div>26-27</div>
<p>Note: A two-day meeting is scheduled for January 25-26, 2028.
Each meeting date is tentative until confirmed at the meeting immediately preceding it.</p>
</html>"""


@pytest.mark.parametrize(
    ("task", "url", "source", "raw"),
    [
        ("census_calendar", CENSUS_CALENDAR_URL, "census", CENSUS),
        ("census_retail_calendar", CENSUS_RETAIL_CALENDAR_URL, "census", RETAIL),
        ("fed_calendar", FED_CALENDAR_URL, "fed", FED),
    ],
)
def test_fixed_html_transport_and_receipt(task, url, source, raw):
    calls = []
    times = iter((NOW, NOW + timedelta(seconds=1)))

    def respond(request):
        calls.append("request")
        assert request.method == "GET" and str(request.url) == url
        assert request.headers["accept"] == "text/html"
        return httpx.Response(
            200, content=raw, headers={"content-type": "text/html; charset=UTF-8"}
        )

    with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False) as client:
        rows = fetch_release(
            task, client, lambda: calls.append("permit"), clock=lambda: next(times)
        )
    assert calls == ["permit", "request", "permit"]
    assert TASKS[task].source == source and TASKS[task].seconds == 86400
    assert TASKS[task].key_env is None
    assert rows
    for row in rows:
        assert row.source_id == source and row.source_url == url
        assert row.actual is row.forecast is row.previous is row.released_at is None
        assert row.available_at == row.first_seen_at == NOW + timedelta(seconds=1)


def test_census_general_date_only_retail_not_duplicated():
    rows = parse_release("census_calendar", CENSUS, NOW)
    assert len(rows) == 1
    event = rows[0]
    assert event.calendar.date_only == date(2027, 1, 4)
    assert event.scheduled_at is None
    assert "10:00 AM" in event.calendar.title
    assert schedule_identities(event) == ()
    changed = parse_release(
        "census_calendar", CENSUS.replace(b"January 4, 2027", b"January 5, 2027"), NOW
    )[0]
    assert (
        changed.event_key == event.event_key
        and changed.calendar.date_only != event.calendar.date_only
    )


def test_census_retail_explicit_time_et_dst_and_reference_period():
    rows = parse_release("census_retail_calendar", RETAIL, NOW)
    assert len(rows) == 2
    winter, summer = rows
    assert winter.scheduled_at == datetime(2026, 11, 17, 13, 30, tzinfo=UTC)
    assert summer.scheduled_at == datetime(2027, 3, 16, 12, 30, tzinfo=UTC)
    assert winter.calendar.date_only is None
    assert schedule_identities(winter)[0].reference_period == "2026-10"
    assert schedule_identities(summer)[0].reference_period == "2027-02"


def test_fed_ranges_tentative_not_inferred_decision_timestamp():
    rows = parse_release("fed_calendar", FED, NOW)
    assert len(rows) == 3
    assert rows[0].calendar.date_only == date(2026, 1, 27)
    assert "2026-01-28" in rows[0].calendar.title
    assert rows[2].calendar.date_only == date(2027, 1, 26)
    assert all(row.scheduled_at is None and row.calendar.status == "tentative" for row in rows)
    assert all(schedule_identities(row) == () for row in rows)
    cross = parse_release(
        "fed_calendar", FED.replace(b"January</div><div>27-28", b"Jan/Feb</div><div>31-1"), NOW
    )[0]
    assert cross.calendar.date_only == date(2026, 1, 31)
    assert "2026-02-01" in cross.calendar.title


@pytest.mark.parametrize(
    ("task", "raw"),
    [
        ("census_calendar", CENSUS.replace(b"Period Covered", b"Unknown")),
        ("census_calendar", CENSUS.replace(b"January 4, 2027", b"January 4, 2028")),
        ("census_retail_calendar", RETAIL.replace(b"Release Date at 8:30 am", b"Unknown")),
        ("fed_calendar", FED.replace(b"27-28", b"date unknown")),
        ("fed_calendar", FED.replace(b"Each meeting date is tentative", b"Other calendar")),
        ("fed_calendar", FED.replace(b"December", b"January")),
        ("fed_calendar", b"<html><script>2026 FOMC Meetings</script></html>"),
    ],
)
def test_schema_drift_fails_closed(task, raw):
    with pytest.raises(ValueError):
        parse_release(task, raw, NOW)


def test_html_source_not_called_without_grant_and_redirect_blocked():
    called = []

    def respond(request):
        called.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://example.test/redirect"})

    def denied():
        raise PermissionDenied("not approved")

    with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False) as client:
        with pytest.raises(PermissionDenied):
            fetch_release("fed_calendar", client, denied, clock=lambda: NOW)
        assert called == []
        with pytest.raises(OfficialSourceError):
            fetch_release("fed_calendar", client, lambda: None, clock=lambda: NOW)
    assert called == [FED_CALENDAR_URL]
