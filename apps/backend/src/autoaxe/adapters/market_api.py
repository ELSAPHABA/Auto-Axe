"""Read-only Phase 1 endpoints; no authenticated external data exposure yet."""

import base64
import json
import os
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request

from autoaxe.adapters.contracts import Contract, Identifier, Money, SafeInt, UtcTime
from autoaxe.domain.canonical import canonical_sha256
from autoaxe.domain.catalog import catalog
from autoaxe.domain.market import Candidate, Quality, quality_at
from autoaxe.domain.types import utc_datetime, utc_string
from autoaxe.infrastructure.market_store import PermissionDenied, current_series_version, query


class SeriesDTO(Contract):
    series_id: Identifier
    indicator_id: Identifier
    source_id: Identifier
    symbol: Identifier
    instrument_type: Identifier
    unit: Identifier
    currency: str | None
    interval: Identifier
    ttl_seconds: int | None
    mapping_version: SafeInt
    priority: int
    activation: str


class MarketMeta(Contract):
    request_id: Identifier
    schema_version: int = 1
    as_of: UtcTime
    next_cursor: str | None = None
    environment: str = "fixture"
    snapshot_version: SafeInt | None = None


class CatalogResponse(Contract):
    data: list[SeriesDTO]
    meta: MarketMeta


class ObservationDTO(Contract):
    observation_id: str
    series_id: Identifier
    source_id: Identifier
    instrument: Identifier
    unit: Identifier
    currency: str | None
    source_event_key: str
    revision: SafeInt
    value: Money | None
    quality: Quality
    stored_quality: Quality
    source_event_at: UtcTime | None
    received_at: UtcTime
    available_at: UtcTime
    ingested_at: UtcTime
    mapping_version: SafeInt
    permission_version: SafeInt
    metadata: dict[str, Any]


class ObservationResponse(Contract):
    data: list[ObservationDTO]
    meta: MarketMeta


def encode_cursor(scope: str, cutoff: datetime, partition: datetime, oid: str, version: int) -> str:
    return base64.urlsafe_b64encode(
        json.dumps(
            [scope, utc_string(cutoff), utc_string(partition), oid, version], separators=(",", ":")
        ).encode()
    ).decode()


def decode_cursor(value: str, scope: str) -> tuple[datetime, datetime, str, int]:
    try:
        if len(value) > 1024:
            raise ValueError("cursor too large")
        data = json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
        if not isinstance(data, list) or len(data) != 5 or data[0] != scope:
            raise ValueError("cursor scope mismatch")
        if type(data[4]) is not int or not 0 <= data[4] <= 9007199254740991:
            raise ValueError("invalid cursor version")
        return (
            utc_datetime(datetime.fromisoformat(data[1])),
            utc_datetime(datetime.fromisoformat(data[2])),
            str(UUID(data[3])),
            data[4],
        )
    except (ValueError, TypeError, IndexError, UnicodeError) as exc:
        raise HTTPException(400, "invalid cursor") from exc


router = APIRouter(prefix="/api/v1")


@router.get("/indicators", operation_id="listIndicatorCatalog", response_model=CatalogResponse)
@router.get("/market/series", operation_id="listMarketSeries", response_model=CatalogResponse)
def list_series(
    request: Request, source: str | None = None, indicator: str | None = None
) -> CatalogResponse:
    rows = [
        SeriesDTO(
            series_id=s.id,
            indicator_id=s.indicator_id,
            source_id=s.source_id,
            symbol=s.symbol,
            instrument_type=s.instrument_type,
            unit=s.unit,
            currency=s.currency,
            interval=s.interval,
            ttl_seconds=s.ttl,
            mapping_version=s.mapping_version,
            priority=s.priority,
            activation="fixture_only" if s.source_id == "fixture" else "blocked",
        )
        for s in catalog().values()
        if (source is None or s.source_id == source)
        and (indicator is None or s.indicator_id == indicator)
    ]
    return CatalogResponse(
        data=rows, meta=MarketMeta(request_id=request.state.request_id, as_of=datetime.now(UTC))
    )


@router.get(
    "/market/observations",
    operation_id="listMarketObservations",
    response_model=ObservationResponse,
)
def observations(
    request: Request,
    series_id: str,
    as_of: UtcTime | None = None,
    start: UtcTime | None = None,
    end: UtcTime | None = None,
    quality: Quality | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ObservationResponse:
    series = catalog().get(series_id)
    if series is None:
        raise HTTPException(404, "unknown series")
    if series.source_id != "fixture":
        raise HTTPException(403, "external data disabled")
    if start and end and start >= end:
        raise HTTPException(400, "invalid date range")
    scope = canonical_sha256(
        [series_id, utc_string(start) if start else None, utc_string(end) if end else None, quality]
    )
    cutoff = as_of or datetime.now(UTC)
    after = None
    version = None
    if cursor:
        prior, stamp, oid, version = decode_cursor(cursor, scope)
        if as_of and as_of != prior:
            raise HTTPException(400, "cursor cutoff mismatch")
        cutoff = prior
        after = (stamp, oid)
    dsn = os.environ.get("AUTOAXE_FIXTURE_MARKET_READ_DSN")
    if not dsn:
        raise HTTPException(503, "fixture market store not configured")
    try:
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            clock = conn.execute("SELECT clock_timestamp()").fetchone()
            assert clock is not None
            if as_of is None and not cursor:
                cutoff = clock[0]
            elif cutoff > clock[0]:
                raise HTTPException(400, "future cutoff")
            visible = current_series_version(conn, series_id)
            if version is None:
                version = visible
            elif version > visible:
                raise HTTPException(400, "future cursor version")
            rows = query(
                conn,
                series_id=series_id,
                as_of=cutoff,
                limit=limit + 1,
                start=start,
                end=end,
                after=after,
                quality=quality,
                snapshot_version=version,
            )
    except PermissionDenied as exc:
        raise HTTPException(403, "market permission denied") from exc
    except psycopg.Error as exc:
        raise HTTPException(503, "fixture market store unavailable") from exc
    data = []
    for row in rows[:limit]:
        item = Candidate(
            series_id,
            row["source_event_key"],
            str(row["value"]) if row["value"] is not None else None,
            row["source_event_at"],
            row["received_at"],
            row["available_at"],
            Quality(row["quality"]),
            row["metadata"],
            row["mapping_version"],
        )
        data.append(
            ObservationDTO(
                observation_id=str(row["observation_id"]),
                series_id=series_id,
                source_id=series.source_id,
                instrument=series.symbol,
                unit=series.unit,
                currency=series.currency,
                source_event_key=item.key,
                revision=row["revision"],
                value=item.value,
                quality=quality_at(item, series, cutoff),
                stored_quality=item.quality,
                source_event_at=item.source_event_at,
                received_at=item.received_at,
                available_at=item.available_at,
                ingested_at=row["ingested_at"],
                mapping_version=item.mapping_version,
                permission_version=row["permission_version"],
                metadata=item.metadata,
            )
        )
    next_cursor = None
    if len(rows) > limit:
        assert version is not None
        last = rows[limit - 1]
        next_cursor = encode_cursor(
            scope, cutoff, last["partition_at"], str(last["observation_id"]), version
        )
    return ObservationResponse(
        data=data,
        meta=MarketMeta(
            request_id=request.state.request_id,
            as_of=cutoff,
            next_cursor=next_cursor,
            snapshot_version=version,
        ),
    )
