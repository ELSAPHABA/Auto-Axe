"""Cache-first confirmed daily OHLCV planning and contiguous feature calculation."""

from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from autoaxe.domain.equity_calendar import ReviewedCalendar
from autoaxe.domain.indicator_math import WINDOWS, ClosedBar, derive_features
from autoaxe.domain.market import Candidate
from autoaxe.domain.types import decimal_string, utc_datetime, utc_string
from autoaxe.domain.volume import NEW_YORK

MAX_HISTORY = 2000
MAX_RANGES = 8


def confirmed_cache(
    rows: list[Candidate],
    symbol: str,
    now: datetime,
    calendar: ReviewedCalendar,
    generation: str | None,
) -> dict[date, Candidate]:
    """Ignore incompatible, invalidated, incomplete or not-yet-available bars."""
    result = {}
    today = now.astimezone(NEW_YORK).date()
    for row in rows:
        m = row.metadata
        try:
            day = date.fromisoformat(row.key)
            if (
                row.series_id != f"{symbol}_DAILY_OHLCV"
                or row.available_at > now
                or day > today
                or m["symbol"] != symbol
                or m["session_date"] != row.key
                or m["interval"] != "1d"
                or m["price_basis"] != "adjusted"
                or m.get("adjustment_generation") != generation
                or m.get("provider_final") is not True
                or m.get("bar_closed") is not True
                or m.get("calendar_verified") is not True
                or m.get("close_confirmation") != "provider_final_and_scheduled_close"
                or m.get("invalidated") is True
                or m["calendar_version"] != calendar.year(symbol, day, as_of=today).version
            ):
                continue
            close = calendar.close(symbol, day, as_of=today)
            if (
                close is None
                or close > row.available_at
                or m["scheduled_close_utc"] != utc_string(close)
            ):
                continue
            o, h, low, c, vol = (
                Decimal(decimal_string(m[k])) for k in ("open", "high", "low", "close", "volume")
            )
            if not (
                0 < low <= o <= h
                and low <= c <= h
                and vol >= 0
                and vol == vol.to_integral_value()
                and row.value is not None
                and Decimal(row.value) == c
            ):
                continue
            result[day] = row
        except (ValueError, TypeError, KeyError):
            continue
    return result


def expected_sessions(
    symbol: str,
    now: datetime,
    calendar: ReviewedCalendar,
    cached: dict[date, Candidate],
) -> list[date]:
    """At least 200 closed sessions, preserve earliest reviewed EMA anchor."""
    today = utc_datetime(now).astimezone(NEW_YORK).date()
    calendar.year(symbol, today, as_of=today)
    anchors = list(cached)
    for row in cached.values():
        seed = row.metadata.get("ema_seed_start")
        if isinstance(seed, str):
            anchors.append(date.fromisoformat(seed))
    anchor = min(anchors, default=today)
    days: list[date] = []
    day = today
    while (len(days) < max(WINDOWS) or day >= anchor) and len(days) < MAX_HISTORY:
        if (symbol, day.year) not in calendar.schedules:
            break
        close = calendar.close(symbol, day, as_of=today)
        if close is not None and close <= now:
            days.append(day)
        day -= timedelta(days=1)
    if len(days) == MAX_HISTORY and day >= anchor:
        raise ValueError("equity history exceeds bounded seed range")
    return list(reversed(days))


def missing_ranges(expected: list[date], cached: dict[date, Candidate]) -> list[tuple[date, date]]:
    groups: list[tuple[date, date]] = []
    start: date | None = None
    end: date | None = None
    for day in expected:
        if day in cached:
            if start is not None and end is not None:
                groups.append((start, end))
            start = end = None
            continue
        if start is None:
            start = day
        elif (day - start).days > 550:
            assert end is not None
            groups.append((start, end))
            start = day
        end = day
    if start is not None and end is not None:
        groups.append((start, end))
    return groups[:MAX_RANGES]


def feature_snapshot(
    expected: list[date],
    cached: dict[date, Candidate],
    now: datetime,
) -> Candidate | None:
    """No gap skipping: rolling windows use a contiguous tail, EMA needs seed history."""
    if not expected or not cached:
        return None
    suffix: list[date] = []
    for day in reversed(expected):
        if day not in cached:
            break
        suffix.append(day)
    suffix.reverse()
    bars = [
        ClosedBar(
            day.isoformat(),
            cached[day].metadata["close"],
            cached[day].metadata["high"],
            cached[day].metadata["low"],
            cached[day].available_at,
            True,
            "adjusted",
        )
        for day in suffix
    ]
    features = derive_features(bars, now, basis="adjusted")
    meta: dict[str, Any] = {}
    for name, feature in features.items():
        # An EMA cannot restart after a gap or before initial seed warmup.
        valid = not name.startswith("EMA_") or (
            len(suffix) == len(expected) and len(expected) >= max(WINDOWS)
        )
        meta[name] = {
            "value": feature.value if valid else None,
            "quality": feature.quality if valid else "warmup",
            "window": feature.window,
        }
    latest = cached[max(cached)]
    metadata = {
        **latest.metadata,
        "features": meta,
        "ema_seed_start": expected[0].isoformat(),
        "ema_seed_policy": "first_close_adjust_false",
        "required_session_count": len(expected),
        "contiguous_session_count": len(suffix),
        "feature_target_session": expected[-1].isoformat(),
    }
    return replace(latest, metadata=metadata, available_at=now)
