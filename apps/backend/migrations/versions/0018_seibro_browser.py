"""Preserve browser capture provenance in the reviewed SEIBro typed ledger."""

from alembic import op

revision = "0018_seibro_browser"
down_revision = "0017_document_inbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    db = op.get_bind().exec_driver_sql("SELECT current_database()").scalar_one()
    if db not in ("autoaxe_market", "autoaxe_dev", "autoaxe_test"):
        return
    op.execute("""
        ALTER TABLE indicators.seibro_top50_snapshots
          ADD COLUMN capture_mode text NOT NULL DEFAULT 'manual_capture',
          ADD COLUMN derived_amount text,
          ADD COLUMN amount_coverage text NOT NULL DEFAULT 'complete',
          ADD CONSTRAINT seibro_snapshot_coverage_key UNIQUE(id,amount_coverage),
          ADD CONSTRAINT seibro_capture_provenance CHECK (
            (capture_mode='manual_capture' AND derived_amount IS NULL
             AND amount_coverage='complete') OR
            (capture_mode='browser_capture' AND row_count=50 AND (
              (rank_basis='1' AND amount_coverage='buy_only' AND derived_amount IS NULL) OR
              (rank_basis='2' AND amount_coverage='sell_only' AND derived_amount IS NULL) OR
              (rank_basis='3' AND amount_coverage='complete' AND derived_amount IS NOT NULL
               AND derived_amount='net_buy_settlement_usd') OR
              (rank_basis='4' AND amount_coverage='complete' AND derived_amount IS NOT NULL
               AND derived_amount='gross_settlement_usd')))
          );
        ALTER TABLE indicators.seibro_top50_rows
          ALTER COLUMN buy_settlement_usd DROP NOT NULL,
          ALTER COLUMN sell_settlement_usd DROP NOT NULL,
          ALTER COLUMN gross_settlement_usd DROP NOT NULL,
          ALTER COLUMN net_buy_settlement_usd DROP NOT NULL,
          ADD COLUMN amount_coverage text NOT NULL DEFAULT 'complete',
          ADD CONSTRAINT seibro_row_coverage_fk FOREIGN KEY(snapshot_id,amount_coverage)
            REFERENCES indicators.seibro_top50_snapshots(id,amount_coverage),
          ADD CONSTRAINT seibro_row_amount_coverage CHECK (
            (amount_coverage='complete' AND buy_settlement_usd IS NOT NULL
             AND sell_settlement_usd IS NOT NULL AND gross_settlement_usd IS NOT NULL
             AND net_buy_settlement_usd IS NOT NULL) OR
            (amount_coverage='buy_only' AND buy_settlement_usd IS NOT NULL
             AND sell_settlement_usd IS NULL AND gross_settlement_usd IS NULL
             AND net_buy_settlement_usd IS NULL) OR
            (amount_coverage='sell_only' AND buy_settlement_usd IS NULL
             AND sell_settlement_usd IS NOT NULL AND gross_settlement_usd IS NULL
             AND net_buy_settlement_usd IS NULL)
          );
    """)


def downgrade() -> None:
    raise RuntimeError("restore an approved backup to downgrade")
