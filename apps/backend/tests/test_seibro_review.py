"""Real PostgreSQL review fences; every source grant/data value is synthetic."""

import secrets
from datetime import date, timedelta
from pathlib import Path

import psycopg
import pytest
from psycopg.errors import InsufficientPrivilege
from testcontainers.postgres import PostgresContainer

from autoaxe.adapters.authorized_seibro import read_top50
from autoaxe.application.scrape_broker import permission
from autoaxe.application.seibro_review import URL, normalize_capture, promote_capture, stage_capture
from autoaxe.infrastructure.db_bootstrap import provision
from autoaxe.infrastructure.market_store import PermissionDenied, set_permission

IMAGE = "postgres:17@sha256:87c8b42f423b45d5247e6aa8fdb2e7762fec164c68a50fe3eb07e7bfcaf4dbcf"


def sample():
    return {
        "source_url": URL,
        "capture_mode": "manual_capture",
        "currency": "USD",
        "settlement_type": "2",
        "country_code": "US",
        "period_code": "1",
        "rank_basis": "4",
        "period_start": None,
        "period_end": None,
        "as_of_date_kst": "2026-11-20",
        "retrieved_at_utc": "2026-11-21T12:00:00Z",
        "top50_coverage": True,
        "rows": [
            {
                "rank": 1,
                "country_name": "미국",
                "isin": "US67066G1040",
                "security_name": "Synthetic",
                "buy_settlement_usd": "100.50",
                "sell_settlement_usd": "200.50",
                "gross_settlement_usd": "301.00",
                "net_buy_settlement_usd": "-100.00",
            }
        ],
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"period_start": "2026-11-15"},
        {"as_of_date_kst": "2099-01-01"},
        {"retrieved_at_utc": "2026-11-21T12:00:00"},
        {"currency": "KRW"},
        {"settlement_type": "1"},
        {"top50_coverage": False},
        {"rows": []},
        {"source_url": "http://localhost"},
        {"capture_mode": "browser"},
    ],
)
def test_bad_scope(overrides):
    with pytest.raises(ValueError):
        normalize_capture(sample() | overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"gross_settlement_usd": "0"},
        {"net_buy_settlement_usd": "100"},
        {"buy_settlement_usd": "NaN"},
        {"rank": 2},
        {"isin": "NVDA"},
        {"country_name": "일본"},
        {"gross_settlement_usd": "1e99"},
        {"rank": True},
    ],
)
def test_bad_row(overrides):
    capture = sample()
    capture["rows"][0].update(overrides)
    with pytest.raises(ValueError):
        normalize_capture(capture)


def test_no_zero_fill_or_cross_rank_merge():
    capture = sample()
    assert normalize_capture(capture)["rows"][0]["net_buy_settlement_usd"] == "-100"
    capture["rows"].append(capture["rows"][0] | {"rank": 2})
    with pytest.raises(ValueError, match="duplicate ISIN"):
        normalize_capture(capture)
    capture["rows"][1].update(
        isin="US0378331005",
        buy_settlement_usd="300.50",
        gross_settlement_usd="501",
        net_buy_settlement_usd="100",
    )
    with pytest.raises(ValueError, match="ranking basis"):
        normalize_capture(capture)


@pytest.mark.integration
def test_reviewed_top50_ledger(monkeypatch):
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
        runtime = psycopg.conninfo.make_conninfo(
            **opts,
            dbname="autoaxe_market",
            user="autoaxe_market_runtime",
            password=passwords["autoaxe_market_runtime"],
        )
        reader = psycopg.conninfo.make_conninfo(
            **opts,
            dbname="autoaxe_market",
            user="autoaxe_market_read",
            password=passwords["autoaxe_market_read"],
        )

        def stage(data):
            with psycopg.connect(runtime) as conn:
                return stage_capture(conn, data)

        def promote(cid):
            with psycopg.connect(runtime) as conn:
                return promote_capture(conn, cid)

        def review(cid, digest, decision="checked"):
            with psycopg.connect(admin, dbname="autoaxe_market") as conn:
                conn.execute(
                    """INSERT INTO ops.seibro_reviews
                    (capture_id,capture_hash,decision,reviewer_ref,evidence_ref)
                    VALUES (%s,%s,%s,'synthetic reviewer','synthetic review only')""",
                    (cid, digest, decision),
                )

        with pytest.raises(PermissionDenied):
            stage(sample())
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            set_permission(
                conn,
                "seibro",
                approved=True,
                evidence="synthetic test only",
                fetch=False,
                storage=True,
            )
        with psycopg.connect(runtime) as conn:
            with pytest.raises(PermissionDenied):
                permission(conn, "seibro")
        with pytest.raises(PermissionDenied, match="fixture"):
            stage(sample() | {"capture_mode": "offline_fixture"})
        cid, digest = stage(sample())
        assert stage(sample()) == (cid, digest)
        with pytest.raises(PermissionDenied):
            promote(cid)
        with psycopg.connect(runtime) as conn:
            assert (
                conn.execute("SELECT count(*) FROM indicators.seibro_top50_snapshots").fetchone()[0]
                == 0
            )
            with pytest.raises(InsufficientPrivilege):
                conn.execute("INSERT INTO ops.seibro_reviews(capture_id) VALUES (%s)", (cid,))
        review(cid, digest)
        state, snapshot = promote(cid)
        assert state == "promoted" and snapshot
        assert promote(cid) == ("duplicate", snapshot)
        with psycopg.connect(runtime) as conn:
            row = conn.execute(
                """SELECT period_start,period_end,quality,top50_coverage,automated_trading_allowed,
                row_count,currency FROM indicators.seibro_top50_snapshots WHERE id=%s""",
                (snapshot,),
            ).fetchone()
            assert row == (None, None, "manual_checked", True, False, 1, "USD")
            amount = conn.execute(
                "SELECT net_buy_settlement_usd FROM indicators.seibro_top50_rows "
                "WHERE snapshot_id=%s",
                (snapshot,),
            ).fetchone()[0]
            assert amount == -100

        def read(*, cutoff=None, basis="4", private=True, day=None):
            with psycopg.connect(reader) as conn:
                conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                now = conn.execute("SELECT transaction_timestamp()").fetchone()[0]
                return read_top50(
                    conn,
                    country_code="US",
                    period_code="1",
                    rank_basis=basis,
                    cutoff=cutoff or now,
                    private_use=private,
                    as_of_date_kst=day,
                )

        first = read()
        assert first is not None and first.snapshot_id == snapshot
        assert first.rows[0].net_buy_settlement_usd == "-100"
        assert read(cutoff=first.available_at - timedelta(microseconds=1)) is None
        assert read(day=date(2026, 11, 19)) is None
        assert read(day=date(2026, 11, 20)) == first
        assert read(basis="1") is None
        with pytest.raises(PermissionDenied):
            read(private=False)
        with psycopg.connect(reader) as conn:
            with pytest.raises(InsufficientPrivilege):
                conn.execute("SELECT * FROM ops.seibro_captures")
        with psycopg.connect(reader) as conn:
            with pytest.raises(InsufficientPrivilege):
                conn.execute("DELETE FROM indicators.seibro_top50_rows")
        again, digest = stage(sample() | {"retrieved_at_utc": "2026-11-21T12:01:00Z"})
        review(again, digest)
        assert promote(again) == ("duplicate", snapshot)
        correction = sample()
        correction["rows"][0].update(
            buy_settlement_usd="110.50", gross_settlement_usd="311", net_buy_settlement_usd="-90"
        )
        corrected, digest = stage(correction)
        review(corrected, digest)
        assert promote(corrected)[0] == "promoted"
        latest = read()
        assert latest is not None and latest.revision == 2
        assert latest.rows[0].net_buy_settlement_usd == "-90"
        assert read(cutoff=first.available_at) == first
        with psycopg.connect(runtime) as conn:
            assert conn.execute(
                "SELECT revision FROM indicators.seibro_top50_snapshots ORDER BY revision"
            ).fetchall() == [(1,), (2,)]
        distinct, digest = stage(sample() | {"rank_basis": "1"})
        review(distinct, digest)
        assert promote(distinct)[0] == "promoted"
        assert read() == latest
        separate = read(basis="1")
        assert separate is not None and separate.rank_basis == "1"
        rejected, digest = stage(sample() | {"period_code": "2"})
        review(rejected, digest, "rejected")
        assert promote(rejected) == ("rejected", None)
        wrong, _ = stage(sample() | {"period_code": "3"})
        review(wrong, "a" * 64)
        with pytest.raises(PermissionDenied, match="hash mismatch"):
            promote(wrong)
        revoked, digest = stage(sample() | {"period_code": "4"})
        review(revoked, digest)
        with psycopg.connect(admin, dbname="autoaxe_market") as conn:
            set_permission(
                conn,
                "seibro",
                approved=False,
                evidence="synthetic revoke",
                fetch=False,
                storage=False,
            )
        with pytest.raises(PermissionDenied):
            promote(revoked)
        with pytest.raises(PermissionDenied):
            stage(sample())
        with pytest.raises(PermissionDenied):
            read()
