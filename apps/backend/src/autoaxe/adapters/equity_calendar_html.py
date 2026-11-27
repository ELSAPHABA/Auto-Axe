"""Strict visible annual calendar tables, reviewed against official pages 2026-11-27.

NYSE: https://www.nyse.com/trade/hours-calendars
NasdaqTrader: https://nasdaqtrader.com/Trader.aspx?id=Calendar
Never calculate a holiday or early close from a holiday rule. Unknown layouts
are pending manual investigation, not a default normal trading session.
"""

import re
from dataclasses import dataclass
from datetime import date

from autoaxe.adapters.official_calendar_html import _VisibleHTML

MONTHS = (
    "January February March April May June July August September October November December"
).split()
WEEKDAYS = "Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split()
HOLIDAYS = (
    "New Year's Day",
    "Martin Luther King, Jr. Day",
    "Washington's Birthday",
    "Good Friday",
    "Memorial Day",
    "Juneteenth National Independence Day",
    "Independence Day",
    "Labor Day",
    "Thanksgiving Day",
    "Christmas Day",
)
NASDAQ_NAMES = (
    "New Years Day (Observed)",
    "Martin Luther King, Jr. Day",
    "President's Day - U.S.",
    "Good Friday",
    "Memorial Day - U.S.",
    "Juneteenth Holiday (Observed)",
    "Independence Day - U.S. (Observed)",
    "Labor Day - U.S.",
    "Thanksgiving Day - U.S.",
    "Christmas Holiday - U.S.",
)
DATE = rf"({'|'.join(MONTHS)}) (\d{{1,2}})"
DAY = rf"({'|'.join(WEEKDAYS)}), {DATE}"


@dataclass(frozen=True)
class ExtractedYear:
    year: int
    holidays: tuple[str, ...]
    early_closes: tuple[str, ...]


def _date(year: int, month: str, day: str, weekday: str | None = None) -> date:
    result = date(year, MONTHS.index(month) + 1, int(day))
    if result.weekday() >= 5 or (weekday is not None and WEEKDAYS[result.weekday()] != weekday):
        raise ValueError("invalid calendar weekday")
    return result


def _result(year: int, closed: list[date], early: list[date]) -> ExtractedYear:
    if (
        len(closed) not in (9, 10)
        or not early
        or len(set(closed)) != len(closed)
        or len(set(early)) != len(early)
        or set(closed) & set(early)
        or any(d.year != year for d in closed + early)
    ):
        raise ValueError("incomplete or conflicting annual calendar")
    return ExtractedYear(
        year,
        tuple(d.isoformat() for d in sorted(closed)),
        tuple(d.isoformat() for d in sorted(early)),
    )


def _norm(value: str) -> str:
    return value.replace("’", "'").strip()


def _nyse(html: _VisibleHTML) -> list[ExtractedYear]:
    candidates = [t for t in html.tables if t and t[0] and t[0][0] == "Holiday"]
    if len(candidates) != 1:
        raise ValueError("ambiguous NYSE annual table")
    header, *rows = candidates[0]
    if not 2 <= len(header) <= 5 or any(not re.fullmatch(r"20\d{2}", y) for y in header[1:]):
        raise ValueError("invalid NYSE year columns")
    years = [int(y) for y in header[1:]]
    if years != list(range(years[0], years[0] + len(years))):
        raise ValueError("nonconsecutive NYSE years")
    scope = "All NYSE markets observe U.S. holidays as listed below for "
    if not any(
        b.startswith(scope) and [int(y) for y in re.findall(r"\b20\d{2}\b", b)] == years
        for b in html.blocks
    ):
        raise ValueError("missing NYSE annual scope")
    if len(rows) != len(HOLIDAYS) or any(len(r) != len(header) for r in rows):
        raise ValueError("incomplete NYSE holiday rows")
    if tuple(_norm(r[0]) for r in rows) != HOLIDAYS:
        raise ValueError("unrecognized NYSE holiday names/order")
    notes: dict[str, str] = {}
    for block in html.blocks:
        match = re.match(
            r"^(\*{1,4})\s+(Because the holiday falls|Each market will close early)", block
        )
        if match:
            marker = match[1]
            if marker in notes:
                raise ValueError("duplicate NYSE footnote")
            notes[marker] = _norm(block[len(marker) :])
    used: set[str] = set()
    results = []
    for column, year in enumerate(years, 1):
        closed: list[date] = []
        early: list[date] = []
        markers: set[str] = set()
        for row in rows:
            label, cell = _norm(row[0]), _norm(row[column])
            match = re.fullmatch(DAY + r"(?: \(([^()]+) observed\))?\s*(\*{1,4})?", cell)
            if not match:
                missing = re.fullmatch(r"[—–-]\s*(\*{1,4})", cell)
                if label != HOLIDAYS[0] or not missing:
                    raise ValueError("missing or unknown NYSE date")
                marker = missing[1]
                note = notes.get(marker, "")
                expected = (
                    f"Because the holiday falls on Saturday, January 1, {year}, "
                    "no New Year's Day holiday is observed."
                )
                if note != expected or date(year, 1, 1).weekday() != 5:
                    raise ValueError("unverified NYSE non-observance")
                used.add(marker)
                continue
            weekday, month, day, observed, marker = match.groups()
            if observed is not None and observed != label:
                raise ValueError("NYSE observed holiday mismatch")
            closed.append(_date(year, month, day, weekday))
            if marker:
                markers.add(marker)
        for marker in sorted(markers):
            note = notes.get(marker, "")
            prefix = (
                "Each market will close early at 1:00 p.m. (1:15 p.m. for eligible options) on "
            )
            if not note.startswith(prefix) or "All times are Eastern Time." not in note:
                raise ValueError("missing NYSE regular-session early close note")
            # Match only the explicitly enumerated dates before late-session text.
            listing = note[len(prefix) :].split(". NYSE American Equities", 1)[0]
            listing = listing.removesuffix(" (the day after Thanksgiving)")
            dates = list(re.finditer(DAY + r", (20\d{2})", listing))
            remainder = re.sub(DAY + r", 20\d{2}", "", listing)
            if not dates or re.sub(r"[\s,.]|\band\b", "", remainder):
                raise ValueError("ambiguous NYSE early close dates")
            selected = [_date(year, m[2], m[3], m[1]) for m in dates if int(m[4]) == year]
            if not selected or any(int(m[4]) not in years for m in dates):
                raise ValueError("NYSE early close year mismatch")
            early.extend(selected)
            used.add(marker)
        results.append(_result(year, closed, early))
    if set(notes) != used:
        raise ValueError("unreferenced NYSE schedule footnote")
    return results


def _nasdaq(html: _VisibleHTML) -> list[ExtractedYear]:
    candidates = [
        t for t in html.tables if t and len(t[0]) == 3 and t[0][1:] == ["Holiday", "Status"]
    ]
    if len(candidates) != 1:
        raise ValueError("ambiguous Nasdaq annual table")
    header, *rows = candidates[0]
    if not re.fullmatch(r"20\d{2}", header[0]):
        raise ValueError("missing Nasdaq year")
    year = int(header[0])
    if f"U.S. Equity and Options Markets Holiday Schedule {year}" not in html.blocks:
        raise ValueError("missing Nasdaq equity annual scope")
    closed: list[date] = []
    early: list[date] = []
    names: list[str] = []
    for row in rows:
        if len(row) != 3:
            raise ValueError("invalid Nasdaq row")
        stamp, label, status = map(_norm, row)
        match = re.fullmatch(DATE + r", (20\d{2})", stamp)
        if not match or int(match[3]) != year:
            raise ValueError("invalid Nasdaq date")
        day = _date(year, match[1], match[2])
        if status == "Closed" and label in NASDAQ_NAMES:
            names.append(label)
            closed.append(day)
        elif status == "1:00 p.m." and label == "Early Close* - U.S.":
            early.append(day)
        else:
            raise ValueError("unknown Nasdaq holiday/status")
    if tuple(names) != NASDAQ_NAMES or not any(
        "Nasdaq will continue to send alerts" in b and "close early" in b for b in html.blocks
    ):
        raise ValueError("incomplete Nasdaq holiday/early-close scope")
    # The published 2026 table has two explicit early closes. For future
    # annual pages, require the explicit Thanksgiving early close as a
    # completeness check, never synthesize it or assume Christmas Eve.
    thanksgiving = closed[8]
    if not any((d - thanksgiving).days == 1 for d in early) or (year == 2026 and len(early) != 2):
        raise ValueError("incomplete Nasdaq early close rows")
    return [_result(year, closed, early)]


def extract_years(symbol: str, body: bytes) -> list[ExtractedYear]:
    html = _VisibleHTML(body)
    if symbol == "QLD":
        return _nyse(html)
    if symbol == "NVDA":
        return _nasdaq(html)
    raise ValueError("unsupported equity calendar symbol")
