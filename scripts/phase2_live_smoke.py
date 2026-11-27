"""Explicit one-shot Stage 2 validation against a fresh disposable PostgreSQL.

Run in the locked backend collection-smoke environment. Never accepts a
production DSN, never persists raw HTTP responses or reports credentials.
The allowlist is limited to documented public paths for this verification.
"""

import argparse
import asyncio
import json
import os
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psycopg
from autoaxe.adapters.mexc_ws import stream_tickers
from autoaxe.adapters.transport import ProviderTransport
from autoaxe.application.binance_qqq_poll import poll_once as poll_qqq
from autoaxe.application.collection import FetchError
from autoaxe.application.document_scheduler import scan_once
from autoaxe.application.mexc_poll import poll_once as poll_mexc
from autoaxe.application.mexc_ws_worker import run_session
from autoaxe.application.official_macro import OfficialSourceError
from autoaxe.application.official_poll import fetch_release, poll_once
from autoaxe.application.pizzint_poll import poll_once as poll_pizzint
from autoaxe.application.polling import tick
from autoaxe.domain.catalog import RATIOS
from autoaxe.entrypoints.binance_qqq_cli import fetch as fetch_qqq
from autoaxe.entrypoints.mexc_cli import fetch as fetch_mexc
from autoaxe.entrypoints.pizzint_cli import fetch_doughcon
from autoaxe.infrastructure.db_bootstrap import provision
from autoaxe.infrastructure.market_store import (
    gate,
    ingest,
    set_permission,
)
from testcontainers.postgres import PostgresContainer

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "postgres:17@sha256:87c8b42f423b45d5247e6aa8fdb2e7762fec164c68a50fe3eb07e7bfcaf4dbcf"
EVIDENCE = {
    "pizzint": ("pizzint", "https://www.pizzint.watch/terms"),
    "treasury": (
        "treasury",
        "https://home.treasury.gov/treasury-daily-interest-rate-xml-feed",
    ),
    "bls_actual": ("bls", "https://www.bls.gov/developers/termsOfService.htm"),
    "bls_calendar": ("bls", "https://www.bls.gov/schedule/"),
    "bea_calendar": ("bea", "https://www.bea.gov/news/schedule/icalendar"),
    "census_calendar": ("census", "https://www.census.gov/economic-indicators/"),
    "census_retail_calendar": ("census", "https://www.census.gov/retail/"),
    "fed_calendar": (
        "fed",
        "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    ),
    "ecb_dfr": ("ecb", "https://data.ecb.europa.eu/help/api/overview"),
    "boe_rate": ("boe", "https://www.bankofengland.co.uk/boeapps/database/Help.asp"),
    "boj_effective": (
        "boj",
        "https://www.stat-search.boj.or.jp/info/api_manual_en.pdf",
    ),
    "boj_document": ("boj", "https://www.boj.or.jp/en/about/copyright.htm"),
    "binance_qqq": (
        "binance_futures",
        "https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data",
    ),
    "binance_ratios": (
        "binance_futures",
        "https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data",
    ),
    "mexc_rest": (
        "mexc",
        "https://www.mexc.com/api-docs/futures/market-endpoints/get-contract-info",
    ),
    "mexc_ws": (
        "mexc",
        "https://www.mexc.com/api-docs/futures/websocket-api/protocol-buffers-integration/",
    ),
}
MARKET_TASKS = {
    "binance_qqq": ("NASDAQ100_BINANCE_QQQ_PERP_USDT",),
    "mexc_rest": ("NASDAQ100_MEXC_PERP_USDT",),
    "mexc_ws": ("NASDAQ100_MEXC_PERP_USDT_WS",),
    # One representative per ratio type. All six symbols were separately
    # validated against the real endpoint during Stage 2.
    "binance_ratios": tuple(f"BINANCE_{kind.upper()}_BTCUSDT" for kind in RATIOS),
}


def emit(task, **fields):
    print(
        json.dumps(
            {"task": task, "checked_at": datetime.now(UTC).isoformat(), **fields},
            ensure_ascii=True,
            default=str,
        ),
        flush=True,
    )


def check_market(task, runtime):
    ids = MARKET_TASKS[task]
    if task == "binance_qqq":
        result = asyncio.run(poll_qqq(runtime, fetch_qqq, enabled=True))
    elif task == "mexc_rest":
        result = asyncio.run(poll_mexc(runtime, fetch_mexc, enabled=True))
    elif task == "mexc_ws":
        result = asyncio.run(
            run_session(
                runtime,
                lambda permit: stream_tickers(
                    permit, network_opt_in=True, session_seconds=12
                ),
                enabled=True,
            )
        )
    else:

        def collect(series_id):
            kind = next(
                k for k in RATIOS if f"BINANCE_{k.upper()}_BTCUSDT" == series_id
            )
            with psycopg.connect(runtime) as conn:

                def permit(sid):
                    if sid != series_id:
                        raise ValueError("outside fixed smoke scope")
                    gate(conn, sid, "fetch")
                    gate(conn, sid, "storage")

                try:
                    return asyncio.run(
                        ProviderTransport(permit, network_opt_in=True).ratios(
                            "BTCUSDT", kind
                        )
                    )
                except httpx.HTTPError:
                    raise ConnectionError("ratio transport failed") from None

        stats = tick(runtime, ids, collect, max_jobs=len(ids))
        emit(task, **stats)
        result = "stored"
    with psycopg.connect(runtime) as conn:
        rows = conn.execute(
            """SELECT series_id,count(*),max(source_event_at),array_agg(DISTINCT quality)
               FROM market.observations WHERE series_id=ANY(%s) GROUP BY series_id ORDER BY series_id""",
            (list(ids),),
        ).fetchall()
        circuit = conn.execute(
            "SELECT reason FROM ops.poll_circuits WHERE source_id=%s",
            (EVIDENCE[task][0],),
        ).fetchone()
    if result == "stored" and len(rows) != len(ids):
        result = "incomplete"
    emit(
        task,
        result=result,
        stored_rows=sum(row[1] for row in rows),
        series=[
            {
                "id": row[0],
                "count": row[1],
                "latest_source_event": row[2],
                "quality": row[3],
            }
            for row in rows
        ],
        circuit=circuit[0] if circuit else None,
    )
    return result


def check(task, runtime, client):
    source, _policy = EVIDENCE[task]
    if task in MARKET_TASKS:
        return check_market(task, runtime)
    if task == "pizzint":
        result = poll_pizzint(runtime, fetch_doughcon)
        with psycopg.connect(runtime) as conn:
            rows = conn.execute(
                """SELECT count(*),max(source_event_at),max(quality) FROM market.observations
                WHERE series_id='PENTAGON_PIZZA_PIZZINT'"""
            ).fetchone()
            circuit = conn.execute(
                "SELECT reason FROM ops.poll_circuits WHERE source_id=%s", (source,)
            ).fetchone()
        emit(
            task,
            result=result,
            stored_rows=rows[0],
            source_event_at=rows[1],
            quality=rows[2],
            circuit=circuit[0] if circuit else None,
        )
        return result
    elif task == "treasury":
        # One official XML request, normalized candidates persist atomically.
        with psycopg.connect(runtime) as conn:

            def permit(series_id):
                gate(conn, series_id, "fetch")
                gate(conn, series_id, "storage")

            rows = asyncio.run(
                ProviderTransport(permit, network_opt_in=True).treasury(
                    datetime.now(UTC).strftime("%Y%m")
                )
            )
            count = sum(ingest(conn, row)[2] for row in rows)
        result = "stored" if count else "no_data"
        emit(
            task,
            result=result,
            stored_rows=count,
            series=sorted({row.series_id for row in rows}),
            latest_observation_date=max(
                (row.metadata["observation_date"] for row in rows), default=None
            ),
            latest_source_event=max(
                (row.source_event_at for row in rows if row.source_event_at),
                default=None,
            ),
        )
        return result
    elif task == "boj_document":
        scan = scan_once(runtime, client, "boj")
        with psycopg.connect(runtime) as conn:
            count = conn.execute(
                "SELECT count(*) FROM ops.official_document_inbox WHERE source_id='boj'"
            ).fetchone()[0]
        result = scan.capture.parse_status if scan.capture else "no_new_document"
        emit(
            task,
            result=result,
            inbox_rows=count,
            source_url=scan.capture.source_url if scan.capture else None,
            candidate_available=bool(scan.capture and scan.capture.candidate),
        )
        return result
    else:
        with psycopg.connect(runtime) as conn:
            before = conn.execute(
                "SELECT count(*) FROM indicators.event_calendar WHERE source_id=%s",
                (source,),
            ).fetchone()[0]

        def fetch(permit):
            events = fetch_release(task, client, permit)
            emit(
                task,
                parsed_rows=len(events),
                observed_values=sum(row.actual is not None for row in events),
                calendar_rows=sum(row.calendar is not None for row in events),
                units=sorted({event.unit for event in events}),
                event_prefixes=sorted(
                    {
                        event.event_key.split(":", 1)[0]
                        for event in events
                        if event.calendar is None
                    }
                ),
            )
            return events

        result = poll_once(runtime, task, fetch)
        with psycopg.connect(runtime) as conn:
            count = conn.execute(
                "SELECT count(*) FROM indicators.event_calendar WHERE source_id=%s",
                (source,),
            ).fetchone()[0]
            circuit = conn.execute(
                "SELECT reason FROM ops.poll_circuits WHERE source_id=%s", (source,)
            ).fetchone()
        emit(
            task,
            result=result,
            stored_rows=count - before,
            circuit=circuit[0] if circuit else None,
        )
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-disposable", required=True, action="store_true")
    parser.add_argument("--tasks", required=True, nargs="+", choices=sorted(EVIDENCE))
    args = parser.parse_args()
    os.environ["AUTOAXE_DISPOSABLE_DB"] = "true"
    # The dedicated PizzINT transport is dependency-free and isolated in the
    # collector image; import only that package for this development smoke.
    sys.path.insert(0, str(ROOT / "apps" / "scraper" / "src"))
    secret = secrets.token_urlsafe(32)
    with PostgresContainer(
        IMAGE, username="smoke_admin", password=secret, dbname="postgres"
    ) as pg:
        opts = {"host": pg.get_container_host_ip(), "port": pg.get_exposed_port(5432)}
        admin = psycopg.conninfo.make_conninfo(
            **opts, dbname="postgres", user="smoke_admin", password=secret
        )
        passwords = provision(admin, ROOT / "apps" / "backend" / "alembic.ini")
        runtime = psycopg.conninfo.make_conninfo(
            **opts,
            dbname="autoaxe_market",
            user="autoaxe_market_runtime",
            password=passwords["autoaxe_market_runtime"],
        )
        # Grant once per source, never re-grant to clear a circuit between tasks.
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            sources = {EVIDENCE[task][0] for task in args.tasks}
            for source in sorted(sources):
                evidence = "; ".join(
                    sorted(
                        {
                            EVIDENCE[task][1]
                            for task in args.tasks
                            if EVIDENCE[task][0] == source
                        }
                    )
                )
                set_permission(
                    conn,
                    source,
                    approved=True,
                    evidence="Stage2 disposable one-shot only; " + evidence,
                    fetch=True,
                    storage=True,
                    redistribution=False,
                    trading=False,
                )
        outcomes = []
        with httpx.Client(
            trust_env=False, follow_redirects=False, timeout=10
        ) as client:
            for task in dict.fromkeys(args.tasks):
                try:
                    outcomes.append(check(task, runtime, client))
                except (FetchError, OfficialSourceError) as exc:
                    outcomes.append("failed")
                    emit(
                        task,
                        result="provider_failed",
                        http_status=exc.status,
                        error_type=type(exc).__name__,
                    )
                except (
                    ValueError,
                    OSError,
                    RuntimeError,
                    psycopg.Error,
                    httpx.HTTPError,
                ) as exc:
                    outcomes.append("failed")
                    # Never print exception text (URLs/DSNs may include credentials).
                    emit(task, result="failed", error_type=type(exc).__name__)
    if any(outcome not in ("stored", "parsed", "no_update") for outcome in outcomes):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
