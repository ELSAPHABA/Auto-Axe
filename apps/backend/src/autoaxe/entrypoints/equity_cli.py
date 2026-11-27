"""Manual, explicit Yahoo equity opt-in; never called by the fixture scheduler."""

import argparse
import asyncio
import os
import signal
from threading import Event

from autoaxe.application.equity_worker import run_daily, run_volume
from autoaxe.infrastructure.market_store import PermissionDenied


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("volume", "daily"))
    parser.add_argument("--allow-yahoo", action="store_true", required=True)
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--continuous", action="store_true")
    args = parser.parse_args()
    dsn = os.environ.get("AUTOAXE_MARKET_RUNTIME_DSN")
    if not dsn:
        parser.error("AUTOAXE_MARKET_RUNTIME_DSN is required")
    stopped = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    try:
        if args.command == "volume":
            ok = asyncio.run(
                run_volume(
                    dsn,
                    enabled=args.allow_yahoo,
                    duration=args.duration,
                    continuous=args.continuous,
                    stopped=stopped.is_set,
                )
            )
        else:
            ok = run_daily(
                dsn,
                enabled=args.allow_yahoo,
                continuous=args.continuous,
                stopped=stopped.is_set,
                wait=stopped.wait,
            )
    except PermissionDenied:
        print("yahoo equity: source permission denied or cooldown", flush=True)
        raise SystemExit(1) from None
    except Exception:
        # Provider exception messages can contain response URLs or credentials.
        print("yahoo equity: collection failed", flush=True)
        raise SystemExit(1) from None
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
