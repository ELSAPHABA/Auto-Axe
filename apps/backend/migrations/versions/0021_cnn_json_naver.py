"""Retire the CNN HTML collection approval and extend Naver scheduling."""

from alembic import op

revision = "0021_cnn_json_naver"
down_revision = "0020_oil_ws"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.exec_driver_sql("SELECT current_database()").scalar_one() not in (
        "autoaxe_market",
        "autoaxe_dev",
        "autoaxe_test",
    ):
        return
    op.execute("""
        UPDATE catalog.source_registry SET
            terms_url='https://production.dataviz.cnn.io/index/fearandgreed/graphdata',
            permission_status='unverified', enabled=false, allow_fetch=false,
            allow_storage=false, allow_redistribution=false, allow_trading=false,
            verified_at=NULL, evidence_ref=NULL, permission_version=permission_version+1
        WHERE source_id='cnn';
        INSERT INTO catalog.permission_versions
            SELECT source_id,permission_version,to_jsonb(r)
            FROM catalog.source_registry r WHERE source_id='cnn';
        UPDATE ops.scrape_jobs SET status='revoked'
        WHERE source_id='cnn' AND status IN ('queued','leased');
        UPDATE ops.scrape_schedule s SET next_due_at=GREATEST(
            s.next_due_at+make_interval(secs=>900-j.schedule_interval_seconds),
            s.last_scheduled_at+interval '900 seconds')
        FROM ops.scrape_jobs j WHERE s.last_job_id=j.id AND s.source_id='naver'
            AND j.schedule_interval_seconds<900;
        UPDATE ops.scrape_jobs SET status='revoked'
        WHERE source_id='naver' AND status IN ('queued','leased')
            AND schedule_interval_seconds<900;
    """)


def downgrade() -> None:
    raise RuntimeError("restore an approved backup to downgrade")
