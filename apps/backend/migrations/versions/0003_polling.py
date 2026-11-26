"""Durable per-series polling slots and provider-wide circuit state."""

from alembic import op

revision = "0003_polling"
down_revision = "0002_market"
branch_labels = None
depends_on = None


def upgrade() -> None:
    db = op.get_bind().exec_driver_sql("SELECT current_database()").scalar_one()
    if db not in ("autoaxe_market", "autoaxe_dev", "autoaxe_test"):
        return
    op.execute("""
        CREATE TABLE ops.poll_slots (
            series_id text PRIMARY KEY REFERENCES catalog.series,
            last_slot bigint NOT NULL,
            last_enqueued_at timestamptz NOT NULL
        );
        CREATE TABLE ops.poll_circuits (
            source_id text PRIMARY KEY REFERENCES catalog.source_registry,
            permission_version integer NOT NULL,
            blocked boolean NOT NULL DEFAULT false,
            retry_at timestamptz,
            reason text NOT NULL
        );
        CREATE INDEX jobs_poll_active ON ops.jobs(owner_ref, status)
            WHERE status IN ('queued','running','cancel_requested');
    """)
    op.execute(f"GRANT SELECT,INSERT,UPDATE ON ops.poll_slots,ops.poll_circuits TO {db}_runtime")
    op.execute(f"GRANT SELECT ON ops.poll_slots,ops.poll_circuits TO {db}_read")


def downgrade() -> None:
    raise RuntimeError("restore an approved backup to downgrade durable scheduling")
