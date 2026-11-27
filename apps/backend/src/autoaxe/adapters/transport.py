"""Bounded transport implementation, disabled unless explicitly supplied an authorization gate.

No user-supplied URL is accepted. Phase 1 CLI has no network mode.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from autoaxe.adapters.providers import (
    FUTURES_REST,
    FUTURES_WS,
    MAX_BYTES,
    SPOT_WS,
    TREASURY_XML,
    normalize_ratio,
    normalize_treasury,
    ratio_request,
)
from autoaxe.application.collection import FetchError
from autoaxe.domain.canonical import strict_json
from autoaxe.domain.catalog import FUTURES, TREASURY
from autoaxe.domain.market import Candidate


class _FixedConnect(connect):
    """Do not follow even same-host redirects outside the fixed route."""

    def process_redirect(self, exc: Exception) -> Exception | str:
        return exc


class ProviderTransport:
    def __init__(
        self,
        authorize: Callable[[str], None],
        *,
        network_opt_in: bool = False,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.authorize = authorize
        self.network_opt_in = network_opt_in
        self.http_transport = http_transport

    def check(self, sid: str) -> None:
        if not self.network_opt_in:
            raise ValueError("provider transport not enabled")
        self.authorize(sid)

    async def _get(self, url: str, params: dict[str, Any], series: list[str]) -> bytes:
        for sid in series:
            self.check(sid)
        try:
            async with (
                asyncio.timeout(25),
                httpx.AsyncClient(
                    timeout=20,
                    follow_redirects=False,
                    trust_env=False,
                    transport=self.http_transport,
                ) as client,
            ):
                async with client.stream("GET", url, params=params) as response:
                    if response.status_code != 200:
                        raise FetchError(response.status_code, response.headers.get("Retry-After"))
                    result = bytearray()
                    async for chunk in response.aiter_bytes():
                        result.extend(chunk)
                        if len(result) > MAX_BYTES:
                            raise ValueError("provider response too large")
        finally:
            for sid in series:
                self.check(sid)
        return bytes(result)

    async def ratios(self, symbol: str, kind: str) -> list[Candidate]:
        url, params = ratio_request(symbol, kind)
        sid = f"BINANCE_{kind.upper()}_{symbol}"
        raw = await self._get(url, params, [sid])
        rows = strict_json(raw.decode("utf-8"))
        if not isinstance(rows, list):
            raise ValueError("expected ratio array")
        return normalize_ratio(symbol, kind, rows, datetime.now(UTC))

    async def treasury(self, month: str) -> list[Candidate]:
        if (
            len(month) != 6
            or not month.isascii()
            or not month.isdigit()
            or not 1 <= int(month[4:]) <= 12
        ):
            raise ValueError("invalid month")
        series = ["UST_2Y_TREASURY" if t == "2Y" else f"UST_{t}_PAR_YIELD" for t in TREASURY]
        raw = await self._get(
            TREASURY_XML,
            {"data": "daily_treasury_yield_curve", "field_tdr_date_value_month": month},
            series,
        )
        return normalize_treasury(raw, datetime.now(UTC))

    async def futures_recovery(self, symbol: str, after: int) -> list[dict[str, Any]]:
        if symbol not in FUTURES or after < 0:
            raise ValueError("bad recovery request")
        raw = await self._get(
            FUTURES_REST + "/aggTrades",
            {"symbol": symbol, "fromId": after + 1, "limit": 1000},
            [FUTURES[symbol][0]],
        )
        result = strict_json(raw.decode("utf-8"))
        if not isinstance(result, list) or len(result) > 1000:
            raise ValueError("invalid recovery array")
        return result

    async def trades(self, *, spot: bool) -> AsyncIterator[dict[str, Any]]:
        series = ["BITCOIN_BINANCE_SPOT"] if spot else [x[0] for x in FUTURES.values()]
        for sid in series:
            self.check(sid)
        # websockets handles ping/pong; bounded queue backpressure and max message size.
        try:
            async with _FixedConnect(
                SPOT_WS if spot else FUTURES_WS,
                open_timeout=10,
                close_timeout=5,
                ping_interval=20,
                ping_timeout=20,
                max_size=MAX_BYTES,
                max_queue=16,
                proxy=None,
            ) as ws:
                while True:
                    for sid in series:
                        self.check(sid)
                    try:
                        try:
                            message = await asyncio.wait_for(ws.recv(), timeout=5)
                        except TimeoutError:
                            continue
                    finally:
                        for sid in series:
                            self.check(sid)
                    result = strict_json(
                        message.decode() if isinstance(message, bytes) else message
                    )
                    if not isinstance(result, dict):
                        raise ValueError("invalid websocket message")
                    yield result
        except InvalidStatus as exc:
            raise FetchError(
                exc.response.status_code, exc.response.headers.get("Retry-After")
            ) from None
        finally:
            for sid in series:
                self.check(sid)


def fetch_yahoo(
    sid: str,
    authorize: Callable[[str], None],
    *,
    network_opt_in: bool = False,
    ticker_factory: Callable[[str], Any] | None = None,
) -> Candidate:
    """Explicitly authorized history call; timestamps are bar labels, not live quote times."""
    from autoaxe.adapters.providers import normalize_yahoo
    from autoaxe.domain.catalog import YAHOO

    if not network_opt_in:
        raise ValueError("Yahoo transport not enabled")
    authorize(sid)
    if ticker_factory is None:
        import yfinance  # type: ignore[import-untyped]  # upstream has no py.typed/stubs

        ticker_factory = yfinance.Ticker
    symbol = YAHOO[sid]
    ticker = ticker_factory(symbol)
    bars = ticker.history(period="1d", interval="1m", auto_adjust=False, timeout=15)
    now = datetime.now(UTC)
    authorize(sid)
    if bars.empty:
        return normalize_yahoo(sid, symbol=symbol, close=None, stamp=None, received=now)
    delay = (ticker.get_history_metadata() or {}).get("exchangeDataDelayedBy")
    authorize(sid)
    return normalize_yahoo(
        sid,
        symbol=symbol,
        close=bars.iloc[-1]["Close"],
        stamp=bars.index[-1].to_pydatetime(),
        received=now,
        delay_minutes=int(delay) if delay is not None else None,
    )
