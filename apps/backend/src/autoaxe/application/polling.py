"""Durable scheduler, fixture-only executable entrypoint; no source activation here."""

from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg import Connection

from autoaxe.application.collection import FetchError
from autoaxe.application.market_worker import run_one, submit_collection
from autoaxe.domain.catalog import catalog
from autoaxe.domain.market import Candidate
from autoaxe.infrastructure.jobs import retry_after
from autoaxe.infrastructure.market_store import PermissionDenied, gate, verify_connection

# Poll interval is NOT TTL or an approved provider quota. External activation stays off.
CADENCE = {
    s.id: (300 if s.interval == "5m" else 3600 if s.interval == "1d" else 300)
    for s in catalog().values()
    if s.source_id != "pizzint"
    and s.id not in {"VIX", "VIX_YAHOO_WS"}  # dedicated quote worker
    and s.id not in {"WTI_YAHOO_FUTURES_WS", "BRENT_YAHOO_FUTURES_WS"}
    and s.symbol not in {"NVDA", "QLD"}
    and (s.source_id in {"yfinance", "treasury"} or s.interval == "5m")
}
CADENCE["FIXTURE_PRICE"] = 5
YAHOO_TREASURY_SERIES = frozenset({"UST_3M", "UST_5Y", "UST_10Y", "UST_30Y"})
CADENCE.update(dict.fromkeys(YAHOO_TREASURY_SERIES, 900))


def _open(conn: Connection[Any], sid: str, now: datetime) -> bool:
    try:
        info = gate(conn, sid, "fetch")
    except PermissionDenied:
        return False
    row = conn.execute(
        "SELECT permission_version,blocked,retry_at FROM ops.poll_circuits WHERE source_id=%s",
        (info["source_id"],),
    ).fetchone()
    return (
        not row
        or row[0] != info["permission_version"]
        or (not row[1] and (row[2] is None or row[2] <= now))
    )


def schedule_due(conn: Connection[Any], series: Iterable[str], now: datetime) -> list[str]:
    """Serialize scheduling, coalesce missed slots, never queue overlapping jobs."""
    verify_connection(conn, write=True)
    if now.utcoffset() is None:
        raise ValueError("aware clock required")
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('poll-schedule',0))")
    ids = []
    for sid in sorted(set(series)):
        if sid not in CADENCE:
            raise ValueError("not a polling series")
        if not _open(conn, sid, now):
            continue
        slot = int(now.timestamp()) // CADENCE[sid]
        old = conn.execute(
            "SELECT last_slot,last_enqueued_at FROM ops.poll_slots WHERE series_id=%s", (sid,)
        ).fetchone()
        # Old 300s Treasury slot numbers are incomparable with new 900s slots.
        # Keep the actual last enqueue time as the migration-safe cadence fence.
        if old and (
            (sid not in YAHOO_TREASURY_SERIES and slot <= old[0])
            or now < old[1] + timedelta(seconds=CADENCE[sid])
        ):
            continue
        owner = "poll:" + catalog()[sid].source_id
        active = conn.execute(
            """SELECT 1 FROM ops.jobs WHERE owner_ref=%s AND input_ref->>'series_id'=%s
            AND status IN ('queued','running','cancel_requested') LIMIT 1""",
            (owner, sid),
        ).fetchone()
        if active:
            continue
        key = f"{sid}:900s:{slot}" if sid in YAHOO_TREASURY_SERIES else f"{sid}:{slot}"
        ids.append(submit_collection(conn, sid, owner, key))
        conn.execute(
            """INSERT INTO ops.poll_slots VALUES (%s,%s,%s) ON CONFLICT(series_id)
            DO UPDATE SET last_slot=EXCLUDED.last_slot,
            last_enqueued_at=EXCLUDED.last_enqueued_at""",
            (sid, slot, now),
        )
    return ids


def record_failure(conn: Connection[Any], sid: str, exc: Exception) -> None:
    """Provider-wide cooldown, or circuit requiring a new permission version."""
    if not isinstance(exc, FetchError):
        return
    try:
        info = gate(conn, sid, "fetch")
    except PermissionDenied:
        return
    now = conn.execute("SELECT clock_timestamp()").fetchone()
    assert now is not None
    blocked = exc.status in (401, 403)
    delay = retry_after(1, exc.retry_header, now[0])
    # Extreme Retry-After must never overflow or cause an earlier retry.
    if delay > 604800:
        blocked = True
    until = None if blocked else now[0] + timedelta(seconds=delay)
    conn.execute(
        """INSERT INTO ops.poll_circuits VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT(source_id) DO UPDATE SET permission_version=EXCLUDED.permission_version,
        blocked=EXCLUDED.blocked,retry_at=EXCLUDED.retry_at,reason=EXCLUDED.reason""",
        (info["source_id"], info["permission_version"], blocked, until, f"http_{exc.status}"),
    )


def tick(
    dsn: str,
    series: Iterable[str],
    collect: Callable[[str], list[Candidate]],
    *,
    now: datetime | None = None,
    max_jobs: int = 64,
) -> dict[str, int]:
    """One bounded pass. A session advisory lock prevents parallel provider polls.
    The only CLI caller supplies synthetic_collect; tests can inject fixture parsers.
    """
    ids = sorted(set(series))
    if not 1 <= max_jobs <= 64 or any(sid not in CADENCE for sid in ids):
        raise ValueError("invalid polling scope")
    with psycopg.connect(dsn, autocommit=True) as leader:
        verify_connection(leader, write=True)
        locked = leader.execute(
            "SELECT pg_try_advisory_lock(hashtextextended('poll-leader',0))"
        ).fetchone()
        if not locked or not locked[0]:
            return {"scheduled": 0, "processed": 0}
        with leader.transaction():
            stamp = leader.execute("SELECT clock_timestamp()").fetchone()
            assert stamp is not None
            scheduled = schedule_due(leader, ids, now or stamp[0])
        processed = 0
        for source in sorted({catalog()[sid].source_id for sid in ids}):
            group = [sid for sid in ids if catalog()[sid].source_id == source]
            representative = group[0]
            while processed < max_jobs:
                clock = leader.execute("SELECT clock_timestamp()").fetchone()
                assert clock is not None
                if not _open(leader, representative, clock[0]):
                    break

                def scoped(sid: str) -> list[Candidate]:
                    if sid not in ids:
                        raise PermissionDenied("outside current polling scope")
                    return collect(sid)

                status = run_one(
                    dsn, scoped, owner="poll:" + source, series=group, on_failure=record_failure
                )
                if status is None:
                    break
                processed += 1
        return {"scheduled": len(scheduled), "processed": processed}
