"""Phase 2 fixture-only dashboard catalog and SSE invalidation contract."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import Field

from autoaxe.adapters.contracts import Contract, Identifier, UtcTime
from autoaxe.domain.indicator_registry import all_indicators

router = APIRouter(prefix="/api/v1", tags=["dashboard"])


class IndicatorView(Contract):
    indicator_id: Identifier
    label: str
    category: str
    source_id: str
    unit: str
    cadence: str
    source_note: str
    value: str | None
    quality: Literal["synthetic_fixture", "permission_required"]
    source_event_at: UtcTime | None
    observed_at: UtcTime | None
    available_at: UtcTime | None
    permission: Literal["fixture_only", "unverified"]


class DashboardMeta(Contract):
    request_id: Identifier
    environment: Literal["fixture"] = "fixture"
    live_enabled: Literal[False] = False
    external_mcp_enabled: Literal[False] = False
    schema_version: Literal[1] = 1
    version: int = Field(default=0, ge=0)
    as_of: UtcTime
    next_cursor: str | None = None


class DashboardPage(Contract):
    data: list[IndicatorView]
    meta: DashboardMeta


def build_dashboard(
    *,
    request_id: str,
    category: str | None = None,
    cursor: str | None = None,
    limit: int = 40,
) -> DashboardPage:
    definitions = [
        item for item in all_indicators() if category is None or item.category == category
    ]
    if cursor is not None and cursor not in [item.id for item in definitions]:
        raise ValueError("invalid dashboard cursor")
    offset = [item.id for item in definitions].index(cursor) + 1 if cursor else 0
    page = definitions[offset : offset + limit]
    data = []
    for entry in page:
        fixture = entry.source_id == "fixture"
        data.append(
            IndicatorView(
                indicator_id=entry.id,
                label=entry.label,
                category=entry.category,
                source_id=entry.source_id,
                unit=entry.unit,
                cadence=entry.cadence,
                source_note=entry.note,
                value="123.45" if fixture else None,
                quality="synthetic_fixture" if fixture else "permission_required",
                source_event_at=None,
                observed_at=None,
                available_at=None,
                permission="fixture_only" if fixture else "unverified",
            )
        )
    next_cursor = page[-1].id if offset + len(page) < len(definitions) and page else None
    return DashboardPage(
        data=data,
        meta=DashboardMeta(request_id=request_id, as_of=datetime.now(UTC), next_cursor=next_cursor),
    )


@router.get(
    "/dashboard/indicators", operation_id="listDashboardIndicators", response_model=DashboardPage
)
def list_dashboard_indicators(
    request: Request,
    category: str | None = None,
    cursor: str | None = None,
    limit: int = Query(40, ge=1, le=100),
) -> DashboardPage:
    if category is not None and category not in {
        "market",
        "equities",
        "macro",
        "rates",
        "calendar",
        "sentiment",
        "industry",
        "manual",
    }:
        raise HTTPException(400, "unrecognized category")
    try:
        return build_dashboard(
            request_id=request.state.request_id,
            category=category,
            cursor=cursor,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(400, "invalid dashboard cursor") from exc


async def fixture_sse(request: Request) -> AsyncIterator[str]:
    """No external/live events; snapshot REST always follows ready."""
    yield (
        "event: ready\ndata: "
        + json.dumps(
            {
                "schema_version": 1,
                "mode": "fixture",
                "aggregate": "dashboard",
                "version": 0,
                "last_event_id": None,
            },
            separators=(",", ":"),
        )
        + "\n\n"
    )
    for _ in range(3):
        if await request.is_disconnected():
            return
        await asyncio.sleep(2)
        yield ": heartbeat\n\n"


@router.get("/dashboard/stream", operation_id="streamFixtureDashboard", include_in_schema=False)
async def stream_dashboard(request: Request) -> StreamingResponse:
    return StreamingResponse(
        fixture_sse(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
