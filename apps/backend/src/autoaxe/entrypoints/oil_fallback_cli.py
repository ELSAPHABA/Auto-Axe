"""Explicit opt-in oil primary/fallback worker. No default network access."""

import argparse
import asyncio
import os
import signal
from threading import Event

import psycopg

from autoaxe.application.oil_fallback import run_cycle


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-binance-oil", required=True, action="store_true")
    parser.add_argument(
        "--yahoo-provider-evidence",
        help="Exact approved source evidence reference covering automated CL=F/BZ=F WS use; "
        "without this, Yahoo remains disabled.",
    )
    parser.add_argument("--daemon", action="store_true")
    args = parser.parse_args()
    dsn = os.environ.get("AUTOAXE_MARKET_RUNTIME_DSN")
    if not dsn:
        parser.error("AUTOAXE_MARKET_RUNTIME_DSN is required")
    stopped = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    while not stopped.is_set():
        try:
            result = asyncio.run(
                run_cycle(
                    dsn,
                    enabled=args.allow_binance_oil,
                    yahoo_evidence=args.yahoo_provider_evidence,
                    stopped=stopped.is_set,
                )
            )
        except psycopg.Error:
            print("oil: database_unavailable", flush=True)
            if not args.daemon:
                raise SystemExit(1) from None
        else:
            print(
                "oil: " + " ".join(f"{oil}={status}" for oil, status in result.items()), flush=True
            )
            if not args.daemon:
                if any(
                    status
                    not in ("primary_received", "fallback_received", "quiet", "not_due", "stopped")
                    for status in result.values()
                ):
                    raise SystemExit(1)
                return
        stopped.wait(10)


if __name__ == "__main__":
    main()
