"""Schedule approved generic HTTP jobs or consume independent admin review decisions.

This process never contacts providers. Run an isolated worker separately.
No adapter grant or review approval is created by this CLI.
"""

import argparse
import os
import time
from uuid import UUID

import psycopg

from autoaxe.application.scrape_broker import SERIES, promote_reviewed, schedule_due
from autoaxe.infrastructure.market_store import PermissionDenied


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    schedule = commands.add_parser("schedule")
    schedule.add_argument("--sources", choices=sorted(SERIES), nargs="+", required=True)
    schedule.add_argument("--daemon", action="store_true")
    promote = commands.add_parser("promote")
    promote.add_argument("job_id", type=UUID)
    args = parser.parse_args()
    dsn = os.getenv("AUTOAXE_SCRAPE_BROKER_MARKET_DSN")
    if not dsn:
        parser.error("existing broker runtime DB required")
    if args.command == "promote":
        try:
            with psycopg.connect(dsn, connect_timeout=3) as conn:
                result = promote_reviewed(conn, str(args.job_id))
        except (psycopg.Error, PermissionDenied, ValueError):
            raise SystemExit("review promotion blocked or unavailable") from None
        print(result, flush=True)
        return
    while True:
        for source in sorted(set(args.sources)):
            try:
                with psycopg.connect(dsn, connect_timeout=3) as conn:
                    state = schedule_due(conn, source)
                if state != "not_due":
                    print(f"{source}: {state}", flush=True)
            except (psycopg.Error, PermissionDenied, ValueError):
                print(f"{source}: blocked_or_unavailable", flush=True)
        if not args.daemon:
            return
        time.sleep(60)


if __name__ == "__main__":
    main()
