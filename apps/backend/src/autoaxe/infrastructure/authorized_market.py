"""Read-only, permission-filtered market observations for authenticated BFF use.

This is separate from the public Phase 1 fixture API. Approved source storage
and current rights are checked for every request. Single-user private viewing
is not a grant to distribute data to third parties.
"""

from datetime import datetime
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

from autoaxe.domain.catalog import catalog
from autoaxe.domain.types import utc_datetime
from autoaxe.infrastructure.market_store import PermissionDenied, verify_connection


def authorized_observations(
    conn: Connection[Any],
    *,
    series_id: str,
    cutoff: datetime,
    limit: int = 200,
    private_use: bool = False,
) -> list[dict[str, Any]]:
    verify_connection(conn, write=False)
    utc_datetime(cutoff)
    if not 1 <= limit <= 200:
        raise ValueError("out-of-range observation limit")
    series = catalog().get(series_id)
    if series is None:
        raise ValueError("unknown market series")
    row = conn.execute(
        """SELECT s.source_id,s.mapping_version,r.permission_status,r.enabled,
           r.free_only,r.allow_storage,r.allow_redistribution,r.verified_at,
           r.evidence_ref,r.permission_version
           FROM catalog.series s JOIN catalog.source_registry r USING (source_id)
           WHERE s.series_id=%s""",
        (series_id,),
    ).fetchone()
    if (
        not row
        or row[0] != series.source_id
        or row[1] != series.mapping_version
        or row[2] != "approved"
        or row[3] is not True
        or row[4] is not True
        or row[5] is not True
        or (row[6] is not True and not private_use)
        or row[7] is None
        or not row[8]
    ):
        raise PermissionDenied("source not approved for this audience")
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """WITH visible AS (
                 SELECT DISTINCT ON(o.source_event_key)
                    o.source_event_key,o.revision,o.value,o.source_event_at,
                    o.received_at,o.available_at,o.ingested_at,o.quality,
                    o.metadata,o.mapping_version,o.permission_version,
                    o.partition_at,o.observation_id,o.series_version
                 FROM market.observations o
                 WHERE o.series_id=%s
                   AND o.available_at<=%s AND o.ingested_at<=%s AND o.mapping_version=%s
                 ORDER BY o.source_event_key,o.revision DESC
               )
               SELECT * FROM visible ORDER BY
                  CASE WHEN %s THEN source_event_key END DESC NULLS LAST, partition_at DESC,
                  series_version DESC,observation_id DESC LIMIT %s""",
            (
                series_id,
                cutoff,
                cutoff,
                series.mapping_version,
                series_id in {"NVDA_DAILY_OHLCV", "QLD_DAILY_OHLCV"},
                limit,
            ),
        ).fetchall()
