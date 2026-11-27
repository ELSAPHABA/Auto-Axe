"""Official data feed *offline* normalizers with retained release/receipt timestamps."""

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from xml.etree import ElementTree

from icalendar import Calendar

from autoaxe.domain.calendars import CalendarEvidence, EventRevision
from autoaxe.domain.types import decimal_string, utc_datetime

# Official subscription page links this file directly (no API key):
# https://www.bea.gov/news/schedule/icalendar
BEA_ICS = "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics"
BEA_CALENDAR_PRODID = "//BEA-Release-Calendar-Subscription//"

BLS_IDS = {
    "CUUR0000SA0": ("US_CPI", "index"),
    "CES0000000001": ("US_NONFARM_PAYROLL", "thousand"),
    "LNS14000000": ("US_UNEMPLOYMENT", "percent"),
}
RATE_KINDS = {
    "FED_TARGET_LOWER": ("fed", "percent"),
    "FED_TARGET_UPPER": ("fed", "percent"),
    "BOJ_POLICY_TARGET": ("boj", "percent"),
    "BOE_BANK_RATE": ("boe", "percent"),
    "ECB_DFR": ("ecb", "percent"),
}


def _decimal(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return decimal_string(str(Decimal(str(value).replace(",", ""))))
    except (ValueError, InvalidOperation) as exc:
        raise ValueError("invalid official release numeric value") from exc


def parse_bls_actual(data: dict[str, Any], received: datetime) -> list[EventRevision]:
    """Never fabricate forecast or publish time from BLS year/month observation."""
    utc_datetime(received)
    output = []
    if data.get("status") != "REQUEST_SUCCEEDED":
        raise ValueError("BLS status not successful")
    series = data.get("Results", {}).get("series", [])
    if not isinstance(series, list) or len(series) > 30:
        raise ValueError("invalid BLS series")
    for group in series:
        sid = group["seriesID"]
        if sid not in BLS_IDS:
            raise ValueError("unregistered BLS series")
        metric, unit = BLS_IDS[sid]
        for row in group.get("data", []):
            period, year = str(row["period"]), int(row["year"])
            if not period.startswith("M") or len(period) != 3 or not 1 <= int(period[1:]) <= 12:
                raise ValueError("BLS monthly observation expected")
            key = f"{metric}:{year}-{period[1:]}"
            output.append(
                EventRevision(
                    key,
                    "bls",
                    None,
                    None,
                    received,
                    received,
                    # BLS explicitly uses "-" for unpublished observations
                    # (including the 2025 lapse in appropriations).
                    # https://www.bls.gov/bls/bls-handling-of-missing-data.htm
                    None if row.get("value") == "-" else _decimal(row.get("value")),
                    None,
                    None,
                    unit,
                    1,
                    "https://www.bls.gov/developers/",
                )
            )
    return output


def parse_official_ics(raw: bytes, received: datetime, source: str) -> list[EventRevision]:
    if source not in ("bls", "bea", "fed") or len(raw) > 1_000_000:
        raise ValueError("unregistered/oversize calendar")
    utc_datetime(received)
    calendar = Calendar.from_ical(raw)
    if source == "bea" and (
        str(calendar.get("PRODID", "")) != BEA_CALENDAR_PRODID
        or str(calendar.get("VERSION", "")) != "2.0"
    ):
        raise ValueError("unexpected BEA subscription calendar identity")
    results: list[EventRevision] = []
    for event in calendar.walk("VEVENT"):
        uid = str(event.get("UID", ""))
        if not uid or len(uid) > 256:
            raise ValueError("calendar UID missing")
        dtstart = event.decoded("DTSTART")
        date_only = None
        if isinstance(dtstart, date) and not isinstance(dtstart, datetime):
            scheduled = None  # Date-only event is not a midnight release time.
            date_only = dtstart
        elif isinstance(dtstart, datetime):
            scheduled = utc_datetime(dtstart)
        else:
            raise ValueError("unexpected calendar DTSTART")
        title: str | None = str(event.get("SUMMARY", ""))
        if not title or len(title) > 512 or not title.isprintable():
            title = None
        status_raw = str(event.get("STATUS", "")).upper()
        status: Literal["confirmed", "unspecified", "tentative", "cancelled", "unsupported"]
        if status_raw == "CANCELLED" or str(calendar.get("METHOD", "")).upper() == "CANCEL":
            status = "cancelled"
        elif any(key in event for key in ("RRULE", "RDATE", "EXDATE", "RECURRENCE-ID")):
            status = "unsupported"
        elif status_raw == "CONFIRMED":
            status = "confirmed"
        elif status_raw == "TENTATIVE":
            status = "tentative"
        elif not status_raw:
            status = "unspecified"
        else:
            status = "unsupported"
        results.append(
            EventRevision(
                uid,
                source,
                scheduled,
                None,
                received,
                received,
                None,
                None,
                None,
                "event",
                1,
                {
                    "bls": "https://www.bls.gov/schedule/",
                    "bea": BEA_ICS,
                    "fed": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                }[source],
                CalendarEvidence(title, date_only, status),
            )
        )
    if not results or len(results) > 2000:
        raise ValueError("calendar empty/oversize")
    return results


def parse_sec_atom(raw: bytes, received: datetime) -> list[dict[str, Any]]:
    """Identify filing references only. Numeric 8-K guidance always needs human review."""
    utc_datetime(received)
    if len(raw) > 1_000_000 or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("unsafe SEC XML")
    root = ElementTree.fromstring(raw)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    output = []
    for entry in root.findall("a:entry", ns):
        link = entry.find("a:link", ns)
        href = link.get("href", "") if link is not None else ""
        if not href.startswith("https://www.sec.gov/"):
            raise ValueError("untrusted SEC link")
        output.append(
            {
                "source_id": "sec_edgar",
                "entry_id": (entry.findtext("a:id", default="", namespaces=ns))[:256],
                "title": (entry.findtext("a:title", default="", namespaces=ns))[:512],
                "filing_url": href,
                "first_seen_at": received,
                "guidance_status": "manual_review_required",
            }
        )
    return output


def normalize_rate_decision(data: dict[str, Any], received: datetime) -> dict[str, Any]:
    """Requires typed, pre-verified source row; never NLP-guesses numeric rates."""
    utc_datetime(received)
    kind = data["rate_kind"]
    source, unit = RATE_KINDS[kind]
    stamp = datetime.fromisoformat(data["published_at"])
    utc_datetime(stamp)
    if stamp > received or data.get("source_id") != source:
        raise ValueError("rate source/timestamp mismatch")
    return {
        "indicator_id": kind,
        "source_id": source,
        "rate": _decimal(data["value"]),
        "unit": unit,
        "published_at": stamp,
        "first_seen_at": received,
        "quality": "manual_review_required",
        "source_url": data["source_url"],
        "effective_at": data.get("effective_at"),
    }


def normalize_mexc_snapshot(
    detail: dict[str, Any], ticker: dict[str, Any], received: datetime
) -> dict[str, Any]:
    """NAS100_USDT candidate only. WS Protobuf contract remains explicitly disabled."""
    utc_datetime(received)
    contract = detail.get("data", {})
    row = ticker.get("data", {})
    if (
        contract.get("symbol") != "NAS100_USDT"
        or row.get("symbol") != "NAS100_USDT"
        or contract.get("state") != 0
    ):
        raise ValueError("MEXC contract unavailable or different instrument")
    stamp = row.get("timestamp")
    event_at = datetime.fromtimestamp(int(stamp) / 1000, tz=UTC) if stamp else None
    if event_at and event_at > received:
        raise ValueError("future MEXC timestamp")
    return {
        "series_id": "NASDAQ100_MEXC_PERP_USDT",
        "value": _decimal(row.get("lastPrice")),
        "quote_currency": "USDT",
        "instrument_type": "index_linked_perpetual",
        "source_event_at": event_at,
        "received_at": received,
        "quality": "unverified",
        "provenance": "mexc_futures_rest_candidate",
    }
