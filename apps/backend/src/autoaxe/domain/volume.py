"""Last Yahoo day_volume sampled locally at 1 Hz, never represented as exchange ticks."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from autoaxe.domain.types import utc_datetime

NEW_YORK = ZoneInfo("America/New_York")
SYMBOLS = ("NVDA", "QLD")


@dataclass(frozen=True)
class VolumeSample:
    symbol: str
    sampled_at: datetime
    source_event_at: datetime | None
    received_at: datetime | None
    day_volume: int | None
    status: str
    updated_since_previous_sample: bool
    source_age_seconds: float | None
    receive_age_seconds: float | None
    delta_since_new_event: int | None
    market_hours: str | None


@dataclass
class _Latest:
    volume: int
    source_event_at: datetime
    received_at: datetime
    session: str
    market_hours: str | None
    generation: int
    reset: bool
    delta: int | None


class VolumeSampler:
    def __init__(self, stale_after_seconds: int = 5) -> None:
        if stale_after_seconds < 1:
            raise ValueError("invalid TTL")
        self.stale_after = stale_after_seconds
        self._latest: dict[str, _Latest] = {}
        self._sampled: dict[str, int] = {}
        self._disconnected = False

    def disconnect(self) -> None:
        self._disconnected = True

    def reconnect(self) -> None:
        self._disconnected = False  # A reconnect is not proof of a fresh tick.

    def observe(self, message: dict[str, Any], received_at: datetime) -> bool:
        utc_datetime(received_at)
        symbol = message.get("id")
        if symbol not in SYMBOLS or "day_volume" not in message or "time" not in message:
            return False
        try:
            raw = message["day_volume"]
            if isinstance(raw, bool):
                return False
            volume = int(raw)
            if str(raw).strip() != str(volume) or volume < 0:
                return False
            timestamp = int(message["time"])
            if timestamp < 0:
                return False
            event_at = datetime.fromtimestamp(
                timestamp / 1000 if timestamp >= 100_000_000_000 else timestamp, tz=UTC
            )
        except (ValueError, TypeError, OverflowError, OSError):
            return False
        if event_at > received_at:
            return False
        previous = self._latest.get(symbol)
        if previous and event_at <= previous.source_event_at:
            return False
        session = event_at.astimezone(NEW_YORK).date().isoformat()
        reset = bool(previous and (previous.session != session or volume < previous.volume))
        delta = None if previous is None or reset else volume - previous.volume
        self._latest[symbol] = _Latest(
            volume,
            event_at,
            received_at,
            session,
            message.get("market_hours"),
            previous.generation + 1 if previous else 1,
            reset,
            delta,
        )
        return True

    def sample(self, symbol: str, now: datetime) -> VolumeSample:
        utc_datetime(now)
        if symbol not in SYMBOLS:
            raise ValueError("unregistered symbol")
        item = self._latest.get(symbol)
        if item is None:
            return VolumeSample(
                symbol,
                now,
                None,
                None,
                None,
                "disconnected" if self._disconnected else "no_data",
                False,
                None,
                None,
                None,
                None,
            )
        changed = self._sampled.get(symbol) != item.generation
        receive_age = (now - item.received_at).total_seconds()
        source_age = (now - item.source_event_at).total_seconds()
        status = (
            "disconnected"
            if self._disconnected
            else "stale"
            if receive_age > self.stale_after or source_age < 0
            else "session_reset"
            if changed and item.reset
            else "fresh"
            if changed
            else "no_update"
        )
        self._sampled[symbol] = item.generation
        return VolumeSample(
            symbol,
            now,
            item.source_event_at,
            item.received_at,
            item.volume,
            status,
            changed,
            source_age,
            receive_age,
            item.delta if changed else None,
            item.market_hours,
        )
