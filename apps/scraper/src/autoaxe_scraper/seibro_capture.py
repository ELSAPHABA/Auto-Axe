"""Offline SEIBro display-row converter; no browser, network or selector claims.

Input is manually transcribed display data or a synthetic fixture, using the
documented WebSquare column names. No internal submission API is invoked.
"""

import argparse
import json
import re
import sys
from decimal import Decimal, InvalidOperation
from typing import Any

SOURCE_URL = (
    "https://seibro.or.kr/websquare/control.jsp"
    "?w2xPath=/IPORTAL/user/ovsSec/BIP_CNTS10013V.xml&menuNo=921"
)
MAX_INPUT = 131_072
FIELDS = {
    "RNUM": "rank",
    "NATION_NM": "country_name",
    "ISIN": "isin",
    "KOR_SECN_NM": "security_name",
    "SUM_FRSEC_BUY_AMT": "buy_settlement_usd",
    "SUM_FRSEC_SELL_AMT": "sell_settlement_usd",
    "SUM_FRSEC_TOT_AMT": "gross_settlement_usd",
    "SUM_FRSEC_NET_BUY_AMT": "net_buy_settlement_usd",
}
SCOPE_FIELDS = {
    "country_code",
    "period_code",
    "rank_basis",
    "period_start",
    "period_end",
    "as_of_date_kst",
    "retrieved_at_utc",
    "capture_mode",
    "currency",
    "settlement_type",
}


def _amount(raw: Any) -> str:
    if (
        not isinstance(raw, str)
        or len(raw) > 40
        or not re.fullmatch(r"-?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?", raw)
    ):
        raise ValueError("invalid displayed amount")
    try:
        value = Decimal(raw.replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError("invalid displayed amount") from exc
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def normalize_display(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or set(data) != SCOPE_FIELDS | {"rows"}:
        raise ValueError("unexpected display capture fields")
    if (
        data["capture_mode"] not in ("manual_capture", "offline_fixture")
        or data["currency"] != "USD"
        or data["settlement_type"] != "2"
        or data["country_code"] not in ("US", "ALL", "HK", "CN", "JP", "VN")
        or data["period_code"] not in ("1", "2", "3", "4", "5")
        or data["rank_basis"] not in ("1", "2", "3", "4")
    ):
        raise ValueError("unsupported display capture scope")
    if not isinstance(data["rows"], list) or not 1 <= len(data["rows"]) <= 50:
        raise ValueError("TOP50 requires 1 to 50 visible rows")
    rows = []
    for raw in data["rows"]:
        if not isinstance(raw, dict) or set(raw) != set(FIELDS):
            raise ValueError("unexpected visible column mapping")
        if not isinstance(raw["RNUM"], str) or not re.fullmatch(r"[1-9][0-9]?", raw["RNUM"]):
            raise ValueError("invalid displayed rank")
        row: dict[str, Any] = {"rank": int(raw["RNUM"])}
        for key, name in FIELDS.items():
            if key == "RNUM":
                continue
            value = raw[key]
            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                raise ValueError("invalid visible cell")
            row[name] = _amount(value) if name.endswith("_usd") else value.strip()
        rows.append(row)
    return {
        **{key: data[key] for key in SCOPE_FIELDS},
        "source_url": SOURCE_URL,
        "top50_coverage": True,
        "rows": rows,
    }


def require_browser() -> None:
    """Live browser execution is intentionally unavailable until audited.

    A source approval alone does not establish sandbox, request/subresource,
    DNS pinning, redirect, WebSocket or download restrictions. The current
    locked package has no browser extra and no verified live DOM contract.
    """
    raise PermissionError("SEIBro live browser contract not verified")


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate capture field")
        result[key] = value
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    try:
        if args.browser:
            require_browser()
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError("capture too large")
        data = json.loads(raw, object_pairs_hook=_unique_pairs)
        print(json.dumps(normalize_display(data), ensure_ascii=False, allow_nan=False))
    except (ValueError, TypeError, PermissionError, UnicodeError):
        raise SystemExit("SEIBro capture blocked or invalid") from None


if __name__ == "__main__":
    main()
