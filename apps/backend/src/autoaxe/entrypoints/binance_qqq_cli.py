"""Opt-in dedicated Binance QQQ REST collection; defaults to a single attempt."""

import argparse
import asyncio
import os
import signal
from collections.abc import Callable
from threading import Event

import psycopg

from autoaxe.adapters.binance_qqq_rest import fetch_snapshot
from autoaxe.application.binance_qqq_poll import poll_once
from autoaxe.domain.market import Candidate


async def fetch(permit: Callable[[], None]) -> Candidate:
    return await fetch_snapshot(permit, network_opt_in=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-binance-qqq", action="store_true", required=True)
    parser.add_argument("--daemon", action="store_true")
    args = parser.parse_args()
    dsn = os.environ.get("AUTOAXE_MARKET_RUNTIME_DSN")
    if not dsn:
        parser.error("AUTOAXE_MARKET_RUNTIME_DSN is required")
    stopped = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    previous = None
    while not stopped.is_set():
        try:
            result = asyncio.run(poll_once(dsn, fetch, enabled=args.allow_binance_qqq))
        except psycopg.Error:
            result = "database_unavailable"
        if result != "not_due" and (result != previous or result in ("stored", "no_update")):
            print(f"binance_qqq: {result}", flush=True)
        previous = result
        if not args.daemon:
            if result not in ("stored", "no_update", "not_due"):
                raise SystemExit(1)
            return
        stopped.wait(10)


if __name__ == "__main__":
    main()
