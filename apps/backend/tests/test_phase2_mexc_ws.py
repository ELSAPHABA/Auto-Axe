"""Synthetic wire fixtures from pinned upstream descriptor; no provider I/O."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from autoaxe.adapters import mexc_ws as ws
from autoaxe.application.collection import SourceUnavailable
from autoaxe.domain.market import Quality
from autoaxe.infrastructure.market_store import PermissionDenied

NOW = datetime(2026, 11, 27, 10, tzinfo=UTC)
MS = int(NOW.timestamp() * 1000) - 1000


def varint(value):
    data = bytearray()
    while value >= 128:
        data.append((value & 127) | 128)
        value >>= 7
    data.append(value)
    return bytes(data)


def text_field(field, value):
    data = value.encode() if isinstance(value, str) else value
    return varint(field * 8 + 2) + varint(len(data)) + data


def int_field(field, value):
    return varint(field * 8) + varint(value)


def wire(symbol=ws.SYMBOL, channel=ws.CHANNEL, inner=ws.SYMBOL, price="27000.125", ms=MS):
    ticker = text_field(1, inner) + text_field(2, price) + int_field(12, ms)
    return text_field(1, symbol) + text_field(2, channel) + text_field(2017, ticker)


def test_original_source_hashes_and_complete_compiled_descriptor():
    manifest = json.loads((ws.PROTO_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["commit"] == ws.SCHEMA_COMMIT
    assert manifest["license"] == "Apache-2.0"
    assert len(list((ws.PROTO_DIR / "proto").glob("*.proto"))) == 69
    for filename, digest in manifest["sha256"].items():
        assert hashlib.sha256((ws.PROTO_DIR / Path(filename)).read_bytes()).hexdigest() == digest
    cls = ws.wrapper_class()
    desc = cls.DESCRIPTOR
    assert desc.fields_by_name["symbol"].number == 1
    assert desc.fields_by_name["channel"].number == 2
    assert desc.fields_by_name["ts"].number == 3
    ticker = desc.fields_by_name["tickerDetail"]
    assert ticker.number == 2017
    assert ticker.containing_oneof.name == "data"
    assert ticker.message_type.fields_by_name["lastPrice"].number == 2
    assert ticker.message_type.fields_by_name["timestamp"].number == 12
    assert len(desc.oneofs_by_name["data"].fields) > 40


def test_independent_wire_and_runtime_roundtrip():
    item = ws.decode_ticker(wire(), NOW)
    assert item.series_id == ws.SERIES_ID and item.quality == Quality.UNKNOWN
    assert item.key == str(MS) and item.value == "27000.125"
    assert item.source_event_at.timestamp() * 1000 == MS
    assert item.received_at == item.available_at == NOW
    assert item.metadata["schema_commit"] == ws.SCHEMA_COMMIT
    assert item.metadata["live_verified"] is False and item.metadata["session_verified"] is False
    cls = ws.wrapper_class()
    obj = cls(symbol=ws.SYMBOL, channel=ws.CHANNEL)
    obj.tickerDetail.symbol = ws.SYMBOL
    obj.tickerDetail.lastPrice = "27000.125"
    obj.tickerDetail.timestamp = MS
    assert obj.SerializeToString() == wire()
    assert ws.decode_ticker(obj.SerializeToString(), NOW) == item


@pytest.mark.parametrize(
    "bad",
    [
        wire(symbol="BTC_USDT"),
        wire(inner="BTC_USDT"),
        wire(channel="push.tickers"),
        wire(price="NaN"),
        wire(price="0"),
        wire(price="-1"),
        wire(price=""),
        wire(ms=MS // 1000),
        wire(ms=MS + 2000),
        b"",
        b"\xff",
        b"x" * (ws.MAX_BYTES + 1),
    ],
)
def test_reject_invalid_wire(bad):
    with pytest.raises(ValueError):
        ws.decode_ticker(bad, NOW)


def test_wrong_oneof_rejected():
    obj = ws.wrapper_class()(symbol=ws.SYMBOL, channel=ws.CHANNEL)
    obj.tickerList.SetInParent()
    with pytest.raises(ValueError, match="unexpected"):
        ws.decode_ticker(obj.SerializeToString(), NOW)


class FakeSocket:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.sent = []
        self.closed = False
        self.receives = 0
        self.opened = False
        self.options = {}

    def opener(self, url, **kwargs):
        assert url == ws.WS_URL
        self.options = kwargs
        self.opened = True
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self.closed = True

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    async def recv(self):
        self.receives += 1
        try:
            return next(self.frames)
        except StopIteration:
            await asyncio.Future()


async def collect(socket, permit=lambda: None, **kwargs):
    return [
        x
        async for x in ws.stream_tickers(
            permit, network_opt_in=True, opener=socket.opener, clock=lambda: NOW, **kwargs
        )
    ]


@pytest.mark.asyncio
async def test_fixed_subscription_and_bounded_close(monkeypatch):
    monkeypatch.setattr(ws, "MAX_MESSAGES", 2)
    socket = FakeSocket(['{"channel":"ack"}', wire()])
    result = await collect(socket)
    assert len(result) == 1 and socket.closed
    assert socket.sent == [{"method": "sub.ticker", "param": {"symbol": ws.SYMBOL}}]
    assert socket.options["proxy"] is None and socket.options["ping_interval"] is None
    assert socket.options["compression"] is None and socket.options["max_size"] == ws.MAX_BYTES


@pytest.mark.asyncio
async def test_disabled_and_revoked_before_connect():
    socket = FakeSocket([wire()])
    with pytest.raises(SourceUnavailable):
        async for _ in ws.stream_tickers(lambda: None, opener=socket.opener):
            pytest.fail("unexpected frame")
    assert not socket.opened

    def deny():
        raise PermissionDenied("revoked")

    with pytest.raises(PermissionDenied):
        await collect(socket, deny)
    assert not socket.opened


@pytest.mark.parametrize("denied", [2, 3, 4, 5, 6])
@pytest.mark.asyncio
async def test_permit_before_after_connect_send_receive(monkeypatch, denied):
    monkeypatch.setattr(ws, "MAX_MESSAGES", 1)
    socket = FakeSocket([wire()])
    count = 0

    def permit():
        nonlocal count
        count += 1
        if count >= denied:
            raise PermissionDenied("revoked")

    with pytest.raises(PermissionDenied):
        await collect(socket, permit)
    assert socket.closed
    assert len(socket.sent) == (0 if denied <= 3 else 1)
    assert socket.receives == (0 if denied <= 5 else 1)


@pytest.mark.asyncio
async def test_heartbeat_and_pong(monkeypatch):
    monkeypatch.setattr(ws, "PING_SECONDS", 0.01)
    monkeypatch.setattr(ws, "PONG_TIMEOUT", 0.2)
    monkeypatch.setattr(ws, "MAX_MESSAGES", 2)

    class Heartbeat(FakeSocket):
        def __init__(self):
            super().__init__([])
            self.ping = asyncio.Event()
            self.ponged = False

        async def send(self, raw):
            await super().send(raw)
            if self.sent[-1]["method"] == "ping":
                self.ping.set()

        async def recv(self):
            await self.ping.wait()
            if not self.ponged:
                self.ponged = True
                return json.dumps({"channel": "pong", "data": MS})
            return wire()

    socket = Heartbeat()
    rows = await collect(socket, session_seconds=1)
    assert len(rows) == 1 and socket.closed
    assert socket.sent[-1] == {"method": "ping"}


@pytest.mark.asyncio
async def test_missing_pong_times_out(monkeypatch):
    monkeypatch.setattr(ws, "PING_SECONDS", 0.01)
    monkeypatch.setattr(ws, "PONG_TIMEOUT", 0.02)
    socket = FakeSocket([])
    with pytest.raises(TimeoutError, match="pong"):
        await collect(socket, session_seconds=1)
    assert socket.closed and socket.sent[-1] == {"method": "ping"}


@pytest.mark.asyncio
async def test_json_market_is_never_fallback():
    socket = FakeSocket(['{"channel":"push.ticker","data":{"lastPrice":10}}'])
    with pytest.raises(ValueError, match="JSON market"):
        await collect(socket)
    assert socket.closed


def test_redirect_never_followed():
    exc = ValueError("redirect")
    assert ws._FixedConnect(ws.WS_URL).process_redirect(exc) is exc
