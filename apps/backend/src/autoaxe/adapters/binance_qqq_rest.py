"""Documented Binance USD-M QQQ ETF perpetual REST candidate, not CME NQ.

Listing (2026-04-06):
https://www.binance.com/en/support/announcement/detail/4cde981dc32d4268b7645e9d16e8d63a
Market-data endpoints (reviewed 2026-11-27):
https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data
ExchangeInfo accepts no symbol filter; discard all other symbol records.
Both requests have documented weight 1 with a single-symbol V2 ticker.
Actual regional availability, payload and exchange session not verified.
"""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx

from autoaxe.application.collection import FetchError, SourceUnavailable
from autoaxe.domain.canonical import strict_json
from autoaxe.domain.market import Candidate, Quality
from autoaxe.domain.types import decimal_string, utc_datetime

SERIES_ID = "NASDAQ100_BINANCE_QQQ_PERP_USDT"
SYMBOL = "QQQUSDT"
SOURCE = "binance_futures"
DETAIL_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"
TICKER_URL = "https://fapi.binance.com/fapi/v2/ticker/price"
MAX_DETAIL_BYTES = 4_000_000
MAX_TICKER_BYTES = 16_384
LISTED_AT = datetime(2026, 4, 6, 13, 30, tzinfo=UTC)


def _positive(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("expected Binance decimal string")
    result = decimal_string(value)
    if Decimal(result) <= 0:
        raise ValueError("nonpositive Binance price or tick")
    return result


def _object(raw: bytes) -> dict[str, Any]:
    row = strict_json(raw.decode("utf-8"))
    if not isinstance(row, dict):
        raise ValueError("invalid Binance response")
    if "code" in row:
        raise SourceUnavailable("Binance API rejected request")
    return row


def contract_tick(raw: bytes) -> str:
    data = _object(raw).get("symbols")
    if not isinstance(data, list) or len(data) > 5000:
        raise ValueError("invalid Binance symbol inventory")
    matches = [row for row in data if isinstance(row, dict) and row.get("symbol") == SYMBOL]
    if len(matches) != 1:
        raise SourceUnavailable("QQQ contract unavailable or ambiguous")
    row = matches[0]
    if any(
        row.get(k) != v
        for k, v in {
            "pair": SYMBOL,
            "contractType": "PERPETUAL",
            "status": "TRADING",
            "baseAsset": "QQQ",
            "quoteAsset": "USDT",
            "marginAsset": "USDT",
        }.items()
    ):
        raise SourceUnavailable("QQQ contract unavailable or mapping changed")
    filters = row.get("filters")
    if not isinstance(filters, list) or len(filters) > 100:
        raise ValueError("invalid QQQ contract filters")
    ticks = [f for f in filters if isinstance(f, dict) and f.get("filterType") == "PRICE_FILTER"]
    if len(ticks) != 1:
        raise ValueError("missing or ambiguous QQQ price filter")
    return _positive(ticks[0].get("tickSize"))


def normalize(raw: bytes, tick: str, received: datetime) -> Candidate:
    row = _object(raw)
    if row.get("symbol") != SYMBOL:
        raise ValueError("QQQ ticker symbol mismatch")
    ms = row.get("time")
    if type(ms) is not int or not 1_000_000_000_000 <= ms <= 9_999_999_999_999:
        raise ValueError("invalid QQQ transaction milliseconds")
    event = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=ms)
    received = utc_datetime(received)
    if not LISTED_AT <= event <= received:
        raise ValueError("QQQ timestamp outside listing/receipt bounds")
    return Candidate(
        SERIES_ID,
        str(ms),
        _positive(row.get("price")),
        event,
        received,
        received,
        Quality.UNKNOWN,
        {
            "symbol": SYMBOL,
            "instrument_type": "etf_linked_perpetual",
            "underlying": "Invesco QQQ Trust Series 1",
            "quote_currency": "USDT",
            "settlement_currency": "USDT",
            "price_unit": _positive(tick),
            "provenance": "binance_qqq_rest_candidate",
            "session_verified": False,
            "live_verified": False,
        },
    )


async def _get(
    client: httpx.AsyncClient,
    *,
    detail: bool,
    permit: Callable[[], None],
) -> bytes:
    permit()
    try:
        async with asyncio.timeout(15):
            async with client.stream(
                "GET",
                DETAIL_URL if detail else TICKER_URL,
                params=None if detail else {"symbol": SYMBOL},
            ) as response:
                if response.status_code != 200:
                    raise FetchError(response.status_code, response.headers.get("Retry-After"))
                media_type = response.headers.get("Content-Type", "").split(";", 1)[0]
                if media_type.strip().lower() != "application/json":
                    raise ValueError("unexpected Binance response media type")
                if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                    raise ValueError("unexpected Binance content encoding")
                limit = MAX_DETAIL_BYTES if detail else MAX_TICKER_BYTES
                result = bytearray()
                async for chunk in response.aiter_raw():
                    result.extend(chunk)
                    if len(result) > limit:
                        raise ValueError("Binance response too large")
                return bytes(result)
    finally:
        permit()


async def fetch_snapshot(
    permit: Callable[[], None],
    *,
    network_opt_in: bool = False,
    http_transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Candidate:
    """Two fixed unsigned GETs; no alternate host, retry, proxy or redirect."""
    if not network_opt_in:
        raise SourceUnavailable("Binance QQQ REST transport not enabled")
    async with httpx.AsyncClient(
        timeout=10,
        follow_redirects=False,
        trust_env=False,
        headers={"Accept": "application/json", "Accept-Encoding": "identity"},
        transport=http_transport,
    ) as client:
        tick = contract_tick(await _get(client, detail=True, permit=permit))
        client.cookies.clear()
        raw = await _get(client, detail=False, permit=permit)
        return normalize(raw, tick, clock())
