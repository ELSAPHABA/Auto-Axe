"""Bounded offline US equity regular-session schedule, checked 2026-11-27.

NVDA (Nasdaq) and QLD (NYSE Arca) share these published regular sessions.
Sources: Nasdaq 2024/2025 trading calendars and 2026 holiday schedule;
NYSE Group 2024–2026 holiday/early close announcement; both exchanges'
2025-01-09 special closure announcements (Nasdaq ETA2025-1 and NYSE ICE
2024-12-30). Calendar facts are not live trading-status confirmations.

https://www.nasdaqtrader.com/content/technicalsupport/2024tradingcalendar.pdf
https://www.nasdaqtrader.com/content/technicalsupport/2025tradingcalendar.pdf
https://www.nasdaq.com/market-activity/stock-market-holiday-schedule
https://www.nasdaq.com/press-release/nyse-group-announces-2024-2025-and-2026-holiday-and-early-closings-calendar-2023-11
https://www.nasdaqtrader.com/TraderNews.aspx?id=ETA2025-1
https://ir.theice.com/press/news-details/2024/The-New-York-Stock-Exchange-Will-Close-Markets-on-January-9-to-Honor-the-Passing-of-Former-President-Jimmy-Carter-on-National-Day-of-Mourning/default.aspx
https://www.nyse.com/trade/hours-calendars
"""

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from types import MappingProxyType
from typing import Any

from autoaxe.domain.canonical import canonical_sha256, strict_json
from autoaxe.domain.volume import NEW_YORK, SYMBOLS

CALENDAR_VERSION = "us_equity_regular_2024_2026_reviewed_20261127"
_HOLIDAYS = {
    2024: "01-01 01-15 02-19 03-29 05-27 06-19 07-04 09-02 11-28 12-25",
    2025: "01-01 01-09 01-20 02-17 04-18 05-26 06-19 07-04 09-01 11-27 12-25",
    2026: "01-01 01-19 02-16 04-03 05-25 06-19 07-03 09-07 11-26 12-25",
}
_EARLY = {2024: "07-03 11-29 12-24", 2025: "07-03 11-28 12-24", 2026: "11-27 12-24"}

NYSE_URL = "https://www.nyse.com/trade/hours-calendars"
NASDAQ_URL = "https://nasdaqtrader.com/Trader.aspx?id=Calendar"
SOURCE_URLS = {"QLD": NYSE_URL, "NVDA": NASDAQ_URL}
MAX_MANIFEST_BYTES = 64_000
ARCA_VERSION = "nyse_arca_regular_2027_2028_reviewed_20261127"
# NYSE Group announcement dated 2025-12-23 and official hours page,
# reviewed 2026-11-27. The 2028 New Year's holiday is explicitly not observed.
# https://ir.theice.com/press/news-details/2025/NYSE-Group-Announces-2026-2027-and-2028-Holiday-and-Early-Closings-Calendar/
_ARCA_HOLIDAYS = {
    2027: "01-01 01-18 02-15 03-26 05-31 06-18 07-05 09-06 11-25 12-24",
    2028: "01-17 02-21 04-14 05-29 06-19 07-04 09-04 11-23 12-25",
}
_ARCA_EARLY = {2027: "11-26", 2028: "07-03 11-24"}


@dataclass(frozen=True)
class YearSchedule:
    holidays: frozenset[date]
    early: frozenset[date]
    version: str
    reviewed_on: date


def _dates(year: int, values: str) -> frozenset[date]:
    return frozenset(date.fromisoformat(f"{year}-{v}") for v in values.split())


def _base() -> dict[tuple[str, int], YearSchedule]:
    result = {
        (symbol, year): YearSchedule(
            _dates(year, holidays), _dates(year, _EARLY[year]), CALENDAR_VERSION, date(2026, 11, 27)
        )
        for symbol in SYMBOLS
        for year, holidays in _HOLIDAYS.items()
    }
    for year, holidays in _ARCA_HOLIDAYS.items():
        result["QLD", year] = YearSchedule(
            _dates(year, holidays),
            _dates(year, _ARCA_EARLY[year]),
            ARCA_VERSION,
            date(2026, 11, 27),
        )
    return result


def _digest(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError("expected lowercase SHA-256")
    return value


def _date(value: object) -> date:
    if not isinstance(value, str):
        raise ValueError("invalid calendar date")
    parsed = date.fromisoformat(value)
    if value != parsed.isoformat():
        raise ValueError("noncanonical calendar date")
    return parsed


def _manifest_dates(values: object, year: int) -> frozenset[date]:
    if not isinstance(values, list) or len(values) > 64:
        raise ValueError("invalid calendar exception list")
    dates = frozenset(_date(x) for x in values)
    if len(dates) != len(values) or any(d.year != year or d.weekday() >= 5 for d in dates):
        raise ValueError("duplicate or invalid calendar exception date")
    return dates


@dataclass(frozen=True)
class ReviewedCalendar:
    schedules: Mapping[tuple[str, int], YearSchedule]

    def year(self, symbol: str, day: date, *, as_of: date | None = None) -> YearSchedule:
        schedule = self.schedules.get((symbol, day.year))
        if schedule is None:
            raise ValueError("unverified equity calendar range or symbol")
        # Retain the pre-existing historical seed contract; newly reviewed
        # extensions must not be used before their review date.
        if (
            as_of is not None
            and schedule.version != CALENDAR_VERSION
            and schedule.reviewed_on > as_of
        ):
            raise ValueError("equity calendar review not yet available")
        return schedule

    def close(self, symbol: str, day: date, *, as_of: date | None = None) -> datetime | None:
        schedule = self.year(symbol, day, as_of=as_of)
        if day.weekday() >= 5 or day in schedule.holidays:
            return None
        hour = 13 if day in schedule.early else 16
        return datetime.combine(day, time(hour), tzinfo=NEW_YORK).astimezone(UTC)


def manifest_rows(raw: bytes, expected_sha256: str) -> list[dict[str, Any]]:
    """Validate operator-reviewed content; digest pins exact bytes, not authorship."""
    if (
        not raw
        or len(raw) > MAX_MANIFEST_BYTES
        or hashlib.sha256(raw).hexdigest() != _digest(expected_sha256)
    ):
        raise ValueError("calendar manifest hash or size mismatch")
    data = strict_json(raw.decode("utf-8"))
    if (
        not isinstance(data, dict)
        or set(data) != {"schema_version", "years"}
        or (type(data["schema_version"]) is not int or data["schema_version"] != 1)
    ):
        raise ValueError("invalid calendar manifest schema")
    rows = data["years"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 20:
        raise ValueError("invalid calendar manifest coverage")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "symbol",
            "year",
            "source_url",
            "evidence_sha256",
            "reviewed_on",
            "reviewer_ref",
            "complete",
            "holidays",
            "early_closes",
        }:
            raise ValueError("invalid calendar manifest row")
        symbol, year = row["symbol"], row["year"]
        if (
            not isinstance(symbol, str)
            or symbol not in SOURCE_URLS
            or type(year) is not int
            or not 2027 <= year <= 2100
            or row["source_url"] != SOURCE_URLS[symbol]
            or row["complete"] is not True
            or not isinstance(row["reviewer_ref"], str)
            or not 1 <= len(row["reviewer_ref"].strip()) <= 256
            or (symbol, year) in seen
        ):
            raise ValueError("unreviewed or duplicate calendar scope")
        _digest(row["evidence_sha256"])
        _date(row["reviewed_on"])
        holidays = _manifest_dates(row["holidays"], year)
        early = _manifest_dates(row["early_closes"], year)
        if not 8 <= len(holidays) <= 20 or holidays & early:
            raise ValueError("incomplete or conflicting calendar exceptions")
        seen.add((symbol, year))
        result.append(row)
    return result


def load_calendar(
    manifest_path: Path | None = None,
    expected_sha256: str | None = None,
    *,
    as_of: date | None = None,
) -> ReviewedCalendar:
    """Read one pinned reviewed manifest, never load staging evidence automatically."""
    if manifest_path is None and expected_sha256 is None:
        path = os.environ.get("AUTOAXE_EQUITY_CALENDAR_MANIFEST")
        expected_sha256 = os.environ.get("AUTOAXE_EQUITY_CALENDAR_SHA256")
        manifest_path = Path(path) if path else None
    schedules = _base()
    if (manifest_path is None) != (expected_sha256 is None):
        raise ValueError("calendar manifest path and SHA-256 must be configured together")
    if manifest_path is not None and expected_sha256 is not None:
        with manifest_path.open("rb") as handle:
            raw = handle.read(MAX_MANIFEST_BYTES + 1)
        for row in manifest_rows(raw, expected_sha256):
            symbol, year = row["symbol"], row["year"]
            reviewed = _date(row["reviewed_on"])
            if reviewed > (as_of or datetime.now(UTC).date()):
                raise ValueError("future calendar review")
            previous = schedules.get((symbol, year))
            if previous and reviewed < previous.reviewed_on:
                raise ValueError("calendar review predates existing seed")
            # Pin each row, not the entire file, so unrelated years cannot
            # spuriously revise previously collected bars.
            schedules[symbol, year] = YearSchedule(
                _manifest_dates(row["holidays"], year),
                _manifest_dates(row["early_closes"], year),
                f"reviewed_{symbol}_{year}_{canonical_sha256(row)}",
                reviewed,
            )
        for symbol in SYMBOLS:
            years = sorted(y for s, y in schedules if s == symbol)
            if years != list(range(2024, years[-1] + 1)):
                raise ValueError("calendar year gap")
    return ReviewedCalendar(MappingProxyType(schedules))


def scheduled_close(symbol: str, day: date) -> datetime | None:
    """Return scheduled regular close UTC, not provider publication time.

    No guessing beyond reviewed years, or on unregistered assets.
    """
    return load_calendar().close(symbol, day)
