"""Credential-free parser preview; persistence requires explicitly scoped fixture DB role."""

import argparse
import json
import os
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import psycopg

from autoaxe.adapters.manual import manual_candidates
from autoaxe.adapters.references import COMMANDS, normalize_reference
from autoaxe.application.market_worker import run_one, submit_collection, synthetic_collect
from autoaxe.application.polling import tick
from autoaxe.domain.canonical import strict_json
from autoaxe.domain.catalog import catalog
from autoaxe.domain.types import utc_datetime
from autoaxe.infrastructure.config import Settings
from autoaxe.infrastructure.market_store import ingest, review_manual


def main() -> None:
    Settings()
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("catalog")
    preview = sub.add_parser("manual-preview")
    preview.add_argument("csv", type=Path)
    for name in ("reference-preview", "reference-import"):
        ref = sub.add_parser(name)
        ref.add_argument("source", choices=COMMANDS)
        ref.add_argument("json", type=Path)
        ref.add_argument("--received-at", required=True)
        ref.add_argument("--symbol")
    collect = sub.add_parser("fixture-collect")
    collect.add_argument("--key", required=True)
    poll = sub.add_parser("fixture-poll")
    poll.add_argument("--cycles", type=int, default=1)
    poll.add_argument("--sleep", type=float, default=5)
    manual = sub.add_parser("manual-import")
    manual.add_argument("csv", type=Path)
    review = sub.add_parser("manual-review")
    review.add_argument("observation_id")
    review.add_argument("--reviewer", required=True)
    review.add_argument("--status", choices=["checked", "rejected"], required=True)
    review.add_argument("--reason", required=True)
    args = parser.parse_args()
    if args.command == "catalog":
        print(json.dumps([asdict(x) for x in catalog().values()], ensure_ascii=False))
    elif args.command == "manual-preview":
        for item in manual_candidates(args.csv.read_text(encoding="utf-8-sig")):
            print(json.dumps(asdict(item), default=str, ensure_ascii=False))
    elif args.command in ("reference-preview", "reference-import"):
        if args.json.stat().st_size > 2_000_000:
            parser.error("reference payload too large")
        raw = strict_json(args.json.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            parser.error("reference payload must be an object")
        rows = normalize_reference(
            args.source,
            raw,
            utc_datetime(datetime.fromisoformat(args.received_at)),
            symbol=args.symbol,
        )
        if args.command == "reference-preview":
            for row in rows:
                print(json.dumps(asdict(row), default=str, ensure_ascii=False))
        else:
            with psycopg.connect(os.environ["AUTOAXE_FIXTURE_MARKET_WRITE_DSN"]) as conn:
                print(json.dumps({"inserted": sum(ingest(conn, row)[2] for row in rows)}))
    else:
        dsn = os.environ["AUTOAXE_FIXTURE_MARKET_WRITE_DSN"]
        if args.command == "fixture-collect":
            with psycopg.connect(dsn) as conn:
                job = submit_collection(conn, "FIXTURE_PRICE", "fixture-cli", args.key)
            result = run_one(dsn, synthetic_collect, owner="fixture-cli", series=["FIXTURE_PRICE"])
            print(json.dumps({"job_id": job, "worker_result": result}))
        elif args.command == "fixture-poll":
            if not 1 <= args.cycles <= 120 or not 1 <= args.sleep <= 300:
                parser.error("invalid bounded fixture poll options")
            for i in range(args.cycles):
                print(json.dumps(tick(dsn, ["FIXTURE_PRICE"], synthetic_collect)), flush=True)
                if i + 1 < args.cycles:
                    time.sleep(args.sleep)
        elif args.command == "manual-import":
            items = manual_candidates(args.csv.read_text(encoding="utf-8-sig"))
            with psycopg.connect(dsn) as conn:
                result_count = sum(ingest(conn, item)[2] for item in items)
            print(json.dumps({"inserted": result_count}))
        elif args.command == "manual-review":
            with psycopg.connect(dsn) as conn:
                review_id = review_manual(
                    conn, args.observation_id, args.reviewer, args.status, args.reason
                )
            print(json.dumps({"review_id": review_id}))


if __name__ == "__main__":
    main()
