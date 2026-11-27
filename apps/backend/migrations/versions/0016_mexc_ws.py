"""Register MEXC NAS100 Protobuf ticker observations without granting source permission."""

import json
from dataclasses import asdict

from alembic import op
from sqlalchemy import text

from autoaxe.domain.market import Series

revision = "0016_mexc_ws"
down_revision = "0015_qqq"
branch_labels = None
depends_on = None

ENTRY = Series(
    "NASDAQ100_MEXC_PERP_USDT_WS",
    "NASDAQ100_MEXC_PERP_USDT_WS",
    "mexc",
    "NAS100_USDT",
    "index_linked_perpetual",
    "USDT/contract",
    "USDT",
    "ticker",
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
        text("SELECT 1 FROM catalog.source_registry WHERE source_id='mexc'")
    ).scalar():
        return
    instrument = "mexc:NAS100_USDT:index_linked_perpetual"
    conn.execute(
        text(
            "INSERT INTO catalog.instruments VALUES (:i,'mexc','NAS100_USDT',"
            "'index_linked_perpetual','USDT') ON CONFLICT DO NOTHING"
        ),
        {"i": instrument},
    )
    conn.execute(
        text(
            "INSERT INTO catalog.series VALUES (:sid,:sid,'mexc',:i,:unit,"
            "'ticker',NULL,1,1) ON CONFLICT DO NOTHING"
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
