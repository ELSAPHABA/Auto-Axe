"""Connect fake/authorized transport to the durable trade checkpoint and health store."""

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

import psycopg

from autoaxe.application.collection import reconnecting_trades
from autoaxe.application.market_worker import record_health
from autoaxe.domain.catalog import FUTURES
from autoaxe.domain.market import Candidate
from autoaxe.infrastructure.market_store import (
    PermissionDenied,
    gate,
    persist_trade,
    verify_connection,
)


async def run_stream(
    dsn: str,
    open_stream: Callable[[], AsyncIterator[Mapping[str, Any]]],
    recover: Callable[[str, int, int], Awaitable[list[Candidate]]],
    *,
    spot: bool,
    max_reconnects: int = 3,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], Awaitable[None]],
    futures_symbols: tuple[str, ...] | None = None,
) -> bool:
    """One bounded reconnect session. No implicit network access; transport is injected."""
    ids = ["BITCOIN_BINANCE_SPOT"] if spot else [row[0] for row in FUTURES.values()]
    if futures_symbols is not None:
        if spot or not futures_symbols or len(set(futures_symbols)) != len(futures_symbols):
            raise ValueError("invalid futures stream scope")
        if not set(futures_symbols) <= set(FUTURES):
            raise ValueError("unknown futures symbol")
        ids = [FUTURES[symbol][0] for symbol in futures_symbols]
    source = "binance_spot" if spot else "binance_futures"
    with psycopg.connect(dsn, autocommit=True) as leader:
        verify_connection(leader, write=True)
        lock_sql = (
            "SELECT pg_try_advisory_lock_shared(hashtextextended(%s,0))"
            if futures_symbols is not None
            else "SELECT pg_try_advisory_lock(hashtextextended(%s,0))"
        )
        lock = leader.execute(lock_sql, ("stream:" + source,)).fetchone()
        if not lock or not lock[0]:
            return False
        if futures_symbols is not None:
            for symbol in sorted(futures_symbols):
                lock = leader.execute(
                    "SELECT pg_try_advisory_lock(hashtextextended(%s,0))",
                    ("stream:binance_futures:" + symbol,),
                ).fetchone()
                if not lock or not lock[0]:
                    return False
        permissions = {sid: gate(leader, sid, "fetch")["permission_version"] for sid in ids}
        checkpoints: dict[str, int] = dict(
            leader.execute(
                "SELECT series_id,last_trade_id FROM market.stream_checkpoints "
                "WHERE series_id=ANY(%s)",
                (ids,),
            ).fetchall()
        )

        def allowed(sid: str) -> None:
            if (
                sid not in permissions
                or gate(leader, sid, "fetch")["permission_version"] != permissions[sid]
            ):
                raise PermissionDenied("stream permission changed")

        async def persist(item: Candidate) -> None:
            with psycopg.connect(dsn) as conn:
                conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("source:" + source,)
                )
                if (
                    gate(conn, item.series_id, "storage")["permission_version"]
                    != permissions[item.series_id]
                ):
                    raise PermissionDenied("stream permission changed")
                persist_trade(conn, item)

        async def health(sid: str, status: str) -> None:
            with psycopg.connect(dsn) as conn:
                record_health(conn, sid, status, "stream_session")

        try:
            await reconnecting_trades(
                open_stream,
                allowed,
                persist,
                health,
                spot=spot,
                clock=clock,
                recover=recover,
                max_reconnects=max_reconnects,
                sleep=sleep,
                checkpoints=checkpoints,
                series_ids=tuple(ids),
            )
        except PermissionDenied:
            for sid in ids:
                await health(sid, "blocked")
            raise
    return True
