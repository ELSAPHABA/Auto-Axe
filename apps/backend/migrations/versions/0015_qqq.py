"""Register Binance QQQ REST snapshots without granting source permission."""

import json
from dataclasses import asdict

from alembic import op
from sqlalchemy import text

from autoaxe.domain.market import Series

revision = "0015_qqq"
down_revision = "0014_mexc"
branch_labels = None
depends_on = None

ENTRY = Series(
    "NASDAQ100_BINANCE_QQQ_PERP_USDT",
    "NASDAQ100_BINANCE_QQQ_PERP_USDT",
    "binance_futures",
    "QQQUSDT",
    "etf_linked_perpetual",
    "USDT/QQQ",
    "USDT",
    "snapshot",
    None,
)


def upgrade() -> None:
    conn = op.get_bind()
    if conn.exec_driver_sql("SELECT current_database()").scalar_one() not in (
        "autoaxe_market",
        "autoaxe_dev",
        "autoaxe_test",
    ):
        return
    # Fresh fixture bootstrap seeds the entire catalog after migrations.
    if not conn.execute(
        text("SELECT 1 FROM catalog.source_registry WHERE source_id='binance_futures'")
    ).scalar():
        return
    instrument = "binance_futures:QQQUSDT:etf_linked_perpetual"
    conn.execute(
        text(
            "INSERT INTO catalog.instruments VALUES (:i,'binance_futures','QQQUSDT',"
            "'etf_linked_perpetual','USDT') ON CONFLICT DO NOTHING"
        ),
        {"i": instrument},
    )
    conn.execute(
        text(
            "INSERT INTO catalog.series VALUES (:sid,:sid,'binance_futures',:i,:unit,"
            "'snapshot',NULL,1,1) ON CONFLICT DO NOTHING"
        ),
        {"sid": ENTRY.id, "i": instrument, "unit": ENTRY.unit},
    )
    conn.execute(
        text(
            "INSERT INTO catalog.instrument_mappings VALUES (:sid,1,CAST(:definition AS jsonb)) "
            "ON CONFLICT DO NOTHING"
        ),
        {"sid": ENTRY.id, "definition": json.dumps(asdict(ENTRY))},
    )


def downgrade() -> None:
    raise RuntimeError("restore an approved backup to downgrade")
