import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from autoaxe.adapters import equity_yahoo
from autoaxe.application.equity_worker import run_daily, run_volume, sample_stream
from autoaxe.domain.equity_samples import (
    EquitySampler,
    fundamentals_candidate,
    history_candidates,
    volume_candidate,
)
from autoaxe.domain.market import Quality
from autoaxe.infrastructure.market_store import PermissionDenied

NOW = datetime(2026, 11, 25, 18, tzinfo=UTC)


def tick(volume, *, stamp=NOW, hours="REGULAR", symbol="NVDA"):
    return {
        "id": symbol,
        "day_volume": str(volume),
        "time": str(int(stamp.timestamp() * 1000)),
        "market_hours": hours,
    }


def test_volume_source_and_receive_age_distinct_and_zero_is_not_missing():
    sampler = EquitySampler()
    assert volume_candidate(sampler.sample("NVDA", NOW)).quality == Quality.NO_DATA
    assert sampler.observe(tick(0, stamp=NOW - timedelta(seconds=10)), NOW)
    item = volume_candidate(sampler.sample("NVDA", NOW))
    assert item.value == "0" and item.quality == Quality.STALE
    assert item.metadata["source_age_sec"] == 10
    assert item.metadata["receive_age_sec"] == 0
    assert sampler.observe(tick(30), NOW)
    assert sampler.sample("NVDA", NOW).status == "fresh"
    assert sampler.sample("NVDA", NOW + timedelta(seconds=1)).status == "no_update"
    assert not sampler.observe(tick(10), NOW)
    assert not sampler.observe(tick(20, stamp=NOW + timedelta(seconds=2)), NOW)
    sampler.disconnect()
    assert sampler.sample("NVDA", NOW + timedelta(seconds=1)).status == "disconnected"


def test_market_hours_and_decrease_reset_survives_multiple_ticks():
    sampler = EquitySampler()
    assert sampler.observe(tick(10, hours="PRE"), NOW)
    sampler.sample("NVDA", NOW)
    assert sampler.observe(tick(20, stamp=NOW + timedelta(seconds=1)), NOW + timedelta(seconds=1))
    assert sampler.observe(tick(30, stamp=NOW + timedelta(seconds=2)), NOW + timedelta(seconds=2))
    row = sampler.sample("NVDA", NOW + timedelta(seconds=2))
    assert row.status == "session_reset" and row.delta_since_new_event is None
    assert sampler.observe(tick(1, stamp=NOW + timedelta(seconds=3)), NOW + timedelta(seconds=3))
    assert sampler.sample("NVDA", NOW + timedelta(seconds=3)).status == "session_reset"
    assert not sampler.observe({**tick(4), "day_volume": True}, NOW)
    assert not sampler.observe({**tick(4), "time": True}, NOW)


def test_reconnect_never_revives_stale_cache_before_each_symbol_updates():
    sampler = EquitySampler()
    for symbol in ("NVDA", "QLD"):
        assert sampler.observe(tick(100, symbol=symbol), NOW)
        sampler.sample(symbol, NOW)
    sampler.disconnect()
    sampler.reconnect()
    after = NOW + timedelta(seconds=1)
    assert sampler.sample("NVDA", after).status == "disconnected"
    assert sampler.observe(tick(150, stamp=after), after)
    nvda = sampler.sample("NVDA", after)
    assert nvda.status == "session_reset" and nvda.delta_since_new_event is None
    qld = sampler.sample("QLD", after)
    assert qld.status == "disconnected" and qld.day_volume == 100


def bar(day, close="100", **overrides):
    return {
        "session_at": datetime(2026, 11, day, 5, tzinfo=UTC),
        "open": "100",
        "high": "110",
        "low": "90",
        "close": close,
        "volume": "500",
        **overrides,
    }


def test_history_excludes_current_day_and_never_backdates_availability():
    rows = [bar(d) for d in (18, 19, 20, 23, 24)] + [bar(25, close="9999")]
    result = history_candidates("NVDA", rows, NOW)
    assert len(result) == 5
    assert result[-1].key == "2026-11-24"
    assert result[-1].source_event_at is None
    assert result[-1].available_at == NOW and result[-1].quality == Quality.UNKNOWN
    metadata = result[-1].metadata
    assert metadata["price_basis"] == "adjusted"
    assert metadata["historical_backfill_valid"] is False
    assert metadata["calendar_verified"] is False
    assert metadata["features"]["SMA_5"]["value"] == "100"
    assert metadata["features"]["HIGH_5D"]["value"] == "110"
    assert metadata["features"]["LOW_5D"]["value"] == "90"
    assert metadata["features"]["SMA_200"]["value"] is None
    assert result[0].metadata["features"] == {}
    with pytest.raises(ValueError):
        history_candidates("NVDA", [bar(24), bar(24)], NOW)
    with pytest.raises(ValueError):
        history_candidates("NVDA", [bar(24, volume="NaN")], NOW)
    with pytest.raises(ValueError):
        history_candidates("NVDA", [bar(24, close="111")], NOW)


def test_fundamentals_no_future_backfill_and_etf_no_company_ratio(monkeypatch):
    def unexpected():
        raise AssertionError("ETF corporate ratio must not fetch")

    monkeypatch.setattr(equity_yahoo, "_yahoo", unexpected)
    assert equity_yahoo.fetch_fundamentals("QLD", lambda: None) == {}
    fields = {"trailingPE": 22.5, "returnOnEquity": 0.35, "priceToBook": "NaN"}
    equity = fundamentals_candidate("NVDA", fields, NOW)
    assert equity.quality == Quality.UNKNOWN and equity.value is None
    assert equity.metadata["metrics"]["roe_ratio"] == "0.35"
    assert equity.metadata["metrics"]["pbr"] is None
    assert equity.metadata["historical_backfill_valid"] is False
    etf = fundamentals_candidate("QLD", fields, NOW)
    assert etf.quality == Quality.NO_DATA
    assert all(v is None for v in etf.metadata["metrics"].values())


def test_unverified_daily_http_never_constructs_sdk(monkeypatch):
    def unexpected():
        raise AssertionError("unverified HTTP must not construct SDK")

    monkeypatch.setattr(equity_yahoo, "_yahoo", unexpected)
    for fetch in (equity_yahoo.fetch_daily, equity_yahoo.fetch_fundamentals):
        with pytest.raises(RuntimeError, match="transport not verified"):
            fetch("NVDA", lambda: None)


@pytest.mark.asyncio
async def test_sampler_skips_missed_slots_and_stops_on_permission_change():
    class Clock:
        elapsed = 0

        async def sleep(self, duration):
            self.elapsed += duration
            await asyncio.sleep(0)

    clock = Clock()
    saved = []
    permitted = True
    stopped = False

    def permit():
        if not permitted:
            raise PermissionDenied("revoked")

    async def listen(permit, handle):
        nonlocal stopped
        permit()
        handle(tick(50))
        try:
            await asyncio.Future()
        finally:
            stopped = True

    def save(rows):
        nonlocal permitted
        saved.append(rows)
        if len(saved) == 1:
            clock.elapsed += 2.2
        if len(saved) == 2:
            permitted = False

    with pytest.raises(PermissionDenied):
        await sample_stream(
            listen,
            permit,
            save,
            duration=8,
            clock=lambda: NOW + timedelta(seconds=clock.elapsed),
            monotonic=lambda: clock.elapsed,
            sleep=clock.sleep,
        )
    assert [rows[0].key for rows in saved] == [
        str(int(NOW.timestamp()) + offset) for offset in (1, 4)
    ]
    assert saved[0][0].value == "50" and saved[0][1].value is None
    assert saved[1][0].quality == Quality.NO_UPDATE
    assert stopped


@pytest.mark.asyncio
async def test_clean_listener_exit_records_disconnected():
    async def listen(permit, handle):
        handle(tick(5))

    saved = []

    async def sleep(_duration):
        await asyncio.sleep(0)

    await sample_stream(
        listen,
        lambda: None,
        saved.extend,
        duration=1,
        clock=lambda: NOW,
        sleep=sleep,
    )
    assert len(saved) == 2
    assert all(row.quality == Quality.DISCONNECTED for row in saved)


@pytest.mark.asyncio
async def test_asyncwebsocket_adapter_single_receive_and_cleanup(monkeypatch):
    received = []
    actions = []

    class FakeSocket:
        async def recv(self):
            if not received:
                return json.dumps({"message": "fixture"})
            raise ConnectionError("fixture close")

    class FakeWebSocket:
        def __init__(self, *, verbose):
            assert verbose is False
            self._ws = FakeSocket()

        async def subscribe(self, symbols):
            actions.append(("subscribe", symbols))
            self._heartbeat_task = asyncio.create_task(asyncio.sleep(100))

        def _decode_message(self, encoded):
            assert encoded == "fixture"
            return tick(33)

        async def close(self):
            actions.append("closed")

    monkeypatch.setattr(
        equity_yahoo, "_yahoo", lambda: SimpleNamespace(AsyncWebSocket=FakeWebSocket)
    )
    with pytest.raises(ConnectionError):
        await equity_yahoo.listen_volume(lambda: actions.append("permit"), received.append)
    assert received == [tick(33)]
    assert ("subscribe", ["NVDA", "QLD"]) in actions
    assert actions[-1] == "closed"


@pytest.mark.asyncio
async def test_network_and_db_default_off():
    with pytest.raises(PermissionDenied):
        await run_volume("invalid-dsn")
    with pytest.raises(PermissionDenied):
        run_daily("invalid-dsn")
