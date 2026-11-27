"""Fixed public calendar HTML contracts, without browser or implicit timestamps.

Reviewed visible table/heading structure (2026-11-27):
https://www.census.gov/economic-indicators/calendar-listview.html
https://www.census.gov/retail/release_schedule.html
https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
Retail's ET convention: https://www2.census.gov/marts/adv2405.pdf
No arbitrary selector, link following, Javascript, or inferred decision time.
"""

import hashlib
import re
from datetime import UTC, date, datetime, time, timedelta
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

from autoaxe.domain.calendars import CalendarEvidence, EventRevision
from autoaxe.domain.economic_linkage import MONTHS
from autoaxe.domain.types import utc_datetime

CENSUS_CALENDAR_URL = "https://www.census.gov/economic-indicators/calendar-listview.html"
CENSUS_RETAIL_CALENDAR_URL = "https://www.census.gov/retail/release_schedule.html"
FED_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
RETAIL = "Advance Monthly Sales for Retail and Food Services"
ET = ZoneInfo("America/New_York")
_BLOCK = frozenset(
    {
        "div",
        "section",
        "article",
        "main",
        "p",
        "li",
        "br",
        "tr",
        "td",
        "th",
        "table",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "footer",
        "nav",
    }
)


class _VisibleHTML(HTMLParser):
    """Read semantic tables and block text; ignore scripts/styles/templates."""

    def __init__(self, raw: bytes):
        super().__init__(convert_charrefs=True)
        if not 0 < len(raw) <= 1_000_000:
            raise ValueError("calendar HTML size invalid")
        self.blocks: list[str] = []
        self.tables: list[list[list[str]]] = []
        self._buffer: list[str] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._hidden = 0
        self.feed(raw.decode("utf-8-sig"))
        self.close()
        self._flush()
        if self._table is not None or self._row is not None or self._cell is not None:
            raise ValueError("incomplete calendar table")

    def _flush(self) -> None:
        value = " ".join("".join(self._buffer).split())
        self._buffer.clear()
        if value:
            self.blocks.append(value)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "template", "noscript"}:
            self._hidden += 1
        if self._hidden:
            return
        if tag in _BLOCK:
            self._flush()
        if tag == "table":
            if self._table is not None:
                raise ValueError("nested calendar table")
            self._table = []
        elif tag == "tr" and self._table is not None:
            if self._row is not None:
                raise ValueError("incomplete calendar row")
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            if self._cell is not None:
                raise ValueError("incomplete calendar cell")
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "template", "noscript"}:
            self._hidden = max(0, self._hidden - 1)
            return
        if self._hidden:
            return
        if tag in _BLOCK:
            self._flush()
        if tag in {"td", "th"} and self._cell is not None:
            assert self._row is not None
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._cell is not None:
                raise ValueError("unclosed calendar cell")
            assert self._table is not None
            self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._row is not None:
                raise ValueError("unclosed calendar row")
            self.tables.append(self._table)
            self._table = None

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self._buffer.append(data)
            if self._cell is not None:
                self._cell.append(data)


def _month(value: str) -> int:
    if value in MONTHS:
        return MONTHS.index(value) + 1
    short = [name[:3] for name in MONTHS]
    if value in short:
        return short.index(value) + 1
    raise ValueError("unknown calendar month")


def _day(raw: str) -> date:
    match = re.fullmatch(r"([A-Za-z]+) ([0-9]{1,2}), ([0-9]{4})", raw)
    if not match:
        raise ValueError("unrecognized explicit release date")
    month, day, year = match.groups()
    return date(int(year), _month(month), int(day))


def _clock(raw: str) -> time:
    match = re.fullmatch(r"([1-9]|1[0-2]):([0-5][0-9]) (AM|PM)", raw)
    if not match:
        raise ValueError("unrecognized explicit release time")
    hour, minute, half = match.groups()
    return time(int(hour) % 12 + (12 if half == "PM" else 0), int(minute))


def _period(raw: str) -> str:
    match = re.fullmatch(r"([A-Za-z]+) ([0-9]{4})", raw)
    if not match:
        raise ValueError("unrecognized explicit covered month")
    return f"{match[2]}-{_month(match[1]):02d}"


def _event(
    key: str,
    source: str,
    url: str,
    received: datetime,
    title: str,
    day: date,
    *,
    stamp: datetime | None = None,
    tentative: bool = False,
) -> EventRevision:
    return EventRevision(
        key,
        source,
        stamp,
        None,
        received,
        received,
        None,
        None,
        None,
        "event",
        1,
        url,
        CalendarEvidence(
            title, None if stamp is not None else day, "tentative" if tentative else "unspecified"
        ),
    )


def parse_census_calendar(raw: bytes, received: datetime) -> list[EventRevision]:
    """General annual list view: use explicit visible columns, not hidden sort keys.

    Non-retail rows preserve the published clock as a label, not an offset-aware
    timestamp, because the list view does not specify a timezone. The dedicated
    retail task below owns retail (avoids duplicated schedule identities).
    """
    utc_datetime(received)
    page = _VisibleHTML(raw)
    years = {
        int(match[1])
        for block in page.blocks
        if (
            match := re.fullmatch(
                r"US Census Bureau: ([0-9]{4}) Economic Indicator Release Schedule: List View",
                block,
            )
        )
    }
    tables = [
        table
        for table in page.tables
        if table and table[0][:4] == ["Indicator", "Release Date", "Time", "Period Covered"]
    ]
    if len(years) != 1 or len(tables) != 1:
        raise ValueError("Census calendar heading/table identity changed")
    year = years.pop()
    if year not in (received.year - 1, received.year, received.year + 1):
        raise ValueError("Census calendar year outside current scope")
    rows: list[EventRevision] = []
    for row in tables[0][1:]:
        if len(row) not in (4, 6):
            raise ValueError("Census calendar columns changed")
        indicator, date_text, clock_text, period = row[:4]
        if not indicator or not period or len(indicator) > 256 or len(period) > 64:
            raise ValueError("Census calendar identity missing")
        if indicator == RETAIL:
            continue
        day = _day(date_text)
        if day.year != year:
            raise ValueError("Census calendar date outside heading year")
        _clock(clock_text)
        key = "CENSUS_SCHEDULE:" + hashlib.sha256((indicator + "\0" + period).encode()).hexdigest()
        title = f"{indicator}, {period} (listed time {clock_text}; timezone unspecified)"
        rows.append(_event(key, "census", CENSUS_CALENDAR_URL, received, title, day))
    if not rows:
        raise ValueError("Census calendar missing rows")
    return rows


def parse_census_retail_calendar(raw: bytes, received: datetime) -> list[EventRevision]:
    """Advance monthly retail table, separate from later full monthly report."""
    utc_datetime(received)
    page = _VisibleHTML(raw)
    tables = [
        table
        for table in page.tables
        if table and table[0] == ["Data Month", "Release Date at 8:30 am"]
    ]
    if len(tables) != 1 or "Advance Monthly Retail Trade Report" not in page.blocks:
        raise ValueError("Census advance retail calendar identity changed")
    rows = []
    for row in tables[0][1:]:
        if len(row) != 2:
            raise ValueError("Census advance retail calendar columns changed")
        period_text, release_text = row
        period = _period(period_text)
        if release_text == "To be announced at a later date":
            # No date or time can be assigned.
            continue
        day = _day(release_text)
        if day <= date.fromisoformat(period + "-01"):
            raise ValueError("Census release date before covered period")
        stamp = datetime.combine(day, time(8, 30), tzinfo=ET).astimezone(UTC)
        rows.append(
            _event(
                f"CENSUS_RETAIL_SCHEDULE:{period}",
                "census",
                CENSUS_RETAIL_CALENDAR_URL,
                received,
                f"{RETAIL}, {period_text}",
                day,
                stamp=stamp,
            )
        )
    if not rows:
        raise ValueError("Census advance retail calendar missing dates")
    return rows


def parse_fed_calendar(raw: bytes, received: datetime) -> list[EventRevision]:
    """Meeting ranges, not release/decision events; every date is provisional."""
    utc_datetime(received)
    blocks = _VisibleHTML(raw).blocks
    if not any("Each meeting date is tentative until confirmed" in block for block in blocks):
        raise ValueError("FOMC calendar disclaimer missing")
    year: int | None = None
    current_year_found = False
    rows: list[EventRevision] = []
    counts: dict[int, int] = {}
    month_names = {*MONTHS, *(name[:3] for name in MONTHS)}
    for i, block in enumerate(blocks):
        heading = re.fullmatch(r"([0-9]{4}) FOMC Meetings", block)
        if heading:
            year = int(heading[1])
            if year == received.astimezone(ET).year:
                current_year_found = True
            continue
        if year not in (received.astimezone(ET).year, received.astimezone(ET).year + 1):
            continue
        names = block.split("/")
        if len(names) not in (1, 2) or not all(name in month_names for name in names):
            continue
        if i + 1 == len(blocks):
            raise ValueError("FOMC meeting date missing")
        raw_range = blocks[i + 1]
        match = re.fullmatch(r"([0-9]{1,2})(?:[-–]([0-9]{1,2}))?\*?", raw_range)
        if not match:
            # Notation votes are not scheduled policy meetings.
            if re.fullmatch(r"[0-9]{1,2} \(notation vote\)", raw_range):
                continue
            raise ValueError("FOMC meeting date format changed")
        assert year is not None
        start = date(year, _month(names[0]), int(match[1]))
        end = date(
            year + int(len(names) == 2 and _month(names[-1]) < start.month),
            _month(names[-1]),
            int(match[2] or match[1]),
        )
        if end < start or end - start > timedelta(days=7):
            raise ValueError("invalid FOMC meeting range")
        counts[year] = counts.get(year, 0) + 1
        if counts[year] > 24:
            raise ValueError("FOMC meeting calendar oversized")
        # Key is a period scope, not an inferred policy announcement date.
        title = f"FOMC meeting: {start.isoformat()} to {end.isoformat()}"
        rows.append(
            _event(
                f"FOMC_MEETING:{start:%Y-%m}",
                "fed",
                FED_CALENDAR_URL,
                received,
                title,
                start,
                tentative=True,
            )
        )
    if not current_year_found or not rows:
        raise ValueError("FOMC current year calendar missing")
    return rows
