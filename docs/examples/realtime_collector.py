#!/usr/bin/env python3
"""Auto-Axe reference collector (stdout JSON Lines, no orders).
Commands: gold, coinbase, binance, sec-8k, bls-calendar, bls-actual, fred, eia, vix-eod
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


def gold():
    data = request("GET", "https://api.gold-api.com/price/XAU").json()
    emit("gold-api", "XAUUSD.spot_estimate", data.get("price"),
         data.get("updatedAt") or data.get("updated_at"), unit="USD/troy_oz",
         price_type="third_party_spot_estimate", raw_timestamp=data.get("updatedAt"))


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
        "vix-eod", "coinbase", "binance", "rss"])
    parser.add_argument("--series", default="", help="FRED or EIA series ID")
    parser.add_argument("--feed", choices=sorted(OFFICIAL_FEEDS), help="official RSS name for rss command")
    parser.add_argument("--interval", type=int, default=0,
                        help="poll seconds; 0=one-shot; SEC >=60, BLS actual >=900 recommended")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.source in ("coinbase", "binance"):
        asyncio.run(coinbase() if args.source == "coinbase" else binance())
        return
    if args.source == "fred" and not args.series:
        parser.error("fred requires --series (example: DGS10)")
    if args.source == "eia" and not args.series:
        parser.error("eia requires --series (example: PET.RWTC.D)")
    if args.source == "rss" and not args.feed:
        parser.error("rss requires --feed (e.g. fed, boj, ecb, nvidia-pr)")
    cb = {
        "gold": gold, "sec-8k": sec_8k, "bls-calendar": bls_calendar,
        "bls-actual": bls_actual, "fred": lambda: fred(args.series),
        "eia": lambda: eia(args.series), "vix-eod": vix_eod,
        "rss": lambda: rss(args.feed)
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
