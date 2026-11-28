from datetime import UTC, datetime, timedelta

import httpx
import pytest

from autoaxe.adapters.manual import HEADERS, manual_candidates
from autoaxe.adapters.providers import (
    FUTURES_WS,
    binance_rest_trade,
    binance_trade,
    normalize_naver,
    normalize_ratio,
    normalize_treasury,
    normalize_yahoo,
    ratio_request,
)
from autoaxe.adapters.transport import ProviderTransport, _FixedConnect
from autoaxe.application.collection import FetchError, GapTracker, bounded_fetch, recover_gap
from autoaxe.domain.catalog import FUTURES, RATIOS, catalog
from autoaxe.domain.market import Candidate, Quality, change_pct, quality_at
from autoaxe.infrastructure.jobs import retry_after

NOW = datetime(2026, 11, 26, 0, 0, 10, tzinfo=UTC)
MS = int((NOW - timedelta(seconds=1)).timestamp() * 1000)


def test_catalog():
    rows = catalog()
    assert len([x for x in rows if x.startswith("BINANCE_")]) == 24
    assert rows["BITCOIN_BINANCE_SPOT"].source_id == "binance_spot"
    assert rows["BINANCE_GLOBAL_ACCOUNTS_BTCUSDT"].source_id == "binance_futures"
    assert rows["VIX"].ttl == 10 and rows["UST_10Y"].ttl == 300
    assert rows["UST_2Y_TOSS"].indicator_id == rows["UST_2Y_TREASURY"].indicator_id
    assert not any("DUBAI" in x for x in rows)
    assert FUTURES_WS.startswith("wss://fstream.binance.com/market/stream?streams=")


@pytest.mark.parametrize("symbol", ["BTCUSDT", *FUTURES])
def test_trade_parity(symbol):
    spot = symbol == "BTCUSDT"
    key = "t" if spot else "a"
    msg = {
        "s": symbol,
        "e": "trade" if spot else "aggTrade",
        key: 5,
        "p": "123.45",
        "q": "0.01",
        "T": MS,
    }
    a = binance_trade({"data": msg}, NOW, spot=spot)
    row = (
        {"id": 5, "price": "123.45", "qty": "0.01", "time": MS}
        if spot
        else {"a": 5, "p": "123.45", "q": "0.01", "T": MS}
    )
    assert a == binance_rest_trade(symbol, row, NOW, spot=spot)
    assert a.value == "123.45" and a.metadata["quote_currency"] == "USDT"
    assert quality_at(a, catalog()[a.series_id], NOW) == Quality.VALID
    assert quality_at(a, catalog()[a.series_id], NOW + timedelta(seconds=11)) == Quality.STALE


@pytest.mark.parametrize("symbol", ["BTCUSDT", *FUTURES])
@pytest.mark.parametrize("kind", list(RATIOS))
def test_ratio_contract(symbol, kind):
    _, params = ratio_request(symbol, kind)
    assert params["period"] == "5m"
    field = RATIOS[kind][1]
    rows = normalize_ratio(
        symbol,
        kind,
        [
            {
                "symbol": symbol,
                "timestamp": MS,
                field: "1.25",
                "longAccount": "0.5",
                "shortAccount": "0.5",
            }
        ],
        NOW,
    )
    assert rows[0].value == "1.25" and rows[0].metadata["raw_ratio_field"] == field
    assert rows[0].series_id == f"BINANCE_{kind.upper()}_{symbol}"


def test_yahoo_naver_daily():
    a = normalize_yahoo(
        "VIX", symbol="^VIX", close=20.1, stamp=NOW - timedelta(seconds=11), received=NOW
    )
    assert quality_at(a, catalog()["VIX"], NOW) == Quality.STALE
    b = normalize_yahoo("VIX", symbol="^VIX", close=float("nan"), stamp=None, received=NOW)
    assert b.value is None and b.quality == Quality.NO_DATA
    n = normalize_naver(
        {
            "result": [
                {
                    "reutersCode": "US2YT=RR",
                    "closePrice": "4.6490",
                    "localTradedAt": "2026-11-20T17:05:00-05:00",
                }
            ]
        },
        NOW,
    )
    assert n.value == "4.649"
    xml = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><NEW_DATE>2026-11-25T00:00:00</NEW_DATE>
    <BC_3MONTH>3.9</BC_3MONTH><BC_2YEAR>4.6</BC_2YEAR><BC_5YEAR>4.2</BC_5YEAR>
    <BC_10YEAR>4.4</BC_10YEAR><BC_30YEAR>4.8</BC_30YEAR></entry></feed>"""
    daily = normalize_treasury(xml, NOW)
    assert len(daily) == 5 and all(x.source_event_at is None for x in daily)
    t = next(x for x in daily if x.series_id == "UST_2Y_TREASURY")
    assert change_pct(n, t) is None
    with pytest.raises(ValueError):
        normalize_treasury(b"<!DOCTYPE x><x/>", NOW)


def test_manual_csv():
    row = [
        "CNN_FEAR_GREED",
        "SENTIMENT",
        "https://edition.cnn.com/markets/fear-and-greed",
        "",
        NOW.isoformat(),
        "snapshot",
        "65",
        "index",
        "greed",
        "",
        "",
        "",
        "",
        "fixture-operator",
        "",
        "unverified",
    ]
    import csv
    from io import StringIO

    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(HEADERS)
    writer.writerow(row)
    item = manual_candidates(buffer.getvalue())[0]
    assert item.value == "65" and item.source_event_at is None
    assert item.quality == Quality.MANUAL_UNVERIFIED
    with pytest.raises(ValueError):
        manual_candidates(buffer.getvalue().replace("unverified", "checked"))


@pytest.mark.asyncio
async def test_bounded_retry_and_forbidden():
    delays = []
    calls = 0

    async def wait(delay):
        delays.append(delay)

    async def transient():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise FetchError(429, "12")
        return "ok"

    assert await bounded_fetch(transient, lambda: None, wait) == "ok"
    assert delays[0] >= 12

    async def forbidden():
        raise FetchError(403)

    with pytest.raises(FetchError):
        await bounded_fetch(forbidden, lambda: None, wait)
    assert len(delays) == 1
    assert retry_after(0, "Fri, 27 Nov 2026 00:00:00 GMT", NOW) > 0


@pytest.mark.asyncio
async def test_gap_recovery():
    tracker = GapTracker()

    def candidate(key):
        return Candidate("BITCOIN_BINANCE_SPOT", str(key), "1", NOW, NOW, NOW)

    assert tracker.observe(candidate(1)) is None
    assert tracker.observe(candidate(4)) == (2, 3)

    async def fetch(url, params):
        assert params["fromId"] == 2
        return [{"id": i, "price": "1", "qty": "1", "time": MS} for i in [2, 3]]

    rows = await recover_gap(
        "BTCUSDT", 2, 3, spot=True, allowed=lambda: None, fetch=fetch, clock=lambda: NOW
    )
    assert [int(x.key) for x in rows] == [2, 3]
    assert change_pct(candidate(1), candidate(2)) is None


@pytest.mark.asyncio
async def test_transport_blocked_and_mock_only():
    calls = []

    def mock(request):
        calls.append(request)
        assert request.url.host == "fapi.binance.com"
        return httpx.Response(
            200, json=[{"symbol": "BTCUSDT", "timestamp": MS, "longShortRatio": "1.25"}]
        )

    transport = httpx.MockTransport(mock)
    blocked = ProviderTransport(lambda _: None, http_transport=transport)
    with pytest.raises(ValueError):
        await blocked.ratios("BTCUSDT", "global_accounts")
    assert not calls
    auth = []
    enabled = ProviderTransport(auth.append, network_opt_in=True, http_transport=transport)
    rows = await enabled.ratios("BTCUSDT", "global_accounts")
    assert rows[0].value == "1.25" and len(calls) == 1 and len(auth) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 403, 429])
async def test_transport_error_no_retry_and_final_permission_check(status):
    calls = []
    auth = []

    def mock(request):
        calls.append(request)
        return httpx.Response(status, headers={"Location": "https://example.com"})

    tr = ProviderTransport(
        auth.append, network_opt_in=True, http_transport=httpx.MockTransport(mock)
    )
    with pytest.raises(FetchError) as exc:
        await tr.ratios("BTCUSDT", "global_accounts")
    assert exc.value.status == status and len(calls) == 1 and len(auth) == 2
    error = ValueError("redirect")
    assert _FixedConnect(FUTURES_WS).process_redirect(error) is error


def test_binance_future_timestamp_fails_closed():
    # A live probe observed a provider timestamp roughly 1 s ahead of receipt.
    # Do not shift the machine clock, source timestamp or availability to admit it.
    msg = {
        "s": "BTCUSDT",
        "e": "trade",
        "t": 5,
        "p": "1",
        "q": "1",
        "T": int((NOW + timedelta(seconds=1)).timestamp() * 1000),
    }
    with pytest.raises(ValueError, match="future source event"):
        binance_trade(msg, NOW, spot=True)
