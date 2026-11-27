"""Import explicitly authorized product calendars; no exchange scraping."""

from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.rows import dict_row

from autoaxe.domain.canonical import canonical_sha256
from autoaxe.domain.expiry_dte import ProductSessionCalendar
from autoaxe.domain.expiry_evidence import HOSTS, SOURCES, Decision, Family, Source
from autoaxe.domain.types import utc_datetime
from autoaxe.infrastructure.expiry_store import _permit
from autoaxe.infrastructure.market_store import PermissionDenied, verify_connection


def submit_calendar(
    conn: Connection[Any],
    *,
    source_id: Source,
    family: Family,
    contract_ref: str,
    coverage_start: date,
    coverage_end: date,
    sessions: tuple[date, ...],
    source_url: str,
    evidence_ref: str,
    submitter_ref: str,
    permission_version: int,
) -> tuple[UUID, int, bool]:
    verify_connection(conn, write=True)
    url = urlsplit(source_url)
    if (
        SOURCES.get(family) != source_id
        or url.scheme != "https"
        or url.hostname not in HOSTS[source_id]
        or url.username
        or url.password
        or url.port is not None
        or url.path in ("", "/")
        or len(source_url) > 2048
        or not 0 < len(submitter_ref.strip()) <= 128
        or not 0 < len(contract_ref.strip()) <= 256
        or not 0 < len(evidence_ref.strip()) <= 2000
        or not 1 <= len(sessions) <= 800
        or (coverage_end - coverage_start).days > 1096
        or tuple(sorted(set(sessions))) != sessions
        or any(not coverage_start <= day <= coverage_end for day in sessions)
    ):
        raise ValueError("invalid complete product calendar evidence")
    _permit(conn, source_id, permission_version)
    key = (source_id, family, contract_ref)
    digest = canonical_sha256(
        {
            "start": coverage_start.isoformat(),
            "end": coverage_end.isoformat(),
            "sessions": [day.isoformat() for day in sessions],
            "url": source_url,
            "evidence": evidence_ref,
        }
    )
    previous = conn.execute(
        """SELECT id,revision,content_hash,permission_version
       FROM indicators.expiry_product_calendar WHERE source_id=%s AND family=%s
       AND contract_ref=%s ORDER BY revision DESC LIMIT 1""",
        key,
    ).fetchone()
    if previous and previous[2] == digest and previous[3] == permission_version:
        return UUID(str(previous[0])), int(previous[1]), False
    revision = int(previous[1]) + 1 if previous else 1
    identifier = uuid4()
    conn.execute(
        """INSERT INTO indicators.expiry_product_calendar
       (id,source_id,family,contract_ref,revision,coverage_start,coverage_end,sessions,
        evidence_ref,source_url,submitter_ref,content_hash,permission_version)
       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            identifier,
            *key,
            revision,
            coverage_start,
            coverage_end,
            list(sessions),
            evidence_ref,
            source_url,
            submitter_ref,
            digest,
            permission_version,
        ),
    )
    return identifier, revision, True


def review_calendar(
    conn: Connection[Any],
    identifier: UUID,
    decision: Decision,
    *,
    reviewer_ref: str,
    reason: str,
    permission_version: int,
) -> bool:
    verify_connection(conn, write=True)
    if (
        decision not in ("checked", "rejected")
        or not 0 < len(reviewer_ref.strip()) <= 128
        or not 0 < len(reason.strip()) <= 2000
    ):
        raise ValueError("invalid calendar review")
    row = conn.execute(
        """SELECT source_id,family,contract_ref,revision,submitter_ref,
      permission_version FROM indicators.expiry_product_calendar WHERE id=%s""",
        (identifier,),
    ).fetchone()
    if not row or row[5] != permission_version:
        raise PermissionDenied("calendar grant changed")
    _permit(conn, str(row[0]), permission_version)
    if row[4] == reviewer_ref:
        raise ValueError("calendar self-review denied")
    latest = conn.execute(
        """SELECT max(revision) FROM indicators.expiry_product_calendar
      WHERE source_id=%s AND family=%s AND contract_ref=%s""",
        tuple(row[:3]),
    ).fetchone()
    if not latest or latest[0] != row[3]:
        raise ValueError("superseded calendar")
    prior = conn.execute(
        """SELECT decision,reviewer_ref,reason FROM
      indicators.expiry_product_calendar_review WHERE calendar_id=%s""",
        (identifier,),
    ).fetchone()
    if prior:
        if tuple(prior) != (decision, reviewer_ref, reason):
            raise ValueError("immutable review")
        return False
    conn.execute(
        """INSERT INTO indicators.expiry_product_calendar_review
      (calendar_id,decision,reviewer_ref,reason) VALUES (%s,%s,%s,%s)""",
        (identifier, decision, reviewer_ref, reason),
    )
    return True


def query_calendar(
    conn: Connection[Any],
    *,
    source_id: Source,
    family: Family,
    contract_ref: str,
    cutoff: datetime,
    private_use: bool,
) -> ProductSessionCalendar | None:
    verify_connection(conn, write=False)
    utc_datetime(cutoff)
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            """WITH latest AS (
          SELECT * FROM indicators.expiry_product_calendar
          WHERE source_id=%s AND family=%s AND contract_ref=%s AND first_seen_at<=%s
          ORDER BY revision DESC LIMIT 1)
          SELECT l.*,v.reviewed_at FROM latest l
          JOIN indicators.expiry_product_calendar_review v ON v.calendar_id=l.id
          JOIN catalog.source_registry r USING(source_id)
          WHERE v.decision='checked' AND v.reviewed_at<=%s
            AND r.permission_status='approved' AND r.free_only AND r.allow_storage
            AND r.verified_at IS NOT NULL AND NULLIF(r.evidence_ref,'') IS NOT NULL
            AND r.permission_version=l.permission_version
            AND (r.allow_redistribution OR %s::boolean)""",
            (source_id, family, contract_ref, cutoff, cutoff, private_use),
        ).fetchone()
    if not row:
        return None
    return ProductSessionCalendar(
        row["source_id"],
        row["family"],
        row["contract_ref"],
        row["permission_version"],
        row["coverage_start"],
        row["coverage_end"],
        tuple(row["sessions"]),
        row["reviewed_at"],
        row["evidence_ref"],
    )
