"""Bounded, durable official API request quota for Phase 2 continuation."""

from alembic import op

revision = "0005_phase2_official"
down_revision = "0004_phase2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    db = op.get_bind().exec_driver_sql("SELECT current_database()").scalar_one()
    if db not in ("autoaxe_market", "autoaxe_dev", "autoaxe_test"):
        return
    op.execute(
        """CREATE TABLE ops.official_api_quota (
             source_id text NOT NULL REFERENCES catalog.source_registry(source_id),
             utc_day date NOT NULL,
             requests_used integer NOT NULL DEFAULT 0 CHECK (requests_used BETWEEN 0 AND 25),
             PRIMARY KEY (source_id,utc_day)
           )"""
    )
    op.execute(f"GRANT SELECT,INSERT,UPDATE ON ops.official_api_quota TO {db}_runtime")


def downgrade() -> None:
    raise RuntimeError("Official API request quota requires approved backup restore")
