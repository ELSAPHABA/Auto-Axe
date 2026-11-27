"""One-shot opt-in BOJ/SEC discovery or capture. Output is NOT reviewed data."""

import argparse
import json
import os

import httpx
import psycopg

from autoaxe.adapters.official_documents import discover_boj, discover_sec, fetch_boj, fetch_sec
from autoaxe.application.document_fetch import capture_once
from autoaxe.application.official_macro import OfficialSourceError
from autoaxe.infrastructure.market_store import PermissionDenied


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-approved", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    boj_list = commands.add_parser("discover-boj")
    boj_list.add_argument("year", type=int)
    boj = commands.add_parser("fetch-boj")
    boj.add_argument("url")
    sec_list = commands.add_parser("discover-sec")
    sec_list.add_argument("cik")
    sec = commands.add_parser("fetch-sec")
    sec.add_argument("cik")
    sec.add_argument("accession")
    args = parser.parse_args()
    dsn = os.getenv("AUTOAXE_MARKET_RUNTIME_DSN")
    if not args.execute_approved or not dsn:
        parser.error("explicit opt-in and existing runtime DB required")
    output: object
    try:
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=5) as client:
            if args.command == "discover-boj":
                output = capture_once(
                    dsn, "boj", lambda permit: discover_boj(client, args.year, permit)
                )
            elif args.command == "fetch-boj":
                output = capture_once(
                    dsn, "boj", lambda permit: fetch_boj(client, args.url, permit)
                ).model_dump(mode="json")
            elif args.command == "discover-sec":
                output = capture_once(
                    dsn,
                    "sec_edgar",
                    lambda permit: discover_sec(
                        client, args.cik, os.environ.get("AUTOAXE_SEC_CONTACT", ""), permit
                    ),
                )
            else:
                output = capture_once(
                    dsn,
                    "sec_edgar",
                    lambda permit: fetch_sec(
                        client,
                        args.cik,
                        args.accession,
                        os.environ.get("AUTOAXE_SEC_CONTACT", ""),
                        permit,
                    ),
                ).model_dump(mode="json")
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except (ValueError, TypeError, KeyError, PermissionDenied, OfficialSourceError, psycopg.Error):
        raise SystemExit("document capture rejected, not due or unavailable") from None


if __name__ == "__main__":
    main()
