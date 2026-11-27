"""Authenticated committed market snapshot and bounded SSE invalidations.

The durable per-series version is written with the ledger/outbox transaction.
The reader never needs relay or write permission; no global event cursor is
assumed. SSE is an invalidation channel, not a replacement for the ledger.
"""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from threading import BoundedSemaphore
from typing import Annotated

import psycopg
from fastapi import APIRouter, Cookie, HTTPException, Request
from fastapi.responses import StreamingResponse
from psycopg.rows import dict_row
from starlette.concurrency import run_in_threadpool

from autoaxe.adapters.contracts import Contract, Identifier, UtcTime
from autoaxe.domain.catalog import catalog
from autoaxe.domain.owner_access import is_configured_owner
from autoaxe.entrypoints.auth import SESSION_COOKIE
from autoaxe.entrypoints.auth import _dsn as identity_dsn
from autoaxe.infrastructure.market_store import PermissionDenied, verify_connection
from autoaxe.infrastructure.sessions import authorize

router = APIRouter(prefix="/api/v1/dashboard/authorized", tags=["dashboard-authorized"])
_connections = BoundedSemaphore(8)
POLL_SECONDS = 2
MAX_POLLS = 450


class SnapshotPoint(Contract):
    series_id: Identifier
    source_id: Identifier
    unit: str
    version: int
    value: str | None
    quality: str
    source_event_at: UtcTime | None
    received_at: UtcTime | None
    collector_status: str | None
    collector_checked_at: UtcTime | None


class SnapshotMeta(Contract):
    request_id: Identifier
    as_of: UtcTime
    schema_version: int = 1
    mode: str = "market_read"
    versions: dict[str, int]


class AuthorizedSnapshot(Contract):
    data: list[SnapshotPoint]
    meta: SnapshotMeta


@dataclass(frozen=True)
class SnapshotState:
    snapshot: AuthorizedSnapshot
    authority: tuple[str, int, bool]
    permissions: dict[str, int]


def read_snapshot(sid: str | None, request_id: str, *, touch: bool) -> SnapshotState:
    dsn = os.environ.get("AUTOAXE_MARKET_READ_DSN")
    if not dsn:
        raise HTTPException(503, "read-only market authority not configured")
    try:
        with psycopg.connect(identity_dsn(), connect_timeout=3) as app:
            grant = authorize(app, sid, required_scope="indicators:read", touch=touch)
        private = is_configured_owner(grant.subject_ref)
        entries = catalog()
        with psycopg.connect(dsn, connect_timeout=3) as market:
            market.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            market.execute("SET LOCAL statement_timeout = '3s'")
            verify_connection(market, write=False)
            clock = market.execute("SELECT transaction_timestamp()").fetchone()
            assert clock is not None
            as_of = clock[0]
            with market.cursor(row_factory=dict_row) as cur:
                rows = cur.execute(
                    """SELECT s.series_id,s.source_id,s.mapping_version,s.unit,
                       r.permission_version,COALESCE(v.version,0) AS version,
                       o.value,o.quality,o.source_event_at,o.received_at,
                       h.status,h.checked_at
                       FROM catalog.series s JOIN catalog.source_registry r USING(source_id)
                       LEFT JOIN market.series_versions v USING(series_id)
                       LEFT JOIN market.latest_observations l USING(series_id)
                       LEFT JOIN market.observations o ON o.partition_at=l.partition_at
                         AND o.observation_id=l.observation_id
                         AND o.mapping_version=s.mapping_version
                         AND o.available_at<=%s AND o.ingested_at<=%s
                       LEFT JOIN ops.collector_health h ON h.series_id=s.series_id
                       WHERE r.permission_status='approved' AND r.enabled AND r.free_only
                         AND r.allow_fetch AND r.allow_storage
                         AND (r.allow_redistribution OR %s::boolean)
                         AND r.verified_at IS NOT NULL AND r.evidence_ref <> ''
                         AND s.source_id <> 'fixture'
                       ORDER BY s.series_id""",
                    (as_of, as_of, private),
                ).fetchall()
        points: list[SnapshotPoint] = []
        permissions: dict[str, int] = {}
        for row in rows:
            series_id = row["series_id"]
            series = entries.get(series_id)
            if (
                series is None
                or series.source_id != row["source_id"]
                or series.mapping_version != row["mapping_version"]
            ):
                continue
            quality = row["quality"] or "no_data"
            stamp = row["source_event_at"]
            if quality == "valid" and series.ttl is not None:
                if stamp is None or (as_of - stamp).total_seconds() > series.ttl:
                    quality = "stale"
            points.append(
                SnapshotPoint(
                    series_id=series_id,
                    source_id=series.source_id,
                    unit=series.unit,
                    version=row["version"],
                    value=str(row["value"]) if row["value"] is not None else None,
                    quality=quality,
                    source_event_at=stamp,
                    received_at=row["received_at"],
                    collector_status=row["status"],
                    collector_checked_at=row["checked_at"],
                )
            )
            permissions[series_id] = row["permission_version"]
        return SnapshotState(
            AuthorizedSnapshot(
                data=points,
                meta=SnapshotMeta(
                    request_id=request_id,
                    as_of=as_of,
                    versions={p.series_id: p.version for p in points},
                ),
            ),
            (grant.session_hash, grant.auth_version, private),
            permissions,
        )
    except (PermissionError, UnicodeError) as exc:
        raise HTTPException(401, "session invalid or insufficient scope") from exc
    except PermissionDenied as exc:
        raise HTTPException(403, "market authority denied") from exc
    except psycopg.Error as exc:
        raise HTTPException(503, "market authority unavailable") from exc


def sse_event(name: str, data: dict[str, object]) -> str:
    return f"event: {name}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


def changes(old: SnapshotState, new: SnapshotState) -> list[str]:
    if old.authority != new.authority or old.permissions != new.permissions:
        return [sse_event("resync", {"reason": "authorization_changed"})]
    if old.snapshot.data == new.snapshot.data:
        return []
    # A coalesced invalidation deliberately does not pretend to be an ordered
    # replay: the next REST read obtains the latest committed version vector.
    return [sse_event("market.invalidate", {"schema_version": 1, "mode": "market_read"})]


@router.get("/snapshot", operation_id="getAuthorizedDashboard", response_model=AuthorizedSnapshot)
def snapshot(
    request: Request,
    sid: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> AuthorizedSnapshot:
    return read_snapshot(sid, request.state.request_id, touch=True).snapshot


async def market_stream(
    request: Request, sid: str | None, initial: SnapshotState
) -> AsyncIterator[str]:
    previous = initial
    yield sse_event("ready", {"schema_version": 1, "mode": "market_read"})
    for _ in range(MAX_POLLS):
        if await request.is_disconnected():
            return
        await asyncio.sleep(POLL_SECONDS)
        try:
            current = await run_in_threadpool(
                read_snapshot, sid, request.state.request_id, touch=False
            )
        except HTTPException:
            yield sse_event("resync", {"reason": "authority_unavailable"})
            return
        for event in changes(previous, current):
            yield event
            if event.startswith("event: resync\n"):
                return
        previous = current
        yield ": heartbeat\n\n"


@router.get("/stream", include_in_schema=False)
async def stream(
    request: Request,
    sid: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> StreamingResponse:
    if not _connections.acquire(blocking=False):
        raise HTTPException(503, "stream capacity reached")
    try:
        initial = await run_in_threadpool(read_snapshot, sid, request.state.request_id, touch=True)
    except BaseException:
        _connections.release()
        raise

    async def bounded() -> AsyncIterator[str]:
        try:
            async for event in market_stream(request, sid, initial):
                yield event
        finally:
            _connections.release()

    return StreamingResponse(
        bounded(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
