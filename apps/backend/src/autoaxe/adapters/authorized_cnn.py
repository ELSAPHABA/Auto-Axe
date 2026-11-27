"""Permission-scoped CNN chart archive, never a live market quote or trading input."""

from datetime import datetime
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

from autoaxe.adapters.contracts import Contract, Money, UtcTime
from autoaxe.application.cnn_graphs import BLOCKS
from autoaxe.infrastructure.authorized_market import authorized_observations


class CnnComponent(Contract):
    timestamp: UtcTime
    score: Money | None
    rating: str | None


class CnnReading(Contract):
    timestamp: UtcTime
    score: Money
    rating: str
    available_at: UtcTime
    comparisons: dict[str, Money]
    components: dict[str, CnnComponent]


class CnnPoint(Contract):
    timestamp: UtcTime
    value: Money
    rating: str | None
    revision: int
    available_at: UtcTime


class CnnGraphPage(Contract):
    as_of: UtcTime
    current: CnnReading | None
    graphs: dict[str, list[CnnPoint]]


def read_cnn_graphs(conn: Connection[Any], cutoff: datetime, *, private_use: bool) -> CnnGraphPage:
    # Reuse the same audience and storage authorization as the market archive.
    authorized_observations(
        conn, series_id="CNN_FEAR_GREED_CNN", cutoff=cutoff, limit=1, private_use=private_use
    )
    version_row = conn.execute(
        "SELECT permission_version FROM catalog.source_registry WHERE source_id='cnn'"
    ).fetchone()
    assert version_row is not None
    version = version_row[0]
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            """
            SELECT value,source_event_at,available_at,metadata
            FROM market.observations
            WHERE series_id='CNN_FEAR_GREED_CNN' AND permission_version=%s
              AND metadata ? 'cnn' AND available_at<=%s AND ingested_at<=%s
            ORDER BY source_event_at DESC,series_version DESC LIMIT 1
        """,
            (version, cutoff, cutoff),
        ).fetchone()
        points = cur.execute(
            """
            WITH revisions AS (
                SELECT DISTINCT ON(graph_key,point_at) *
                FROM indicators.cnn_graph_points
                WHERE permission_version=%s AND available_at<=%s AND point_at<=%s
                    AND ingested_at<=%s
                ORDER BY graph_key,point_at,revision DESC
            ), bounded AS (
                SELECT *,row_number() OVER(PARTITION BY graph_key ORDER BY point_at DESC) AS rn
                FROM revisions
            )
            SELECT graph_key,point_at,value,rating,revision,available_at FROM bounded
            WHERE rn<=400 ORDER BY graph_key,point_at
        """,
            (version, cutoff, cutoff, cutoff),
        ).fetchall()
    current = None
    if row:
        details = row["metadata"]["cnn"]
        current = CnnReading(
            timestamp=row["source_event_at"],
            score=str(row["value"]),
            rating=row["metadata"]["category"],
            available_at=row["available_at"],
            comparisons=details["comparisons"],
            components=details["components"],
        )
    graphs: dict[str, list[CnnPoint]] = {}
    allowed = set(BLOCKS) | {"score:" + key for key in BLOCKS[1:]}
    for point in points:
        key = point["graph_key"]
        if key not in allowed:
            continue
        graphs.setdefault(key, []).append(
            CnnPoint(
                timestamp=point["point_at"],
                value=str(point["value"]),
                rating=point["rating"],
                revision=point["revision"],
                available_at=point["available_at"],
            )
        )
    return CnnGraphPage(as_of=cutoff, current=current, graphs=graphs)
