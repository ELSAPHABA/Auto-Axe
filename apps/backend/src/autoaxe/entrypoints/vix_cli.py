"""Explicitly enabled private VIX refresh/stream runner."""

import argparse
import asyncio
import os
import signal
from threading import Event

import psycopg

from autoaxe.application.vix_refresh import refresh_vix
from autoaxe.infrastructure.market_store import PermissionDenied


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-vix-ws", action="store_true", required=True)
    parser.add_argument("--evidence-ref", required=True)
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
            result = asyncio.run(
                refresh_vix(
                    dsn,
                    enabled=args.allow_vix_ws,
                    evidence_ref=args.evidence_ref,
                    continuous_session=args.daemon,
                    stopped=stopped.is_set,
                )
            )
        except (psycopg.Error, PermissionDenied):
            result = "database_or_permission_unavailable"
        if result != previous:
            print(f"vix: {result}", flush=True)
        previous = result
        if not args.daemon:
            raise SystemExit(0 if result == "fresh" else 1)
        stopped.wait(5)


if __name__ == "__main__":
    main()
