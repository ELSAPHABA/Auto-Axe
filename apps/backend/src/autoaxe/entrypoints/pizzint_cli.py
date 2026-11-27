"""Run only the fixed DOUGHCON adapter; no generic scraper or trading runtime."""

import argparse
import http.client
import importlib
import os
import signal
from collections.abc import Callable, Mapping
from threading import Event
from typing import Any, cast

import psycopg

from autoaxe.application.collection import FetchError
from autoaxe.application.pizzint_poll import poll_once


def fetch_doughcon(permit: Callable[[], None]) -> Mapping[str, Any]:
    # The dedicated image includes only the dependency-free pinned reader and
    # its policy module from apps/scraper, not the general browser/scraper runtime.
    transport = importlib.import_module("autoaxe_scraper.transport")
    try:
        return cast(Mapping[str, Any], transport.fetch_pizzint_doughcon(permit=permit))
    except transport.ProviderHTTPError as exc:
        raise FetchError(exc.status, exc.retry_header) from None
    except transport.SourceBlocked:
        raise ValueError("DOUGHCON response rejected") from None
    except http.client.HTTPException:
        raise ConnectionError("DOUGHCON HTTP transport error") from None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    dsn = os.environ.get("AUTOAXE_MARKET_RUNTIME_DSN")
    if not dsn:
        parser.error("AUTOAXE_MARKET_RUNTIME_DSN is required")
    # Fail at startup if the fixed transport was not packaged.
    importlib.import_module("autoaxe_scraper.transport")
    stopped = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    previous = None
    while not stopped.is_set():
        try:
            result = poll_once(dsn, fetch_doughcon)
        except psycopg.Error:
            result = "database_unavailable"
        if result != "not_due" and (result != previous or result in {"stored", "no_update"}):
            print(f"pizzint: {result}", flush=True)
        previous = result
        if args.once:
            if result not in {"stored", "no_update", "not_due"}:
                raise SystemExit(1)
            return
        stopped.wait(10)


if __name__ == "__main__":
    main()
