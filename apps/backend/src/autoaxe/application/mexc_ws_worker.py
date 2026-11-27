"""Dedicated bounded Protobuf sessions with durable reservation and grant fences."""

import math
from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg import Connection

from autoaxe.adapters.mexc_ws import MAX_MESSAGES, SCHEMA_COMMIT, SERIES_ID, SYMBOL
from autoaxe.application.collection import FetchError, SourceUnavailable
from autoaxe.application.market_worker import record_health
from autoaxe.domain.market import Candidate, Quality
from autoaxe.infrastructure.jobs import retry_after
from autoaxe.infrastructure.market_store import PermissionDenied, gate, ingest, verify_connection

PERIOD_SECONDS = 300
Stream = Callable[[Callable[[], None]], AsyncGenerator[Candidate, None]]


class SessionStopped(Exception):
    """Local stop request; no new provider I/O."""


def _clock(conn: Connection[Any]) -> datetime:
    row = conn.execute("SELECT clock_timestamp()").fetchone()
    assert row is not None
    return row[0]  # type: ignore[no-any-return]


def _source_lock(conn: Connection[Any]) -> None:
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('source:mexc',0))")


def _permission(conn: Connection[Any]) -> int:
    fetch = gate(conn, SERIES_ID, "fetch")
    storage = gate(conn, SERIES_ID, "storage")
    if (
        fetch["source_id"] != "mexc"
        or storage["source_id"] != "mexc"
        or fetch["permission_version"] != storage["permission_version"]
        or fetch["mapping_version"] != 1
        or storage["mapping_version"] != 1
    ):
        raise PermissionDenied("MEXC permission or mapping mismatch")
    return int(fetch["permission_version"])


def _cooldown(conn: Connection[Any], version: int, now: datetime) -> bool:
    row = conn.execute(
        "SELECT permission_version,blocked,retry_at FROM ops.poll_circuits WHERE source_id='mexc'"
    ).fetchone()
    # A new explicit approval can clear a policy block, but never shorten
    # an outstanding rate-limit delay.
    return bool(row and ((row[0] == version and row[1]) or (row[2] and row[2] > now)))


def _permit(conn: Connection[Any], version: int) -> None:
    if _permission(conn) != version or _cooldown(conn, version, _clock(conn)):
        raise PermissionDenied("MEXC grant changed or circuit open")


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
                raise PermissionDenied("MEXC approval changed")
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
            retry_at = None if blocked else now + timedelta(seconds=max(PERIOD_SECONDS, delay))
            conn.execute(
                """INSERT INTO ops.poll_circuits VALUES ('mexc',%s,%s,%s,%s)
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
                """INSERT INTO ops.poll_circuits VALUES ('mexc',%s,true,NULL,'invalid_response')
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
        or item.metadata.get("instrument_type") != "index_linked_perpetual"
        or item.metadata.get("quote_currency") != "USDT"
        or item.metadata.get("settlement_currency") != "USDT"
        or item.metadata.get("session_verified") is not False
        or item.metadata.get("live_verified") is not False
        or item.metadata.get("provenance") != "mexc_futures_protobuf_ticker"
        or item.metadata.get("schema_commit") != SCHEMA_COMMIT
        or item.metadata.get("timestamp_semantics") != "provider_ticker_timestamp"
    ):
        raise ValueError("unexpected MEXC Protobuf ticker")
    return item


async def run_session(
    dsn: str,
    stream: Stream,
    *,
    enabled: bool = False,
    stopped: Callable[[], bool] = lambda: False,
) -> str:
    if not enabled:
        raise PermissionDenied("MEXC Protobuf opt-in required")
    if stopped():
        return "stopped"
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as conn:
        verify_connection(conn, write=True)
        locked = conn.execute(
            "SELECT pg_try_advisory_lock(hashtextextended('poll:mexc_ws',0))"
        ).fetchone()
        if not locked or not locked[0]:
            return "busy"
        version = reserve(conn)
        if isinstance(version, str):
            return version

        def permit() -> None:
            if stopped():
                raise SessionStopped
            _permit(conn, version)

        try:
            permit()
            seen = inserted = 0
            async with aclosing(stream(permit)) as rows:
                async for row in rows:
                    seen += 1
                    if seen > MAX_MESSAGES:
                        raise ValueError("MEXC session message bound exceeded")
                    item = _candidate(row)
                    with conn.transaction():
                        _source_lock(conn)
                        permit()
                        _, _, new = ingest(conn, item)
                        inserted += int(new)
                        record_health(conn, SERIES_ID, "unknown", "protobuf_ticker_unverified")
            with conn.transaction():
                _source_lock(conn)
                permit()
                if not seen:
                    record_health(conn, SERIES_ID, "unknown", "no_ticker_in_bounded_session")
            return "stored" if inserted else "no_update" if seen else "no_data"
        except SessionStopped:
            return "stopped"
        except (FetchError, SourceUnavailable, OSError, ValueError) as exc:
            return _failure(conn, version, exc)
