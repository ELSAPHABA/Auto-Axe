"""PostgreSQL-authoritative opaque browser sessions; never persist raw tokens."""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

from autoaxe.domain.types import utc_datetime

IDLE = timedelta(minutes=30)
ABSOLUTE = timedelta(hours=12)
ROLES = {"viewer", "analyst", "strategy_editor", "operator", "trading_approver", "security_admin"}


def digest(raw: str) -> str:
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class SessionGrant:
    subject_ref: str
    role: str
    scopes: frozenset[str]
    auth_version: int
    session_hash: str


def _check_app_role(conn: Connection[Any]) -> None:
    row = conn.execute("SELECT current_database(),current_user").fetchone()
    if row != ("autoaxe_app", "autoaxe_app_runtime"):
        raise PermissionError("wrong BFF database principal")


def create_session(
    conn: Connection[Any],
    subject_ref: str,
    issuer: str,
    expires_at: datetime,
) -> tuple[str, str]:
    """Only an already-provisioned principal may log in; never infer roles from IdP names."""
    _check_app_role(conn)
    utc_datetime(expires_at)
    grant = conn.execute(
        "SELECT role,auth_version,revoked_at FROM identity.user_grants "
        "WHERE subject_ref=%s FOR UPDATE",
        (subject_ref,),
    ).fetchone()
    if not grant or grant[2] is not None or grant[0] not in ROLES:
        raise PermissionError("principal not provisioned")
    now_row = conn.execute("SELECT clock_timestamp()").fetchone()
    assert now_row is not None
    now = now_row[0]
    until = min(now + ABSOLUTE, expires_at)
    if until <= now:
        raise PermissionError("expired provider identity")
    sid, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    conn.execute(
        """INSERT INTO identity.web_sessions
        (session_hash,subject_ref,csrf_hash,auth_version,created_at,last_seen_at,
        idle_expires_at,absolute_expires_at,issuer)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            digest(sid),
            subject_ref,
            digest(csrf),
            grant[1],
            now,
            now,
            min(now + IDLE, until),
            until,
            issuer,
        ),
    )
    return sid, csrf


def authorize(
    conn: Connection[Any],
    session_id: str | None,
    *,
    required_scope: str = "indicators:read",
    csrf: str | None = None,
) -> SessionGrant:
    """Check session and current principal version in DB for every protected request."""
    _check_app_role(conn)
    if not session_id or len(session_id) > 256:
        raise PermissionError("missing session")
    with conn.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            """SELECT s.*,g.role,g.scopes,g.auth_version AS current_version,
            g.revoked_at AS grant_revoked,clock_timestamp() AS now
            FROM identity.web_sessions s JOIN identity.user_grants g
            USING(subject_ref) WHERE s.session_hash=%s FOR UPDATE OF s""",
            (digest(session_id),),
        ).fetchone()
    if not row or row["revoked_at"] is not None or row["grant_revoked"] is not None:
        raise PermissionError("session revoked")
    if (
        row["auth_version"] != row["current_version"]
        or row["idle_expires_at"] <= row["now"]
        or row["absolute_expires_at"] <= row["now"]
    ):
        raise PermissionError("expired/changed authorization")
    if csrf is not None and not hmac.compare_digest(digest(csrf), row["csrf_hash"]):
        raise PermissionError("CSRF token mismatch")
    scopes = frozenset(row["scopes"])
    if required_scope not in scopes:
        raise PermissionError("insufficient scope")
    conn.execute(
        """UPDATE identity.web_sessions SET last_seen_at=%s,
        idle_expires_at=LEAST(%s,absolute_expires_at) WHERE session_hash=%s""",
        (row["now"], row["now"] + IDLE, digest(session_id)),
    )
    return SessionGrant(
        row["subject_ref"], row["role"], scopes, row["auth_version"], digest(session_id)
    )


def revoke(conn: Connection[Any], session_id: str) -> None:
    _check_app_role(conn)
    conn.execute(
        "UPDATE identity.web_sessions SET revoked_at=clock_timestamp() "
        "WHERE session_hash=%s AND revoked_at IS NULL",
        (digest(session_id),),
    )


def rotate(conn: Connection[Any], sid: str, scope: str = "indicators:read") -> tuple[str, str]:
    grant = authorize(conn, sid, required_scope=scope)
    row = conn.execute(
        "SELECT issuer,absolute_expires_at FROM identity.web_sessions WHERE session_hash=%s",
        (grant.session_hash,),
    ).fetchone()
    assert row is not None
    revoke(conn, sid)
    return create_session(conn, grant.subject_ref, row[0], row[1])
