"""Actual PG17 transaction, permissions, replay and REST contract evidence."""

import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.errors import InsufficientPrivilege
from testcontainers.postgres import PostgresContainer

from autoaxe.application.market_worker import (
    relay_batch,
    run_one,
    submit_collection,
    synthetic_collect,
)
from autoaxe.domain.market import Candidate, Quality
from autoaxe.entrypoints.api import create_app
from autoaxe.infrastructure.db_bootstrap import provision
from autoaxe.infrastructure.jobs import (
    accept,
    acknowledge,
    cancel,
    claim,
    enqueue,
    finish,
    heartbeat,
    pending,
)
from autoaxe.infrastructure.market_store import (
    PermissionDenied,
    gate,
    ingest,
    persist_trade,
    query,
    review_manual,
    select_two_year,
    set_permission,
)

IMAGE = "postgres:17@sha256:87c8b42f423b45d5247e6aa8fdb2e7762fec164c68a50fe3eb07e7bfcaf4dbcf"


@pytest.mark.integration
def test_ledger_jobs_and_mode_ingress(monkeypatch):
    monkeypatch.setenv("AUTOAXE_DISPOSABLE_DB", "true")
    password = secrets.token_urlsafe(24)
    with PostgresContainer(
        IMAGE, username="fixture_admin", password=password, dbname="postgres"
    ) as pg:
        host, port = pg.get_container_host_ip(), pg.get_exposed_port(5432)
        admin = psycopg.conninfo.make_conninfo(
            host=host, port=port, dbname="postgres", user="fixture_admin", password=password
        )
        passwords = provision(admin, Path(__file__).resolve().parents[1] / "alembic.ini")

        def dsn(db, role):
            user = f"{db}_{role}"
            return psycopg.conninfo.make_conninfo(
                host=host, port=port, dbname=db, user=user, password=passwords[user]
            )

        market = dsn("autoaxe_market", "runtime")
        reader = dsn("autoaxe_market", "read")
        now = datetime.now(UTC) - timedelta(seconds=1)

        def item(key, value, stamp):
            return Candidate("FIXTURE_PRICE", key, value, stamp, now, now)

        with psycopg.connect(market) as conn:
            with pytest.raises(PermissionDenied):
                gate(conn, "VIX", "fetch")
            with pytest.raises(PermissionDenied):
                ingest(conn, Candidate("VIX", "1", "15", now, now, now))
            oid, rev, created = ingest(conn, item("10", "123.45678901234567890123456789", now))
            assert rev == 1 and created
            assert ingest(conn, item("10", "123.45678901234567890123456789", now)) == (
                oid,
                1,
                False,
            )
            oid2, rev2, created = ingest(conn, item("10", "124", now))
            assert rev2 == 2 and created and oid2 != oid
            ingest(conn, item("9", "120", now - timedelta(seconds=5)))
            latest = conn.execute(
                "SELECT observation_id FROM market.latest_observations"
            ).fetchone()
            assert str(latest[0]) == oid2
            jid = enqueue(conn, "collect", "fixture", "key", {"series": "FIXTURE_PRICE"})
            assert enqueue(conn, "collect", "fixture", "key", {"series": "FIXTURE_PRICE"}) == jid
            with pytest.raises(ValueError):
                enqueue(conn, "collect", "fixture", "key", {"series": "other"})
            assert select_two_year(conn, now) == (None, "no_permitted_source")
        with psycopg.connect(reader) as conn:
            cutoff = conn.execute("SELECT clock_timestamp()").fetchone()[0]
            rows = query(conn, series_id="FIXTURE_PRICE", as_of=cutoff, limit=10)
            assert len(rows) == 2 and str(rows[0]["value"]) == "124"
            with pytest.raises(InsufficientPrivilege):
                conn.execute("DELETE FROM market.observations")
        # rollback must remove observation + dedupe + event together
        with psycopg.connect(market) as conn:
            ingest(conn, item("rollback", "99", now))
            conn.rollback()
        with psycopg.connect(market) as conn:
            assert conn.execute("SELECT count(*) FROM market.observations").fetchone()[0] == 3
            claimed = claim(conn)
            assert str(claimed["id"]) == jid
            token = str(claimed["lease_token"])
        with psycopg.connect(market) as conn:
            assert heartbeat(conn, jid, token)
            assert (
                finish(conn, jid, token, success=False, retryable=True, error_code="429")
                == "queued"
            )
        with psycopg.connect(market) as conn:
            # Test clock manipulation only (not sleep); simulate retry ready.
            conn.execute("UPDATE ops.jobs SET available_at=clock_timestamp() WHERE id=%s", (jid,))
            second = claim(conn)
            assert second["attempt"] == 2 and str(second["lease_token"]) != token
            with pytest.raises(ValueError):
                finish(conn, jid, token, success=True)
            assert cancel(conn, jid, "fixture") == "cancel_requested"
            assert finish(conn, jid, str(second["lease_token"]), success=True) == "cancelled"
        relay = dsn("autoaxe_market", "relay")
        mode = dsn("autoaxe_dry_run", "runtime")
        with psycopg.connect(relay) as conn:
            events = pending(conn, "dry")
        obs = [e for e in events if e["event_type"] == "market.observation.recorded"]
        assert len(obs) == 3
        with psycopg.connect(mode) as conn:
            assert accept(conn, "dry", obs[1]) == "gap"
            assert accept(conn, "dry", obs[0]) == "accepted"
            assert accept(conn, "dry", obs[0]) == "duplicate"
            assert accept(conn, "dry", obs[1]) == "accepted"
            assert accept(conn, "dry", obs[2]) == "accepted"
        with psycopg.connect(relay) as conn:
            acknowledge(conn, "dry", obs[0]["event_id"])
            assert obs[0] not in pending(conn, "dry")
        # API read-only fixture scope, cursor stable across revisions.
        monkeypatch.setenv("AUTOAXE_FIXTURE_MARKET_READ_DSN", reader)
        client = TestClient(create_app())
        response = client.get(
            "/api/v1/market/observations", params={"series_id": "FIXTURE_PRICE", "limit": 1}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["data"][0]["value"] == "124"
        cursor = body["meta"]["next_cursor"]
        assert cursor
        second = client.get(
            "/api/v1/market/observations", params={"series_id": "FIXTURE_PRICE", "cursor": cursor}
        )
        assert second.status_code == 200 and second.json()["data"][0]["value"] == "120"
        assert (
            client.get("/api/v1/market/observations", params={"series_id": "VIX"}).status_code
            == 403
        )
        # Authorized test-only source states; no network requests.
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            set_permission(
                conn,
                "treasury",
                approved=True,
                evidence="synthetic test permission",
                fetch=True,
                storage=True,
            )
        with psycopg.connect(market) as conn:
            ingest(
                conn,
                Candidate(
                    "UST_2Y_TREASURY",
                    "2026-11-25",
                    "4.6",
                    None,
                    now,
                    now,
                    Quality.UNKNOWN,
                    {"official_daily": True},
                ),
            )
            conn.execute(
                "INSERT INTO ops.collector_health VALUES "
                "('UST_2Y_TREASURY','healthy','fixture',clock_timestamp())"
            )
            assert select_two_year(conn, now)[0] == "UST_2Y_TREASURY"
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            set_permission(
                conn,
                "naver",
                approved=True,
                evidence="synthetic test permission",
                fetch=True,
                storage=True,
            )
        with psycopg.connect(market) as conn:
            ingest(conn, Candidate("UST_2Y_NAVER", "primary", "4.65", now, now, now))
            conn.execute(
                "INSERT INTO ops.collector_health VALUES "
                "('UST_2Y_NAVER','healthy','fixture',clock_timestamp())"
            )
            assert select_two_year(conn, now)[0] == "UST_2Y_NAVER"
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            set_permission(
                conn,
                "naver",
                approved=False,
                evidence="synthetic revoked",
                fetch=False,
                storage=False,
            )
        with psycopg.connect(market) as conn:
            assert select_two_year(conn, now)[0] == "UST_2Y_TREASURY"
            with pytest.raises(PermissionDenied):
                ingest(conn, Candidate("UST_2Y_NAVER", "after-revoke", "4.7", now, now, now))
            submit_collection(conn, "FIXTURE_PRICE", "worker", "test-one")
        assert run_one(market, synthetic_collect) == "succeeded"
        assert relay_batch(relay, mode, "dry") > 0
        assert relay_batch(relay, mode, "dry") == 0
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            set_permission(
                conn,
                "manual:CNN_FEAR_GREED",
                approved=True,
                evidence="synthetic permission",
                fetch=True,
                storage=True,
            )
            set_permission(
                conn,
                "binance_spot",
                approved=True,
                evidence="synthetic permission",
                fetch=True,
                storage=True,
            )
        with psycopg.connect(market) as conn:
            manual = Candidate(
                "CNN_FEAR_GREED",
                "manual-1",
                "65",
                None,
                now,
                now,
                Quality.MANUAL_UNVERIFIED,
                {"operator": "fixture-a"},
            )
            mid = ingest(conn, manual)[0]
            with pytest.raises(ValueError):
                review_manual(conn, mid, "fixture-a", "checked", "self")
            assert review_manual(conn, mid, "fixture-b", "checked", "fixture review")
            assert conn.execute("SELECT count(*) FROM market.manual_reviews").fetchone()[0] == 1
            first = Candidate("BITCOIN_BINANCE_SPOT", "1", "10", now, now, now)
            persist_trade(conn, first)
            with pytest.raises(ValueError):
                persist_trade(conn, Candidate("BITCOIN_BINANCE_SPOT", "3", "11", now, now, now))
            persist_trade(conn, Candidate("BITCOIN_BINANCE_SPOT", "2", "11", now, now, now))
            assert (
                conn.execute("SELECT last_trade_id FROM market.stream_checkpoints").fetchone()[0]
                == 2
            )
            assert (
                conn.execute(
                    "SELECT count(*) FROM catalog.permission_versions WHERE source_id='naver'"
                ).fetchone()[0]
                == 3
            )
