"""Single NAS100_USDT Protobuf ticker, using the pinned official schema.

https://www.mexc.com/api-docs/futures/websocket-api/protocol-buffers-integration/
https://www.mexc.com/api-docs/futures/websocket-api/get-a-single-ticker
https://www.mexc.com/api-docs/futures/websocket-api/command-details-for-data-exchange
No private channels, fallback, JSON market payloads, or inferred session state.
"""

import asyncio
import hashlib
import importlib
import json
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from websockets.asyncio.client import connect
from websockets.exceptions import (
    ConnectionClosed,
    InvalidHandshake,
    InvalidStatus,
    WebSocketException,
)

from autoaxe.application.collection import FetchError, SourceUnavailable
from autoaxe.domain.canonical import strict_json
from autoaxe.domain.market import Candidate, Quality
from autoaxe.domain.types import decimal_string, utc_datetime

SERIES_ID = "NASDAQ100_MEXC_PERP_USDT_WS"
SYMBOL = "NAS100_USDT"
WS_URL = "wss://contract.mexc.com/edge?Trans-Protocol=Protobuf"
CHANNEL = "push.ticker"
SCHEMA_COMMIT = "033825833318b4bc3add4481997e9f76005c6483"
DESCRIPTOR_SHA256 = "f6ebc7533d5d533d4715b59771b9b48ac673bb18ee7e346f2dd740de6e95df77"
MAX_BYTES = 64_000
MAX_MESSAGES = 1024
SESSION_SECONDS = 300
PING_SECONDS = 15
PONG_TIMEOUT = 10
MAX_UNDOCUMENTED_CONTROLS = 4
PROTO_DIR = Path(__file__).with_name("mexc_proto")


@lru_cache(maxsize=1)
def wrapper_class() -> type[Any]:
    """Load complete protoc-generated descriptor, verify pinned bytes first."""
    raw = (PROTO_DIR / "contract.desc").read_bytes()
    if len(raw) != 41481 or hashlib.sha256(raw).hexdigest() != DESCRIPTOR_SHA256:
        raise SourceUnavailable("MEXC official descriptor integrity failure")
    pb = importlib.import_module("google.protobuf.descriptor_pb2")
    pool_module = importlib.import_module("google.protobuf.descriptor_pool")
    factory = importlib.import_module("google.protobuf.message_factory")
    desc = pb.FileDescriptorSet()
    desc.ParseFromString(raw)
    pool = pool_module.DescriptorPool()
    # protoc's include_imports produces dependencies before dependants.
    for file in desc.file:
        pool.Add(file)
    cls = factory.GetMessageClass(pool.FindMessageTypeByName("ContractWrapper"))
    if not isinstance(cls, type):
        raise SourceUnavailable("MEXC wrapper class unavailable")
    return cls


def _millis(value: int, received: datetime) -> datetime:
    if not 1_000_000_000_000 <= value <= 9_999_999_999_999:
        raise ValueError("invalid MEXC timestamp")
    stamp = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=value)
    if stamp > received:
        raise ValueError("future MEXC timestamp")
    return stamp


def decode_ticker(raw: bytes, received: datetime) -> Candidate:
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_BYTES:
        raise ValueError("invalid MEXC binary frame size")
    received = utc_datetime(received)
    wrapper = wrapper_class()()
    try:
        wrapper.ParseFromString(raw)
    except Exception:
        raise ValueError("invalid MEXC Protobuf frame") from None
    if (
        wrapper.symbol != SYMBOL
        or wrapper.channel != CHANNEL
        or wrapper.WhichOneof("data") != "tickerDetail"
        or wrapper.tickerDetail.symbol != SYMBOL
    ):
        raise ValueError("MEXC unexpected symbol/channel/message")
    row = wrapper.tickerDetail
    stamp = _millis(row.timestamp, received)
    if wrapper.ts:
        _millis(wrapper.ts, received)
    price = decimal_string(row.lastPrice)
    if Decimal(price) <= 0:
        raise ValueError("nonpositive MEXC ticker price")
    return Candidate(
        SERIES_ID,
        str(row.timestamp),
        price,
        stamp,
        received,
        received,
        Quality.UNKNOWN,
        {
            "symbol": SYMBOL,
            "instrument_type": "index_linked_perpetual",
            "quote_currency": "USDT",
            "settlement_currency": "USDT",
            "provenance": "mexc_futures_protobuf_ticker",
            "schema_commit": SCHEMA_COMMIT,
            "timestamp_semantics": "provider_ticker_timestamp",
            "session_verified": False,
            "live_verified": False,
        },
    )


class _FixedConnect(connect):
    # websockets 16.1.1 normally follows handshake redirects. Disable this:
    # even a redirect to another MEXC URL is outside the approved contract.
    def process_redirect(self, exc: Exception) -> Exception | str:
        return exc


async def _send(ws: Any, payload: dict[str, Any], permit: Callable[[], None]) -> None:
    permit()
    try:
        async with asyncio.timeout(5):
            await ws.send(json.dumps(payload, separators=(",", ":")))
    finally:
        permit()


def _control(frame: str) -> bool:
    if len(frame.encode("utf-8")) > MAX_BYTES:
        raise ValueError("oversize MEXC control")
    row = strict_json(frame)
    if not isinstance(row, dict):
        raise ValueError("invalid MEXC control")
    if row.get("channel") == "pong":
        if type(row.get("data")) is not int or row["data"] <= 0:
            raise ValueError("invalid MEXC pong")
        return True
    # No published Protobuf subscribe-ACK layout: never treat it as data or
    # successful subscription. A few opaque controls may precede real pushes.
    if (
        str(row.get("channel", "")).startswith("push.")
        or row.get("success") is False
        or "error" in row
    ):
        raise ValueError("unexpected MEXC JSON market data or error")
    return False


async def stream_tickers(
    permit: Callable[[], None],
    *,
    network_opt_in: bool = False,
    session_seconds: int = SESSION_SECONDS,
    opener: Callable[..., Any] = _FixedConnect,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> AsyncGenerator[Candidate, None]:
    """Bounded single session. Caller owns durable reservation and persistence."""
    if not network_opt_in:
        raise SourceUnavailable("MEXC Protobuf transport not enabled")
    if not 1 <= session_seconds <= SESSION_SECONDS:
        raise ValueError("invalid MEXC session duration")
    # Validate runtime schema before network access.
    wrapper_class()
    loop = asyncio.get_running_loop()
    permit()
    try:
        async with opener(
            WS_URL,
            open_timeout=10,
            close_timeout=5,
            ping_interval=None,
            compression=None,
            proxy=None,
            max_size=MAX_BYTES,
            max_queue=8,
        ) as ws:
            permit()
            await _send(ws, {"method": "sub.ticker", "param": {"symbol": SYMBOL}}, permit)
            deadline = loop.time() + session_seconds
            next_ping = loop.time() + PING_SECONDS
            pong_due: float | None = None
            controls = 0
            messages = 0
            while loop.time() < deadline and messages < MAX_MESSAGES:
                now = loop.time()
                if pong_due is not None and now >= pong_due:
                    raise TimeoutError("MEXC pong deadline expired")
                if now >= next_ping:
                    await _send(ws, {"method": "ping"}, permit)
                    next_ping = loop.time() + PING_SECONDS
                    pong_due = loop.time() + PONG_TIMEOUT
                    now = loop.time()
                wait = min(
                    5.0,
                    deadline - now,
                    next_ping - now,
                    pong_due - now if pong_due is not None else 5.0,
                )
                if wait <= 0:
                    continue
                permit()
                try:
                    try:
                        frame = await asyncio.wait_for(ws.recv(), timeout=wait)
                    except TimeoutError:
                        continue
                finally:
                    permit()
                messages += 1
                if isinstance(frame, str):
                    if _control(frame):
                        pong_due = None
                    else:
                        controls += 1
                        if controls > MAX_UNDOCUMENTED_CONTROLS:
                            raise ValueError("too many undocumented MEXC controls")
                elif isinstance(frame, bytes):
                    yield decode_ticker(frame, clock())
                else:
                    raise ValueError("unexpected MEXC frame type")
            # Close is sufficient teardown; do not send an unsubscribe after
            # revocation, and no reconnect or hidden retry occurs here.
    except InvalidStatus as exc:
        raise FetchError(
            exc.response.status_code, exc.response.headers.get("Retry-After")
        ) from None
    except ConnectionClosed:
        raise ConnectionError("MEXC WebSocket disconnected") from None
    except InvalidHandshake:
        raise SourceUnavailable("MEXC WebSocket handshake rejected") from None
    except WebSocketException:
        raise SourceUnavailable("MEXC WebSocket protocol rejected") from None
    finally:
        permit()
