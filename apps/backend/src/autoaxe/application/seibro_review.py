"""Private review boundary for SEIBro TOP50; no network or scalar market signal."""

import re
from datetime import date, datetime
from decimal import Decimal, localcontext
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from autoaxe.application.scrape_broker import source_lock
from autoaxe.domain.canonical import canonical_sha256
from autoaxe.domain.types import decimal_string, utc_string
from autoaxe.infrastructure.market_store import PermissionDenied, verify_connection

URL = (
    "https://seibro.or.kr/websquare/control.jsp"
    "?w2xPath=/IPORTAL/user/ovsSec/BIP_CNTS10013V.xml&menuNo=921"
)
COUNTRIES = {"US": "미국", "HK": "홍콩", "CN": "중국", "JP": "일본", "VN": "베트남"}
SCOPE = (
    "country_code",
    "period_code",
    "rank_basis",
    "period_start",
    "period_end",
    "as_of_date_kst",
)
AMOUNTS = (
    "buy_settlement_usd",
    "sell_settlement_usd",
    "gross_settlement_usd",
    "net_buy_settlement_usd",
)
ROW_FIELDS = {"rank", "country_name", "isin", "security_name", *AMOUNTS}


def storage_permission(conn: Connection[Any], *, private_use: bool = True) -> int:
    """Manual storage/read approval never authorizes automatic source requests."""
    row = conn.execute(
        """SELECT permission_status,free_only,allow_storage,verified_at,evidence_ref,
                  permission_version,allow_redistribution
           FROM catalog.source_registry WHERE source_id='seibro'"""
    ).fetchone()
    if (
        not row
        or row[:3] != ("approved", True, True)
        or row[3] is None
        or not row[4]
        or not row[4].strip()
        or (not private_use and row[6] is not True)
    ):
        raise PermissionDenied("SEIBro manual storage not approved for this audience")
    return int(row[5])


def _date(raw: Any) -> date:
    if not isinstance(raw, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw):
        raise ValueError("explicit ISO date required")
    return date.fromisoformat(raw)


def _label(value: Any) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 256 or not value.isprintable():
        raise ValueError("invalid visible label")
    if not value.strip() or value != value.strip():
        raise ValueError("invalid visible label")
    return value


def normalize_capture(data: Any) -> dict[str, Any]:
    fields = {
        *SCOPE,
        "retrieved_at_utc",
        "capture_mode",
        "currency",
        "settlement_type",
        "source_url",
        "top50_coverage",
        "rows",
    }
    if not isinstance(data, dict) or set(data) != fields:
        raise ValueError("invalid capture envelope")
    country = data["country_code"]
    if (
        country not in (*COUNTRIES, "ALL")
        or data["period_code"] not in ("1", "2", "3", "4", "5")
        or data["rank_basis"] not in ("1", "2", "3", "4")
        or data["currency"] != "USD"
        or data["settlement_type"] != "2"
        or data["source_url"] != URL
        or data["top50_coverage"] is not True
        or data["capture_mode"] not in ("manual_capture", "offline_fixture")
    ):
        raise ValueError("invalid settlement scope")
    as_of = _date(data["as_of_date_kst"])
    start, end = data["period_start"], data["period_end"]
    if (start is None) != (end is None) or (
        start is not None and not _date(start) <= _date(end) <= as_of
    ):
        raise ValueError("invalid or incomplete displayed period")
    raw_time = data["retrieved_at_utc"]
    if not isinstance(raw_time, str) or len(raw_time) > 64:
        raise ValueError("invalid retrieval timestamp")
    stamp = datetime.fromisoformat(raw_time)
    if stamp.utcoffset() is None or as_of > stamp.astimezone(ZoneInfo("Asia/Seoul")).date():
        raise ValueError("invalid retrieval timestamp or future settlement date")
    rows = data["rows"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 50:
        raise ValueError("expected 1 to 50 ranked rows")
    normalized = []
    seen = set()
    last = None
    for rank, row in enumerate(rows, 1):
        if (
            not isinstance(row, dict)
            or set(row) != ROW_FIELDS
            or type(row["rank"]) is not int
            or row["rank"] != rank
        ):
            raise ValueError("noncontiguous or invalid rank")
        isin = row["isin"]
        if (
            not isinstance(isin, str)
            or not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", isin)
            or isin in seen
        ):
            raise ValueError("invalid or duplicate ISIN")
        seen.add(isin)
        name, nation = _label(row["security_name"]), _label(row["country_name"])
        if country != "ALL" and nation != COUNTRIES[country]:
            raise ValueError("country does not match capture scope")
        values = []
        for field in AMOUNTS:
            raw = row[field]
            if (
                not isinstance(raw, str)
                or len(raw) > 40
                or not re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", raw)
            ):
                raise ValueError("invalid settlement amount")
            values.append(Decimal(raw))
        buy, sell, gross, net = values
        # Exact arithmetic, never silently adjust provider amounts.
        with localcontext() as context:
            context.prec = 100
            if buy < 0 or sell < 0 or gross != buy + sell or net != buy - sell:
                raise ValueError("settlement arithmetic mismatch")
        metric = values[int(data["rank_basis"]) - 1]
        if last is not None and metric > last:
            raise ValueError("rows do not follow declared ranking basis")
        last = metric
        normalized.append(
            {
                "rank": rank,
                "isin": isin,
                "country_name": nation,
                "security_name": name,
                **dict(zip(AMOUNTS, map(decimal_string, values), strict=True)),
            }
        )
    return {**data, "retrieved_at_utc": utc_string(stamp), "rows": normalized}


def stage_capture(conn: Connection[Any], data: Any) -> tuple[str, str]:
    """Stage normalized, permission-scoped candidates, never raw HTML or fixtures."""
    verify_connection(conn, write=True)
    payload = normalize_capture(data)
    if payload["capture_mode"] != "manual_capture":
        raise PermissionDenied("fixture cannot enter reviewed ledger")
    source_lock(conn, "seibro")
    version = storage_permission(conn)
    clock = conn.execute("SELECT clock_timestamp()").fetchone()
    assert clock is not None
    if datetime.fromisoformat(payload["retrieved_at_utc"]) > clock[0]:
        raise ValueError("future retrieval timestamp")
    digest = canonical_sha256(payload)
    capture_id = str(uuid4())
    row = conn.execute(
        """INSERT INTO ops.seibro_captures(id,permission_version,capture_hash,payload)
        VALUES (%s,%s,%s,%s) ON CONFLICT(permission_version,capture_hash)
        DO NOTHING RETURNING id""",
        (capture_id, version, digest, Jsonb(payload)),
    ).fetchone()
    if not row:
        row = conn.execute(
            "SELECT id FROM ops.seibro_captures WHERE permission_version=%s AND capture_hash=%s",
            (version, digest),
        ).fetchone()
    assert row is not None
    return str(row[0]), digest


def promote_capture(conn: Connection[Any], capture_id: str) -> tuple[str, str | None]:
    """Independent administrator review required; atomic append-only typed ledger."""
    verify_connection(conn, write=True)
    source_lock(conn, "seibro")
    version = storage_permission(conn)
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            """SELECT c.*,r.capture_hash AS reviewed_hash,r.decision,r.reviewed_at
            FROM ops.seibro_captures c JOIN ops.seibro_reviews r ON r.capture_id=c.id
            WHERE c.id=%s""",
            (capture_id,),
        ).fetchone()
    if not row or row["permission_version"] != version:
        raise PermissionDenied("independent current-version review required")
    payload = normalize_capture(row["payload"])
    if payload["capture_mode"] != "manual_capture" or not (
        row["capture_hash"] == row["reviewed_hash"] == canonical_sha256(payload)
    ):
        raise PermissionDenied("reviewed capture hash mismatch")
    clock = conn.execute("SELECT clock_timestamp()").fetchone()
    assert clock is not None
    now = clock[0]
    if not row["first_seen_at"] <= row["reviewed_at"] <= now:
        raise PermissionDenied("invalid review time")
    receipt = conn.execute(
        "SELECT snapshot_id,decision FROM ops.seibro_promotions WHERE capture_id=%s", (capture_id,)
    ).fetchone()
    if receipt:
        if receipt[1] != row["decision"]:
            raise PermissionDenied("review decision changed")
        return "duplicate", str(receipt[0]) if receipt[0] else None
    snapshot_id = None
    state = "rejected"
    if row["decision"] == "checked":
        scope = {key: payload[key] for key in SCOPE}
        scope_hash = canonical_sha256(scope)
        content_hash = canonical_sha256({"scope": scope, "rows": payload["rows"]})
        old = conn.execute(
            """SELECT id,revision,content_hash,permission_version
            FROM indicators.seibro_top50_snapshots WHERE scope_hash=%s
            ORDER BY revision DESC LIMIT 1""",
            (scope_hash,),
        ).fetchone()
        if old and old[2] == content_hash and old[3] == version:
            snapshot_id, state = str(old[0]), "duplicate"
        else:
            snapshot_id, state = str(uuid4()), "promoted"
            conn.execute(
                """INSERT INTO indicators.seibro_top50_snapshots
                (id,capture_id,permission_version,scope_hash,content_hash,revision,country_code,
                period_code,rank_basis,period_start,period_end,as_of_date_kst,retrieved_at,
                first_seen_at,available_at,row_count)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    snapshot_id,
                    capture_id,
                    version,
                    scope_hash,
                    content_hash,
                    old[1] + 1 if old else 1,
                    *(scope[key] for key in SCOPE),
                    payload["retrieved_at_utc"],
                    row["first_seen_at"],
                    now,
                    len(payload["rows"]),
                ),
            )
            with conn.cursor() as cur:
                cur.executemany(
                    """INSERT INTO indicators.seibro_top50_rows
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    [
                        (
                            snapshot_id,
                            item["rank"],
                            item["country_name"],
                            item["isin"],
                            item["security_name"],
                            *(Decimal(item[key]) for key in AMOUNTS),
                        )
                        for item in payload["rows"]
                    ],
                )
    conn.execute(
        "INSERT INTO ops.seibro_promotions(capture_id,snapshot_id,decision) VALUES (%s,%s,%s)",
        (capture_id, snapshot_id, row["decision"]),
    )
    return state, snapshot_id
