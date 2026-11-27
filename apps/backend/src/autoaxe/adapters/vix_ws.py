"""Bounded Yahoo index quote session using the pinned yfinance protobuf schema."""

import asyncio
import base64
import importlib
import json
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from importlib.metadata import version
from typing import Any

from websockets.exceptions import InvalidStatus

from autoaxe.adapters.transport import _FixedConnect
from autoaxe.application.collection import FetchError
from autoaxe.domain.market import Candidate, Quality
from autoaxe.domain.types import utc_string

URL = "wss://streamer.finance.yahoo.com/?version=2"
SYMBOL = "^VIX"
SID = "VIX_YAHOO_WS"
MAX_FRAME = 64_000


def normalize_quote(message: dict[str, Any], received: datetime) -> Candidate:
    if message.get("id") != SYMBOL:
        raise ValueError("unexpected VIX symbol")
    raw_time = message.get("time")
    if isinstance(raw_time, bool) or not isinstance(raw_time, (str, int)):
        raise ValueError("missing VIX quote time")
    if not str(raw_time).isascii() or not str(raw_time).isdigit() or len(str(raw_time)) != 13:
        raise ValueError("VIX quote time must be epoch milliseconds")
    stamp = datetime.fromtimestamp(int(raw_time) / 1000, UTC)
    try:
        price = Decimal(str(message["price"]))
    except (KeyError, InvalidOperation, ValueError) as exc:
        raise ValueError("invalid VIX quote price") from exc
    if not price.is_finite() or price <= 0:
        raise ValueError("invalid VIX quote price")
    # Until source timestamp semantics, session and live/delay behavior are
    # externally verified, even a recent frame is informational only.
    return Candidate(
        SID,
        "ws:" + utc_string(stamp),
        str(price),
        stamp,
        received,
        received,
        Quality.STALE if (received - stamp).total_seconds() > 10 else Quality.UNKNOWN,
        {
            "symbol": SYMBOL,
            "provenance": "yahoo_ws_quote",
            "timestamp_semantics": "provider_quote_timestamp",
            "session_verified": False,
            "live_verified": False,
        },
    )


def decode_frame(raw: str | bytes, received: datetime) -> Candidate | None:
    if len(raw) > MAX_FRAME or version("yfinance") != "1.8.0":
        raise ValueError("unsupported Yahoo frame or client version")
    envelope = json.loads(raw)
    if not isinstance(envelope, dict):
        raise ValueError("invalid Yahoo envelope")
    encoded = envelope.get("message")
    if encoded is None:
        return None
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("invalid Yahoo quote message")
    try:
        protobuf = importlib.import_module("yfinance.pricing_pb2")
        msg = protobuf.PricingData()
        msg.ParseFromString(base64.b64decode(encoded, validate=True))
    except Exception as exc:
        raise ValueError("invalid Yahoo protobuf") from exc
    return normalize_quote({"id": msg.id, "time": msg.time, "price": msg.price}, received)


async def stream_quotes(
    permit: Callable[[], None],
    *,
    duration: float = 900,
) -> AsyncGenerator[Candidate, None]:
    """One fixed session; no library reconnect, redirects, proxies or raw logs."""
    if not 1 <= duration <= 900:
        raise ValueError("invalid VIX session duration")
    permit()
    if version("yfinance") != "1.8.0":
        raise ValueError("unsupported Yahoo client version")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + duration
    try:
        async with _FixedConnect(
            URL,
            open_timeout=10,
            close_timeout=3,
            ping_interval=20,
            ping_timeout=20,
            max_size=MAX_FRAME,
            max_queue=8,
            proxy=None,
        ) as ws:
            permit()
            subscription = json.dumps({"subscribe": [SYMBOL]})
            await asyncio.wait_for(ws.send(subscription), timeout=5)
            heartbeat = loop.time() + 15
            while loop.time() < deadline:
                permit()
                try:
                    raw = await asyncio.wait_for(
                        ws.recv(),
                        timeout=max(0.001, min(5, deadline - loop.time(), heartbeat - loop.time())),
                    )
                except TimeoutError:
                    if loop.time() >= heartbeat and loop.time() < deadline:
                        permit()
                        await asyncio.wait_for(ws.send(subscription), timeout=5)
                        heartbeat = loop.time() + 15
                    continue
                received = datetime.now(UTC)
                permit()
                item = decode_frame(raw, received)
                if item is not None:
                    yield item
                if loop.time() >= heartbeat and loop.time() < deadline:
                    permit()
                    await asyncio.wait_for(ws.send(subscription), timeout=5)
                    heartbeat = loop.time() + 15
    except InvalidStatus as exc:
        raise FetchError(
            exc.response.status_code, exc.response.headers.get("Retry-After")
        ) from None
    finally:
        permit()
