"""Policy-first collection and reconnect/recovery primitives for fixture transports."""

import asyncio
import random
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from autoaxe.adapters.providers import binance_rest_trade, binance_trade, recovery_request
from autoaxe.domain.catalog import FUTURES
from autoaxe.domain.market import Candidate
from autoaxe.infrastructure.jobs import retry_after


class SourceUnavailable(RuntimeError):
    pass


class FetchError(SourceUnavailable):
    def __init__(self, status: int, retry_header: str | None = None):
        super().__init__(f"provider HTTP {status}")
        self.status = status
        self.retry_header = retry_header


async def bounded_fetch(
    call: Callable[[], Awaitable[Any]],
    authorize: Callable[[], None],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    attempts: int = 4,
) -> Any:
    for attempt in range(attempts):
        authorize()
        try:
            result = await asyncio.wait_for(call(), timeout=20)
            authorize()
            return result
        except FetchError as exc:
            if exc.status in (401, 403) or exc.status not in (429, 500, 502, 503, 504):
                raise
            if attempt + 1 == attempts:
                raise
            delay = retry_after(attempt, exc.retry_header, datetime.now(UTC))
            await sleep(delay + random.random())
        except (TimeoutError, ConnectionError):
            if attempt + 1 == attempts:
                raise
            await sleep(min(60, 2**attempt) + random.random())
    raise SourceUnavailable("retry exhausted")


class GapTracker:
    def __init__(self, checkpoints: Mapping[str, int] | None = None) -> None:
        self.last: dict[str, int] = dict(checkpoints or {})

    def gap(self, item: Candidate) -> tuple[int, int] | None:
        current = int(item.key)
        previous = self.last.get(item.series_id)
        if previous is not None and current > previous + 1:
            return previous + 1, current - 1
        return None

    def observe(self, item: Candidate) -> tuple[int, int] | None:
        current = int(item.key)
        previous = self.last.get(item.series_id)
        if previous is not None and current > previous + 1:
            return previous + 1, current - 1
        if previous is None or current > previous:
            self.last[item.series_id] = current
        return None


async def recover_gap(
    symbol: str,
    start: int,
    end: int,
    *,
    spot: bool,
    allowed: Callable[[], None],
    fetch: Callable[[str, dict[str, Any]], Awaitable[list[dict[str, Any]]]],
    clock: Callable[[], datetime],
    max_pages: int = 10,
) -> list[Candidate]:
    if start > end or end - start + 1 > 1000 * max_pages:
        raise SourceUnavailable("gap outside bounded recovery")
    result: list[Candidate] = []
    expected = start
    for _ in range(max_pages):
        allowed()
        url, params = recovery_request(symbol, expected - 1, spot=spot)
        rows = await fetch(url, params)
        allowed()
        if len(rows) > 1000:
            raise SourceUnavailable("oversize recovery response")
        for row in rows:
            item = binance_rest_trade(symbol, row, clock(), spot=spot)
            key = int(item.key)
            if key > end:
                break
            if key != expected:
                raise SourceUnavailable("unresolved recovery gap")
            result.append(item)
            expected += 1
        if expected > end:
            return result
        if not rows:
            break
    raise SourceUnavailable("unresolved recovery gap")


async def reconnecting_trades(
    open_stream: Callable[[], AsyncIterator[Mapping[str, Any]]],
    allowed: Callable[[str], None],
    persist: Callable[[Candidate], Awaitable[None]],
    health: Callable[[str, str], Awaitable[None]],
    *,
    spot: bool,
    clock: Callable[[], datetime],
    recover: Callable[[str, int, int], Awaitable[list[Candidate]]],
    max_reconnects: int = 3,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    checkpoints: Mapping[str, int] | None = None,
    series_ids: tuple[str, ...] | None = None,
) -> None:
    """Sequential processing bounds memory. Unfilled gaps block the affected stream."""
    tracker = GapTracker(checkpoints)
    series = ["BITCOIN_BINANCE_SPOT"] if spot else [row[0] for row in FUTURES.values()]
    if series_ids is not None:
        if (
            not series_ids
            or len(set(series_ids)) != len(series_ids)
            or not set(series_ids) <= set(series)
        ):
            raise ValueError("invalid stream scope")
        series = list(series_ids)
    for attempt in range(max_reconnects + 1):
        for sid in series:
            allowed(sid)
        try:
            async for message in open_stream():
                item = binance_trade(message, clock(), spot=spot)
                allowed(item.series_id)
                gap = tracker.gap(item)
                if gap:
                    await health(item.series_id, "gap")
                    recovered = await recover(item.series_id, *gap)
                    if [int(x.key) for x in recovered] != list(range(gap[0], gap[1] + 1)):
                        raise SourceUnavailable("unresolved gap")
                    for row in recovered:
                        allowed(row.series_id)
                        if row.series_id != item.series_id:
                            raise SourceUnavailable("recovery instrument mismatch")
                        await persist(row)
                        tracker.observe(row)
                await persist(item)
                tracker.observe(item)
                await health(item.series_id, "healthy")
            raise ConnectionError("stream ended")
        except (ConnectionError, TimeoutError, SourceUnavailable) as exc:
            for sid in series:
                await health(sid, "disconnected")
            if isinstance(exc, FetchError) and exc.status not in (429, 500, 502, 503, 504):
                raise
            if attempt == max_reconnects:
                raise
            delay = (
                retry_after(attempt, exc.retry_header, clock())
                if isinstance(exc, FetchError)
                else min(60, 2**attempt)
            )
            await sleep(delay + random.random())
