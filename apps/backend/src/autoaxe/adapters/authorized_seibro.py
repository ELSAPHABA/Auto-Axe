"""Authenticated private SEIBro TOP50 snapshots; no raw captures or fetches."""

import os
from datetime import date, datetime
from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from psycopg import Connection
from psycopg.rows import dict_row

from autoaxe.adapters.contracts import Contract, Identifier, Money, UtcTime
from autoaxe.application.seibro_review import storage_permission
from autoaxe.domain.owner_access import is_configured_owner
from autoaxe.domain.types import utc_datetime
from autoaxe.entrypoints.auth import SESSION_COOKIE
from autoaxe.entrypoints.auth import _dsn as identity_dsn
from autoaxe.infrastructure.market_store import PermissionDenied, verify_connection
from autoaxe.infrastructure.sessions import authorize

Country = Literal["US", "ALL", "HK", "CN", "JP", "VN"]
Period = Literal["1", "2", "3", "4", "5"]
Basis = Literal["1", "2", "3", "4"]

router = APIRouter(prefix="/api/v1/dashboard/authorized", tags=["dashboard-authorized"])


class SeibroRow(Contract):
    rank: int
    country_name: str
    isin: str
    security_name: str
    buy_settlement_usd: Money | None
    sell_settlement_usd: Money | None
    gross_settlement_usd: Money | None
    net_buy_settlement_usd: Money | None


class SeibroSnapshot(Contract):
    snapshot_id: str
    country_code: Country
    period_code: Period
    rank_basis: Basis
    period_start: date | None
    period_end: date | None
    as_of_date_kst: date
    revision: int
    retrieved_at: UtcTime
    first_seen_at: UtcTime
    available_at: UtcTime
    row_count: int
    currency: Literal["USD"]
    quality: Literal["manual_checked"]
    top50_coverage: Literal[True]
    automated_trading_allowed: Literal[False]
    capture_mode: Literal["manual_capture", "browser_capture"] = "manual_capture"
    derived_amount: Literal["gross_settlement_usd", "net_buy_settlement_usd"] | None = None
    amount_coverage: Literal["complete", "buy_only", "sell_only"] = "complete"
    rows: list[SeibroRow]


class SeibroMeta(Contract):
    request_id: Identifier
    as_of: UtcTime
    source_id: Literal["seibro"] = "seibro"
    permission: Literal["approved_personal_education", "approved_with_redistribution"]
    country_code: Country
    period_code: Period
    rank_basis: Basis


class SeibroResponse(Contract):
    data: SeibroSnapshot | None
    meta: SeibroMeta


def read_top50(
    conn: Connection[Any],
    *,
    country_code: Country,
    period_code: Period,
    rank_basis: Basis,
    cutoff: datetime,
    as_of_date_kst: date | None = None,
    private_use: bool = False,
) -> SeibroSnapshot | None:
    """Select one whole snapshot; never merge ranking universes or revisions."""
    verify_connection(conn, write=False)
    utc_datetime(cutoff)
    version = storage_permission(conn, private_use=private_use)
    with conn.cursor(row_factory=dict_row) as cur:
        snapshot = cur.execute(
            """SELECT id::text AS snapshot_id,country_code,period_code,rank_basis,
                      period_start,period_end,as_of_date_kst,revision,retrieved_at,
                      first_seen_at,available_at,row_count,currency,quality,top50_coverage,
                      automated_trading_allowed,capture_mode,derived_amount,amount_coverage
               FROM indicators.seibro_top50_snapshots
               WHERE country_code=%s AND period_code=%s AND rank_basis=%s
                 AND permission_version=%s AND available_at<=%s
                 AND (%s::date IS NULL OR as_of_date_kst=%s)
               ORDER BY as_of_date_kst DESC,available_at DESC,revision DESC,id DESC LIMIT 1""",
            (
                country_code,
                period_code,
                rank_basis,
                version,
                cutoff,
                as_of_date_kst,
                as_of_date_kst,
            ),
        ).fetchone()
        if snapshot is None:
            return None
        rows = cur.execute(
            """SELECT rank,country_name,isin,security_name,buy_settlement_usd,
                      sell_settlement_usd,gross_settlement_usd,net_buy_settlement_usd
               FROM indicators.seibro_top50_rows WHERE snapshot_id=%s ORDER BY rank LIMIT 51""",
            (snapshot["snapshot_id"],),
        ).fetchall()
    if not 1 <= snapshot["row_count"] <= 50 or len(rows) != snapshot["row_count"]:
        raise ValueError("incomplete SEIBro snapshot")
    if [r["rank"] for r in rows] != list(range(1, len(rows) + 1)):
        raise ValueError("invalid SEIBro snapshot ranks")
    return SeibroSnapshot.model_validate({**snapshot, "rows": rows})


@router.get("/seibro", operation_id="getAuthorizedSeibroTop50", response_model=SeibroResponse)
def get_authorized_seibro(
    request: Request,
    response: Response,
    country_code: Country = "US",
    period_code: Period = "1",
    rank_basis: Basis = "4",
    as_of: UtcTime | None = None,
    as_of_date_kst: date | None = None,
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> SeibroResponse:
    dsn = os.environ.get("AUTOAXE_MARKET_READ_DSN")
    if not dsn:
        raise HTTPException(503, "read-only market authority not configured")
    try:
        with psycopg.connect(identity_dsn(), connect_timeout=3) as app:
            grant = authorize(app, session_id, required_scope="indicators:read")
        private = is_configured_owner(grant.subject_ref)
        with psycopg.connect(dsn, connect_timeout=3) as market:
            market.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            market.execute("SET LOCAL statement_timeout = '3s'")
            clock = market.execute("SELECT transaction_timestamp()").fetchone()
            assert clock is not None
            cutoff = as_of or clock[0]
            if cutoff > clock[0]:
                raise HTTPException(400, "future snapshot cutoff")
            snapshot = read_top50(
                market,
                country_code=country_code,
                period_code=period_code,
                rank_basis=rank_basis,
                cutoff=cutoff,
                as_of_date_kst=as_of_date_kst,
                private_use=private,
            )
    except PermissionError as exc:
        raise HTTPException(401, "session invalid or insufficient scope") from exc
    except PermissionDenied as exc:
        raise HTTPException(403, "source not approved for this audience") from exc
    except (psycopg.Error, ValueError) as exc:
        raise HTTPException(503, "SEIBro snapshot unavailable") from exc
    response.headers["Cache-Control"] = "no-store"
    return SeibroResponse(
        data=snapshot,
        meta=SeibroMeta(
            request_id=request.state.request_id,
            as_of=cutoff,
            country_code=country_code,
            period_code=period_code,
            rank_basis=rank_basis,
            permission="approved_personal_education" if private else "approved_with_redistribution",
        ),
    )
