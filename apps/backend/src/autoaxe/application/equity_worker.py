"""Bounded Yahoo equity collection with revocation fences and durable samples."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg import Connection

from autoaxe.adapters.equity_http import ApprovedHTTP, load_approved_http
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
from autoaxe.domain.equity_cache import (
    MAX_HISTORY,
    confirmed_cache,
    expected_sessions,
    feature_snapshot,
    missing_ranges,
)
from autoaxe.domain.equity_calendar import load_calendar
from autoaxe.domain.equity_samples import (
    FUNDAMENTAL_IDS,
    HISTORY_IDS,
    VOLUME_IDS,
    EquitySampler,
    fundamentals_candidate,
    history_candidates,
    volume_candidate,
)
from autoaxe.domain.market import Candidate, Quality
from autoaxe.domain.types import decimal_string
from autoaxe.domain.volume import NEW_YORK, SYMBOLS
from autoaxe.infrastructure.market_store import PermissionDenied, gate, ingest, verify_connection


def _version(conn: Connection[Any], ids: tuple[str, ...], *, fetch: bool = True) -> int:
    versions: set[int] = set()
    for sid in ids:
        for action in ("fetch", "storage") if fetch else ("storage",):
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
    if circuit and ((circuit[0] == version and circuit[1]) or circuit[2]):
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


def _local_bars(conn: Connection[Any], sid: str, now: datetime, version: int) -> list[Candidate]:
    mapping = int(gate(conn, sid)["mapping_version"])
    rows = conn.execute(
        """SELECT DISTINCT ON(source_event_key) source_event_key,value,received_at,
                  available_at,quality,metadata
           FROM market.observations
           WHERE series_id=%s AND permission_version=%s AND mapping_version=%s
             AND available_at<=%s AND ingested_at<=%s
           ORDER BY source_event_key DESC,revision DESC LIMIT %s""",
        (sid, version, mapping, now, now, MAX_HISTORY + 1),
    ).fetchall()
    if len(rows) > MAX_HISTORY:
        raise ValueError("equity cache exceeds bounded history")
    return [
        Candidate(
            sid,
            key,
            decimal_string(value) if value is not None else None,
            None,
            received,
            available,
            Quality(quality),
            metadata,
            mapping,
        )
        for key, value, received, available, quality, metadata in rows
    ]


def _fundamental_due(conn: Connection[Any], sid: str, now: datetime, version: int) -> bool:
    mapping = int(gate(conn, sid)["mapping_version"])
    row = conn.execute(
        """SELECT available_at FROM market.observations
           WHERE series_id=%s AND permission_version=%s AND mapping_version=%s
             AND available_at<=%s AND ingested_at<=%s
           ORDER BY available_at DESC,revision DESC LIMIT 1""",
        (sid, version, mapping, now, now),
    ).fetchone()
    return row is None or row[0] <= now - timedelta(days=1)


def daily_symbol(
    conn: Connection[Any],
    symbol: str,
    version: int,
    contract: ApprovedHTTP | None,
) -> bool:
    """Plan from local ledger before reserving any HTTP; one bounded pass."""
    sid, fid = f"{symbol}_DAILY_OHLCV", f"{symbol}_FUNDAMENTALS"
    ids = (sid, fid)
    now = utc_now()
    calendar = load_calendar(as_of=now.astimezone(NEW_YORK).date())
    local = _local_bars(conn, sid, now, version)
    generation = (
        contract.adjustment_generation
        if contract
        else (
            max(local, key=lambda row: row.available_at).metadata.get("adjustment_generation")
            if local
            else None
        )
    )
    cached = confirmed_cache(local, symbol, now, calendar, generation)
    expected = expected_sessions(symbol, now, calendar, cached)
    gaps = missing_ranges(expected, cached)
    fundamental_due = _fundamental_due(conn, fid, now, version)
    fresh: list[Candidate] = []
    remote = False
    if contract is not None and (gaps or (fundamental_due and symbol != "QLD")):
        request_ids = tuple(
            series
            for series, needed in ((sid, bool(gaps)), (fid, fundamental_due and symbol != "QLD"))
            if needed
        )

        def permit() -> None:
            _permit(conn, request_ids, version)
            for series in request_ids:
                if gate(conn, series, "fetch")["evidence_ref"] != contract.evidence_ref:
                    raise PermissionDenied("Yahoo HTTP grant evidence mismatch")

        permit()
        if _reserve(conn, request_ids, version, 86400):
            remote = True
            for start, end in gaps:
                daily = fetch_daily(symbol, permit, start=start, end=end, contract=contract)
                captured = utc_now()
                candidates = history_candidates(symbol, daily, captured, calendar=calendar)
                requested = {day.isoformat() for day in expected if start <= day <= end}
                for candidate in candidates:
                    if candidate.key not in requested:
                        raise ValueError("Yahoo response includes unrequested session")
                    # Incremental response features must never be published alone.
                    fresh.append(
                        replace(
                            candidate,
                            metadata={
                                **candidate.metadata,
                                "features": {},
                                "capture_permission_version": version,
                            },
                        )
                    )
                cached.update(confirmed_cache(fresh, symbol, captured, calendar, generation))
            if fundamental_due and symbol != "QLD":
                data = fetch_fundamentals(symbol, permit, contract=contract)
                fresh.append(fundamentals_candidate(symbol, data, utc_now()))
    if fundamental_due and symbol == "QLD":
        fresh.append(fundamentals_candidate(symbol, {}, utc_now()))
    now = utc_now()
    snapshot = feature_snapshot(expected, cached, now)
    if snapshot is not None and (
        snapshot.metadata != cached[max(cached)].metadata
        or any(r.series_id == sid and r.key == snapshot.key for r in fresh)
    ):
        fresh = [r for r in fresh if not (r.series_id == sid and r.key == snapshot.key)]
        fresh.append(snapshot)
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('source:yfinance',0))")
        if _version(conn, ids, fetch=False) != version:
            raise PermissionDenied("equity storage grant changed")
        if remote:
            permit()
        for row in fresh:
            ingest(conn, row)
        complete = bool(expected) and all(day in cached for day in expected)
        record_health(
            conn,
            sid,
            "unknown" if complete else "gap",
            "cache_complete" if complete else "confirmed_daily_sessions_missing",
        )
        if fundamental_due and symbol != "QLD" and not any(r.series_id == fid for r in fresh):
            record_health(conn, fid, "no_data", "fundamental_refresh_unavailable")
    return complete


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
    # Local authorized cache calculations work even without an HTTP contract.
    contract = load_approved_http()
    ids = HISTORY_IDS + FUNDAMENTAL_IDS
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as conn:
        verify_connection(conn, write=True)
        locked = conn.execute(
            "SELECT pg_try_advisory_lock(hashtextextended('poll:yfinance:equity',0))"
        ).fetchone()
        if not locked or not locked[0]:
            return False
        try:
            version = _version(conn, ids, fetch=False)

            while not stopped():
                complete = True
                try:
                    for symbol in SYMBOLS:
                        if stopped():
                            return True
                        complete = daily_symbol(conn, symbol, version, contract) and complete
                except FetchError as exc:
                    _provider_error(conn, ids, version, exc)
                    raise
                except (ConnectionError, TimeoutError, OSError):
                    _health(conn, ids, "disconnected", "yahoo_daily_transport_error")
                    if not continuous:
                        raise
                if not continuous:
                    return complete
                wait(30)
        except PermissionDenied:
            _health(conn, ids, "blocked", "source_permission_required_or_changed")
            raise
    return True
