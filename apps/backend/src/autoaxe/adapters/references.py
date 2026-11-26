"""Offline normalization of optional market references from the original PoC.

References never replace the primary tick source. No URL is fetched here.
"""

from datetime import date, datetime
from typing import Any

from autoaxe.adapters.providers import millis, number
from autoaxe.domain.catalog import FUTURES
from autoaxe.domain.market import Candidate, Quality
from autoaxe.domain.types import utc_datetime, utc_string

COMMANDS = (
    "gold",
    "binance-futures",
    "gold-spot-reference",
    "eia",
    "vix-eod",
    "coinbase",
    "binance-kline",
)


def _stamp(raw: Any) -> datetime | None:
    return utc_datetime(datetime.fromisoformat(raw)) if raw else None


def _daily(
    sid: str, day: date, value: Any, received: datetime, metadata: dict[str, Any]
) -> Candidate:
    if day > received.date():
        raise ValueError("future daily observation")
    return Candidate(
        sid,
        day.isoformat(),
        number(str(value)) if value is not None else None,
        None,
        received,
        received,
        Quality.UNKNOWN if value is not None else Quality.NO_DATA,
        {**metadata, "observation_date": day.isoformat(), "daily_reference": True},
    )


def normalize_reference(
    command: str, payload: dict[str, Any], received: datetime, *, symbol: str | None = None
) -> list[Candidate]:
    if command in ("gold", "binance-futures"):
        sym = payload["symbol"]
        if sym not in FUTURES or (command == "gold" and sym != "XAUUSDT"):
            raise ValueError("snapshot symbol mismatch")
        if symbol is not None and symbol != sym:
            raise ValueError("snapshot symbol mismatch")
        stamp = millis(payload["time"]) if payload.get("time") is not None else None
        return [
            Candidate(
                FUTURES[sym][0] + "_SNAPSHOT",
                utc_string(stamp) if stamp else "missing:" + utc_string(received),
                number(payload["price"]),
                stamp,
                received,
                received,
                Quality.VALID if stamp else Quality.UNKNOWN,
                {"symbol": sym, "quote_currency": "USDT", "snapshot": True},
            )
        ]
    if command == "gold-spot-reference":
        stamp = _stamp(payload.get("updatedAt") or payload.get("updated_at"))
        return [
            Candidate(
                "GOLD_SPOT_REFERENCE",
                utc_string(stamp) if stamp else "missing:" + utc_string(received),
                number(str(payload["price"])),
                stamp,
                received,
                received,
                Quality.UNKNOWN,
                {"symbol": "XAUUSD", "quote_currency": "USD", "reference_only": True},
            )
        ]
    if command == "eia":
        sid = {"PET.RWTC.D": "WTI_EIA_DAILY", "PET.RBRTE.D": "BRENT_EIA_DAILY"}.get(symbol or "")
        if not sid:
            raise ValueError("unknown EIA series")
        rows = payload["response"]["data"]
        if not isinstance(rows, list) or len(rows) > 1000:
            raise ValueError("invalid EIA data")
        return sorted(
            [
                _daily(
                    sid,
                    date.fromisoformat(row["period"]),
                    row.get("value"),
                    received,
                    {"symbol": symbol, "unit": "USD/bbl"},
                )
                for row in rows
            ],
            key=lambda row: row.key,
        )
    if command == "vix-eod":
        raw = payload["DATE"]
        day = datetime.strptime(raw, "%m/%d/%Y").date()
        meta = {
            k.lower(): number(str(payload[k]))
            for k in ("OPEN", "HIGH", "LOW")
            if payload.get(k) not in (None, "")
        }
        return [_daily("VIX_CBOE_EOD", day, payload.get("CLOSE"), received, meta)]
    if command == "coinbase":
        if payload.get("type") != "ticker" or payload.get("product_id") != "BTC-USD":
            raise ValueError("not BTC-USD ticker")
        stamp = _stamp(payload["time"])
        if stamp is None:
            raise ValueError("ticker missing timestamp")
        return [
            Candidate(
                "BITCOIN_COINBASE_USD",
                str(int(payload["trade_id"])),
                number(payload["price"]),
                stamp,
                received,
                received,
                Quality.VALID,
                {
                    "symbol": "BTC-USD",
                    "quote_currency": "USD",
                    "best_bid": number(payload["best_bid"]),
                    "best_ask": number(payload["best_ask"]),
                },
            )
        ]
    if command == "binance-kline":
        msg = payload.get("data", payload)
        bar = msg["k"]
        if msg.get("e") != "kline" or msg.get("s") != "BTCUSDT" or bar.get("i") != "1m":
            raise ValueError("not BTCUSDT 1m bar")
        if bar.get("x") is not True:
            return []
        stamp = millis(bar["T"])
        return [
            Candidate(
                "BTCUSDT_BINANCE_SPOT_1M_CLOSE",
                utc_string(stamp),
                number(bar["c"]),
                stamp,
                received,
                received,
                Quality.UNKNOWN,
                {
                    "bar_closed": True,
                    "bar_interval": "1m",
                    "symbol": "BTCUSDT",
                    "open": number(bar["o"]),
                    "high": number(bar["h"]),
                    "low": number(bar["l"]),
                    "volume_base": number(bar["v"]),
                },
            )
        ]
    raise ValueError("unknown reference command")
