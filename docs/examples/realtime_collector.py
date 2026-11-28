#!/usr/bin/env python3
"""Auto-Axe reference collector (stdout JSON Lines, no orders).
Commands: binance-live, binance-futures, binance-longshort, gold, naver-2y, yf-market, treasury-five, coinbase, binance, sec-8k, bls-calendar, bls-actual, fred, eia, vix-eod
Set env vars in docs/examples/.env.example. Respect source terms and credentials.
"""
import argparse
import asyncio
import calendar
import datetime as dt
import hashlib
import json
import logging
import os
import random
import sys
import time

import feedparser
import requests
from dotenv import load_dotenv
from icalendar import Calendar
from websockets.asyncio.client import connect

UTC = dt.timezone.utc
USER_AGENT = os.getenv("AUTO_AXE_USER_AGENT", "AutoAxeResearch/0.1")
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def iso_now():
    return dt.datetime.now(UTC).isoformat()


def emit(provider, series, value, observed_at=None, **extra):
    record = {
        "provider": provider,
        "series": series,
        "value": value,
        "source_event_at": observed_at,
        "received_at": iso_now(),
        **extra,
    }
    print(json.dumps(record, ensure_ascii=False, default=str), flush=True)


def millis(ms):
    return dt.datetime.fromtimestamp(int(ms) / 1000, UTC).isoformat()


def request(method, url, **kwargs):
    """Retry transient errors; do not bypass 401/403 or rate limits."""
    for attempt in range(5):
        try:
            response = SESSION.request(method, url, timeout=(6, 20), **kwargs)
            if response.status_code in (401, 403):
                response.raise_for_status()
            if response.status_code in (429, 500, 502, 503, 504):
                pause = response.headers.get("Retry-After")
                try:
                    delay = min(120, float(pause)) if pause else min(60, 2 ** attempt + random.random())
                except ValueError:
                    delay = min(60, 2 ** attempt + random.random())
                logging.warning("%s response from %s; retry in %.1fs", response.status_code, url.split("?")[0], delay)
                time.sleep(delay)
                continue
            response.raise_for_status()
            return response
        except (requests.ConnectionError, requests.Timeout):
            if attempt == 4:
                raise
            time.sleep(min(60, 2 ** attempt + random.random()))
    raise RuntimeError(f"source unavailable: {url.split('?')[0]}")


def poll(name, interval, callback):
    while True:
        try:
            callback()
        except (requests.RequestException, ValueError, KeyError, RuntimeError) as exc:
            logging.error("%s: %s", name, exc)
        time.sleep(max(interval, 1))


# The five bond tenor definitions. US 2Y is the official Treasury daily fallback,
# with an opt-in Naver page extraction only after written scraping authorization.
TENORS = {
    "3M": ("^IRX", "BC_3MONTH"),
    "2Y": (None, "BC_2YEAR"),
    "5Y": ("^FVX", "BC_5YEAR"),
    "10Y": ("^TNX", "BC_10YEAR"),
    "30Y": ("^TYX", "BC_30YEAR"),
}

# Finance Yahoo symbols are NOT the same as the spot reference values.
YF_MARKET_SYMBOLS = {
    "VIX": ("^VIX", "volatility_index", "index_point"),
    "UST_3M": ("^IRX", "treasury_yield_index", "percent"),
    "UST_5Y": ("^FVX", "treasury_yield_index", "percent"),
    "UST_10Y": ("^TNX", "treasury_yield_index", "percent"),
    "UST_30Y": ("^TYX", "treasury_yield_index", "percent"),
}
YF_CHOICES = list(YF_MARKET_SYMBOLS)

# Prices are BINANCE contracts, not Yahoo front-month futures or OTC spot.
# USDT denomination is NOT the same as a USD settlement quote.
BINANCE_TRADFI_SYMBOLS = {
    "GOLD_BINANCE_PERP": ("XAUUSDT", "commodity_gold_linked_perpetual", "USDT/gold_contract_unit"),
    "SILVER_BINANCE_PERP": ("XAGUSDT", "commodity_silver_linked_perpetual", "USDT/silver_contract_unit"),
    "COPPER_BINANCE_PERP": ("COPPERUSDT", "commodity_copper_linked_perpetual", "USDT/copper_contract_unit"),
    "WTI_BINANCE_PERP": ("CLUSDT", "commodity_wti_linked_perpetual", "USDT/oil_contract_unit"),
    "BRENT_BINANCE_PERP": ("BZUSDT", "commodity_brent_linked_perpetual", "USDT/oil_contract_unit"),
}
BINANCE_SPOT_SYMBOLS = {
    "BITCOIN_BINANCE_SPOT": ("BTCUSDT", "spot_crypto", "USDT/BTC"),
}
BINANCE_FUTURES_REST = "https://fapi.binance.com/fapi/v1"
BINANCE_FUTURES_DATA_REST = "https://fapi.binance.com/futures/data"
BINANCE_LONGSHORT_TYPES = {
    "global_accounts": ("/globalLongShortAccountRatio", "long_short_account_ratio"),
    "top_accounts": ("/topLongShortAccountRatio", "top_trader_account_ratio"),
    "top_positions": ("/topLongShortPositionRatio", "top_trader_position_ratio"),
    "taker_volume": ("/takerlongshortRatio", "taker_buy_sell_volume_ratio"),
}
BINANCE_LONGSHORT_PERIODS = ("5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d")
BINANCE_LONGSHORT_SYMBOLS = ("BTCUSDT",) + tuple(value[0] for value in BINANCE_TRADFI_SYMBOLS.values())
BINANCE_RATIO_SEEN = {}  # In-process dedup; durable storage must also key on period end.
BINANCE_FUTURES_WS = "wss://fstream.binance.com/market/stream?streams="
BINANCE_SPOT_WS = "wss://data-stream.binance.vision/stream?streams="
NAVER_2Y_PAGE = "https://m.stock.naver.com/marketindex/bond/US2YT=RR"
NAVER_BOND_LIST = "https://m.stock.naver.com/front-api/marketIndex/bondList"



def yf_market(selected, bar_interval="1m", period="1d"):
    """One latest bar per market; Yahoo data can be exchange-delayed."""
    import yfinance as yf  # optional library required only for this source
    for key in selected:
        symbol, instrument_type, unit = YF_MARKET_SYMBOLS[key]
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=bar_interval,
                                auto_adjust=False, timeout=15)
            if df.empty:
                logging.warning("yfinance: no bars for %s %s", key, symbol)
                continue
            metadata = ticker.get_history_metadata() or {}
            last = df.iloc[-1]
            timestamp = df.index[-1].isoformat()
            close = last.get("Close")
            if close is None or close != close:  # NaN check
                continue
            emit("yfinance", key, float(close), timestamp,
                 symbol=symbol, instrument_type=instrument_type, unit=unit,
                 open=float(last["Open"]) if last["Open"] == last["Open"] else None,
                 high=float(last["High"]) if last["High"] == last["High"] else None,
                 low=float(last["Low"]) if last["Low"] == last["Low"] else None,
                 bar_interval=bar_interval, quote_exchange=metadata.get("exchangeName"),
                 exchange_delay_minutes=metadata.get("exchangeDataDelayedBy"),
                 status="potentially_delayed",
                 source_url="https://finance.yahoo.com/quote/" + symbol,
                 note="Web research/personal use; no guarantee of licensed or undelayed market data")
        except Exception as exc:
            logging.error("yfinance source %s (%s) unavailable: %s", key, symbol, exc)


def treasury_five():
    """Official daily 3M/2Y/5Y/10Y/30Y PAR yield curve, separate from Yahoo indices."""
    import xml.etree.ElementTree as ET
    now = dt.datetime.now(UTC)
    for month in (now.strftime("%Y%m"), (now.replace(day=1) - dt.timedelta(days=1)).strftime("%Y%m")):
        response = request("GET",
            "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml",
            params={"data": "daily_treasury_yield_curve", "field_tdr_date_value_month": month},
            headers={"Accept": "application/xml,application/atom+xml"})
        root = ET.fromstring(response.content)
        entries = root.findall("{http://www.w3.org/2005/Atom}entry")
        if not entries:
            continue
        data = []
        for entry in entries:
            row = {node.tag.split("}")[-1]: node.text for node in entry.iter()}
            if row.get("NEW_DATE"):
                data.append(row)
        if not data:
            continue
        last = max(data, key=lambda r: r["NEW_DATE"])
        for tenor, (_, field) in TENORS.items():
            value = last.get(field)
            if value is None or not value.strip():
                logging.warning("Treasury missing %s at %s", tenor, last["NEW_DATE"])
                continue
            emit("US_Treasury", "UST_" + tenor + "_PAR_YIELD",
                 float(value), last["NEW_DATE"][:10], unit="percent",
                 instrument_type="official_daily_par_yield",
                 source_url="https://home.treasury.gov/treasury-daily-interest-rate-xml-feed",
                 status="official_daily_not_live")
        return
    raise RuntimeError("No Treasury daily yield curve entries found for current/previous month")


def binance_futures_snapshot(selected=None):
    """Read-only latest Binance TradFi perpetual prices, NOT spot/fixed futures."""
    selected = selected or list(BINANCE_TRADFI_SYMBOLS)
    for series in selected:
        symbol, instrument_type, unit = BINANCE_TRADFI_SYMBOLS[series]
        response = request("GET", BINANCE_FUTURES_REST + "/ticker/price",
                           params={"symbol": symbol}).json()
        if response.get("symbol") != symbol or response.get("price") is None:
            raise RuntimeError(f"Unexpected Binance futures price response for {symbol}")
        emit("binance_futures", series, float(response["price"]),
             millis(response["time"]) if response.get("time") is not None else None,
             symbol=symbol, instrument_type=instrument_type, unit=unit,
             quote_currency="USDT", data_kind="perpetual_last_price",
             market_status="unverified_session",
             source_url=BINANCE_FUTURES_REST + "/ticker/price",
             note="Exchange contract last trade; not gold spot or NYMEX/ICE dated futures")


def binance_longshort(symbols=None, types=None, period="5m"):
    """Latest *completed aggregate interval* ratios (REST, min 5m).

    These are exchange-wide summaries, not per-trade real-time position updates.
    'taker_volume' measures aggressive buy versus sell volume, not open
    long/short positions. Provider occasionally uses surprising property names
    for top_positions; record the raw field names rather than reinterpret them.
    """
    symbols = symbols or BINANCE_LONGSHORT_SYMBOLS
    types = types or tuple(BINANCE_LONGSHORT_TYPES)
    if period not in BINANCE_LONGSHORT_PERIODS:
        raise ValueError(f"Binance ratio period unsupported: {period}")
    for symbol in symbols:
        for kind in types:
            path, meaning = BINANCE_LONGSHORT_TYPES[kind]
            url = BINANCE_FUTURES_DATA_REST + path
            try:
                data = request("GET", url, params={
                    "symbol": symbol, "period": period, "limit": 2}).json()
                if not isinstance(data, list) or not data:
                    logging.warning("Binance ratio empty for %s %s %s",
                                    symbol, kind, period)
                    continue
                latest = max(data, key=lambda x: int(x.get("timestamp") or 0))
                if not latest.get("timestamp"):
                    logging.warning("Binance ratio missing timestamp for %s %s",
                                    symbol, kind)
                    continue
                raw_stamp = int(latest["timestamp"])
                key = (symbol, kind, period)
                if BINANCE_RATIO_SEEN.get(key) == raw_stamp:
                    continue
                raw_ratio = latest.get("buySellRatio") if kind == "taker_volume" else latest.get("longShortRatio")
                if raw_ratio is None:
                    logging.warning("Binance ratio missing data for %s %s",
                                    symbol, kind)
                    continue
                value = float(raw_ratio)
                if value < 0:
                    raise ValueError(f"Negative ratio for {symbol} {kind}")
                # The response field names vary (e.g. top positions sometimes
                # arrives with longAccount/shortAccount). Expose them literally.
                extra = {k: float(latest[k]) for k in
                         ("longAccount", "shortAccount", "longPosition",
                          "shortPosition", "buyVol", "sellVol") if latest.get(k) is not None}
                series = "BINANCE_" + kind.upper() + "_" + symbol
                emit("binance_futures", series, value, millis(raw_stamp),
                     symbol=symbol, unit="ratio", kind=kind, ratio_definition=meaning,
                     period=period, period_end_utc=millis(raw_stamp),
                     source_url=url, data_kind="periodic_rest_aggregate_not_live_tick",
                     quote_currency="USDT", raw_response_fields=extra,
                     note="5-minute-or-longer published aggregates; no real-time position WS guarantee")
                BINANCE_RATIO_SEEN[key] = raw_stamp
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                logging.error("Binance ratio %s %s %s: %s",
                              symbol, kind, period, exc)


def gold():
    """Legacy 'gold' command now uses Binance real-time-source XAU perp snapshot."""
    binance_futures_snapshot(["GOLD_BINANCE_PERP"])


def gold_spot_reference():
    """Optional third-party gold spot *reference*: NOT Binance, NOT live."""
    data = request("GET", "https://api.gold-api.com/price/XAU").json()
    if data.get("price") is None:
        raise RuntimeError("Gold API returned no numeric reference price")
    emit("gold-api", "XAUUSD.spot_reference", float(data["price"]),
         data.get("updatedAt") or data.get("updated_at"), unit="USD/troy_oz",
         instrument_type="third_party_spot_estimate", raw_timestamp=data.get("updatedAt"),
         note="Separate reference; never merge with Binance XAUUSDT perp quotes")


def naver_2y():
    """Retired source; use approved Toss browser or Treasury daily fallback."""
    raise RuntimeError("Naver 2Y retired; use the approved Toss worker or treasury-five")


def sec_8k():
    if USER_AGENT == "AutoAxeResearch/0.1" or "@" not in USER_AGENT:
        raise RuntimeError("For SEC set AUTO_AXE_USER_AGENT='AutoAxe your-real-contact@example.com'")
    url = "https://www.sec.gov/cgi-bin/browse-edgar"
    params = {"action": "getcurrent", "type": "8-K", "company": "",
              "dateb": "", "owner": "exclude", "count": 100, "output": "atom"}
    body = request("GET", url, params=params, headers={
        "Accept": "application/atom+xml",
        "User-Agent": USER_AGENT
    }).content
    feed = feedparser.parse(body)
    if feed.bozo and not feed.entries:
        raise RuntimeError(f"invalid Atom feed: {feed.bozo_exception}")
    for entry in feed.entries:
        uid = entry.get("id") or entry.get("link") or ""
        if not uid:
            continue
        if uid in seen_sec:
            continue
        seen_sec.add(uid)
        emit("sec", "filing.8-K", entry.get("title", ""),
             entry.get("updated") or entry.get("published"),
             uid=uid, link=entry.get("link"), event_type="new_disclosure",
             note="Filing detected; guidance must be extracted from 8-K and exhibits")
    if len(seen_sec) > 10000:
        seen_sec.clear()


seen_sec = set()
seen_calendar = {}
seen_rss = set()

# Official publicly published feeds; verify each issuer's terms before production use.
OFFICIAL_FEEDS = {
    "fed": "https://www.federalreserve.gov/feeds/press_monetary.xml",
    "boj": "https://www.boj.or.jp/en/rss/whatsnew.xml",
    "ecb": "https://www.ecb.europa.eu/rss/press.html",
    "nvidia-pr": "https://nvidianews.nvidia.com/cats/press_release.xml",
    "nvidia-ir-events": "https://investor.nvidia.com/rss/event.aspx",
}


def rss(name):
    url = OFFICIAL_FEEDS[name]
    response = request("GET", url, headers={"Accept": "application/rss+xml,application/atom+xml,application/xml"})
    feed = feedparser.parse(response.content)
    if feed.bozo and not feed.entries:
        raise RuntimeError(f"invalid RSS/Atom: {feed.bozo_exception}")
    if not feed.entries:
        raise RuntimeError("RSS/Atom returned no entries; manually verify source")
    for entry in feed.entries:
        uid = entry.get("id") or entry.get("link") or ""
        if not uid or (name, uid) in seen_rss:
            continue
        seen_rss.add((name, uid))
        emit(name, "official_rss.new_entry", entry.get("title", ""),
             entry.get("published") or entry.get("updated"),
             uid=uid, link=entry.get("link"), summary=entry.get("summary", "")[:180],
             note="Announcement headline, verify official article for numeric rate/guidance")
    if len(seen_rss) > 20000:
        seen_rss.clear()


def bls_calendar():
    url = "https://www.bls.gov/schedule/news_release/bls.ics"
    response = request("GET", url, headers={"Accept": "text/calendar"})
    cal = Calendar.from_ical(response.content)
    for item in cal.walk("VEVENT"):
        uid = str(item.get("UID", ""))
        if not uid:
            continue
        title = str(item.get("SUMMARY", ""))
        event_start = item.get("DTSTART").dt
        if isinstance(event_start, dt.date) and not isinstance(event_start, dt.datetime):
            when = event_start.isoformat()
        else:
            when = event_start.isoformat()
        status = str(item.get("STATUS", "CONFIRMED"))
        digest = hashlib.sha256(f"{title}|{when}|{status}".encode()).hexdigest()
        if seen_calendar.get(uid) == digest:
            continue
        seen_calendar[uid] = digest
        emit("bls", "release_schedule", title, when, uid=uid, status=status,
             raw_timezone=str(getattr(event_start, "tzinfo", "")),
             note="scheduled event, not actual indicator result")


def bls_actual():
    series = [v.strip() for v in os.getenv(
        "BLS_SERIES", "CUUR0000SA0,CES0000000001,LNS14000000"
    ).split(",") if v.strip()]
    if len(series) > 25:
        raise RuntimeError("limit BLS_SERIES to at most 25 unless plan checked")
    year = str(dt.datetime.now(UTC).year)
    payload = {"seriesid": series, "startyear": year, "endyear": year}
    if os.getenv("BLS_API_KEY"):
        payload["registrationkey"] = os.environ["BLS_API_KEY"]
    data = request("POST", "https://api.bls.gov/publicAPI/v2/timeseries/data/",
                   json=payload).json()
    if data.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError("BLS API returned: " + str(data.get("message")))
    for block in data.get("Results", {}).get("series", []):
        for item in block.get("data", [])[:3]:
            period = item.get("period")
            if not period or not period.startswith("M"):
                continue
            emit("bls", block["seriesID"], item.get("value"), None,
                 period=f"{item.get('year')}-{period}", revision_aware=False,
                 note="Published-time not provided by API; do not treat received_at as release_at")


def fred(series):
    key = os.getenv("FRED_API_KEY")
    if not key:
        raise RuntimeError("FRED_API_KEY is required")
    data = request("GET", "https://api.stlouisfed.org/fred/series/observations",
                   params={"series_id": series, "api_key": key,
                           "file_type": "json", "sort_order": "desc", "limit": 3}).json()
    for item in data.get("observations", []):
        if item.get("value") == ".":
            continue
        emit("fred", series, item.get("value"), item.get("date"),
             frequency="source_frequency", note="Observation date is not publication timestamp")


def eia(series):
    key = os.getenv("EIA_API_KEY")
    if not key:
        raise RuntimeError("EIA_API_KEY is required")
    data = request("GET", f"https://api.eia.gov/v2/seriesid/{series}",
                   params={"api_key": key}).json()
    response = data.get("response", {})
    if isinstance(response, dict):
        for row in response.get("data", [])[:5]:
            emit("eia", series, row.get("value"), row.get("period"),
                 note="EIA daily spot observation, not live futures")
    else:
        raise RuntimeError("EIA response schema changed; inspect manually")


def vix_eod():
    import csv
    import io
    url = "https://cdn-api.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
    rows = list(csv.DictReader(io.StringIO(request("GET", url).text)))
    for row in rows[-3:]:
        emit("cboe", "VIX.EOD", row.get("CLOSE"), row.get("DATE"),
             open=row.get("OPEN"), high=row.get("HIGH"), low=row.get("LOW"),
             note="Daily close; never label this as real-time")


async def binance_futures_live():
    """Aggregate trade ticks from Binance's *tradfi perpetual contracts*."""
    symbols = [item[0].lower() for item in BINANCE_TRADFI_SYMBOLS.values()]
    stream_names = [f"{sym}@aggTrade" for sym in symbols]
    uri = BINANCE_FUTURES_WS + "/".join(stream_names)
    by_symbol = {value[0]: (key, value[1], value[2])
                 for key, value in BINANCE_TRADFI_SYMBOLS.items()}
    backoff = 1
    while True:
        try:
            async with connect(uri, ping_interval=20, ping_timeout=20,
                               open_timeout=15, max_size=2**20) as ws:
                backoff = 1
                async for raw in ws:
                    obj = json.loads(raw)
                    msg = obj.get("data", obj)
                    if msg.get("e") != "aggTrade":
                        continue
                    symbol = msg.get("s")
                    if symbol not in by_symbol or not msg.get("p"):
                        continue
                    series, instrument_type, unit = by_symbol[symbol]
                    emit("binance_futures", series, float(msg["p"]),
                         millis(msg["T"]) if msg.get("T") is not None else None,
                         symbol=symbol, quote_currency="USDT",
                         instrument_type=instrument_type, unit=unit,
                         data_kind="live_aggregate_perpetual_trade",
                         aggregate_trade_id=msg.get("a"), qty=msg.get("q"),
                         market_status="underlying_may_be_closed",
                         source_url="https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures",
                         note="Binance contract tick, NOT physical spot or CME/ICE futures")
        except Exception as exc:
            logging.warning("Binance Futures WS disconnected: %s; retry in %ss", exc, backoff)
            await asyncio.sleep(backoff + random.random())
            backoff = min(backoff * 2, 60)


async def binance_spot_btc_live():
    """Public Binance SPOT BTCUSDT trade ticks; USDT/BTC, not USD/BTC."""
    uri = BINANCE_SPOT_WS + "btcusdt@trade"
    backoff = 1
    while True:
        try:
            async with connect(uri, ping_interval=20, ping_timeout=20,
                               open_timeout=15, max_size=2**20) as ws:
                backoff = 1
                async for raw in ws:
                    obj = json.loads(raw)
                    msg = obj.get("data", obj)
                    if msg.get("e") != "trade" or msg.get("s") != "BTCUSDT":
                        continue
                    emit("binance_spot", "BITCOIN_BINANCE_SPOT",
                         float(msg["p"]), millis(msg["T"]),
                         symbol="BTCUSDT", unit="USDT/BTC",
                         instrument_type="spot_crypto",
                         data_kind="exchange_trade",
                         trade_id=msg.get("t"), qty=msg.get("q"),
                         source_url="https://data-api.binance.vision",
                         note="Actual exchange BTC/USDT trade, not Yahoo BTC/USD index")
        except Exception as exc:
            logging.warning("Binance spot BTC WS disconnected: %s; retry in %ss", exc, backoff)
            await asyncio.sleep(backoff + random.random())
            backoff = min(backoff * 2, 60)


async def binance_market_live():
    await asyncio.gather(binance_futures_live(), binance_spot_btc_live())


async def coinbase():
    uri = "wss://ws-feed.exchange.coinbase.com"
    subscription = {"type": "subscribe", "product_ids": ["BTC-USD"],
                    "channels": ["ticker", "heartbeat"]}
    backoff = 1
    while True:
        try:
            async with connect(uri, ping_interval=20, ping_timeout=20,
                               open_timeout=15, max_size=2**20) as ws:
                await ws.send(json.dumps(subscription))
                backoff = 1
                async for raw in ws:
                    message = json.loads(raw)
                    if message.get("type") == "ticker":
                        emit("coinbase", "BTC-USD.trade_ticker",
                             message.get("price"), message.get("time"),
                             trade_id=message.get("trade_id"), best_bid=message.get("best_bid"),
                             best_ask=message.get("best_ask"), quote="USD")
        except (OSError, Exception) as exc:
            logging.warning("Coinbase WS lost: %s; reconnect in %ss", exc, backoff)
            await asyncio.sleep(backoff + random.random())
            backoff = min(backoff * 2, 60)


async def binance():
    # This is a public market-data-only endpoint; availability varies by region.
    uri = "wss://data-stream.binance.vision/stream?streams=btcusdt@trade/btcusdt@kline_1m"
    backoff = 1
    while True:
        try:
            async with connect(uri, ping_interval=None, open_timeout=15,
                               max_size=2**20) as ws:
                backoff = 1
                async for raw in ws:
                    wrapper = json.loads(raw)
                    msg = wrapper.get("data", {})
                    if msg.get("e") == "trade":
                        emit("binance", "BTCUSDT.trade", msg.get("p"),
                             millis(msg["T"]), qty=msg.get("q"),
                             trade_id=msg.get("t"), quote="USDT")
                    elif msg.get("e") == "kline":
                        k = msg.get("k", {})
                        if k.get("x"):  # finalized bar only
                            emit("binance", "BTCUSDT.1m.close", k.get("c"),
                                 millis(k["T"]), open=k.get("o"), high=k.get("h"),
                                 low=k.get("l"), volume_base=k.get("v"), closed=True,
                                 quote="USDT")
        except (OSError, Exception) as exc:
            logging.warning("Binance WS lost: %s; reconnect in %ss", exc, backoff)
            await asyncio.sleep(backoff + random.random())
            backoff = min(backoff * 2, 60)


def main():
    load_dotenv()
    global USER_AGENT
    USER_AGENT = os.getenv("AUTO_AXE_USER_AGENT", "AutoAxeResearch/0.1")
    SESSION.headers.update({"User-Agent": USER_AGENT})
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=[
        "gold", "sec-8k", "bls-calendar", "bls-actual", "fred", "eia",
        "vix-eod", "coinbase", "binance", "rss", "yf-market", "treasury-five",
        "binance-live", "binance-futures", "binance-longshort", "naver-2y", "gold-spot-reference"])
    parser.add_argument("--symbols", nargs="+", default=YF_CHOICES,
                        choices=YF_CHOICES,
                        help="market indicators for yfinance (2Y is official Treasury only)")
    parser.add_argument("--bar-interval", default="1m",
                        help="yfinance bar interval: 1m, 5m, 1d (not real-time guarantee)")
    parser.add_argument("--period", default="1d", help="yfinance lookback (1d, 5d, etc)")
    parser.add_argument("--ratio-symbols", nargs="+",
                        choices=BINANCE_LONGSHORT_SYMBOLS,
                        default=list(BINANCE_LONGSHORT_SYMBOLS),
                        help="Binance USD-M contracts for periodic ratios")
    parser.add_argument("--ratio-types", nargs="+",
                        choices=tuple(BINANCE_LONGSHORT_TYPES),
                        default=list(BINANCE_LONGSHORT_TYPES),
                        help="global_accounts, top_accounts, top_positions, taker_volume")
    parser.add_argument("--ratio-period", choices=BINANCE_LONGSHORT_PERIODS,
                        default="5m", help="Binance min ratio interval is 5m (no real-time WS)")
    parser.add_argument("--series", default="", help="FRED or EIA series ID")
    parser.add_argument("--feed", choices=sorted(OFFICIAL_FEEDS), help="official RSS name for rss command")
    parser.add_argument("--interval", type=int, default=0,
                        help="poll seconds; 0=one-shot; SEC >=60, BLS actual >=900 recommended")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.source in ("coinbase", "binance", "binance-live"):
        if args.source == "coinbase":
            asyncio.run(coinbase())
        elif args.source == "binance":
            asyncio.run(binance())
        else:
            asyncio.run(binance_market_live())
        return
    if args.source == "fred" and not args.series:
        parser.error("fred requires --series (example: DGS10)")
    if args.source == "eia" and not args.series:
        parser.error("eia requires --series (example: PET.RWTC.D)")
    if args.source == "rss" and not args.feed:
        parser.error("rss requires --feed (e.g. fed, boj, ecb, nvidia-pr)")
    cb = {
        "gold": gold, "binance-futures": binance_futures_snapshot,
        "binance-longshort": lambda: binance_longshort(args.ratio_symbols, args.ratio_types, args.ratio_period),
        "gold-spot-reference": gold_spot_reference,
        "naver-2y": naver_2y,
        "sec-8k": sec_8k, "bls-calendar": bls_calendar,
        "bls-actual": bls_actual, "fred": lambda: fred(args.series),
        "eia": lambda: eia(args.series), "vix-eod": vix_eod,
        "rss": lambda: rss(args.feed),
        "yf-market": lambda: yf_market(args.symbols, args.bar_interval, args.period),
        "treasury-five": treasury_five
    }[args.source]
    if args.interval > 0:
        poll(args.source, args.interval, cb)
    else:
        cb()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
    except (RuntimeError, requests.RequestException, ValueError, KeyError) as exc:
        logging.error("Collector stopped: %s", exc)
        sys.exit(2)
