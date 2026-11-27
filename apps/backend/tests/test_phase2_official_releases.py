import json
from datetime import UTC, datetime

import httpx
import pytest

from autoaxe.adapters.official_releases import ECB_KEY, parse_release
from autoaxe.application.official_macro import OfficialSourceError
from autoaxe.application.official_poll import fetch_release

NOW = datetime(2026, 11, 27, tzinfo=UTC)


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
