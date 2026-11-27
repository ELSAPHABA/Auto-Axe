import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from autoaxe.adapters.macro_sources import BEA_ICS
from autoaxe.adapters.official_releases import ECB_KEY, parse_release
from autoaxe.application.official_macro import OfficialSourceError
from autoaxe.application.official_poll import TASKS, fetch_release
from autoaxe.domain.economic_linkage import schedule_identities
from autoaxe.infrastructure.market_store import PermissionDenied

NOW = datetime(2026, 11, 27, tzinfo=UTC)

# Synthetic rows using the publicly documented BEA subscription ICS format.
BEA_FIXTURE = (
    b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID://BEA-Release-Calendar-Subscription//\r\n"
    b"BEGIN:VEVENT\r\nUID:fixture-pce\r\n"
    b"SUMMARY:Personal Income and Outlays\\, October 2026\r\n"
    b"DTSTART;VALUE=DATE-TIME:20261125T133000Z\r\n"
    b"DTSTAMP:20261101T000000Z\r\nSEQUENCE:1\r\nEND:VEVENT\r\n"
    b"BEGIN:VEVENT\r\nUID:fixture-date-only\r\nSUMMARY:Future release\r\n"
    b"DTSTART;VALUE=DATE:20261223\r\nSTATUS:TENTATIVE\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
)


def test_bea_calendar_transport_and_pit(monkeypatch):
    monkeypatch.delenv("AUTOAXE_BEA_API_KEY", raising=False)
    calls = []
    receipts = iter((NOW, NOW + timedelta(seconds=1)))

    def permit():
        calls.append("permit")

    def respond(request):
        assert request.method == "GET" and str(request.url) == BEA_ICS
        assert "text/plain" in request.headers["accept"]
        assert "authorization" not in request.headers
        calls.append("request")
        return httpx.Response(
            200, headers={"content-type": "text/plain; charset=utf-8"}, content=BEA_FIXTURE
        )

    with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False) as client:
        pce, date_only = fetch_release("bea_calendar", client, permit, clock=lambda: next(receipts))
    assert calls == ["permit", "request", "permit"]
    assert TASKS["bea_calendar"].source == "bea" and TASKS["bea_calendar"].seconds == 21600
    assert TASKS["bea_calendar"].key_env is None
    assert pce.source_url == BEA_ICS and pce.event_key == "fixture-pce" and pce.source_id == "bea"
    assert pce.scheduled_at == datetime(2026, 11, 25, 13, 30, tzinfo=UTC)
    assert pce.released_at is None and pce.actual is None and pce.forecast is None
    assert pce.available_at == pce.first_seen_at == NOW + timedelta(seconds=1)
    assert schedule_identities(pce)[0].reference_period == "2026M10"
    assert date_only.scheduled_at is None and date_only.calendar.date_only == date(2026, 12, 23)
    assert date_only.calendar.status == "tentative"


@pytest.mark.parametrize(
    "raw",
    [
        b"<html>error</html>",
        BEA_FIXTURE.replace(b"//BEA-Release-Calendar-Subscription//", b"//Other calendar//"),
        BEA_FIXTURE.replace(b"fixture-date-only", b"fixture-pce"),
        BEA_FIXTURE.replace(b"20261125T133000Z", b"20261125T133000"),
    ],
)
def test_bea_calendar_rejects_untrusted_or_ambiguous_data(raw):
    with pytest.raises(ValueError):
        parse_release("bea_calendar", raw, NOW)


def test_bea_calendar_authorization_and_no_redirect():
    requests = []

    def response(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://example.test/other.ics"})

    def denied():
        raise PermissionDenied("not approved")

    with httpx.Client(transport=httpx.MockTransport(response), trust_env=False) as client:
        with pytest.raises(PermissionDenied):
            fetch_release("bea_calendar", client, denied, clock=lambda: NOW)
        assert not requests
        with pytest.raises(OfficialSourceError) as exc:
            fetch_release("bea_calendar", client, lambda: None, clock=lambda: NOW)
        assert exc.value.status == 302 and requests == [BEA_ICS]
    assert "census_calendar" not in TASKS and "fed_calendar" not in TASKS


def test_bea_contract():
    raw = json.dumps(
        {
            "BEAAPI": {
                "Results": {
                    "Data": [
                        {
                            "TableName": "T10101",
                            "LineNumber": "1",
                            "TimePeriod": "2026Q3",
                            "LineDescription": "Gross domestic product",
                            "DataValue": "2.4",
                        }
                    ]
                }
            }
        }
    )
    row = parse_release("bea_gdp", raw.encode(), NOW)[0]
    assert row.event_key == "US_GDP:2026Q3"
    assert row.actual == "2.4"
    with pytest.raises(ValueError):
        parse_release("bea_pce", raw.encode(), NOW)


def test_ecb_mismatched_key():
    with pytest.raises(ValueError):
        parse_release("ecb_dfr", b"KEY,TIME_PERIOD,OBS_VALUE\nWRONG,2026-11-26,2.0\n", NOW)


def test_rates_and_census():
    ecb = f"KEY,TIME_PERIOD,OBS_VALUE\n{ECB_KEY},2026-11-26,2.0\n".encode()
    assert parse_release("ecb_dfr", ecb, NOW)[0].event_key == "ECB_DFR:2026-11-26"
    assert parse_release("boe_rate", b"DATE,IUDBEDR\n2026-11-26,4.0\n", NOW)[0].actual == "4"
    assert (
        parse_release("fred_lower", b'{"observations":[{"date":"2026-11-26","value":"3.5"}]}', NOW)[
            0
        ].event_key
        == "FED_TARGET_LOWER:2026-11-26"
    )
    raw = json.dumps(
        [
            [
                "cell_value",
                "time",
                "category_code",
                "data_type_code",
                "seasonally_adj",
                "error_data",
            ],
            ["-0.3", "2026-10", "44X72", "MPCSM", "yes", "no"],
        ]
    ).encode()
    assert parse_release("census_retail", raw, NOW)[0].actual == "-0.3"


def test_fixed_transport_and_retry():
    checks = []

    def permit():
        checks.append(True)

    def respond(request):
        assert request.url.host == "data-api.ecb.europa.eu"
        return httpx.Response(
            200,
            headers={"content-type": "text/csv"},
            content=f"KEY,TIME_PERIOD,OBS_VALUE\n{ECB_KEY},2026-11-26,2\n".encode(),
        )

    with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False) as client:
        assert fetch_release("ecb_dfr", client, permit, clock=lambda: NOW)
    assert len(checks) == 2
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(429, headers={"retry-after": "60"})),
        trust_env=False,
    ) as client:
        with pytest.raises(OfficialSourceError) as exc:
            fetch_release("ecb_dfr", client, permit, clock=lambda: NOW)
    assert exc.value.status == 429 and exc.value.retry_header == "60"


def test_boj_effective_is_not_policy_target():
    payload = {
        "STATUS": 200,
        "NEXTPOSITION": None,
        "PARAMETER": {"DB": "FM01"},
        "RESULTSET": [
            {
                "SERIES_CODE": "STRDCLUCON",
                "UNIT": "percent per annum",
                "FREQUENCY": "DAILY",
                "VALUES": {"SURVEY_DATES": [20261125, 20261126], "VALUES": [0.7, None]},
            }
        ],
    }

    def response(request):
        assert request.url.host == "www.stat-search.boj.or.jp"
        assert request.url.path == "/api/v1/getDataCode"
        assert request.url.params["code"] == "STRDCLUCON"
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(response), trust_env=False) as client:
        rows = fetch_release("boj_effective", client, lambda: None, clock=lambda: NOW)
    assert len(rows) == 1
    assert rows[0].event_key == "BOJ_EFFECTIVE_CALL_RATE:2026-11-25"
    assert rows[0].actual == "0.7"
    assert rows[0].released_at is None and rows[0].available_at == NOW
    payload["NEXTPOSITION"] = 1
    with pytest.raises(ValueError):
        parse_release("boj_effective", json.dumps(payload).encode(), NOW)
