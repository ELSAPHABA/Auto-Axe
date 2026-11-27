"""Durable private scrape job lease/fence; quarantines results instead of auto-ingesting."""

import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from autoaxe.domain.canonical import canonical_sha256
from autoaxe.domain.catalog import SOURCE_URLS
from autoaxe.infrastructure.market_store import PermissionDenied, verify_connection
from autoaxe.infrastructure.sessions import digest

SOURCES = {"cnn", "pizzint", "dramexchange", "seibro", "naver"}


def parameters(source: str, values: dict[str, str]) -> dict[str, str]:
    if source not in SOURCES:
        raise ValueError("unregistered scrape source")
    if source != "seibro":
        if values:
            raise ValueError("unexpected parameters")
        return {}
    if set(values) != {"country", "period", "basis"}:
        raise ValueError("SEIBro query must use fixed enumerations")
    if values["country"] not in {"US", "ALL", "HK", "CN", "JP", "VN"}:
        raise ValueError("unknown settlement country")
    if values["period"] not in {"1", "2", "3", "4", "5"}:
        raise ValueError("unknown settlement period")
    if values["basis"] not in {"1", "2", "3", "4"}:
        raise ValueError("unknown settlement basis")
    return dict(values)


def permission(conn: Connection[Any], source: str) -> int:
    if source not in SOURCES or source not in SOURCE_URLS:
        raise PermissionDenied("unregistered source")
    # PizzINT public API is an allowable source under its published terms.
    # Do not infer homepage HTML scraping permission from this broker approval.
    # The API-only source adapter pins /api/dashboard-data, not the homepage.
    row = conn.execute(
        """SELECT permission_status,enabled,allow_fetch,allow_storage,free_only,
        verified_at,evidence_ref,permission_version
        FROM catalog.source_registry WHERE source_id=%s""",
        (source,),
    ).fetchone()
    if not row or row[:5] != ("approved", True, True, True, True) or row[5] is None or not row[6]:
        raise PermissionDenied("scrape source not authorized")
    return int(row[7])


@dataclass(frozen=True)
class Lease:
    job_id: str
    source_id: str
    adapter_version: int
    schema_version: int
    params: dict[str, str]
    nonce: str
    lease_token: str
    deadline_at: datetime
    expires_at: datetime
    permission_version: int


def submit(
    conn: Connection[Any],
    source: str,
    query: dict[str, str],
    key: str,
    deadline: datetime,
    *,
    adapter_version: int = 1,
) -> str:
    verify_connection(conn, write=True)
    query = parameters(source, query)
    if not key or len(key) > 128 or adapter_version != 1:
        raise ValueError("invalid scrape key/version")
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("source:" + source,))
    version = permission(conn, source)
    current = conn.execute("SELECT clock_timestamp()").fetchone()
    assert current is not None
    if not current[0] < deadline <= current[0] + timedelta(minutes=5):
        raise ValueError("invalid scrape deadline")
    job_id = str(uuid4())
    row = conn.execute(
        """INSERT INTO ops.scrape_jobs
        (id,source_id,adapter_version,schema_version,params,idempotency_key,
        permission_version,status,nonce_hash,deadline_at)
        VALUES (%s,%s,%s,1,%s,%s,%s,'queued',%s,%s)
        ON CONFLICT(source_id,idempotency_key) DO NOTHING RETURNING id""",
        (
            job_id,
            source,
            adapter_version,
            Jsonb(query),
            key,
            version,
            digest(secrets.token_urlsafe(32)),
            deadline,
        ),
    ).fetchone()
    if row:
        return str(row[0])
    existing = conn.execute(
        "SELECT id,params,adapter_version FROM ops.scrape_jobs "
        "WHERE source_id=%s AND idempotency_key=%s",
        (source, key),
    ).fetchone()
    if not existing or existing[1] != query or existing[2] != adapter_version:
        raise ValueError("idempotency conflict")
    return str(existing[0])


def claim(conn: Connection[Any], *, source: str, lease_seconds: int = 30) -> Lease | None:
    verify_connection(conn, write=True)
    if not 1 <= lease_seconds <= 60:
        raise ValueError("invalid scrape lease")
    params: tuple[str, ...] = (source,)
    if source not in SOURCES:
        raise PermissionDenied("unregistered source")
    with conn.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            """SELECT * FROM ops.scrape_jobs WHERE source_id=%s
            AND deadline_at>clock_timestamp() AND attempt<max_attempts
            AND (status='queued' OR
            (status='leased' AND lease_expires_at<=clock_timestamp()))
            ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1""",
            params,
        ).fetchone()
        if row is None:
            return None
        version = permission(conn, source)
        if version != row["permission_version"]:
            cursor.execute(
                "UPDATE ops.scrape_jobs SET status='revoked' WHERE id=%s",
                (row["id"],),
            )
            return None
        nonce, token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        clock = conn.execute("SELECT clock_timestamp()").fetchone()
        assert clock is not None
        expiry = min(clock[0] + timedelta(seconds=lease_seconds), row["deadline_at"])
        cursor.execute(
            """UPDATE ops.scrape_jobs SET status='leased',attempt=attempt+1,
            nonce_hash=%s,lease_hash=%s,lease_expires_at=%s WHERE id=%s""",
            (digest(nonce), digest(token), expiry, row["id"]),
        )
        return Lease(
            str(row["id"]),
            source,
            row["adapter_version"],
            row["schema_version"],
            row["params"],
            nonce,
            token,
            row["deadline_at"],
            expiry,
            version,
        )


def heartbeat(conn: Connection[Any], job_id: str, token: str, nonce: str) -> bool:
    verify_connection(conn, write=True)
    row = conn.execute(
        """UPDATE ops.scrape_jobs SET lease_expires_at=
        LEAST(clock_timestamp()+interval '30 seconds',deadline_at)
        WHERE id=%s AND status='leased' AND lease_hash=%s AND nonce_hash=%s
        AND lease_expires_at>clock_timestamp() AND deadline_at>clock_timestamp()
        RETURNING source_id,permission_version""",
        (job_id, digest(token), digest(nonce)),
    ).fetchone()
    if not row:
        return False
    try:
        if row[1] != permission(conn, row[0]):
            raise PermissionDenied("scraper permission changed")
    except PermissionDenied:
        conn.execute("UPDATE ops.scrape_jobs SET status='revoked' WHERE id=%s", (job_id,))
        return False
    return True


def complete(
    conn: Connection[Any],
    job_id: str,
    source: str,
    token: str,
    nonce: str,
    candidates: list[dict[str, Any]],
    *,
    adapter_version: int = 1,
) -> str:
    """Result is quarantined, never auto-committed to the market ledger."""
    verify_connection(conn, write=True)
    if source not in SOURCES or adapter_version != 1 or len(candidates) > 100:
        raise ValueError("unknown source/version or oversized candidate batch")
    if source == "pizzint":
        # Reject unrelated fields even if an old or misbehaving worker sends them.
        # A failed collection must not manufacture a DOUGHCON 5 observation.
        if len(candidates) != 1:
            raise ValueError("expected exactly one DOUGHCON candidate")
        item = candidates[0]
        if (
            not isinstance(item, dict)
            or set(item)
            != {"series_id", "value", "source_event_at", "quality", "automated_trading_allowed"}
            or item["series_id"] != "PENTAGON_PIZZA_PIZZINT"
            or item["value"] not in ("1", "2", "3", "4", "5")
            or item["automated_trading_allowed"] is not False
            or not isinstance(item["source_event_at"], str)
        ):
            raise ValueError("invalid DOUGHCON candidate")
        stamp = datetime.fromisoformat(item["source_event_at"])
        if stamp.tzinfo is None or stamp > datetime.now(stamp.tzinfo):
            raise ValueError("invalid DOUGHCON API timestamp")
    for item in candidates:
        if (
            not isinstance(item, dict)
            or item.get("quality") != "manual_review_required"
            or "raw_html" in item
            or "html" in item
        ):
            raise ValueError("unreviewed/unsafe scrape result")
    payload = {"source_id": source, "adapter_version": adapter_version, "candidates": candidates}
    if len(str(payload).encode("utf-8")) > 1_000_000:
        raise ValueError("scrape result exceeds limit")
    payload_hash = canonical_sha256(payload)
    row = conn.execute(
        "SELECT source_id,adapter_version,status,lease_hash,nonce_hash,"
        "lease_expires_at,deadline_at,permission_version,result_hash "
        "FROM ops.scrape_jobs WHERE id=%s FOR UPDATE",
        (job_id,),
    ).fetchone()
    if not row or row[0] != source or row[1] != adapter_version:
        raise PermissionDenied("scrape job identity mismatch")
    if not (
        isinstance(token, str)
        and isinstance(nonce, str)
        and token.isascii()
        and nonce.isascii()
        and 10 <= len(token) <= 256
        and 10 <= len(nonce) <= 256
    ):
        raise PermissionDenied("invalid scrape lease credential")
    if not hmac.compare_digest(row[3] or "", digest(token)) or not hmac.compare_digest(
        row[4] or "", digest(nonce)
    ):
        raise PermissionDenied("invalid scrape lease credential")
    if row[2] == "quarantined" and row[8] == payload_hash:
        if row[7] != permission(conn, source):
            raise PermissionDenied("source permission revoked")
        return "duplicate"
    clock = conn.execute("SELECT clock_timestamp()").fetchone()
    assert clock is not None
    if (
        row[2] != "leased"
        or row[3] != digest(token)
        or row[4] != digest(nonce)
        or row[5] <= clock[0]
        or row[6] <= clock[0]
    ):
        raise PermissionDenied("scrape lease expired or fenced")
    if row[7] != permission(conn, source):
        raise PermissionDenied("scrape permission revoked")
    conn.execute(
        """INSERT INTO ops.scrape_results(job_id,payload,result_hash)
        VALUES (%s,%s,%s)""",
        (job_id, Jsonb(payload), payload_hash),
    )
    conn.execute(
        """UPDATE ops.scrape_jobs SET status='quarantined',candidate_count=%s,
        result_hash=%s WHERE id=%s""",
        (len(candidates), payload_hash, job_id),
    )
    return "quarantined"
