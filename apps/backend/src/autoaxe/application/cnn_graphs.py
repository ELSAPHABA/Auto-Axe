"""Independent server-side validation and incremental reviewed graph storage."""

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb

from autoaxe.domain.canonical import canonical_sha256

BLOCKS = (
    "fear_and_greed_historical",
    "market_momentum_sp500",
    "market_momentum_sp125",
    "stock_price_strength",
    "stock_price_breadth",
    "put_call_options",
    "market_volatility_vix",
    "market_volatility_vix_50",
    "junk_bond_demand",
    "safe_haven_demand",
)
COMPARISONS = {"previous_close", "previous_1_week", "previous_1_month", "previous_1_year"}
MA = {"market_momentum_sp125", "market_volatility_vix_50"}
RATINGS = {"Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed"}


def _number(raw: Any, score: bool = False) -> None:
    if (
        not isinstance(raw, str)
        or not 1 <= len(raw) <= 64
        or not re.fullmatch(r"-?[0-9]+(?:\.[0-9]{1,24})?", raw)
    ):
        raise ValueError("invalid CNN graph number")
    value = Decimal(raw)
    if abs(value) > Decimal("1e15") or (score and not 0 <= value <= 100):
        raise ValueError("CNN graph value out of range")


def _stamp(raw: Any, cutoff: datetime) -> datetime:
    if not isinstance(raw, str) or len(raw) > 64:
        raise ValueError("invalid CNN graph time")
    stamp = datetime.fromisoformat(raw)
    if stamp.utcoffset() is None or not datetime(2000, 1, 1, tzinfo=UTC) <= stamp <= cutoff:
        raise ValueError("CNN graph time out of range")
    return stamp


def _rating(raw: Any, optional: bool = False) -> None:
    if optional and raw is None:
        return
    if not isinstance(raw, str) or raw not in RATINGS:
        raise ValueError("invalid CNN graph rating")


def validate_details(data: Any, cutoff: datetime) -> None:
    if not isinstance(data, dict) or set(data) != {"comparisons", "blocks"}:
        raise ValueError("missing CNN graph envelope")
    comparisons, blocks = data["comparisons"], data["blocks"]
    if (
        not isinstance(comparisons, dict)
        or set(comparisons) != COMPARISONS
        or not isinstance(blocks, dict)
        or set(blocks) != set(BLOCKS)
    ):
        raise ValueError("invalid CNN graph keys")
    for value in comparisons.values():
        _number(value, True)
    for key, block in blocks.items():
        if not isinstance(block, dict) or set(block) != {"timestamp", "score", "rating", "data"}:
            raise ValueError("invalid CNN graph block")
        _stamp(block["timestamp"], cutoff)
        if block["score"] is not None or key not in MA:
            _number(block["score"], True)
        _rating(block["rating"], key in MA)
        points = block["data"]
        if not isinstance(points, list) or not 1 <= len(points) <= 400:
            raise ValueError("invalid CNN graph length")
        seen = set()
        for point in points:
            if not isinstance(point, list) or len(point) != 3:
                raise ValueError("invalid CNN graph point")
            stamp = _stamp(point[0], cutoff)
            if stamp in seen:
                raise ValueError("duplicate CNN graph time")
            seen.add(stamp)
            _number(point[1], key == BLOCKS[0])
            _rating(point[2], True)


def save_graphs(
    conn: Connection[Any],
    details: dict[str, Any],
    *,
    version: int,
    received: datetime,
    reviewed: datetime,
    job_id: str,
) -> dict[str, Any]:
    """Caller holds source lock and independently reviewed the entire candidate."""
    validate_details(details, received)
    points: list[dict[str, Any]] = []
    components = {}
    for key in BLOCKS:
        block = details["blocks"][key]
        components[key] = {k: block[k] for k in ("timestamp", "score", "rating")}
        points.extend(
            {"graph_key": key, "point_at": p[0], "value": p[1], "rating": p[2]}
            for p in block["data"]
        )
        if key != BLOCKS[0] and block["score"] is not None:
            points.append(
                {
                    "graph_key": "score:" + key,
                    "point_at": block["timestamp"],
                    "value": block["score"],
                    "rating": block["rating"],
                }
            )
    # Compare with latest revision, not with any historical hash: A->B->A is a correction.
    conn.execute(
        """
        INSERT INTO indicators.cnn_graph_points
        (permission_version,graph_key,point_at,revision,value,rating,received_at,available_at,job_id)
        SELECT %s,p.graph_key,p.point_at,COALESCE(old.revision,0)+1,
               p.value,p.rating,%s,%s,%s
        FROM jsonb_to_recordset(%s)
            AS p(graph_key text,point_at timestamptz,value numeric,rating text)
        LEFT JOIN LATERAL (
            SELECT revision,value,rating FROM indicators.cnn_graph_points
            WHERE permission_version=%s AND graph_key=p.graph_key AND point_at=p.point_at
            ORDER BY revision DESC LIMIT 1
        ) old ON true
        WHERE old.revision IS NULL OR (old.value,old.rating) IS DISTINCT FROM (p.value,p.rating)
    """,
        (version, received, reviewed, job_id, Jsonb(points), version),
    )
    return {
        "comparisons": details["comparisons"],
        "components": components,
        "graph_hash": canonical_sha256(details),
        "permission_version": version,
    }
