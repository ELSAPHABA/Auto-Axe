"""Fixed individual Binance oil streams; permission-gated Yahoo quote candidate.

Yahoo wire format is from locked yfinance 1.8.0, not a documented provider
contract. Only an explicit reviewed provider grant covering this endpoint
and symbol permits connection. No SDK reconnect, HTTP fallback or proxy.
"""

import asyncio
import base64
import importlib
import json
import ssl
from collections.abc import AsyncGenerator, Callable
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from importlib.metadata import version
from typing import Any

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus, WebSocketException

from autoaxe.adapters.providers import binance_trade, millis
from autoaxe.application.collection import FetchError, SourceUnavailable
from autoaxe.domain.canonical import strict_json
from autoaxe.domain.market import Candidate, Quality
from autoaxe.domain.types import decimal_string

OIL = {
    "WTI": ("CLUSDT", "WTI_BINANCE_PERP_SNAPSHOT", "CL=F", "WTI_YAHOO_FUTURES_WS"),
    "BRENT": ("BZUSDT", "BRENT_BINANCE_PERP_SNAPSHOT", "BZ=F", "BRENT_YAHOO_FUTURES_WS"),
}
YAHOO_URL = "wss://streamer.finance.yahoo.com/?version=2"
MAX_BYTES = 64_000
SESSION_SECONDS = 60
MAX_MESSAGES = 10_000
Permit = Callable[[], None]


class StreamFailure(ConnectionError):
    """Only genuine connection failure, never a permission/schema error."""


class FixedConnect(connect):
    def process_redirect(self, exc: Exception) -> Exception | str:
        return exc


def primary_candidate(oil: str, raw: dict[str, Any], received: datetime) -> Candidate:
    symbol, sid, _, _ = OIL[oil]
    item = binance_trade(raw, received, spot=False)
    if item.metadata["symbol"] != symbol or item.value is None or Decimal(item.value) <= 0:
        raise ValueError("unexpected Binance oil trade")
    # Latest-price snapshot only. Never advance the contiguous trade ledger.
    return replace(
        item,
        series_id=sid,
        key="ws:" + item.key,
        metadata={
            **item.metadata,
            "provenance": "binance_oil_ws_snapshot",
            "instrument_type": "commodity_linked_perpetual",
            "contiguous_trade_ledger": False,
        },
    )


def yahoo_candidate(oil: str, row: dict[str, Any], received: datetime) -> Candidate:
    _, _, symbol, sid = OIL[oil]
    if row.get("id") != symbol or row.get("currency") != "USD":
        raise ValueError("Yahoo oil symbol or currency mismatch")
    stamp = millis(row.get("time"))
    if stamp > received or stamp.year < 2000:
        raise ValueError("invalid Yahoo quote timestamp")
    price = decimal_string(str(row.get("price")))
    if Decimal(price) <= 0:
        raise ValueError("invalid Yahoo oil price")
    meta: dict[str, Any] = {
        "symbol": symbol,
        "quote_currency": "USD",
        "instrument_type": "commodity_futures_continuous_quote",
        "provenance": "yahoo_oil_ws_fallback",
        "session_verified": False,
        "live_verified": False,
        "contract_month_verified": False,
        "fallback_only": True,
    }
    if isinstance(row.get("exchange"), str) and 0 < len(row["exchange"]) <= 32:
        meta["provider_exchange"] = row["exchange"]
    # Expiry is optional provider metadata, not an inferred active contract.
    if "expire_date" in row:
        meta["provider_expire_date_ms"] = str(int(row["expire_date"]))
    return Candidate(sid, str(row["time"]), price, stamp, received, received, Quality.UNKNOWN, meta)


def decode_yahoo(raw: str | bytes) -> dict[str, Any] | None:
    if version("yfinance") != "1.8.0":
        raise SourceUnavailable("unsupported Yahoo wire schema")
    envelope = strict_json(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    if not isinstance(envelope, dict):
        raise ValueError("invalid Yahoo envelope")
    encoded = envelope.get("message")
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("unknown Yahoo control envelope")
    try:
        message = importlib.import_module("yfinance.pricing_pb2").PricingData()
        message.ParseFromString(base64.b64decode(encoded, validate=True))
        row = importlib.import_module("google.protobuf.json_format").MessageToDict(
            message, preserving_proto_field_name=True
        )
    except Exception:
        raise ValueError("invalid Yahoo quote protobuf") from None
    if not isinstance(row, dict):
        raise ValueError("invalid Yahoo quote")
    return row


async def _frames(
    url: str,
    permit: Permit,
    *,
    seconds: int,
    subscribe: str | None = None,
    opener: Callable[..., Any] = FixedConnect,
) -> AsyncGenerator[tuple[str | bytes, datetime], None]:
    if not 1 <= seconds <= SESSION_SECONDS:
        raise ValueError("invalid bounded oil session")
    loop = asyncio.get_running_loop()
    permit()
    try:
        async with opener(
            url,
            open_timeout=10,
            close_timeout=5,
            proxy=None,
            compression=None,
            ping_interval=20,
            ping_timeout=20,
            max_size=MAX_BYTES,
            max_queue=8,
        ) as ws:
            permit()
            deadline = loop.time() + seconds
            next_sub = loop.time()
            count = 0
            while loop.time() < deadline and count < MAX_MESSAGES:
                if subscribe is not None and loop.time() >= next_sub:
                    permit()
                    try:
                        await asyncio.wait_for(ws.send(json.dumps({"subscribe": [subscribe]})), 5)
                    finally:
                        permit()
                    next_sub = loop.time() + 15
                wait = min(5.0, deadline - loop.time())
                if subscribe is not None:
                    wait = min(wait, next_sub - loop.time())
                if wait <= 0:
                    continue
                permit()
                try:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), wait)
                    except TimeoutError:
                        continue
                finally:
                    permit()
                received = datetime.now(UTC)
                if not isinstance(raw, (str, bytes)) or len(raw) > MAX_BYTES:
                    raise ValueError("invalid oil WS frame")
                count += 1
                yield raw, received
            # Quiet open socket or planned rollover is not a provider failure.
    except InvalidStatus as exc:
        raise FetchError(
            exc.response.status_code, exc.response.headers.get("Retry-After")
        ) from None
    except ConnectionClosed as exc:
        if exc.rcvd is None or exc.rcvd.code in (1000, 1001, 1011, 1012, 1013):
            raise StreamFailure("oil WS disconnected") from None
        raise SourceUnavailable("oil WS protocol or policy rejection") from None
    except ssl.SSLError:
        raise SourceUnavailable("oil WS TLS failure") from None
    except OSError:
        raise StreamFailure("oil WS connection failed") from None
    except WebSocketException:
        raise SourceUnavailable("oil WS protocol rejected") from None
    finally:
        permit()


async def binance_quotes(
    oil: str,
    permit: Permit,
    *,
    seconds: int = SESSION_SECONDS,
) -> AsyncGenerator[Candidate, None]:
    from contextlib import aclosing

    symbol = OIL[oil][0]
    url = f"wss://fstream.binance.com/market/stream?streams={symbol.lower()}@aggTrade"
    async with aclosing(_frames(url, permit, seconds=seconds)) as frames:
        async for raw, received in frames:
            row = strict_json(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            if not isinstance(row, dict):
                raise ValueError("invalid Binance oil frame")
            yield primary_candidate(oil, row, received)


async def yahoo_quotes(
    oil: str,
    permit: Permit,
    *,
    authorized: bool = False,
    seconds: int = SESSION_SECONDS,
) -> AsyncGenerator[Candidate, None]:
    from contextlib import aclosing

    if not authorized:
        raise SourceUnavailable("affirmative Yahoo provider approval required")
    symbol = OIL[oil][2]
    if version("yfinance") != "1.8.0":
        raise SourceUnavailable("unsupported Yahoo wire schema")
    async with aclosing(_frames(YAHOO_URL, permit, seconds=seconds, subscribe=symbol)) as frames:
        async for raw, received in frames:
            row = decode_yahoo(raw)
            if row is not None:
                yield yahoo_candidate(oil, row, received)
