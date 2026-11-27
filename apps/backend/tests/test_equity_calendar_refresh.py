"""No official site is contacted: source captures and reviews use fixtures."""

import hashlib
import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from autoaxe.adapters.equity_calendar_html import NASDAQ_NAMES, extract_years
from autoaxe.application.equity_calendar_refresh import draft_summary, publish_reviewed, refresh
from autoaxe.domain.equity_calendar import (
    ARCA_VERSION,
    CALENDAR_VERSION,
    SOURCE_URLS,
    load_calendar,
    scheduled_close,
)
from autoaxe.domain.equity_samples import history_candidates

NOW = datetime(2026, 11, 27, 10, tzinfo=UTC)


def nasdaq_fixture(year=2027):
    # Synthetic dates for parser tests only, not official Nasdaq 2027 evidence.
    dates = (
        (
            "January 1",
            "January 18",
            "February 15",
            "March 26",
            "May 31",
            "June 18",
            "July 5",
            "September 6",
            "November 25",
            "December 24",
        )
        if year == 2027
        else (
            "January 1",
            "January 19",
            "February 16",
            "April 3",
            "May 25",
            "June 19",
            "July 3",
            "September 7",
            "November 26",
            "December 25",
        )
    )
    rows = "".join(
        f"<tr><td>{day}, {year}</td><td>{label}</td><td>Closed</td></tr>"
        for day, label in zip(dates, NASDAQ_NAMES, strict=True)
    )
    early = ["November 26"] if year == 2027 else ["November 27", "December 24"]
    rows += "".join(
        f"<tr><td>{day}, {year}</td><td>Early Close* - U.S.</td><td>1:00 p.m.</td></tr>"
        for day in early
    )
    return (
        f"<h1>U.S. Equity and Options Markets Holiday Schedule {year}</h1>"
        f"<table><tr><th>{year}</th><th>Holiday</th><th>Status</th></tr>{rows}</table>"
        "<p>* Nasdaq will continue to send alerts on dates the Market will close early.</p>"
    ).encode()


BODY = nasdaq_fixture()
SHA = hashlib.sha256(BODY).hexdigest()


class Stream(httpx.SyncByteStream):
    def __iter__(self):
        yield BODY


def fixture_row(**overrides):
    # Synthetic operator review input: these dates are not a Nasdaq seed.
    return {
        "symbol": "NVDA",
        "year": 2027,
        "source_url": SOURCE_URLS["NVDA"],
        "evidence_sha256": SHA,
        "reviewed_on": "2026-11-27",
        "reviewer_ref": "offline-test",
        "complete": True,
        "holidays": [
            "2027-01-01",
            "2027-01-18",
            "2027-02-15",
            "2027-03-26",
            "2027-05-31",
            "2027-06-18",
            "2027-07-05",
            "2027-09-06",
            "2027-11-25",
            "2027-12-24",
        ],
        "early_closes": ["2027-11-26"],
    } | overrides


def draft_file(root, rows):
    path = root / "draft.json"
    raw = json.dumps({"schema_version": 1, "years": rows}).encode()
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def test_seed_arca_future_only_no_nasdaq_extrapolation():
    calendar = load_calendar()
    assert calendar.year("QLD", date(2026, 12, 24)).version == CALENDAR_VERSION
    assert calendar.year("QLD", date(2027, 11, 26)).version == ARCA_VERSION
    assert scheduled_close("QLD", date(2027, 6, 18)) is None
    assert scheduled_close("QLD", date(2027, 12, 24)) is None
    assert scheduled_close("QLD", date(2027, 11, 26)) == datetime(2027, 11, 26, 18, tzinfo=UTC)
    assert scheduled_close("QLD", date(2028, 7, 3)) == datetime(2028, 7, 3, 17, tzinfo=UTC)
    assert scheduled_close("QLD", date(2027, 12, 31)) == datetime(2027, 12, 31, 21, tzinfo=UTC)
    with pytest.raises(ValueError, match="unverified"):
        scheduled_close("NVDA", date(2027, 1, 4))
    with pytest.raises(ValueError, match="unverified"):
        scheduled_close("QLD", date(2029, 1, 2))


def test_refresh_reserves_before_io_and_review_requires_pinned_manifest(tmp_path, monkeypatch):
    calls = []

    def handler(request):
        assert str(request.url) == SOURCE_URLS["NVDA"]
        assert request.method == "GET"
        state = json.loads((tmp_path / "NVDA-refresh.json").read_text())
        assert state["status"] == "reserved"
        calls.append(request)
        return httpx.Response(200, stream=Stream(), headers={"Content-Type": "text/html"})

    transport = httpx.MockTransport(handler)
    with pytest.raises(ValueError, match="opt-in"):
        refresh(tmp_path, "NVDA", transport=transport)
    assert refresh(tmp_path, "NVDA", enabled=True, transport=transport, now=NOW) == "pending_review"
    assert (tmp_path / f"NVDA-{SHA}.html").read_bytes() == BODY
    summary = draft_summary(tmp_path, "NVDA")
    assert summary is not None
    automatic, parsed = summary
    assert parsed[0]["reviewer_ref"] is None and parsed[0]["reviewed_on"] is None
    assert parsed[0]["holidays"] == fixture_row()["holidays"]
    with pytest.raises(ValueError):
        load_calendar(automatic, hashlib.sha256(automatic.read_bytes()).hexdigest())
    assert (
        refresh(tmp_path, "NVDA", enabled=True, transport=transport, now=NOW + timedelta(hours=23))
        == "not_due"
    )
    assert len(calls) == 1
    with pytest.raises(ValueError):
        scheduled_close("NVDA", date(2027, 1, 4))
    draft, digest = draft_file(tmp_path, [fixture_row()])
    with pytest.raises(ValueError, match="approval"):
        publish_reviewed(tmp_path, draft)
    # Simulate the trusted reviewer explicitly promoting the test fixture.
    path, reviewed_hash = publish_reviewed(tmp_path, draft, enabled=True)
    assert digest == reviewed_hash and path.name == f"reviewed-{digest}.json"
    reviewed, auto_digest = publish_reviewed(
        tmp_path, automatic, enabled=True, reviewer_ref="fixture-reviewer"
    )
    assert load_calendar(reviewed, auto_digest).year("NVDA", date(2027, 1, 4))
    monkeypatch.setenv("AUTOAXE_EQUITY_CALENDAR_MANIFEST", str(path))
    monkeypatch.setenv("AUTOAXE_EQUITY_CALENDAR_SHA256", digest)
    calendar = load_calendar()
    version = calendar.year("NVDA", date(2027, 1, 4)).version
    assert version.startswith("reviewed_NVDA_2027_")
    assert scheduled_close("NVDA", date(2027, 1, 4)) == datetime(2027, 1, 4, 21, tzinfo=UTC)
    # Manifest affects history through default loader, without changing old bars.
    rows = [
        {
            "session_at": datetime(y, m, d, 12, tzinfo=UTC),
            "open": "100",
            "high": "110",
            "low": "90",
            "close": "105",
            "volume": "500",
            "provider_final": True,
        }
        for y, m, d in [(2026, 12, 31), (2027, 1, 4)]
    ]
    result = history_candidates("NVDA", rows, datetime(2027, 1, 4, 22, tzinfo=UTC))
    assert [x.metadata["calendar_version"] for x in result] == [CALENDAR_VERSION, version]
    assert all(x.metadata["historical_backfill_valid"] is False for x in result)
    with pytest.raises(ValueError, match="hash"):
        load_calendar(path, "0" * 64)
    path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash"):
        load_calendar()


def test_nasdaq_2026_verified_shape_and_missing_rows():
    body = nasdaq_fixture(2026)
    year = extract_years("NVDA", body)[0]
    assert len(year.holidays) == 10
    assert year.early_closes == ("2026-11-27", "2026-12-24")
    for bad in (
        body.replace(b"Good Friday", b"Unknown holiday"),
        body.replace(b"1:00 p.m.", b"2:00 p.m."),
        body.replace(b"December 24, 2026", b"December 24, 2027"),
        body.replace(b"U.S. Equity and Options Markets", b"Other Market"),
    ):
        with pytest.raises(ValueError):
            extract_years("NVDA", bad)


def test_nyse_visible_table_and_footnotes():
    from autoaxe.adapters.equity_calendar_html import HOLIDAYS

    cells = [
        ("Thursday, January 1", "Friday, January 1", "—*"),
        ("Monday, January 19", "Monday, January 18", "Monday, January 17"),
        ("Monday, February 16", "Monday, February 15", "Monday, February 21"),
        ("Friday, April 3", "Friday, March 26", "Friday, April 14"),
        ("Monday, May 25", "Monday, May 31", "Monday, May 29"),
        (
            "Friday, June 19",
            "Friday, June 18 (Juneteenth National Independence Day observed)",
            "Monday, June 19",
        ),
        (
            "Friday, July 3 (Independence Day observed)",
            "Monday, July 5 (Independence Day observed)",
            "Tuesday, July 4**",
        ),
        ("Monday, September 7", "Monday, September 6", "Monday, September 4"),
        ("Thursday, November 26***", "Thursday, November 25***", "Thursday, November 23***"),
        (
            "Friday, December 25****",
            "Friday, December 24 (Christmas Day observed)",
            "Monday, December 25",
        ),
    ]
    rows = "".join(
        "<tr>" + "".join(f"<td>{value}</td>" for value in (name, *values)) + "</tr>"
        for name, values in zip(HOLIDAYS, cells, strict=True)
    )
    prefix = "Each market will close early at 1:00 p.m. (1:15 p.m. for eligible options) on "
    end = ". NYSE American Equities, NYSE Arca Equities late trading sessions close later. "
    end += "All times are Eastern Time."
    body = (
        "<h4>All NYSE markets observe U.S. holidays as listed below for 2026, 2027, and 2028.</h4>"
        "<table><tr><th>Holiday</th><th>2026</th><th>2027</th><th>2028</th></tr>"
        + rows
        + "</table>"
        "<p>* Because the holiday falls on Saturday, January 1, 2028, "
        "no New Year’s Day holiday is observed.</p>"
        f"<p>** {prefix}Monday, July 3, 2028{end}</p>"
        f"<p>*** {prefix}Friday, November 27, 2026, Friday, November 26, 2027, "
        f"and Friday, November 24, 2028 (the day after Thanksgiving){end}</p>"
        f"<p>**** {prefix}Thursday, December 24, 2026{end}</p>"
    ).encode()
    a, b, c = extract_years("QLD", body)
    assert a.early_closes == ("2026-11-27", "2026-12-24")
    assert b.early_closes == ("2027-11-26",)
    assert c.early_closes == ("2028-07-03", "2028-11-24") and len(c.holidays) == 9
    for bad in (
        body.replace(b"Friday, November 26, 2027", b""),
        body.replace(b"Thursday, November 25***", b""),
        body.replace(b"Monday, July 3, 2028", b"Sunday, July 3, 2028"),
        body.replace(b"1:00 p.m.", b"2:00 p.m."),
    ):
        with pytest.raises(ValueError):
            extract_years("QLD", bad)


@pytest.mark.parametrize("status", [403, 302, 429])
def test_error_no_redirect_or_evasion_and_durable_cooldown(tmp_path, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status,
            headers={
                "Location": "https://example.com",
                "Retry-After": "172800",
            },
        )

    transport = httpx.MockTransport(handler)
    assert refresh(tmp_path, "QLD", enabled=True, transport=transport, now=NOW) == f"http_{status}"
    assert refresh(
        tmp_path, "QLD", enabled=True, transport=transport, now=NOW + timedelta(days=1)
    ) == ("not_due" if status == 429 else "blocked")
    assert len(calls) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"year": 2026},
        {"complete": False},
        {"source_url": "https://example.com"},
        {"reviewer_ref": ""},
        {"holidays": []},
        {"early_closes": ["2027-01-01"]},
        {"early_closes": ["2027-11-27"]},
        {"reviewed_on": "2099-01-01"},
    ],
)
def test_manifest_invalid_or_incomplete_rejected(tmp_path, change):
    path, digest = draft_file(tmp_path, [fixture_row(**change)])
    with pytest.raises(ValueError):
        load_calendar(path, digest, as_of=NOW.date())


def test_gap_and_unmatched_evidence_rejected(tmp_path):
    row = fixture_row(
        year=2028,
        holidays=[v.replace("2027", "2028") for v in fixture_row()["holidays"]],
        early_closes=[],
    )
    path, digest = draft_file(tmp_path, [row])
    with pytest.raises(ValueError):
        load_calendar(path, digest)
    path, _ = draft_file(tmp_path, [fixture_row()])
    with pytest.raises(OSError):
        publish_reviewed(tmp_path, path, enabled=True)
