"""Offline lifecycle and policy tests; injected fetch never calls MEXC."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from autoaxe.adapters.mexc_rest import SERIES_ID
from autoaxe.application import mexc_poll
from autoaxe.application.collection import FetchError
from autoaxe.application.polling import CADENCE
from autoaxe.domain.catalog import catalog
from autoaxe.domain.indicator_registry import all_indicators
from autoaxe.domain.market import Candidate, Quality
from autoaxe.infrastructure.market_store import PermissionDenied

NOW = datetime(2026, 11, 27, 10, tzinfo=UTC)


def candidate(**overrides):
    fields = {
        "series_id": SERIES_ID,
        "key": "1795773599000",
        "value": "28000.1",
        "source_event_at": NOW - timedelta(seconds=1),
        "received_at": NOW,
        "available_at": NOW,
        "quality": Quality.UNKNOWN,
        "metadata": {
            "symbol": "NAS100_USDT",
            "instrument_type": "index_linked_perpetual",
            "quote_currency": "USDT",
            "settlement_currency": "USDT",
            "contract_id": 123,
            "contract_size": "0.01",
            "price_unit": "0.1",
            "contract_detail_received_at": NOW.isoformat(),
            "provenance": "mexc_futures_rest_candidate",
            "session_verified": False,
            "live_verified": False,
        },
    }
    return Candidate(**(fields | overrides))


class FakeDB:
    def __init__(self):
        self.now = NOW
        self.version = 1
        self.approved = True
        self.mapping = 1
        self.leader = True
        self.slot = None
        self.circuit = None
        self.health = []
        self.stored = []
        self.transaction_depth = 0
        self.reservation_committed = False
        self.events = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    @contextmanager
    def transaction(self):
        self.transaction_depth += 1
        try:
            yield
        finally:
            self.transaction_depth -= 1
        if self.slot is not None:
            self.reservation_committed = True

    def execute(self, query, params=None):
        row = None
        if "pg_try_advisory_lock" in query:
            row = (self.leader,)
        elif "pg_advisory_xact_lock" in query:
            assert self.transaction_depth
        elif "SELECT clock_timestamp()" in query:
            row = (self.now,)
        elif "SELECT permission_version,blocked,retry_at" in query:
            row = self.circuit
        elif "SELECT last_enqueued_at" in query:
            row = (self.slot,) if self.slot else None
        elif "INSERT INTO ops.poll_slots" in query:
            assert self.transaction_depth
            assert params[0] == SERIES_ID
            self.slot = params[2]
            self.reservation_committed = False
        elif "INSERT INTO ops.poll_circuits" in query:
            assert self.transaction_depth
            self.circuit = (params[0], True, None) if "invalid_response" in query else params[:3]
        else:
            raise AssertionError(query)
        return SimpleNamespace(fetchone=lambda: row)

    def gate(self, conn, series, action):
        assert conn is self and series == SERIES_ID
        assert action in ("fetch", "storage")
        self.events.append(action)
        if not self.approved:
            raise PermissionDenied("revoked")
        return {
            "source_id": "mexc",
            "permission_version": self.version,
            "mapping_version": self.mapping,
        }

    def ingest(self, conn, item):
        assert conn is self and self.transaction_depth
        assert self.reservation_committed
        assert self.approved
        assert item.quality == Quality.UNKNOWN
        assert "contract_detail_received_at" not in item.metadata
        inserted = not any(
            old.key == item.key and old.value == item.value and old.metadata == item.metadata
            for old in self.stored
        )
        if inserted:
            self.stored.append(item)
        return "fixture", 1, inserted


@pytest.fixture
def db(monkeypatch):
    state = FakeDB()
    monkeypatch.setattr(mexc_poll.psycopg, "connect", lambda *a, **kw: state)
    monkeypatch.setattr(mexc_poll, "verify_connection", lambda conn, **kw: None)
    monkeypatch.setattr(mexc_poll, "gate", state.gate)
    monkeypatch.setattr(mexc_poll, "ingest", state.ingest)
    monkeypatch.setattr(
        mexc_poll,
        "record_health",
        lambda conn, sid, status, reason: state.health.append((sid, status, reason)),
    )
    return state


def test_catalog_registered_only_dedicated_scheduler():
    series = catalog()[SERIES_ID]
    assert series.source_id == "mexc" and series.interval == "snapshot"
    assert series.ttl is None and series.unit == "USDT/contract"
    assert SERIES_ID not in CADENCE
    entry = next(i for i in all_indicators() if i.id == SERIES_ID)
    assert entry.cadence == "5m" and "미검증" in entry.note


@pytest.mark.asyncio
async def test_disabled_and_denied_no_fetch(db):
    async def fetch(_permit):
        pytest.fail("unexpected provider call")

    with pytest.raises(PermissionDenied):
        await mexc_poll.poll_once("fixture", fetch)
    db.approved = False
    assert await mexc_poll.poll_once("fixture", fetch, enabled=True) == "permission_required"
    assert db.slot is None
    db.approved = True
    db.leader = False
    assert await mexc_poll.poll_once("fixture", fetch, enabled=True) == "busy"
    assert db.slot is None


@pytest.mark.asyncio
async def test_reserve_commits_before_io_restart_no_catchup_and_dedup(db):
    calls = []

    async def fetch(permit):
        assert db.reservation_committed and db.transaction_depth == 0
        permit()
        calls.append(db.now)
        permit()
        item = candidate()
        return candidate(
            metadata=item.metadata | {"contract_detail_received_at": db.now.isoformat()}
        )

    assert await mexc_poll.poll_once("fixture", fetch, enabled=True) == "stored"
    assert db.slot == NOW and db.health[-1][1] == "unknown"
    db.now += timedelta(seconds=299)
    assert await mexc_poll.poll_once("fixture", fetch, enabled=True) == "not_due"
    db.now += timedelta(seconds=1)
    assert await mexc_poll.poll_once("fixture", fetch, enabled=True) == "no_update"
    db.now += timedelta(days=2)
    assert await mexc_poll.poll_once("fixture", fetch, enabled=True) == "no_update"
    assert len(calls) == 3 and len(db.stored) == 1 and db.slot == db.now


@pytest.mark.parametrize("change", ["version", "revocation", "circuit", "mapping"])
@pytest.mark.asyncio
async def test_storage_fence_even_if_transport_returns_after_revocation(db, change):
    async def fetch(permit):
        permit()
        if change == "version":
            db.version += 1
        elif change == "revocation":
            db.approved = False
        elif change == "circuit":
            db.circuit = (db.version, True, None)
        else:
            db.mapping = 2
        return candidate()

    assert await mexc_poll.poll_once("fixture", fetch, enabled=True) == "permission_changed"
    assert db.slot == NOW and db.stored == []
    assert db.health[-1][1] == "blocked"


@pytest.mark.parametrize(
    "status,header,blocked,seconds",
    [
        (429, "900", False, 900),
        (503, None, False, 300),
        (403, None, True, None),
        (302, None, True, None),
        (429, "1e999", True, None),
        (429, "99999999", True, None),
    ],
)
@pytest.mark.asyncio
async def test_durable_http_circuit(db, status, header, blocked, seconds):
    calls = 0

    async def fetch(permit):
        nonlocal calls
        permit()
        calls += 1
        raise FetchError(status, header)

    assert await mexc_poll.poll_once("fixture", fetch, enabled=True) == "http_error"
    assert db.circuit == (1, blocked, None if seconds is None else NOW + timedelta(seconds=seconds))
    db.now += timedelta(seconds=300)
    if blocked or seconds > 300:
        assert await mexc_poll.poll_once("fixture", fetch, enabled=True) == "cooldown"
        assert calls == 1
    # A new approval cannot shorten a pending Retry-After.
    if seconds and seconds > 300:
        db.version += 1
        assert await mexc_poll.poll_once("fixture", fetch, enabled=True) == "cooldown"
        assert calls == 1
    if blocked:
        db.version += 1
        assert await mexc_poll.poll_once("fixture", fetch, enabled=True) == "http_error"
        assert calls == 2


@pytest.mark.asyncio
async def test_wrong_quality_and_transport_failure(db):
    async def wrong(permit):
        permit()
        return candidate(quality=Quality.VALID)

    assert await mexc_poll.poll_once("fixture", wrong, enabled=True) == "collection_failed"
    assert db.circuit == (1, True, None)
    assert db.health[-1][1] == "schema_error" and not db.stored
    db.version = 2
    db.now += timedelta(seconds=300)

    async def broken(permit):
        permit()
        raise httpx.ConnectError("fixture")

    assert await mexc_poll.poll_once("fixture", broken, enabled=True) == "collection_failed"
    assert db.health[-1][1] == "disconnected" and not db.stored
