"""Durable BLS Public API v1 unregistered quota, reserved before network I/O."""

from datetime import date
from typing import Any

from psycopg import Connection

from autoaxe.infrastructure.event_store import require_event_permission
from autoaxe.infrastructure.market_store import PermissionDenied, verify_connection

MAX_UNREGISTERED_DAILY_REQUESTS = 25


def reserve_bls_v1(conn: Connection[Any]) -> tuple[date, int, int]:
    """Requires independent commit *before* the actual network request.

    A timeout or failed API call still consumes a quota unit. This prevents
    automatic retries from exceeding official daily fair-use limits.
    """
    verify_connection(conn, write=True)
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        ("source:bls",),
    )
    version = require_event_permission(conn, "bls")
    row = conn.execute(
        """INSERT INTO ops.official_api_quota (source_id,utc_day,requests_used)
           VALUES ('bls',(clock_timestamp() AT TIME ZONE 'UTC')::date,1)
           ON CONFLICT (source_id,utc_day)
           DO UPDATE SET requests_used=ops.official_api_quota.requests_used+1
           WHERE ops.official_api_quota.requests_used<%s
           RETURNING utc_day,requests_used""",
        (MAX_UNREGISTERED_DAILY_REQUESTS,),
    ).fetchone()
    if not row:
        raise PermissionDenied("BLS v1 daily quota exhausted")
    return row[0], int(row[1]), version
