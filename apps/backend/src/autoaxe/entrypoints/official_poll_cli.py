"""A fixed-task, opt-in official feed daemon; no source is granted implicitly."""

import argparse
import os
import time
from functools import partial

import httpx
import psycopg

from autoaxe.application.official_poll import TASKS, fetch_release, poll_once
from autoaxe.infrastructure.market_store import PermissionDenied


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-approved", action="store_true")
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--tasks", nargs="+", required=True, choices=sorted(TASKS))
    args = parser.parse_args()
    dsn = os.getenv("AUTOAXE_MARKET_RUNTIME_DSN")
    if not args.execute_approved or not dsn:
        parser.error("explicit opt-in and existing runtime DB required")
    with httpx.Client(trust_env=False, follow_redirects=False, timeout=10) as client:
        while True:
            for task in sorted(set(args.tasks)):
                try:
                    result = poll_once(dsn, task, partial(fetch_release, task, client))
                    if result != "not_due":
                        print(f"{task}: {result}", flush=True)
                except (psycopg.Error, PermissionDenied, ValueError):
                    print(f"{task}: blocked_or_unavailable", flush=True)
            if not args.daemon:
                return
            time.sleep(60)


if __name__ == "__main__":
    main()
