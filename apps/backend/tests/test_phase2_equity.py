import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from autoaxe.adapters import equity_yahoo
from autoaxe.application.equity_worker import run_daily, run_volume, sample_stream
from autoaxe.domain.equity_calendar import CALENDAR_VERSION, scheduled_close
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
        "provider_final": True,
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
    assert metadata["calendar_verified"] is True
    assert metadata["calendar_version"] == CALENDAR_VERSION
    assert metadata["provider_final"] is True
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


@pytest.mark.parametrize("symbol", ["NVDA", "QLD"])
def test_official_regular_session_calendar(symbol):
    assert scheduled_close(symbol, date(2025, 1, 9)) is None
    assert scheduled_close(symbol, date(2026, 11, 26)) is None
    assert scheduled_close(symbol, date(2026, 11, 28)) is None
    assert scheduled_close(symbol, date(2026, 11, 27)) == datetime(2026, 11, 27, 18, tzinfo=UTC)
    assert scheduled_close(symbol, date(2026, 7, 2)) == datetime(2026, 7, 2, 20, tzinfo=UTC)
    assert scheduled_close(symbol, date(2026, 7, 3)) is None
    assert scheduled_close(symbol, date(2024, 7, 3)) == datetime(2024, 7, 3, 17, tzinfo=UTC)
    with pytest.raises(ValueError, match="unverified equity calendar"):
        scheduled_close(symbol, date(2027, 1, 4))


def test_daily_requires_finality_and_regular_close():
    close = datetime(2026, 11, 27, 18, tzinfo=UTC)
    assert history_candidates("NVDA", [bar(27)], close - timedelta(seconds=1)) == []
    assert history_candidates("NVDA", [bar(27, provider_final=False)], close) == []
    assert history_candidates("NVDA", [bar(25, provider_final=1)], close) == []
    no_flag = bar(25)
    del no_flag["provider_final"]
    assert history_candidates("NVDA", [no_flag], close) == []
    rows = history_candidates("NVDA", [bar(25), bar(27)], close + timedelta(seconds=1))
    assert len(rows) == 2
    assert rows[-1].metadata["scheduled_close_utc"] == "2026-11-27T18:00:00Z"
    assert rows[-1].source_event_at is None
    assert rows[-1].available_at == close + timedelta(seconds=1)
    assert rows[-1].quality == Quality.UNKNOWN
    with pytest.raises(ValueError, match="invalid or duplicate daily session"):
        history_candidates("NVDA", [bar(26)], close)
    with pytest.raises(ValueError, match="unverified equity calendar"):
        history_candidates("NVDA", [], datetime(2027, 1, 4, 18, tzinfo=UTC))


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
        calls = []
        with pytest.raises(equity_yahoo.DailyTransportUnavailable, match="transport not verified"):
            fetch("NVDA", lambda calls=calls: calls.append("permit"))
        assert calls == ["permit"]

        def revoked():
            raise PermissionDenied("revoked")

        with pytest.raises(PermissionDenied, match="revoked"):
            fetch("NVDA", revoked)


def test_disabled_daily_worker_never_connects_or_reserves(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("disabled daily worker must not open DB or network")

    monkeypatch.setattr("autoaxe.application.equity_worker.psycopg.connect", unexpected)
    monkeypatch.setattr(equity_yahoo, "_yahoo", unexpected)
    for continuous in (False, True):
        with pytest.raises(equity_yahoo.DailyTransportUnavailable):
            run_daily("invalid-dsn", enabled=True, continuous=continuous)


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
