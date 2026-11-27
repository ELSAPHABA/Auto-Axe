from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from autoaxe.adapters.macro_sources import (
    normalize_mexc_snapshot,
    normalize_rate_decision,
    parse_bls_actual,
    parse_official_ics,
    parse_sec_atom,
)
from autoaxe.domain.calendars import (
    FamilyState,
    Witching,
    classify_witching,
    point_in_time,
    third_friday,
    witching_flags,
)
from autoaxe.domain.indicator_math import (
    ClosedBar,
    derive_features,
    financial_snapshot,
)
from autoaxe.domain.indicator_registry import all_indicators
from autoaxe.domain.volume import VolumeSampler

NOW = datetime(2026, 11, 26, 20, tzinfo=UTC)


def test_all_indicator_catalog_is_registered_without_claiming_permission():
    rows = all_indicators()
    assert len(rows) >= 90 and len({x.id for x in rows}) == len(rows)
    assert next(x for x in rows if x.id == "NASDAQ100_MEXC_PERP_USDT").source_id == "mexc"
    assert any(x.id == "DRAM_DDR5_RDIMM_AUTO" and x.unit == "unverified" for x in rows)
    pizza = [x for x in rows if "PENTAGON_PIZZA" in x.id or x.source_id == "pizzint"]
    assert len(pizza) == 1
    assert (pizza[0].id, pizza[0].label, pizza[0].unit, pizza[0].cadence) == (
        "PENTAGON_PIZZA_PIZZINT",
        "DOUGHCON",
        "level",
        "10m",
    )


def test_technical_features_no_partial_bars_or_holiday_padding():
    bars = [
        ClosedBar(
            f"2026-{(i // 28) + 1:02d}-{i % 28 + 1:02d}",
            str(100 + i),
            str(101 + i),
            str(99 + i),
            NOW - timedelta(minutes=1),
            True,
            "adjusted",
        )
        for i in range(200)
    ]
    bars.append(ClosedBar("2027-01-01", "999", "1000", "900", NOW, False, "adjusted"))
    result = derive_features(bars, NOW, basis="adjusted")
    assert Decimal(result["SMA_5"].value) == Decimal("297")
    assert result["SMA_200"].quality == "valid"
    assert result["HIGH_20D"].value == "300"
    assert result["LOW_5D"].value == "294"
    assert result["EMA_12"].value is not None
    assert derive_features(bars[:4], NOW, basis="adjusted")["SMA_5"].value is None
    with pytest.raises(ValueError):
        derive_features([bars[0], bars[0]], NOW, basis="adjusted")


def test_financial_valuation_etf_is_never_fabricated():
    raw = {"trailingPE": 20.5, "forwardPE": "12.25", "priceToBook": "NaN", "returnOnEquity": 0.35}
    stock = financial_snapshot("NVDA", "equity", raw, NOW)
    assert stock["metrics"]["roe_ratio"] == "0.35"
    assert stock["metrics"]["pbr"] is None
    assert stock["historical_backfill_valid"] is False
    etf = financial_snapshot("QLD", "etf", raw, NOW)
    assert all(x is None for x in etf["metrics"].values())
    with pytest.raises(ValueError):
        financial_snapshot("QLD", "equity", raw, NOW)


def test_yahoo_volume_local_sampling_not_provider_1hz():
    sampler = VolumeSampler(stale_after_seconds=5)
    assert sampler.sample("NVDA", NOW).status == "no_data"
    message = {
        "id": "NVDA",
        "time": int((NOW - timedelta(seconds=1)).timestamp()),
        "day_volume": "1000",
        "market_hours": "REGULAR",
    }
    assert sampler.observe(message, NOW)
    one = sampler.sample("NVDA", NOW)
    assert one.day_volume == 1000 and one.status == "fresh"
    assert one.delta_since_new_event is None
    two = sampler.sample("NVDA", NOW + timedelta(seconds=1))
    assert two.status == "no_update" and not two.updated_since_previous_sample
    assert sampler.sample("NVDA", NOW + timedelta(seconds=8)).status == "stale"
    sampler.disconnect()
    assert sampler.sample("NVDA", NOW + timedelta(seconds=9)).status == "disconnected"
    sampler.reconnect()
    assert sampler.sample("NVDA", NOW + timedelta(seconds=9)).status == "stale"
    newer = {**message, "time": int(NOW.timestamp()), "day_volume": "800"}
    assert sampler.observe(newer, NOW + timedelta(seconds=1))
    assert sampler.sample("NVDA", NOW + timedelta(seconds=1)).status == "session_reset"
    assert sampler.sample("NVDA", NOW + timedelta(seconds=1)).status == "no_update"
    assert not sampler.observe(message, NOW + timedelta(seconds=2))


def test_economic_actual_and_calendar_revision_pit():
    payload = {
        "status": "REQUEST_SUCCEEDED",
        "Results": {
            "series": [
                {
                    "seriesID": "CUUR0000SA0",
                    "data": [{"year": "2026", "period": "M10", "value": "321.50"}],
                }
            ]
        },
    }
    event = parse_bls_actual(payload, NOW)[0]
    assert event.actual == "321.5" and event.forecast is None
    assert event.scheduled_at is None  # monthly period is NOT release time
    revised = type(event)(
        **{
            **event.__dict__,
            "revision": 2,
            "actual": "321.75",
            "available_at": NOW + timedelta(hours=2),
        }
    )
    assert point_in_time([event, revised], NOW)[0].actual == "321.5"
    assert point_in_time([event, revised], NOW + timedelta(hours=3))[0].actual == "321.75"
    ics = (
        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:release-001\r\n"
        b"DTSTART:20261130T133000Z\r\nSUMMARY:Fixture CPI\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    assert parse_official_ics(ics, NOW, "bls")[0].scheduled_at.hour == 13
    with pytest.raises(ValueError):
        parse_official_ics(ics, NOW, "unknown")


def test_witching_four_family_evidence():
    assert third_friday(2026, 12).isoformat() == "2026-12-18"
    names = ("EQUITY_OPTION", "INDEX_OPTION", "INDEX_FUTURE", "SINGLE_STOCK_FUTURE")
    states = dict(
        zip(
            names,
            (FamilyState.YES, FamilyState.YES, FamilyState.YES, FamilyState.UNKNOWN),
            strict=True,
        )
    )
    assert classify_witching(states) == Witching.PENDING
    assert witching_flags(Witching.PENDING)["is_triple"] is None
    states["SINGLE_STOCK_FUTURE"] = FamilyState.YES
    assert classify_witching(states) == Witching.QUADRUPLE
    states["SINGLE_STOCK_FUTURE"] = FamilyState.NO
    assert classify_witching(states) == Witching.TRIPLE


def test_sec_and_policy_rates_no_free_text_financial_guessing():
    xml = (
        b'<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
        b'<id>fixture</id><title>8-K</title><link href="https://www.sec.gov/Archives/fixture"/>'
        b"</entry></feed>"
    )
    result = parse_sec_atom(xml, NOW)
    assert result[0]["guidance_status"] == "manual_review_required"
    with pytest.raises(ValueError):
        parse_sec_atom(xml.replace(b"www.sec.gov", b"127.0.0.1"), NOW)
    decision = normalize_rate_decision(
        {
            "rate_kind": "ECB_DFR",
            "source_id": "ecb",
            "value": "2.5",
            "published_at": NOW.isoformat(),
            "source_url": "https://www.ecb.europa.eu/",
        },
        NOW,
    )
    assert decision["rate"] == "2.5" and decision["quality"] == "manual_review_required"
    candidate = normalize_mexc_snapshot(
        {"data": {"symbol": "NAS100_USDT", "state": 0}},
        {
            "data": {
                "symbol": "NAS100_USDT",
                "lastPrice": "20001",
                "timestamp": int(NOW.timestamp() * 1000),
            }
        },
        NOW,
    )
    assert candidate["quality"] == "unverified"
