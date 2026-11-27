"""Per-instrument bounded primary/fallback lifecycle with durable permissions.

No automatic fallback for a quiet socket, policy/permission denial, rate
limit, bad schema or clock error. Close fallback before probing primary again.
"""

import asyncio
import math
from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg import Connection

from autoaxe.adapters.oil_ws import (
    OIL,
    SESSION_SECONDS,
    StreamFailure,
    binance_quotes,
    yahoo_quotes,
)
from autoaxe.application.collection import FetchError, SourceUnavailable
from autoaxe.application.market_worker import record_health
from autoaxe.domain.market import Candidate, Quality
from autoaxe.infrastructure.jobs import retry_after
from autoaxe.infrastructure.market_store import PermissionDenied, gate, ingest, verify_connection

Stream = Callable[[str, Callable[[], None]], AsyncGenerator[Candidate, None]]
RETRY_SECONDS = 60


class Stopped(Exception):
    pass


def _clock(conn: Connection[Any]) -> datetime:
    row = conn.execute("SELECT clock_timestamp()").fetchone()
    assert row is not None
    return row[0]  # type: ignore[no-any-return]


def _lock(conn: Connection[Any], source: str) -> None:
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("source:" + source,))


def _approval(conn: Connection[Any], sid: str, source: str, evidence: str | None = None) -> int:
    rows = [gate(conn, sid, action) for action in ("fetch", "storage")]
    if (
        any(
            row["source_id"] != source
            or row["mapping_version"] != 1
            or (evidence is not None and row["evidence_ref"] != evidence)
            for row in rows
        )
        or rows[0]["permission_version"] != rows[1]["permission_version"]
    ):
        raise PermissionDenied("oil source grant or mapping mismatch")
    return int(rows[0]["permission_version"])


def _circuit(conn: Connection[Any], source: str, version: int) -> bool:
    row = conn.execute(
        "SELECT permission_version,blocked,retry_at FROM ops.poll_circuits WHERE source_id=%s",
        (source,),
    ).fetchone()
    return bool(row and ((row[0] == version and row[1]) or (row[2] and row[2] > _clock(conn))))


def _permit(
    conn: Connection[Any], sid: str, source: str, version: int, evidence: str | None = None
) -> None:
    if _approval(conn, sid, source, evidence) != version or _circuit(conn, source, version):
        raise PermissionDenied("oil permission changed or circuit open")


def _reserve(
    conn: Connection[Any],
    sid: str,
    source: str,
    evidence: str | None = None,
) -> int | str:
    with conn.transaction():
        _lock(conn, source)
        try:
            version = _approval(conn, sid, source, evidence)
        except PermissionDenied:
            record_health(conn, sid, "blocked", "source_permission_required")
            return "permission_required"
        if _circuit(conn, source, version):
            return "cooldown"
        now = _clock(conn)
        old = conn.execute(
            "SELECT last_enqueued_at FROM ops.poll_slots WHERE series_id=%s", (sid,)
        ).fetchone()
        if old and now < old[0] + timedelta(seconds=RETRY_SECONDS):
            return "not_due"
        conn.execute(
            """INSERT INTO ops.poll_slots VALUES (%s,%s,%s)
            ON CONFLICT(series_id) DO UPDATE SET last_slot=EXCLUDED.last_slot,
            last_enqueued_at=EXCLUDED.last_enqueued_at""",
            (sid, int(now.timestamp()) // RETRY_SECONDS, now),
        )
        return version


def _http_failure(
    conn: Connection[Any],
    sid: str,
    source: str,
    version: int,
    exc: FetchError,
    evidence: str | None,
) -> None:
    with conn.transaction():
        _lock(conn, source)
        if _approval(conn, sid, source, evidence) != version:
            raise PermissionDenied("oil permission changed")
        if _circuit(conn, source, version):
            return
        now = _clock(conn)
        delay = retry_after(1, exc.retry_header, now)
        invalid = False
        if exc.retry_header is not None:
            try:
                invalid = not math.isfinite(float(exc.retry_header))
            except ValueError:
                pass
        blocked = exc.status not in (429, 500, 502, 503, 504) or invalid or delay > 604800
        if exc.status == 418:
            delay = max(delay, 259200)
        until = (
            now + timedelta(seconds=max(RETRY_SECONDS, delay))
            if not blocked or (exc.status == 418 and not invalid and delay <= 604800)
            else None
        )
        conn.execute(
            """INSERT INTO ops.poll_circuits VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT(source_id) DO UPDATE SET permission_version=EXCLUDED.permission_version,
            blocked=EXCLUDED.blocked,retry_at=EXCLUDED.retry_at,reason=EXCLUDED.reason""",
            (source, version, blocked, until, f"http_{exc.status}"),
        )
        record_health(conn, sid, "blocked" if blocked else "disconnected", f"http_{exc.status}")


def _validate(oil: str, item: Candidate, *, fallback: bool) -> None:
    primary_symbol, primary_sid, yahoo_symbol, yahoo_sid = OIL[oil]
    if (
        item.mapping_version != 1
        or item.value is None
        or item.source_event_at is None
        or item.series_id != (yahoo_sid if fallback else primary_sid)
        or item.metadata.get("symbol") != (yahoo_symbol if fallback else primary_symbol)
        or item.metadata.get("quote_currency") != ("USD" if fallback else "USDT")
        or item.metadata.get("provenance")
        != ("yahoo_oil_ws_fallback" if fallback else "binance_oil_ws_snapshot")
        or item.quality != (Quality.UNKNOWN if fallback else Quality.VALID)
        or (
            fallback
            and (
                item.metadata.get("session_verified") is not False
                or item.metadata.get("live_verified") is not False
                or item.metadata.get("contract_month_verified") is not False
                or item.metadata.get("fallback_only") is not True
            )
        )
    ):
        raise ValueError("oil candidate mapping/quality mismatch")


def _select(conn: Connection[Any], oil: str, sid: str | None, reason: str) -> None:
    """Append only actual selection transitions, not every tick."""
    indicator = OIL[oil][1].removesuffix("_SNAPSHOT")
    previous = conn.execute(
        "SELECT series_id,reason FROM market.source_selections WHERE indicator_id=%s "
        "ORDER BY selection_id DESC LIMIT 1",
        (indicator,),
    ).fetchone()
    if previous != (sid, reason):
        conn.execute(
            "INSERT INTO market.source_selections(indicator_id,series_id,reason) VALUES (%s,%s,%s)",
            (indicator, sid, reason),
        )


async def _consume(
    conn: Connection[Any],
    oil: str,
    sid: str,
    source: str,
    version: int,
    stream: Stream,
    *,
    stopped: Callable[[], bool],
    fallback: bool = False,
    evidence: str | None = None,
    primary_permit: Callable[[], None] = lambda: None,
) -> str:
    def permit() -> None:
        if stopped():
            raise Stopped
        primary_permit()
        _permit(conn, sid, source, version, evidence)

    seen = 0
    permit()
    async with aclosing(stream(oil, permit)) as rows:
        async for item in rows:
            _validate(oil, item, fallback=fallback)
            with conn.transaction():
                # Lock order always Binance before Yahoo; revocation fence on both.
                if fallback:
                    _lock(conn, "binance_futures")
                _lock(conn, source)
                permit()
                ingest(conn, item)
                record_health(
                    conn,
                    sid,
                    "unknown" if fallback else "healthy",
                    "oil_fallback_unverified" if fallback else "oil_ws_snapshot",
                )
                _select(conn, oil, sid, "fallback_received" if fallback else "primary_received")
            seen += 1
    if not seen:
        with conn.transaction():
            _lock(conn, source)
            permit()
            record_health(conn, sid, "unknown", "quiet_bounded_session")
            _select(conn, oil, None, "quiet_bounded_session")
    return "fallback_received" if fallback and seen else "primary_received" if seen else "quiet"


async def run_oil(
    conn: Connection[Any],
    oil: str,
    *,
    primary: Stream = binance_quotes,
    fallback: Stream | None = None,
    yahoo_evidence: str | None = None,
    stopped: Callable[[], bool] = lambda: False,
) -> str:
    """Caller holds exclusive Binance stream leader; no overlapping feeds per oil."""
    _, sid, _, fallback_sid = OIL[oil]
    if stopped():
        return "stopped"
    version = _reserve(conn, sid, "binance_futures")
    if isinstance(version, str):
        _select(conn, oil, None, "primary_" + version)
        return version
    try:
        # Inactive fallback health must not present old quote as current.
        record_health(conn, fallback_sid, "unknown", "primary_probe")
        _select(conn, oil, None, "primary_probe")
        return await _consume(conn, oil, sid, "binance_futures", version, primary, stopped=stopped)
    except Stopped:
        _select(conn, oil, None, "stopped")
        return "stopped"
    except PermissionDenied:
        record_health(conn, sid, "blocked", "primary_permission_changed")
        _select(conn, oil, None, "primary_permission_changed")
        return "permission_changed"
    except FetchError as exc:
        _http_failure(conn, sid, "binance_futures", version, exc, None)
        _select(conn, oil, None, "primary_http_error")
        # Provider-wide HTTP denial/rate/maintenance cannot be a per-symbol
        # outage determination. Never initiate fallback merely from a circuit.
        return "http_error"
    except (ValueError, SourceUnavailable):
        record_health(conn, sid, "schema_error", "primary_invalid_response")
        _select(conn, oil, None, "primary_invalid_response")
        return "primary_invalid"
    except StreamFailure:
        # The generator is fully closed by _consume before fallback opens.
        record_health(conn, sid, "disconnected", "primary_transport_failure")
        _select(conn, oil, None, "primary_transport_failure")
    if fallback is None or not yahoo_evidence:
        record_health(conn, fallback_sid, "blocked", "fallback_provider_approval_required")
        return "fallback_unavailable"

    def primary_permit() -> None:
        _permit(conn, sid, "binance_futures", version)

    try:
        primary_permit()
        yversion = _reserve(conn, fallback_sid, "yfinance", yahoo_evidence)
    except PermissionDenied:
        record_health(conn, fallback_sid, "blocked", "fallback_permission_changed")
        return "permission_changed"
    if isinstance(yversion, str):
        return "fallback_" + yversion
    try:
        return await _consume(
            conn,
            oil,
            fallback_sid,
            "yfinance",
            yversion,
            fallback,
            stopped=stopped,
            fallback=True,
            evidence=yahoo_evidence,
            primary_permit=primary_permit,
        )
    except Stopped:
        _select(conn, oil, None, "stopped")
        return "stopped"
    except PermissionDenied:
        record_health(conn, fallback_sid, "blocked", "fallback_permission_changed")
        _select(conn, oil, None, "fallback_permission_changed")
        return "permission_changed"
    except FetchError as exc:
        _http_failure(conn, fallback_sid, "yfinance", yversion, exc, yahoo_evidence)
        _select(conn, oil, None, "fallback_http_error")
        return "fallback_http_error"
    except (ValueError, SourceUnavailable):
        record_health(conn, fallback_sid, "schema_error", "fallback_invalid_response")
        _select(conn, oil, None, "fallback_invalid_response")
        return "fallback_invalid"
    except StreamFailure:
        record_health(conn, fallback_sid, "disconnected", "fallback_transport_failure")
        _select(conn, oil, None, "fallback_transport_failure")
        return "fallback_disconnected"


async def run_cycle(
    dsn: str,
    *,
    enabled: bool = False,
    primary: Stream = binance_quotes,
    yahoo_evidence: str | None = None,
    stopped: Callable[[], bool] = lambda: False,
) -> dict[str, str]:
    if not enabled:
        raise PermissionDenied("Binance oil opt-in required")
    if yahoo_evidence is not None and (not yahoo_evidence.strip() or len(yahoo_evidence) > 512):
        raise ValueError("invalid reviewed Yahoo provider evidence reference")
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as conn:
        verify_connection(conn, write=True)
        # A legacy/all-symbol worker takes the exclusive global lock. A
        # metal-only worker can share it, with disjoint per-symbol locks.
        lock = conn.execute(
            "SELECT pg_try_advisory_lock_shared(hashtextextended('stream:binance_futures',0))"
        ).fetchone()
        if not lock or not lock[0]:
            return {oil: "busy" for oil in OIL}
        for symbol in sorted(row[0] for row in OIL.values()):
            lock = conn.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s,0))",
                ("stream:binance_futures:" + symbol,),
            ).fetchone()
            if not lock or not lock[0]:
                return {oil: "busy" for oil in OIL}

        def yahoo(oil: str, permit: Callable[[], None]) -> AsyncGenerator[Candidate, None]:
            return yahoo_quotes(oil, permit, authorized=True, seconds=SESSION_SECONDS)

        # DB calls contain no await inside transactions; independent sockets
        # share only the serialized synchronous connection and source circuit.
        tasks = [
            asyncio.create_task(
                run_oil(
                    conn,
                    oil,
                    primary=primary,
                    fallback=yahoo if yahoo_evidence else None,
                    yahoo_evidence=yahoo_evidence,
                    stopped=stopped,
                )
            )
            for oil in OIL
        ]
        try:
            result = await asyncio.gather(*tasks)
            return dict(zip(OIL, result, strict=True))
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
