"""PIT revision persistence for approved official economic events.

No inferred publication time, no overwrite of historical actuals, and no
implicit permission escalation. Caller owns the transaction.
"""

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from autoaxe.domain.calendars import EventRevision
from autoaxe.domain.canonical import canonical_sha256
from autoaxe.domain.types import utc_datetime
from autoaxe.infrastructure.market_store import PermissionDenied, verify_connection

OFFICIAL_EVENT_SOURCES = frozenset(
    {"bls", "bea", "census", "fed", "sec_edgar", "fred", "boj", "boe", "ecb"}
)


def require_event_permission(conn: Connection[Any], source_id: str) -> int:
    """Official release persistence is allowed only by a versioned admin grant."""
    verify_connection(conn, write=True)
    if source_id not in OFFICIAL_EVENT_SOURCES:
        raise PermissionDenied("unrecognized official event source")
    row = conn.execute(
        """SELECT permission_status,enabled,free_only,allow_fetch,allow_storage,
                  verified_at,evidence_ref,permission_version
           FROM catalog.source_registry WHERE source_id=%s""",
        (source_id,),
    ).fetchone()
    if (
        not row
        or tuple(row[:5]) != ("approved", True, True, True, True)
        or row[5] is None
        or not row[6]
    ):
        raise PermissionDenied("official event source not approved")
    return int(row[7])


def persist_event(
    conn: Connection[Any],
    event: EventRevision,
    *,
    expected_permission_version: int | None = None,
) -> tuple[EventRevision, bool]:
    """Serialize source/event revisions using an advisory transaction lock.

    A correction with identical semantic content is a no-op. The new revision
    receives its own observed first_seen_at, never the original release date.
    """
    verify_connection(conn, write=True)
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        (f"source:{event.source_id}",),
    )
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        (f"event:{event.source_id}:{event.event_key}",),
    )
    permission_version = require_event_permission(conn, event.source_id)
    if (
        expected_permission_version is not None
        and expected_permission_version != permission_version
    ):
        raise PermissionDenied("official source approval changed during collection")
    data = {
        "scheduled_at": event.scheduled_at.isoformat() if event.scheduled_at else None,
        "released_at": event.released_at.isoformat() if event.released_at else None,
        "actual": event.actual,
        "forecast": event.forecast,
        "previous": event.previous,
        "unit": event.unit,
        "source_url": event.source_url,
    }
    content_hash = canonical_sha256(data)
    with conn.cursor(row_factory=dict_row) as cur:
        previous = cur.execute(
            """SELECT revision,provenance FROM indicators.event_calendar
               WHERE source_id=%s AND event_uid=%s
               ORDER BY revision DESC LIMIT 1""",
            (event.source_id, event.event_key),
        ).fetchone()
    if previous and previous["provenance"].get("content_hash") == content_hash:
        return replace(event, revision=int(previous["revision"])), False
    revision = (int(previous["revision"]) if previous else 0) + 1
    result = replace(event, revision=revision)
    conn.execute(
        """INSERT INTO indicators.event_calendar(
           id,source_id,event_uid,revision,scheduled_at,released_at,first_seen_at,
           available_at,actual,forecast,previous,unit,source_url,provenance)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            str(uuid4()),
            event.source_id,
            event.event_key,
            revision,
            event.scheduled_at,
            event.released_at,
            event.first_seen_at,
            event.available_at,
            Decimal(event.actual) if event.actual else None,
            Decimal(event.forecast) if event.forecast else None,
            Decimal(event.previous) if event.previous else None,
            event.unit,
            event.source_url,
            Jsonb({"content_hash": content_hash, "permission_version": permission_version}),
        ),
    )
    return result, True


def query_events(
    conn: Connection[Any],
    *,
    cutoff: datetime,
    source_id: str | None = None,
    limit: int = 100,
    private_use: bool = False,
) -> list[EventRevision]:
    """Latest revision visible at cutoff, not the latest revision known today."""
    verify_connection(conn, write=False)
    utc_datetime(cutoff)
    if source_id is not None and source_id not in OFFICIAL_EVENT_SOURCES:
        raise ValueError("unsupported source")
    if not 1 <= limit <= 200:
        raise ValueError("invalid event query limit")
    # Gate visible rows on CURRENT authorization as well as historical evidence.
    sql = """
    SELECT * FROM (
      SELECT DISTINCT ON (e.source_id,e.event_uid)
        e.source_id,e.event_uid,e.revision,e.scheduled_at,e.released_at,
        e.first_seen_at,e.available_at,e.actual,e.forecast,e.previous,
        e.unit,e.source_url
      FROM indicators.event_calendar e
      JOIN catalog.source_registry r ON r.source_id=e.source_id
      WHERE e.available_at<=%s
        AND r.permission_status='approved' AND r.enabled
        AND r.free_only AND r.allow_storage
        AND (r.allow_redistribution OR %s::boolean)
        AND r.verified_at IS NOT NULL AND r.evidence_ref IS NOT NULL
        AND (%s::text IS NULL OR e.source_id=%s)
      ORDER BY e.source_id,e.event_uid,e.revision DESC
    ) current_rows ORDER BY available_at DESC,source_id,event_uid LIMIT %s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(sql, (cutoff, private_use, source_id, source_id, limit)).fetchall()
    return [
        EventRevision(
            row["event_uid"],
            row["source_id"],
            row["scheduled_at"],
            row["released_at"],
            row["first_seen_at"],
            row["available_at"],
            str(row["actual"]) if row["actual"] is not None else None,
            str(row["forecast"]) if row["forecast"] is not None else None,
            str(row["previous"]) if row["previous"] is not None else None,
            row["unit"],
            int(row["revision"]),
            row["source_url"],
        )
        for row in rows
    ]
