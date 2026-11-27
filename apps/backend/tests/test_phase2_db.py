"""PostgreSQL 17 real role isolation, session revocation, scrape lease and quarantine."""

import asyncio
import secrets
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.errors import InsufficientPrivilege
from testcontainers.postgres import PostgresContainer

from autoaxe.adapters.authorized_dashboard import changes, read_snapshot
from autoaxe.adapters.binance_qqq_rest import SERIES_ID as QQQ_SERIES
from autoaxe.adapters.macro_sources import BEA_ICS
from autoaxe.adapters.mexc_rest import SERIES_ID as MEXC_SERIES
from autoaxe.adapters.mexc_ws import SCHEMA_COMMIT
from autoaxe.adapters.mexc_ws import SERIES_ID as MEXC_WS_SERIES
from autoaxe.adapters.official_documents import DocumentCapture
from autoaxe.application.binance_qqq_poll import poll_once as poll_qqq
from autoaxe.application.collection import FetchError
from autoaxe.application.document_fetch import capture_once
from autoaxe.application.document_scheduler import Scan, save_scan
from autoaxe.application.mexc_poll import poll_once as poll_mexc
from autoaxe.application.mexc_ws_worker import run_session
from autoaxe.application.official_macro import OfficialSourceError
from autoaxe.application.official_poll import poll_once as poll_official
from autoaxe.application.pizzint_poll import SERIES, poll_once
from autoaxe.application.scrape_broker import (
    claim,
    complete,
    heartbeat,
    submit,
)
from autoaxe.domain.calendars import CalendarEvidence, EventRevision
from autoaxe.domain.canonical import canonical_sha256
from autoaxe.domain.market import Candidate, Quality
from autoaxe.domain.reviewed_documents import extract_boj_policy, extract_guidance
from autoaxe.entrypoints.api import create_app
from autoaxe.infrastructure.db_bootstrap import provision
from autoaxe.infrastructure.document_store import (
    candidate_payload,
    promote_review,
    query_guidance,
    record_review,
)
from autoaxe.infrastructure.event_store import persist_event, query_events
from autoaxe.infrastructure.market_store import PermissionDenied, gate, ingest, set_permission
from autoaxe.infrastructure.official_quota import reserve_bls_v1
from autoaxe.infrastructure.sessions import authorize, create_session, revoke, rotate

IMAGE = "postgres:17@sha256:87c8b42f423b45d5247e6aa8fdb2e7762fec164c68a50fe3eb07e7bfcaf4dbcf"


@pytest.mark.integration
def test_sessions_scraper_permissions_and_quarantine(monkeypatch):
    monkeypatch.setenv("AUTOAXE_DISPOSABLE_DB", "true")
    monkeypatch.delenv("AUTOAXE_OWNER_SUBJECT_REF", raising=False)
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
            from autoaxe.application.official_poll import reserve

            with pytest.raises(PermissionDenied):
                reserve(conn, "ecb_dfr")
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            set_permission(
                conn,
                "ecb",
                approved=True,
                evidence="synthetic official scheduler fixture",
                fetch=True,
                storage=True,
            )
        with psycopg.connect(market) as conn:
            assert reserve(conn, "ecb_dfr") is not None
            assert reserve(conn, "ecb_dfr") is None
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
        def never_fetch(_permit):
            raise AssertionError("must not request source")

        assert poll_once(market, never_fetch) == "permission_required"
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
            pizza_lease = claim(conn, source="pizzint")
            assert pizza_lease is not None and pizza_lease.job_id == api_job
            doughcon = {
                "series_id": "PENTAGON_PIZZA_PIZZINT",
                "value": "5",
                "source_event_at": datetime.now(UTC).isoformat(),
                "quality": "manual_review_required",
                "automated_trading_allowed": False,
            }
            for bad in (
                [],
                [{**doughcon, "value": "0"}],
                [{**doughcon, "data": [{"name": "must not persist"}]}],
                [{**doughcon, "automated_trading_allowed": True}],
                [{**doughcon, "source_event_at": "2026-11-27T00:00:00"}],
                [doughcon, doughcon],
            ):
                with pytest.raises(ValueError):
                    complete(
                        conn, api_job, "pizzint", pizza_lease.lease_token, pizza_lease.nonce, bad
                    )
            assert (
                complete(
                    conn, api_job, "pizzint", pizza_lease.lease_token, pizza_lease.nonce, [doughcon]
                )
                == "quarantined"
            )
            saved = conn.execute(
                "SELECT payload FROM ops.scrape_results WHERE job_id=%s", (api_job,)
            ).fetchone()[0]
            assert saved["candidates"] == [doughcon]
            with pytest.raises(PermissionDenied, match="informational only"):
                gate(conn, "PENTAGON_PIZZA_PIZZINT", "trading")
            with pytest.raises(PermissionDenied, match="retired"):
                gate(conn, "PENTAGON_PIZZA")
            pizza_at = datetime.now(UTC)
            for wrong_value, metadata in (
                ("0", {}),
                ("6", {}),
                ("5", {"data": "must not persist"}),
            ):
                with pytest.raises(ValueError, match="only the level"):
                    ingest(
                        conn,
                        Candidate(
                            "PENTAGON_PIZZA_PIZZINT",
                            "reject-extra",
                            wrong_value,
                            pizza_at,
                            pizza_at,
                            pizza_at,
                            metadata=metadata,
                        ),
                    )

        # Dedicated schedule: source time identity, restart safety and durable cooldown.
        calls = 0

        def valid_fetch(permit):
            nonlocal calls
            calls += 1
            permit()
            assert poll_once(market, never_fetch) == "busy"
            permit()
            return doughcon

        def due():
            # Accelerate only the isolated test DB's last reservation, not wall time.
            with psycopg.connect(market) as conn:
                conn.execute(
                    "UPDATE ops.poll_slots SET last_enqueued_at=clock_timestamp() "
                    "- interval '301 seconds' WHERE series_id=%s",
                    (SERIES,),
                )

        assert poll_once(market, valid_fetch) == "stored"
        assert poll_once(market, never_fetch) == "not_due"
        due()
        assert poll_once(market, valid_fetch) == "no_update"
        assert calls == 2
        due()

        def limited(_permit):
            raise FetchError(429, "900")

        assert poll_once(market, limited) == "http_error"
        due()
        assert poll_once(market, never_fetch) == "cooldown"
        with psycopg.connect(market) as conn:
            assert conn.execute(
                "SELECT retry_at > clock_timestamp()+interval '800 seconds' "
                "FROM ops.poll_circuits WHERE source_id='pizzint'"
            ).fetchone()[0]
            conn.execute(
                "UPDATE ops.poll_circuits SET retry_at=clock_timestamp()-interval '1 second' "
                "WHERE source_id='pizzint'"
            )

        def denied(_permit):
            raise FetchError(403)

        assert poll_once(market, denied) == "http_error"
        due()
        assert poll_once(market, never_fetch) == "cooldown"

        def approve_pizza(approved):
            with psycopg.connect(admin, dbname="autoaxe_market") as conn:
                set_permission(
                    conn,
                    "pizzint",
                    approved=approved,
                    evidence="synthetic polling test",
                    fetch=approved,
                    storage=approved,
                )

        approve_pizza(True)

        def revoked_during_fetch(permit):
            permit()
            approve_pizza(False)
            return {**doughcon, "value": "1"}

        assert poll_once(market, revoked_during_fetch) == "permission_changed"
        assert poll_once(market, never_fetch) == "permission_required"
        approve_pizza(True)
        with psycopg.connect(market) as conn:
            assert (
                conn.execute(
                    "SELECT count(*) FROM market.observations WHERE series_id=%s", (SERIES,)
                ).fetchone()[0]
                == 1
            )
            assert (
                conn.execute(
                    "SELECT frequency FROM catalog.series WHERE series_id=%s", (SERIES,)
                ).fetchone()[0]
                == "5m"
            )

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
        # Owner-only access is a project invariant, not an optional UI mode.
        monkeypatch.setenv(
            "AUTOAXE_OWNER_SUBJECT_REF",
            "https://idp.example/realms/a|someone-else",
        )
        still_blocked = api.get(
            "/api/v1/dashboard/official-events",
            cookies={"__Host-autoaxe-sid": authenticated_sid},
        )
        assert still_blocked.status_code == 200 and still_blocked.json()["data"] == []
        monkeypatch.setenv(
            "AUTOAXE_OWNER_SUBJECT_REF",
            "https://idp.example/realms/a|fixture-1",
        )
        personal = api.get(
            "/api/v1/dashboard/official-events",
            cookies={"__Host-autoaxe-sid": authenticated_sid},
        )
        assert personal.status_code == 200 and personal.json()["data"][0]["actual"] == "321.5"
        monkeypatch.delenv("AUTOAXE_OWNER_SUBJECT_REF")
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
        schedule_seen = datetime.now(UTC) - timedelta(days=3)
        schedule = EventRevision(
            "fixture-cpi-calendar",
            "bls",
            schedule_seen + timedelta(days=1),
            None,
            schedule_seen,
            schedule_seen,
            None,
            None,
            None,
            "event",
            1,
            "https://www.bls.gov/schedule/",
            CalendarEvidence("Consumer Price Index for October 2026", None, "confirmed"),
        )
        with psycopg.connect(market) as conn:
            persist_event(conn, schedule)
        monkeypatch.setenv("AUTOAXE_OWNER_SUBJECT_REF", "https://idp.example/realms/a|fixture-1")
        linked = api.get(
            "/api/v1/dashboard/official-events",
            cookies={"__Host-autoaxe-sid": authenticated_sid},
            params={"source_id": "bls"},
        )
        assert linked.status_code == 200
        linked_actual = next(r for r in linked.json()["data"] if r["event_key"] == "US_CPI:2026-10")
        assert linked_actual["link_status"] == "period_match"
        assert linked_actual["period_match"]["event_key"] == "fixture-cpi-calendar"
        assert linked_actual["scheduled_at"] is None and linked_actual["released_at"] is None
        # Rule estimates require no OCC/CME source grant and never assert
        # verified active contracts. The explicit candidate remains the key.
        expiry = api.get(
            "/api/v1/dashboard/expiry-calendar",
            cookies={"__Host-autoaxe-sid": authenticated_sid},
            params={"candidate_date": "2027-06-18"},
        )
        assert expiry.status_code == 200
        assert expiry.json()["projection"]["estimated_date"] == "2027-06-17"
        assert expiry.json()["evidence"] == []
        assert expiry.json()["sessions"][0]["event_type"] == "PENDING_VERIFICATION"
        automatic = api.get(
            "/api/v1/dashboard/expiry-calendar",
            cookies={"__Host-autoaxe-sid": authenticated_sid},
        )
        assert automatic.status_code == 200
        automatic_body = automatic.json()
        assert (
            automatic_body["meta"]["candidate_date"] == automatic_body["projection"]["nominal_date"]
        )
        monkeypatch.delenv("AUTOAXE_OWNER_SUBJECT_REF")
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
        with psycopg.connect(market) as conn:
            db_clock = conn.execute("SELECT clock_timestamp()").fetchone()
            assert db_clock is not None
            now = min(datetime.now(UTC), db_clock[0]) - timedelta(seconds=2)
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
        monkeypatch.setenv(
            "AUTOAXE_OWNER_SUBJECT_REF",
            "https://idp.example/realms/a|fixture-1",
        )
        personal_market = api.get(route, cookies={"__Host-autoaxe-sid": authenticated_sid})
        assert personal_market.status_code == 200
        assert personal_market.json()["data"][0]["value"] == "23.45"
        assert personal_market.json()["meta"]["permission"] == "approved_personal_education"
        snapshot_route = "/api/v1/dashboard/authorized/snapshot"
        assert api.get(snapshot_route).status_code == 401
        snapshot_response = api.get(
            snapshot_route, cookies={"__Host-autoaxe-sid": authenticated_sid}
        )
        assert snapshot_response.status_code == 200
        payload = snapshot_response.json()
        assert payload["meta"]["mode"] == "market_read"
        assert payload["meta"]["versions"]["VIX"] == 1
        points = {row["series_id"]: row for row in payload["data"]}
        assert points["VIX"]["value"] == "23.45"
        assert "FIXTURE_PRICE" not in points
        initial = read_snapshot(authenticated_sid, "test", touch=False)
        with psycopg.connect(market) as conn:
            db_clock = conn.execute("SELECT clock_timestamp()").fetchone()
            assert db_clock is not None
            clock = min(datetime.now(UTC), db_clock[0]) - timedelta(seconds=1)
            ingest(conn, Candidate("VIX", "intermediate-tick", "24.0", clock, clock, clock))
            ingest(conn, Candidate("VIX", "next-tick", "24.5", clock, clock, clock))
        after_tick = read_snapshot(authenticated_sid, "test", touch=False, previous=initial)
        assert after_tick.snapshot.meta.versions["VIX"] == 3
        assert after_tick.replay == (("VIX", 2), ("VIX", 3))
        deltas = changes(initial, after_tick)
        assert len(deltas) == 2
        assert all(event.startswith("event: market.invalidate\n") for event in deltas)
        assert '"aggregate_version":2' in deltas[0]
        assert '"aggregate_version":3' in deltas[1]
        assert "version_gap" in changes(initial, replace(after_tick, replay=()))[0]
        pizza_route = "/api/v1/dashboard/authorized/market/" + SERIES
        assert api.get(pizza_route).status_code == 401
        pizza_read = api.get(pizza_route, cookies={"__Host-autoaxe-sid": authenticated_sid})
        assert pizza_read.status_code == 200
        assert len(pizza_read.json()["data"]) == 1
        assert pizza_read.json()["data"][0]["value"] == "5"
        assert pizza_read.json()["data"][0]["quality"] == "manual_unverified"
        assert pizza_read.json()["meta"]["collector_status"] == "blocked"
        # Personal viewing cannot enable a public endpoint or allow anonymous access.
        assert api.get(route).status_code == 401
        monkeypatch.delenv("AUTOAXE_OWNER_SUBJECT_REF")
        after_owner_change = read_snapshot(authenticated_sid, "test", touch=False)
        assert "VIX" not in after_owner_change.snapshot.meta.versions
        assert changes(after_tick, after_owner_change)[0].startswith("event: resync\n")
        assert api.get(route, cookies={"__Host-autoaxe-sid": authenticated_sid}).status_code == 403
        assert (
            api.get(pizza_route, cookies={"__Host-autoaxe-sid": authenticated_sid}).status_code
            == 403
        )
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
        assert [point["value"] for point in allowed.json()["data"][:2]] == ["24.5", "24"]
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
        assert (
            "VIX"
            not in read_snapshot(authenticated_sid, "test", touch=False).snapshot.meta.versions
        )
        # Official source document reviews are separate from runtime ingestion.
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            db_now = conn.execute("SELECT clock_timestamp()").fetchone()[0]
            captured = min(datetime.now(UTC), db_now) - timedelta(minutes=2)
            for source in ("boj", "sec_edgar"):
                set_permission(
                    conn,
                    source,
                    approved=True,
                    evidence="fixture document review",
                    fetch=True,
                    storage=True,
                    redistribution=False,
                )
        policy = extract_boj_policy(
            "Bank of Japan\n\nThe board adopted the guideline for market operations.\n\n"
            "The Bank will encourage the uncollateralized overnight call rate "
            "to remain at around 0 to 0.1 percent.",
            "https://www.boj.or.jp/en/mopo/mpmdeci/state_2024/k240319a.htm",
            captured,
        )
        company = extract_guidance(
            "FY2027Q2 GAAP revenue outlook: 10 to 12 USD billion.",
            "https://www.sec.gov/Archives/edgar/data/1045810/000104581024000113/exhibit.htm",
            "0001045810",
            "0001045810-24-000113",
            captured,
        )
        calls = []

        def captured_document(permit):
            permit()
            calls.append("capture")
            return company

        assert capture_once(market, "sec_edgar", captured_document) == company
        with pytest.raises(PermissionDenied, match="not due"):
            capture_once(market, "sec_edgar", captured_document)
        assert calls == ["capture"]
        with psycopg.connect(market) as conn:
            ver = conn.execute(
                "SELECT permission_version FROM catalog.source_registry WHERE source_id='sec_edgar'"
            ).fetchone()[0]
            scan = Scan(
                "0001045810",
                DocumentCapture(
                    "sec_edgar",
                    "0001045810:test",
                    company.source_url,
                    "a" * 64,
                    "unparsed synthetic exhibit",
                    captured,
                    None,
                    "review_required",
                ),
            )
            save_scan(conn, "sec_edgar", scan, ver)
            save_scan(conn, "sec_edgar", scan, ver)
            assert (
                conn.execute("SELECT count(*) FROM ops.official_document_inbox").fetchone()[0] == 1
            )
            with pytest.raises(PermissionDenied):
                save_scan(conn, "sec_edgar", scan, ver + 1)
        with psycopg.connect(market_read) as conn:
            with pytest.raises(InsufficientPrivilege):
                conn.execute("SELECT * FROM ops.official_document_inbox")
        with psycopg.connect(market_read) as conn:
            cutoff = conn.execute("SELECT clock_timestamp()").fetchone()[0]
            assert query_guidance(conn, cutoff=cutoff, private_use=True) == []

        def denied_document(permit):
            permit()
            raise OfficialSourceError("synthetic access denial", status=403)

        with pytest.raises(OfficialSourceError):
            capture_once(market, "boj", denied_document)
        with pytest.raises(PermissionDenied, match="circuit open"):
            capture_once(market, "boj", captured_document)
        with psycopg.connect(market) as conn:
            with pytest.raises(InsufficientPrivilege):
                record_review(
                    conn,
                    company,
                    expected_hash=canonical_sha256(candidate_payload(company)),
                    reviewer_ref="fixture",
                    evidence_ref="fixture",
                )
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            with pytest.raises(ValueError, match="hash changed"):
                record_review(
                    conn,
                    company,
                    expected_hash="0" * 64,
                    reviewer_ref="fixture",
                    evidence_ref="fixture",
                )
            company_review = record_review(
                conn,
                company,
                expected_hash=canonical_sha256(candidate_payload(company)),
                reviewer_ref="fixture reviewer",
                evidence_ref="synthetic filing exhibit",
            )
            policy_review = record_review(
                conn,
                policy,
                expected_hash=canonical_sha256(candidate_payload(policy)),
                reviewer_ref="fixture reviewer",
                evidence_ref="synthetic decision",
            )
        with psycopg.connect(market_read) as conn:
            before_promotion = conn.execute("SELECT clock_timestamp()").fetchone()[0]
            assert query_guidance(conn, cutoff=before_promotion, private_use=True) == []
        with psycopg.connect(market) as conn:
            assert promote_review(conn, company_review) == "promoted"
            assert promote_review(conn, company_review) == "duplicate"
            assert promote_review(conn, policy_review) == "promoted"
        with psycopg.connect(market_read) as conn:
            cutoff = conn.execute("SELECT clock_timestamp()").fetchone()[0]
            assert query_guidance(conn, cutoff=before_promotion, private_use=True) == []
            assert query_guidance(conn, cutoff=cutoff, private_use=False) == []
            assert query_guidance(conn, cutoff=cutoff, private_use=True)[0]["low"] == 10_000_000_000
            rows = query_events(conn, cutoff=cutoff, source_id="boj", private_use=True)
            assert {r.event_key: r.actual for r in rows} == {
                "BOJ_POLICY_TARGET_LOWER:2024-03-19": "0",
                "BOJ_POLICY_TARGET_UPPER:2024-03-19": "0.1",
            }
        guidance_route = "/api/v1/dashboard/corporate-guidance"
        assert api.get(guidance_route).status_code == 401
        assert (
            api.get(guidance_route, cookies={"__Host-autoaxe-sid": authenticated_sid}).json()[
                "data"
            ]
            == []
        )
        monkeypatch.setenv("AUTOAXE_OWNER_SUBJECT_REF", "https://idp.example/realms/a|fixture-1")
        assert (
            api.get(guidance_route, cookies={"__Host-autoaxe-sid": authenticated_sid}).json()[
                "data"
            ][0]["basis"]
            == "GAAP"
        )
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            set_permission(
                conn,
                "sec_edgar",
                approved=False,
                evidence="fixture revoke",
                fetch=False,
                storage=False,
            )
        assert (
            api.get(guidance_route, cookies={"__Host-autoaxe-sid": authenticated_sid}).json()[
                "data"
            ]
            == []
        )
        with psycopg.connect(market) as conn:
            with pytest.raises(PermissionDenied):
                promote_review(conn, company_review)

        # MEXC remains a separate, opt-in REST snapshot with UNKNOWN quality.
        async def no_mexc(_permit):
            raise AssertionError("must not request MEXC")

        assert asyncio.run(poll_mexc(market, no_mexc, enabled=True)) == "permission_required"
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            set_permission(
                conn,
                "mexc",
                approved=True,
                evidence="synthetic MEXC grant",
                fetch=True,
                storage=True,
                redistribution=False,
            )
        mexc_now = datetime.now(UTC) - timedelta(seconds=5)
        item = Candidate(
            MEXC_SERIES,
            str(int(mexc_now.timestamp() * 1000)),
            "28000.1",
            mexc_now,
            mexc_now,
            mexc_now,
            Quality.UNKNOWN,
            {
                "symbol": "NAS100_USDT",
                "instrument_type": "index_linked_perpetual",
                "quote_currency": "USDT",
                "settlement_currency": "USDT",
                "contract_id": 123,
                "contract_size": "0.01",
                "price_unit": "0.1",
                "provenance": "mexc_futures_rest_candidate",
                "session_verified": False,
                "live_verified": False,
            },
        )

        async def fetch_mexc(permit):
            permit()
            assert await poll_mexc(market, no_mexc, enabled=True) == "busy"
            permit()
            return item

        assert asyncio.run(poll_mexc(market, fetch_mexc, enabled=True)) == "stored"
        assert asyncio.run(poll_mexc(market, no_mexc, enabled=True)) == "not_due"
        with psycopg.connect(market) as conn:
            conn.execute(
                "UPDATE ops.poll_slots SET last_enqueued_at=clock_timestamp() "
                "- interval '301 seconds' WHERE series_id=%s",
                (MEXC_SERIES,),
            )
        assert asyncio.run(poll_mexc(market, fetch_mexc, enabled=True)) == "no_update"
        with psycopg.connect(market_read) as conn:
            assert conn.execute(
                "SELECT quality,count(*) FROM market.observations WHERE series_id=%s "
                "GROUP BY quality",
                (MEXC_SERIES,),
            ).fetchall() == [("unknown", 1)]
        mexc_snapshot = read_snapshot(authenticated_sid, "test", touch=False).snapshot
        assert mexc_snapshot.meta.versions[MEXC_SERIES] == 1
        assert (
            next(p for p in mexc_snapshot.data if p.series_id == MEXC_SERIES).quality == "unknown"
        )
        ws_item = replace(
            item,
            series_id=MEXC_WS_SERIES,
            metadata={
                **item.metadata,
                "provenance": "mexc_futures_protobuf_ticker",
                "schema_commit": SCHEMA_COMMIT,
                "timestamp_semantics": "provider_ticker_timestamp",
            },
        )

        async def ws_fixture(permit):
            permit()
            yield ws_item

        assert asyncio.run(run_session(market, ws_fixture, enabled=True)) == "stored"
        assert asyncio.run(run_session(market, ws_fixture, enabled=True)) == "not_due"
        with psycopg.connect(market) as conn:
            with pytest.raises(PermissionDenied, match="informational only"):
                gate(conn, MEXC_WS_SERIES, "trading")
            assert (
                conn.execute(
                    "SELECT count(*) FROM market.observations WHERE series_id=%s", (MEXC_WS_SERIES,)
                ).fetchone()[0]
                == 1
            )

        # Dedicated QQQ REST ledger is distinct from MEXC, generic futures and CME NQ.
        assert asyncio.run(poll_qqq(market, no_mexc, enabled=True)) == "permission_required"
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            set_permission(
                conn,
                "binance_futures",
                approved=True,
                evidence="synthetic QQQ fixture grant",
                fetch=True,
                storage=True,
                redistribution=False,
            )
        qqq = Candidate(
            QQQ_SERIES,
            "fixture-qqq",
            "612.34",
            mexc_now,
            mexc_now,
            mexc_now,
            Quality.UNKNOWN,
            {
                "symbol": "QQQUSDT",
                "instrument_type": "etf_linked_perpetual",
                "underlying": "Invesco QQQ Trust Series 1",
                "quote_currency": "USDT",
                "settlement_currency": "USDT",
                "price_unit": "0.01",
                "provenance": "binance_qqq_rest_candidate",
                "session_verified": False,
                "live_verified": False,
            },
        )

        async def fetch_qqq(permit):
            permit()
            assert await poll_qqq(market, no_mexc, enabled=True) == "busy"
            return qqq

        assert asyncio.run(poll_qqq(market, fetch_qqq, enabled=True)) == "stored"
        assert asyncio.run(poll_qqq(market, no_mexc, enabled=True)) == "not_due"
        with psycopg.connect(market) as conn:
            conn.execute(
                "UPDATE ops.poll_slots SET last_enqueued_at=clock_timestamp() "
                "- interval '301 seconds' WHERE series_id=%s",
                (QQQ_SERIES,),
            )
        assert asyncio.run(poll_qqq(market, fetch_qqq, enabled=True)) == "no_update"
        qqq_state = read_snapshot(authenticated_sid, "test", touch=False).snapshot
        assert qqq_state.meta.versions[QQQ_SERIES] == 1
        assert qqq_state.meta.versions[MEXC_SERIES] == 1
        assert next(p for p in qqq_state.data if p.series_id == QQQ_SERIES).quality == "unknown"

        # BEA subscription uses a separate durable reservation and same-source PIT linkage.
        bea_seen = captured
        bea_calendar = EventRevision(
            "fixture-bea-pce",
            "bea",
            bea_seen - timedelta(days=1),
            None,
            bea_seen,
            bea_seen,
            None,
            None,
            None,
            "event",
            1,
            BEA_ICS,
            CalendarEvidence("Personal Income and Outlays, October 2026", None, "confirmed"),
        )
        bea_actual = EventRevision(
            "US_PCE:2026M10",
            "bea",
            None,
            None,
            bea_seen,
            bea_seen,
            "0.2",
            None,
            None,
            "percent_mom",
            1,
            "https://www.bea.gov/news/",
        )
        calendar_calls = []

        def fetch_bea(permit):
            permit()
            calendar_calls.append(1)
            return [bea_calendar]

        assert poll_official(market, "bea_calendar", fetch_bea) == "blocked"
        assert calendar_calls == []
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            set_permission(
                conn,
                "bea",
                approved=True,
                evidence="synthetic BEA fixture grant",
                fetch=True,
                storage=True,
                redistribution=False,
            )
        assert poll_official(market, "bea_calendar", fetch_bea) == "stored"
        assert poll_official(market, "bea_calendar", fetch_bea) == "not_due"
        assert calendar_calls == [1]
        with psycopg.connect(market) as conn:
            persist_event(conn, bea_actual)
        bea_response = api.get(
            "/api/v1/dashboard/official-events",
            params={"source_id": "bea"},
            cookies={"__Host-autoaxe-sid": authenticated_sid},
        )
        assert bea_response.status_code == 200
        bea_row = next(r for r in bea_response.json()["data"] if r["actual"] is not None)
        assert bea_row["period_match"]["event_key"] == "fixture-bea-pce"
        assert bea_row["released_at"] is None
        with psycopg.connect(app_runtime) as conn:
            revoke(conn, authenticated_sid)
        assert (
            api.get(snapshot_route, cookies={"__Host-autoaxe-sid": authenticated_sid}).status_code
            == 401
        )
