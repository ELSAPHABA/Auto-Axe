"""Explicitly approved Yahoo HTTP contract; never invokes yfinance retry machinery.

The paths/schema are from the locked yfinance 1.8.0 implementation, NOT an
official public authorization. A reviewed, digest-pinned operator manifest
must document express prior permission for both exact paths and adjustment
generation. Provider finality is separate evidence, never a clock heuristic.
"""

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from time import monotonic
from typing import Any
from urllib.parse import quote

import httpx

from autoaxe.application.collection import FetchError
from autoaxe.domain.catalog import YAHOO
from autoaxe.domain.market import Candidate
from autoaxe.domain.types import decimal_string, utc_datetime
from autoaxe.domain.volume import NEW_YORK, SYMBOLS

CHART = "https://query2.finance.yahoo.com/v8/finance/chart"
SUMMARY = "https://query2.finance.yahoo.com/v10/finance/quoteSummary"
MAX_BODY = 1_000_000


class DailyTransportUnavailable(RuntimeError):
    """No verified, authorized HTTP contract is configured."""


@dataclass(frozen=True)
class ApprovedHTTP:
    evidence_ref: str
    expires_at: datetime
    adjustment_generation: str
    # Exact session-date evidence supplied by a separately reviewed provider
    # document. Do not mark dates final merely because a bar was returned.
    final_sessions: dict[str, dict[str, str]]

    def check(self, now: datetime) -> None:
        if (
            not self.evidence_ref.strip()
            or len(self.evidence_ref) > 512
            or not self.adjustment_generation.strip()
            or len(self.adjustment_generation) > 128
            or utc_datetime(now) >= utc_datetime(self.expires_at)
        ):
            raise DailyTransportUnavailable("Yahoo HTTP transport not verified or expired")


def load_approved_http() -> ApprovedHTTP | None:
    path = os.getenv("AUTOAXE_YAHOO_HTTP_CONTRACT")
    digest = os.getenv("AUTOAXE_YAHOO_HTTP_CONTRACT_SHA256")
    if not path and not digest:
        return None
    try:
        if not path or not digest:
            raise ValueError("incomplete contract")
        with Path(path).open("rb") as file:
            raw = file.read(65537)
        if len(raw) > 65536 or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("contract digest mismatch")
        doc = json.loads(raw)
        if (
            set(doc)
            != {
                "version",
                "evidence_ref",
                "expires_at",
                "adjustment_generation",
                "chart_url",
                "summary_url",
                "final_sessions",
            }
            or doc["version"] != 1
            or doc["chart_url"] != CHART
            or doc["summary_url"] != SUMMARY
        ):
            raise ValueError("unsupported contract")
        final = doc["final_sessions"]
        if not isinstance(final, dict) or not set(final) <= set(SYMBOLS):
            raise ValueError("invalid finality evidence")
        for sessions in final.values():
            if not isinstance(sessions, dict) or len(sessions) > 2000:
                raise ValueError("invalid finality evidence")
            for day, evidence in sessions.items():
                if (
                    date.fromisoformat(day).isoformat() != day
                    or not isinstance(evidence, str)
                    or not 1 <= len(evidence.strip()) <= 512
                ):
                    raise ValueError("invalid finality evidence")
        contract = ApprovedHTTP(
            doc["evidence_ref"],
            datetime.fromisoformat(doc["expires_at"]),
            doc["adjustment_generation"],
            final,
        )
        contract.check(datetime.now(UTC))
        return contract
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise DailyTransportUnavailable("Yahoo HTTP transport not verified") from exc


def _get(
    client: httpx.Client,
    url: str,
    params: dict[str, str],
    permit: Callable[[], None],
    contract: ApprovedHTTP,
) -> Any:
    if client.trust_env or client.follow_redirects:
        raise ValueError("Yahoo HTTP proxy/redirect disabled")
    contract.check(datetime.now(UTC))
    permit()
    deadline = monotonic() + 20
    try:
        with client.stream(
            "GET",
            url,
            params=params,
            follow_redirects=False,
            timeout=10,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "User-Agent": "Auto-Axe/0.1 approved research client",
            },
        ) as response:
            if response.status_code != 200:
                raise FetchError(response.status_code, response.headers.get("retry-after"))
            if response.headers.get("content-type", "").split(";")[0].lower() != "application/json":
                raise ValueError("Yahoo HTTP response media mismatch")
            raw = bytearray()
            for part in response.iter_bytes():
                if monotonic() > deadline:
                    raise TimeoutError("Yahoo HTTP total deadline exceeded")
                raw.extend(part)
                if len(raw) > MAX_BODY:
                    raise ValueError("Yahoo HTTP response exceeds bound")
        permit()
        contract.check(datetime.now(UTC))
        return json.loads(raw, parse_float=Decimal)
    except httpx.HTTPError:
        raise ConnectionError("Yahoo HTTP transport failed") from None


def _number(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, Decimal, str)):
        raise ValueError("invalid Yahoo number")
    return Decimal(decimal_string(str(value)))


def chart_rows(
    payload: Any,
    symbol: str,
    start: date,
    end: date,
    contract: ApprovedHTTP,
) -> list[dict[str, Any]]:
    chart = payload["chart"]
    if chart["error"] is not None or len(chart["result"]) != 1:
        raise ValueError("Yahoo chart unavailable")
    result = chart["result"][0]
    meta = result["meta"]
    if (
        meta["symbol"] != symbol
        or meta["currency"] != "USD"
        or meta["exchangeTimezoneName"] != "America/New_York"
        or meta["dataGranularity"] != "1d"
    ):
        raise ValueError("Yahoo chart identity mismatch")
    stamps = result["timestamp"]
    indicators = result["indicators"]
    if len(indicators["quote"]) != 1 or len(indicators["adjclose"]) != 1 or len(stamps) > 600:
        raise ValueError("Yahoo chart shape mismatch")
    quote = indicators["quote"][0]
    columns = ("open", "high", "low", "close", "volume")
    adjusted = indicators["adjclose"][0]["adjclose"]
    rows = []
    seen: set[date] = set()
    for stamp, adj, *values in zip(stamps, adjusted, *(quote[k] for k in columns), strict=True):
        if type(stamp) is not int:
            raise ValueError("invalid Yahoo session timestamp")
        at = datetime.fromtimestamp(stamp, UTC)
        day = at.astimezone(NEW_YORK).date()
        if not start <= day <= end or day in seen:
            raise ValueError("Yahoo chart outside requested range")
        seen.add(day)
        if adj is None or any(v is None for v in values):
            continue
        o, h, low, close, volume = map(_number, values)
        adj_close = _number(adj)
        if close <= 0 or adj_close <= 0 or volume < 0 or volume != volume.to_integral_value():
            raise ValueError("invalid Yahoo adjusted OHLCV")
        factor = adj_close / close
        final = contract.final_sessions.get(symbol, {}).get(day.isoformat())
        rows.append(
            {
                "session_at": at,
                "open": decimal_string(o * factor),
                "high": decimal_string(h * factor),
                "low": decimal_string(low * factor),
                "close": decimal_string(adj_close),
                "volume": decimal_string(volume),
                "provider_final": final is not None,
                "provider_final_evidence": final,
                "adjustment_generation": contract.adjustment_generation,
            }
        )
    return rows


def fetch_chart(
    client: httpx.Client,
    contract: ApprovedHTTP,
    symbol: str,
    start: date,
    end: date,
    permit: Callable[[], None],
) -> list[dict[str, Any]]:
    if symbol not in SYMBOLS or not 0 <= (end - start).days <= 600:
        raise ValueError("invalid Yahoo daily range")
    params = {
        "period1": str(int(datetime.combine(start, time.min, NEW_YORK).timestamp())),
        "period2": str(
            int(datetime.combine(end + timedelta(days=1), time.min, NEW_YORK).timestamp())
        ),
        "interval": "1d",
        "includePrePost": "false",
        "events": "div,splits",
        "includeAdjustedClose": "true",
    }
    return chart_rows(
        _get(client, f"{CHART}/{symbol}", params, permit, contract), symbol, start, end, contract
    )


def fetch_summary(
    client: httpx.Client,
    contract: ApprovedHTTP,
    symbol: str,
    permit: Callable[[], None],
) -> dict[str, Any]:
    if symbol not in SYMBOLS:
        raise ValueError("unregistered equity")
    if symbol == "QLD":
        return {}
    payload = _get(
        client,
        f"{SUMMARY}/{symbol}",
        {
            "modules": "summaryDetail,defaultKeyStatistics,financialData,price",
            "formatted": "false",
        },
        permit,
        contract,
    )["quoteSummary"]
    if payload["error"] is not None or len(payload["result"]) != 1:
        raise ValueError("Yahoo fundamentals unavailable")
    result = payload["result"][0]
    if result["price"]["symbol"] != symbol or result["price"]["currency"] != "USD":
        raise ValueError("Yahoo fundamentals identity mismatch")
    fields = {
        "trailingPE": "summaryDetail",
        "forwardPE": "summaryDetail",
        "priceToBook": "defaultKeyStatistics",
        "returnOnEquity": "financialData",
    }
    output = {}
    for name, module in fields.items():
        value = result.get(module, {}).get(name)
        if isinstance(value, dict):
            value = value.get("raw")
        if value is not None:
            output[name] = decimal_string(_number(value))
    return output


def fetch_market_bar(
    client: httpx.Client,
    contract: ApprovedHTTP,
    sid: str,
    permit: Callable[[], None],
) -> Candidate:
    """One approved chart request for a known index; never a live quote."""
    from autoaxe.adapters.providers import normalize_yahoo

    if sid not in YAHOO:
        raise ValueError("unregistered Yahoo market series")
    symbol = YAHOO[sid]
    chart = _get(
        client,
        f"{CHART}/{quote(symbol, safe='')}",
        {"range": "1d", "interval": "1m", "includePrePost": "false"},
        permit,
        contract,
    )["chart"]
    if chart["error"] is not None or len(chart["result"]) != 1:
        raise ValueError("Yahoo market chart unavailable")
    row = chart["result"][0]
    meta = row["meta"]
    if meta["symbol"] != symbol or meta["dataGranularity"] != "1m":
        raise ValueError("Yahoo market chart identity mismatch")
    stamps = row.get("timestamp", [])
    values = row["indicators"]["quote"]
    if len(values) != 1 or len(stamps) > 2000:
        raise ValueError("Yahoo market chart shape mismatch")
    closes = values[0]["close"]
    received = datetime.now(UTC)
    latest: tuple[datetime, Decimal] | None = None
    for stamp, value in zip(stamps, closes, strict=True):
        if type(stamp) is not int:
            raise ValueError("Yahoo market bar timestamp")
        at = datetime.fromtimestamp(stamp, UTC)
        if at > received:
            raise ValueError("future Yahoo market bar")
        if value is not None:
            price = _number(value)
            if latest is None or at > latest[0]:
                latest = (at, price)
    delay = meta.get("exchangeDataDelayedBy")
    if delay is not None and (type(delay) is not int or delay < 0):
        raise ValueError("Yahoo market delay metadata invalid")
    return normalize_yahoo(
        sid,
        symbol=symbol,
        close=latest[1] if latest else None,
        stamp=latest[0] if latest else None,
        received=received,
        delay_minutes=delay,
    )
