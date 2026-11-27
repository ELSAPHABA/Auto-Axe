"""Local trusted runtime operator CLI; no HTTP, no implicit source approval.

Submit one typed JSON document and review its UUID in a separate operation.
The operator supplies the source grant version and review reference; this is
not a remotely accessible reviewer identity or browser mutation endpoint.
"""

import argparse
import os
from datetime import date
from pathlib import Path
from uuid import UUID

import psycopg
from pydantic import BaseModel, ConfigDict, Field

from autoaxe.adapters.expiry_api import ExpiryClaimView
from autoaxe.domain.expiry_evidence import ExpiryClaim, Family, Source
from autoaxe.infrastructure.expiry_session_store import review_calendar, submit_calendar
from autoaxe.infrastructure.expiry_store import review_expiry, submit_expiry
from autoaxe.infrastructure.market_store import PermissionDenied


class CalendarInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: Source
    family: Family
    contract_ref: str
    coverage_start: date
    coverage_end: date
    sessions: tuple[date, ...] = Field(min_length=1, max_length=800)
    source_url: str
    evidence_ref: str


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
    cal = sub.add_parser("submit-calendar")
    cal.add_argument("file", type=Path)
    cal.add_argument("--submitter-ref", required=True)
    cal_review = sub.add_parser("review-calendar")
    cal_review.add_argument("evidence_id", type=UUID)
    cal_review.add_argument("decision", choices=("checked", "rejected"))
    cal_review.add_argument("--reviewer-ref", required=True)
    cal_review.add_argument("--reason", required=True)
    args = parser.parse_args()
    dsn = os.environ.get("AUTOAXE_MARKET_RUNTIME_DSN")
    if not dsn:
        parser.error("AUTOAXE_MARKET_RUNTIME_DSN is required")
    try:
        claim = None
        calendar = None
        if args.command in ("submit", "submit-calendar"):
            with args.file.open("rb") as file:
                payload = file.read(32769)
            if len(payload) > 32768:
                raise ValueError("evidence too large")
            if args.command == "submit":
                view = ExpiryClaimView.model_validate_json(payload)
                claim = ExpiryClaim(**view.model_dump())
            else:
                calendar = CalendarInput.model_validate_json(payload)
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            if claim is not None:
                identifier, revision, created = submit_expiry(
                    conn,
                    claim,
                    submitter_ref=args.submitter_ref,
                    expected_permission_version=args.permission_version,
                )
                result = f"{identifier} revision={revision} created={created}"
            elif calendar is not None:
                identifier, revision, created = submit_calendar(
                    conn,
                    **calendar.model_dump(),
                    submitter_ref=args.submitter_ref,
                    permission_version=args.permission_version,
                )
                result = f"{identifier} revision={revision} created={created}"
            elif args.command == "review-calendar":
                created = review_calendar(
                    conn,
                    args.evidence_id,
                    args.decision,
                    reviewer_ref=args.reviewer_ref,
                    reason=args.reason,
                    permission_version=args.permission_version,
                )
                result = f"{args.evidence_id} reviewed={created}"
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
