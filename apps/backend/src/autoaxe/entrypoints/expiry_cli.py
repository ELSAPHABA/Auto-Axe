"""Local trusted runtime operator CLI; no HTTP, no implicit source approval.

Submit one typed JSON document and review its UUID in a separate operation.
The operator supplies the source grant version and review reference; this is
not a remotely accessible reviewer identity or browser mutation endpoint.
"""

import argparse
import os
from pathlib import Path
from uuid import UUID

import psycopg

from autoaxe.adapters.expiry_api import ExpiryClaimView
from autoaxe.domain.expiry_evidence import ExpiryClaim
from autoaxe.infrastructure.expiry_store import review_expiry, submit_expiry
from autoaxe.infrastructure.market_store import PermissionDenied


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--permission-version", type=int, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    submit = sub.add_parser("submit")
    submit.add_argument("file", type=Path)
    submit.add_argument("--submitter-ref", required=True)
    review = sub.add_parser("review")
    review.add_argument("evidence_id", type=UUID)
    review.add_argument("decision", choices=("checked", "rejected"))
    review.add_argument("--reviewer-ref", required=True)
    review.add_argument("--reason", required=True)
    args = parser.parse_args()
    dsn = os.environ.get("AUTOAXE_MARKET_RUNTIME_DSN")
    if not dsn:
        parser.error("AUTOAXE_MARKET_RUNTIME_DSN is required")
    try:
        claim = None
        if args.command == "submit":
            with args.file.open("rb") as file:
                payload = file.read(32769)
            if len(payload) > 32768:
                raise ValueError("evidence too large")
            view = ExpiryClaimView.model_validate_json(payload)
            claim = ExpiryClaim(**view.model_dump())
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            if claim is not None:
                identifier, revision, created = submit_expiry(
                    conn,
                    claim,
                    submitter_ref=args.submitter_ref,
                    expected_permission_version=args.permission_version,
                )
                result = f"{identifier} revision={revision} created={created}"
            else:
                created = review_expiry(
                    conn,
                    args.evidence_id,
                    args.decision,
                    reviewer_ref=args.reviewer_ref,
                    reason=args.reason,
                    expected_permission_version=args.permission_version,
                )
                result = f"{args.evidence_id} reviewed={created}"
        print(result, flush=True)
    except PermissionDenied:
        print("expiry evidence: permission denied", flush=True)
        raise SystemExit(1) from None
    except (ValueError, OSError, psycopg.Error):
        print("expiry evidence: invalid input or authority unavailable", flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
