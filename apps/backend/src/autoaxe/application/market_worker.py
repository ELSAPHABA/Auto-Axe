"""Fixture collection job orchestration and cross-DB relay; caller controls transports."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg import Connection

from autoaxe.application.collection import FetchError
from autoaxe.domain.catalog import catalog
from autoaxe.domain.market import Candidate, Quality, quality_at
from autoaxe.infrastructure.jobs import (
    StaleLease,
    accept,
    acknowledge,
    claim,
    enqueue,
    finish,
    pending,
)
from autoaxe.infrastructure.market_store import PermissionDenied, gate, ingest, verify_connection


def record_health(conn: Connection[Any], sid: str, status: str, reason: str) -> None:
    verify_connection(conn, write=True)
    if status not in {
        "healthy",
        "no_data",
        "no_update",
        "stale",
        "disconnected",
        "gap",
        "blocked",
        "schema_error",
        "manual_required",
        "session_closed",
        "unknown",
    }:
        raise ValueError("invalid health state")
    conn.execute(
        """INSERT INTO ops.collector_health(series_id,status,reason,checked_at)
        VALUES (%s,%s,%s,clock_timestamp()) ON CONFLICT(series_id) DO UPDATE SET
        status=EXCLUDED.status,reason=EXCLUDED.reason,checked_at=EXCLUDED.checked_at""",
        (sid, status, reason),
    )


def submit_collection(conn: Connection[Any], sid: str, owner: str, key: str) -> str:
    verify_connection(conn, write=True)
    gate(conn, sid, "fetch")
    return enqueue(conn, "collect", owner, key, {"series_id": sid})


def run_one(
    dsn: str,
    collect: Callable[[str], list[Candidate]],
    *,
    owner: str | None = None,
    series: list[str] | None = None,
    on_failure: Callable[[Connection[Any], str, Exception], None] | None = None,
) -> str | None:
    """Claim/commit, collect outside transaction, fence result in new transaction.

    Caller provides authorized adapter. This runner accepts at most 1000 results
    and stores result plus job status/outbox together. No retry for policy/schema errors.
    """
    with psycopg.connect(dsn) as conn:
        verify_connection(conn, write=True)
        job = claim(conn, owner=owner, series=series)
    if job is None:
        return None
    jid, token = str(job["id"]), str(job["lease_token"])
    sid = job["input_ref"].get("series_id")
    if job["kind"] != "collect" or not isinstance(sid, str):
        with psycopg.connect(dsn) as conn:
            return finish(conn, jid, token, success=False, error_code="unsupported_job")
    try:
        with psycopg.connect(dsn) as conn:
            permission = gate(conn, sid, "fetch")
        candidates = collect(sid)
        if len(candidates) > 1000 or any(row.series_id != sid for row in candidates):
            raise ValueError("bad candidate batch")
        with psycopg.connect(dsn) as conn:
            # finish() locks the live token and updates in this transaction;
            # no observations are accepted after cancellation, stale lease or revocation.
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ("source:" + permission["source_id"],),
            )
            current = gate(conn, sid, "storage")
            if current["permission_version"] != permission["permission_version"]:
                raise PermissionDenied("permission changed during collection")
            status = finish(
                conn, jid, token, success=True, result={"candidate_count": len(candidates)}
            )
            if status != "succeeded":
                return status
            inserted = sum(ingest(conn, row)[2] for row in candidates)
            if not candidates:
                health = "no_data"
            else:
                latest = max(
                    candidates, key=lambda row: (row.source_event_at or row.received_at, row.key)
                )
                quality = quality_at(latest, catalog()[sid], datetime.now(UTC))
                if latest.value is None:
                    health = "no_data"
                elif quality == Quality.STALE:
                    health = "stale"
                elif quality == Quality.UNKNOWN and not latest.metadata.get("official_daily"):
                    health = "unknown"
                else:
                    health = "healthy" if inserted else "no_update"
            record_health(conn, sid, health, "collection_finished")
            return status
    except StaleLease:
        return "lease_lost"
    except (ValueError, TimeoutError, ConnectionError, FetchError, KeyError, TypeError) as exc:
        with psycopg.connect(dsn) as conn:
            retryable = isinstance(exc, (TimeoutError, ConnectionError)) or (
                isinstance(exc, FetchError) and exc.status in (429, 500, 502, 503, 504)
            )
            code = (
                f"http_{exc.status}"
                if isinstance(exc, FetchError)
                else ("transport_error" if retryable else "policy_or_schema_error")
            )
            try:
                status = finish(
                    conn, jid, token, success=False, retryable=retryable, error_code=code
                )
            except StaleLease:
                return "lease_lost"
            if status != "cancelled" and on_failure:
                on_failure(conn, sid, exc)
            record_health(conn, sid, "disconnected" if retryable else "blocked", code)
            return status


def synthetic_collect(sid: str) -> list[Candidate]:
    if sid != "FIXTURE_PRICE":
        raise ValueError("network source unavailable in fixture runner")
    now = datetime.now(UTC)
    return [
        Candidate(sid, now.isoformat(), "123.45", now, now, now, Quality.VALID, {"synthetic": True})
    ]


def relay_batch(source_dsn: str, target_dsn: str, consumer: str, limit: int = 100) -> int:
    """Read unacked, commit receiver then ack producer; duplicate after crash is safe."""
    with psycopg.connect(source_dsn) as source:
        events = pending(source, consumer, limit)
    count = 0
    for event in events:
        with psycopg.connect(target_dsn) as target:
            row = target.execute("SELECT current_database(),current_user").fetchone()
            if not row or row[0] not in {
                "autoaxe_backtest",
                "autoaxe_dry_run",
                "autoaxe_paper_local",
                "autoaxe_paper_broker",
            }:
                raise ValueError("invalid fixture ingress target")
            if row[1] != f"{row[0]}_runtime":
                raise ValueError("invalid ingress role")
            result = accept(target, consumer, event)
        if result in {"accepted", "duplicate"}:
            with psycopg.connect(source_dsn) as source:
                acknowledge(source, consumer, event["event_id"])
            count += 1
    return count
