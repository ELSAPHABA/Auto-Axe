"""Synthetic, credential-free use case; no live source or order operations."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from autoaxe.domain.types import decimal_string


@dataclass(frozen=True)
class FixtureQuote:
    series_id: str
    value: str | None
    unit: str
    quality: Literal["fixture", "no_data"]
    source_event_at: datetime | None


def get_quote(series_id: str) -> FixtureQuote:
    if series_id == "FIXTURE_PRICE":
        return FixtureQuote(
            series_id,
            decimal_string("123.4500"),
            "USD",
            "fixture",
            datetime(2026, 1, 1, tzinfo=UTC),
        )
    if series_id == "FIXTURE_MISSING":
        return FixtureQuote(series_id, None, "USD", "no_data", None)
    raise KeyError(series_id)
