#!/usr/bin/env python3
"""Read-only Binance API coverage probe for Auto-Axe; no keys/orders.

This is supplemental market research, not a substitute for original VIX or
Treasury yields, and does not alter the existing yfinance-first collector.
"""
import argparse
import datetime as dt
import json
import sys
import requests

SPOT = "https://data-api.binance.vision/api/v3"
FUTURES = "https://fapi.binance.com/fapi/v1"
OPTIONS = "https://eapi.binance.com/eapi/v1"

WATCH = {
    "spot": {"BTCUSDT": "BTC spot quote in USDT",
             "BTCUSDC": "BTC spot quote in USDC",
             "PAXGUSDT": "PAX Gold token",
             "XAUTUSDT": "Tether Gold token"},
    "futures": {"BTCUSDT": "BTC USDT perpetual",
                "XAUUSDT": "Gold-linked TradFi perpetual",
                "CLUSDT": "WTI-linked TradFi perpetual",
                "BZUSDT": "Brent-linked TradFi perpetual",
                "UVXYUSDT": "Leveraged VIX ETF-linked perpetual (NOT VIX)",
                "TMFUSDT": "Long-duration leveraged Treasury ETF-linked perpetual",
                "TBTUSDT": "Long-duration inverse Treasury ETF-linked perpetual"}
}

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def get(session, url, params=None):
    response = session.get(url, params=params, timeout=15)
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict) and not isinstance(value, list):
        raise RuntimeError(f"Unexpected JSON schema from {url}")
    return value

def inspect(session, include_klines=False):
    for venue, base in (("spot", SPOT), ("futures", FUTURES)):
        exchange = get(session, base + "/exchangeInfo")
        symbols = {x["symbol"]: x for x in exchange.get("symbols", [])}
        print(json.dumps({"utc": now(), "venue": venue,
                          "total_registered": len(symbols),
                          "watched": [
                              {"symbol": sym, "registered": sym in symbols,
                               "status": symbols.get(sym, {}).get("status"),
                               "contract_type": symbols.get(sym, {}).get("contractType"),
                               "meaning": meaning}
                              for sym, meaning in WATCH[venue].items()]},
                         ensure_ascii=False))
        if include_klines:
            for sym in WATCH[venue]:
                if symbols.get(sym, {}).get("status") != "TRADING":
                    continue
                try:
                    bars = get(session, base + "/klines",
                               {"symbol": sym, "interval": "1m", "limit": 2})
                    if not isinstance(bars, list) or not bars:
                        raise RuntimeError("Empty klines")
                    print(json.dumps({"venue": venue, "symbol": sym,
                                      "bars_received": len(bars),
                                      "last_candle_open_utc": dt.datetime.fromtimestamp(
                                          bars[-1][0] / 1000, dt.timezone.utc).isoformat()},
                                     ensure_ascii=False))
                except (requests.RequestException, RuntimeError, ValueError) as exc:
                    print(json.dumps({"venue":venue,"symbol":sym,"error":str(exc)},
                                     ensure_ascii=False), file=sys.stderr)
    options = get(session, OPTIONS + "/exchangeInfo")
    o = options.get("optionSymbols", [])
    underlying = {}
    for sym in o:
        key = sym.get("underlying", "unknown")
        underlying[key] = underlying.get(key, 0) + 1
    print(json.dumps({"utc": now(), "venue": "options",
                      "total_registered": len(o),
                      "underlying_counts": underlying,
                      "expiry_fields": ["symbol","underlying","expiryDate","strikePrice","side","status"]},
                     ensure_ascii=False))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--klines", action="store_true",
                        help="also query two recent 1m bars for each trading watched symbol")
    args = parser.parse_args()
    session = requests.Session()
    session.headers.update({"User-Agent":"AutoAxe-ReadOnlyCoverage/1.0", "Accept":"application/json"})
    inspect(session, include_klines=args.klines)

if __name__ == "__main__":
    main()
