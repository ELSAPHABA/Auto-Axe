"""One-shot, explicitly opted-in official source collection (never scheduled)."""

import argparse
import json
import os

import httpx
import psycopg

from autoaxe.adapters.macro_sources import BLS_IDS
from autoaxe.application.official_macro import collect_bls_v1
from autoaxe.infrastructure.event_store import persist_event, require_event_permission
from autoaxe.infrastructure.official_quota import reserve_bls_v1


def main() -> None:
    parser = argparse.ArgumentParser(description="Authorized BLS API v1 official collection")
    parser.add_argument(
        "--execute-approved",
        action="store_true",
        help="Explicit one-shot invocation; still requires DB source approval",
    )
    parser.add_argument("--series", nargs="+", choices=sorted(BLS_IDS), required=True)
    args = parser.parse_args()
    if not args.execute_approved:
        parser.error("Live provider collection is disabled; --execute-approved required")
    dsn = os.environ.get("AUTOAXE_MARKET_RUNTIME_DSN")
    if not dsn:
        parser.error("AUTOAXE_MARKET_RUNTIME_DSN not configured")
    # Commit the request reservation before any external I/O. No auto retries.
    with psycopg.connect(dsn, connect_timeout=3) as conn:
        _, used, permission_version = reserve_bls_v1(conn)

    def authorized() -> None:
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            current = require_event_permission(conn, "bls")
            if current != permission_version:
                raise PermissionError("source approval changed during the request")

    with httpx.Client(trust_env=False, follow_redirects=False, timeout=10.0) as client:
        actuals = collect_bls_v1(client, authorize=authorized, series_ids=tuple(args.series))
    with psycopg.connect(dsn, connect_timeout=3) as conn:
        # All actuals are committed in one transaction or none at all.
        written = [
            persist_event(conn, item, expected_permission_version=permission_version)[1]
            for item in actuals
        ]
    print(
        json.dumps(
            {
                "source": "bls",
                "observations": len(actuals),
                "new_revisions": sum(written),
                "daily_requests_used": used,
            },
        )
    )


if __name__ == "__main__":
    main()
