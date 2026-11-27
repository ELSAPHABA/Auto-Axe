"""Append-only local operator evidence/review, current permission and PIT read fences.

Caller owns the transaction. No provider HTTP, and no publication of pending
or rejected claims. A new observed revision invalidates the prior assertion
at its first-seen cutoff until the new revision is checked.
"""

from dataclasses import asdict
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.rows import dict_row

from autoaxe.domain.calendars import FamilyState
from autoaxe.domain.canonical import canonical_sha256
from autoaxe.domain.expiry_evidence import (
    Decision,
    ExpiryClaim,
    ReviewedExpiry,
    check_candidate,
)
from autoaxe.domain.types import utc_datetime, utc_string
from autoaxe.infrastructure.market_store import PermissionDenied, verify_connection


def _permit(conn: Connection[Any], source: str, expected: int) -> None:
    if source not in ("occ", "cme") or expected < 1:
        raise PermissionDenied("invalid expiry source grant")
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"source:{source}",))
    row = conn.execute(
        """SELECT permission_status,free_only,allow_storage,verified_at,
                  evidence_ref,permission_version
           FROM catalog.source_registry WHERE source_id=%s""",
        (source,),
    ).fetchone()
    if (
        not row
        or tuple(row[:3]) != ("approved", True, True)
        or row[3] is None
        or not row[4]
        or row[5] != expected
    ):
        raise PermissionDenied("expiry storage permission denied or changed")


def submit_expiry(
    conn: Connection[Any],
    claim: ExpiryClaim,
    *,
    submitter_ref: str,
    expected_permission_version: int,
) -> tuple[UUID, int, bool]:
    verify_connection(conn, write=True)
    if not 0 < len(submitter_ref.strip()) <= 128:
        raise ValueError("invalid expiry submitter")
    _permit(conn, claim.source_id, expected_permission_version)
    key = (claim.source_id, claim.candidate_date, claim.family, claim.evidence_key)
    # The source transaction lock serializes all revisions and review operations.
    encoded = {
        k: utc_string(v) if isinstance(v, datetime) else v.isoformat() if isinstance(v, date) else v
        for k, v in asdict(claim).items()
    }
    digest = canonical_sha256(encoded)
    previous = conn.execute(
        """SELECT id,revision,content_hash,permission_version
           FROM indicators.expiry_evidence
           WHERE source_id=%s AND candidate_date=%s AND family=%s AND evidence_key=%s
           ORDER BY revision DESC LIMIT 1""",
        key,
    ).fetchone()
    if previous and previous[2] == digest and previous[3] == expected_permission_version:
        return UUID(str(previous[0])), int(previous[1]), False
    revision = int(previous[1]) + 1 if previous else 1
    identifier = uuid4()
    conn.execute(
        """INSERT INTO indicators.expiry_evidence
        (id,source_id,candidate_date,family,evidence_key,revision,status,session_date,
         contract_ref,nominal_expiry_date,last_trade_at,processing_at,settlement_at,
         settlement_basis,source_url,evidence_ref,family_coverage,
         last_trade_date,processing_date,settlement_date,submitter_ref,
         permission_version,content_hash)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            identifier,
            *key,
            revision,
            claim.status.value,
            claim.session_date,
            claim.contract_ref,
            claim.nominal_expiry_date,
            claim.last_trade_at,
            claim.processing_at,
            claim.settlement_at,
            claim.settlement_basis,
            claim.source_url,
            claim.evidence_ref,
            claim.family_coverage,
            claim.last_trade_date,
            claim.processing_date,
            claim.settlement_date,
            submitter_ref,
            expected_permission_version,
            digest,
        ),
    )
    return identifier, revision, True


def review_expiry(
    conn: Connection[Any],
    evidence_id: UUID,
    decision: Decision,
    *,
    reviewer_ref: str,
    reason: str,
    expected_permission_version: int,
) -> bool:
    verify_connection(conn, write=True)
    if (
        decision not in ("checked", "rejected")
        or not 0 < len(reviewer_ref.strip()) <= 128
        or not 0 < len(reason.strip()) <= 2000
    ):
        raise ValueError("invalid expiry review")
    row = conn.execute(
        """SELECT source_id,permission_version,candidate_date,family,evidence_key,revision,
                  submitter_ref
           FROM indicators.expiry_evidence WHERE id=%s""",
        (evidence_id,),
    ).fetchone()
    if not row or row[1] != expected_permission_version:
        raise PermissionDenied("expiry evidence missing or grant changed")
    _permit(conn, str(row[0]), expected_permission_version)
    if row[6] == reviewer_ref:
        raise ValueError("expiry self-review denied")
    latest = conn.execute(
        """SELECT max(revision) FROM indicators.expiry_evidence
           WHERE source_id=%s AND candidate_date=%s AND family=%s AND evidence_key=%s""",
        (row[0], row[2], row[3], row[4]),
    ).fetchone()
    if not latest or latest[0] != row[5]:
        raise ValueError("superseded expiry evidence cannot be reviewed")
    previous = conn.execute(
        "SELECT decision,reviewer_ref,reason FROM indicators.expiry_review WHERE evidence_id=%s",
        (evidence_id,),
    ).fetchone()
    if previous:
        if tuple(previous) != (decision, reviewer_ref, reason):
            raise ValueError("review is immutable; submit a new evidence revision")
        return False
    conn.execute(
        """INSERT INTO indicators.expiry_review(evidence_id,decision,reviewer_ref,reason)
           VALUES (%s,%s,%s,%s)""",
        (evidence_id, decision, reviewer_ref, reason),
    )
    return True


def query_expiry(
    conn: Connection[Any], *, candidate_date: date, cutoff: datetime, private_use: bool = False
) -> list[ReviewedExpiry]:
    verify_connection(conn, write=False)
    check_candidate(candidate_date)
    utc_datetime(cutoff)
    # Select latest OBSERVED revision before filtering review or permission, so
    # pending/rejected/corrected evidence never silently revives an older claim.
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            """WITH latest AS (
               SELECT DISTINCT ON (source_id,family,evidence_key) *
               FROM indicators.expiry_evidence WHERE candidate_date=%s AND first_seen_at<=%s
               ORDER BY source_id,family,evidence_key,revision DESC
            )
            SELECT e.*,v.reviewed_at FROM latest e
            JOIN indicators.expiry_review v ON v.evidence_id=e.id
            JOIN catalog.source_registry r ON r.source_id=e.source_id
            WHERE v.decision='checked' AND v.reviewed_at<=%s
              AND r.permission_status='approved' AND r.free_only AND r.allow_storage
              AND r.verified_at IS NOT NULL AND NULLIF(r.evidence_ref,'') IS NOT NULL
              AND r.permission_version=e.permission_version
              AND (r.allow_redistribution OR %s::boolean)
            ORDER BY e.session_date,e.family,e.evidence_key LIMIT 201""",
            (candidate_date, cutoff, cutoff, private_use),
        ).fetchall()
    if len(rows) > 200:
        raise ValueError("expiry evidence exceeds safe complete read bound")
    return [
        ReviewedExpiry(
            ExpiryClaim(
                r["candidate_date"],
                r["family"],
                r["source_id"],
                r["evidence_key"],
                FamilyState(r["status"]),
                r["session_date"],
                r["contract_ref"],
                r["nominal_expiry_date"],
                r["last_trade_at"],
                r["processing_at"],
                r["settlement_at"],
                r["settlement_basis"],
                r["source_url"],
                r["evidence_ref"],
                r["family_coverage"],
                r["last_trade_date"],
                r["processing_date"],
                r["settlement_date"],
            ),
            r["revision"],
            r["first_seen_at"],
            r["reviewed_at"],
            r["permission_version"],
        )
        for r in rows
    ]
