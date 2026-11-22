#!/usr/bin/env python3
"""Record an Auto-Axe manual observation into a UTF-8 CSV (no API calls)."""
import argparse
import csv
import datetime as dt
import os
from pathlib import Path

HEADERS = [
    "series_id","instrument_type","source_url","as_of_utc",
    "collected_at_utc","frequency","value","unit","category",
    "quote_currency","exchange","contract","source_delay_minutes",
    "operator","note","verification_status"
]


def iso_utc(value: str) -> str:
    if not value:
        return ""
    stamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise argparse.ArgumentTypeError("as-of requires timezone offset (e.g. ...Z)")
    return stamp.astimezone(dt.timezone.utc).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series", required=True, help="e.g. CNN_FEAR_GREED")
    parser.add_argument("--source-url", required=True, help="exact source seen by operator")
    parser.add_argument("--value", required=True, help="observed number or textual status")
    parser.add_argument("--unit", required=True, help="index, percent, USD/bbl ...")
    parser.add_argument("--operator", required=True)
    parser.add_argument("--as-of", default="", help="source's published observation time ISO with zone, blank when unknown")
    parser.add_argument("--frequency", default="snapshot")
    parser.add_argument("--instrument-type", default="MANUAL_OBSERVATION")
    parser.add_argument("--category", default="")
    parser.add_argument("--quote-currency", default="")
    parser.add_argument("--exchange", default="")
    parser.add_argument("--contract", default="")
    parser.add_argument("--source-delay-minutes", default="")
    parser.add_argument("--note", default="")
    parser.add_argument("--output", default="auto_axe_manual_observations.csv")
    args = parser.parse_args()
    path = Path(args.output).expanduser().resolve()
    if path.exists() and path.is_dir():
        parser.error("--output must be a CSV file path")
    as_of = iso_utc(args.as_of)
    row = {
        "series_id": args.series,
        "instrument_type": args.instrument_type,
        "source_url": args.source_url,
        "as_of_utc": as_of,
        "collected_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "frequency": args.frequency,
        "value": args.value,
        "unit": args.unit,
        "category": args.category,
        "quote_currency": args.quote_currency,
        "exchange": args.exchange,
        "contract": args.contract,
        "source_delay_minutes": args.source_delay_minutes,
        "operator": args.operator,
        "note": args.note,
        "verification_status": "unverified"
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    first = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8-sig" if first else "utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=HEADERS)
        if first:
            writer.writeheader()
        writer.writerow(row)
    print(f"Recorded manual observation: {args.series} -> {path}")


if __name__ == "__main__":
    main()
