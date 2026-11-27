"""Immutable manual quarterly expiry evidence and review ledger."""

from alembic import op

revision = "0012_expiry_evidence"
down_revision = "0011_seibro"
branch_labels = None
depends_on = None


def upgrade() -> None:
    db = op.get_bind().exec_driver_sql("SELECT current_database()").scalar_one()
    if db not in ("autoaxe_market", "autoaxe_dev", "autoaxe_test"):
        return
    op.execute("""
    CREATE TABLE indicators.expiry_evidence (
        id uuid PRIMARY KEY,
        source_id text NOT NULL REFERENCES catalog.source_registry,
        candidate_date date NOT NULL,
        family text NOT NULL CHECK (
            family IN ('EQUITY_OPTION','INDEX_OPTION','INDEX_FUTURE','SINGLE_STOCK_FUTURE')
        ),
        evidence_key text NOT NULL CHECK (length(evidence_key) BETWEEN 1 AND 128),
        revision integer NOT NULL CHECK (revision > 0),
        status text NOT NULL CHECK (status IN ('YES','NO','UNKNOWN')),
        session_date date NOT NULL,
        contract_ref text,
        nominal_expiry_date date,
        last_trade_at timestamptz,
        processing_at timestamptz,
        settlement_at timestamptz,
        last_trade_date date,
        processing_date date,
        settlement_date date,
        settlement_basis text CHECK (settlement_basis IN ('AM','PM','OTHER')),
        source_url text NOT NULL,
        evidence_ref text NOT NULL,
        family_coverage boolean NOT NULL,
        submitter_ref text NOT NULL CHECK (length(submitter_ref) BETWEEN 1 AND 128),
        permission_version integer NOT NULL CHECK (permission_version > 0),
        content_hash char(64) NOT NULL,
        first_seen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        UNIQUE(source_id,candidate_date,family,evidence_key,revision),
        CHECK (
            (source_id='occ' AND family IN ('EQUITY_OPTION','INDEX_OPTION'))
            OR (source_id='cme' AND family IN ('INDEX_FUTURE','SINGLE_STOCK_FUTURE'))
        ),
        CHECK (status <> 'YES' OR (contract_ref IS NOT NULL AND nominal_expiry_date IS NOT NULL)),
        CHECK (status <> 'NO' OR family_coverage),
        CHECK (abs(session_date - candidate_date) <= 7),
        CHECK (status='YES' OR (
            contract_ref IS NULL AND nominal_expiry_date IS NULL AND last_trade_at IS NULL
            AND processing_at IS NULL AND settlement_at IS NULL AND settlement_basis IS NULL
            AND last_trade_date IS NULL AND processing_date IS NULL AND settlement_date IS NULL
        ))
    );
    CREATE INDEX expiry_evidence_pit ON indicators.expiry_evidence
       (candidate_date,source_id,family,evidence_key,revision DESC);
    CREATE TABLE indicators.expiry_review (
        evidence_id uuid PRIMARY KEY REFERENCES indicators.expiry_evidence,
        decision text NOT NULL CHECK (decision IN ('checked','rejected')),
        reviewer_ref text NOT NULL CHECK (length(reviewer_ref) BETWEEN 1 AND 128),
        reason text NOT NULL CHECK (length(reason) BETWEEN 1 AND 2000),
        reviewed_at timestamptz NOT NULL DEFAULT clock_timestamp()
    );
    """)
    op.execute(
        "GRANT SELECT,INSERT ON indicators.expiry_evidence,indicators.expiry_review "
        f"TO {db}_runtime"
    )
    op.execute(f"GRANT SELECT ON indicators.expiry_evidence,indicators.expiry_review TO {db}_read")


def downgrade() -> None:
    raise RuntimeError("restore an approved backup to downgrade expiry review ledger")
