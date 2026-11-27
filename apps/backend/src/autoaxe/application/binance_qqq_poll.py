"""Dedicated durable 5-minute REST snapshot collector; no WS or trade path."""

import math
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

import httpx
import psycopg
from psycopg import Connection

from autoaxe.adapters.binance_qqq_rest import SERIES_ID, SYMBOL
from autoaxe.application.collection import FetchError, SourceUnavailable
from autoaxe.application.market_worker import record_health
from autoaxe.domain.market import Candidate, Quality
from autoaxe.infrastructure.jobs import retry_after
from autoaxe.infrastructure.market_store import PermissionDenied, gate, ingest, verify_connection

PERIOD_SECONDS = 300
Fetch = Callable[[Callable[[], None]], Awaitable[Candidate]]


def _clock(conn: Connection[Any]) -> datetime:
    row = conn.execute("SELECT clock_timestamp()").fetchone()
    assert row is not None
    return row[0]  # type: ignore[no-any-return]


def _source_lock(conn: Connection[Any]) -> None:
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('source:binance_futures',0))")


def _permission(conn: Connection[Any]) -> int:
    fetch = gate(conn, SERIES_ID, "fetch")
    storage = gate(conn, SERIES_ID, "storage")
    if (
        fetch["source_id"] != "binance_futures"
        or storage["source_id"] != "binance_futures"
        or fetch["permission_version"] != storage["permission_version"]
        or fetch["mapping_version"] != 1
        or storage["mapping_version"] != 1
    ):
        raise PermissionDenied("Binance QQQ permission or mapping mismatch")
    return int(fetch["permission_version"])


def _cooldown(conn: Connection[Any], version: int, now: datetime) -> bool:
    row = conn.execute(
        "SELECT permission_version,blocked,retry_at FROM ops.poll_circuits "
        "WHERE source_id='binance_futures'"
    ).fetchone()
    # A new explicit approval can clear a policy block, but never shorten
    # an outstanding rate-limit delay.
    return bool(row and ((row[0] == version and row[1]) or (row[2] and row[2] > now)))


def _permit(conn: Connection[Any], version: int) -> None:
    if _permission(conn) != version or _cooldown(conn, version, _clock(conn)):
        raise PermissionDenied("Binance QQQ grant changed or circuit open")


def reserve(conn: Connection[Any]) -> int | str:
    """Commit reservation before the first request, never replay missed slots."""
    with conn.transaction():
        _source_lock(conn)
        try:
            version = _permission(conn)
        except PermissionDenied:
            record_health(conn, SERIES_ID, "blocked", "source_permission_required")
            return "permission_required"
        now = _clock(conn)
        if _cooldown(conn, version, now):
            return "cooldown"
        old = conn.execute(
            "SELECT last_enqueued_at FROM ops.poll_slots WHERE series_id=%s", (SERIES_ID,)
        ).fetchone()
        if old and now < old[0] + timedelta(seconds=PERIOD_SECONDS):
            return "not_due"
        conn.execute(
            """INSERT INTO ops.poll_slots VALUES (%s,%s,%s)
               ON CONFLICT(series_id) DO UPDATE SET last_slot=EXCLUDED.last_slot,
               last_enqueued_at=EXCLUDED.last_enqueued_at""",
            (SERIES_ID, int(now.timestamp()) // PERIOD_SECONDS, now),
        )
        return version


def _failure(conn: Connection[Any], version: int, exc: Exception) -> str:
    with conn.transaction():
        _source_lock(conn)
        try:
            if _permission(conn) != version:
                raise PermissionDenied("Binance QQQ approval changed")
        except PermissionDenied:
            record_health(conn, SERIES_ID, "blocked", "source_permission_changed")
            return "permission_changed"
        if isinstance(exc, PermissionDenied):
            record_health(conn, SERIES_ID, "blocked", "source_permission_or_circuit_changed")
            return "permission_changed"
        if _cooldown(conn, version, _clock(conn)):
            record_health(conn, SERIES_ID, "blocked", "source_circuit_open")
            return "cooldown"
        if isinstance(exc, FetchError):
            now = _clock(conn)
            delay = retry_after(1, exc.retry_header, now)
            nonfinite_header = False
            if exc.retry_header is not None:
                try:
                    nonfinite_header = not math.isfinite(float(exc.retry_header))
                except ValueError:
                    pass
            blocked = (
                exc.status not in (429, 500, 502, 503, 504) or delay > 604800 or nonfinite_header
            )
            # 418 is an IP ban; a new approval alone must not shorten it.
            if exc.status == 418:
                delay = max(delay, 259200)
            retry_at = (
                now + timedelta(seconds=max(PERIOD_SECONDS, delay))
                if not blocked or (exc.status == 418 and delay <= 604800 and not nonfinite_header)
                else None
            )
            conn.execute(
                """INSERT INTO ops.poll_circuits VALUES ('binance_futures',%s,%s,%s,%s)
                   ON CONFLICT(source_id) DO UPDATE SET
                   permission_version=EXCLUDED.permission_version,blocked=EXCLUDED.blocked,
                   retry_at=EXCLUDED.retry_at,reason=EXCLUDED.reason""",
                (version, blocked, retry_at, f"http_{exc.status}"),
            )
            record_health(
                conn, SERIES_ID, "blocked" if blocked else "disconnected", f"http_{exc.status}"
            )
            return "http_error"
        # Schema/instrument changes fail closed until an explicit new approval.
        if isinstance(exc, (ValueError, SourceUnavailable)):
            conn.execute(
                """INSERT INTO ops.poll_circuits
                   VALUES ('binance_futures',%s,true,NULL,'invalid_response')
                   ON CONFLICT(source_id) DO UPDATE SET
                   permission_version=EXCLUDED.permission_version,blocked=true,
                   retry_at=NULL,reason=EXCLUDED.reason""",
                (version,),
            )
            record_health(conn, SERIES_ID, "schema_error", "invalid_or_unavailable_contract")
        else:
            record_health(conn, SERIES_ID, "disconnected", "transport_error")
        return "collection_failed"


def _candidate(item: Candidate) -> Candidate:
    if (
        item.series_id != SERIES_ID
        or item.mapping_version != 1
        or item.quality != Quality.UNKNOWN
        or item.value is None
        or item.source_event_at is None
        or item.metadata.get("symbol") != SYMBOL
        or item.metadata.get("instrument_type") != "etf_linked_perpetual"
        or item.metadata.get("quote_currency") != "USDT"
        or item.metadata.get("settlement_currency") != "USDT"
        or item.metadata.get("session_verified") is not False
        or item.metadata.get("live_verified") is not False
        or item.metadata.get("provenance") != "binance_qqq_rest_candidate"
    ):
        raise ValueError("unexpected Binance QQQ snapshot")
    return item


async def poll_once(dsn: str, fetch: Fetch, *, enabled: bool = False) -> str:
    if not enabled:
        raise PermissionDenied("Binance QQQ REST opt-in required")
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as conn:
        verify_connection(conn, write=True)
        locked = conn.execute(
            "SELECT pg_try_advisory_lock(hashtextextended('poll:binance_qqq',0))"
        ).fetchone()
        if not locked or not locked[0]:
            return "busy"
        version = reserve(conn)
        if isinstance(version, str):
            return version

        def permit() -> None:
            _permit(conn, version)

        try:
            permit()
            item = _candidate(await fetch(permit))
            with conn.transaction():
                _source_lock(conn)
                permit()
                _, _, inserted = ingest(conn, item)
                # Successful transport never establishes freshness or session.
                record_health(conn, SERIES_ID, "unknown", "rest_snapshot_unverified")
            return "stored" if inserted else "no_update"
        except (FetchError, SourceUnavailable, httpx.HTTPError, OSError, ValueError) as exc:
            return _failure(conn, version, exc)
