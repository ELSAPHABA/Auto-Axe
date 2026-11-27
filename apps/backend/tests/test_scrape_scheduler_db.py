"""Real PostgreSQL tests; no provider requests and no real adapter grants."""

import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from psycopg.errors import InsufficientPrivilege
from psycopg.types.json import Jsonb
from testcontainers.postgres import PostgresContainer

from autoaxe.application.scrape_broker import (
    SERIES,
    claim,
    complete,
    fail,
    heartbeat,
    promote_reviewed,
    schedule_due,
    submit,
)
from autoaxe.infrastructure.db_bootstrap import provision
from autoaxe.infrastructure.market_store import PermissionDenied, set_permission

IMAGE = "postgres:17@sha256:87c8b42f423b45d5247e6aa8fdb2e7762fec164c68a50fe3eb07e7bfcaf4dbcf"


@pytest.mark.integration
def test_generic_scheduler_and_review_fences(monkeypatch):
    monkeypatch.setenv("AUTOAXE_DISPOSABLE_DB", "true")
    secret = secrets.token_urlsafe(24)
    with PostgresContainer(
        IMAGE, username="fixture_admin", password=secret, dbname="postgres"
    ) as pg:
        opts = dict(host=pg.get_container_host_ip(), port=pg.get_exposed_port(5432))
        admin = psycopg.conninfo.make_conninfo(
            **opts, dbname="postgres", user="fixture_admin", password=secret
        )
        passwords = provision(admin, Path(__file__).resolve().parents[1] / "alembic.ini")
        market = psycopg.conninfo.make_conninfo(
            **opts,
            dbname="autoaxe_market",
            user="autoaxe_market_runtime",
            password=passwords["autoaxe_market_runtime"],
        )

        def grant(source, *, adapter=True):
            with psycopg.connect(admin, dbname="autoaxe_market") as conn:
                set_permission(
                    conn,
                    source,
                    approved=True,
                    evidence="synthetic permission test only",
                    fetch=True,
                    storage=True,
                )
                version = conn.execute(
                    "SELECT permission_version FROM catalog.source_registry WHERE source_id=%s",
                    (source,),
                ).fetchone()[0]
                if adapter:
                    conn.execute(
                        """INSERT INTO ops.scrape_adapter_grants
                        (source_id,permission_version,adapter_version,schema_version,mapping_versions,interval_seconds,evidence_ref)
                        VALUES (%s,%s,1,1,%s,%s,'synthetic DOM contract test only')""",
                        (
                            source,
                            version,
                            Jsonb(dict.fromkeys(SERIES[source], 1)),
                            86400 if source == "dramexchange" else 300,
                        ),
                    )
                return version

        def tick(source):
            with psycopg.connect(market) as conn:
                return schedule_due(conn, source)

        def lease(source):
            with psycopg.connect(market) as conn:
                item = claim(conn, source=source, scheduled_only=True)
                assert item is not None
                return item

        def reset_due(source):
            with psycopg.connect(admin, dbname="autoaxe_market") as conn:
                conn.execute(
                    "UPDATE ops.scrape_schedule SET next_due_at=clock_timestamp()"
                    "-interval '1 second' "
                    "WHERE source_id=%s",
                    (source,),
                )

        def quarantine(item, candidates):
            with psycopg.connect(market) as conn:
                assert (
                    complete(
                        conn, item.job_id, item.source_id, item.lease_token, item.nonce, candidates
                    )
                    == "quarantined"
                )

        def review(item, units, *, hash_override=None, decision="checked"):
            with psycopg.connect(admin, dbname="autoaxe_market") as conn:
                # Docker VM and Windows host clocks can differ. Use known
                # host-side fixture times, leaving the production future-time
                # fence unchanged.
                reviewed_at = datetime.now(UTC)
                conn.execute(
                    "UPDATE ops.scrape_results SET submitted_at=%s WHERE job_id=%s",
                    (reviewed_at - timedelta(seconds=1), item.job_id),
                )
                result_hash = conn.execute(
                    "SELECT result_hash FROM ops.scrape_results WHERE job_id=%s", (item.job_id,)
                ).fetchone()[0]
                conn.execute(
                    """INSERT INTO ops.scrape_reviews
                    (job_id,result_hash,decision,reviewer_ref,evidence_ref,units,reviewed_at)
                    VALUES (%s,%s,%s,'synthetic reviewer','synthetic evidence',%s,%s)""",
                    (
                        item.job_id,
                        hash_override or result_hash,
                        decision,
                        Jsonb(units),
                        reviewed_at,
                    ),
                )

        assert tick("naver") == "blocked"
        grant("naver", adapter=False)
        assert tick("naver") == "blocked"
        with psycopg.connect(market) as conn:
            with pytest.raises(InsufficientPrivilege):
                conn.execute("INSERT INTO ops.scrape_adapter_grants(source_id) VALUES ('naver')")
        with psycopg.connect(market) as conn:
            deadline = conn.execute("SELECT clock_timestamp()+interval '3 minutes'").fetchone()[0]
            legacy = submit(conn, "naver", {}, "legacy-fixture", deadline)
        with psycopg.connect(market) as conn:
            with pytest.raises(PermissionDenied):
                claim(conn, source="naver", scheduled_only=True)
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            conn.execute(
                "UPDATE ops.scrape_jobs SET deadline_at=clock_timestamp()-interval '1 second' "
                "WHERE id=%s",
                (legacy,),
            )
        version = grant("naver")
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(tick, ["naver", "naver"])) == ["not_due", "scheduled"]
        first = lease("naver")
        assert first.permission_version == version
        assert tick("naver") == "not_due"
        with psycopg.connect(market) as conn:
            assert claim(conn, source="naver", scheduled_only=True) is None
            assert heartbeat(conn, first.job_id, first.lease_token, first.nonce)
            with pytest.raises(PermissionDenied):
                fail(
                    conn,
                    first.job_id,
                    "naver",
                    "forged-token",
                    first.nonce,
                    reason="http",
                    http_status=429,
                    retry_header="900",
                )
            assert (
                fail(
                    conn,
                    first.job_id,
                    "naver",
                    first.lease_token,
                    first.nonce,
                    reason="http",
                    http_status=429,
                    retry_header="900",
                )
                == "failed"
            )
            delay = conn.execute(
                "SELECT extract(epoch FROM retry_at-clock_timestamp()) "
                "FROM ops.poll_circuits WHERE source_id='naver'"
            ).fetchone()[0]
            assert 890 < delay <= 900
        reset_due("naver")
        assert tick("naver") == "blocked"  # Retry-After survives scheduler restart.
        grant("naver")  # A new independently verified version, fixture only.
        assert tick("naver") == "blocked"
        # Simulate elapsed time in the disposable fixture only.
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            conn.execute(
                "UPDATE ops.poll_circuits SET retry_at=clock_timestamp() WHERE source_id='naver'"
            )
        assert tick("naver") == "scheduled"
        second = lease("naver")
        stamp = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
        candidate = {
            "series_id": "UST_2Y_NAVER",
            "value": "4.2",
            "source_event_at": stamp,
            "quality": "manual_review_required",
        }
        with psycopg.connect(market) as conn:
            with pytest.raises(ValueError):
                complete(
                    conn,
                    second.job_id,
                    "naver",
                    second.lease_token,
                    second.nonce,
                    [{**candidate, "series_id": "VIX"}],
                )
        quarantine(second, [candidate])
        with psycopg.connect(market) as conn:
            with pytest.raises(PermissionDenied):
                promote_reviewed(conn, second.job_id)
            assert (
                conn.execute(
                    "SELECT count(*) FROM market.observations WHERE series_id='UST_2Y_NAVER'"
                ).fetchone()[0]
                == 0
            )
            with pytest.raises(InsufficientPrivilege):
                conn.execute("INSERT INTO ops.scrape_reviews(job_id) VALUES (%s)", (second.job_id,))
        review(second, {"UST_2Y_NAVER": "percent"})
        with psycopg.connect(market) as conn:
            assert promote_reviewed(conn, second.job_id) == "promoted"
            assert promote_reviewed(conn, second.job_id) == "duplicate"
            value, quality, metadata, source_at, received, available = conn.execute(
                "SELECT value,quality,metadata,source_event_at,received_at,available_at "
                "FROM market.observations WHERE series_id='UST_2Y_NAVER'"
            ).fetchone()
            assert str(value) == "4.2" and quality == "manual_checked"
            assert metadata == {"automated_trading_allowed": False}
            assert source_at == datetime.fromisoformat(stamp) < received <= available
            assert (
                conn.execute(
                    "SELECT count(*) FROM ops.outbox WHERE envelope->>'series_id'='UST_2Y_NAVER'"
                ).fetchone()[0]
                == 1
            )
        reset_due("naver")
        assert tick("naver") == "scheduled"
        third = lease("naver")
        quarantine(third, [candidate])
        review(third, {"UST_2Y_NAVER": "percent"}, hash_override="a" * 64)
        with psycopg.connect(market) as conn:
            with pytest.raises(PermissionDenied, match="hash mismatch"):
                promote_reviewed(conn, third.job_id)
        reset_due("naver")
        assert tick("naver") == "scheduled"
        fourth = lease("naver")
        quarantine(fourth, [candidate])
        review(fourth, {"UST_2Y_NAVER": "percent"})
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            set_permission(
                conn,
                "naver",
                approved=False,
                evidence="synthetic revocation",
                fetch=False,
                storage=False,
            )
        with psycopg.connect(market) as conn:
            with pytest.raises(PermissionDenied):
                promote_reviewed(conn, fourth.job_id)

        grant("cnn")
        assert tick("cnn") == "scheduled"
        cnn = lease("cnn")
        quarantine(
            cnn,
            [
                {
                    "series_id": "CNN_FEAR_GREED_CNN",
                    "value": "65",
                    "source_event_at": None,
                    "quality": "manual_review_required",
                    "category": "Greed",
                    "automated_trading_allowed": False,
                }
            ],
        )
        review(cnn, {"CNN_FEAR_GREED_CNN": "index"})
        with psycopg.connect(market) as conn:
            assert promote_reviewed(conn, cnn.job_id) == "promoted"
            assert conn.execute(
                "SELECT source_event_at,quality FROM market.observations "
                "WHERE series_id='CNN_FEAR_GREED_CNN'"
            ).fetchone() == (None, "manual_checked")
        reset_due("cnn")
        assert tick("cnn") == "scheduled"
        expired = lease("cnn")
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            conn.execute(
                "UPDATE ops.scrape_jobs SET lease_expires_at=clock_timestamp()-interval '1 second' "
                "WHERE id=%s",
                (expired.job_id,),
            )
        assert tick("cnn") == "not_due"
        with psycopg.connect(market) as conn:
            assert (
                conn.execute(
                    "SELECT status FROM ops.scrape_jobs WHERE id=%s", (expired.job_id,)
                ).fetchone()[0]
                == "failed"
            )
            assert (
                conn.execute(
                    "SELECT status FROM ops.collector_health WHERE series_id='CNN_FEAR_GREED_CNN'"
                ).fetchone()[0]
                == "unknown"
            )
            assert claim(conn, source="cnn", scheduled_only=True) is None
        grant("dramexchange")
        assert tick("dramexchange") == "scheduled"
        dram = lease("dramexchange")
        dram_candidates = [
            {
                "series_id": sid,
                "item": label,
                "value": "12.3",
                "source_event_at": stamp,
                "quality": "manual_review_required",
                "unit": None,
                "unit_verified": False,
                "source_id": "dramexchange",
            }
            for sid, label in zip(
                SERIES["dramexchange"],
                ("DDR5 UDIMM 16GB 4800/5600", "DDR5 RDIMM 32GB 4800/5600"),
                strict=True,
            )
        ]
        quarantine(dram, dram_candidates)
        review(dram, dict.fromkeys(SERIES["dramexchange"], "USD/module"))
        with psycopg.connect(market) as conn:
            with pytest.raises(PermissionDenied, match="verified source units"):
                promote_reviewed(conn, dram.job_id)
            assert (
                conn.execute(
                    "SELECT count(*) FROM market.observations "
                    "WHERE series_id LIKE 'DRAM_DDR5_%_AUTO'"
                ).fetchone()[0]
                == 0
            )
            with pytest.raises(ValueError):
                schedule_due(conn, "pizzint")
