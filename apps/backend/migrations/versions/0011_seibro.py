"""Private, independently reviewed SEIBro TOP50 settlement snapshots."""

from alembic import op

revision = "0011_seibro"
down_revision = "0010_scrape_series_replay"
branch_labels = None
depends_on = None


def upgrade() -> None:
    db = op.get_bind().exec_driver_sql("SELECT current_database()").scalar_one()
    if db not in ("autoaxe_market", "autoaxe_dev", "autoaxe_test"):
        return
    op.execute("""
        CREATE TABLE ops.seibro_captures (
            id uuid PRIMARY KEY,
            source_id text NOT NULL DEFAULT 'seibro' CHECK (source_id='seibro'),
            permission_version integer NOT NULL,
            capture_hash char(64) NOT NULL,
            payload jsonb NOT NULL,
            first_seen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE(permission_version,capture_hash),
            FOREIGN KEY(source_id,permission_version)
                REFERENCES catalog.permission_versions(source_id,permission_version)
        );
        CREATE TABLE ops.seibro_reviews (
            capture_id uuid PRIMARY KEY REFERENCES ops.seibro_captures,
            capture_hash char(64) NOT NULL,
            decision text NOT NULL CHECK (decision IN ('checked','rejected')),
            reviewer_ref text NOT NULL CHECK (length(trim(reviewer_ref)) BETWEEN 1 AND 256),
            evidence_ref text NOT NULL CHECK (length(trim(evidence_ref)) BETWEEN 1 AND 512),
            reviewed_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE TABLE indicators.seibro_top50_snapshots (
            id uuid PRIMARY KEY,
            capture_id uuid NOT NULL UNIQUE REFERENCES ops.seibro_captures,
            permission_version integer NOT NULL,
            scope_hash char(64) NOT NULL,
            content_hash char(64) NOT NULL,
            revision integer NOT NULL CHECK (revision>0),
            country_code text NOT NULL CHECK (country_code IN ('US','ALL','HK','CN','JP','VN')),
            period_code text NOT NULL CHECK (period_code IN ('1','2','3','4','5')),
            rank_basis text NOT NULL CHECK (rank_basis IN ('1','2','3','4')),
            period_start date, period_end date, as_of_date_kst date NOT NULL,
            retrieved_at timestamptz NOT NULL,
            first_seen_at timestamptz NOT NULL,
            available_at timestamptz NOT NULL,
            row_count integer NOT NULL CHECK (row_count BETWEEN 1 AND 50),
            currency text NOT NULL DEFAULT 'USD' CHECK (currency='USD'),
            quality text NOT NULL DEFAULT 'manual_checked' CHECK (quality='manual_checked'),
            top50_coverage boolean NOT NULL DEFAULT true CHECK (top50_coverage),
            automated_trading_allowed boolean NOT NULL DEFAULT false
                CHECK (NOT automated_trading_allowed),
            UNIQUE(scope_hash,revision),
            CHECK ((period_start IS NULL AND period_end IS NULL) OR
                (period_start IS NOT NULL AND period_end IS NOT NULL AND
                 period_start<=period_end AND period_end<=as_of_date_kst)),
            CHECK (retrieved_at<=first_seen_at AND first_seen_at<=available_at)
        );
        CREATE TABLE indicators.seibro_top50_rows (
            snapshot_id uuid NOT NULL REFERENCES indicators.seibro_top50_snapshots,
            rank integer NOT NULL CHECK (rank BETWEEN 1 AND 50),
            country_name text NOT NULL, isin text NOT NULL,
            security_name text NOT NULL,
            buy_settlement_usd numeric NOT NULL CHECK (buy_settlement_usd>=0),
            sell_settlement_usd numeric NOT NULL CHECK (sell_settlement_usd>=0),
            gross_settlement_usd numeric NOT NULL,
            net_buy_settlement_usd numeric NOT NULL,
            PRIMARY KEY(snapshot_id,rank), UNIQUE(snapshot_id,isin),
            CHECK (gross_settlement_usd=buy_settlement_usd+sell_settlement_usd),
            CHECK (net_buy_settlement_usd=buy_settlement_usd-sell_settlement_usd),
            CHECK (buy_settlement_usd NOT IN ('NaN','Infinity','-Infinity') AND
                   sell_settlement_usd NOT IN ('NaN','Infinity','-Infinity'))
        );
        CREATE TABLE ops.seibro_promotions (
            capture_id uuid PRIMARY KEY REFERENCES ops.seibro_reviews,
            snapshot_id uuid REFERENCES indicators.seibro_top50_snapshots,
            decision text NOT NULL CHECK (decision IN ('checked','rejected')),
            promoted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CHECK ((decision='checked')=(snapshot_id IS NOT NULL))
        );
        REVOKE ALL ON indicators.seibro_top50_snapshots,indicators.seibro_top50_rows FROM PUBLIC;
    """)
    op.execute(f"GRANT SELECT,INSERT ON ops.seibro_captures,ops.seibro_promotions TO {db}_runtime")
    op.execute(f"GRANT SELECT ON ops.seibro_reviews TO {db}_runtime")
    op.execute(
        f"GRANT SELECT,INSERT ON indicators.seibro_top50_snapshots,"
        f"indicators.seibro_top50_rows TO {db}_runtime"
    )
    op.execute(
        f"GRANT SELECT ON indicators.seibro_top50_snapshots,"
        f"indicators.seibro_top50_rows TO {db}_read"
    )
    op.execute("""CREATE INDEX seibro_snapshot_lookup ON indicators.seibro_top50_snapshots
        (country_code,period_code,rank_basis,permission_version,as_of_date_kst DESC,
         available_at DESC,revision DESC)""")


def downgrade() -> None:
    raise RuntimeError("restore an approved backup to downgrade")
