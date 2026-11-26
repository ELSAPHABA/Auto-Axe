"""Provision an isolated, disposable Phase 0 PostgreSQL instance.

Only run against a dedicated fixture cluster. Never point this at an existing
production database: the bootstrap intentionally revokes PUBLIC privileges.
Random login passwords are returned only to in-process integration tests.
"""

import os
import secrets
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from sqlalchemy import URL, create_engine

from autoaxe.infrastructure.config import Settings

DATABASES = (
    "autoaxe_dev",
    "autoaxe_test",
    "autoaxe_market",
    "autoaxe_app",
    "autoaxe_backtest",
    "autoaxe_dry_run",
    "autoaxe_paper_local",
    "autoaxe_paper_broker",
    "autoaxe_live",
    "autoaxe_identity",
)
EXECUTOR_DBS = {"autoaxe_paper_local", "autoaxe_paper_broker", "autoaxe_live"}
SUFFIXES = ("migration", "runtime", "read", "relay")


def provision(admin_dsn: str, migrations: Path) -> dict[str, str]:
    Settings()
    if os.getenv("AUTOAXE_DISPOSABLE_DB") != "true":
        raise RuntimeError("explicit disposable fixture DB consent required")
    conn = conninfo_to_dict(admin_dsn)
    if conn.get("dbname") != "postgres":
        raise ValueError("bootstrap requires postgres admin database")
    passwords: dict[str, str] = {}
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        major = int(admin.info.server_version) // 10000
        if major != 17:
            raise RuntimeError("PostgreSQL 17 required")
        existing = admin.execute(
            "SELECT datname FROM pg_database WHERE NOT datistemplate AND datname <> 'postgres'"
        ).fetchall()
        if any(row[0] not in DATABASES for row in existing):
            raise RuntimeError("non-fixture database found; refusing bootstrap")
        for database in ("postgres", "template1"):
            admin.execute(
                sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(
                    sql.Identifier(database)
                )
            )
        for database in DATABASES:
            owner = f"{database}_owner"
            roles = (*SUFFIXES, "executor") if database in EXECUTOR_DBS else SUFFIXES
            if not admin.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (owner,)).fetchone():
                admin.execute(
                    sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE").format(
                        sql.Identifier(owner)
                    )
                )
            for suffix in roles:
                role = f"{database}_{suffix}"
                password = secrets.token_urlsafe(32)
                passwords[role] = password
                exists = admin.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)
                ).fetchone()
                verb = sql.SQL("ALTER ROLE") if exists else sql.SQL("CREATE ROLE")
                admin.execute(
                    sql.SQL(
                        "{} {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOREPLICATION NOBYPASSRLS PASSWORD {}"
                    ).format(verb, sql.Identifier(role), sql.Literal(password))
                )
            admin.execute(
                sql.SQL("GRANT {} TO {}").format(
                    sql.Identifier(owner), sql.Identifier(f"{database}_migration")
                )
            )
            if not admin.execute(
                "SELECT 1 FROM pg_database WHERE datname=%s", (database,)
            ).fetchone():
                admin.execute(
                    sql.SQL("CREATE DATABASE {} OWNER {}").format(
                        sql.Identifier(database), sql.Identifier(owner)
                    )
                )
            admin.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database))
            )
            for suffix in roles:
                admin.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                        sql.Identifier(database), sql.Identifier(f"{database}_{suffix}")
                    )
                )
            with psycopg.connect(admin_dsn, dbname=database, autocommit=True) as scoped:
                scoped.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
                scoped.execute(
                    sql.SQL("CREATE SCHEMA IF NOT EXISTS ops AUTHORIZATION {}").format(
                        sql.Identifier(owner)
                    )
                )
                for suffix in roles:
                    scoped.execute(
                        sql.SQL("GRANT USAGE ON SCHEMA ops TO {}").format(
                            sql.Identifier(f"{database}_{suffix}")
                        )
                    )
            migration = f"{database}_migration"
            url = URL.create(
                "postgresql+psycopg",
                username=migration,
                password=passwords[migration],
                host=str(conn.get("host") or "localhost"),
                port=int(str(conn.get("port") or "5432")),
                database=database,
            )
            engine = create_engine(url, connect_args={"options": f"-c role={owner}"})
            try:
                config = Config(str(migrations))
                with engine.begin() as connection:
                    config.attributes["connection"] = connection
                    command.upgrade(config, "head")
            finally:
                engine.dispose()
            with psycopg.connect(admin_dsn, dbname=database, autocommit=True) as scoped:
                for suffix in roles:
                    if suffix == "migration":
                        continue
                    privileges = (
                        sql.SQL("SELECT, INSERT, UPDATE, DELETE")
                        if suffix in ("runtime", "executor")
                        else sql.SQL("SELECT")
                    )
                    scoped.execute(
                        sql.SQL("GRANT {} ON ops.fixture_marker TO {}").format(
                            privileges, sql.Identifier(f"{database}_{suffix}")
                        )
                    )
    return passwords


def main() -> None:
    # Never log DSNs, passwords or connection exceptions with raw parameters.
    dsn = os.environ["AUTOAXE_FIXTURE_ADMIN_DSN"]
    config = Path(os.environ.get("AUTOAXE_ALEMBIC_CONFIG", "alembic.ini")).resolve()
    provision(dsn, config)
    print("fixture DB roles and migration verified by bootstrap; runtime secrets not persisted")


if __name__ == "__main__":
    main()
