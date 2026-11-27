"""Register independent Yahoo oil fallback and VIX quote series without rights."""

import json
from dataclasses import asdict

from alembic import op
from sqlalchemy import text

from autoaxe.domain.market import Series

revision = "0020_oil_ws"
down_revision = "0019_expiry_sessions"
branch_labels = None
depends_on = None

ENTRIES = (
    Series(
        "VIX_YAHOO_WS",
        "VIX",
        "yfinance",
        "^VIX",
        "volatility_index",
        "index_point",
        None,
        "ticker",
        10,
    ),
    Series(
        "WTI_YAHOO_FUTURES_WS",
        "WTI_YAHOO_FUTURES_WS",
        "yfinance",
        "CL=F",
        "commodity_wti_futures_continuous_quote",
        "USD/bbl",
        "USD",
        "ticker",
        None,
    ),
    Series(
        "BRENT_YAHOO_FUTURES_WS",
        "BRENT_YAHOO_FUTURES_WS",
        "yfinance",
        "BZ=F",
        "commodity_brent_futures_continuous_quote",
        "USD/bbl",
        "USD",
        "ticker",
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
    if not conn.execute(
        text("SELECT 1 FROM catalog.source_registry WHERE source_id='yfinance'")
    ).scalar():
        return
    for entry in ENTRIES:
        instrument = f"yfinance:{entry.symbol}:{entry.instrument_type}"
        conn.execute(
            text(
                "INSERT INTO catalog.instruments VALUES (:i,'yfinance',:symbol,:kind,:currency) "
                "ON CONFLICT DO NOTHING"
            ),
            {
                "i": instrument,
                "symbol": entry.symbol,
                "kind": entry.instrument_type,
                "currency": entry.currency,
            },
        )
        conn.execute(
            text(
                "INSERT INTO catalog.series VALUES (:sid,:indicator,'yfinance',:i,:unit,"
                "'ticker',:ttl,1,1) ON CONFLICT DO NOTHING"
            ),
            {
                "sid": entry.id,
                "indicator": entry.indicator_id,
                "i": instrument,
                "unit": entry.unit,
                "ttl": entry.ttl,
            },
        )
        conn.execute(
            text(
                "INSERT INTO catalog.instrument_mappings "
                "VALUES (:sid,1,CAST(:definition AS jsonb)) "
                "ON CONFLICT DO NOTHING"
            ),
            {"sid": entry.id, "definition": json.dumps(asdict(entry))},
        )


def downgrade() -> None:
    raise RuntimeError("restore an approved backup to downgrade")
