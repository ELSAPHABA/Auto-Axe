"""Phase 1 provider normalization. All endpoints fixed; transport injected by collector."""

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from xml.etree import ElementTree

from autoaxe.domain.catalog import FUTURES, RATIOS, TREASURY, YAHOO, catalog
from autoaxe.domain.market import Candidate, Quality
from autoaxe.domain.types import decimal_string, utc_string

SPOT_WS = "wss://data-stream.binance.vision/stream?streams=btcusdt@trade"
FUTURES_WS = "wss://fstream.binance.com/market/stream?streams=" + "/".join(
    s.lower() + "@aggTrade" for s in FUTURES
)
FUTURES_REST = "https://fapi.binance.com/fapi/v1"
SPOT_REST = "https://data-api.binance.vision/api/v3"
RATIO_REST = "https://fapi.binance.com/futures/data"
TREASURY_XML = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
)
NAVER_PAGE = "https://m.stock.naver.com/marketindex/bond/US2YT=RR"
NAVER_API = "https://m.stock.naver.com/front-api/marketIndex/bondList"
MAX_BYTES = 2_000_000


def millis(value: object) -> datetime:
    if not isinstance(value, (int, str)) or isinstance(value, bool):
        raise ValueError("invalid millisecond timestamp")
    ms = int(value)
    if ms < 0:
        raise ValueError("negative timestamp")
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=ms)


def number(value: object, *, nonnegative: bool = False) -> str:
    # Original Binance string; yfinance receives str(value) explicitly at its boundary.
    result = decimal_string(value)
    if nonnegative and Decimal(result) < 0:
        raise ValueError("negative number")
    return result


def binance_trade(message: Mapping[str, Any], received: datetime, *, spot: bool) -> Candidate:
    msg = message.get("data", message)
    if not isinstance(msg, dict):
        raise ValueError("bad trade payload")
    symbol = msg["s"]
    sid = "BITCOIN_BINANCE_SPOT" if spot else FUTURES[symbol][0]
    expected = "trade" if spot else "aggTrade"
    if msg.get("e") != expected or (spot and symbol != "BTCUSDT"):
        raise ValueError("instrument or event mismatch")
    stream = message.get("stream")
    if stream is not None and stream != symbol.lower() + "@" + expected:
        raise ValueError("stream mismatch")
    key = str(int(msg["t" if spot else "a"]))
    return Candidate(
        sid,
        key,
        number(msg["p"], nonnegative=True),
        millis(msg["T"]),
        received,
        received,
        metadata={
            "symbol": symbol,
            "trade_id": key,
            "quantity": number(msg["q"], nonnegative=True),
            "event_type": expected,
            "quote_currency": "USDT",
        },
    )


def binance_rest_trade(
    symbol: str, row: Mapping[str, Any], received: datetime, *, spot: bool
) -> Candidate:
    # Spot REST aggTrades has aggregate ID, not raw trade ID. For spot use
    # historical trades (id/price/qty/time) only when separately authorized.
    msg = {
        "s": symbol,
        "e": "trade" if spot else "aggTrade",
        "t" if spot else "a": row["id" if spot else "a"],
        "p": row["price" if spot else "p"],
        "q": row["qty" if spot else "q"],
        "T": row["time" if spot else "T"],
    }
    return binance_trade(msg, received, spot=spot)


def ratio_request(symbol: str, kind: str) -> tuple[str, dict[str, Any]]:
    if symbol not in ("BTCUSDT", *FUTURES):
        raise ValueError("unknown symbol")
    return RATIO_REST + "/" + RATIOS[kind][0], {"symbol": symbol, "period": "5m", "limit": 2}


def normalize_ratio(
    symbol: str, kind: str, payload: list[dict[str, Any]], received: datetime
) -> list[Candidate]:
    ratio_request(symbol, kind)
    if len(payload) > 2:
        raise ValueError("unexpected ratio batch")
    field = RATIOS[kind][1]
    result = []
    for row in sorted(payload, key=lambda r: int(r["timestamp"])):
        if row.get("symbol", symbol) != symbol:
            raise ValueError("ratio symbol mismatch")
        stamp = millis(row["timestamp"])
        raw = row.get(field)
        quality = Quality.NO_DATA if raw is None else Quality.VALID
        metadata = {
            k: number(row[k], nonnegative=True)
            for k in (
                "longAccount",
                "shortAccount",
                "longPosition",
                "shortPosition",
                "buyVol",
                "sellVol",
            )
            if row.get(k) is not None
        }
        metadata.update(
            {"symbol": symbol, "ratio_kind": kind, "period": "5m", "raw_ratio_field": field}
        )
        result.append(
            Candidate(
                f"BINANCE_{kind.upper()}_{symbol}",
                utc_string(stamp),
                None if raw is None else number(raw, nonnegative=True),
                stamp,
                received,
                received,
                quality,
                metadata,
            )
        )
    return result


def normalize_yahoo(
    sid: str,
    *,
    symbol: str,
    close: object,
    stamp: datetime | None,
    received: datetime,
    delay_minutes: int | None = None,
    bar_interval: str = "1m",
) -> Candidate:
    if YAHOO[sid] != symbol or bar_interval != "1m":
        raise ValueError("Yahoo symbol/interval mismatch")
    value: str | None = None
    if close is not None:
        try:
            value = number(str(close))
        except ValueError:
            pass
    quality = (
        Quality.NO_DATA if value is None else (Quality.UNKNOWN if stamp is None else Quality.VALID)
    )
    # A bar's start time is not a quote event or proof of closed-bar status.
    return Candidate(
        sid,
        utc_string(stamp) if stamp else "missing:" + utc_string(received),
        value,
        stamp,
        received,
        received,
        quality,
        {
            "symbol": symbol,
            "bar_interval": bar_interval,
            "potentially_delayed": True,
            "bar_closed": False,
            "delay_minutes": delay_minutes,
        },
    )


def normalize_naver(payload: Mapping[str, Any], received: datetime) -> Candidate:
    rows = [r for r in payload["result"] if r.get("reutersCode") == "US2YT=RR"]
    if len(rows) != 1:
        raise ValueError("Naver row missing or ambiguous")
    row = rows[0]
    stamp = datetime.fromisoformat(row["localTradedAt"]) if row.get("localTradedAt") else None
    raw = row.get("closePrice")
    return Candidate(
        "UST_2Y_NAVER",
        utc_string(stamp) if stamp else "missing:" + utc_string(received),
        number(raw) if raw is not None else None,
        stamp,
        received,
        received,
        Quality.NO_DATA if raw is None else Quality.VALID if stamp else Quality.UNKNOWN,
        {
            "symbol": "US2YT=RR",
            "price_data_type": row.get("priceDataType"),
            "delay_time": row.get("delayTime"),
            "market_status": row.get("marketStatus"),
            "source_url": NAVER_PAGE,
        },
    )


def normalize_treasury(raw: bytes, received: datetime) -> list[Candidate]:
    if len(raw) > MAX_BYTES or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("unsafe XML")
    root = ElementTree.fromstring(raw)
    result: list[Candidate] = []
    for entry in root.findall("{http://www.w3.org/2005/Atom}entry"):
        row = {node.tag.split("}")[-1]: node.text for node in entry.iter()}
        if not row.get("NEW_DATE"):
            continue
        day = date.fromisoformat(str(row["NEW_DATE"])[:10])
        if day > received.date():
            raise ValueError("future Treasury date")
        for tenor, field in TREASURY.items():
            sid = "UST_2Y_TREASURY" if tenor == "2Y" else f"UST_{tenor}_PAR_YIELD"
            value = row.get(field)
            # Published date is known, precise time is not. Never invent midnight.
            result.append(
                Candidate(
                    sid,
                    day.isoformat(),
                    number(value) if value else None,
                    None,
                    received,
                    received,
                    Quality.UNKNOWN if value else Quality.NO_DATA,
                    {
                        "official_daily": True,
                        "observation_date": day.isoformat(),
                        "field": field,
                        "unit": "percent",
                    },
                )
            )
    if not result:
        raise ValueError("no Treasury entries")
    return result


Fetch = Callable[[str, dict[str, Any]], Awaitable[Any]]
Allowed = Callable[[str], None]


async def fetch_ratios(
    fetch: Fetch, allowed: Allowed, received: datetime, symbol: str, kind: str
) -> list[Candidate]:
    sid = f"BINANCE_{kind.upper()}_{symbol}"
    allowed(sid)
    url, params = ratio_request(symbol, kind)
    rows = await fetch(url, params)
    allowed(sid)
    return normalize_ratio(symbol, kind, rows, received)


def recovery_request(symbol: str, after: int, *, spot: bool) -> tuple[str, dict[str, Any]]:
    if after < 0 or (spot and symbol != "BTCUSDT") or (not spot and symbol not in FUTURES):
        raise ValueError("invalid recovery parameters")
    if spot:
        # /historicalTrades requires API key; never substitute aggTrades IDs.
        return SPOT_REST + "/historicalTrades", {
            "symbol": symbol,
            "fromId": after + 1,
            "limit": 1000,
        }
    return FUTURES_REST + "/aggTrades", {"symbol": symbol, "fromId": after + 1, "limit": 1000}


async def stream_trades(
    messages: AsyncIterator[Mapping[str, Any]],
    allowed: Allowed,
    *,
    spot: bool,
    clock: Callable[[], datetime],
) -> AsyncIterator[Candidate]:
    """Bounded pull stream: backpressure via awaiting consumer; reconnect is caller-owned."""
    for sid in ["BITCOIN_BINANCE_SPOT"] if spot else [x[0] for x in FUTURES.values()]:
        allowed(sid)
    async for message in messages:
        item = binance_trade(message, clock(), spot=spot)
        allowed(item.series_id)
        yield item


def series_for_ratio(symbol: str, kind: str) -> str:
    sid = f"BINANCE_{kind.upper()}_{symbol}"
    if sid not in catalog():
        raise ValueError("unknown ratio")
    return sid
