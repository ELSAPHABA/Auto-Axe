"""Independent official document review and checked corporate guidance."""

from alembic import op

revision = "0013_reviewed_documents"
down_revision = "0012_expiry_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    db = op.get_bind().exec_driver_sql("SELECT current_database()").scalar_one()
    if db not in ("autoaxe_market", "autoaxe_dev", "autoaxe_test"):
        return
    op.execute("""
        CREATE TABLE ops.official_document_reviews (
          id uuid PRIMARY KEY,
          source_id text NOT NULL,
          permission_version integer NOT NULL,
          candidate jsonb NOT NULL,
          candidate_hash char(64) NOT NULL,
          reviewer_ref text NOT NULL CHECK(length(trim(reviewer_ref)) BETWEEN 1 AND 256),
          evidence_ref text NOT NULL CHECK(length(trim(evidence_ref)) BETWEEN 1 AND 512),
          reviewed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
          FOREIGN KEY(source_id,permission_version)
            REFERENCES catalog.permission_versions(source_id,permission_version),
          CHECK(source_id IN ('boj','sec_edgar')),
          UNIQUE(source_id,permission_version,candidate_hash)
        );
        CREATE TABLE ops.official_document_promotions (
          review_id uuid PRIMARY KEY REFERENCES ops.official_document_reviews,
          promoted_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        ALTER TABLE indicators.corporate_guidance
          ADD COLUMN available_at timestamptz,
          ADD COLUMN issued_at timestamptz,
          ADD COLUMN permission_version integer,
          ADD COLUMN review_id uuid REFERENCES ops.official_document_reviews(id),
          ADD CONSTRAINT corporate_guidance_pit CHECK(
             (review_id IS NULL) OR (
               available_at IS NOT NULL AND available_at>=first_seen_at
               AND (issued_at IS NULL OR issued_at<=first_seen_at)
               AND permission_version IS NOT NULL AND review_status='checked'
             )
          );
        CREATE INDEX corporate_guidance_pit_idx
          ON indicators.corporate_guidance(cik,available_at);
    """)
    op.execute(f"GRANT SELECT ON ops.official_document_reviews TO {db}_runtime")
    op.execute(f"GRANT SELECT,INSERT ON ops.official_document_promotions TO {db}_runtime")


def downgrade() -> None:
    raise RuntimeError("restore an approved backup to downgrade")
