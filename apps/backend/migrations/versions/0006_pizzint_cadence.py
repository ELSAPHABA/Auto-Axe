"""Update existing DOUGHCON catalog frequency without deleting observations."""

from alembic import op

revision = "0006_pizzint_cadence"
down_revision = "0005_phase2_official"
branch_labels = None
depends_on = None


def upgrade() -> None:
    db = op.get_bind().exec_driver_sql("SELECT current_database()").scalar_one()
    if db in ("autoaxe_market", "autoaxe_dev", "autoaxe_test"):
        op.execute("""
            UPDATE catalog.series SET frequency='5m'
            WHERE series_id='PENTAGON_PIZZA_PIZZINT' AND source_id='pizzint'
        """)


def downgrade() -> None:
    raise RuntimeError("restore an approved backup to downgrade")
