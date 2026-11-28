"""Private SEIBro typed capture staging/promotion; never grants permission."""

import argparse
import os
import sys
from uuid import UUID

import psycopg

from autoaxe.application.seibro_browser_runner import capture_daily, capture_once, run_daily_loop
from autoaxe.application.seibro_review import promote_capture, stage_capture
from autoaxe.domain.canonical import strict_json
from autoaxe.infrastructure.market_store import PermissionDenied


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("stage")
    promote = commands.add_parser("promote")
    promote.add_argument("capture_id", type=UUID)
    browser = commands.add_parser("capture-browser")
    browser.add_argument("--execute-approved", action="store_true", required=True)
    browser.add_argument("--egress-verified", action="store_true", required=True)
    browser.add_argument("--country", choices=["ALL", "US", "HK", "CN", "JP", "VN"], default="US")
    browser.add_argument("--period", choices=["1", "2", "3", "4", "5"], default="1")
    browser.add_argument("--basis", choices=["1", "2", "3", "4"], default="4")
    daily = commands.add_parser("capture-daily")
    daily.add_argument("--execute-approved", action="store_true", required=True)
    daily.add_argument("--egress-verified", action="store_true", required=True)
    daemon = commands.add_parser("run-daily")
    daemon.add_argument("--execute-approved", action="store_true", required=True)
    daemon.add_argument("--egress-verified", action="store_true", required=True)
    args = parser.parse_args()
    dsn = os.getenv("AUTOAXE_MARKET_RUNTIME_DSN")
    if not dsn:
        parser.error("existing private runtime DB required")
    try:
        if args.command in ("capture-browser", "capture-daily", "run-daily"):
            if not os.getenv("AUTOAXE_SEIBRO_RESTRICTED_EGRESS_NETWORK"):
                raise PermissionDenied("externally enforced browser network required")
            if args.command == "run-daily":
                run_daily_loop(dsn)
            elif args.command == "capture-daily":
                print(capture_daily(dsn))
            else:
                print(capture_once(dsn, country=args.country, period=args.period, basis=args.basis))
            return
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            if args.command == "stage":
                raw = sys.stdin.buffer.read(131_073)
                if len(raw) > 131_072:
                    raise ValueError("capture too large")
                capture_id, digest = stage_capture(conn, strict_json(raw.decode("utf-8")))
                result = f"staged {capture_id} {digest}"
            else:
                state, snapshot = promote_capture(conn, str(args.capture_id))
                result = f"{state} {snapshot or ''}".strip()
    except KeyboardInterrupt:
        return
    except (ValueError, PermissionDenied, psycopg.Error, TypeError, OSError, KeyError):
        raise SystemExit("SEIBro review blocked or unavailable") from None
    print(result)


if __name__ == "__main__":
    main()
