"""PostgreSQL 17 real role isolation, session revocation, scrape lease and quarantine."""

import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from psycopg.errors import InsufficientPrivilege
from testcontainers.postgres import PostgresContainer

from autoaxe.application.scrape_broker import (
    claim,
    complete,
    heartbeat,
    submit,
)
from autoaxe.infrastructure.db_bootstrap import provision
from autoaxe.infrastructure.market_store import PermissionDenied, set_permission
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
