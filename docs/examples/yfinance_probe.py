#!/usr/bin/env python3
"""
Command:
  python docs/examples/yfinance_probe.py --interval 1m --period 5d
  python docs/examples/yfinance_probe.py --websocket --ws-seconds 45
"""
import argparse
import asyncio
import datetime as dt
import json
import sys

DEFAULT_SYMBOLS = ["^VIX", "^TNX", "^FVX", "^IRX", "^TYX", "CL=F", "BZ=F"]


def print_json(d):
    print(json.dumps(d, ensure_ascii=False, default=str), flush=True)


def get_bars(symbols, period, interval):
    import yfinance as yf

    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval,
                                auto_adjust=False, timeout=10)
            meta = ticker.get_history_metadata() or {}
            last = df.iloc[-1] if not df.empty else None
            event_at = df.index[-1].isoformat() if not df.empty else None
            print_json({
                "source": "yfinance/Yahoo Finance",
                "symbol": symbol,
                "method": "historical_intraday_or_daily_query",
                "rows": len(df),
                "interval": interval,
                "last_bar_at": event_at,
                "last_close": float(last["Close"]) if last is not None else None,
                "exchange": meta.get("exchangeName"),
                "instrument_type": meta.get("instrumentType"),
                "exchange_data_delayed_by": meta.get("exchangeDataDelayedBy"),
                "received_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "live_entitlement_confirmed": False,
                "note": "None delay metadata does NOT imply zero delay",
            })
        except Exception as exc:
            print_json({"symbol": symbol, "status": "error",
                        "error_type": type(exc).__name__,
                        "reason": str(exc)[:300]})


async def test_websocket(symbols, seconds):
    import yfinance as yf

    counter = 0

    def handler(message):
        nonlocal counter
        counter += 1
        print_json({"method": "yfinance_websocket",
                    "received_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "event": message})

    try:
        async with yf.AsyncWebSocket(verbose=False) as ws:
            await ws.subscribe(symbols)
            try:
                await asyncio.wait_for(ws.listen(handler), timeout=seconds)
            except asyncio.TimeoutError:
                print_json({"status": "timeout", "received_events": counter,
                            "note": "No events does not imply unsupported ticker on a closed market"})
    except Exception as exc:
        print_json({"status": "connection_error",
                    "error_type": type(exc).__name__,
                    "reason": str(exc)[:300]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--period", default="5d", help="e.g. 1d,5d,1mo")
    parser.add_argument("--interval", default="1m", help="e.g. 1m,5m,1d")
    parser.add_argument("--websocket", action="store_true",
                        help="optional bounded WS test; Yahoo symbol coverage not guaranteed")
    parser.add_argument("--ws-seconds", type=int, default=45)
    args = parser.parse_args()
    if args.ws_seconds < 1 or args.ws_seconds > 300:
        parser.error("--ws-seconds must be 1..300")
    if args.websocket:
        asyncio.run(test_websocket(args.symbols, args.ws_seconds))
    else:
        get_bars(args.symbols, args.period, args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
