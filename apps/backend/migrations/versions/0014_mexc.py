"""Register MEXC NAS100 REST snapshots without granting source permission."""

import json
from dataclasses import asdict

from alembic import op
from sqlalchemy import text

from autoaxe.domain.market import Series

revision = "0014_mexc"
down_revision = "0013_reviewed_documents"
branch_labels = None
depends_on = None

ENTRY = Series(
    "NASDAQ100_MEXC_PERP_USDT",
    "NASDAQ100_MEXC_PERP_USDT",
    "mexc",
    "NAS100_USDT",
    "index_linked_perpetual",
    "USDT/contract",
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
