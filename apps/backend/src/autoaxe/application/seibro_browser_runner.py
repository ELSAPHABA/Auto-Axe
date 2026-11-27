"""Explicit private one-shot SEIBro browser launcher; no implicit source grants.

The operator controls the Docker daemon and externally enforced restricted
egress. The isolated browser receives only a bounded scope reservation over
stdin, never a DB DSN or credentials. The launcher stages a candidate only
under the same current permission version, and never reviews or promotes it.
"""

import json
import subprocess
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

import psycopg
from psycopg import Connection

from autoaxe.application.scrape_broker import source_lock
from autoaxe.application.seibro_review import browser_permission, stage_capture
from autoaxe.domain.canonical import strict_json
from autoaxe.domain.types import utc_string
from autoaxe.infrastructure.market_store import PermissionDenied, verify_connection

TASK_ID = "seibro_browser"
INTERVAL_SECONDS = 86400
TIMEOUT_SECONDS = 120
MAX_OUTPUT = 131072
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
    if circuit and circuit[0] == version and (circuit[1] or circuit[2]):
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
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
        if process.returncode != 0 or not 0 < len(process.stdout) <= MAX_OUTPUT:
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
