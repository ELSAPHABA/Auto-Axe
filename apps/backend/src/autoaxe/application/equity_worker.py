"""Bounded Yahoo equity collection with revocation fences and durable samples."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import psycopg
from psycopg import Connection

from autoaxe.adapters.equity_yahoo import (
    Listen,
    fetch_daily,
    fetch_fundamentals,
    listen_volume,
    utc_now,
)
from autoaxe.application.collection import FetchError
from autoaxe.application.market_worker import record_health
from autoaxe.application.polling import record_failure
from autoaxe.domain.equity_samples import (
    FUNDAMENTAL_IDS,
    HISTORY_IDS,
    VOLUME_IDS,
    EquitySampler,
    fundamentals_candidate,
    history_candidates,
    volume_candidate,
)
from autoaxe.domain.market import Candidate
from autoaxe.domain.volume import SYMBOLS
from autoaxe.infrastructure.market_store import PermissionDenied, gate, ingest, verify_connection


def _version(conn: Connection[Any], ids: tuple[str, ...]) -> int:
    versions: set[int] = set()
    for sid in ids:
        for action in ("fetch", "storage"):
            row = gate(conn, sid, action)
            if row["source_id"] != "yfinance":
                raise PermissionDenied("wrong equity source")
            versions.add(int(row["permission_version"]))
    if len(versions) != 1:
        raise PermissionDenied("equity grant version mismatch")
    return versions.pop()


def _permit(conn: Connection[Any], ids: tuple[str, ...], version: int) -> None:
    if _version(conn, ids) != version:
        raise PermissionDenied("equity approval changed")
    circuit = conn.execute(
        "SELECT permission_version,blocked,retry_at>clock_timestamp() "
        "FROM ops.poll_circuits WHERE source_id='yfinance'"
    ).fetchone()
    if circuit and circuit[0] == version and (circuit[1] or circuit[2]):
        raise PermissionDenied("Yahoo circuit open")


def _save(conn: Connection[Any], rows: list[Candidate], ids: tuple[str, ...], version: int) -> None:
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('source:yfinance',0))")
        _permit(conn, ids, version)
        for row in rows:
            if row.series_id not in ids:
                raise ValueError("unexpected equity series")
            # One durable sample per second even after process restart.
            # Revisions of historical bars are intentional; local samples aren't.
            if (
                row.series_id in VOLUME_IDS
                and conn.execute(
                    "SELECT 1 FROM market.source_events WHERE series_id=%s AND source_event_key=%s",
                    (row.series_id, row.key),
                ).fetchone()
            ):
                continue
            ingest(conn, row)
            status = row.metadata.get("data_status", row.quality.value)
            record_health(
                conn,
                row.series_id,
                {"fresh": "healthy", "session_reset": "unknown", "valid": "healthy"}.get(
                    status, status
                ),
                "yahoo_equity_sample",
            )


async def sample_stream(
    listen: Listen,
    permit: Callable[[], None],
    save: Callable[[list[Candidate]], None],
    *,
    duration: float | None,
    sampler: EquitySampler | None = None,
    stopped: Callable[[], bool] = lambda: False,
    clock: Callable[[], datetime] = utc_now,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Independent monotonic sampler; skip missed slots, never fabricate backfill."""
    if duration is not None and not 1 <= duration <= 1800:
        raise ValueError("stream duration must be 1..1800 seconds")
    permit()
    sampler = sampler or EquitySampler()

    def handle(msg: dict[str, Any]) -> None:
        sampler.observe(msg, clock())

    def publish() -> None:
        permit()
        now = clock()
        save([volume_candidate(sampler.sample(s, now)) for s in SYMBOLS])

    task = asyncio.ensure_future(listen(permit, handle))
    start = monotonic()
    deadline = start + duration if duration is not None else float("inf")
    next_tick = start + 1
    try:
        while next_tick <= deadline and not stopped():
            await sleep(max(0, next_tick - monotonic()))
            if stopped():
                return
            if task.done():
                sampler.disconnect()
                publish()
                task.result()
                return
            publish()
            if monotonic() >= deadline:
                return
            # A slow write or sleep never causes a burst of historical samples.
            next_tick += max(1, int(monotonic() - next_tick) + 1)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def _reserve(conn: Connection[Any], ids: tuple[str, ...], version: int, interval: int) -> bool:
    """Persist the attempt before connecting; never duplicate a missed slot."""
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('source:yfinance',0))")
        _permit(conn, ids, version)
        if conn.execute(
            "SELECT 1 FROM ops.poll_slots WHERE series_id=ANY(%s) "
            "AND last_enqueued_at>clock_timestamp()-(%s * interval '1 second')",
            (list(ids), interval),
        ).fetchone():
            return False
        for sid in ids:
            conn.execute(
                """INSERT INTO ops.poll_slots VALUES
                (%s,floor(extract(epoch from clock_timestamp())/%s)::bigint,
                clock_timestamp())
                ON CONFLICT(series_id) DO UPDATE SET last_slot=EXCLUDED.last_slot,
                last_enqueued_at=EXCLUDED.last_enqueued_at""",
                (sid, interval),
            )
    return True


def _health(conn: Connection[Any], ids: tuple[str, ...], status: str, reason: str) -> None:
    with conn.transaction():
        for sid in ids:
            record_health(conn, sid, status, reason)


def _provider_error(
    conn: Connection[Any], ids: tuple[str, ...], version: int, exc: FetchError
) -> None:
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('source:yfinance',0))")
        if _version(conn, ids) != version:
            raise PermissionDenied("equity approval changed")
        record_failure(conn, ids[0], exc)
        for sid in ids:
            record_health(
                conn,
                sid,
                "blocked" if exc.status in (401, 403) else "disconnected",
                f"http_{exc.status}",
            )


async def run_volume(
    dsn: str,
    *,
    enabled: bool = False,
    duration: float = 60,
    continuous: bool = False,
    stopped: Callable[[], bool] = lambda: False,
) -> bool:
    """Dedicated one-shot or daemon; permission version is pinned for its lifetime."""
    if not enabled:
        raise PermissionDenied("Yahoo equity opt-in required")
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as conn:
        verify_connection(conn, write=True)
        locked = conn.execute(
            "SELECT pg_try_advisory_lock(hashtextextended('stream:yfinance:equity',0))"
        ).fetchone()
        if not locked or not locked[0]:
            return False
        ids = VOLUME_IDS
        sampler = EquitySampler()
        sampler.disconnect()
        failures = 0
        try:
            version = _version(conn, ids)

            def permit() -> None:
                _permit(conn, ids, version)

            async def backoff(seconds: float) -> None:
                end = time.monotonic() + seconds
                tick = time.monotonic()
                while tick < end and not stopped():
                    permit()
                    now = utc_now()
                    _save(
                        conn,
                        [volume_candidate(sampler.sample(s, now)) for s in SYMBOLS],
                        ids,
                        version,
                    )
                    tick += max(1, int(time.monotonic() - tick) + 1)
                    await asyncio.sleep(max(0, min(end, tick) - time.monotonic()))

            while not stopped():
                if not _reserve(conn, ids, version, 60):
                    if not continuous:
                        return False
                    await backoff(1)
                    continue
                sampler.reconnect()
                started = time.monotonic()
                try:
                    await sample_stream(
                        listen_volume,
                        permit,
                        lambda rows: _save(conn, rows, ids, version),
                        duration=None if continuous else duration,
                        sampler=sampler,
                        stopped=stopped,
                    )
                except FetchError as exc:
                    _provider_error(conn, ids, version, exc)
                    raise
                except (ConnectionError, TimeoutError, OSError):
                    if not continuous:
                        raise
                finally:
                    sampler.disconnect()
                _health(conn, ids, "disconnected", "yahoo_stream_closed")
                if not continuous or stopped():
                    return True
                # Long healthy connections reset backoff; repeated disconnects
                # cannot spin. Reservation also survives a process restart.
                failures = 0 if time.monotonic() - started >= 300 else min(3, failures + 1)
                await backoff(min(300, 60 * (2 ** max(0, failures - 1))))
        except PermissionDenied:
            _health(conn, ids, "blocked", "source_permission_required_or_changed")
            raise
    return True


def run_daily(
    dsn: str,
    *,
    enabled: bool = False,
    continuous: bool = False,
    stopped: Callable[[], bool] = lambda: False,
    wait: Callable[[float], Any] = time.sleep,
) -> bool:
    """One manual capture or 24-hour durable scheduler; no historical backdating."""
    if not enabled:
        raise PermissionDenied("Yahoo equity opt-in required")
    ids = HISTORY_IDS + FUNDAMENTAL_IDS
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as conn:
        verify_connection(conn, write=True)
        locked = conn.execute(
            "SELECT pg_try_advisory_lock(hashtextextended('poll:yfinance:equity',0))"
        ).fetchone()
        if not locked or not locked[0]:
            return False
        try:
            version = _version(conn, ids)

            def permit() -> None:
                _permit(conn, ids, version)

            while not stopped():
                if not _reserve(conn, ids, version, 86400):
                    if not continuous:
                        return False
                    wait(30)
                    continue
                try:
                    for symbol in SYMBOLS:
                        if stopped():
                            return True
                        daily = fetch_daily(symbol, permit)
                        rows = history_candidates(symbol, daily, utc_now())
                        if not rows:
                            raise ValueError("no valid historical bars")
                        data = fetch_fundamentals(symbol, permit)
                        rows.append(fundamentals_candidate(symbol, data, utc_now()))
                        _save(conn, rows, ids, version)
                except FetchError as exc:
                    _provider_error(conn, ids, version, exc)
                    raise
                except (ConnectionError, TimeoutError, OSError):
                    _health(conn, ids, "disconnected", "yahoo_daily_transport_error")
                    if not continuous:
                        raise
                if not continuous:
                    return True
                wait(30)
        except PermissionDenied:
            _health(conn, ids, "blocked", "source_permission_required_or_changed")
            raise
    return True
