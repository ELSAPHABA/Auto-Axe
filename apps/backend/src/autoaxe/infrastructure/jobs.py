"""Durable leased jobs and at-least-once local inbox. No trade retry logic."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from autoaxe.domain.canonical import canonical_sha256
from autoaxe.infrastructure.market_store import emit


def enqueue(
    conn: Connection[Any],
    kind: str,
    owner: str,
    key: str,
    payload: dict[str, Any],
    max_attempts: int = 3,
) -> str:
    if kind not in {"collect", "manual_review", "refresh"}:
        raise ValueError("unsupported job kind")
    digest = canonical_sha256(payload)
    jid = str(uuid4())
    row = conn.execute(
        """INSERT INTO ops.jobs(id,kind,owner_ref,input_ref,input_version,idempotency_key,
        payload_hash,status,max_attempts,available_at)
        VALUES (%s,%s,%s,%s,1,%s,%s,'queued',%s,clock_timestamp())
        ON CONFLICT(owner_ref,kind,idempotency_key) DO NOTHING RETURNING id""",
        (jid, kind, owner, Jsonb(payload), key, digest, max_attempts),
    ).fetchone()
    if row:
        emit(conn, "job.status.changed", "job", jid, 1, {"job_id": jid, "status": "queued"})
        return jid
    old = conn.execute(
        "SELECT id,payload_hash FROM ops.jobs "
        "WHERE owner_ref=%s AND kind=%s AND idempotency_key=%s",
        (owner, kind, key),
    ).fetchone()
    if not old or old[1] != digest:
        raise ValueError("idempotency payload mismatch")
    return str(old[0])


def claim(conn: Connection[Any], lease_seconds: int = 30) -> dict[str, Any] | None:
    if not 1 <= lease_seconds <= 600:
        raise ValueError("invalid lease")
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            """SELECT * FROM ops.jobs WHERE
            (status='queued' AND available_at<=clock_timestamp()) OR
            (status IN ('running','cancel_requested') AND lease_until<=clock_timestamp())
            ORDER BY available_at,id FOR UPDATE SKIP LOCKED LIMIT 1"""
        ).fetchone()
        if not row:
            return None
        jid = str(row["id"])
        if row["status"] != "queued":
            cur.execute(
                """UPDATE ops.job_attempts SET ended_at=clock_timestamp(),outcome='lease_expired'
                WHERE job_id=%s AND attempt=%s AND ended_at IS NULL""",
                (jid, row["attempt"]),
            )
        if row["status"] == "cancel_requested" or row["attempt"] >= row["max_attempts"]:
            status = "cancelled" if row["status"] == "cancel_requested" else "failed"
            cur.execute(
                """UPDATE ops.jobs SET status=%s,finished_at=clock_timestamp(),
                lease_token=NULL,lease_until=NULL,version=version+1 WHERE id=%s""",
                (status, jid),
            )
            emit(
                conn,
                "job.status.changed",
                "job",
                jid,
                row["version"] + 1,
                {"job_id": jid, "status": status},
            )
            return None
        token = str(uuid4())
        updated = cur.execute(
            """UPDATE ops.jobs SET status='running',attempt=attempt+1,lease_token=%s,
            lease_until=clock_timestamp()+make_interval(secs=>%s),
            heartbeat_at=clock_timestamp(),version=version+1 WHERE id=%s RETURNING *""",
            (token, lease_seconds, jid),
        ).fetchone()
        assert updated is not None
        cur.execute(
            "INSERT INTO ops.job_attempts(job_id,attempt,lease_token) VALUES (%s,%s,%s)",
            (jid, updated["attempt"], token),
        )
        emit(
            conn,
            "job.status.changed",
            "job",
            jid,
            updated["version"],
            {"job_id": jid, "status": "running"},
        )
        return updated


def heartbeat(conn: Connection[Any], jid: str, token: str, lease_seconds: int = 30) -> bool:
    if not 1 <= lease_seconds <= 600:
        raise ValueError("invalid lease")
    return (
        conn.execute(
            """UPDATE ops.jobs SET heartbeat_at=clock_timestamp(),
        lease_until=clock_timestamp()+make_interval(secs=>%s)
        WHERE id=%s AND lease_token=%s AND status='running' AND lease_until>clock_timestamp()""",
            (lease_seconds, jid, token),
        ).rowcount
        == 1
    )


def finish(
    conn: Connection[Any],
    jid: str,
    token: str,
    *,
    success: bool,
    result: dict[str, Any] | None = None,
    retryable: bool = False,
    error_code: str | None = None,
) -> str:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            """SELECT * FROM ops.jobs WHERE id=%s AND lease_token=%s
            AND status IN ('running','cancel_requested') AND lease_until>clock_timestamp()
            FOR UPDATE""",
            (jid, token),
        ).fetchone()
        if not row:
            raise ValueError("stale lease")
        status = "succeeded" if success else "failed"
        if row["status"] == "cancel_requested":
            status = "cancelled"
        elif not success and retryable and row["attempt"] < row["max_attempts"]:
            status = "queued"
        delay = min(300, 2 ** row["attempt"]) if status == "queued" else 0
        cur.execute(
            """UPDATE ops.jobs SET status=%s,result_ref=%s,error_code=%s,
            available_at=clock_timestamp()+make_interval(secs=>%s),lease_token=NULL,
            lease_until=NULL,version=version+1,finished_at=CASE WHEN %s='queued' THEN NULL
            ELSE clock_timestamp() END,progress=CASE WHEN %s='succeeded' THEN 100 ELSE progress END
            WHERE id=%s""",
            (
                status,
                Jsonb(result) if result is not None else None,
                error_code,
                delay,
                status,
                status,
                jid,
            ),
        )
        cur.execute(
            """UPDATE ops.job_attempts SET ended_at=clock_timestamp(),outcome=%s
            WHERE job_id=%s AND attempt=%s""",
            (status, jid, row["attempt"]),
        )
        emit(
            conn,
            "job.status.changed",
            "job",
            jid,
            row["version"] + 1,
            {"job_id": jid, "status": status},
        )
        return status


def pending(conn: Connection[Any], consumer: str, limit: int = 100) -> list[dict[str, Any]]:
    if not 1 <= limit <= 1000:
        raise ValueError("invalid relay batch")
    return [
        row[0]
        for row in conn.execute(
            """SELECT envelope FROM ops.outbox o WHERE NOT EXISTS
        (SELECT 1 FROM ops.outbox_delivery d WHERE d.consumer=%s AND d.event_id=o.event_id)
        ORDER BY aggregate_type,aggregate_id,aggregate_version LIMIT %s""",
            (consumer, limit),
        ).fetchall()
    ]


def accept(conn: Connection[Any], consumer: str, event: dict[str, Any]) -> str:
    from pydantic import TypeAdapter

    from autoaxe.adapters.contracts import Event

    parsed = TypeAdapter(Event).validate_python(event)
    event = parsed.model_dump(mode="json")
    ident = (consumer, event["origin_db"], event["aggregate_type"], event["aggregate_id"])
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        ("inbox:" + canonical_sha256(ident),),
    )
    existing = conn.execute(
        "SELECT envelope FROM ops.consumer_inbox WHERE consumer=%s AND event_id=%s",
        (consumer, event["event_id"]),
    ).fetchone()
    if existing:
        if existing[0] != event:
            raise ValueError("event id collision")
        return "duplicate"
    current = conn.execute(
        """SELECT aggregate_version FROM ops.checkpoints
        WHERE consumer=%s AND origin_db=%s AND aggregate_type=%s AND aggregate_id=%s""",
        ident,
    ).fetchone()
    previous = current[0] if current else 0
    if event["aggregate_version"] != previous + 1:
        return "gap" if event["aggregate_version"] > previous else "late"
    conn.execute(
        """INSERT INTO ops.consumer_inbox(consumer,event_id,origin_db,aggregate_type,
        aggregate_id,aggregate_version,envelope) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (consumer, event["event_id"], *ident[1:], event["aggregate_version"], Jsonb(event)),
    )
    conn.execute(
        """INSERT INTO ops.checkpoints VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT(consumer,origin_db,aggregate_type,aggregate_id)
        DO UPDATE SET aggregate_version=EXCLUDED.aggregate_version""",
        (*ident, event["aggregate_version"]),
    )
    return "accepted"


def acknowledge(conn: Connection[Any], consumer: str, event_id: str) -> None:
    conn.execute(
        """INSERT INTO ops.outbox_delivery(consumer,event_id) VALUES (%s,%s)
        ON CONFLICT DO NOTHING""",
        (consumer, event_id),
    )


def retry_after(attempt: int, header: str | None, now: datetime) -> float:
    """Honor Retry-After (including HTTP date); no retry sooner than instructed."""
    from email.utils import parsedate_to_datetime

    base = float(min(300, 2 ** min(attempt, 8)))
    if header:
        try:
            delay = float(header)
        except ValueError:
            try:
                delay = (parsedate_to_datetime(header) - now).total_seconds()
            except (TypeError, ValueError, OverflowError):
                return base
        if delay >= 0 and delay != float("inf"):
            return max(base, delay)
    return base


def cancel(conn: Connection[Any], jid: str, owner: str) -> str:
    row = conn.execute(
        "SELECT status,version FROM ops.jobs WHERE id=%s AND owner_ref=%s FOR UPDATE", (jid, owner)
    ).fetchone()
    if not row:
        raise KeyError(jid)
    if row[0] not in ("queued", "running"):
        return str(row[0])
    status = "cancelled" if row[0] == "queued" else "cancel_requested"
    conn.execute(
        """UPDATE ops.jobs SET status=%s,version=version+1,
        finished_at=CASE WHEN %s='cancelled' THEN clock_timestamp() ELSE NULL END WHERE id=%s""",
        (status, status, jid),
    )
    emit(conn, "job.status.changed", "job", jid, row[1] + 1, {"job_id": jid, "status": status})
    return status
