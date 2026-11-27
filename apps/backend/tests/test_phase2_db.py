"""PostgreSQL 17 real role isolation, session revocation, scrape lease and quarantine."""

import secrets
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.errors import InsufficientPrivilege
from testcontainers.postgres import PostgresContainer

from autoaxe.application.scrape_broker import (
    claim,
    complete,
    heartbeat,
    submit,
)
from autoaxe.domain.calendars import EventRevision
from autoaxe.domain.market import Candidate
from autoaxe.entrypoints.api import create_app
from autoaxe.infrastructure.db_bootstrap import provision
from autoaxe.infrastructure.event_store import persist_event, query_events
from autoaxe.infrastructure.market_store import PermissionDenied, ingest, set_permission
from autoaxe.infrastructure.official_quota import reserve_bls_v1
from autoaxe.infrastructure.sessions import authorize, create_session, revoke, rotate

IMAGE = "postgres:17@sha256:87c8b42f423b45d5247e6aa8fdb2e7762fec164c68a50fe3eb07e7bfcaf4dbcf"


@pytest.mark.integration
def test_sessions_scraper_permissions_and_quarantine(monkeypatch):
    monkeypatch.setenv("AUTOAXE_DISPOSABLE_DB", "true")
    secret = secrets.token_urlsafe(24)
    with PostgresContainer(
        IMAGE, username="fixture_admin", password=secret, dbname="postgres"
    ) as pg:
        opts = dict(host=pg.get_container_host_ip(), port=pg.get_exposed_port(5432))
        admin = psycopg.conninfo.make_conninfo(
            **opts,
            dbname="postgres",
            user="fixture_admin",
            password=secret,
        )
        passwords = provision(admin, Path(__file__).resolve().parents[1] / "alembic.ini")

        def dsn(db: str, suffix: str) -> str:
            role = f"{db}_{suffix}"
            return psycopg.conninfo.make_conninfo(
                **opts,
                dbname=db,
                user=role,
                password=passwords[role],
            )

        app_runtime = dsn("autoaxe_app", "runtime")
        app_read = dsn("autoaxe_app", "read")
        market = dsn("autoaxe_market", "runtime")
        market_read = dsn("autoaxe_market", "read")
        with psycopg.connect(admin, dbname="autoaxe_app") as conn:
            conn.execute(
                """INSERT INTO identity.user_grants(subject_ref,role,scopes)
                VALUES ('https://idp.example/realms/a|fixture-1','viewer',
                '["indicators:read"]'::jsonb)"""
            )
        with psycopg.connect(app_runtime) as conn:
            sid, csrf = create_session(
                conn,
                "https://idp.example/realms/a|fixture-1",
                "https://idp.example/realms/a",
                datetime.now(UTC) + timedelta(hours=1),
            )
            assert authorize(conn, sid, csrf=csrf).role == "viewer"
            with pytest.raises(PermissionError):
                authorize(conn, sid, required_scope="scrapers:admin")
            with pytest.raises(PermissionError):
                authorize(conn, sid, csrf="not-a-token")
            rotated, new_csrf = rotate(conn, sid)
            with pytest.raises(PermissionError):
                authorize(conn, sid)
            assert authorize(conn, rotated, csrf=new_csrf).role == "viewer"
            revoke(conn, rotated)
            with pytest.raises(PermissionError):
                authorize(conn, rotated)
        with psycopg.connect(app_read) as conn:
            with pytest.raises(InsufficientPrivilege):
                conn.execute("SELECT * FROM identity.web_sessions")
        with psycopg.connect(admin, dbname="autoaxe_app") as conn:
            conn.execute(
                "UPDATE identity.user_grants SET auth_version=auth_version+1 "
                "WHERE subject_ref='https://idp.example/realms/a|fixture-1'"
            )
        with psycopg.connect(app_runtime) as conn:
            sid, _ = create_session(
                conn,
                "https://idp.example/realms/a|fixture-1",
                "https://idp.example/realms/a",
                datetime.now(UTC) + timedelta(hours=1),
            )
        with psycopg.connect(admin, dbname="autoaxe_app") as conn:
            conn.execute(
                "UPDATE identity.user_grants SET auth_version=auth_version+1 "
                "WHERE subject_ref='https://idp.example/realms/a|fixture-1'"
            )
        with psycopg.connect(app_runtime) as conn:
            with pytest.raises(PermissionError):
                authorize(conn, sid)
        with psycopg.connect(market) as conn:
            deadline = conn.execute("SELECT clock_timestamp()+interval '3 minutes'").fetchone()[0]
            with pytest.raises(PermissionDenied):
                submit(conn, "cnn", {}, "initial-block", deadline)
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            set_permission(
                conn,
                "cnn",
                approved=True,
                evidence="synthetic unit test only",
                fetch=True,
                storage=True,
            )
        with psycopg.connect(market) as conn:
            job = submit(conn, "cnn", {}, "test-1", deadline)
            assert submit(conn, "cnn", {}, "test-1", deadline) == job
            lease = claim(conn, source="cnn")
            assert lease is not None and lease.job_id == job
            assert heartbeat(conn, job, lease.lease_token, lease.nonce)
            with pytest.raises(PermissionDenied):
                complete(conn, job, "cnn", "forged-token", lease.nonce, [])
            with pytest.raises(ValueError):
                complete(conn, job, "cnn", lease.lease_token, lease.nonce, [{"quality": "valid"}])
            candidate = {
                "quality": "manual_review_required",
                "series_id": "CNN_FEAR_GREED_CNN",
                "value": "65",
            }
            assert (
                complete(conn, job, "cnn", lease.lease_token, lease.nonce, [candidate])
                == "quarantined"
            )
            assert (
                complete(conn, job, "cnn", lease.lease_token, lease.nonce, [candidate])
                == "duplicate"
            )
            with pytest.raises(PermissionDenied):
                complete(conn, job, "cnn", "forged-token", lease.nonce, [candidate])
            assert (
                conn.execute(
                    "SELECT count(*) FROM ops.scrape_results WHERE review_status='quarantined'"
                ).fetchone()[0]
                == 1
            )
            # Nothing is copied into live market data without an independent review.
            assert (
                conn.execute(
                    "SELECT count(*) FROM market.observations WHERE series_id='CNN_FEAR_GREED'"
                ).fetchone()[0]
                == 0
            )
            another = submit(conn, "cnn", {}, "test-2", deadline)
            claim_two = claim(conn, source="cnn")
            assert claim_two is not None and claim_two.job_id == another
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            set_permission(
                conn,
                "cnn",
                approved=False,
                evidence="synthetic revoked",
                fetch=False,
                storage=False,
            )
        with psycopg.connect(market) as conn:
            assert not heartbeat(conn, another, claim_two.lease_token, claim_two.nonce)
            with pytest.raises(PermissionDenied):
                complete(conn, another, "cnn", claim_two.lease_token, claim_two.nonce, [candidate])
        with psycopg.connect(market_read) as conn:
            with pytest.raises(InsufficientPrivilege):
                conn.execute("SELECT * FROM ops.scrape_jobs")

        # PizzINT explicitly allows reasonable public API access. An approved
        # API-only job may be queued, but default unverified source still denies it.
        with psycopg.connect(market) as conn:
            with pytest.raises(PermissionDenied):
                submit(conn, "pizzint", {}, "api-only-denied", deadline)
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            set_permission(
                conn,
                "pizzint",
                approved=True,
                evidence="fixture approved public API only (not homepage HTML)",
                fetch=True,
                storage=True,
                redistribution=False,
            )
        with psycopg.connect(market) as conn:
            new_deadline = conn.execute("SELECT clock_timestamp()+interval '3 minutes'").fetchone()[
                0
            ]
            api_job = submit(conn, "pizzint", {}, "api-only-allowed", new_deadline)
            assert api_job

        # Authorized event persistence must not imply public redistribution rights.
        event = EventRevision(
            "US_CPI:2026-10",
            "bls",
            None,
            None,
            datetime.now(UTC),
            datetime.now(UTC),
            "321.5",
            None,
            None,
            "index",
            1,
            "https://www.bls.gov/developers/",
        )
        with psycopg.connect(market) as conn:
            with pytest.raises(PermissionDenied):
                persist_event(conn, event)
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            set_permission(
                conn,
                "bls",
                approved=True,
                evidence="fixture policy test only",
                fetch=True,
                storage=True,
                redistribution=False,
            )
        with psycopg.connect(market) as conn:
            first, added = persist_event(conn, event)
            assert added and first.revision == 1
            duplicate, added = persist_event(conn, event)
            assert not added and duplicate.revision == 1
            day, used, version = reserve_bls_v1(conn)
            assert used == 1 and version > 0 and day == datetime.now(UTC).date()
            for request in range(2, 26):
                assert reserve_bls_v1(conn)[1] == request
            with pytest.raises(PermissionDenied, match="quota exhausted"):
                reserve_bls_v1(conn)
        with psycopg.connect(market_read) as conn:
            assert query_events(conn, cutoff=datetime.now(UTC)) == []
            # Personal storage/read is not distribution to a third party.
            assert (
                query_events(conn, cutoff=datetime.now(UTC), private_use=True)[0].actual == "321.5"
            )
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            set_permission(
                conn,
                "bls",
                approved=True,
                evidence="fixture redistribution test only",
                fetch=True,
                storage=True,
                redistribution=True,
            )
        cutoff = datetime.now(UTC)
        with psycopg.connect(market_read) as conn:
            actuals = query_events(conn, cutoff=cutoff)
            assert len(actuals) == 1 and actuals[0].actual == "321.5"
        monkeypatch.setenv("AUTOAXE_MARKET_READ_DSN", market_read)
        monkeypatch.setenv("AUTOAXE_APP_RUNTIME_DSN", app_runtime)
        api = TestClient(create_app())
        assert api.get("/api/v1/dashboard/official-events").status_code == 401
        with psycopg.connect(app_runtime) as conn:
            authenticated_sid, _ = create_session(
                conn,
                "https://idp.example/realms/a|fixture-1",
                "https://idp.example/realms/a",
                datetime.now(UTC) + timedelta(minutes=30),
            )
        permitted = api.get(
            "/api/v1/dashboard/official-events",
            cookies={"__Host-autoaxe-sid": authenticated_sid},
        )
        assert permitted.status_code == 200
        assert permitted.json()["data"][0]["actual"] == "321.5"
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            set_permission(
                conn,
                "bls",
                approved=True,
                evidence="personal education without third-party redistribution fixture",
                fetch=True,
                storage=True,
                redistribution=False,
            )
        blocked = api.get(
            "/api/v1/dashboard/official-events",
            cookies={"__Host-autoaxe-sid": authenticated_sid},
        )
        assert blocked.status_code == 200 and blocked.json()["data"] == []
        monkeypatch.setenv("AUTOAXE_PRIVATE_EDUCATIONAL_MODE", "true")
        # A flag alone is not enough: the caller must be the configured owner.
        monkeypatch.setenv(
            "AUTOAXE_PRIVATE_EDUCATIONAL_OWNER_SUBJECT_REF",
            "https://idp.example/realms/a|someone-else",
        )
        still_blocked = api.get(
            "/api/v1/dashboard/official-events",
            cookies={"__Host-autoaxe-sid": authenticated_sid},
        )
        assert still_blocked.status_code == 200 and still_blocked.json()["data"] == []
        monkeypatch.setenv(
            "AUTOAXE_PRIVATE_EDUCATIONAL_OWNER_SUBJECT_REF",
            "https://idp.example/realms/a|fixture-1",
        )
        personal = api.get(
            "/api/v1/dashboard/official-events",
            cookies={"__Host-autoaxe-sid": authenticated_sid},
        )
        assert personal.status_code == 200 and personal.json()["data"][0]["actual"] == "321.5"
        monkeypatch.delenv("AUTOAXE_PRIVATE_EDUCATIONAL_MODE")
        later = datetime.now(UTC) + timedelta(seconds=2)
        corrected = replace(event, actual="321.75", first_seen_at=later, available_at=later)
        with psycopg.connect(market) as conn:
            with pytest.raises(PermissionDenied, match="approval changed"):
                persist_event(conn, corrected, expected_permission_version=version)
            revision, inserted = persist_event(conn, corrected)
            assert inserted and revision.revision == 2
        with psycopg.connect(market_read) as conn:
            assert query_events(conn, cutoff=cutoff, private_use=True)[0].actual == "321.5"
            assert (
                query_events(conn, cutoff=later + timedelta(seconds=1), private_use=True)[0].actual
                == "321.75"
            )
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            set_permission(
                conn,
                "bls",
                approved=False,
                evidence="test source permission revoked",
                fetch=False,
                storage=False,
                redistribution=False,
            )
        with psycopg.connect(market_read) as conn:
            assert query_events(conn, cutoff=later + timedelta(seconds=1)) == []
        hidden = api.get(
            "/api/v1/dashboard/official-events",
            cookies={"__Host-autoaxe-sid": authenticated_sid},
        )
        assert hidden.status_code == 200 and hidden.json()["data"] == []

        # Approved storage is not automatically permission to expose prices.
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            set_permission(
                conn,
                "yfinance",
                approved=True,
                evidence="synthetic historical series integration test only",
                fetch=True,
                storage=True,
                redistribution=False,
            )
        now = datetime.now(UTC)
        with psycopg.connect(market) as conn:
            assert (
                ingest(
                    conn,
                    Candidate(
                        "VIX",
                        "synthetic-integration-bar",
                        "23.45",
                        now,
                        now,
                        now,
                    ),
                )[2]
                is True
            )
        route = "/api/v1/dashboard/authorized/market/VIX"
        assert api.get(route).status_code == 401
        assert api.get(route, cookies={"__Host-autoaxe-sid": authenticated_sid}).status_code == 403
        monkeypatch.setenv("AUTOAXE_PRIVATE_EDUCATIONAL_MODE", "true")
        monkeypatch.setenv(
            "AUTOAXE_PRIVATE_EDUCATIONAL_OWNER_SUBJECT_REF",
            "https://idp.example/realms/a|fixture-1",
        )
        personal_market = api.get(route, cookies={"__Host-autoaxe-sid": authenticated_sid})
        assert personal_market.status_code == 200
        assert personal_market.json()["data"][0]["value"] == "23.45"
        assert personal_market.json()["meta"]["permission"] == "approved_personal_education"
        # Personal viewing cannot enable a public endpoint or allow anonymous access.
        assert api.get(route).status_code == 401
        monkeypatch.delenv("AUTOAXE_PRIVATE_EDUCATIONAL_MODE")
        assert api.get(route, cookies={"__Host-autoaxe-sid": authenticated_sid}).status_code == 403
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            set_permission(
                conn,
                "yfinance",
                approved=True,
                evidence="synthetic market read permission fixture",
                fetch=True,
                storage=True,
                redistribution=True,
            )
        allowed = api.get(route, cookies={"__Host-autoaxe-sid": authenticated_sid})
        assert allowed.status_code == 200
        assert allowed.json()["data"][0]["value"] == "23.45"
        assert allowed.json()["meta"]["source_id"] == "yfinance"
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            set_permission(
                conn,
                "yfinance",
                approved=False,
                evidence="synthetic fixture source revoke",
                fetch=False,
                storage=False,
                redistribution=False,
            )
        assert api.get(route, cookies={"__Host-autoaxe-sid": authenticated_sid}).status_code == 403
