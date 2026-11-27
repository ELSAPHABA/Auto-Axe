import pytest

from autoaxe_scraper.seibro_capture import SOURCE_URL, normalize_display, require_browser


def sample():
    return {
        "capture_mode": "offline_fixture",
        "currency": "USD",
        "settlement_type": "2",
        "country_code": "US",
        "period_code": "1",
        "rank_basis": "4",
        "period_start": None,
        "period_end": None,
        "as_of_date_kst": "2026-11-20",
        "retrieved_at_utc": "2026-11-21T12:00:00Z",
        "rows": [
            {
                "RNUM": "1",
                "NATION_NM": "미국",
                "ISIN": "US67066G1040",
                "KOR_SECN_NM": "Synthetic",
                "SUM_FRSEC_BUY_AMT": "1,234.50",
                "SUM_FRSEC_SELL_AMT": "200.50",
                "SUM_FRSEC_TOT_AMT": "1,435.00",
                "SUM_FRSEC_NET_BUY_AMT": "1,034.00",
            }
        ],
    }


def test_explicit_visible_columns_without_live_dom():
    value = normalize_display(sample())
    assert value["source_url"] == SOURCE_URL and value["top50_coverage"] is True
    assert value["rows"][0]["buy_settlement_usd"] == "1234.5"
    assert value["rows"][0]["net_buy_settlement_usd"] == "1034"
    assert value["period_start"] is None and value["period_end"] is None
    assert value["capture_mode"] == "offline_fixture"


@pytest.mark.parametrize(
    "overrides",
    [
        {"settlement_type": "1"},
        {"currency": "KRW"},
        {"country_code": "ZZ"},
        {"rank_basis": "5"},
        {"url": "http://127.0.0.1"},
        {"capture_mode": "browser"},
    ],
)
def test_no_arbitrary_source_or_unverified_browser(overrides):
    with pytest.raises(ValueError):
        normalize_display(sample() | overrides)
    with pytest.raises(PermissionError):
        require_browser()


def test_missing_or_bad_amount_is_not_filled():
    value = sample()
    value["rows"][0]["SUM_FRSEC_BUY_AMT"] = "1,2"
    with pytest.raises(ValueError):
        normalize_display(value)
    del value["rows"][0]["SUM_FRSEC_BUY_AMT"]
    with pytest.raises(ValueError):
        normalize_display(value)
