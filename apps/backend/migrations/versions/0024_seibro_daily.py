"""Daily validated SEIBro batches with independent versioned adapter approval."""

from alembic import op

revision = "0024_seibro_daily"
down_revision = "0023_toss_2y"
branch_labels = None
depends_on = None


def upgrade() -> None:
    db = op.get_bind().exec_driver_sql("SELECT current_database()").scalar_one()
    if db not in ("autoaxe_market", "autoaxe_dev", "autoaxe_test"):
        return
    op.execute("""
        CREATE TABLE ops.seibro_adapter_grants (
            source_id text NOT NULL DEFAULT 'seibro' CHECK (source_id='seibro'),
            permission_version integer NOT NULL,
            adapter_version integer NOT NULL CHECK (adapter_version=1),
            schema_version integer NOT NULL CHECK (schema_version=1),
            interval_seconds integer NOT NULL CHECK (interval_seconds=86400),
            reviewer_ref text NOT NULL CHECK (length(trim(reviewer_ref)) BETWEEN 1 AND 256),
            evidence_ref text NOT NULL CHECK (length(trim(evidence_ref)) BETWEEN 1 AND 512),
            verified_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY(source_id,permission_version,adapter_version,schema_version),
            FOREIGN KEY(source_id,permission_version)
                REFERENCES catalog.permission_versions(source_id,permission_version)
        );
        CREATE TABLE ops.seibro_daily_batches (
            id uuid PRIMARY KEY,
            source_id text NOT NULL DEFAULT 'seibro' CHECK (source_id='seibro'),
            permission_version integer NOT NULL,
            reserved_at timestamptz NOT NULL UNIQUE,
            deadline_at timestamptz NOT NULL,
            available_at timestamptz NOT NULL,
            as_of_date_kst date NOT NULL,
            scope_count integer NOT NULL CHECK (scope_count=15),
            CHECK (reserved_at<=available_at AND available_at<=deadline_at),
            FOREIGN KEY(source_id,permission_version)
                REFERENCES catalog.permission_versions(source_id,permission_version)
        );
        CREATE TABLE ops.seibro_validated_promotions (
            capture_id uuid PRIMARY KEY REFERENCES ops.seibro_captures,
            batch_id uuid NOT NULL REFERENCES ops.seibro_daily_batches,
            period_code text NOT NULL CHECK (period_code IN ('1','2','3','4','5')),
            rank_basis text NOT NULL CHECK (rank_basis IN ('1','2','4')),
            snapshot_id uuid NOT NULL REFERENCES indicators.seibro_top50_snapshots,
            UNIQUE(batch_id,period_code,rank_basis)
        );
        ALTER TABLE indicators.seibro_top50_snapshots
            DROP CONSTRAINT seibro_top50_snapshots_quality_check,
            DROP CONSTRAINT seibro_top50_snapshots_automated_trading_allowed_check,
            ADD CONSTRAINT seibro_snapshot_validation CHECK (
                quality='manual_checked'
                OR (quality='adapter_validated' AND capture_mode='browser_capture'
                    AND country_code='US' AND rank_basis IN ('1','2','4'))
            );
    """)
    op.execute(f"GRANT SELECT ON ops.seibro_adapter_grants TO {db}_runtime")
    op.execute(
        f"GRANT SELECT(source_id,permission_version,adapter_version,schema_version,verified_at)"
        f" ON ops.seibro_adapter_grants TO {db}_read"
    )
    op.execute(
        f"GRANT SELECT,INSERT ON ops.seibro_daily_batches,"
        f"ops.seibro_validated_promotions TO {db}_runtime"
    )
    op.execute(
        f"GRANT SELECT(id,permission_version,available_at) ON ops.seibro_daily_batches TO {db}_read"
    )
    op.execute(
        f"GRANT SELECT(batch_id,snapshot_id) ON ops.seibro_validated_promotions TO {db}_read"
    )
    op.execute("""
        CREATE INDEX seibro_validated_snapshot_lookup
        ON ops.seibro_validated_promotions(snapshot_id,batch_id)
    """)


def downgrade() -> None:
    raise RuntimeError("restore an approved backup to downgrade")
