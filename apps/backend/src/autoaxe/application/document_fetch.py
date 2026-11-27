"""One-shot approved document capture; never inserts reviewed financial values."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import psycopg
from psycopg import Connection

from autoaxe.application.official_macro import OfficialSourceError
from autoaxe.infrastructure.event_store import require_event_permission
from autoaxe.infrastructure.jobs import retry_after
from autoaxe.infrastructure.market_store import PermissionDenied, verify_connection

CADENCE = {"boj": 3600, "sec_edgar": 900}


def _grant(conn: Connection[Any], source: str) -> int:
    version = require_event_permission(conn, source)
    circuit = conn.execute(
        "SELECT permission_version,blocked,retry_at>clock_timestamp() "
        "FROM ops.poll_circuits WHERE source_id=%s",
        (source,),
    ).fetchone()
    if circuit and ((circuit[0] == version and circuit[1]) or circuit[2]):
        raise PermissionDenied("document source circuit open")
    return version


def capture_once[T](
    dsn: str,
    source: str,
    fetch: Callable[[Callable[[], None]], T],
    *,
    persist: Callable[[Connection[Any], T, int], None] | None = None,
) -> T:
    """Same source leader as official poller; commit reservation before network.

    All document operations share a per-source interval, including discovery,
    errors, process restarts and attempts to change the selected document.
    """
    if source not in CADENCE:
        raise ValueError("unsupported document source")
    seconds = CADENCE[source]
    with psycopg.connect(dsn, autocommit=True, connect_timeout=3) as conn:
        verify_connection(conn, write=True)
        leader = conn.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s,0))",
            ("official:" + source,),
        ).fetchone()
        if not leader or not leader[0]:
            raise PermissionDenied("official source busy")
        with conn.transaction():
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("source:" + source,)
            )
            version = _grant(conn, source)
            row = conn.execute(
                """INSERT INTO ops.official_poll_slots VALUES
                (%s,%s,clock_timestamp(),clock_timestamp()+make_interval(secs=>%s),%s)
                ON CONFLICT(task_id) DO UPDATE SET last_requested_at=EXCLUDED.last_requested_at,
                  next_requested_at=EXCLUDED.next_requested_at,
                  permission_version=EXCLUDED.permission_version
                WHERE ops.official_poll_slots.next_requested_at<=clock_timestamp()
                RETURNING permission_version""",
                ("document:" + source, source, seconds, version),
            ).fetchone()
            if row is None:
                raise PermissionDenied("document capture not due")

        def permit() -> None:
            if _grant(conn, source) != version:
                raise PermissionDenied("document permission changed")

        try:
            permit()
            result = fetch(permit)
            with conn.transaction():
                conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("source:" + source,)
                )
                permit()
                if persist is not None:
                    persist(conn, result, version)
            return result
        except OfficialSourceError as exc:
            with conn.transaction():
                conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("source:" + source,)
                )
                if require_event_permission(conn, source) != version:
                    raise PermissionDenied("document permission changed") from None
                now = conn.execute("SELECT clock_timestamp()").fetchone()
                assert now is not None
                delay = max(seconds, retry_after(1, exc.retry_header, now[0]))
                blocked = exc.status in (401, 403) or delay > 604800
                conn.execute(
                    """INSERT INTO ops.poll_circuits VALUES (%s,%s,%s,%s,%s)
                    ON CONFLICT(source_id) DO UPDATE SET
                      permission_version=EXCLUDED.permission_version,
                      blocked=EXCLUDED.blocked,retry_at=EXCLUDED.retry_at,
                      reason=EXCLUDED.reason""",
                    (
                        source,
                        version,
                        blocked,
                        None if blocked else now[0] + timedelta(seconds=delay),
                        "document_http_" + str(exc.status or "error"),
                    ),
                )
            raise
