"""Offline individual-source lifecycle and wire validation."""

import asyncio
import base64
import importlib
import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from autoaxe.adapters import oil_ws
from autoaxe.application import oil_fallback as worker
from autoaxe.application.collection import FetchError, SourceUnavailable
from autoaxe.domain.catalog import catalog
from autoaxe.domain.market import Quality
from autoaxe.infrastructure.market_store import PermissionDenied

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
MS = int(NOW.timestamp() * 1000) - 100


def primary(oil):
    symbol = oil_ws.OIL[oil][0]
    return oil_ws.primary_candidate(
        oil,
        {
            "stream": symbol.lower() + "@aggTrade",
            "data": {"s": symbol, "e": "aggTrade", "a": 3, "p": "75.1", "q": "2", "T": MS},
        },
        NOW,
    )


def yahoo(oil):
    return oil_ws.yahoo_candidate(
        oil,
        {
            "id": oil_ws.OIL[oil][2],
            "currency": "USD",
            "price": 75.2,
            "time": str(MS),
            "exchange": "fixture",
        },
        NOW,
    )


class DB:
    def __init__(self):
        self.now = NOW
        self.slots = {}
        self.circuits = {}
        self.versions = {"binance_futures": 1, "yfinance": 1}
        self.denied = set()
        self.saved = []
        self.health = []
        self.depth = 0
        self.evidence = "reviewed-provider-grant-fixture"
        self.selections = {}

    @contextmanager
    def transaction(self):
        self.depth += 1
        try:
            yield
        finally:
            self.depth -= 1

    def execute(self, sql, params=None):
        row = None
        if "pg_advisory_xact_lock" in sql:
            assert self.depth
        elif "SELECT clock_timestamp()" in sql:
            row = (self.now,)
        elif "SELECT permission_version,blocked,retry_at" in sql:
            row = self.circuits.get(params[0])
        elif "SELECT last_enqueued_at" in sql:
            stamp = self.slots.get(params[0])
            row = (stamp,) if stamp else None
        elif "INSERT INTO ops.poll_slots" in sql:
            assert self.depth
            self.slots[params[0]] = params[2]
        elif "INSERT INTO ops.poll_circuits" in sql:
            assert self.depth
            self.circuits[params[0]] = params[1:4]
        elif "SELECT series_id,reason FROM market.source_selections" in sql:
            row = self.selections.get(params[0])
        elif "INSERT INTO market.source_selections" in sql:
            self.selections[params[0]] = params[1:]
        else:
            raise AssertionError(sql)
        return SimpleNamespace(fetchone=lambda: row)

    def gate(self, conn, sid, action):
        assert conn is self and action in ("fetch", "storage")
        src = catalog()[sid].source_id
        if src in self.denied:
            raise PermissionDenied("fixture denied")
        return {
            "source_id": src,
            "mapping_version": 1,
            "permission_version": self.versions[src],
            "evidence_ref": self.evidence,
        }


@pytest.fixture
def db(monkeypatch):
    state = DB()
    monkeypatch.setattr(worker, "gate", state.gate)
    monkeypatch.setattr(worker, "ingest", lambda conn, item: state.saved.append(item))
    monkeypatch.setattr(
        worker,
        "record_health",
        lambda conn, sid, status, reason: state.health.append((sid, status, reason)),
    )
    return state


def test_separate_instruments_and_units():
    for oil, (_, primary_sid, symbol, sid) in oil_ws.OIL.items():
        p, y = primary(oil), yahoo(oil)
        assert p.series_id == primary_sid and p.quality == Quality.VALID
        assert p.key == "ws:3" and p.metadata["contiguous_trade_ledger"] is False
        assert y.series_id == sid and y.quality == Quality.UNKNOWN
        assert y.metadata["symbol"] == symbol and y.metadata["contract_month_verified"] is False
        assert catalog()[sid].unit == "USD/bbl" and catalog()[sid].currency == "USD"
        assert catalog()[primary_sid].currency == "USDT"
        assert catalog()[sid].indicator_id != catalog()[primary_sid].indicator_id
        assert catalog()[sid].ttl is None
    assert catalog()["VIX"].ttl == 10


def test_yahoo_pinned_protobuf_decode():
    cls = importlib.import_module("yfinance.pricing_pb2").PricingData
    payload = cls(id="CL=F", currency="USD", time=MS, price=75.25).SerializeToString()
    row = oil_ws.decode_yahoo(json.dumps({"message": base64.b64encode(payload).decode()}))
    assert row is not None
    item = oil_ws.yahoo_candidate("WTI", row, NOW)
    assert item.value == "75.25" and item.source_event_at < NOW
    with pytest.raises(ValueError):
        oil_ws.yahoo_candidate("BRENT", row, NOW)
    with pytest.raises(ValueError):
        oil_ws.yahoo_candidate("WTI", {**row, "currency": "USDT"}, NOW)
    with pytest.raises(ValueError):
        oil_ws.yahoo_candidate("WTI", {**row, "time": str(MS + 500)}, NOW)


@pytest.mark.asyncio
async def test_independent_failure_and_recovery(db):
    active = set()
    order = []
    fail = True

    async def p(oil, permit):
        assert oil not in active and db.slots[oil_ws.OIL[oil][1]]
        permit()
        active.add(oil)
        order.append(("primary_open", oil))
        try:
            await asyncio.sleep(0)
            if oil == "WTI" and fail:
                raise oil_ws.StreamFailure("fixture disconnect")
            yield primary(oil)
        finally:
            active.remove(oil)
            order.append(("primary_closed", oil))

    async def y(oil, permit):
        assert oil == "WTI" and oil not in active
        permit()
        order.append(("fallback_open", oil))
        try:
            yield yahoo(oil)
        finally:
            order.append(("fallback_closed", oil))

    result = await asyncio.gather(
        *[
            worker.run_oil(db, oil, primary=p, fallback=y, yahoo_evidence=db.evidence)
            for oil in oil_ws.OIL
        ]
    )
    assert result == ["fallback_received", "primary_received"]
    assert order.index(("primary_closed", "WTI")) < order.index(("fallback_open", "WTI"))
    assert {x.series_id for x in db.saved} == {
        oil_ws.OIL["WTI"][3],
        oil_ws.OIL["BRENT"][1],
    }
    assert (
        await worker.run_oil(db, "WTI", primary=p, fallback=y, yahoo_evidence=db.evidence)
        == "not_due"
    )
    db.now += timedelta(seconds=60)
    fail = False
    assert (
        await worker.run_oil(db, "WTI", primary=p, fallback=y, yahoo_evidence=db.evidence)
        == "primary_received"
    )
    assert order.count(("fallback_open", "WTI")) == 1
    assert order.index(("fallback_closed", "WTI")) < len(order) - 2
    assert db.saved[-1].series_id == oil_ws.OIL["WTI"][1]


@pytest.mark.parametrize(
    "error,expected",
    [
        (None, "quiet"),
        (ValueError("future source event"), "primary_invalid"),
        (SourceUnavailable("schema"), "primary_invalid"),
        (PermissionDenied("revoked"), "permission_changed"),
        (FetchError(403), "http_error"),
        (FetchError(429, "300"), "http_error"),
        (FetchError(503), "http_error"),
    ],
)
@pytest.mark.asyncio
async def test_not_genuine_individual_failure_no_fallback(db, error, expected):
    async def p(oil, permit):
        permit()
        if error:
            raise error
        if False:
            yield primary(oil)

    async def y(oil, permit):
        pytest.fail("unexpected fallback")
        yield yahoo(oil)

    assert (
        await worker.run_oil(db, "WTI", primary=p, fallback=y, yahoo_evidence=db.evidence)
        == expected
    )
    assert oil_ws.OIL["WTI"][3] not in db.slots and not db.saved


@pytest.mark.asyncio
async def test_fallback_requires_affirmative_matching_evidence_and_revocation(db):
    async def p(oil, permit):
        permit()
        raise oil_ws.StreamFailure("fixture disconnect")
        yield primary(oil)

    async def y(oil, permit):
        permit()
        db.versions["binance_futures"] += 1
        yield yahoo(oil)

    assert await worker.run_oil(db, "WTI", primary=p, fallback=y) == "fallback_unavailable"
    db.now += timedelta(seconds=60)
    assert (
        await worker.run_oil(db, "WTI", primary=p, fallback=y, yahoo_evidence="wrong")
        == "fallback_permission_required"
    )
    db.now += timedelta(seconds=60)
    assert (
        await worker.run_oil(db, "WTI", primary=p, fallback=y, yahoo_evidence=db.evidence)
        == "permission_changed"
    )
    assert not db.saved


@pytest.mark.asyncio
async def test_yahoo_network_default_blocked():
    with pytest.raises(SourceUnavailable, match="affirmative"):
        async for _ in oil_ws.yahoo_quotes("WTI", lambda: None):
            pytest.fail("unauthorized network")
