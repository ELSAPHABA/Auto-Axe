"""Source catalog and immutable observations; no transport or framework imports."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from autoaxe.domain.types import decimal_string, utc_datetime


class Quality(StrEnum):
    VALID = "valid"
    NO_DATA = "no_data"
    NO_UPDATE = "no_update"
    STALE = "stale"
    DISCONNECTED = "disconnected"
    UNKNOWN = "unknown"
    SESSION_CLOSED = "session_closed"
    MANUAL_UNVERIFIED = "manual_unverified"
    MANUAL_CHECKED = "manual_checked"


@dataclass(frozen=True)
class Series:
    id: str
    indicator_id: str
    source_id: str
    symbol: str
    instrument_type: str
    unit: str
    currency: str | None
    interval: str
    ttl: int | None
    priority: int = 1
    mapping_version: int = 1


@dataclass(frozen=True)
class Candidate:
    series_id: str
    key: str
    value: str | None
    source_event_at: datetime | None
    received_at: datetime
    available_at: datetime
    quality: Quality = Quality.VALID
    metadata: dict[str, Any] = field(default_factory=dict)
    mapping_version: int = 1

    def __post_init__(self) -> None:
        if not self.key or len(self.key) > 256:
            raise ValueError("invalid event key")
        for stamp in (self.received_at, self.available_at, self.source_event_at):
            if stamp is not None:
                utc_datetime(stamp)
        if self.available_at < self.received_at:
            raise ValueError("available_at cannot precede first observation")
        if self.source_event_at and self.source_event_at > self.received_at:
            raise ValueError("future source event")
        if self.value is not None:
            object.__setattr__(self, "value", decimal_string(self.value))
        if self.quality == Quality.VALID and (self.value is None or self.source_event_at is None):
            raise ValueError("valid observation requires source time and value")
        if self.quality == Quality.NO_DATA and self.value is not None:
            raise ValueError("no_data must have null value")


def quality_at(item: Candidate, series: Series, now: datetime) -> Quality:
    utc_datetime(now)
    if item.quality not in (Quality.VALID, Quality.MANUAL_CHECKED):
        return item.quality
    if item.source_event_at is None or series.ttl is None:
        return Quality.UNKNOWN
    age = (now - item.source_event_at).total_seconds()
    if age < 0:
        return Quality.UNKNOWN
    if age > series.ttl:
        return Quality.STALE
    if item.metadata.get("bar_closed") is False:
        return Quality.UNKNOWN
    return item.quality


def change_pct(before: Candidate, after: Candidate) -> Decimal | None:
    if (
        before.series_id != after.series_id
        or before.mapping_version != after.mapping_version
        or before.quality != Quality.VALID
        or after.quality != Quality.VALID
        or before.value is None
        or after.value is None
        or Decimal(before.value) == 0
        or before.source_event_at is None
        or after.source_event_at is None
        or after.source_event_at <= before.source_event_at
        or before.metadata.get("bar_closed") is False
        or after.metadata.get("bar_closed") is False
    ):
        return None
    return (Decimal(after.value) / Decimal(before.value) - 1) * 100
