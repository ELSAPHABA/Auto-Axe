"""Independent durable reservation for each official release task."""

from alembic import op

revision = "0008_official_poll"
down_revision = "0007_equity_series"
branch_labels = None
depends_on = None


def upgrade() -> None:
    db = op.get_bind().exec_driver_sql("SELECT current_database()").scalar_one()
    if db not in ("autoaxe_market", "autoaxe_dev", "autoaxe_test"):
        return
    op.execute("""
        CREATE TABLE ops.official_poll_slots (
            task_id text PRIMARY KEY,
            source_id text NOT NULL REFERENCES catalog.source_registry,
            last_requested_at timestamptz NOT NULL,
            next_requested_at timestamptz NOT NULL,
            permission_version integer NOT NULL
        )
    """)
    op.execute(f"GRANT SELECT,INSERT,UPDATE ON ops.official_poll_slots TO {db}_runtime")


def downgrade() -> None:
    raise RuntimeError("restore an approved backup to downgrade")
