"""Authenticated committed market snapshot and bounded durable version replay.

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
from pydantic import Field
from starlette.concurrency import run_in_threadpool
from starlette.types import Receive, Scope, Send

from autoaxe.adapters.contracts import Contract, Identifier, UtcTime
from autoaxe.domain.catalog import catalog
from autoaxe.domain.owner_access import is_configured_owner
from autoaxe.entrypoints.auth import SESSION_COOKIE
from autoaxe.entrypoints.auth import _dsn as identity_dsn
from autoaxe.infrastructure.market_store import PermissionDenied, two_year_usable, verify_connection
from autoaxe.infrastructure.sessions import authorize

router = APIRouter(prefix="/api/v1/dashboard/authorized", tags=["dashboard-authorized"])
_connections = BoundedSemaphore(8)
POLL_SECONDS = 2
MAX_POLLS = 450
MAX_REPLAY = 256


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
    oil_selected: dict[str, str | None] = Field(default_factory=dict)
    two_year_selected: str | None = None


class AuthorizedSnapshot(Contract):
    data: list[SnapshotPoint]
    meta: SnapshotMeta


@dataclass(frozen=True)
class SnapshotState:
    snapshot: AuthorizedSnapshot
    authority: tuple[str, int, bool]
    permissions: dict[str, int]
    replay: tuple[tuple[str, int], ...] | None = None


def read_snapshot(
    sid: str | None,
    request_id: str,
    *,
    touch: bool,
    previous: SnapshotState | None = None,
) -> SnapshotState:
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
                       o.value,o.quality,o.source_event_at,o.received_at,o.metadata,
                       h.status,h.checked_at,h.reason
                       FROM catalog.series s JOIN catalog.source_registry r USING(source_id)
                       LEFT JOIN market.series_versions v USING(series_id)
                       LEFT JOIN market.latest_observations l USING(series_id)
                       LEFT JOIN market.observations o ON o.partition_at=l.partition_at
                         AND o.observation_id=l.observation_id
                         AND o.mapping_version=s.mapping_version
                         AND (s.series_id NOT IN ('UST_2Y_TOSS','UST_2Y_TREASURY')
                              OR o.permission_version=r.permission_version)
                         AND o.available_at<=%s AND o.ingested_at<=%s
                       LEFT JOIN ops.collector_health h ON h.series_id=s.series_id
                       WHERE r.permission_status='approved' AND r.enabled AND r.free_only
                         AND r.allow_fetch AND r.allow_storage
                         AND (r.allow_redistribution OR %s::boolean)
                         AND (s.source_id<>'toss' OR %s::boolean)
                         AND r.verified_at IS NOT NULL AND r.evidence_ref <> ''
                         AND s.source_id <> 'fixture'
                       ORDER BY s.series_id""",
                    (as_of, as_of, private, private),
                ).fetchall()
                oil_selections = cur.execute(
                    """SELECT DISTINCT ON(indicator_id) indicator_id,series_id
                    FROM market.source_selections
                    WHERE indicator_id IN ('WTI_BINANCE_PERP','BRENT_BINANCE_PERP')
                    AND selected_at<=%s ORDER BY indicator_id,selection_id DESC""",
                    (as_of,),
                ).fetchall()
                replay: tuple[tuple[str, int], ...] | None = None
                if previous is not None:
                    wanted = {
                        row["series_id"]: row["version"]
                        for row in rows
                        if row["series_id"] in previous.permissions
                        and row["permission_version"] == previous.permissions[row["series_id"]]
                        and row["series_id"] in entries
                        and row["mapping_version"] == entries[row["series_id"]].mapping_version
                    }
                    baseline = previous.snapshot.meta.versions
                    ranges = [
                        (sid_, baseline[sid_], version)
                        for sid_, version in wanted.items()
                        if sid_ in baseline and version > baseline[sid_]
                    ]
                    if sum(end - start for _, start, end in ranges) <= MAX_REPLAY:
                        if ranges:
                            items = cur.execute(
                                """SELECT o.series_id,o.series_version
                                   FROM unnest(%s::text[],%s::bigint[],%s::bigint[])
                                      AS bounds(sid,lo,hi)
                                   JOIN market.observations o ON o.series_id=bounds.sid
                                     AND o.series_version>bounds.lo AND o.series_version<=bounds.hi
                                   JOIN catalog.series s ON s.series_id=o.series_id
                                     AND s.mapping_version=o.mapping_version
                                   WHERE o.available_at<=%s AND o.ingested_at<=%s
                                   ORDER BY o.series_id,o.series_version LIMIT %s""",
                                (
                                    [r[0] for r in ranges],
                                    [r[1] for r in ranges],
                                    [r[2] for r in ranges],
                                    as_of,
                                    as_of,
                                    MAX_REPLAY + 1,
                                ),
                            ).fetchall()
                            replay = tuple((r["series_id"], r["series_version"]) for r in items)
                        else:
                            replay = ()
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
            if series_id in {"VIX", "VIX_YAHOO_WS"} and quality == "unknown" and stamp is not None:
                if (as_of - stamp).total_seconds() > 10:
                    quality = "stale"
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
        oil_selected: dict[str, str | None] = {}
        by_id = {p.series_id: p for p in points}
        for selection in oil_selections:
            indicator = selection["indicator_id"]
            selected = selection["series_id"]
            primary = indicator + "_SNAPSHOT"
            fallback = indicator.removesuffix("_BINANCE_PERP") + "_YAHOO_FUTURES_WS"
            # Do not disclose selections for an entirely unauthorized indicator.
            if not ({indicator, primary, fallback} & by_id.keys()):
                continue
            point = by_id.get(selected)
            if selected == primary and point and point.value is not None:
                oil_selected[indicator] = selected
            elif (
                selected == fallback
                and point
                and point.value is not None
                and point.collector_checked_at is not None
                and 0 <= (as_of - point.collector_checked_at).total_seconds() <= 60
            ):
                oil_selected[indicator] = selected
            else:
                oil_selected[indicator] = None
        two_year_selected = None
        row_by_id = {row["series_id"]: row for row in rows}
        for sid_2y in ("UST_2Y_TOSS", "UST_2Y_TREASURY"):
            if sid_2y in by_id:
                r2 = row_by_id[sid_2y]
                if two_year_usable(
                    sid_2y,
                    r2["status"],
                    r2["value"],
                    r2["quality"],
                    r2["metadata"],
                    r2["received_at"],
                    as_of,
                    r2["reason"],
                ):
                    two_year_selected = sid_2y
                    break
        return SnapshotState(
            AuthorizedSnapshot(
                data=points,
                meta=SnapshotMeta(
                    request_id=request_id,
                    as_of=as_of,
                    versions={p.series_id: p.version for p in points},
                    oil_selected=oil_selected,
                    two_year_selected=two_year_selected,
                ),
            ),
            (grant.session_hash, grant.auth_version, private),
            permissions,
            replay,
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
    before, after = old.snapshot.meta.versions, new.snapshot.meta.versions
    if before.keys() != after.keys() or any(after[k] < v for k, v in before.items()):
        return [sse_event("resync", {"reason": "version_reset"})]
    count = sum(after[k] - v for k, v in before.items())
    if count > MAX_REPLAY:
        return [sse_event("resync", {"reason": "replay_overflow"})]
    expected = tuple((k, v) for k in sorted(before) for v in range(before[k] + 1, after[k] + 1))
    if count and new.replay != expected:
        return [sse_event("resync", {"reason": "version_gap"})]
    events = [
        sse_event(
            "market.invalidate",
            {
                "schema_version": 1,
                "mode": "market_read",
                "aggregate_id": sid,
                "aggregate_version": version,
                "event_type": "market.observation.recorded",
            },
        )
        for sid, version in expected
    ]
    if not events and (
        old.snapshot.data != new.snapshot.data
        or old.snapshot.meta.oil_selected != new.snapshot.meta.oil_selected
        or old.snapshot.meta.two_year_selected != new.snapshot.meta.two_year_selected
    ):
        events.append(sse_event("market.refresh", {"schema_version": 1, "mode": "market_read"}))
    return events


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
        if await request.is_disconnected():
            return
        try:
            current = await run_in_threadpool(
                read_snapshot, sid, request.state.request_id, touch=False, previous=previous
            )
        except HTTPException:
            yield sse_event("resync", {"reason": "authority_unavailable"})
            return
        for event in changes(previous, current):
            yield event
            if event.startswith("event: resync\n"):
                return
        previous = current
        yield sse_event("heartbeat", {"schema_version": 1, "mode": "market_read"})


class CapacityResponse(StreamingResponse):
    """Release admission even if ASGI disconnects before the first body yield."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            _connections.release()


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

    return CapacityResponse(
        market_stream(request, sid, initial),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
