"""PostgreSQL ledger. Caller owns the transaction; never commits in a repository."""

from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from autoaxe.domain.canonical import canonical_sha256
from autoaxe.domain.catalog import SOURCE_URLS, catalog
from autoaxe.domain.market import Candidate
from autoaxe.domain.types import utc_string

MARKET_DBS = {"autoaxe_market", "autoaxe_dev", "autoaxe_test"}


class PermissionDenied(ValueError):
    pass


def verify_connection(conn: Connection[Any], *, write: bool) -> None:
    row = conn.execute("SELECT current_database(), current_user").fetchone()
    suffix = "runtime" if write else "read"
    if row is None or row[0] not in MARKET_DBS or row[1] != f"{row[0]}_{suffix}":
        raise PermissionDenied("wrong database or role")


def seed_catalog(conn: Connection[Any]) -> None:
    """Admin-only initialization of fixed definitions; never grant external permission."""
    for source, url in SOURCE_URLS.items():
        fixture = source == "fixture"
        conn.execute(
            """INSERT INTO catalog.source_registry
            (source_id,provider,terms_url,permission_status,enabled,allow_fetch,allow_storage,
             verified_at,evidence_ref)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
            (
                source,
                source,
                url,
                "approved" if fixture else "unverified",
                fixture,
                fixture,
                fixture,
                datetime.now(UTC) if fixture else None,
                "synthetic fixture only" if fixture else None,
            ),
        )
        conn.execute(
            """INSERT INTO catalog.permission_versions
            SELECT source_id,permission_version,to_jsonb(r) FROM catalog.source_registry r
            WHERE source_id=%s ON CONFLICT DO NOTHING""",
            (source,),
        )
    for item in catalog().values():
        instrument_id = f"{item.source_id}:{item.symbol}:{item.instrument_type}"
        conn.execute(
            """INSERT INTO catalog.instruments VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT DO NOTHING""",
            (instrument_id, item.source_id, item.symbol, item.instrument_type, item.currency),
        )
        conn.execute(
            """INSERT INTO catalog.series VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT DO NOTHING""",
            (
                item.id,
                item.indicator_id,
                item.source_id,
                instrument_id,
                item.unit,
                item.interval,
                item.ttl,
                item.priority,
                item.mapping_version,
            ),
        )
        conn.execute(
            """INSERT INTO catalog.instrument_mappings VALUES (%s,%s,%s)
            ON CONFLICT DO NOTHING""",
            (item.id, item.mapping_version, Jsonb(asdict(item))),
        )


def gate(conn: Connection[Any], series_id: str, action: str = "storage") -> dict[str, Any]:
    if action not in {"storage", "fetch", "redistribution", "trading"}:
        raise ValueError("unsupported action")
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            """SELECT s.*, r.permission_status,r.enabled,r.free_only,r.allow_fetch,
            r.allow_storage,r.allow_redistribution,r.allow_trading,r.permission_version,
            r.verified_at,r.evidence_ref FROM catalog.series s
            JOIN catalog.source_registry r USING(source_id) WHERE series_id=%s""",
            (series_id,),
        ).fetchone()
    if (
        not row
        or row["permission_status"] != "approved"
        or not row["enabled"]
        or not row["free_only"]
        or not row["verified_at"]
        or not row["evidence_ref"]
        or not row[f"allow_{action}"]
    ):
        raise PermissionDenied(f"source action denied: {action}")
    return row


def emit(
    conn: Connection[Any],
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    version: int,
    payload: dict[str, Any],
    *,
    source: str | None = None,
    series_id: str | None = None,
    source_event_at: datetime | None = None,
    available_at: datetime | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    event_id = str(uuid4())
    db = conn.execute("SELECT current_database()").fetchone()
    assert db is not None
    event = dict(
        event_id=event_id,
        event_type=event_type,
        schema_version=1,
        origin_db=db[0],
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=version,
        source=source,
        series_id=series_id,
        source_event_at=utc_string(source_event_at) if source_event_at else None,
        occurred_at=utc_string(now),
        available_at=utc_string(available_at or now),
        committed_at=utc_string(now),
        correlation_id=event_id,
        causation_id=None,
        mode=None,
        account_ref=None,
        payload=payload,
    )
    from pydantic import TypeAdapter

    from autoaxe.adapters.contracts import Event

    event = TypeAdapter(Event).validate_python(event).model_dump(mode="json")
    conn.execute(
        """INSERT INTO ops.outbox
        (event_id,event_type,schema_version,origin_db,aggregate_type,aggregate_id,
         aggregate_version,envelope) VALUES (%s,%s,1,%s,%s,%s,%s,%s)""",
        (event_id, event_type, db[0], aggregate_type, aggregate_id, version, Jsonb(event)),
    )
    return event


def ingest(conn: Connection[Any], item: Candidate) -> tuple[str, int, bool]:
    """Lock per series, recheck gate, deduplicate and atomically append + outbox."""
    verify_connection(conn, write=True)
    # Admin permission updates must use the same source lock (see set_permission).
    series = catalog().get(item.series_id)
    if series is None:
        raise ValueError("unknown series")
    if series.source_id.startswith("manual:") and item.quality.value != "manual_unverified":
        raise ValueError("manual observation must be unverified")
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("source:" + series.source_id,)
    )
    permitted = gate(conn, item.series_id)
    if permitted["mapping_version"] != item.mapping_version:
        raise ValueError("stale mapping")
    if item.available_at > datetime.now(UTC):
        raise ValueError("future availability")
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("series:" + item.series_id,)
    )
    digest = canonical_sha256(
        dict(
            value=item.value,
            source_event_at=(utc_string(item.source_event_at) if item.source_event_at else None),
            quality=item.quality.value,
            metadata=item.metadata,
            mapping_version=item.mapping_version,
        )
    )
    previous = conn.execute(
        """SELECT observation_id,revision FROM market.source_events
        WHERE series_id=%s AND source_event_key=%s AND payload_hash=%s""",
        (item.series_id, item.key, digest),
    ).fetchone()
    if previous:
        return str(previous[0]), int(previous[1]), False
    row = conn.execute(
        """SELECT COALESCE(MAX(revision),0)+1 FROM market.source_events
        WHERE series_id=%s AND source_event_key=%s""",
        (item.series_id, item.key),
    ).fetchone()
    assert row is not None
    revision = int(row[0])
    oid = str(uuid4())
    partition_at = item.source_event_at or item.received_at
    version_row = conn.execute(
        """INSERT INTO market.series_versions VALUES (%s,1)
        ON CONFLICT(series_id) DO UPDATE SET version=market.series_versions.version+1
        RETURNING version""",
        (item.series_id,),
    ).fetchone()
    assert version_row is not None
    version = int(version_row[0])
    conn.execute(
        "INSERT INTO market.source_events VALUES (%s,%s,%s,%s,%s,%s)",
        (item.series_id, item.key, revision, digest, partition_at, oid),
    )
    conn.execute(
        """INSERT INTO market.observations
        (partition_at,observation_id,series_id,source_event_key,revision,mapping_version,
        permission_version,series_version,source_event_at,available_at,received_at,value,
        quality,metadata) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            partition_at,
            oid,
            item.series_id,
            item.key,
            revision,
            item.mapping_version,
            permitted["permission_version"],
            version,
            item.source_event_at,
            item.available_at,
            item.received_at,
            Decimal(item.value) if item.value is not None else None,
            item.quality.value,
            Jsonb(item.metadata),
        ),
    )
    # Unknown timestamps cannot displace a known source time; late ticks cannot regress latest.
    conn.execute(
        """INSERT INTO market.latest_observations VALUES (%s,%s,%s,%s)
        ON CONFLICT(series_id) DO UPDATE SET partition_at=EXCLUDED.partition_at,
          observation_id=EXCLUDED.observation_id,aggregate_version=EXCLUDED.aggregate_version
        WHERE EXISTS(SELECT 1 FROM market.observations old
          WHERE old.partition_at=market.latest_observations.partition_at
          AND old.observation_id=market.latest_observations.observation_id
          AND CASE WHEN %s::text IS NOT NULL AND old.metadata ? 'observation_date'
          THEN (%s::text,%s) >= (old.metadata->>'observation_date',old.series_version)
          ELSE (COALESCE(%s,'-infinity'::timestamptz),%s)
              >= (COALESCE(old.source_event_at,'-infinity'::timestamptz),old.series_version)
          END)""",
        (
            item.series_id,
            partition_at,
            oid,
            version,
            item.metadata.get("observation_date") if series.interval == "1d" else None,
            item.metadata.get("observation_date") if series.interval == "1d" else None,
            version,
            item.source_event_at,
            version,
        ),
    )
    emit(
        conn,
        "market.observation.recorded",
        "market_series",
        item.series_id,
        version,
        {"observation_id": oid, "revision": revision, "quality": item.quality.value},
        source=series.source_id,
        series_id=item.series_id,
        source_event_at=item.source_event_at,
        available_at=item.available_at,
    )
    return oid, revision, True


def set_permission(
    conn: Connection[Any],
    source: str,
    *,
    approved: bool,
    evidence: str,
    fetch: bool,
    storage: bool,
    redistribution: bool = False,
    trading: bool = False,
) -> None:
    """Administrator-only; must never be exposed through an unauthenticated endpoint."""
    if source not in SOURCE_URLS or not evidence.strip():
        raise ValueError("missing source/permission evidence")
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("source:" + source,))
    conn.execute(
        """UPDATE catalog.source_registry SET permission_status=%s,enabled=%s,
        allow_fetch=%s,allow_storage=%s,allow_redistribution=%s,allow_trading=%s,
        verified_at=clock_timestamp(),evidence_ref=%s,permission_version=permission_version+1
        WHERE source_id=%s""",
        (
            "approved" if approved else "blocked",
            approved and fetch and storage,
            approved and fetch,
            approved and storage,
            approved and redistribution,
            approved and trading,
            evidence,
            source,
        ),
    )
    conn.execute(
        """INSERT INTO catalog.permission_versions
        SELECT source_id,permission_version,to_jsonb(r) FROM catalog.source_registry r
        WHERE source_id=%s""",
        (source,),
    )


def query(
    conn: Connection[Any],
    *,
    series_id: str,
    as_of: datetime,
    limit: int,
    start: datetime | None = None,
    end: datetime | None = None,
    after: tuple[datetime, str] | None = None,
    quality: str | None = None,
    snapshot_version: int | None = None,
) -> list[dict[str, Any]]:
    verify_connection(conn, write=False)
    gate(conn, series_id, "storage")
    # Phase 1 HTTP exposes synthetic fixture only; actual licensed read scope is Phase 2.
    if catalog()[series_id].source_id != "fixture":
        raise PermissionDenied("external series query disabled in fixture API")
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            """WITH revisions AS (
               SELECT DISTINCT ON(source_event_key) * FROM market.observations
               WHERE series_id=%s AND available_at<=%s AND ingested_at<=%s
                 AND (%s::bigint IS NULL OR series_version<=%s)
               ORDER BY source_event_key,revision DESC
            ) SELECT * FROM revisions WHERE
               (%s::timestamptz IS NULL OR partition_at >= %s)
               AND (%s::timestamptz IS NULL OR partition_at < %s)
               AND (%s::text IS NULL OR quality=%s)
               AND (%s::timestamptz IS NULL OR (partition_at,observation_id) < (%s,%s::uuid))
               ORDER BY partition_at DESC,observation_id DESC LIMIT %s""",
            (
                series_id,
                as_of,
                as_of,
                snapshot_version,
                snapshot_version,
                start,
                start,
                end,
                end,
                quality,
                quality,
                after[0] if after else None,
                after[0] if after else None,
                after[1] if after else None,
                limit,
            ),
        ).fetchall()
    return rows


def current_series_version(conn: Connection[Any], series_id: str) -> int:
    verify_connection(conn, write=False)
    row = conn.execute(
        "SELECT version FROM market.series_versions WHERE series_id=%s", (series_id,)
    ).fetchone()
    return int(row[0]) if row else 0


def persist_trade(conn: Connection[Any], item: Candidate) -> tuple[str, int, bool]:
    """Advance durable contiguous checkpoint in the same transaction as append."""
    verify_connection(conn, write=True)
    series = catalog().get(item.series_id)
    if series is None or series.interval != "trade":
        raise ValueError("not a trade series")
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("source:" + series.source_id,)
    )
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("trade:" + item.series_id,)
    )
    trade_id = int(item.key)
    if trade_id < 0:
        raise ValueError("negative trade id")
    old = conn.execute(
        "SELECT last_trade_id FROM market.stream_checkpoints WHERE series_id=%s", (item.series_id,)
    ).fetchone()
    if old and trade_id > old[0] + 1:
        raise ValueError("unfilled trade gap")
    result = ingest(conn, item)
    conn.execute(
        """INSERT INTO market.stream_checkpoints VALUES (%s,%s)
        ON CONFLICT(series_id) DO UPDATE SET
        last_trade_id=GREATEST(market.stream_checkpoints.last_trade_id,EXCLUDED.last_trade_id)""",
        (item.series_id, trade_id),
    )
    return result


def review_manual(
    conn: Connection[Any], observation_id: str, reviewer: str, status: str, reason: str
) -> str:
    """Review is append-only and never mutates the original unverified observation."""
    verify_connection(conn, write=True)
    if status not in ("checked", "rejected") or not reviewer.strip() or not reason.strip():
        raise ValueError("invalid review")
    row = conn.execute(
        """SELECT o.series_id,o.quality,o.metadata FROM market.observations o
        JOIN market.source_events e USING(observation_id,partition_at)
        WHERE o.observation_id=%s""",
        (observation_id,),
    ).fetchone()
    if (
        not row
        or row[1] != "manual_unverified"
        or not catalog()[row[0]].source_id.startswith("manual:")
    ):
        raise ValueError("not a manual observation")
    if row[2].get("operator") == reviewer:
        raise ValueError("self-review denied")
    gate(conn, row[0], "storage")
    review_id = str(uuid4())
    conn.execute(
        """INSERT INTO market.manual_reviews(review_id,observation_id,reviewer,status,reason)
        VALUES (%s,%s,%s,%s,%s)""",
        (review_id, observation_id, reviewer, status, reason),
    )
    return review_id


def select_two_year(conn: Connection[Any], now: datetime) -> tuple[str | None, str]:
    """Only permitted healthy source; no source blending, explicit transition audit."""
    verify_connection(conn, write=True)
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('selection:UST_2Y',0))")
    for source in ("naver", "treasury"):
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("source:" + source,))
    chosen = None
    reason = "no_permitted_source"
    for sid in ("UST_2Y_NAVER", "UST_2Y_TREASURY"):
        try:
            gate(conn, sid)
        except PermissionDenied:
            continue
        row = conn.execute(
            """SELECT h.status,o.value,o.source_event_at,o.quality,o.metadata
            FROM ops.collector_health h LEFT JOIN market.latest_observations l USING(series_id)
            LEFT JOIN market.observations o ON o.partition_at=l.partition_at
            AND o.observation_id=l.observation_id WHERE h.series_id=%s""",
            (sid,),
        ).fetchone()
        if row is None:
            if sid.endswith("NAVER"):
                reason = "primary_status_unknown"
                break
            continue
        healthy = row[0] in ("healthy", "no_update") and row[1] is not None
        if healthy and sid.endswith("NAVER"):
            healthy = (
                row[2] is not None
                and row[3] == "valid"
                and (0 <= (now - row[2]).total_seconds() <= 300)
            )
        if healthy and sid.endswith("TREASURY"):
            healthy = bool(row[4].get("official_daily"))
        if healthy:
            chosen = sid
            reason = (
                "primary_recovered_or_healthy"
                if sid.endswith("NAVER")
                else "primary_unavailable_daily_fallback"
            )
            break
    previous = conn.execute(
        "SELECT series_id,reason FROM market.source_selections WHERE indicator_id='UST_2Y' "
        "ORDER BY selection_id DESC LIMIT 1"
    ).fetchone()
    if previous != (chosen, reason):
        conn.execute(
            """INSERT INTO market.source_selections(indicator_id,series_id,reason,selected_at)
            VALUES ('UST_2Y',%s,%s,%s)""",
            (chosen, reason, now),
        )
    return chosen, reason
