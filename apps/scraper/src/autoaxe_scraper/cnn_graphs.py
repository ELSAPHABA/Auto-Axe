"""Normalize the bounded, observed CNN graphdata contract; no new HTTP requests."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

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
COMPARISONS = ("previous_close", "previous_1_week", "previous_1_month", "previous_1_year")
MA = {"market_momentum_sp125", "market_volatility_vix_50"}
RATINGS = {"Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed"}


def number(value: Any, *, score: bool = False) -> str:
    if type(value) not in (int, Decimal):
        raise ValueError("invalid CNN number")
    dec = Decimal(value)
    if not dec.is_finite() or abs(dec) > Decimal("1e15") or (score and not 0 <= dec <= 100):
        raise ValueError("CNN number out of range")
    # Bound formatting before expanding a Decimal exponent.
    exponent = dec.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -24:
        raise ValueError("CNN precision exceeds contract")
    return format(dec, "f")


def rating(value: Any) -> str:
    if not isinstance(value, str) or value.title() not in RATINGS:
        raise ValueError("invalid CNN rating")
    return value.title()


def milliseconds(value: Any, now: datetime) -> str:
    if type(value) not in (int, Decimal) or not Decimal(value).is_finite():
        raise ValueError("invalid CNN epoch")
    if value != int(value) or not 946684800000 <= value <= int(now.timestamp() * 1000):
        raise ValueError("CNN epoch out of range")
    return datetime.fromtimestamp(int(value) / 1000, UTC).isoformat()


def details(root: dict[str, Any], now: datetime) -> dict[str, Any]:
    head = root["fear_and_greed"]
    comparisons = {key: number(head[key], score=True) for key in COMPARISONS}
    blocks = {}
    for key in BLOCKS:
        block = root[key]
        score = block.get("score")
        label = block.get("rating")
        if key not in MA and (score is None or label is None):
            raise ValueError("missing CNN component score")
        raw = block["data"]
        if not isinstance(raw, list) or not 1 <= len(raw) <= 400:
            raise ValueError("invalid CNN history length")
        seen = set()
        rows = []
        for point in raw:
            at = milliseconds(point["x"], now)
            if at in seen:
                raise ValueError("duplicate CNN history time")
            seen.add(at)
            rows.append(
                [
                    at,
                    number(point["y"], score=key == BLOCKS[0]),
                    rating(point["rating"]) if point.get("rating") is not None else None,
                ]
            )
        blocks[key] = {
            "timestamp": milliseconds(block["timestamp"], now),
            "score": number(score, score=True) if score is not None else None,
            "rating": rating(label) if label is not None else None,
            "data": sorted(rows),
        }
    return {"comparisons": comparisons, "blocks": blocks}
