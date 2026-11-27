"""Opt-in bounded sessions; no provider access without explicit CLI approval."""

import argparse
import asyncio
import os
import signal
from collections.abc import AsyncGenerator, Callable
from threading import Event

import psycopg

from autoaxe.adapters.mexc_ws import stream_tickers, wrapper_class
from autoaxe.application.mexc_ws_worker import run_session
from autoaxe.domain.market import Candidate


def stream(permit: Callable[[], None]) -> AsyncGenerator[Candidate, None]:
    return stream_tickers(permit, network_opt_in=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-mexc-ws", action="store_true", required=True)
    parser.add_argument("--daemon", action="store_true")
    args = parser.parse_args()
    dsn = os.environ.get("AUTOAXE_MARKET_RUNTIME_DSN")
    if not dsn:
        parser.error("AUTOAXE_MARKET_RUNTIME_DSN is required")
    wrapper_class()
    stopped = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    previous = None
    while not stopped.is_set():
        try:
            result = asyncio.run(
                run_session(dsn, stream, enabled=args.allow_mexc_ws, stopped=stopped.is_set)
            )
        except psycopg.Error:
            result = "database_unavailable"
        if result != "not_due" and (result != previous or result in ("stored", "no_update")):
            print(f"mexc-ws: {result}", flush=True)
        previous = result
        if not args.daemon:
            if result not in ("stored", "no_update", "not_due", "no_data", "stopped"):
                raise SystemExit(1)
            return
        stopped.wait(10)


if __name__ == "__main__":
    main()
