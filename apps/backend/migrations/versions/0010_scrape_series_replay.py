"""Register source-specific scrape series and index per-series committed replay."""

import json
from dataclasses import asdict

from alembic import op
from sqlalchemy import text

from autoaxe.domain.market import Series

revision = "0010_scrape_series_replay"
down_revision = "0009_scrape_review"
branch_labels = None
depends_on = None

SERIES = (
    Series(
        "CNN_FEAR_GREED_CNN",
        "CNN_FEAR_GREED_CNN",
        "cnn",
        "FEAR_GREED",
        "sentiment_index",
        "index",
        None,
        "snapshot",
        None,
    ),
    Series(
        "DRAM_DDR5_UDIMM_AUTO",
        "DRAM_DDR5_UDIMM_AUTO",
        "dramexchange",
        "DDR5 UDIMM 16GB 4800/5600",
        "module_spot_session_average",
        "unverified",
        None,
        "weekly",
        None,
    ),
    Series(
        "DRAM_DDR5_RDIMM_AUTO",
        "DRAM_DDR5_RDIMM_AUTO",
        "dramexchange",
        "DDR5 RDIMM 32GB 4800/5600",
        "module_spot_session_average",
        "unverified",
        None,
        "weekly",
        None,
    ),
)


def upgrade() -> None:
    conn = op.get_bind()
    if conn.exec_driver_sql("SELECT current_database()").scalar_one() not in (
        "autoaxe_market",
        "autoaxe_dev",
        "autoaxe_test",
    ):
        return
    op.execute(
        "CREATE INDEX observations_series_version ON market.observations (series_id,series_version)"
    )
    for entry in SERIES:
        if not conn.execute(
            text("SELECT 1 FROM catalog.source_registry WHERE source_id=:source"),
            {"source": entry.source_id},
        ).scalar():
            continue
        instrument = f"{entry.source_id}:{entry.symbol}:{entry.instrument_type}"
        conn.execute(
            text(
                "INSERT INTO catalog.instruments VALUES (:i,:source,:symbol,:kind,:currency) "
                "ON CONFLICT DO NOTHING"
            ),
            {
                "i": instrument,
                "source": entry.source_id,
                "symbol": entry.symbol,
                "kind": entry.instrument_type,
                "currency": entry.currency,
            },
        )
        conn.execute(
            text(
                "INSERT INTO catalog.series VALUES (:sid,:sid,:source,:i,:unit,:freq,NULL,1,1) "
                "ON CONFLICT DO NOTHING"
            ),
            {
                "sid": entry.id,
                "source": entry.source_id,
                "i": instrument,
                "unit": entry.unit,
                "freq": entry.interval,
            },
        )
        conn.execute(
            text(
                "INSERT INTO catalog.instrument_mappings VALUES "
                "(:sid,1,CAST(:definition AS jsonb)) ON CONFLICT DO NOTHING"
            ),
            {"sid": entry.id, "definition": json.dumps(asdict(entry))},
        )


def downgrade() -> None:
    raise RuntimeError("restore an approved backup to downgrade")
