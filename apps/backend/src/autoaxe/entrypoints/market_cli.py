"""Credential-free parser preview; persistence requires explicitly scoped fixture DB role."""

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

import psycopg

from autoaxe.adapters.manual import manual_candidates
from autoaxe.application.market_worker import run_one, submit_collection, synthetic_collect
from autoaxe.domain.catalog import catalog
from autoaxe.infrastructure.config import Settings
from autoaxe.infrastructure.market_store import ingest, review_manual


def main() -> None:
    Settings()
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("catalog")
    preview = sub.add_parser("manual-preview")
    preview.add_argument("csv", type=Path)
    collect = sub.add_parser("fixture-collect")
    collect.add_argument("--key", required=True)
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
    else:
        dsn = os.environ["AUTOAXE_FIXTURE_MARKET_WRITE_DSN"]
        if args.command == "fixture-collect":
            with psycopg.connect(dsn) as conn:
                job = submit_collection(conn, "FIXTURE_PRICE", "fixture-cli", args.key)
            result = run_one(dsn, synthetic_collect)
            print(json.dumps({"job_id": job, "worker_result": result}))
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
