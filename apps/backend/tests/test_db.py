"""Real ephemeral PG17; no broker or provider access."""

import secrets
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from psycopg.errors import InsufficientPrivilege
from testcontainers.postgres import PostgresContainer

from autoaxe.infrastructure.db_bootstrap import DATABASES, EXECUTOR_DBS, provision

IMAGE = "postgres:17@sha256:87c8b42f423b45d5247e6aa8fdb2e7762fec164c68a50fe3eb07e7bfcaf4dbcf"


@pytest.mark.integration
def test_database_role_matrix(monkeypatch):
    monkeypatch.setenv("AUTOAXE_DISPOSABLE_DB", "true")
    secret = secrets.token_urlsafe(24)
    with PostgresContainer(
        IMAGE, username="fixture_admin", password=secret, dbname="postgres"
    ) as pg:
        host, port = pg.get_container_host_ip(), pg.get_exposed_port(5432)
        dsn = psycopg.conninfo.make_conninfo(
            host=host, port=port, dbname="postgres", user="fixture_admin", password=secret
        )
        passwords = provision(dsn, Path(__file__).resolve().parents[1] / "alembic.ini")
        for db in DATABASES:
            role = f"{db}_runtime"
            auth = dict(host=host, port=port, user=role, password=passwords[role])
            value = Decimal("123456789012345678.123456789012345678")
            stamp = datetime(2026, 1, 1, 12, 34, 56, tzinfo=UTC)
            with psycopg.connect(**auth, dbname=db, autocommit=True) as connection:
                assert connection.execute("SELECT current_database(), current_user").fetchone() == (
                    db,
                    role,
                )
                connection.execute(
                    "INSERT INTO ops.fixture_marker VALUES (%s,%s,%s)", (1, value, stamp)
                )
                assert connection.execute(
                    "SELECT value, observed_at FROM ops.fixture_marker"
                ).fetchone() == (value, stamp)
                assert connection.execute(
                    "SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls "
                    "FROM pg_roles WHERE rolname=current_user"
                ).fetchone() == (False, False, False, False)
                with pytest.raises(InsufficientPrivilege):
                    connection.execute("CREATE TABLE ops.forbidden (id int)")
                with pytest.raises(InsufficientPrivilege):
                    connection.execute("SELECT * FROM ops.alembic_version")
            for suffix in ("read", "relay"):
                reader = f"{db}_{suffix}"
                with psycopg.connect(
                    host=host,
                    port=port,
                    dbname=db,
                    user=reader,
                    password=passwords[reader],
                    autocommit=True,
                ) as connection:
                    assert connection.execute(
                        "SELECT count(*) FROM ops.fixture_marker"
                    ).fetchone() == (1,)
                    with pytest.raises(InsufficientPrivilege):
                        connection.execute("DELETE FROM ops.fixture_marker")
            # Actual authentication/CONNECT checks, not SET ROLE simulations.
            for other in (*DATABASES, "postgres"):
                if other != db:
                    with pytest.raises(psycopg.OperationalError, match="permission denied"):
                        psycopg.connect(**auth, dbname=other, connect_timeout=3)
            if db in EXECUTOR_DBS:
                executor = f"{db}_executor"
                auth = dict(host=host, port=port, user=executor, password=passwords[executor])
                with psycopg.connect(**auth, dbname=db) as connection:
                    assert connection.execute(
                        "SELECT count(*) FROM ops.fixture_marker"
                    ).fetchone() == (1,)
                for other in DATABASES:
                    if other != db:
                        with pytest.raises(psycopg.OperationalError, match="permission denied"):
                            psycopg.connect(**auth, dbname=other, connect_timeout=3)
