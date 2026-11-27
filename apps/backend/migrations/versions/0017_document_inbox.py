"""Durable official document capture, separate from approved reviews."""

from alembic import op

revision = "0017_document_inbox"
down_revision = "0016_mexc_ws"
branch_labels = None
depends_on = None


def upgrade() -> None:
    db = op.get_bind().exec_driver_sql("SELECT current_database()").scalar_one()
    if db not in ("autoaxe_market", "autoaxe_dev", "autoaxe_test"):
        return
    op.execute("""
        CREATE TABLE ops.official_document_inbox (
          id uuid PRIMARY KEY,
          source_id text NOT NULL CHECK(source_id IN ('boj','sec_edgar')),
          document_key text NOT NULL CHECK(length(document_key) BETWEEN 1 AND 80),
          source_url text NOT NULL CHECK(length(source_url) BETWEEN 1 AND 512),
          raw_sha256 char(64) NOT NULL CHECK(raw_sha256 ~ '^[a-f0-9]{64}$'),
          rendered_text text NOT NULL CHECK(octet_length(rendered_text)<=1000000),
          captured_at timestamptz NOT NULL,
          permission_version integer NOT NULL,
          parse_status text NOT NULL CHECK(parse_status IN ('parsed','review_required')),
          candidate jsonb,
          candidate_hash char(64),
          FOREIGN KEY(source_id,permission_version)
            REFERENCES catalog.permission_versions(source_id,permission_version),
          CHECK((parse_status='parsed' AND candidate IS NOT NULL AND candidate_hash IS NOT NULL)
             OR (parse_status='review_required' AND candidate IS NULL AND candidate_hash IS NULL)),
          UNIQUE(source_id,document_key,source_url,raw_sha256,permission_version)
        );
        CREATE INDEX official_inbox_key ON ops.official_document_inbox
          (source_id,permission_version,document_key);
        CREATE TABLE ops.official_document_scan_cursor (
          source_id text PRIMARY KEY CHECK(source_id IN ('boj','sec_edgar')),
          last_scope text NOT NULL CHECK(length(last_scope) BETWEEN 1 AND 16),
          checked_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
    """)
    op.execute(f"GRANT SELECT,INSERT ON ops.official_document_inbox TO {db}_runtime")
    op.execute(f"GRANT SELECT,INSERT,UPDATE ON ops.official_document_scan_cursor TO {db}_runtime")


def downgrade() -> None:
    raise RuntimeError("restore an approved backup to downgrade")
