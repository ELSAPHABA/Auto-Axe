"""Explicitly enabled fixed-source official polling with durable cadence."""

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import psycopg
from psycopg import Connection

from autoaxe.adapters.macro_sources import BEA_ICS, BLS_IDS
from autoaxe.adapters.official_calendar_html import (
    CENSUS_CALENDAR_URL,
    CENSUS_RETAIL_CALENDAR_URL,
    FED_CALENDAR_URL,
)
from autoaxe.adapters.official_releases import (
    BEA_URL,
    BLS_ICS,
    BOE_URL,
    BOJ_CODE,
    BOJ_URL,
    CENSUS_URL,
    ECB_URL,
    FRED_URL,
    SEC_ATOM,
    parse_release,
)
from autoaxe.application.official_macro import OfficialSourceError, collect_bls_v1
from autoaxe.domain.calendars import EventRevision
from autoaxe.infrastructure.event_store import persist_event, require_event_permission
from autoaxe.infrastructure.jobs import retry_after
from autoaxe.infrastructure.market_store import PermissionDenied, verify_connection
from autoaxe.infrastructure.official_quota import reserve_bls_v1


@dataclass(frozen=True)
class Task:
    source: str
    url: str
    media: tuple[str, ...]
    seconds: int
    key_env: str | None = None


JSON = ("application/json",)
CSV = ("text/csv", "application/vnd.sdmx.data+csv", "application/csv")
TASKS = {
    "bls_actual": Task("bls", "", JSON, 3600),
    "bls_calendar": Task("bls", BLS_ICS, ("text/calendar", "application/ics"), 21600),
    # BEA publishes its subscription file with text/plain as well as ICS media.
    # Its parser checks the VCALENDAR producer identity, not arbitrary plain text.
    "bea_calendar": Task("bea", BEA_ICS, ("text/calendar", "application/ics", "text/plain"), 21600),
    # Official public calendar pages; still require source approval and explicit opt-in.
    "census_calendar": Task("census", CENSUS_CALENDAR_URL, ("text/html",), 86400),
    "census_retail_calendar": Task("census", CENSUS_RETAIL_CALENDAR_URL, ("text/html",), 86400),
    "fed_calendar": Task("fed", FED_CALENDAR_URL, ("text/html",), 86400),
    "bea_gdp": Task("bea", BEA_URL, JSON, 21600, "AUTOAXE_BEA_API_KEY"),
    "bea_pce": Task("bea", BEA_URL, JSON, 21600, "AUTOAXE_BEA_API_KEY"),
    "census_retail": Task("census", CENSUS_URL, JSON, 21600, "AUTOAXE_CENSUS_API_KEY"),
    "fred_lower": Task("fred", FRED_URL, JSON, 21600, "AUTOAXE_FRED_API_KEY"),
    "fred_upper": Task("fred", FRED_URL, JSON, 21600, "AUTOAXE_FRED_API_KEY"),
    "ecb_dfr": Task("ecb", ECB_URL, CSV, 21600),
    "boe_rate": Task("boe", BOE_URL, CSV, 21600),
    "boj_effective": Task("boj", BOJ_URL, JSON, 86400),
    "sec_filings": Task(
        "sec_edgar", SEC_ATOM, ("application/atom+xml", "application/xml", "text/xml"), 900
    ),
}


def parameters(task_id: str, now: datetime, key: str | None) -> dict[str, str]:
    if task_id in ("bea_gdp", "bea_pce"):
        return {
            "UserID": key or "",
            "Method": "GetData",
            "DatasetName": "NIPA",
            "TableName": "T10101" if task_id == "bea_gdp" else "T20807",
            "Frequency": "Q" if task_id == "bea_gdp" else "M",
            "Year": f"{now.year - 1},{now.year}",
            "ResultFormat": "JSON",
        }
    if task_id == "census_retail":
        return {
            "get": "cell_value,category_code,data_type_code,seasonally_adj,error_data",
            "time": f"from {now.year - 1}-01 to {now.year}-{now.month:02d}",
            "category_code": "44X72",
            "data_type_code": "MPCSM",
            "seasonally_adj": "yes",
            "error_data": "no",
            "key": key or "",
        }
    if task_id.startswith("fred_"):
        return {
            "series_id": "DFEDTARL" if task_id == "fred_lower" else "DFEDTARU",
            "api_key": key or "",
            "file_type": "json",
            "sort_order": "desc",
            "limit": "30",
        }
    if task_id == "ecb_dfr":
        return {"lastNObservations": "30", "format": "csvdata"}
    if task_id == "boe_rate":
        return {
            "CSVF": "TN",
            "Datefrom": f"01/Jan/{now.year - 1}",
            "Dateto": "now",
            "SeriesCodes": "IUDBEDR",
            "UsingCodes": "Y",
            "csv.x": "yes",
            "VPD": "Y",
            "VFD": "N",
        }
    if task_id == "sec_filings":
        return {
            "action": "getcurrent",
            "type": "8-K",
            "company": "",
            "dateb": "",
            "owner": "exclude",
            "count": "100",
            "output": "atom",
        }
    if task_id == "boj_effective":
        return {
            "format": "json",
            "lang": "en",
            "db": "FM01",
            "code": BOJ_CODE,
            "startDate": (now - timedelta(days=30)).strftime("%Y%m"),
            "endDate": now.strftime("%Y%m"),
        }
    return {}


def fetch_release(
    task_id: str,
    client: httpx.Client,
    permit: Callable[[], None],
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> list[EventRevision]:
    task = TASKS[task_id]
    if client.trust_env or client.follow_redirects:
        raise ValueError("official transport must not use proxies or redirects")
    if task_id == "bls_actual":
        return collect_bls_v1(client, authorize=permit, series_ids=tuple(BLS_IDS))
    key = os.environ.get(task.key_env) if task.key_env else None
    if task.key_env and not key:
        raise PermissionDenied("registered free API credential required")
    ua = "Auto-Axe/0.1 personal educational collector"
    if task.source == "sec_edgar":
        # SEC fair access requires an identifiable contact; never log it.
        contact = os.environ.get("AUTOAXE_SEC_CONTACT", "")
        if "@" not in contact or any(c in contact for c in "\r\n") or len(contact) > 160:
            raise PermissionDenied("SEC contact required")
        ua += " " + contact
    permit()
    try:
        with client.stream(
            "GET",
            task.url,
            params=parameters(task_id, clock(), key),
            headers={
                "Accept": ", ".join(task.media),
                "User-Agent": ua,
                "Accept-Encoding": "identity",
            },
            timeout=10,
            follow_redirects=False,
        ) as response:
            if response.status_code != 200:
                raise OfficialSourceError(
                    "official provider unavailable",
                    status=response.status_code,
                    retry_header=response.headers.get("retry-after"),
                )
            if response.headers.get("content-type", "").split(";")[0].lower() not in task.media:
                raise OfficialSourceError("unexpected official response media")
            parts = bytearray()
            for part in response.iter_bytes():
                parts.extend(part)
                if len(parts) > 1_000_000:
                    raise OfficialSourceError("official response exceeds size limit")
        permit()
        return parse_release(task_id, bytes(parts), clock())
    except PermissionDenied:
        raise
    except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError, SyntaxError) as exc:
        # Exception strings may contain key-bearing URLs. Do not propagate them.
        raise OfficialSourceError("official response contract or transport failed") from exc


def _grant(conn: Connection[Any], source: str) -> int:
    version = require_event_permission(conn, source)
    circuit = conn.execute(
        "SELECT permission_version,blocked,retry_at>clock_timestamp() "
        "FROM ops.poll_circuits WHERE source_id=%s",
        (source,),
    ).fetchone()
    if circuit and circuit[0] == version and (circuit[1] or circuit[2]):
        raise PermissionDenied("official source circuit open")
    return version


def reserve(conn: Connection[Any], task_id: str) -> int | None:
    """Called inside a transaction; commit before invoking the network."""
    verify_connection(conn, write=True)
    task = TASKS[task_id]
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("source:" + task.source,))
    version = _grant(conn, task.source)
    row = conn.execute(
        """INSERT INTO ops.official_poll_slots VALUES
           (%s,%s,clock_timestamp(),clock_timestamp()+make_interval(secs=>%s),%s)
           ON CONFLICT(task_id) DO UPDATE SET last_requested_at=EXCLUDED.last_requested_at,
             next_requested_at=EXCLUDED.next_requested_at,
             permission_version=EXCLUDED.permission_version
           WHERE ops.official_poll_slots.next_requested_at<=clock_timestamp()
           RETURNING permission_version""",
        (task_id, task.source, task.seconds, version),
    ).fetchone()
    if row is None:
        return None
    if task_id == "bls_actual":
        _, _, reserved_version = reserve_bls_v1(conn)
        if reserved_version != version:
            raise PermissionDenied("BLS approval changed")
    return version


def poll_once(
    dsn: str, task_id: str, fetch: Callable[[Callable[[], None]], list[EventRevision]]
) -> str:
    task = TASKS[task_id]
    with psycopg.connect(dsn, autocommit=True, connect_timeout=3) as conn:
        verify_connection(conn, write=True)
        leader = conn.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s,0))",
            ("official:" + task.source,),
        ).fetchone()
        if not leader or not leader[0]:
            return "busy"
        try:
            with conn.transaction():
                version = reserve(conn, task_id)
        except PermissionDenied:
            return "blocked"
        if version is None:
            return "not_due"

        def permit() -> None:
            if _grant(conn, task.source) != version:
                raise PermissionDenied("official approval changed")

        try:
            rows = fetch(permit)
            if not rows or len(rows) > 2000 or any(row.source_id != task.source for row in rows):
                raise OfficialSourceError("official result scope mismatch")
            with conn.transaction():
                conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                    ("source:" + task.source,),
                )
                permit()
                for row in rows:
                    persist_event(conn, row, expected_permission_version=version)
            return "stored"
        except PermissionDenied:
            return "blocked"
        except OfficialSourceError as exc:
            with conn.transaction():
                conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                    ("source:" + task.source,),
                )
                if require_event_permission(conn, task.source) != version:
                    return "blocked"
                now = conn.execute("SELECT clock_timestamp()").fetchone()
                assert now is not None
                delay = max(task.seconds, retry_after(1, exc.retry_header, now[0]))
                blocked = exc.status in (401, 403) or delay > 604800
                conn.execute(
                    """INSERT INTO ops.poll_circuits VALUES (%s,%s,%s,%s,%s)
                       ON CONFLICT(source_id) DO UPDATE SET
                       permission_version=EXCLUDED.permission_version,blocked=EXCLUDED.blocked,
                       retry_at=EXCLUDED.retry_at,reason=EXCLUDED.reason""",
                    (
                        task.source,
                        version,
                        blocked,
                        None if blocked else now[0] + timedelta(seconds=delay),
                        "official_http_" + str(exc.status or "error"),
                    ),
                )
            return "failed"
