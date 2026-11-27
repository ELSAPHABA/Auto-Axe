"""Append-only, independently reviewed contract-specific session calendars."""

from alembic import op

revision = "0019_expiry_sessions"
down_revision = "0018_seibro_browser"
branch_labels = None
depends_on = None


def upgrade() -> None:
    db = op.get_bind().exec_driver_sql("SELECT current_database()").scalar_one()
    if db not in ("autoaxe_market", "autoaxe_dev", "autoaxe_test"):
        return
    op.execute("""
      CREATE TABLE indicators.expiry_product_calendar (
        id uuid PRIMARY KEY,
        source_id text NOT NULL CHECK(source_id IN ('occ','cme')),
        family text NOT NULL CHECK(family IN ('EQUITY_OPTION','INDEX_OPTION',
          'INDEX_FUTURE','SINGLE_STOCK_FUTURE')),
        contract_ref text NOT NULL CHECK(length(contract_ref) BETWEEN 1 AND 256),
        revision integer NOT NULL CHECK(revision>0),
        coverage_start date NOT NULL,
        coverage_end date NOT NULL CHECK(coverage_end>=coverage_start),
        sessions date[] NOT NULL CHECK(cardinality(sessions) BETWEEN 1 AND 800),
        evidence_ref text NOT NULL CHECK(length(evidence_ref) BETWEEN 1 AND 2000),
        source_url text NOT NULL CHECK(length(source_url) BETWEEN 1 AND 2048),
        submitter_ref text NOT NULL CHECK(length(submitter_ref) BETWEEN 1 AND 128),
        content_hash char(64) NOT NULL,
        permission_version integer NOT NULL,
        first_seen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        FOREIGN KEY(source_id,permission_version)
          REFERENCES catalog.permission_versions(source_id,permission_version),
        UNIQUE(source_id,family,contract_ref,revision)
      );
      CREATE TABLE indicators.expiry_product_calendar_review (
        calendar_id uuid PRIMARY KEY REFERENCES indicators.expiry_product_calendar(id),
        decision text NOT NULL CHECK(decision IN ('checked','rejected')),
        reviewer_ref text NOT NULL CHECK(length(reviewer_ref) BETWEEN 1 AND 128),
        reason text NOT NULL CHECK(length(reason) BETWEEN 1 AND 2000),
        reviewed_at timestamptz NOT NULL DEFAULT clock_timestamp()
      );
    """)
    for table in ("expiry_product_calendar", "expiry_product_calendar_review"):
        op.execute(f"GRANT SELECT,INSERT ON indicators.{table} TO {db}_runtime")
        op.execute(f"GRANT SELECT ON indicators.{table} TO {db}_read")


def downgrade() -> None:
    raise RuntimeError("restore an approved backup to downgrade")
