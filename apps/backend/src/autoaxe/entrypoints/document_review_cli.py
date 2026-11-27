"""Offline official document candidate and explicit admin review/promote commands."""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from uuid import UUID

import psycopg

from autoaxe.domain.canonical import canonical_sha256, strict_json
from autoaxe.domain.reviewed_documents import (
    CompanyGuidance,
    PolicyDecision,
    extract_boj_policy,
    extract_guidance,
    sec_filing_refs,
    select_sec_exhibit,
)
from autoaxe.infrastructure.document_store import (
    ADAPTER,
    candidate_payload,
    promote_review,
    record_review,
)
from autoaxe.infrastructure.market_store import PermissionDenied


def read_text(path: Path) -> str:
    with path.open("rb") as stream:
        raw = stream.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("document too large")
    return raw.decode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inbox = commands.add_parser("inbox-list")
    inbox.add_argument("--limit", type=int, default=50)
    export = commands.add_parser("inbox-export")
    export.add_argument("capture_id", type=UUID)
    export.add_argument("--text", action="store_true")
    discover = commands.add_parser("discover-sec")
    discover.add_argument("submissions_file", type=Path)
    discover.add_argument("--cik", required=True)
    select = commands.add_parser("select-sec-exhibit")
    select.add_argument("filing_index_file", type=Path)
    select.add_argument("--cik", required=True)
    select.add_argument("--accession", required=True)
    for kind in ("extract-boj", "extract-sec"):
        extract = commands.add_parser(kind)
        extract.add_argument("text_file", type=Path)
        extract.add_argument("--source-url", required=True)
        extract.add_argument("--first-seen-at", required=True, type=datetime.fromisoformat)
        extract.add_argument("--issued-at", type=datetime.fromisoformat)
        if kind == "extract-sec":
            extract.add_argument("--cik", required=True)
            extract.add_argument("--accession", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("candidate_file", type=Path)
    review = commands.add_parser("approve")
    review.add_argument("candidate_file", type=Path)
    review.add_argument("--expected-hash", required=True)
    review.add_argument("--reviewer-ref", required=True)
    review.add_argument("--evidence-ref", required=True)
    promote = commands.add_parser("promote")
    promote.add_argument("review_id", type=UUID)
    args = parser.parse_args()
    candidate: PolicyDecision | CompanyGuidance
    try:
        if args.command in ("inbox-list", "inbox-export"):
            from psycopg.rows import dict_row

            with psycopg.connect(
                os.environ["AUTOAXE_DOCUMENT_REVIEW_ADMIN_DSN"],
                connect_timeout=3,
                row_factory=dict_row,
            ) as conn:
                if args.command == "inbox-list":
                    if not 1 <= args.limit <= 200:
                        raise ValueError("invalid inbox limit")
                    rows = conn.execute(
                        """SELECT id,source_id,document_key,source_url,raw_sha256,captured_at,
                                  permission_version,parse_status,candidate_hash
                           FROM ops.official_document_inbox
                           ORDER BY captured_at DESC,id LIMIT %s""",
                        (args.limit,),
                    ).fetchall()
                    print(json.dumps(rows, default=str, ensure_ascii=False, indent=2))
                else:
                    row = conn.execute(
                        """SELECT rendered_text,candidate FROM ops.official_document_inbox
                           WHERE id=%s""",
                        (args.capture_id,),
                    ).fetchone()
                    if row is None:
                        raise ValueError("capture not found")
                    if args.text:
                        print(row["rendered_text"])
                    elif row["candidate"] is None:
                        raise ValueError("capture requires manual extraction")
                    else:
                        print(json.dumps(row["candidate"], ensure_ascii=False, indent=2))
            return
        if args.command == "discover-sec":
            print(
                json.dumps(
                    sec_filing_refs(strict_json(read_text(args.submissions_file)), args.cik),
                    indent=2,
                )
            )
            return
        if args.command == "select-sec-exhibit":
            print(select_sec_exhibit(read_text(args.filing_index_file), args.cik, args.accession))
            return
        if args.command == "extract-boj":
            candidate = extract_boj_policy(
                read_text(args.text_file),
                args.source_url,
                args.first_seen_at,
                issued_at=args.issued_at,
            )
        elif args.command == "extract-sec":
            candidate = extract_guidance(
                read_text(args.text_file),
                args.source_url,
                args.cik,
                args.accession,
                args.first_seen_at,
                issued_at=args.issued_at,
            )
        elif args.command == "promote":
            with psycopg.connect(
                os.environ["AUTOAXE_MARKET_RUNTIME_DSN"], connect_timeout=3
            ) as conn:
                result = promote_review(conn, str(args.review_id))
            print(result)
            return
        else:
            candidate = ADAPTER.validate_python(strict_json(read_text(args.candidate_file)))
        payload = candidate_payload(candidate)
        if args.command == "approve":
            # Separate operator-only environment; never supply this to a runtime container.
            with psycopg.connect(
                os.environ["AUTOAXE_DOCUMENT_REVIEW_ADMIN_DSN"], connect_timeout=3
            ) as conn:
                review_id = record_review(
                    conn,
                    candidate,
                    expected_hash=args.expected_hash,
                    reviewer_ref=args.reviewer_ref,
                    evidence_ref=args.evidence_ref,
                )
            print(review_id)
        elif args.command == "inspect":
            print(canonical_sha256(payload))
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError, PermissionDenied, psycopg.Error):
        raise SystemExit("document operation rejected or unavailable") from None


if __name__ == "__main__":
    main()
