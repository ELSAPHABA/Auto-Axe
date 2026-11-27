"""Phase 2 BFF identity and immutable indicator/event/scrape-broker foundation."""

from alembic import op

revision = "0004_phase2"
down_revision = "0003_polling"
branch_labels = None
depends_on = None

APP = """
CREATE SCHEMA IF NOT EXISTS identity;
CREATE TABLE identity.user_grants (
 subject_ref text PRIMARY KEY, role text NOT NULL,
 scopes jsonb NOT NULL DEFAULT '[]'::jsonb, auth_version bigint NOT NULL DEFAULT 1,
 revoked_at timestamptz
);
CREATE TABLE identity.oidc_states (
 state_hash char(64) PRIMARY KEY, nonce_hash char(64) NOT NULL,
 code_verifier_ciphertext bytea NOT NULL, expires_at timestamptz NOT NULL,
 consumed_at timestamptz
);
CREATE TABLE identity.web_sessions (
 session_hash char(64) PRIMARY KEY, subject_ref text NOT NULL
 REFERENCES identity.user_grants, csrf_hash char(64) NOT NULL,
 auth_version bigint NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 last_seen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 idle_expires_at timestamptz NOT NULL, absolute_expires_at timestamptz NOT NULL,
 revoked_at timestamptz, issuer text NOT NULL
);
CREATE INDEX web_sessions_expiration ON identity.web_sessions(idle_expires_at,absolute_expires_at);
"""

MARKET = """
CREATE SCHEMA IF NOT EXISTS indicators;
CREATE TABLE indicators.snapshot_revisions (
 id uuid PRIMARY KEY, series_id text NOT NULL, source_id text NOT NULL,
 source_event_key text NOT NULL, revision integer NOT NULL CHECK (revision > 0),
 value numeric, unit text NOT NULL, first_seen_at timestamptz NOT NULL,
 available_at timestamptz NOT NULL, source_event_at timestamptz,
 quality text NOT NULL, provenance jsonb NOT NULL,
 UNIQUE(series_id,source_event_key,revision),
 CHECK (available_at >= first_seen_at),
 CHECK (value IS NULL OR value NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric))
);
CREATE TABLE indicators.event_calendar (
 id uuid PRIMARY KEY, source_id text NOT NULL, event_uid text NOT NULL,
 revision integer NOT NULL CHECK(revision > 0),
 scheduled_at timestamptz, released_at timestamptz,
 first_seen_at timestamptz NOT NULL, available_at timestamptz NOT NULL,
 actual numeric, forecast numeric, previous numeric, unit text NOT NULL,
 nominal_expiration_at timestamptz, last_trade_at timestamptz,
 processing_at timestamptz, settlement_at timestamptz,
 effective_session_date date, product_family text, source_url text NOT NULL,
 provenance jsonb NOT NULL, UNIQUE(source_id,event_uid,revision),
 CHECK (available_at >= first_seen_at)
);
CREATE TABLE indicators.corporate_guidance (
 id uuid PRIMARY KEY, cik text NOT NULL, accession text NOT NULL,
 fiscal_period text NOT NULL, metric text NOT NULL, basis text NOT NULL
 CHECK(basis IN ('GAAP','ADJUSTED')), low numeric, high numeric,
 unit text NOT NULL, first_seen_at timestamptz NOT NULL,
 review_status text NOT NULL CHECK(review_status IN ('manual_review_required','checked')),
 source_url text NOT NULL, evidence jsonb NOT NULL,
 UNIQUE(cik,accession,fiscal_period,metric,basis),
 CHECK (low IS NULL OR high IS NULL OR low <= high)
);
CREATE TABLE ops.scrape_jobs (
 id uuid PRIMARY KEY, source_id text NOT NULL REFERENCES catalog.source_registry,
 adapter_version integer NOT NULL, schema_version integer NOT NULL DEFAULT 1,
 params jsonb NOT NULL, idempotency_key text NOT NULL,
 permission_version integer NOT NULL,
 status text NOT NULL CHECK (status IN
 ('queued','leased','succeeded','failed','quarantined','revoked')),
 nonce_hash char(64) NOT NULL, lease_hash char(64),
 lease_expires_at timestamptz, deadline_at timestamptz NOT NULL,
 attempt integer NOT NULL DEFAULT 0, max_attempts integer NOT NULL DEFAULT 3,
 result_hash char(64), candidate_count integer NOT NULL DEFAULT 0,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(source_id,idempotency_key)
);
CREATE INDEX scrape_jobs_claim ON ops.scrape_jobs(status,deadline_at,lease_expires_at);
CREATE TABLE ops.scrape_results (
 job_id uuid PRIMARY KEY REFERENCES ops.scrape_jobs,
 payload jsonb NOT NULL, result_hash char(64) NOT NULL,
 submitted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 review_status text NOT NULL DEFAULT 'quarantined'
 CHECK (review_status IN ('quarantined','checked','rejected'))
);
"""


def upgrade() -> None:
    db = op.get_bind().exec_driver_sql("SELECT current_database()").scalar_one()
    if db == "autoaxe_app":
        op.execute(APP)
        op.execute("GRANT USAGE ON SCHEMA identity TO autoaxe_app_runtime")
        op.execute(
            "GRANT SELECT,INSERT,UPDATE ON ALL TABLES IN SCHEMA identity TO autoaxe_app_runtime"
        )
        return
    if db not in ("autoaxe_market", "autoaxe_dev", "autoaxe_test"):
        return
    op.execute(MARKET)
    op.execute(f"GRANT USAGE ON SCHEMA indicators TO {db}_runtime,{db}_read")
    op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA indicators TO {db}_read")
    op.execute(f"GRANT SELECT,INSERT ON ALL TABLES IN SCHEMA indicators TO {db}_runtime")
    op.execute(f"GRANT SELECT,INSERT,UPDATE ON ops.scrape_jobs,ops.scrape_results TO {db}_runtime")


def downgrade() -> None:
    raise RuntimeError("Phase 2 identity/event ledger requires approved backup restore")
