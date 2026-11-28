"""Register Toss separately; retire Naver without relabeling historical data."""

import json
from dataclasses import asdict

from alembic import op
from sqlalchemy import text

from autoaxe.domain.market import Series

revision = "0023_toss_2y"
down_revision = "0022_cnn_graphs"
branch_labels = None
depends_on = None

ENTRY = Series(
    "UST_2Y_TOSS",
    "UST_2Y",
    "toss",
    "ROB.US2YT-RR",
    "us_two_year_treasury_yield",
    "percent",
    None,
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
    op.execute("""
        INSERT INTO catalog.source_registry
            (source_id,provider,terms_url,permission_status,enabled,allow_fetch,allow_storage)
        VALUES ('toss','toss','https://corp.tossinvest.com/en/terms/v2?id=35',
                'unverified',false,false,false)
        ON CONFLICT DO NOTHING;
        INSERT INTO catalog.permission_versions
            SELECT source_id,permission_version,to_jsonb(r)
            FROM catalog.source_registry r WHERE source_id='toss' ON CONFLICT DO NOTHING;
        UPDATE catalog.source_registry SET permission_status='blocked',enabled=false,
            allow_fetch=false,allow_storage=false,allow_redistribution=false,
            allow_trading=false,permission_version=permission_version+1,
            verified_at=clock_timestamp(),evidence_ref='Retired: replaced by Toss 2Y'
        WHERE source_id='naver';
        INSERT INTO catalog.permission_versions
            SELECT source_id,permission_version,to_jsonb(r)
            FROM catalog.source_registry r WHERE source_id='naver' ON CONFLICT DO NOTHING;
        UPDATE ops.scrape_jobs SET status='revoked'
            WHERE source_id='naver' AND status IN ('queued','leased');
        UPDATE catalog.source_registry SET terms_url=
            'https://www.tossinvest.com/indices/ROB.US2YT-RR',
            permission_status='unverified',enabled=false,allow_fetch=false,allow_storage=false,
            allow_redistribution=false,allow_trading=false,verified_at=NULL,evidence_ref=NULL,
            permission_version=permission_version+1
        WHERE source_id='manual:UST_2Y_INTRADAY'
            AND terms_url<>'https://www.tossinvest.com/indices/ROB.US2YT-RR';
        INSERT INTO catalog.permission_versions
            SELECT source_id,permission_version,to_jsonb(r) FROM catalog.source_registry r
            WHERE source_id='manual:UST_2Y_INTRADAY' ON CONFLICT DO NOTHING;
        ALTER TABLE ops.scrape_adapter_grants
            DROP CONSTRAINT scrape_adapter_grants_source_id_check,
            ADD CONSTRAINT scrape_adapter_grants_source_id_check
            CHECK (source_id IN ('cnn','dramexchange','naver','toss'));
        ALTER TABLE ops.scrape_schedule
            DROP CONSTRAINT scrape_schedule_source_id_check,
            ADD CONSTRAINT scrape_schedule_source_id_check
            CHECK (source_id IN ('cnn','dramexchange','naver','toss'));
    """)
    instrument = f"toss:{ENTRY.symbol}:{ENTRY.instrument_type}"
    conn.execute(
        text(
            "INSERT INTO catalog.instruments VALUES (:i,'toss',:symbol,:kind,NULL) "
            "ON CONFLICT DO NOTHING"
        ),
        {"i": instrument, "symbol": ENTRY.symbol, "kind": ENTRY.instrument_type},
    )
    conn.execute(
        text(
            "INSERT INTO catalog.series VALUES (:sid,'UST_2Y','toss',:i,'percent',"
            "'snapshot',NULL,1,1) ON CONFLICT DO NOTHING"
        ),
        {"sid": ENTRY.id, "i": instrument},
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
