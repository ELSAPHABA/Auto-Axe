"""Append-only reviewed CNN graph points; expanded rights must be reviewed again."""

from alembic import op

revision = "0022_cnn_graphs"
down_revision = "0021_cnn_json_naver"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    db = conn.exec_driver_sql("SELECT current_database()").scalar_one()
    if db not in ("autoaxe_market", "autoaxe_dev", "autoaxe_test"):
        return
    op.execute("""
        CREATE TABLE indicators.cnn_graph_points (
            permission_version integer NOT NULL,
            source_id text NOT NULL DEFAULT 'cnn' CHECK (source_id='cnn'),
            graph_key text NOT NULL,
            point_at timestamptz NOT NULL,
            revision integer NOT NULL CHECK (revision>0),
            value numeric NOT NULL CHECK (value BETWEEN -1000000000000000 AND 1000000000000000),
            rating text CHECK (rating IN ('Extreme Fear','Fear','Neutral','Greed','Extreme Greed')),
            received_at timestamptz NOT NULL,
            available_at timestamptz NOT NULL,
            ingested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            job_id uuid NOT NULL REFERENCES ops.scrape_jobs(id),
            PRIMARY KEY(permission_version,graph_key,point_at,revision),
            FOREIGN KEY(source_id,permission_version)
                REFERENCES catalog.permission_versions(source_id,permission_version),
            CHECK (point_at<=received_at AND received_at<=available_at)
        );
        UPDATE catalog.source_registry SET permission_status='unverified',
            enabled=false,allow_fetch=false,allow_storage=false,
            allow_redistribution=false,allow_trading=false,verified_at=NULL,
            evidence_ref=NULL,permission_version=permission_version+1
        WHERE source_id='cnn';
        INSERT INTO catalog.permission_versions
            SELECT source_id,permission_version,to_jsonb(r)
            FROM catalog.source_registry r WHERE source_id='cnn';
        UPDATE ops.scrape_jobs SET status='revoked'
        WHERE source_id='cnn' AND status IN ('queued','leased');
    """)
    op.execute(f"GRANT SELECT,INSERT ON indicators.cnn_graph_points TO {db}_runtime")
    op.execute(f"GRANT SELECT ON indicators.cnn_graph_points TO {db}_read")


def downgrade() -> None:
    raise RuntimeError("restore an approved backup to downgrade")
