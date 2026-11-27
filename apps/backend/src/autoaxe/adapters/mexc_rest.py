"""MEXC NAS100_USDT public REST snapshot (documentation checked 2026-11-27).

https://www.mexc.com/api-docs/futures/integration-guide
https://www.mexc.com/api-docs/futures/market-endpoints/get-contract-info
https://www.mexc.com/api-docs/futures/market-endpoints/get-ticker-contract-market-data
https://www.mexc.com/api-docs/futures/error-code
Current detail docs specify /detail/country; no fallback to old /detail.
Both endpoints document 10 requests / 2 seconds; caller owns durable cadence,
source grant version, cooldown, and storage-time permission check.
Futures JSON WS migration deadline: 2026-12-01 10:00 UTC.
https://www.mexc.com/pt-BR/announcements/article/mexc-to-migrate-futures-websocket-market-data-from-json-to-protobuf-17827791539697
https://www.mexc.com/api-docs/futures/websocket-api/protocol-buffers-integration
Separate WS adapter exists. Pair type 2 observed 2026-11-27; it denotes
the documented suspended-pair class, not current session status.
"""

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx

from autoaxe.application.collection import FetchError, SourceUnavailable
from autoaxe.domain.market import Candidate, Quality
from autoaxe.domain.types import decimal_string, utc_datetime, utc_string

SERIES_ID = "NASDAQ100_MEXC_PERP_USDT"
SYMBOL = "NAS100_USDT"
DETAIL_URL = "https://api.mexc.com/api/v1/contract/detail/country"
TICKER_URL = "https://api.mexc.com/api/v1/contract/ticker"
MAX_BYTES = 256_000
PROTOBUF_DEADLINE = datetime(2026, 12, 1, 10, tzinfo=UTC)


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate MEXC JSON key")
        result[key] = value
    return result


def _invalid(_: str) -> Any:
    raise ValueError("nonfinite MEXC JSON")


def _row(raw: bytes) -> dict[str, Any]:
    data = json.loads(
        raw.decode("utf-8"), parse_float=Decimal, parse_constant=_invalid, object_pairs_hook=_pairs
    )
    if not isinstance(data, dict) or type(data.get("code")) is not int:
        raise ValueError("invalid MEXC response envelope")
    code = data["code"]
    if data.get("success") is not True or code != 0:
        # HTTP 200 may carry documented rate-limit/access errors. Map only
        # known codes to the scheduler's error classes; never retry here.
        if code == 510:
            raise FetchError(429)
        if code in (401, 402, 406, 511, 701, 702, 703, 704):
            raise FetchError(403)
        if code in (500, 501, 604, 801):
            raise FetchError(503)
        raise SourceUnavailable("MEXC API rejected request")
    row = data.get("data")
    if not isinstance(row, dict) or row.get("symbol") != SYMBOL:
        raise ValueError("MEXC symbol or response shape mismatch")
    return row


def _decimal(value: object, *, positive: bool = False) -> str:
    if type(value) is int:
        value = str(value)
    result = decimal_string(value)
    if positive and Decimal(result) <= 0:
        raise ValueError("nonpositive MEXC price or size")
    return result


def _int(value: object) -> int:
    if type(value) is not int:
        raise ValueError("invalid MEXC integer")
    return value


@dataclass(frozen=True)
class ContractDetail:
    contract_id: int
    contract_size: str
    price_unit: str
    pair_type: int

    @classmethod
    def parse(cls, raw: bytes) -> "ContractDetail":
        row = _row(raw)
        if (
            _int(row.get("state")) != 0
            or _int(row.get("futureType")) != 1
            or _int(row.get("type")) not in (1, 2)
            or row.get("baseCoin") != "NAS100"
            or row.get("quoteCoin") != "USDT"
            or row.get("settleCoin") != "USDT"
        ):
            raise SourceUnavailable("MEXC contract is unavailable or mapping changed")
        cid = _int(row.get("id"))
        if cid <= 0:
            raise ValueError("invalid MEXC contract id")
        return cls(
            cid,
            _decimal(row.get("contractSize"), positive=True),
            _decimal(row.get("priceUnit"), positive=True),
            _int(row.get("type")),
        )


@dataclass(frozen=True)
class TickerSnapshot:
    last_price: str
    source_event_at: datetime
    timestamp_ms: int
    contract_id: int

    @classmethod
    def parse(cls, raw: bytes, detail: ContractDetail, received: datetime) -> "TickerSnapshot":
        row = _row(raw)
        cid = _int(row.get("contractId"))
        if cid != detail.contract_id:
            raise ValueError("MEXC contract id mismatch")
        ms = _int(row.get("timestamp"))
        if not 1_000_000_000_000 <= ms <= 9_999_999_999_999:
            raise ValueError("invalid MEXC millisecond timestamp")
        event = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=ms)
        if event > utc_datetime(received):
            raise ValueError("future MEXC trade timestamp")
        return cls(_decimal(row.get("lastPrice"), positive=True), event, ms, cid)


async def _get(
    client: httpx.AsyncClient,
    url: str,
    permit: Callable[[], None],
) -> bytes:
    permit()
    try:
        async with asyncio.timeout(15):
            async with client.stream("GET", url, params={"symbol": SYMBOL}) as response:
                if response.status_code != 200:
                    raise FetchError(response.status_code, response.headers.get("Retry-After"))
                if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                    raise ValueError("unexpected MEXC content encoding")
                result = bytearray()
                async for chunk in response.aiter_raw():
                    result.extend(chunk)
                    if len(result) > MAX_BYTES:
                        raise ValueError("MEXC response too large")
                return bytes(result)
    finally:
        # Includes error paths and in-flight revocation; no second request
        # or data return after authority changes.
        permit()


async def fetch_snapshot(
    permit: Callable[[], None],
    *,
    network_opt_in: bool = False,
    http_transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Candidate:
    """One bounded pair of unsigned fixed GETs; no retry, redirect, proxy or fallback.

    The mandatory permit must verify current fetch/storage, grant version and
    source cooldown. Caller must fence persistence again. Injected transport
    is a trusted offline test seam, not a URL/credential configuration.
    """
    if not network_opt_in:
        raise SourceUnavailable("MEXC REST transport not enabled")
    async with httpx.AsyncClient(
        timeout=10,
        follow_redirects=False,
        trust_env=False,
        headers={"Accept": "application/json", "Accept-Encoding": "identity"},
        transport=http_transport,
    ) as client:
        detail = ContractDetail.parse(await _get(client, DETAIL_URL, permit))
        detail_received = utc_datetime(clock())
        client.cookies.clear()
        raw = await _get(client, TICKER_URL, permit)
        received = utc_datetime(clock())
        if received < detail_received:
            raise ValueError("MEXC observation clock regressed")
        ticker = TickerSnapshot.parse(raw, detail, received)
    # Not an exchange-session confirmation or verified live CME price.
    return Candidate(
        SERIES_ID,
        str(ticker.timestamp_ms),
        ticker.last_price,
        ticker.source_event_at,
        received,
        received,
        Quality.UNKNOWN,
        {
            "symbol": SYMBOL,
            "instrument_type": "index_linked_perpetual",
            "quote_currency": "USDT",
            "settlement_currency": "USDT",
            "contract_id": ticker.contract_id,
            "contract_size": detail.contract_size,
            "price_unit": detail.price_unit,
            "pair_type": detail.pair_type,
            "contract_detail_received_at": utc_string(detail_received),
            "provenance": "mexc_futures_rest_candidate",
            "session_verified": False,
            "live_verified": False,
        },
    )
