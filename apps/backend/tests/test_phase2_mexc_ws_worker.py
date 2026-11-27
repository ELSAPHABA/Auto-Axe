"""Offline durable-session tests using a fake DB and synthetic candidates."""

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from autoaxe.adapters import mexc_ws
from autoaxe.application import mexc_ws_worker as worker
from autoaxe.application.collection import FetchError
from autoaxe.application.polling import CADENCE
from autoaxe.domain.catalog import catalog
from autoaxe.domain.indicator_registry import all_indicators
from autoaxe.domain.market import Quality
from autoaxe.infrastructure.market_store import PermissionDenied

NOW = datetime(2026, 11, 27, 10, tzinfo=UTC)
SID = mexc_ws.SERIES_ID


def item():
    obj = mexc_ws.wrapper_class()(symbol=mexc_ws.SYMBOL, channel=mexc_ws.CHANNEL)
    obj.tickerDetail.symbol = mexc_ws.SYMBOL
    obj.tickerDetail.lastPrice = "27000.125"
    obj.tickerDetail.timestamp = int(NOW.timestamp() * 1000) - 1000
    return mexc_ws.decode_ticker(obj.SerializeToString(), NOW)


class DB:
    def __init__(self):
        self.now = NOW
        self.version = 1
        self.approved = True
        self.mapping = 1
        self.leader = True
        self.slot = None
        self.circuit = None
        self.depth = 0
        self.committed = False
        self.rows = []
        self.health = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    @contextmanager
    def transaction(self):
        self.depth += 1
        try:
            yield
        finally:
            self.depth -= 1
        if self.slot is not None:
            self.committed = True

    def execute(self, sql, params=None):
        row = None
        if "pg_try_advisory_lock" in sql:
            assert "poll:mexc_ws" in sql
            row = (self.leader,)
        elif "pg_advisory_xact_lock" in sql:
            assert self.depth and "source:mexc" in sql
        elif "SELECT clock_timestamp()" in sql:
            row = (self.now,)
        elif "SELECT permission_version,blocked,retry_at" in sql:
            assert "source_id='mexc'" in sql
            row = self.circuit
        elif "SELECT last_enqueued_at" in sql:
            assert params == (SID,)
            row = (self.slot,) if self.slot else None
        elif "INSERT INTO ops.poll_slots" in sql:
            assert self.depth and params[0] == SID
            self.slot = params[2]
            self.committed = False
        elif "INSERT INTO ops.poll_circuits" in sql:
            assert self.depth
            self.circuit = (params[0], True, None) if "invalid_response" in sql else params[:3]
        else:
            raise AssertionError(sql)
        return SimpleNamespace(fetchone=lambda: row)

    def gate(self, conn, sid, action):
        assert conn is self and sid == SID and action in ("fetch", "storage")
        if not self.approved:
            raise PermissionDenied("fixture revoked")
        return {
            "source_id": "mexc",
            "permission_version": self.version,
            "mapping_version": self.mapping,
        }

    def ingest(self, conn, row):
        assert self.depth and self.committed and self.approved and conn is self
        assert row.quality == Quality.UNKNOWN
        assert row.metadata["session_verified"] is False
        if row in self.rows:
            return "fixture", 1, False
        self.rows.append(row)
        return "fixture", 1, True


@pytest.fixture
def db(monkeypatch):
    state = DB()
    monkeypatch.setattr(worker.psycopg, "connect", lambda *a, **kw: state)
    monkeypatch.setattr(worker, "verify_connection", lambda *a, **kw: None)
    monkeypatch.setattr(worker, "gate", state.gate)
    monkeypatch.setattr(worker, "ingest", state.ingest)
    monkeypatch.setattr(
        worker,
        "record_health",
        lambda _, sid, status, reason: state.health.append((sid, status, reason)),
    )
    return state


def test_catalog_separate_series():
    s = catalog()[SID]
    assert s.source_id == "mexc" and s.symbol == mexc_ws.SYMBOL and s.interval == "ticker"
    assert s.id != "NASDAQ100_MEXC_PERP_USDT" and s.ttl is None
    assert SID not in CADENCE
    definition = next(x for x in all_indicators() if x.id == SID)
    assert definition.cadence == "ticker" and "미검증" in definition.note


@pytest.mark.asyncio
async def test_reserve_before_stream_restart_and_duplicates(db):
    calls = []

    async def stream(permit):
        assert db.committed and not db.depth
        permit()
        calls.append(db.now)
        yield item()
        yield item()

    assert await worker.run_session("fixture", stream, enabled=True) == "stored"
    assert db.rows == [item()] and db.health[-1][1] == "unknown"
    db.now += timedelta(seconds=299)
    assert await worker.run_session("fixture", stream, enabled=True) == "not_due"
    db.now += timedelta(seconds=1)
    assert await worker.run_session("fixture", stream, enabled=True) == "no_update"
    db.now += timedelta(days=2)
    assert await worker.run_session("fixture", stream, enabled=True) == "no_update"
    assert len(calls) == 3 and db.slot == db.now


@pytest.mark.asyncio
async def test_disabled_denied_busy_and_stop_no_io(db):
    async def never(_):
        pytest.fail("unexpected provider request")
        yield item()

    with pytest.raises(PermissionDenied):
        await worker.run_session("fixture", never)
    db.approved = False
    assert await worker.run_session("fixture", never, enabled=True) == "permission_required"
    db.approved = True
    db.leader = False
    assert await worker.run_session("fixture", never, enabled=True) == "busy"
    assert (
        await worker.run_session("fixture", never, enabled=True, stopped=lambda: True) == "stopped"
    )
    assert db.slot is None


@pytest.mark.parametrize("change", ["version", "revoked", "mapping", "circuit"])
@pytest.mark.asyncio
async def test_per_message_storage_fence_and_teardown(db, change):
    closed = []

    async def stream(permit):
        try:
            permit()
            yield item()
            if change == "version":
                db.version += 1
            elif change == "revoked":
                db.approved = False
            elif change == "mapping":
                db.mapping = 2
            else:
                db.circuit = (1, True, None)
            yield replace(item(), value="28000")
        finally:
            closed.append(True)

    assert await worker.run_session("fixture", stream, enabled=True) == "permission_changed"
    assert closed == [True] and db.rows == [item()] and db.health[-1][1] == "blocked"


@pytest.mark.asyncio
async def test_stop_during_stream_closes_without_persisting(db):
    stop = False
    closed = []

    async def stream(permit):
        nonlocal stop
        try:
            permit()
            stop = True
            yield item()
        finally:
            closed.append(True)

    assert (
        await worker.run_session("fixture", stream, enabled=True, stopped=lambda: stop) == "stopped"
    )
    assert closed == [True] and not db.rows


@pytest.mark.parametrize(
    "status,header,blocked,seconds",
    [
        (429, "900", False, 900),
        (503, None, False, 300),
        (403, None, True, None),
        (302, None, True, None),
        (429, "1e999", True, None),
    ],
)
@pytest.mark.asyncio
async def test_shared_http_circuit(db, status, header, blocked, seconds):
    calls = []

    async def stream(permit):
        permit()
        calls.append(True)
        raise FetchError(status, header)
        yield item()

    assert await worker.run_session("fixture", stream, enabled=True) == "http_error"
    assert db.circuit == (1, blocked, None if seconds is None else NOW + timedelta(seconds=seconds))
    db.now += timedelta(seconds=300)
    if blocked or seconds > 300:
        assert await worker.run_session("fixture", stream, enabled=True) == "cooldown"
        assert len(calls) == 1
    if seconds and seconds > 300:
        db.version += 1
        assert await worker.run_session("fixture", stream, enabled=True) == "cooldown"
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_circuit_preserves_active_rest_delay(db):
    active = (1, False, NOW + timedelta(hours=4))

    async def stream(permit):
        permit()
        db.circuit = active
        raise FetchError(429, "30")
        yield item()

    assert await worker.run_session("fixture", stream, enabled=True) == "cooldown"
    assert db.circuit == active


@pytest.mark.asyncio
async def test_bad_quality_blocks_no_data_is_unknown(db):
    async def empty(permit):
        permit()
        if False:
            yield item()

    assert await worker.run_session("fixture", empty, enabled=True) == "no_data"
    assert db.health[-1] == (SID, "unknown", "no_ticker_in_bounded_session")
    db.now += timedelta(seconds=300)

    async def invalid(permit):
        permit()
        yield replace(item(), quality=Quality.VALID)

    assert await worker.run_session("fixture", invalid, enabled=True) == "collection_failed"
    assert db.circuit == (1, True, None) and not db.rows
