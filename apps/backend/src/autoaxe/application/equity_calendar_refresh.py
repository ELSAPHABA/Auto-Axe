"""Fixed-source local calendar evidence staging; never auto-promote a schedule.

No market price requests, no redirect, browser, proxy, or retry. A trusted
operator explicitly approves document retrieval and later reviews the exact
archived source, including all exceptions and regular-session scope.
"""

import hashlib
import json
import os
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from autoaxe.adapters.equity_calendar_html import extract_years
from autoaxe.domain.canonical import strict_json
from autoaxe.domain.equity_calendar import (
    MAX_MANIFEST_BYTES,
    SOURCE_URLS,
    load_calendar,
    manifest_rows,
)
from autoaxe.domain.types import utc_datetime, utc_string
from autoaxe.infrastructure.jobs import retry_after

MAX_DOCUMENT_BYTES = 4_000_000
REFRESH_SECONDS = 86400


@contextmanager
def _lock(root: Path) -> Iterator[None]:
    """Local filesystem lock released on process exit, including crashes."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / "refresh.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic(path: Path, raw: bytes) -> None:
    fd, name = tempfile.mkstemp(prefix=".calendar-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        if os.name != "nt":
            parent_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
    finally:
        Path(name).unlink(missing_ok=True)


def _json(path: Path, limit: int = MAX_MANIFEST_BYTES) -> Any:
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if not raw or len(raw) > limit:
        raise ValueError("invalid calendar state size")
    return strict_json(raw.decode("utf-8"))


def _write_json(path: Path, obj: object) -> None:
    _atomic(path, json.dumps(obj, sort_keys=True, separators=(",", ":")).encode())


def _immutable(path: Path, raw: bytes) -> None:
    if path.exists():
        with path.open("rb") as handle:
            if handle.read(len(raw) + 1) != raw:
                raise ValueError("calendar evidence integrity mismatch")
    else:
        _atomic(path, raw)


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("invalid calendar refresh timestamp")
    return utc_datetime(datetime.fromisoformat(value))


def _draft(symbol: str, body: bytes, sha: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "years": [
            {
                "symbol": symbol,
                "year": row.year,
                "source_url": SOURCE_URLS[symbol],
                "evidence_sha256": sha,
                "reviewed_on": None,
                "reviewer_ref": None,
                "complete": True,
                "holidays": list(row.holidays),
                "early_closes": list(row.early_closes),
            }
            for row in extract_years(symbol, body)
        ],
    }


def draft_summary(root: Path, symbol: str) -> tuple[Path, list[dict[str, Any]]] | None:
    """Read only the last successful extraction, including on a not-due run."""
    if symbol not in SOURCE_URLS:
        raise ValueError("unknown calendar exchange")
    with _lock(root):
        state = _json(root / f"{symbol}-refresh.json")
        if state.get("status") != "pending_review":
            return None
        sha = state.get("evidence_sha256")
        if (
            not isinstance(sha, str)
            or len(sha) != 64
            or any(c not in "0123456789abcdef" for c in sha)
        ):
            raise ValueError("invalid evidence digest")
        path = root / f"{symbol}-{sha}-draft.json"
        return path, _json(path)["years"]


def refresh(
    root: Path,
    symbol: str,
    *,
    enabled: bool = False,
    transport: httpx.BaseTransport | None = None,
    now: datetime | None = None,
) -> str:
    """One fixed-source capture attempt; durable cooldown per exchange."""
    if not enabled:
        raise ValueError("explicit official calendar refresh opt-in required")
    if symbol not in SOURCE_URLS:
        raise ValueError("unknown calendar exchange")
    now = utc_datetime(now or datetime.now(UTC))
    with _lock(root):
        state_path = root / f"{symbol}-refresh.json"
        if state_path.exists():
            state = _json(state_path)
            if not isinstance(state, dict) or state.get("source_url") != SOURCE_URLS[symbol]:
                raise ValueError("invalid calendar refresh state")
            if state.get("blocked") is True:
                return "blocked"
            if now < _timestamp(state["next_attempt_at"]):
                return "not_due"
        state = {
            "source_url": SOURCE_URLS[symbol],
            "attempt_at": utc_string(now),
            "next_attempt_at": utc_string(now + timedelta(seconds=REFRESH_SECONDS)),
            "blocked": False,
            "status": "reserved",
        }
        # Commit the reservation before creating the client/network request.
        _write_json(state_path, state)
        try:
            started = time.monotonic()
            with httpx.Client(
                timeout=10,
                follow_redirects=False,
                trust_env=False,
                headers={"Accept": "text/html", "Accept-Encoding": "identity"},
                transport=transport,
            ) as client:
                with client.stream("GET", SOURCE_URLS[symbol]) as response:
                    if response.status_code != 200:
                        status = response.status_code
                        state["status"] = f"http_{status}"
                        if status not in (429, 500, 502, 503, 504):
                            state["blocked"] = True
                        elif status == 429 or response.headers.get("Retry-After"):
                            delay = retry_after(1, response.headers.get("Retry-After"), now)
                            if delay > 604800 or not 0 <= delay < float("inf"):
                                state["blocked"] = True
                            else:
                                state["next_attempt_at"] = utc_string(
                                    now + timedelta(seconds=max(REFRESH_SECONDS, delay))
                                )
                        _write_json(state_path, state)
                        return str(state["status"])
                    media = response.headers.get("Content-Type", "").split(";", 1)[0].strip()
                    if media.lower() != "text/html":
                        raise ValueError("unexpected calendar response media type")
                    if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                        raise ValueError("unexpected calendar response encoding")
                    raw = bytearray()
                    for chunk in response.iter_raw():
                        raw.extend(chunk)
                        if len(raw) > MAX_DOCUMENT_BYTES or time.monotonic() - started > 30:
                            raise ValueError("calendar document exceeds bounds")
            if not raw:
                raise ValueError("empty calendar document")
            body = bytes(raw)
            sha = hashlib.sha256(body).hexdigest()
            document = root / f"{symbol}-{sha}.html"
            receipt = root / f"{symbol}-{sha}.json"
            _immutable(document, body)
            if not receipt.exists():
                _write_json(
                    receipt,
                    {
                        "symbol": symbol,
                        "source_url": SOURCE_URLS[symbol],
                        "evidence_sha256": sha,
                        "captured_at": utc_string(now),
                        "review_status": "pending",
                    },
                )
            state["evidence_sha256"] = sha
            try:
                draft = _draft(symbol, body, sha)
            except ValueError:
                state["status"] = "parse_rejected"
            else:
                raw_draft = json.dumps(draft, sort_keys=True, indent=2).encode()
                _immutable(root / f"{symbol}-{sha}-draft.json", raw_draft)
                state["status"] = "pending_review"
        except (httpx.HTTPError, OSError, ValueError):
            state["status"] = "capture_failed"
        _write_json(state_path, state)
        return str(state["status"])


def publish_reviewed(
    root: Path, draft: Path, *, enabled: bool = False, reviewer_ref: str | None = None
) -> tuple[Path, str]:
    """Publish immutable manifest only after explicit trusted operator review.

    Manual review must establish completeness and compare all dates against the
    archived official page. This routine validates provenance/shape, not the
    reviewer's semantic interpretation or identity. Activation is separate:
    configure path AND exact digest in the history process.
    """
    if not enabled:
        raise ValueError("explicit calendar review approval required")
    with draft.open("rb") as handle:
        raw = handle.read(MAX_MANIFEST_BYTES + 1)
    if reviewer_ref is not None:
        if len(raw) > MAX_MANIFEST_BYTES or not reviewer_ref.strip() or len(reviewer_ref) > 256:
            raise ValueError("invalid review input")
        data = strict_json(raw.decode("utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("years"), list):
            raise ValueError("invalid automatic draft")
        draft_rows = data["years"]
        if not draft_rows or any(not isinstance(r, dict) for r in draft_rows):
            raise ValueError("invalid automatic draft rows")
        first = draft_rows[0]
        symbol, sha = first.get("symbol"), first.get("evidence_sha256")
        if (
            not isinstance(symbol, str)
            or symbol not in SOURCE_URLS
            or not isinstance(sha, str)
            or len(sha) != 64
            or any(c not in "0123456789abcdef" for c in sha)
        ):
            raise ValueError("invalid automatic draft provenance")
        with (root / f"{symbol}-{sha}.html").open("rb") as handle:
            body = handle.read(MAX_DOCUMENT_BYTES + 1)
        if hashlib.sha256(body).hexdigest() != sha or data != _draft(symbol, body, sha):
            raise ValueError("automatic draft differs from extracted evidence")
        rows_to_review = [
            {
                **row,
                "reviewed_on": datetime.now(UTC).date().isoformat(),
                "reviewer_ref": reviewer_ref,
            }
            for row in draft_rows
            if row["year"] >= 2027
        ]
        if not rows_to_review:
            raise ValueError("no extendable years; historical seed unchanged")
        raw = json.dumps({"schema_version": 1, "years": rows_to_review}, sort_keys=True).encode()
    digest = hashlib.sha256(raw).hexdigest()
    rows = manifest_rows(raw, digest)
    with _lock(root):
        for row in rows:
            prefix = f"{row['symbol']}-{row['evidence_sha256']}"
            receipt = _json(root / f"{prefix}.json")
            if (
                not isinstance(receipt, dict)
                or any(
                    receipt.get(key) != row[key]
                    for key in ("symbol", "source_url", "evidence_sha256")
                )
                or receipt.get("review_status") != "pending"
            ):
                raise ValueError("calendar evidence receipt mismatch")
            captured = _timestamp(receipt["captured_at"])
            if captured.date() > datetime.fromisoformat(row["reviewed_on"]).date():
                raise ValueError("calendar review precedes evidence capture")
            with (root / f"{prefix}.html").open("rb") as handle:
                body = handle.read(MAX_DOCUMENT_BYTES + 1)
            if (
                not body
                or len(body) > MAX_DOCUMENT_BYTES
                or (hashlib.sha256(body).hexdigest() != row["evidence_sha256"])
            ):
                raise ValueError("calendar evidence hash mismatch")
        path = root / f"reviewed-{digest}.json"
        # Validate coverage before publishing the final immutable filename.
        fd, name = tempfile.mkstemp(prefix=".review-", dir=root)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
            load_calendar(Path(name), digest)
        finally:
            Path(name).unlink(missing_ok=True)
        _immutable(path, raw)
    return path, digest
