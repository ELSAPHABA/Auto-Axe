"""Register equity collection series without granting source rights."""

import json
from dataclasses import asdict

from alembic import op
from sqlalchemy import text

from autoaxe.domain.market import Series

revision = "0007_equity_series"
down_revision = "0006_pizzint_cadence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    db = conn.exec_driver_sql("SELECT current_database()").scalar_one()
    if db not in ("autoaxe_market", "autoaxe_dev", "autoaxe_test"):
        return
    # Fresh fixture bootstrap seeds the catalog after migrations. Existing
    # DBs already have the source; never grant rights or overwrite mappings.
    if not conn.execute(
        text("SELECT 1 FROM catalog.source_registry WHERE source_id='yfinance'")
    ).scalar():
        return
    for symbol, kind in (("NVDA", "us_equity"), ("QLD", "us_etf")):
        for sid, unit, cadence, ttl in (
            (f"US_STOCK_DAILY_CUM_VOLUME_1S_{symbol}", "shares", "local_1hz", 5),
            (f"{symbol}_FUNDAMENTALS", "mixed", "daily", None),
            (f"{symbol}_DAILY_OHLCV", "USD", "1d", None),
        ):
            entry = Series(sid, sid, "yfinance", symbol, kind, unit, "USD", cadence, ttl)
            instrument = f"yfinance:{symbol}:{kind}"
            conn.execute(
                text(
                    "INSERT INTO catalog.instruments VALUES (:i,'yfinance',:s,:k,'USD') "
                    "ON CONFLICT DO NOTHING"
                ),
                {"i": instrument, "s": symbol, "k": kind},
            )
            conn.execute(
                text(
                    "INSERT INTO catalog.series VALUES (:sid,:sid,'yfinance',:i,:u,:f,:ttl,1,1) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"sid": sid, "i": instrument, "u": unit, "f": cadence, "ttl": ttl},
            )
            conn.execute(
                text(
                    "INSERT INTO catalog.instrument_mappings VALUES "
                    "(:sid,1,CAST(:definition AS jsonb)) ON CONFLICT DO NOTHING"
                ),
                {"sid": sid, "definition": json.dumps(asdict(entry))},
            )


def downgrade() -> None:
    raise RuntimeError("restore an approved backup to downgrade")
