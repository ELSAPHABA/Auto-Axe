"""Approved BOJ/SEC periodic capture into an immutable review inbox."""

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import psycopg
from psycopg import Connection
from psycopg.types.json import Jsonb

from autoaxe.adapters.official_documents import (
    DocumentCapture,
    capture_boj,
    capture_sec_ref,
    discover_boj,
    discover_sec,
)
from autoaxe.application.document_fetch import capture_once
from autoaxe.domain.canonical import canonical_sha256
from autoaxe.domain.reviewed_documents import boj_date
from autoaxe.infrastructure.document_store import candidate_payload, source_of
from autoaxe.infrastructure.event_store import require_event_permission
from autoaxe.infrastructure.market_store import PermissionDenied, verify_connection


@dataclass(frozen=True)
class Scan:
    scope: str
    capture: DocumentCapture | None


def next_scope(scopes: tuple[str, ...], previous: str | None) -> str:
    if not scopes:
        raise ValueError("empty document scan scopes")
    if previous not in scopes:
        return scopes[0]
    return scopes[(scopes.index(previous) + 1) % len(scopes)]


def _seen(conn: Connection[Any], source: str, version: int, keys: list[str]) -> set[str]:
    rows = conn.execute(
        """SELECT DISTINCT document_key FROM ops.official_document_inbox
           WHERE source_id=%s AND permission_version=%s AND document_key=ANY(%s)""",
        (source, version, keys),
    ).fetchall()
    return {str(row[0]) for row in rows}


def save_scan(conn: Connection[Any], source: str, scan: Scan, version: int) -> None:
    """Called inside the source lock/permission fence, never publishes values."""
    if require_event_permission(conn, source) != version:
        raise PermissionDenied("document grant changed")
    item = scan.capture
    if item is not None:
        if item.source_id != source or not re.fullmatch(r"[a-f0-9]{64}", item.raw_sha256):
            raise ValueError("invalid document capture")
        payload = candidate_payload(item.candidate) if item.candidate else None
        if item.candidate is not None and (
            source_of(item.candidate) != source
            or item.candidate.source_url != item.source_url
            or item.candidate.first_seen_at != item.captured_at
            or item.candidate.document_sha256 != hashlib.sha256(item.text.encode()).hexdigest()
        ):
            raise ValueError("document candidate does not match rendered evidence")
        conn.execute(
            """INSERT INTO ops.official_document_inbox
               (id,source_id,document_key,source_url,raw_sha256,rendered_text,
                captured_at,permission_version,parse_status,candidate,candidate_hash)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT(source_id,document_key,source_url,raw_sha256,permission_version)
               DO NOTHING""",
            (
                str(uuid4()),
                source,
                item.document_key,
                item.source_url,
                item.raw_sha256,
                item.text,
                item.captured_at,
                version,
                item.parse_status,
                Jsonb(payload) if payload else None,
                canonical_sha256(payload) if payload else None,
            ),
        )
    conn.execute(
        """INSERT INTO ops.official_document_scan_cursor(source_id,last_scope)
           VALUES(%s,%s) ON CONFLICT(source_id) DO UPDATE SET
           last_scope=EXCLUDED.last_scope,checked_at=clock_timestamp()""",
        (source, scan.scope),
    )


def scan_once(
    dsn: str,
    client: httpx.Client,
    source: str,
    *,
    ciks: tuple[str, ...] = (),
    contact: str = "",
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Scan:
    """One bounded scan per reserved source slot, rotating SEC issuers durably."""
    if source not in ("boj", "sec_edgar"):
        raise ValueError("unsupported document source")
    if source == "sec_edgar" and (
        not 1 <= len(ciks) <= 32
        or len(set(ciks)) != len(ciks)
        or any(not re.fullmatch(r"\d{10}", cik) or not int(cik) for cik in ciks)
    ):
        raise ValueError("configure 1 to 32 unique SEC CIKs")

    def fetch(permit: Callable[[], None]) -> Scan:
        permit()
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            verify_connection(conn, write=True)
            version = require_event_permission(conn, source)
            now = clock()
            if source == "boj":
                year = now.year
                links = discover_boj(client, year, permit, clock=clock)
                # Prefer HTML over PDF of the same statement when both exist.
                selected: dict[str, str] = {}
                for url in links:
                    key = boj_date(url).isoformat()
                    if boj_date(url) <= now.date() and (
                        key not in selected or url.endswith(".htm")
                    ):
                        selected[key] = url
                seen = _seen(conn, source, version, list(selected))
                pending = sorted(set(selected) - seen, reverse=True)
                if not pending:
                    return Scan(str(year), None)
                return Scan(
                    str(year), capture_boj(client, selected[pending[0]], permit, clock=clock)
                )
            previous = conn.execute(
                "SELECT last_scope FROM ops.official_document_scan_cursor WHERE source_id=%s",
                (source,),
            ).fetchone()
            cik = next_scope(ciks, str(previous[0]) if previous else None)
            refs = [
                row
                for row in discover_sec(client, cik, contact, permit)
                if now - timedelta(days=90) <= datetime.fromisoformat(row["accepted_at"]) <= now
            ]
            refs.sort(key=lambda row: (row["accepted_at"], row["accession"]), reverse=True)
            seen = _seen(conn, source, version, [f"{cik}:{row['accession']}" for row in refs])
            for row in refs:
                if f"{cik}:{row['accession']}" not in seen:
                    return Scan(
                        cik, capture_sec_ref(client, cik, row, contact, permit, clock=clock)
                    )
            return Scan(cik, None)

    return capture_once(
        dsn,
        source,
        fetch,
        persist=lambda conn, result, version: save_scan(conn, source, result, version),
    )
