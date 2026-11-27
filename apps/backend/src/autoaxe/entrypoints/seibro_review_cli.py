"""Private SEIBro typed capture staging/promotion; never grants permission."""

import argparse
import os
import sys
from uuid import UUID

import psycopg

from autoaxe.application.seibro_review import promote_capture, stage_capture
from autoaxe.domain.canonical import strict_json
from autoaxe.infrastructure.market_store import PermissionDenied


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("stage")
    promote = commands.add_parser("promote")
    promote.add_argument("capture_id", type=UUID)
    args = parser.parse_args()
    dsn = os.getenv("AUTOAXE_MARKET_RUNTIME_DSN")
    if not dsn:
        parser.error("existing private runtime DB required")
    try:
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
    except (ValueError, PermissionDenied, psycopg.Error, TypeError):
        raise SystemExit("SEIBro review blocked or unavailable") from None
    print(result)


if __name__ == "__main__":
    main()
