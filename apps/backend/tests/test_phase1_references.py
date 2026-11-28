from datetime import UTC, datetime, timedelta

import pytest

from autoaxe.adapters.providers import normalize_yahoo
from autoaxe.adapters.references import normalize_reference
from autoaxe.application.poll_adapters import PollAdapters
from autoaxe.domain.catalog import FUTURES, RATIOS, catalog
from autoaxe.domain.market import Quality

NOW = datetime(2026, 11, 26, 12, tzinfo=UTC)
MS = int((NOW - timedelta(seconds=1)).timestamp() * 1000)


@pytest.mark.parametrize("symbol", list(FUTURES))
def test_snapshot_separate_from_trade(symbol):
    row = normalize_reference(
        "binance-futures", {"symbol": symbol, "price": "123.45", "time": MS}, NOW
    )[0]
    assert row.series_id == FUTURES[symbol][0] + "_SNAPSHOT"
    assert catalog()[row.series_id].interval == "snapshot"
    assert row.value == "123.45"


def test_reference_sources():
    gold = normalize_reference("gold-spot-reference", {"price": 123.45}, NOW)[0]
    assert gold.series_id == "GOLD_SPOT_REFERENCE" and gold.quality == Quality.UNKNOWN
    for sym, sid in (("PET.RWTC.D", "WTI_EIA_DAILY"), ("PET.RBRTE.D", "BRENT_EIA_DAILY")):
        oil = normalize_reference(
            "eia",
            {"response": {"data": [{"period": "2026-11-25", "value": "70.25"}]}},
            NOW,
            symbol=sym,
        )[0]
        assert oil.series_id == sid and oil.source_event_at is None
    vix = normalize_reference("vix-eod", {"DATE": "11/25/2026", "CLOSE": "20.1"}, NOW)[0]
    assert vix.series_id == "VIX_CBOE_EOD" and vix.source_event_at is None
    btc = normalize_reference(
        "coinbase",
        {
            "type": "ticker",
            "product_id": "BTC-USD",
            "time": NOW.isoformat(),
            "trade_id": 1,
            "price": "100",
            "best_bid": "99",
            "best_ask": "101",
        },
        NOW,
    )[0]
    assert btc.series_id == "BITCOIN_COINBASE_USD"
    bar = {
        "e": "kline",
        "s": "BTCUSDT",
        "k": {
            "i": "1m",
            "T": MS,
            "c": "100",
            "o": "99",
            "h": "101",
            "l": "98",
            "v": "20",
            "x": False,
        },
    }
    assert normalize_reference("binance-kline", bar, NOW) == []
    bar["k"]["x"] = True
    assert normalize_reference("binance-kline", bar, NOW)[0].metadata["bar_closed"]
    with pytest.raises(ValueError):
        normalize_reference("gold", {"symbol": "XAGUSDT", "price": "10"}, NOW)
    with pytest.raises(ValueError):
        normalize_reference("eia", {}, NOW, symbol="DUBAI")


def test_poll_dispatch():
    calls = []
    xml = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><NEW_DATE>2026-11-25</NEW_DATE><BC_2YEAR>4.5</BC_2YEAR></entry></feed>'
    adapter = PollAdapters(
        authorize=calls.append,
        ratio=lambda s, k: [{"symbol": s, "timestamp": MS, RATIOS[k][1]: "1.25"}],
        yahoo=lambda sid: normalize_yahoo(sid, symbol="^VIX", close="20", stamp=NOW, received=NOW),
        treasury=lambda: xml,
        clock=lambda: NOW,
    )
    for sid in ("BINANCE_GLOBAL_ACCOUNTS_BTCUSDT", "VIX", "UST_2Y_TREASURY"):
        assert adapter.collect(sid)[0].series_id == sid
        assert calls[-2:] == [sid, sid]
