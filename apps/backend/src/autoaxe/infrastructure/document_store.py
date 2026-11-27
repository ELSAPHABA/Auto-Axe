"""Independent administrator review, atomic promotion, and PIT guidance reads."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import TypeAdapter

from autoaxe.domain.calendars import EventRevision
from autoaxe.domain.canonical import canonical_sha256
from autoaxe.domain.reviewed_documents import CompanyGuidance, PolicyDecision, ReviewedDocument
from autoaxe.domain.types import utc_datetime
from autoaxe.infrastructure.event_store import persist_event, require_event_permission
from autoaxe.infrastructure.market_store import PermissionDenied, verify_connection

ADAPTER: TypeAdapter[PolicyDecision | CompanyGuidance] = TypeAdapter(ReviewedDocument)


def candidate_payload(candidate: PolicyDecision | CompanyGuidance) -> dict[str, Any]:
    return candidate.model_dump(mode="json")


def source_of(candidate: PolicyDecision | CompanyGuidance) -> str:
    return "boj" if isinstance(candidate, PolicyDecision) else "sec_edgar"


def record_review(
    conn: Connection[Any],
    candidate: PolicyDecision | CompanyGuidance,
    *,
    expected_hash: str,
    reviewer_ref: str,
    evidence_ref: str,
) -> str:
    """Admin-only insert via DB grants; not exposed by BFF or collector.

    Administrator explicitly confirms the candidate hash after source review.
    Runtime DB roles have no INSERT privilege on this table.
    """
    source = source_of(candidate)
    payload = candidate_payload(candidate)
    digest = canonical_sha256(payload)
    if expected_hash != digest:
        raise ValueError("candidate hash changed")
    if not 1 <= len(reviewer_ref.strip()) <= 256 or not 1 <= len(evidence_ref.strip()) <= 512:
        raise ValueError("reviewer and source evidence required")
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("source:" + source,))
    row = conn.execute(
        """SELECT permission_version,clock_timestamp() FROM catalog.source_registry
           WHERE source_id=%s AND permission_status='approved' AND enabled
             AND free_only AND allow_fetch AND allow_storage
             AND verified_at IS NOT NULL AND length(trim(evidence_ref))>0""",
        (source,),
    ).fetchone()
    if row is None or candidate.first_seen_at > row[1]:
        raise PermissionDenied("source permission or capture time invalid")
    result = conn.execute(
        """INSERT INTO ops.official_document_reviews
           (id,source_id,permission_version,candidate,candidate_hash,reviewer_ref,evidence_ref)
           VALUES (%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT(source_id,permission_version,candidate_hash) DO NOTHING
           RETURNING id""",
        (str(uuid4()), source, row[0], Jsonb(payload), digest, reviewer_ref, evidence_ref),
    ).fetchone()
    if result is None:
        result = conn.execute(
            """SELECT id FROM ops.official_document_reviews
               WHERE source_id=%s AND permission_version=%s AND candidate_hash=%s""",
            (source, row[0], digest),
        ).fetchone()
    assert result is not None
    return str(result[0])


def promote_review(conn: Connection[Any], review_id: str) -> str:
    """Publish only a checked immutable hash with current permission."""
    verify_connection(conn, write=True)
    with conn.cursor(row_factory=dict_row) as cur:
        review = cur.execute(
            "SELECT * FROM ops.official_document_reviews WHERE id=%s", (review_id,)
        ).fetchone()
    if review is None:
        raise PermissionDenied("independent document review missing")
    source = review["source_id"]
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("source:" + source,))
    version = require_event_permission(conn, source)
    if version != review["permission_version"]:
        raise PermissionDenied("document permission changed")
    candidate = ADAPTER.validate_python(review["candidate"])
    if (
        canonical_sha256(candidate_payload(candidate)) != review["candidate_hash"]
        or source_of(candidate) != source
    ):
        raise PermissionDenied("document review hash mismatch")
    if conn.execute(
        "SELECT 1 FROM ops.official_document_promotions WHERE review_id=%s", (review_id,)
    ).fetchone():
        return "duplicate"
    clock = conn.execute("SELECT clock_timestamp()").fetchone()
    assert clock is not None
    now = clock[0]
    if not candidate.first_seen_at <= review["reviewed_at"] <= now:
        raise PermissionDenied("document review time invalid")
    if isinstance(candidate, PolicyDecision):
        # Keep ranges as independent endpoints; never collapse into a midpoint.
        for name, value in (("LOWER", candidate.low), ("UPPER", candidate.high)):
            persist_event(
                conn,
                EventRevision(
                    f"BOJ_POLICY_TARGET_{name}:{candidate.decision_date.isoformat()}",
                    "boj",
                    None,
                    candidate.issued_at,
                    candidate.first_seen_at,
                    now,
                    value,
                    None,
                    None,
                    "percent",
                    1,
                    candidate.source_url,
                ),
                expected_permission_version=version,
            )
    else:
        for item in candidate.values:
            # A new filing accession is a new immutable observation. Conflicting
            # values for the same accession/scope are not overwritten.
            evidence = {
                "document_sha256": candidate.document_sha256,
                "candidate_hash": review["candidate_hash"],
                "source_kind": "issuer_guidance",
            }
            row = conn.execute(
                """INSERT INTO indicators.corporate_guidance
                   (id,cik,accession,fiscal_period,metric,basis,low,high,unit,
                    first_seen_at,review_status,source_url,evidence,available_at,
                    issued_at,permission_version,review_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'checked',%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(cik,accession,fiscal_period,metric,basis) DO NOTHING
                   RETURNING id""",
                (
                    str(uuid4()),
                    candidate.cik,
                    candidate.accession,
                    item.fiscal_period,
                    item.metric,
                    item.basis,
                    Decimal(item.low),
                    Decimal(item.high),
                    item.unit,
                    candidate.first_seen_at,
                    candidate.source_url,
                    Jsonb(evidence),
                    now,
                    candidate.issued_at,
                    version,
                    review_id,
                ),
            ).fetchone()
            if row is None:
                prior = conn.execute(
                    """SELECT low,high,unit,source_url,evidence,issued_at,review_id
                       FROM indicators.corporate_guidance
                       WHERE cik=%s AND accession=%s AND fiscal_period=%s
                         AND metric=%s AND basis=%s""",
                    (
                        candidate.cik,
                        candidate.accession,
                        item.fiscal_period,
                        item.metric,
                        item.basis,
                    ),
                ).fetchone()
                if (
                    not prior
                    or prior[6] is None
                    or prior[:4]
                    != (Decimal(item.low), Decimal(item.high), item.unit, candidate.source_url)
                    or prior[4].get("document_sha256") != candidate.document_sha256
                    or prior[5] != candidate.issued_at
                ):
                    raise ValueError("conflicting guidance for immutable filing")
    conn.execute(
        "INSERT INTO ops.official_document_promotions(review_id) VALUES (%s)", (review_id,)
    )
    return "promoted"


def query_guidance(
    conn: Connection[Any],
    *,
    cutoff: datetime,
    private_use: bool,
    cik: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    verify_connection(conn, write=False)
    utc_datetime(cutoff)
    if not 1 <= limit <= 200:
        raise ValueError("invalid guidance limit")
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            """SELECT g.cik,g.accession,g.fiscal_period,g.metric,g.basis,g.low,g.high,g.unit,
                      g.source_url,g.issued_at,g.first_seen_at,g.available_at
               FROM indicators.corporate_guidance g
               JOIN catalog.source_registry r ON r.source_id='sec_edgar'
               WHERE g.review_id IS NOT NULL AND g.review_status='checked'
                 AND g.available_at<=%s AND r.permission_status='approved' AND r.enabled
                 AND r.free_only AND r.allow_fetch AND r.allow_storage
                 AND (r.allow_redistribution OR %s::boolean)
                 AND r.verified_at IS NOT NULL AND length(trim(r.evidence_ref))>0
                 AND (%s::text IS NULL OR g.cik=%s)
               ORDER BY g.available_at DESC,g.cik,g.accession,g.metric,g.basis LIMIT %s""",
            (cutoff, private_use, cik, cik, limit),
        ).fetchall()
    return rows
