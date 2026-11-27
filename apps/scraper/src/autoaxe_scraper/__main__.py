"""Explicit offline HTML parser CLI: never fetches network resources."""

import argparse
import json
from pathlib import Path

from autoaxe_scraper.parsers import parse_offline
from autoaxe_scraper.policy import SOURCES


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline parser fixture")
    parser.add_argument("source", choices=sorted(s for s, p in SOURCES.items() if not p.api_only))
    parser.add_argument("html", type=Path)
    args = parser.parse_args()
    if args.html.stat().st_size > 2_000_000:
        parser.error("HTML file too large")
    data = parse_offline(args.source, args.html.read_text(encoding="utf-8"))
    print(json.dumps(data, ensure_ascii=False))


if __name__ == "__main__":
    main()
