"""Point-in-time technical and valuation calculations with confirmed sessions only."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from autoaxe.domain.types import decimal_string, utc_datetime

WINDOWS = (5, 20, 60, 120, 200)
RANGES = (5, 10, 20)
EMAS = (12, 26)


@dataclass(frozen=True)
class ClosedBar:
    session: str
    close: str
    high: str
    low: str
    available_at: datetime
    confirmed: bool
    adjustment: Literal["adjusted", "unadjusted"]

    def __post_init__(self) -> None:
        utc_datetime(self.available_at)
        for field in ("close", "high", "low"):
            decimal_string(getattr(self, field))
        if not Decimal(self.low) <= Decimal(self.close) <= Decimal(self.high):
            raise ValueError("inconsistent OHLC")


@dataclass(frozen=True)
class Feature:
    name: str
    value: str | None
    quality: Literal["valid", "warmup"]
    window: int
    as_of: datetime
    price_basis: Literal["adjusted", "unadjusted"]


def derive_features(
    bars: list[ClosedBar], as_of: datetime, *, basis: Literal["adjusted", "unadjusted"]
) -> dict[str, Feature]:
    """Unconfirmed/unavailable candles cannot enter current or historical features."""
    utc_datetime(as_of)
    allowed = [
        bar
        for bar in bars
        if bar.confirmed and bar.available_at <= as_of and bar.adjustment == basis
    ]
    if len({bar.session for bar in allowed}) != len(allowed):
        raise ValueError("duplicate trading session")
    if [bar.session for bar in allowed] != sorted(bar.session for bar in allowed):
        raise ValueError("unordered trading sessions")
    closes = [Decimal(bar.close) for bar in allowed]
    highs = [Decimal(bar.high) for bar in allowed]
    lows = [Decimal(bar.low) for bar in allowed]
    result: dict[str, Feature] = {}

    def store(name: str, value: Decimal | None, window: int) -> None:
        result[name] = Feature(
            name,
            str(value) if value is not None else None,
            "valid" if value is not None else "warmup",
            window,
            as_of,
            basis,
        )

    for n in WINDOWS:
        store(f"SMA_{n}", sum(closes[-n:], Decimal(0)) / n if len(closes) >= n else None, n)
    for n in EMAS:
        if not closes:
            store(f"EMA_{n}", None, n)
            continue
        alpha = Decimal(2) / Decimal(n + 1)
        ema = closes[0]
        for close in closes[1:]:
            ema = close * alpha + ema * (1 - alpha)
        store(f"EMA_{n}", ema if len(closes) >= n else None, n)
    for n in RANGES:
        store(f"HIGH_{n}D", max(highs[-n:]) if len(highs) >= n else None, n)
        store(f"LOW_{n}D", min(lows[-n:]) if len(lows) >= n else None, n)
    return result


def financial_snapshot(
    symbol: str,
    asset_type: Literal["equity", "etf"],
    data: dict[str, Any],
    captured_at: datetime,
    financial_period_end: str | None = None,
) -> dict[str, Any]:
    if (symbol, asset_type) not in {("NVDA", "equity"), ("QLD", "etf")}:
        raise ValueError("unregistered asset")
    utc_datetime(captured_at)
    fields = {
        "per_ttm": "trailingPE",
        "per_forward": "forwardPE",
        "pbr": "priceToBook",
        "roe_ratio": "returnOnEquity",
    }
    metrics: dict[str, str | None] = {}
    for name, key in fields.items():
        raw = data.get(key) if asset_type == "equity" else None
        if raw is None:
            metrics[name] = None
            continue
        try:
            metrics[name] = decimal_string(str(Decimal(str(raw))))
        except (ValueError, TypeError, InvalidOperation):
            metrics[name] = None
    return {
        "symbol": symbol,
        "asset_type": asset_type,
        "metrics": metrics,
        "captured_at": captured_at,
        "financial_period_end": financial_period_end,
        "quality": "valid" if any(v is not None for v in metrics.values()) else "no_data",
        "historical_backfill_valid": False,
    }
