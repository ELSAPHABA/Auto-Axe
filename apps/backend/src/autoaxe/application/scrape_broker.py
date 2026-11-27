"""Durable private scrape job lease/fence; quarantines results instead of auto-ingesting."""

import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from autoaxe.application.cnn_graphs import save_graphs, validate_details
from autoaxe.application.market_worker import record_health
from autoaxe.domain.canonical import canonical_sha256
from autoaxe.domain.catalog import SOURCE_URLS, catalog
from autoaxe.domain.market import Candidate, Quality
from autoaxe.domain.types import decimal_string, utc_string
from autoaxe.infrastructure.jobs import retry_after
from autoaxe.infrastructure.market_store import PermissionDenied, gate, ingest, verify_connection
from autoaxe.infrastructure.sessions import digest

SOURCES = {"cnn", "pizzint", "dramexchange", "seibro", "naver"}
SERIES = {
    "cnn": ("CNN_FEAR_GREED_CNN",),
    "dramexchange": ("DRAM_DDR5_UDIMM_AUTO", "DRAM_DDR5_RDIMM_AUTO"),
    "naver": ("UST_2Y_NAVER",),
}


def source_lock(conn: Connection[Any], source: str) -> None:
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("source:" + source,))


def health(conn: Connection[Any], source: str, status: str, reason: str) -> None:
    for sid in SERIES.get(source, ()):
        if sid in catalog():
            record_health(conn, sid, status, reason)


def adapter_grant(conn: Connection[Any], source: str, version: int) -> int:
    """Only a separately recorded administrator grant permits scheduled work."""
    if source not in SERIES or permission(conn, source) != version:
        raise PermissionDenied("generic adapter permission changed")
    row = conn.execute(
        """SELECT interval_seconds,mapping_versions FROM ops.scrape_adapter_grants
           WHERE source_id=%s AND permission_version=%s AND adapter_version=1
           AND schema_version=1 AND verified_at<=clock_timestamp()""",
        (source, version),
    ).fetchone()
    if row is None:
        raise PermissionDenied("independent adapter verification required")
    expected = {}
    for sid in SERIES[source]:
        series = catalog().get(sid)
        info = gate(conn, sid, "storage")
        if (
            series is None
            or series.source_id != source
            or info["mapping_version"] != series.mapping_version
        ):
            raise PermissionDenied("scrape mapping unavailable or changed")
        expected[sid] = series.mapping_version
    if row[1] != expected:
        raise PermissionDenied("scrape mapping verification changed")
    circuit = conn.execute(
        "SELECT permission_version,blocked,retry_at>clock_timestamp() "
        "FROM ops.poll_circuits WHERE source_id=%s",
        (source,),
    ).fetchone()
    # A renewed approval is not a license to shorten an outstanding Retry-After.
    if circuit and ((circuit[0] == version and circuit[1]) or circuit[2]):
        raise PermissionDenied("source circuit open")
    return max(int(row[0]), 900) if source == "naver" else int(row[0])


def reap(conn: Connection[Any], source: str) -> int:
    """Fail expired work; uncertain external requests are never replayed immediately."""
    rows = conn.execute(
        """UPDATE ops.scrape_jobs SET status='failed' WHERE source_id=%s
           AND status IN ('queued','leased') AND (deadline_at<=clock_timestamp()
           OR (status='leased' AND attempt>=max_attempts AND lease_expires_at<=clock_timestamp()))
           RETURNING schedule_interval_seconds""",
        (source,),
    ).fetchall()
    if any(row[0] is not None for row in rows):
        health(conn, source, "unknown", "scrape_lease_expired")
    return len(rows)


def schedule_due(conn: Connection[Any], source: str) -> str:
    """Reserve one bounded job, coalesce missed polls and never schedule PizzINT."""
    verify_connection(conn, write=True)
    if source not in SERIES:
        raise ValueError("unsupported generic schedule source")
    source_lock(conn, source)
    reap(conn, source)
    try:
        version = permission(conn, source)
        interval = adapter_grant(conn, source, version)
    except PermissionDenied:
        conn.execute(
            """UPDATE ops.scrape_jobs SET status='revoked' WHERE source_id=%s
               AND schedule_interval_seconds IS NOT NULL AND status IN ('queued','leased')""",
            (source,),
        )
        health(conn, source, "blocked", "scrape_permission_or_adapter_required")
        return "blocked"
    if conn.execute(
        "SELECT 1 FROM ops.scrape_schedule WHERE source_id=%s AND next_due_at>clock_timestamp()",
        (source,),
    ).fetchone():
        return "not_due"
    if conn.execute(
        "SELECT 1 FROM ops.scrape_jobs WHERE source_id=%s "
        "AND status IN ('queued','leased') LIMIT 1",
        (source,),
    ).fetchone():
        return "busy"
    stamp = conn.execute("SELECT clock_timestamp()").fetchone()
    assert stamp is not None
    job_id = submit(conn, source, {}, "scheduled:" + str(uuid4()), stamp[0] + timedelta(minutes=5))
    conn.execute(
        "UPDATE ops.scrape_jobs SET max_attempts=1,schedule_interval_seconds=%s WHERE id=%s",
        (interval, job_id),
    )
    conn.execute(
        """INSERT INTO ops.scrape_schedule VALUES (%s,%s,%s,%s)
           ON CONFLICT(source_id) DO UPDATE SET last_job_id=EXCLUDED.last_job_id,
           last_scheduled_at=EXCLUDED.last_scheduled_at,next_due_at=EXCLUDED.next_due_at""",
        (source, job_id, stamp[0], stamp[0] + timedelta(seconds=interval)),
    )
    return "scheduled"


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


def claim(
    conn: Connection[Any], *, source: str, lease_seconds: int = 30, scheduled_only: bool = False
) -> Lease | None:
    verify_connection(conn, write=True)
    if not 1 <= lease_seconds <= 60:
        raise ValueError("invalid scrape lease")
    if source not in SOURCES:
        raise PermissionDenied("unregistered source")
    source_lock(conn, source)
    reap(conn, source)
    if scheduled_only:
        version = permission(conn, source)
        adapter_grant(conn, source, version)
    with conn.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            """SELECT * FROM ops.scrape_jobs WHERE source_id=%s
            AND deadline_at>clock_timestamp() AND attempt<max_attempts
            AND (status='queued' OR
            (status='leased' AND lease_expires_at<=clock_timestamp()))
            AND (NOT %s OR schedule_interval_seconds IS NOT NULL)
            ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1""",
            (source, scheduled_only),
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
        interval = row["schedule_interval_seconds"]
        if interval is not None:
            if adapter_grant(conn, source, version) != interval:
                raise PermissionDenied("scheduled interval changed")
            # Start-to-start spacing, even if an older job sat in the queue.
            cursor.execute(
                """UPDATE ops.scrape_schedule SET next_due_at=GREATEST(next_due_at,
                   clock_timestamp()+make_interval(secs=>%s)) WHERE last_job_id=%s""",
                (interval, row["id"]),
            )
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
    source_row = conn.execute(
        "SELECT source_id FROM ops.scrape_jobs WHERE id=%s", (job_id,)
    ).fetchone()
    if not source_row:
        return False
    source_lock(conn, source_row[0])
    row = conn.execute(
        """UPDATE ops.scrape_jobs SET lease_expires_at=
        LEAST(clock_timestamp()+interval '30 seconds',deadline_at)
        WHERE id=%s AND status='leased' AND lease_hash=%s AND nonce_hash=%s
        AND lease_expires_at>clock_timestamp() AND deadline_at>clock_timestamp()
        RETURNING source_id,permission_version,schedule_interval_seconds""",
        (job_id, digest(token), digest(nonce)),
    ).fetchone()
    if not row:
        return False
    try:
        if row[1] != permission(conn, row[0]):
            raise PermissionDenied("scraper permission changed")
        if row[2] is not None and adapter_grant(conn, row[0], row[1]) != row[2]:
            raise PermissionDenied("scraper adapter changed")
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
    source_lock(conn, source)
    row = conn.execute(
        "SELECT source_id,adapter_version,status,lease_hash,nonce_hash,"
        "lease_expires_at,deadline_at,permission_version,result_hash,schedule_interval_seconds "
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
    if row[9] is not None:
        if adapter_grant(conn, source, row[7]) != row[9]:
            raise PermissionDenied("scraper adapter changed")
        validate_candidates(source, candidates)
    if row[2] in ("quarantined", "succeeded") and row[8] == payload_hash:
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
    if row[9] is not None:
        health(conn, source, "manual_required", "scrape_quarantined")
    return "quarantined"


def validate_candidates(source: str, candidates: list[dict[str, Any]]) -> None:
    """Constrain quarantined candidate schema even if a trusted worker is compromised."""
    common = {"series_id", "value", "source_event_at", "quality"}
    dram_items = {
        "DRAM_DDR5_UDIMM_AUTO": "DDR5 UDIMM 16GB 4800/5600",
        "DRAM_DDR5_RDIMM_AUTO": "DDR5 RDIMM 32GB 4800/5600",
    }
    expected = {
        "cnn": {"CNN_FEAR_GREED_CNN"},
        "naver": {"UST_2Y_NAVER"},
        "dramexchange": set(dram_items),
    }[source]
    if len(candidates) != len(expected):
        raise ValueError("candidate count mismatch")
    seen: set[str] = set()
    for item in candidates:
        sid = item.get("series_id")
        if not isinstance(sid, str) or sid not in expected or sid in seen:
            raise ValueError("unexpected candidate series")
        seen.add(sid)
        raw = item.get("value")
        if not isinstance(raw, str) or len(raw) > 64:
            raise ValueError("invalid candidate value")
        try:
            value = Decimal(decimal_string(raw))
        except InvalidOperation as exc:
            raise ValueError("invalid candidate value") from exc
        if not value.is_finite() or item.get("quality") != "manual_review_required":
            raise ValueError("invalid candidate quality or value")
        if source == "cnn":
            if (
                set(item) != common | {"category", "automated_trading_allowed", "details"}
                or not 0 <= value <= 100
                or item["category"]
                not in ("Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed")
                or item["automated_trading_allowed"] is not False
            ):
                raise ValueError("invalid CNN candidate")
            stamp = item["source_event_at"]
            if not isinstance(stamp, str) or len(stamp) > 64:
                raise ValueError("CNN source timestamp required")
            parsed = datetime.fromisoformat(stamp)
            if parsed.utcoffset() is None or parsed > datetime.now(UTC):
                raise ValueError("invalid CNN source timestamp")
            validate_details(item["details"], datetime.now(UTC))
        else:
            stamp = item.get("source_event_at")
            if not isinstance(stamp, str) or len(stamp) > 64:
                raise ValueError("invalid source timestamp")
            parsed = datetime.fromisoformat(stamp)
            if parsed.tzinfo is None or parsed > datetime.now(UTC):
                raise ValueError("source timestamp must be timezone aware and not future")
            if source == "naver" and set(item) != common:
                raise ValueError("invalid Naver candidate")
            if source == "dramexchange" and (
                set(item) != common | {"item", "unit", "unit_verified", "source_id"}
                or item["item"] != dram_items[sid]
                or item["unit"] is not None
                or item["unit_verified"] is not False
                or item["source_id"] != source
                or value <= 0
            ):
                raise ValueError("invalid DRAM candidate")


def fail(
    conn: Connection[Any],
    job_id: str,
    source: str,
    token: str,
    nonce: str,
    *,
    reason: str,
    http_status: int | None = None,
    retry_header: str | None = None,
) -> str:
    """Consume a valid scheduled lease and persist conservative source-wide cooldown."""
    verify_connection(conn, write=True)
    if source not in SERIES or reason not in {"http", "schema", "transport"}:
        raise ValueError("invalid scrape failure")
    if reason == "http":
        if http_status is None or not 100 <= http_status <= 599 or http_status == 200:
            raise ValueError("invalid HTTP status")
    elif http_status is not None or retry_header is not None:
        raise ValueError("unexpected HTTP failure fields")
    if retry_header is not None and (len(retry_header) > 128 or not retry_header.isascii()):
        raise ValueError("invalid Retry-After")
    source_lock(conn, source)
    row = conn.execute(
        """SELECT permission_version,schedule_interval_seconds FROM ops.scrape_jobs
           WHERE id=%s AND source_id=%s AND status='leased' AND lease_hash=%s AND nonce_hash=%s
           AND deadline_at>clock_timestamp() AND lease_expires_at>clock_timestamp()
           AND schedule_interval_seconds IS NOT NULL FOR UPDATE""",
        (job_id, source, digest(token), digest(nonce)),
    ).fetchone()
    if row is None or adapter_grant(conn, source, row[0]) != row[1]:
        raise PermissionDenied("stale or unauthorized failure report")
    stamp = conn.execute("SELECT clock_timestamp()").fetchone()
    assert stamp is not None
    now = stamp[0]
    delay = max(row[1], retry_after(1, retry_header, now))
    blocked = reason == "schema" or http_status in (401, 403) or delay > 604800
    if retry_header and retry_header.strip().isdigit() and len(retry_header.strip()) > 7:
        blocked = True
    until = None if blocked else now + timedelta(seconds=delay)
    code = f"http_{http_status}" if reason == "http" else "scrape_" + reason
    conn.execute(
        """INSERT INTO ops.poll_circuits VALUES (%s,%s,%s,%s,%s)
           ON CONFLICT(source_id) DO UPDATE SET permission_version=EXCLUDED.permission_version,
           blocked=EXCLUDED.blocked,retry_at=EXCLUDED.retry_at,reason=EXCLUDED.reason""",
        (source, row[0], blocked, until, code),
    )
    if until is not None:
        conn.execute(
            "UPDATE ops.scrape_schedule SET next_due_at=GREATEST(next_due_at,%s) "
            "WHERE source_id=%s",
            (until, source),
        )
    conn.execute("UPDATE ops.scrape_jobs SET status='failed' WHERE id=%s", (job_id,))
    health(
        conn,
        source,
        "schema_error" if reason == "schema" else "blocked" if blocked else "unknown",
        code,
    )
    return "failed"


def promote_reviewed(conn: Connection[Any], job_id: str) -> str:
    """Ingest only an independent administrator decision bound to an exact result hash.

    A worker cannot insert that decision. Publication is atomic with the review
    receipt, uses MANUAL_CHECKED, and never infers missing timestamp or unit.
    """
    verify_connection(conn, write=True)
    source_row = conn.execute(
        "SELECT source_id FROM ops.scrape_jobs WHERE id=%s", (job_id,)
    ).fetchone()
    if not source_row or source_row[0] not in SERIES:
        raise PermissionDenied("not a generic scrape job")
    source = source_row[0]
    source_lock(conn, source)
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            """SELECT j.status,j.permission_version,j.schedule_interval_seconds,
               j.result_hash AS job_hash,
               r.payload,r.result_hash,r.submitted_at,r.review_status,
               v.result_hash AS reviewed_hash,v.decision,v.units,v.reviewed_at
               FROM ops.scrape_jobs j JOIN ops.scrape_results r ON r.job_id=j.id
               JOIN ops.scrape_reviews v ON v.job_id=j.id WHERE j.id=%s FOR UPDATE OF j,r""",
            (job_id,),
        ).fetchone()
    if not row or row["schedule_interval_seconds"] is None:
        raise PermissionDenied("independent review of scheduled result required")
    if adapter_grant(conn, source, row["permission_version"]) != row["schedule_interval_seconds"]:
        raise PermissionDenied("adapter verification changed")
    if not (
        row["job_hash"]
        == row["result_hash"]
        == row["reviewed_hash"]
        == canonical_sha256(row["payload"])
    ):
        raise PermissionDenied("reviewed result hash mismatch")
    if row["reviewed_at"] < row["submitted_at"]:
        raise PermissionDenied("review predates submission")
    previous = conn.execute(
        "SELECT result_hash FROM ops.scrape_promotions WHERE job_id=%s", (job_id,)
    ).fetchone()
    if previous:
        if previous[0] != row["result_hash"] or row["review_status"] != row["decision"]:
            raise PermissionDenied("review receipt mismatch")
        return "duplicate"
    if row["status"] != "quarantined" or row["review_status"] != "quarantined":
        raise PermissionDenied("result not pending review")
    payload = row["payload"]
    if (
        set(payload) != {"source_id", "adapter_version", "candidates"}
        or payload["source_id"] != source
        or payload["adapter_version"] != 1
    ):
        raise ValueError("invalid reviewed payload scope")
    candidates = payload["candidates"]
    validate_candidates(source, candidates)
    ids: list[str] = []
    if row["decision"] == "checked":
        reviewed = row["reviewed_at"]
        if reviewed > datetime.now(UTC):
            raise ValueError("review time in future")
        expected_units = {sid: catalog()[sid].unit for sid in SERIES[source]}
        if "unverified" in expected_units.values() or row["units"] != expected_units:
            raise PermissionDenied("verified source units required")
        for item in candidates:
            sid = item["series_id"]
            series = catalog()[sid]
            stamp = (
                datetime.fromisoformat(item["source_event_at"]) if item["source_event_at"] else None
            )
            # Unknown source time must remain unknown; use per-job identity only.
            key = utc_string(stamp) if stamp else "review:" + job_id
            metadata: dict[str, Any] = {"automated_trading_allowed": False}
            if source == "cnn":
                metadata["category"] = item["category"]
                metadata["cnn"] = save_graphs(
                    conn,
                    item["details"],
                    version=row["permission_version"],
                    received=row["submitted_at"],
                    reviewed=reviewed,
                    job_id=job_id,
                )
            candidate = Candidate(
                sid,
                key,
                item["value"],
                stamp,
                row["submitted_at"],
                reviewed,
                Quality.MANUAL_CHECKED,
                metadata,
                series.mapping_version,
            )
            ids.append(ingest(conn, candidate)[0])
        health(conn, source, "manual_required", "scrape_manually_checked_nontrading")
    else:
        health(conn, source, "manual_required", "scrape_review_rejected")
    conn.execute(
        "INSERT INTO ops.scrape_promotions(job_id,result_hash,observation_ids) VALUES (%s,%s,%s)",
        (job_id, row["result_hash"], Jsonb(ids)),
    )
    conn.execute(
        "UPDATE ops.scrape_results SET review_status=%s WHERE job_id=%s", (row["decision"], job_id)
    )
    conn.execute(
        "UPDATE ops.scrape_jobs SET status=%s WHERE id=%s",
        ("succeeded" if ids else "failed", job_id),
    )
    return "promoted" if ids else "rejected"
