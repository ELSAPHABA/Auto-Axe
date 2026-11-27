"""Fixed official feeds; never infer publication time from an observation period."""

import csv
import io
import json
import re
from datetime import date, datetime
from typing import Any

from autoaxe.adapters.macro_sources import parse_official_ics, parse_sec_atom
from autoaxe.adapters.official_calendar_html import (
    parse_census_calendar,
    parse_census_retail_calendar,
    parse_fed_calendar,
)
from autoaxe.domain.calendars import EventRevision
from autoaxe.domain.types import decimal_string

BEA_URL = "https://apps.bea.gov/api/data"
CENSUS_URL = "https://api.census.gov/data/timeseries/eits/marts"
FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
ECB_URL = "https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.DFR.LEV"
ECB_KEY = "FM.D.U2.EUR.4F.KR.DFR.LEV"
BOE_URL = "https://www.bankofengland.co.uk/boeapps/database/fromshowcolumns.asp"
BOJ_URL = "https://www.stat-search.boj.or.jp/api/v1/getDataCode"
BOJ_CODE = "STRDCLUCON"
BLS_ICS = "https://www.bls.gov/schedule/news_release/bls.ics"
SEC_ATOM = "https://www.sec.gov/cgi-bin/browse-edgar"


def event(
    source: str, key: str, value: object, unit: str, now: datetime, url: str
) -> EventRevision:
    numeric = None if value is None else decimal_string(str(value).replace(",", ""))
    return EventRevision(key, source, None, None, now, now, numeric, None, None, unit, 1, url)


def period(value: str, pattern: str, now: datetime) -> str:
    if not re.fullmatch(pattern, value) or int(value[:4]) > now.year:
        raise ValueError("invalid observation period")
    return value


def parse_bea(raw: bytes, now: datetime, *, table: str) -> list[EventRevision]:
    contracts = {
        "T10101": ("US_GDP", r"\d{4}Q[1-4]", "percent_annual_rate", "Gross domestic product"),
        "T20807": (
            "US_PCE",
            r"\d{4}M(?:0[1-9]|1[0-2])",
            "percent_mom",
            "Personal consumption expenditures",
        ),
    }
    metric, pattern, unit, description = contracts[table]
    data = json.loads(raw)["BEAAPI"]["Results"]["Data"]
    rows = []
    for row in data:
        if str(row["LineNumber"]) != "1":
            continue
        if row["TableName"] != table or row["LineDescription"].strip() != description:
            raise ValueError("BEA series identity mismatch")
        stamp = period(row["TimePeriod"], pattern, now)
        rows.append(
            event(
                "bea",
                f"{metric}:{stamp}",
                row["DataValue"],
                unit,
                now,
                "https://www.bea.gov/resources/for-developers",
            )
        )
    return rows


def parse_census(raw: bytes, now: datetime) -> list[EventRevision]:
    data = json.loads(raw)
    fields = data[0]
    required = {
        "cell_value",
        "category_code",
        "data_type_code",
        "seasonally_adj",
        "time",
        "error_data",
    }
    if (
        not isinstance(fields, list)
        or not required <= set(fields)
        or len(set(fields)) != len(fields)
    ):
        raise ValueError("Census fields missing")
    rows = []
    for values in data[1:]:
        row = dict(zip(fields, values, strict=True))
        if (
            row["category_code"],
            row["data_type_code"],
            row["seasonally_adj"],
            row["error_data"],
        ) != ("44X72", "MPCSM", "yes", "no"):
            raise ValueError("Census series identity mismatch")
        stamp = period(row["time"], r"\d{4}-(?:0[1-9]|1[0-2])", now)
        rows.append(
            event(
                "census",
                f"US_RETAIL_SALES:{stamp}",
                row["cell_value"],
                "percent_mom_sa",
                now,
                "https://www.census.gov/retail/index.html",
            )
        )
    return rows


def parse_fred(raw: bytes, now: datetime, *, series: str) -> list[EventRevision]:
    metric = {"DFEDTARL": "FED_TARGET_LOWER", "DFEDTARU": "FED_TARGET_UPPER"}[series]
    rows = []
    for row in json.loads(raw)["observations"]:
        stamp = date.fromisoformat(row["date"])
        if stamp > now.date():
            raise ValueError("future FRED observation")
        if row["value"] != ".":
            rows.append(
                event(
                    "fred",
                    f"{metric}:{stamp.isoformat()}",
                    row["value"],
                    "percent",
                    now,
                    f"https://fred.stlouisfed.org/series/{series}",
                )
            )
    return rows


def parse_ecb(raw: bytes, now: datetime) -> list[EventRevision]:
    rows = []
    for row in csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))):
        if row.get("KEY") != ECB_KEY:
            raise ValueError("ECB series identity mismatch")
        stamp = date.fromisoformat(row["TIME_PERIOD"])
        if stamp > now.date():
            raise ValueError("future ECB observation")
        rows.append(
            event(
                "ecb",
                f"ECB_DFR:{stamp.isoformat()}",
                row["OBS_VALUE"],
                "percent",
                now,
                "https://data.ecb.europa.eu/data/datasets/FM/FM.D.U2.EUR.4F.KR.DFR.LEV",
            )
        )
    return rows


def parse_boe(raw: bytes, now: datetime) -> list[EventRevision]:
    rows = []
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if not reader.fieldnames or not {"DATE", "IUDBEDR"} <= set(reader.fieldnames):
        raise ValueError("BoE CSV identity mismatch")
    for row in reader:
        raw_date = row["DATE"]
        try:
            stamp = date.fromisoformat(raw_date)
        except ValueError:
            stamp = datetime.strptime(raw_date, "%d %b %Y").date()
        if stamp > now.date():
            raise ValueError("future BoE observation")
        rows.append(
            event(
                "boe",
                f"BOE_BANK_RATE:{stamp.isoformat()}",
                row["IUDBEDR"],
                "percent",
                now,
                "https://www.bankofengland.co.uk/boeapps/database/Bank-Rate.asp",
            )
        )
    return rows


def parse_sec_refs(raw: bytes, now: datetime) -> list[EventRevision]:
    # Only filing reference detection; do not present an inferred EPS/revenue.
    return [
        event(
            "sec_edgar",
            "8K:" + row["entry_id"][:220],
            None,
            "filing_reference",
            now,
            row["filing_url"],
        )
        for row in parse_sec_atom(raw, now)
        if row["entry_id"]
    ]


def parse_boj_effective(raw: bytes, now: datetime) -> list[EventRevision]:
    """Official daily realized call rate, explicitly NOT the policy target."""
    payload = json.loads(raw)
    if payload["STATUS"] != 200 or payload["NEXTPOSITION"] is not None:
        raise ValueError("BOJ failed or incomplete response")
    if payload["PARAMETER"]["DB"] != "FM01" or len(payload["RESULTSET"]) != 1:
        raise ValueError("BOJ database mismatch")
    row = payload["RESULTSET"][0]
    if (
        row["SERIES_CODE"] != BOJ_CODE
        or row["UNIT"].lower() != "percent per annum"
        or row["FREQUENCY"] != "DAILY"
    ):
        raise ValueError("BOJ series identity mismatch")
    dates, values = row["VALUES"]["SURVEY_DATES"], row["VALUES"]["VALUES"]
    if not isinstance(dates, list) or not isinstance(values, list) or len(dates) > 100:
        raise ValueError("unexpected BOJ daily observation shape")
    events = []
    for stamp, value in zip(dates, values, strict=True):
        parsed = datetime.strptime(str(stamp), "%Y%m%d").date()
        if parsed > now.date():
            raise ValueError("future BOJ observation")
        if value is None or value == "NA":
            continue
        events.append(
            event(
                "boj",
                f"BOJ_EFFECTIVE_CALL_RATE:{parsed.isoformat()}",
                value,
                "percent_per_annum",
                now,
                "https://www.stat-search.boj.or.jp/ssi/mtshtml/fm01_d_1_en.html",
            )
        )
    return events


def parse_release(task: str, raw: bytes, now: datetime) -> list[EventRevision]:
    parsers: dict[str, Any] = {
        "bls_calendar": lambda: parse_official_ics(raw, now, "bls"),
        "bea_calendar": lambda: parse_official_ics(raw, now, "bea"),
        "census_calendar": lambda: parse_census_calendar(raw, now),
        "census_retail_calendar": lambda: parse_census_retail_calendar(raw, now),
        "fed_calendar": lambda: parse_fed_calendar(raw, now),
        "bea_gdp": lambda: parse_bea(raw, now, table="T10101"),
        "bea_pce": lambda: parse_bea(raw, now, table="T20807"),
        "census_retail": lambda: parse_census(raw, now),
        "fred_lower": lambda: parse_fred(raw, now, series="DFEDTARL"),
        "fred_upper": lambda: parse_fred(raw, now, series="DFEDTARU"),
        "ecb_dfr": lambda: parse_ecb(raw, now),
        "boe_rate": lambda: parse_boe(raw, now),
        "boj_effective": lambda: parse_boj_effective(raw, now),
        "sec_filings": lambda: parse_sec_refs(raw, now),
    }
    rows: list[EventRevision] = parsers[task]()
    if not rows or len(rows) > 2000 or len({row.event_key for row in rows}) != len(rows):
        raise ValueError("empty, duplicate, or oversized official release")
    return rows
