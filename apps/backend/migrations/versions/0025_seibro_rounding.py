"""Retain observed whole-dollar SEIBro net rounding with explicit provenance."""

from alembic import op

revision = "0025_seibro_rounding"
down_revision = "0024_seibro_daily"
branch_labels = None
depends_on = None


def upgrade() -> None:
    db = op.get_bind().exec_driver_sql("SELECT current_database()").scalar_one()
    if db not in ("autoaxe_market", "autoaxe_dev", "autoaxe_test"):
        return
    op.execute("""
        ALTER TABLE indicators.seibro_top50_snapshots
          ADD CONSTRAINT seibro_snapshot_derived_key UNIQUE(id,derived_amount);
        ALTER TABLE indicators.seibro_top50_rows
          DROP CONSTRAINT seibro_top50_rows_check1,
          ADD COLUMN net_display_rounding_usd smallint NOT NULL DEFAULT 0,
          ADD COLUMN rounding_derived_amount text GENERATED ALWAYS AS
            (CASE WHEN net_display_rounding_usd<>0
                  THEN 'gross_settlement_usd' ELSE NULL END) STORED,
          ADD CONSTRAINT seibro_net_rounding_provenance_fk
            FOREIGN KEY(snapshot_id,rounding_derived_amount)
            REFERENCES indicators.seibro_top50_snapshots(id,derived_amount),
          ADD CONSTRAINT seibro_net_rounding_bounds CHECK (
            net_display_rounding_usd IN (-1,0,1) AND (
              net_display_rounding_usd=0 OR (
                amount_coverage='complete' AND
                buy_settlement_usd IS NOT NULL AND sell_settlement_usd IS NOT NULL AND
                net_buy_settlement_usd IS NOT NULL AND
                buy_settlement_usd=trunc(buy_settlement_usd) AND
                sell_settlement_usd=trunc(sell_settlement_usd) AND
                net_buy_settlement_usd=trunc(net_buy_settlement_usd)
              )
            )
          ),
          ADD CONSTRAINT seibro_net_display_arithmetic CHECK (
            net_buy_settlement_usd=
                buy_settlement_usd-sell_settlement_usd+net_display_rounding_usd
          );
    """)


def downgrade() -> None:
    raise RuntimeError("restore an approved backup to downgrade")
