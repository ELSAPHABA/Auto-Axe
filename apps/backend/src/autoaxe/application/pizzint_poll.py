"""Dedicated durable five-minute DOUGHCON collection, never a trading input."""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg import Connection

from autoaxe.application.collection import FetchError
from autoaxe.application.market_worker import record_health
from autoaxe.domain.market import Candidate, Quality
from autoaxe.infrastructure.jobs import retry_after
from autoaxe.infrastructure.market_store import PermissionDenied, gate, ingest, verify_connection

SERIES = "PENTAGON_PIZZA_PIZZINT"
PERIOD_SECONDS = 300
Fetch = Callable[[Callable[[], None]], Mapping[str, Any]]


def _permission(conn: Connection[Any]) -> int:
    fetch = gate(conn, SERIES, "fetch")
    storage = gate(conn, SERIES, "storage")
    if (
        fetch["source_id"] != "pizzint"
        or fetch["permission_version"] != storage["permission_version"]
    ):
        raise PermissionDenied("DOUGHCON source permission mismatch")
    return int(fetch["permission_version"])


def _clock(conn: Connection[Any]) -> datetime:
    row = conn.execute("SELECT clock_timestamp()").fetchone()
    assert row is not None
    return row[0].astimezone(UTC)  # type: ignore[no-any-return]


def _reserve(conn: Connection[Any]) -> int | str:
    """Commit an attempt before I/O. Crash/restart never replays a missed slot."""
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('source:pizzint',0))")
        try:
            version = _permission(conn)
        except PermissionDenied:
            record_health(conn, SERIES, "blocked", "source_permission_required")
            return "permission_required"
        now = _clock(conn)
        circuit = conn.execute(
            "SELECT permission_version,blocked,retry_at FROM ops.poll_circuits "
            "WHERE source_id='pizzint'"
        ).fetchone()
        if circuit and (
            (circuit[0] == version and circuit[1]) or (circuit[2] is not None and circuit[2] > now)
        ):
            return "cooldown"
        old = conn.execute(
            "SELECT last_enqueued_at FROM ops.poll_slots WHERE series_id=%s", (SERIES,)
        ).fetchone()
        if old and now < old[0] + timedelta(seconds=PERIOD_SECONDS):
            return "not_due"
        conn.execute(
            """INSERT INTO ops.poll_slots VALUES (%s,%s,%s)
               ON CONFLICT(series_id) DO UPDATE SET last_slot=EXCLUDED.last_slot,
               last_enqueued_at=EXCLUDED.last_enqueued_at""",
            (SERIES, int(now.timestamp()) // PERIOD_SECONDS, now),
        )
        return version


def _candidate(payload: Mapping[str, Any], received: datetime) -> Candidate:
    if (
        set(payload)
        != {"series_id", "value", "source_event_at", "quality", "automated_trading_allowed"}
        or payload["series_id"] != SERIES
        or payload["value"] not in ("1", "2", "3", "4", "5")
        or payload["quality"] != "manual_review_required"
        or payload["automated_trading_allowed"] is not False
        or not isinstance(payload["source_event_at"], str)
    ):
        raise ValueError("invalid DOUGHCON candidate")
    stamp = datetime.fromisoformat(payload["source_event_at"])
    if stamp.tzinfo is None or stamp > received:
        raise ValueError("invalid DOUGHCON timestamp")
    stamp = stamp.astimezone(UTC)
    # Informational, not a verified financial observation or a trading signal.
    return Candidate(
        SERIES,
        stamp.isoformat(),
        payload["value"],
        stamp,
        received,
        received,
        Quality.MANUAL_UNVERIFIED,
    )


def _failure(conn: Connection[Any], version: int, exc: Exception) -> str:
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('source:pizzint',0))")
        try:
            if _permission(conn) != version:
                raise PermissionDenied("source approval changed")
        except PermissionDenied:
            record_health(conn, SERIES, "blocked", "source_permission_changed")
            return "permission_changed"
        if isinstance(exc, FetchError):
            now = _clock(conn)
            delay = retry_after(1, exc.retry_header, now)
            blocked = exc.status in (401, 403) or delay > 604800
            retry = None if blocked else now + timedelta(seconds=max(PERIOD_SECONDS, delay))
            conn.execute(
                """INSERT INTO ops.poll_circuits VALUES ('pizzint',%s,%s,%s,%s)
                   ON CONFLICT(source_id) DO UPDATE SET
                   permission_version=EXCLUDED.permission_version,
                   blocked=EXCLUDED.blocked,retry_at=EXCLUDED.retry_at,reason=EXCLUDED.reason""",
                (version, blocked, retry, f"http_{exc.status}"),
            )
            record_health(
                conn, SERIES, "blocked" if blocked else "disconnected", f"http_{exc.status}"
            )
            return "http_error"
        if isinstance(exc, PermissionDenied):
            record_health(conn, SERIES, "blocked", "source_permission_changed")
            return "permission_changed"
        record_health(
            conn,
            SERIES,
            "disconnected" if isinstance(exc, OSError) else "schema_error",
            "transport_error" if isinstance(exc, OSError) else "invalid_response",
        )
        return "collection_failed"


def poll_once(dsn: str, fetch: Fetch) -> str:
    """One bounded attempt; one leader per database, no immediate retry or backfill."""
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as conn:
        verify_connection(conn, write=True)
        locked = conn.execute(
            "SELECT pg_try_advisory_lock(hashtextextended('poll:pizzint',0))"
        ).fetchone()
        if not locked or not locked[0]:
            return "busy"
        version = _reserve(conn)
        if isinstance(version, str):
            return version

        def permit() -> None:
            if _permission(conn) != version:
                raise PermissionDenied("source approval changed during request")

        try:
            permit()
            payload = fetch(permit)
            permit()
            item = _candidate(payload, datetime.now(UTC))
            with conn.transaction():
                conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('source:pizzint',0))")
                permit()
                _, _, inserted = ingest(conn, item)
                record_health(
                    conn, SERIES, "healthy" if inserted else "no_update", "collection_finished"
                )
            return "stored" if inserted else "no_update"
        except (FetchError, OSError, ValueError, RuntimeError) as exc:
            return _failure(conn, version, exc)
