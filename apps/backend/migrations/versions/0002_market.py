"""Phase 1 catalog, partitioned immutable market ledger and durable event/job foundation."""

from alembic import op

revision = "0002_market"
down_revision = "0001_fixture"
branch_labels = None
depends_on = None

MARKET = """
CREATE SCHEMA catalog;
CREATE SCHEMA market;
CREATE TABLE catalog.source_registry (
 source_id text PRIMARY KEY, provider text NOT NULL, terms_url text NOT NULL,
 permission_status text NOT NULL CHECK (permission_status IN ('unverified','blocked','approved')),
 enabled boolean NOT NULL DEFAULT false, free_only boolean NOT NULL DEFAULT true CHECK (free_only),
 allow_fetch boolean NOT NULL DEFAULT false, allow_storage boolean NOT NULL DEFAULT false,
 allow_redistribution boolean NOT NULL DEFAULT false, allow_trading boolean NOT NULL DEFAULT false,
 verified_at timestamptz, evidence_ref text, permission_version integer NOT NULL DEFAULT 1,
 rate_limit_policy text NOT NULL DEFAULT 'unverified',
 CHECK (NOT enabled OR (permission_status='approved' AND allow_fetch AND allow_storage
  AND verified_at IS NOT NULL AND evidence_ref IS NOT NULL))
);
CREATE TABLE catalog.instruments (
 instrument_id text PRIMARY KEY, provider text NOT NULL, symbol text NOT NULL,
 instrument_type text NOT NULL, currency text, UNIQUE(provider,symbol,instrument_type)
);
CREATE TABLE catalog.permission_versions (
 source_id text NOT NULL REFERENCES catalog.source_registry,
 permission_version integer NOT NULL, definition jsonb NOT NULL,
 PRIMARY KEY(source_id,permission_version)
);
CREATE TABLE catalog.series (
 series_id text PRIMARY KEY, indicator_id text NOT NULL,
 source_id text NOT NULL REFERENCES catalog.source_registry,
 instrument_id text NOT NULL REFERENCES catalog.instruments,
 unit text NOT NULL, frequency text NOT NULL, ttl_seconds integer,
 priority integer NOT NULL, mapping_version integer NOT NULL
);
CREATE TABLE catalog.instrument_mappings (
 series_id text NOT NULL REFERENCES catalog.series, mapping_version integer NOT NULL,
 definition jsonb NOT NULL, PRIMARY KEY(series_id,mapping_version)
);
CREATE TABLE market.source_events (
 series_id text NOT NULL REFERENCES catalog.series, source_event_key text NOT NULL,
 revision integer NOT NULL, payload_hash text NOT NULL, partition_at timestamptz NOT NULL,
 observation_id uuid NOT NULL UNIQUE, PRIMARY KEY(series_id,source_event_key,revision),
 UNIQUE(series_id,source_event_key,payload_hash)
);
CREATE TABLE market.observations (
 partition_at timestamptz NOT NULL, observation_id uuid NOT NULL,
 series_id text NOT NULL REFERENCES catalog.series, source_event_key text NOT NULL,
 revision integer NOT NULL, mapping_version integer NOT NULL, permission_version integer NOT NULL,
 series_version bigint NOT NULL,
 source_event_at timestamptz, available_at timestamptz NOT NULL, received_at timestamptz NOT NULL,
 ingested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 value numeric, quality text NOT NULL, metadata jsonb NOT NULL,
 PRIMARY KEY(partition_at,observation_id),
 CHECK (available_at >= received_at),
 CHECK (source_event_at IS NULL OR source_event_at <= received_at),
 CHECK (quality <> 'valid' OR (value IS NOT NULL AND source_event_at IS NOT NULL)),
 CHECK (quality <> 'no_data' OR value IS NULL),
 CHECK (value IS NULL OR value NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric))
) PARTITION BY RANGE(partition_at);
CREATE TABLE market.observations_default PARTITION OF market.observations DEFAULT;
DO $$
DECLARE month_start date;
BEGIN
 FOR offset_month IN -1..2 LOOP
   month_start := (date_trunc('month',CURRENT_DATE) +
                   make_interval(months=>offset_month))::date;
   EXECUTE format('CREATE TABLE market.%I PARTITION OF market.observations
                  FOR VALUES FROM (%L) TO (%L)',
                  'observations_'||to_char(month_start,'YYYYMM'),
                  month_start::text||' 00:00:00+00',
                  (month_start+interval '1 month')::date::text||' 00:00:00+00');
 END LOOP;
END $$;
CREATE INDEX observations_series_time
 ON market.observations(series_id,partition_at DESC,observation_id);
CREATE INDEX observations_available ON market.observations(series_id,available_at);
CREATE TABLE market.latest_observations (
 series_id text PRIMARY KEY REFERENCES catalog.series, partition_at timestamptz NOT NULL,
 observation_id uuid NOT NULL, aggregate_version bigint NOT NULL,
 FOREIGN KEY(partition_at,observation_id) REFERENCES market.observations
);
CREATE TABLE market.series_versions (series_id text PRIMARY KEY REFERENCES catalog.series,
 version bigint NOT NULL);
CREATE TABLE market.source_selections (
 selection_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 indicator_id text NOT NULL, series_id text REFERENCES catalog.series,
 reason text NOT NULL, selected_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE market.manual_reviews (
 review_id uuid PRIMARY KEY,
 observation_id uuid NOT NULL REFERENCES market.source_events(observation_id),
 reviewer text NOT NULL, status text NOT NULL CHECK(status IN ('checked','rejected')),
 reviewed_at timestamptz NOT NULL DEFAULT clock_timestamp(), reason text NOT NULL
);
CREATE TABLE market.stream_checkpoints (
 series_id text PRIMARY KEY REFERENCES catalog.series, last_trade_id bigint NOT NULL
);
CREATE TABLE market.quarantine (
 quarantine_id uuid PRIMARY KEY, series_id text REFERENCES catalog.series,
 reason text NOT NULL, payload_hash text NOT NULL,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
"""
OPS = """
CREATE TABLE ops.jobs (
 id uuid PRIMARY KEY, kind text NOT NULL, owner_ref text NOT NULL, input_ref jsonb NOT NULL,
 input_version integer NOT NULL, idempotency_key text NOT NULL, payload_hash text NOT NULL,
 status text NOT NULL CHECK(status IN
 ('queued','running','succeeded','failed','cancel_requested','cancelled')),
 attempt integer NOT NULL DEFAULT 0,
 max_attempts integer NOT NULL CHECK(max_attempts BETWEEN 1 AND 10),
 available_at timestamptz NOT NULL, lease_until timestamptz, lease_token uuid,
 heartbeat_at timestamptz, progress integer NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 100),
 result_ref jsonb, error_code text, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 finished_at timestamptz, version bigint NOT NULL DEFAULT 1,
 UNIQUE(owner_ref,kind,idempotency_key)
);
CREATE INDEX jobs_claim ON ops.jobs(status,available_at,lease_until);
CREATE TABLE ops.job_attempts (
 job_id uuid NOT NULL REFERENCES ops.jobs, attempt integer NOT NULL, lease_token uuid NOT NULL,
 started_at timestamptz NOT NULL DEFAULT clock_timestamp(), ended_at timestamptz,
 outcome text, PRIMARY KEY(job_id,attempt)
);
CREATE TABLE ops.outbox (
 event_id uuid PRIMARY KEY, event_type text NOT NULL, schema_version integer NOT NULL,
 origin_db text NOT NULL, aggregate_type text NOT NULL, aggregate_id text NOT NULL,
 aggregate_version bigint NOT NULL, envelope jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(origin_db,aggregate_type,aggregate_id,aggregate_version)
);
CREATE TABLE ops.consumer_inbox (
 consumer text NOT NULL, event_id uuid NOT NULL, origin_db text NOT NULL,
 aggregate_type text NOT NULL, aggregate_id text NOT NULL, aggregate_version bigint NOT NULL,
 envelope jsonb NOT NULL, received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(consumer,event_id),
 UNIQUE(consumer,origin_db,aggregate_type,aggregate_id,aggregate_version)
);
CREATE TABLE ops.checkpoints (
 consumer text NOT NULL, origin_db text NOT NULL, aggregate_type text NOT NULL,
 aggregate_id text NOT NULL, aggregate_version bigint NOT NULL,
 PRIMARY KEY(consumer,origin_db,aggregate_type,aggregate_id)
);
CREATE TABLE ops.outbox_delivery (
 consumer text NOT NULL, event_id uuid NOT NULL REFERENCES ops.outbox,
 acknowledged_at timestamptz NOT NULL DEFAULT clock_timestamp(), PRIMARY KEY(consumer,event_id)
);
CREATE TABLE ops.collector_health (
 series_id text PRIMARY KEY, status text NOT NULL, reason text NOT NULL,
 checked_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
"""


def upgrade() -> None:
    db = op.get_bind().exec_driver_sql("SELECT current_database()").scalar_one()
    if db not in (
        "autoaxe_market",
        "autoaxe_app",
        "autoaxe_backtest",
        "autoaxe_dry_run",
        "autoaxe_paper_local",
        "autoaxe_paper_broker",
        "autoaxe_live",
        "autoaxe_dev",
        "autoaxe_test",
    ):
        return
    op.execute(OPS)
    runtime, reader, relay = (f"{db}_{r}" for r in ("runtime", "read", "relay"))
    op.execute(
        f"GRANT SELECT,INSERT,UPDATE ON ops.jobs,ops.job_attempts,ops.collector_health TO {runtime}"
    )
    op.execute(f"GRANT SELECT,INSERT ON ops.outbox,ops.consumer_inbox TO {runtime}")
    op.execute(f"GRANT SELECT,INSERT,UPDATE ON ops.checkpoints TO {runtime}")
    op.execute(f"GRANT SELECT ON ops.outbox TO {relay}")
    op.execute(f"GRANT SELECT,INSERT ON ops.outbox_delivery TO {relay}")
    op.execute(f"GRANT SELECT ON ops.jobs,ops.collector_health TO {reader}")
    if db not in ("autoaxe_market", "autoaxe_dev", "autoaxe_test"):
        return
    op.execute(MARKET)
    op.execute(f"GRANT USAGE ON SCHEMA catalog,market TO {runtime},{reader}")
    op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA catalog,market TO {reader}")
    op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA catalog TO {runtime}")
    op.execute(
        "GRANT SELECT,INSERT ON market.observations,market.source_events,"
        f"market.manual_reviews TO {runtime}"
    )
    op.execute(
        "GRANT SELECT,INSERT,UPDATE ON market.latest_observations,"
        f"market.series_versions TO {runtime}"
    )
    op.execute(f"GRANT SELECT,INSERT ON market.source_selections TO {runtime}")
    op.execute(f"GRANT SELECT,INSERT ON market.quarantine TO {runtime}")
    op.execute(f"GRANT SELECT,INSERT,UPDATE ON market.stream_checkpoints TO {runtime}")
    op.execute(f"GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA market TO {runtime}")


def downgrade() -> None:
    raise RuntimeError("destructive ledger downgrade prohibited; restore an approved backup")
