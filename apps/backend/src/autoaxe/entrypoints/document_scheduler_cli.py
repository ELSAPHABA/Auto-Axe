"""Opt-in daemon for official BOJ/SEC document capture (review required)."""

import argparse
import os
import time

import httpx
import psycopg

from autoaxe.application.document_scheduler import scan_once
from autoaxe.application.official_macro import OfficialSourceError
from autoaxe.infrastructure.market_store import PermissionDenied


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-approved", action="store_true")
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--sources", nargs="+", choices=("boj", "sec_edgar"), required=True)
    parser.add_argument("--ciks", nargs="*", default=[])
    args = parser.parse_args()
    dsn = os.getenv("AUTOAXE_MARKET_RUNTIME_DSN")
    if not args.execute_approved or not dsn:
        parser.error("explicit opt-in and existing runtime DB required")
    if "sec_edgar" in args.sources and (not args.ciks or not os.getenv("AUTOAXE_SEC_CONTACT")):
        parser.error("SEC requires explicit CIKs and contact")
    with httpx.Client(trust_env=False, follow_redirects=False, timeout=5) as client:
        while True:
            for source in sorted(set(args.sources)):
                try:
                    result = scan_once(
                        dsn,
                        client,
                        source,
                        ciks=tuple(args.ciks),
                        contact=os.environ.get("AUTOAXE_SEC_CONTACT", ""),
                    )
                    status = result.capture.parse_status if result.capture else "no_new_document"
                    print(f"{source}: {status}", flush=True)
                except (PermissionDenied, OfficialSourceError, ValueError, psycopg.Error):
                    print(f"{source}: not_due_or_unavailable", flush=True)
            if not args.daemon:
                return
            time.sleep(60)


if __name__ == "__main__":
    main()
