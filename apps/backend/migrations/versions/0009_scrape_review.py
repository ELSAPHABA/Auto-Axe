"""Durable generic scrape schedule and independently approved review records."""

from alembic import op

revision = "0009_scrape_review"
down_revision = "0008_official_poll"
branch_labels = None
depends_on = None


def upgrade() -> None:
    db = op.get_bind().exec_driver_sql("SELECT current_database()").scalar_one()
    if db not in ("autoaxe_market", "autoaxe_dev", "autoaxe_test"):
        return
    op.execute("""
        ALTER TABLE ops.scrape_jobs ADD COLUMN schedule_interval_seconds integer
            CHECK (schedule_interval_seconds BETWEEN 300 AND 604800);
        CREATE TABLE ops.scrape_adapter_grants (
            source_id text NOT NULL REFERENCES catalog.source_registry,
            permission_version integer NOT NULL,
            adapter_version integer NOT NULL CHECK (adapter_version=1),
            schema_version integer NOT NULL CHECK (schema_version=1),
            mapping_versions jsonb NOT NULL,
            interval_seconds integer NOT NULL CHECK (interval_seconds BETWEEN 300 AND 604800),
            evidence_ref text NOT NULL CHECK (length(trim(evidence_ref)) BETWEEN 1 AND 512),
            verified_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY(source_id,permission_version,adapter_version,schema_version),
            FOREIGN KEY(source_id,permission_version)
                REFERENCES catalog.permission_versions(source_id,permission_version),
            CHECK (source_id IN ('cnn','dramexchange','naver')),
            CHECK (source_id <> 'dramexchange' OR interval_seconds >= 86400)
        );
        CREATE TABLE ops.scrape_schedule (
            source_id text PRIMARY KEY REFERENCES catalog.source_registry,
            last_job_id uuid NOT NULL REFERENCES ops.scrape_jobs,
            last_scheduled_at timestamptz NOT NULL,
            next_due_at timestamptz NOT NULL,
            CHECK (source_id IN ('cnn','dramexchange','naver'))
        );
        CREATE TABLE ops.scrape_reviews (
            job_id uuid PRIMARY KEY REFERENCES ops.scrape_results,
            result_hash char(64) NOT NULL,
            decision text NOT NULL CHECK (decision IN ('checked','rejected')),
            reviewer_ref text NOT NULL CHECK (length(trim(reviewer_ref)) BETWEEN 1 AND 256),
            evidence_ref text NOT NULL CHECK (length(trim(evidence_ref)) BETWEEN 1 AND 512),
            units jsonb NOT NULL,
            reviewed_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE TABLE ops.scrape_promotions (
            job_id uuid PRIMARY KEY REFERENCES ops.scrape_reviews,
            result_hash char(64) NOT NULL,
            observation_ids jsonb NOT NULL,
            promoted_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
    """)
    # Runtime cannot grant adapter verification or create/modify review decisions.
    op.execute(f"GRANT SELECT ON ops.scrape_adapter_grants,ops.scrape_reviews TO {db}_runtime")
    op.execute(f"GRANT SELECT,INSERT,UPDATE ON ops.scrape_schedule TO {db}_runtime")
    op.execute(f"GRANT SELECT,INSERT ON ops.scrape_promotions TO {db}_runtime")


def downgrade() -> None:
    raise RuntimeError("restore an approved backup to downgrade")
