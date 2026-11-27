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

from datetime import UTC, date, datetime, time

from autoaxe.domain.volume import NEW_YORK, SYMBOLS

CALENDAR_VERSION = "us_equity_regular_2024_2026_reviewed_20261127"
_HOLIDAYS = {
    2024: "01-01 01-15 02-19 03-29 05-27 06-19 07-04 09-02 11-28 12-25",
    2025: "01-01 01-09 01-20 02-17 04-18 05-26 06-19 07-04 09-01 11-27 12-25",
    2026: "01-01 01-19 02-16 04-03 05-25 06-19 07-03 09-07 11-26 12-25",
}
_EARLY = {2024: "07-03 11-29 12-24", 2025: "07-03 11-28 12-24", 2026: "11-27 12-24"}


def scheduled_close(symbol: str, day: date) -> datetime | None:
    """Return scheduled regular close UTC, not provider publication time.

    No guessing beyond reviewed years, or on unregistered assets.
    """
    if symbol not in SYMBOLS or day.year not in _HOLIDAYS:
        raise ValueError("unverified equity calendar range or symbol")
    month_day = day.strftime("%m-%d")
    if day.weekday() >= 5 or month_day in _HOLIDAYS[day.year].split():
        return None
    hour = 13 if month_day in _EARLY[day.year].split() else 16
    return datetime.combine(day, time(hour), tzinfo=NEW_YORK).astimezone(UTC)
