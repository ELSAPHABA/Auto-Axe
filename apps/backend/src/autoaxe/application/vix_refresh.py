"""Internal immediate refresh and dedicated VIX stream; TTL is never relaxed."""

from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg import Connection
from websockets.exceptions import WebSocketException

from autoaxe.adapters.vix_ws import SID, SYMBOL, stream_quotes
from autoaxe.application.collection import FetchError
from autoaxe.application.market_worker import record_health
from autoaxe.domain.catalog import catalog
from autoaxe.domain.market import Candidate, Quality
from autoaxe.infrastructure.jobs import retry_after
from autoaxe.infrastructure.market_store import PermissionDenied, gate, ingest, verify_connection

TTL_SECONDS = 10
# Reconnect budget is not freshness TTL. The normal path keeps a subscription
# active; don't create a new connection every time a workflow requests refresh.
RECONNECT_SECONDS = 60
Stream = Callable[[Callable[[], None]], AsyncGenerator[Candidate, None]]


def _clock(conn: Connection[Any]) -> datetime:
    row = conn.execute("SELECT clock_timestamp()").fetchone()
    assert row is not None
    return row[0]  # type: ignore[no-any-return]


def _version(conn: Connection[Any], evidence_ref: str) -> int:
    fetch = gate(conn, SID, "fetch")
    store = gate(conn, SID, "storage")
    if (
        fetch["source_id"] != "yfinance"
        or store["source_id"] != "yfinance"
        or fetch["permission_version"] != store["permission_version"]
        or fetch["evidence_ref"] != evidence_ref
        or store["evidence_ref"] != evidence_ref
        or fetch["mapping_version"] != catalog()[SID].mapping_version
    ):
        raise PermissionDenied("VIX permission mismatch")
    return int(fetch["permission_version"])


def _cooldown(conn: Connection[Any], version: int, now: datetime) -> bool:
    circuit = conn.execute(
        "SELECT permission_version,blocked,retry_at FROM ops.poll_circuits "
        "WHERE source_id='yfinance'"
    ).fetchone()
    return bool(
        circuit and ((circuit[0] == version and circuit[1]) or (circuit[2] and circuit[2] > now))
    )


def _latest(conn: Connection[Any], version: int, now: datetime) -> str:
    row = conn.execute(
        """SELECT o.source_event_at,o.value,o.quality,o.metadata
        FROM market.latest_observations l JOIN market.observations o
        ON o.partition_at=l.partition_at AND o.observation_id=l.observation_id
        WHERE l.series_id=%s AND o.permission_version=%s AND o.mapping_version=%s""",
        (SID, version, catalog()[SID].mapping_version),
    ).fetchone()
    if not row or row[0] is None or row[1] is None:
        return "no_data"
    age = (now - row[0]).total_seconds()
    if age > TTL_SECONDS:
        return "stale"
    if age < 0 or row[2] != "valid" or row[3].get("provenance") != "yahoo_ws_quote":
        return "unknown"
    if row[3].get("live_verified") is not True or row[3].get("session_verified") is not True:
        return "unknown"
    return "fresh"


def _lock_source(conn: Connection[Any]) -> None:
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('source:yfinance',0))")


async def refresh_vix(
    dsn: str,
    *,
    enabled: bool = False,
    evidence_ref: str = "",
    continuous_session: bool = False,
    stream: Stream | None = None,
    stopped: Callable[[], bool] = lambda: False,
) -> str:
    """Immediate internal request; share active stream and durable reconnect budget.

    No public request starts provider IO. An internal workflow may call this
    function on condition attainment. 'unknown'/'stale' never satisfies a VIX
    freshness requirement; an active stream is coalesced, not duplicated.
    """
    if not enabled or not evidence_ref.strip():
        raise PermissionDenied("explicit VIX quote opt-in and reviewed evidence required")
    if stopped():
        return "stopped"

    def default_stream(permit: Callable[[], None]) -> AsyncGenerator[Candidate, None]:
        return stream_quotes(permit, duration=900 if continuous_session else 10)

    transport = stream or default_stream
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as conn:
        verify_connection(conn, write=True)
        with conn.transaction():
            _lock_source(conn)
            version = _version(conn, evidence_ref)
            now = _clock(conn)
            latest = _latest(conn, version, now)
            if not continuous_session and latest == "fresh":
                return "fresh"
            if _cooldown(conn, version, now):
                return "cooldown:" + latest
        locked = conn.execute(
            "SELECT pg_try_advisory_lock(hashtextextended('poll:vix_ws',0))"
        ).fetchone()
        if not locked or not locked[0]:
            return "stream_active:" + latest
        with conn.transaction():
            _lock_source(conn)
            if _version(conn, evidence_ref) != version or _cooldown(conn, version, _clock(conn)):
                return "permission_or_circuit_changed"
            now = _clock(conn)
            old = conn.execute(
                "SELECT last_enqueued_at FROM ops.poll_slots WHERE series_id=%s", (SID,)
            ).fetchone()
            if old and now < old[0] + timedelta(seconds=RECONNECT_SECONDS):
                return "reconnect_limited:" + latest
            conn.execute(
                """INSERT INTO ops.poll_slots VALUES (%s,%s,%s) ON CONFLICT(series_id)
                DO UPDATE SET last_slot=EXCLUDED.last_slot,
                last_enqueued_at=EXCLUDED.last_enqueued_at""",
                (SID, int(now.timestamp()) // RECONNECT_SECONDS, now),
            )

        def permit() -> None:
            if (
                stopped()
                or _version(conn, evidence_ref) != version
                or _cooldown(conn, version, _clock(conn))
            ):
                raise PermissionDenied("VIX stream stopped or grant/circuit changed")

        try:
            async with aclosing(transport(permit)) as rows:
                async for item in rows:
                    if (
                        item.series_id != SID
                        or item.value is None
                        or item.source_event_at is None
                        or item.metadata.get("symbol") != SYMBOL
                        or item.metadata.get("provenance") != "yahoo_ws_quote"
                        or item.quality not in (Quality.UNKNOWN, Quality.STALE)
                    ):
                        raise ValueError("invalid VIX quote")
                    with conn.transaction():
                        _lock_source(conn)
                        permit()
                        ingest(conn, item)
                        record_health(
                            conn, SID, item.quality.value, "quote_live_semantics_unverified"
                        )
                    if not continuous_session:
                        break
            with conn.transaction():
                _lock_source(conn)
                permit()
                latest = _latest(conn, version, _clock(conn))
                record_health(conn, SID, "healthy" if latest == "fresh" else latest, "vix_refresh")
                return latest
        except PermissionDenied:
            return "stopped" if stopped() else "permission_changed"
        except (FetchError, OSError, WebSocketException, ValueError) as exc:
            with conn.transaction():
                _lock_source(conn)
                try:
                    permit()
                except PermissionDenied:
                    return "permission_or_circuit_changed"
                if isinstance(exc, FetchError):
                    now = _clock(conn)
                    delay = retry_after(1, exc.retry_header, now)
                    blocked = exc.status not in (429, 500, 502, 503, 504) or delay > 604800
                    until = (
                        None if blocked else now + timedelta(seconds=max(RECONNECT_SECONDS, delay))
                    )
                    reason = f"http_{exc.status}"
                elif isinstance(exc, ValueError):
                    blocked, until, reason = True, None, "invalid_vix_quote"
                else:
                    blocked, until, reason = (
                        False,
                        _clock(conn) + timedelta(seconds=RECONNECT_SECONDS),
                        "vix_transport_error",
                    )
                conn.execute(
                    """INSERT INTO ops.poll_circuits VALUES ('yfinance',%s,%s,%s,%s)
                    ON CONFLICT(source_id) DO UPDATE SET
                    permission_version=EXCLUDED.permission_version,
                    blocked=EXCLUDED.blocked,retry_at=EXCLUDED.retry_at,reason=EXCLUDED.reason""",
                    (version, blocked, until, reason),
                )
                record_health(conn, SID, "blocked" if blocked else "disconnected", reason)
                return "collection_failed"
