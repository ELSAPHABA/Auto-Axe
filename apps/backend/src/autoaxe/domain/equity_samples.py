"""Canonical equity samples and as-of daily snapshots."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, TypedDict

from autoaxe.domain.equity_calendar import CALENDAR_VERSION, scheduled_close
from autoaxe.domain.indicator_math import ClosedBar, derive_features, financial_snapshot
from autoaxe.domain.market import Candidate, Quality
from autoaxe.domain.types import decimal_string, utc_datetime, utc_string
from autoaxe.domain.volume import NEW_YORK, SYMBOLS, VolumeSample, VolumeSampler

VOLUME_IDS = tuple(f"US_STOCK_DAILY_CUM_VOLUME_1S_{s}" for s in SYMBOLS)
HISTORY_IDS = tuple(f"{s}_DAILY_OHLCV" for s in SYMBOLS)
FUNDAMENTAL_IDS = tuple(f"{s}_FUNDAMENTALS" for s in SYMBOLS)


class EquitySampler:
    """Preserve existing cache semantics, additionally fence market-hours transitions."""

    def __init__(self) -> None:
        self.cache = VolumeSampler()
        self.last: dict[str, tuple[int, str, str | None]] = {}
        self.reset_pending: set[str] = set()
        self.reconnect_pending: set[str] = set()

    def observe(self, message: dict[str, Any], received: datetime) -> bool:
        symbol = message.get("id")
        if symbol not in SYMBOLS:
            return False
        hours = message.get("market_hours")
        if hours is not None and (not isinstance(hours, str) or len(hours) > 40):
            return False
        timestamp = message.get("time")
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, str)):
            return False
        if not self.cache.observe(message, received):
            return False
        if symbol in self.reconnect_pending:
            self.reconnect_pending.remove(symbol)
            if symbol in self.last:
                self.reset_pending.add(symbol)
        # Cache validated the timestamp and volume. Do not sample here: that
        # would advance the generation before the scheduled local sample.
        millis_or_seconds = int(timestamp)
        event = datetime.fromtimestamp(
            millis_or_seconds / 1000 if millis_or_seconds >= 100_000_000_000 else millis_or_seconds,
            tz=UTC,
        )
        current = (int(message["day_volume"]), event.astimezone(NEW_YORK).date().isoformat(), hours)
        old = self.last.get(symbol)
        if old and (current[0] < old[0] or current[1:] != old[1:]):
            self.reset_pending.add(symbol)
        self.last[symbol] = current
        return True

    def disconnect(self) -> None:
        self.cache.disconnect()

    def reconnect(self) -> None:
        self.cache.reconnect()
        self.reconnect_pending = set(SYMBOLS)

    def sample(self, symbol: str, now: datetime) -> VolumeSample:
        row = self.cache.sample(symbol, now)
        if symbol in self.reconnect_pending:
            row = replace(row, status="disconnected", delta_since_new_event=None)
        if row.status not in {"no_data", "disconnected"} and (
            row.source_age_seconds is None
            or row.source_age_seconds > self.cache.stale_after
            or row.receive_age_seconds is None
            or row.receive_age_seconds < 0
        ):
            row = replace(row, status="stale", delta_since_new_event=None)
        if symbol in self.reset_pending and row.updated_since_previous_sample:
            self.reset_pending.remove(symbol)
            row = replace(
                row,
                status="session_reset" if row.status == "fresh" else row.status,
                delta_since_new_event=None,
            )
        if row.status in {"disconnected", "stale", "no_data"}:
            row = replace(row, delta_since_new_event=None)
        return row


def volume_candidate(sample: VolumeSample) -> Candidate:
    quality = {
        "fresh": Quality.VALID,
        "no_update": Quality.NO_UPDATE,
        "session_reset": Quality.UNKNOWN,
        "stale": Quality.STALE,
        "disconnected": Quality.DISCONNECTED,
        "no_data": Quality.NO_DATA,
    }[sample.status]
    now = sample.sampled_at
    return Candidate(
        f"US_STOCK_DAILY_CUM_VOLUME_1S_{sample.symbol}",
        str(int(now.timestamp())),
        str(sample.day_volume) if sample.day_volume is not None else None,
        sample.source_event_at,
        now,
        now,
        quality,
        {
            "symbol": sample.symbol,
            "provider": "yfinance_yahoo_stream",
            "data_status": sample.status,
            "sampled_at_utc": utc_string(now),
            "last_received_at_utc": utc_string(sample.received_at) if sample.received_at else None,
            "source_age_sec": sample.source_age_seconds,
            "receive_age_sec": sample.receive_age_seconds,
            "updated_since_previous_sample": sample.updated_since_previous_sample,
            "delta_since_last_new_observation": sample.delta_since_new_event,
            "market_hours": sample.market_hours,
            "provider_1hz_guaranteed": False,
        },
    )


def fundamentals_candidate(symbol: str, data: dict[str, Any], now: datetime) -> Candidate:
    snapshot = financial_snapshot(symbol, "etf" if symbol == "QLD" else "equity", data, now)
    snapshot["captured_at"] = utc_string(now)
    # There is no provider publication timestamp and no single numeric value
    # for four metrics. Preserve their typed provenance; not a valid quote.
    return Candidate(
        f"{symbol}_FUNDAMENTALS",
        utc_string(now),
        None,
        None,
        now,
        now,
        Quality.UNKNOWN if snapshot["quality"] == "valid" else Quality.NO_DATA,
        snapshot,
    )


class FeatureMetadata(TypedDict):
    value: str | None
    quality: Literal["valid", "warmup"]
    window: int


class DailyMetadata(TypedDict):
    symbol: str
    session_date: str
    observation_date: str
    open: str
    high: str
    low: str
    close: str
    volume: str
    price_basis: Literal["adjusted"]
    interval: Literal["1d"]
    bar_closed: Literal[True]
    close_confirmation: Literal["provider_final_and_scheduled_close"]
    calendar_verified: Literal[True]
    calendar_version: str
    scheduled_close_utc: str
    provider_final: Literal[True]
    historical_backfill_valid: Literal[False]
    features: dict[str, FeatureMetadata]


def history_candidates(
    symbol: str,
    rows: list[dict[str, Any]],
    now: datetime,
) -> list[Candidate]:
    """Require a reviewed session and explicit final-bar evidence.

    Fixture/approved adapters must supply provider_final=True only when
    the documented provider contract establishes finality. Scheduled close
    alone cannot prove finality or publication. Availability is capture time.
    """
    if symbol not in SYMBOLS or len(rows) > 600:
        raise ValueError("invalid history request")
    now = utc_datetime(now)
    today = now.astimezone(NEW_YORK).date()
    scheduled_close(symbol, today)  # fail closed on expired calendar
    items: list[tuple[ClosedBar, dict[str, Any], datetime]] = []
    seen: set[str] = set()
    for row in rows:
        stamp = row["session_at"]
        if not isinstance(stamp, datetime):
            raise ValueError("invalid daily index")
        day = utc_datetime(stamp).astimezone(NEW_YORK).date()
        if day > today:
            continue
        close_at = scheduled_close(symbol, day)
        session = day.isoformat()
        if session in seen or close_at is None:
            raise ValueError("invalid or duplicate daily session")
        seen.add(session)
        if now < close_at or row.get("provider_final") is not True:
            continue
        values = {
            key: decimal_string(row[key]) for key in ("open", "high", "low", "close", "volume")
        }
        if (
            not Decimal(values["low"]) <= Decimal(values["open"]) <= Decimal(values["high"])
            or min(Decimal(values[k]) for k in ("open", "high", "low", "close")) <= 0
            or Decimal(values["volume"]) < 0
            or Decimal(values["volume"]) != Decimal(values["volume"]).to_integral_value()
        ):
            raise ValueError("invalid OHLCV")
        bar = ClosedBar(
            session, values["close"], values["high"], values["low"], now, True, "adjusted"
        )
        items.append((bar, values, close_at))
    items.sort(key=lambda pair: pair[0].session)
    bars = [item[0] for item in items]
    result: list[Candidate] = []
    for i, (bar, values, close_at) in enumerate(items):
        # Only the latest historical bar receives a current snapshot of
        # calculated features; avoid suggesting earlier PIT feature values.
        features = derive_features(bars, now, basis="adjusted") if i == len(items) - 1 else {}
        metadata: DailyMetadata = {
            "symbol": symbol,
            "session_date": bar.session,
            "observation_date": bar.session,
            "open": values["open"],
            "high": values["high"],
            "low": values["low"],
            "close": values["close"],
            "volume": values["volume"],
            "price_basis": "adjusted",
            "interval": "1d",
            "bar_closed": True,
            "close_confirmation": "provider_final_and_scheduled_close",
            "calendar_verified": True,
            "calendar_version": CALENDAR_VERSION,
            "scheduled_close_utc": utc_string(close_at),
            "provider_final": True,
            "historical_backfill_valid": False,
            "features": {
                name: {"value": feature.value, "quality": feature.quality, "window": feature.window}
                for name, feature in features.items()
            },
        }
        # Daily bar dates are not provider event timestamps.
        result.append(
            Candidate(
                f"{symbol}_DAILY_OHLCV",
                bar.session,
                bar.close,
                None,
                now,
                now,
                Quality.UNKNOWN,
                dict(metadata),
            )
        )
    return result
