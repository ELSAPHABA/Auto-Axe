"""Explicit official document staging and trusted local review CLI."""

import argparse
from pathlib import Path

from autoaxe.application.equity_calendar_refresh import draft_summary, publish_reviewed, refresh


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("refresh")
    capture.add_argument("--symbol", choices=("NVDA", "QLD"), required=True)
    capture.add_argument("--allow-official-refresh", action="store_true", required=True)
    review = sub.add_parser("publish-reviewed")
    review.add_argument("--draft", type=Path, required=True)
    review.add_argument("--approve-reviewed", action="store_true", required=True)
    review.add_argument("--reviewer-ref")
    args = parser.parse_args()
    try:
        if args.command == "refresh":
            status = refresh(args.root, args.symbol, enabled=args.allow_official_refresh)
            print(status)
            if status not in {"pending_review", "not_due"}:
                raise SystemExit(1)
            summary = draft_summary(args.root, args.symbol)
            if summary is not None:
                path, rows = summary
                print(f"draft={path.resolve()}")
                for row in rows:
                    print(f"{row['symbol']} {row['year']} (pending review)")
                    print("  Closed: " + ", ".join(row["holidays"]))
                    print("  Early close 13:00 ET: " + ", ".join(row["early_closes"]))
        else:
            path, digest = publish_reviewed(
                args.root, args.draft, enabled=args.approve_reviewed, reviewer_ref=args.reviewer_ref
            )
            print(f"AUTOAXE_EQUITY_CALENDAR_MANIFEST={path.resolve()}")
            print(f"AUTOAXE_EQUITY_CALENDAR_SHA256={digest}")
    except (OSError, ValueError):
        parser.exit(1, "calendar refresh/review failed; existing reviewed manifest unchanged\n")


if __name__ == "__main__":
    main()
