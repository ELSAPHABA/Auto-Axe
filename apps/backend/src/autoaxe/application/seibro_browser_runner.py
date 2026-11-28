"""Explicit private one-shot SEIBro browser launcher; no implicit source grants.

The operator controls the Docker daemon and externally enforced restricted
egress. The isolated browser receives only a bounded scope reservation over
stdin, never a DB DSN or credentials. The launcher stages a candidate only
under the same current permission version, and never reviews or promotes it.
"""

import json
import subprocess
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

import psycopg
from psycopg import Connection

from autoaxe.application.scrape_broker import source_lock
from autoaxe.application.seibro_review import (
    browser_permission,
    insert_snapshot,
    normalize_capture,
    stage_capture,
)
from autoaxe.domain.canonical import strict_json
from autoaxe.domain.types import utc_string
from autoaxe.infrastructure.market_store import PermissionDenied, verify_connection

TASK_ID = "seibro_browser"
INTERVAL_SECONDS = 86400
TIMEOUT_SECONDS = 120
MAX_OUTPUT = 131072
BATCH_TIMEOUT_SECONDS = 480
BATCH_MAX_OUTPUT = 2_097_152
DAILY_SCOPES = tuple((str(period), basis) for period in range(1, 6) for basis in ("1", "2", "4"))
COMPOSE = "infra/compose/seibro-browser.yaml"


def reserve_browser(
    conn: Connection[Any],
    *,
    country: str,
    period: str,
    basis: str,
) -> dict[str, Any] | None:
    if country not in ("ALL", "US", "HK", "CN", "JP", "VN"):
        raise ValueError("unsupported country")
    if period not in ("1", "2", "3", "4", "5") or basis not in ("1", "2", "3", "4"):
        raise ValueError("unsupported browser ranking scope")
    verify_connection(conn, write=True)
    source_lock(conn, "seibro")
    version = browser_permission(conn)
    circuit = conn.execute(
        "SELECT permission_version,blocked,retry_at>clock_timestamp() "
        "FROM ops.poll_circuits WHERE source_id='seibro'"
    ).fetchone()
    if circuit and ((circuit[0] == version and circuit[1]) or circuit[2]):
        raise PermissionDenied("SEIBro source circuit open")
    # Source-wide reservation, not one slot per rank or country. Commit before
    # launching the browser, including failures; no immediate retry.
    row = conn.execute(
        """INSERT INTO ops.official_poll_slots VALUES
           (%s,'seibro',clock_timestamp(),clock_timestamp()+make_interval(secs=>%s),%s)
           ON CONFLICT(task_id) DO UPDATE SET last_requested_at=EXCLUDED.last_requested_at,
             next_requested_at=EXCLUDED.next_requested_at,
             permission_version=EXCLUDED.permission_version
           WHERE ops.official_poll_slots.next_requested_at<=clock_timestamp()
           RETURNING last_requested_at""",
        (TASK_ID, INTERVAL_SECONDS, version),
    ).fetchone()
    if row is None:
        return None
    return {
        "country": country,
        "period": period,
        "basis": basis,
        "permission_version": version,
        "deadline": utc_string(row[0] + timedelta(seconds=TIMEOUT_SECONDS + 10)),
    }


def run_container(ticket: dict[str, Any]) -> Any:
    """Launch a prebuilt isolated image. No build/pull or provider retry."""
    name = "autoaxe-seibro-capture-" + uuid4().hex
    timeout = BATCH_TIMEOUT_SECONDS if "scopes" in ticket else TIMEOUT_SECONDS
    max_output = BATCH_MAX_OUTPUT if "scopes" in ticket else MAX_OUTPUT
    command = [
        "docker",
        "compose",
        "-f",
        COMPOSE,
        "--profile",
        "browser",
        "run",
        "--rm",
        "-T",
        "--no-deps",
        "--no-build",
        "--pull",
        "never",
        "--name",
        name,
        "seibro-browser",
    ]
    try:
        process = subprocess.run(
            command,
            input=json.dumps(ticket).encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
        if process.returncode != 0 or not 0 < len(process.stdout) <= max_output:
            raise ValueError("isolated browser failed or oversized result")
        return strict_json(process.stdout.decode("utf-8"))
    except subprocess.TimeoutExpired as exc:
        # A killed Compose CLI may leave the container. Target only this
        # randomly named one-shot instance.
        subprocess.run(
            ["docker", "rm", "-f", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        raise ValueError("isolated browser timed out") from exc


def capture_once(
    dsn: str,
    *,
    country: str,
    period: str,
    basis: str,
    launch: Callable[[dict[str, Any]], Any] = run_container,
) -> str:
    with psycopg.connect(dsn, connect_timeout=3) as conn:
        ticket = reserve_browser(conn, country=country, period=period, basis=basis)
    if ticket is None:
        return "not_due"
    # Recheck immediately before launch, using the same permission version.
    with psycopg.connect(dsn, connect_timeout=3) as conn:
        if browser_permission(conn) != ticket["permission_version"]:
            raise PermissionDenied("browser grant changed before capture")
    result = launch(ticket)
    if (
        not isinstance(result, dict)
        or result.get("capture_mode") != "browser_capture"
        or result.get("country_code") != country
        or result.get("period_code") != period
        or result.get("rank_basis") != basis
    ):
        raise ValueError("browser returned wrong capture scope")
    # Database time guards both expiry and stage receipt. The operator and
    # browser hosts must have synchronized clocks; no timestamp fabrication.
    with psycopg.connect(dsn, connect_timeout=3) as conn:
        clock = conn.execute("SELECT clock_timestamp()").fetchone()
        assert clock is not None
        deadline = datetime.fromisoformat(ticket["deadline"])
        stamp = datetime.fromisoformat(result["retrieved_at_utc"])
        if clock[0] > deadline or stamp < deadline - timedelta(seconds=TIMEOUT_SECONDS + 10):
            raise ValueError("capture outside reservation")
        identifier, digest = stage_capture(
            conn,
            result,
            expected_browser_version=ticket["permission_version"],
        )
    return f"staged {identifier} {digest}"


def daily_adapter_grant(conn: Connection[Any], version: int) -> bool:
    """Return current trading eligibility after independent parser approval."""
    if browser_permission(conn) != version:
        raise PermissionDenied("SEIBro browser grant changed")
    row = conn.execute(
        """SELECT r.allow_trading FROM ops.seibro_adapter_grants g
           JOIN catalog.source_registry r USING(source_id,permission_version)
           WHERE g.source_id='seibro' AND g.permission_version=%s
             AND g.adapter_version=1 AND g.schema_version=1
             AND g.interval_seconds=86400 AND g.verified_at<=clock_timestamp()
             AND r.verified_at<=clock_timestamp()""",
        (version,),
    ).fetchone()
    if row is None:
        raise PermissionDenied("independent SEIBro adapter verification required")
    return bool(row[0])


def reserve_daily(conn: Connection[Any]) -> dict[str, Any] | None:
    verify_connection(conn, write=True)
    source_lock(conn, "seibro")
    version = browser_permission(conn)
    daily_adapter_grant(conn, version)
    # Reuse the single browser source-wide slot to prevent overlapping captures.
    ticket = reserve_browser(conn, country="US", period="1", basis="4")
    if ticket is None:
        return None
    deadline = datetime.fromisoformat(ticket["deadline"]) + timedelta(
        seconds=BATCH_TIMEOUT_SECONDS - TIMEOUT_SECONDS
    )
    return {
        "country": "US",
        "scopes": [{"period": period, "basis": basis} for period, basis in DAILY_SCOPES],
        "permission_version": version,
        "deadline": utc_string(deadline),
    }


def normalize_daily(result: Any, ticket: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    """Require every scope exactly once with coherent displayed settlement dates."""
    if (
        not isinstance(result, dict)
        or set(result) != {"captures"}
        or not isinstance(result["captures"], list)
        or len(result["captures"]) != len(DAILY_SCOPES)
    ):
        raise ValueError("invalid daily batch envelope")
    deadline = datetime.fromisoformat(ticket["deadline"])
    reserved = deadline - timedelta(seconds=BATCH_TIMEOUT_SECONDS + 10)
    if not reserved <= now <= deadline:
        raise ValueError("daily batch outside reservation")
    captures = {}
    periods: dict[str, tuple[str, str]] = {}
    dates = set()
    for raw in result["captures"]:
        data = normalize_capture(raw)
        key = (data["period_code"], data["rank_basis"])
        stamp = datetime.fromisoformat(data["retrieved_at_utc"])
        if (
            data["capture_mode"] != "browser_capture"
            or data["country_code"] != "US"
            or key not in DAILY_SCOPES
            or key in captures
            or not reserved <= stamp <= now
        ):
            raise ValueError("invalid or repeated daily scope")
        dates.add(data["as_of_date_kst"])
        period = (data["period_start"], data["period_end"])
        if periods.setdefault(key[0], period) != period:
            raise ValueError("inconsistent settlement period within daily batch")
        captures[key] = data
    if len(dates) != 1 or set(captures) != set(DAILY_SCOPES):
        raise ValueError("incomplete or inconsistent daily batch")
    return [captures[key] for key in DAILY_SCOPES]


def promote_daily(conn: Connection[Any], ticket: dict[str, Any], result: Any) -> str:
    """All 15 captures, typed snapshots and receipts commit in one transaction."""
    verify_connection(conn, write=True)
    source_lock(conn, "seibro")
    version = ticket["permission_version"]
    trading = daily_adapter_grant(conn, version)
    deadline = datetime.fromisoformat(ticket["deadline"])
    reserved = deadline - timedelta(seconds=BATCH_TIMEOUT_SECONDS + 10)
    slot = conn.execute(
        """SELECT last_requested_at,permission_version FROM ops.official_poll_slots
           WHERE task_id=%s AND source_id='seibro'""",
        (TASK_ID,),
    ).fetchone()
    if slot != (reserved, version):
        raise PermissionDenied("daily reservation changed or missing")
    clock = conn.execute("SELECT clock_timestamp()").fetchone()
    assert clock is not None
    captures = normalize_daily(result, ticket, clock[0])
    batch_id = str(uuid4())
    # Stage all rows before a common available_at is assigned.
    staged = []
    for payload in captures:
        capture_id, _ = stage_capture(conn, payload, expected_browser_version=version)
        existing = conn.execute(
            """SELECT first_seen_at FROM ops.seibro_captures c WHERE id=%s
               AND NOT EXISTS (SELECT 1 FROM ops.seibro_promotions p WHERE p.capture_id=c.id)
               AND NOT EXISTS (
                   SELECT 1 FROM ops.seibro_validated_promotions p WHERE p.capture_id=c.id
               )
               AND NOT EXISTS (SELECT 1 FROM ops.seibro_reviews r WHERE r.capture_id=c.id)""",
            (capture_id,),
        ).fetchone()
        if existing is None:
            raise PermissionDenied("capture already used by another review or batch")
        staged.append((payload, capture_id, existing[0]))
    clock = conn.execute("SELECT clock_timestamp()").fetchone()
    assert clock is not None
    now = clock[0]
    if now > deadline:
        raise ValueError("daily batch expired during validation")
    conn.execute(
        """INSERT INTO ops.seibro_daily_batches
           (id,permission_version,reserved_at,deadline_at,available_at,as_of_date_kst,scope_count)
           VALUES (%s,%s,%s,%s,%s,%s,15)""",
        (batch_id, version, reserved, deadline, now, captures[0]["as_of_date_kst"]),
    )
    for payload, capture_id, first_seen in staged:
        _, snapshot_id = insert_snapshot(
            conn,
            payload,
            capture_id,
            version,
            first_seen,
            now,
            quality="adapter_validated",
            trading=trading,
        )
        conn.execute(
            """INSERT INTO ops.seibro_validated_promotions
               (capture_id,batch_id,period_code,rank_basis,snapshot_id) VALUES (%s,%s,%s,%s,%s)""",
            (capture_id, batch_id, payload["period_code"], payload["rank_basis"], snapshot_id),
        )
    return f"validated {batch_id} 15"


def capture_daily(
    dsn: str,
    *,
    launch: Callable[[dict[str, Any]], Any] = run_container,
) -> str:
    with psycopg.connect(dsn, connect_timeout=3) as conn:
        ticket = reserve_daily(conn)
    if ticket is None:
        return "not_due"
    with psycopg.connect(dsn, connect_timeout=3) as conn:
        daily_adapter_grant(conn, ticket["permission_version"])
        clock = conn.execute("SELECT clock_timestamp()").fetchone()
        assert clock is not None
        if clock[0] >= datetime.fromisoformat(ticket["deadline"]):
            raise ValueError("daily reservation expired before launch")
    result = launch(ticket)
    with psycopg.connect(dsn, connect_timeout=3) as conn:
        return promote_daily(conn, ticket, result)


def run_daily_loop(
    dsn: str,
    *,
    capture: Callable[[str], str] = capture_daily,
    sleep: Callable[[float], None] = time.sleep,
    report: Callable[[str], None] = print,
) -> None:
    """Recheck DB cadence every five minutes; only a committed reservation launches."""
    while True:
        try:
            status = capture(dsn)
        except (ValueError, PermissionDenied, psycopg.Error, TypeError, OSError, KeyError):
            # Do not emit provider payloads, exception strings or DSNs.
            report("SEIBro daily capture blocked or unavailable")
        else:
            if status != "not_due":
                report(status)
        sleep(300)
