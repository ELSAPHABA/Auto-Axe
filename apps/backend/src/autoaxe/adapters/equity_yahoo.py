"""Opt-in Yahoo adapter. No import, connection or request at module load."""

import asyncio
import importlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from importlib.metadata import version
from typing import Any

import httpx
from websockets.exceptions import ConnectionClosed, ConnectionClosedOK, InvalidStatus

from autoaxe.adapters.equity_http import (
    ApprovedHTTP,
    fetch_chart,
    fetch_summary,
    load_approved_http,
)
from autoaxe.adapters.equity_http import (
    DailyTransportUnavailable as DailyTransportUnavailable,
)
from autoaxe.application.collection import FetchError
from autoaxe.domain.volume import SYMBOLS

YAHOO_WS_VERSION = "1.8.0"
Permit = Callable[[], None]
Handler = Callable[[dict[str, Any]], None]
Clock = Callable[[], datetime]


def _yahoo() -> Any:
    # The locked client has a listen() reconnect loop that cannot reliably
    # surface a clean WebSocket close. Only this inspected version is supported.
    if version("yfinance") != YAHOO_WS_VERSION:
        raise RuntimeError("unsupported yfinance transport version")
    return importlib.import_module("yfinance")


async def listen_volume(permit: Permit, on_message: Handler) -> None:
    """A single subscription, without opaque automatic reconnects.

    Use the pinned client's public subscription/close and its decoder and
    underlying socket for one bounded receive loop. A clean close returns to
    our caller. No raw provider payload is persisted or logged here.
    """
    permit()
    yf = _yahoo()
    ws = yf.AsyncWebSocket(verbose=False)
    try:
        permit()
        await asyncio.wait_for(ws.subscribe(list(SYMBOLS)), timeout=15)
        # Cancel the library's unfenced heartbeat. Keep one guarded heartbeat
        # using the same subscription protocol and documented interval.
        heartbeat = ws._heartbeat_task
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)
        next_heartbeat = asyncio.get_running_loop().time() + 15
        while True:
            permit()
            timeout = max(0.0, next_heartbeat - asyncio.get_running_loop().time())
            try:
                raw = await asyncio.wait_for(ws._ws.recv(), timeout=timeout)
            except TimeoutError:
                permit()
                await asyncio.wait_for(
                    ws._ws.send(json.dumps({"subscribe": list(SYMBOLS)})), timeout=5
                )
                next_heartbeat = asyncio.get_running_loop().time() + 15
                continue
            if not isinstance(raw, (str, bytes)) or len(raw) > 64_000:
                raise ValueError("invalid Yahoo message envelope")
            envelope = json.loads(raw)
            if not isinstance(envelope, dict):
                raise ValueError("invalid Yahoo message envelope")
            encoded = envelope.get("message")
            if not isinstance(encoded, str) or not encoded:
                continue
            message = ws._decode_message(encoded)
            if not isinstance(message, dict) or "error" in message:
                raise ValueError("invalid Yahoo message")
            on_message(message)
    except ConnectionClosedOK:
        return
    except InvalidStatus as exc:
        raise FetchError(
            exc.response.status_code, exc.response.headers.get("Retry-After")
        ) from None
    except ConnectionClosed as exc:
        if exc.rcvd is None or exc.rcvd.code in (1001, 1011, 1012, 1013):
            raise ConnectionError("Yahoo WebSocket disconnected") from None
        raise RuntimeError("Yahoo WebSocket protocol or policy rejection") from None
    finally:
        await asyncio.wait_for(ws.close(), timeout=5)


def require_daily_transport(contract: ApprovedHTTP | None = None) -> ApprovedHTTP:
    approved = contract or load_approved_http()
    if approved is None:
        raise DailyTransportUnavailable("Yahoo daily HTTP transport not verified; disabled")
    approved.check(datetime.now(UTC))
    return approved


def fetch_daily(
    symbol: str,
    permit: Permit,
    *,
    start: date | None = None,
    end: date | None = None,
    contract: ApprovedHTTP | None = None,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """One explicit bounded missing-session request under a reviewed contract."""
    if symbol not in SYMBOLS:
        raise ValueError("unregistered equity")
    permit()
    approved = require_daily_transport(contract)
    if start is None or end is None:
        raise ValueError("explicit daily range required")
    if client is not None:
        return fetch_chart(client, approved, symbol, start, end, permit)
    with httpx.Client(trust_env=False, follow_redirects=False) as transport:
        return fetch_chart(transport, approved, symbol, start, end, permit)


def fetch_fundamentals(
    symbol: str,
    permit: Permit,
    *,
    contract: ApprovedHTTP | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    if symbol not in SYMBOLS:
        raise ValueError("unregistered equity")
    permit()
    if symbol == "QLD":
        # Corporate metrics do not apply to the ETF. No HTTP request needed.
        return {}
    approved = require_daily_transport(contract)
    if client is not None:
        return fetch_summary(client, approved, symbol, permit)
    with httpx.Client(trust_env=False, follow_redirects=False) as transport:
        return fetch_summary(transport, approved, symbol, permit)


Listen = Callable[[Permit, Handler], Awaitable[None]]


def utc_now() -> datetime:
    return datetime.now(UTC)
