"""Explicit Phase 1 adapter dispatch. The scheduler never constructs external transports."""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from autoaxe.adapters.providers import normalize_ratio, normalize_treasury
from autoaxe.domain.catalog import FUTURES, RATIOS, YAHOO, catalog
from autoaxe.domain.market import Candidate


class PollAdapters:
    def __init__(
        self,
        *,
        authorize: Callable[[str], None],
        ratio: Callable[[str, str], list[dict[str, Any]]],
        yahoo: Callable[[str], Candidate],
        treasury: Callable[[], bytes],
        clock: Callable[[], datetime],
    ) -> None:
        self.authorize = authorize
        self.ratio = ratio
        self.yahoo = yahoo
        self.treasury = treasury
        self.clock = clock

    def collect(self, sid: str) -> list[Candidate]:
        self.authorize(sid)
        definition = catalog()[sid]
        if definition.source_id == "binance_futures" and definition.interval == "5m":
            kind = next(k for k in RATIOS if sid == f"BINANCE_{k.upper()}_{definition.symbol}")
            if definition.symbol not in ("BTCUSDT", *FUTURES):
                raise ValueError("ratio symbol invalid")
            raw = self.ratio(definition.symbol, kind)
            rows = normalize_ratio(definition.symbol, kind, raw, self.clock())
        elif sid in YAHOO:
            rows = [self.yahoo(sid)]
        elif definition.source_id == "treasury":
            rows = [
                row
                for row in normalize_treasury(self.treasury(), self.clock())
                if row.series_id == sid
            ]
        else:
            raise ValueError("no polling adapter")
        self.authorize(sid)
        if any(row.series_id != sid for row in rows):
            raise ValueError("adapter series mismatch")
        return rows
