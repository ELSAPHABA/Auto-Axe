import pytest

from autoaxe_scraper.parsers import SchemaChanged, parse_offline
from autoaxe_scraper.policy import SOURCES, SourcePolicy

DRAM = """
<section><h2>DRAM Spot Price</h2><table><tr><th>Item</th><th>Session Average</th></tr>
<tr><td>DDR5 UDIMM 16GB 4800/5600</td><td>1</td></tr></table></section>
<section><h2>Module Spot Price</h2><p data-last-update="2026-11-23 15:00"></p>
<table><tr><th>Item</th><th>Weekly High</th><th>Session Average</th></tr>
<tr><td>DDR5 UDIMM 16GB 4800/5600</td><td>99</td><td>12.45</td></tr>
<tr><td>DDR5 RDIMM 32GB 4800/5600</td><td>100</td><td>22.50</td></tr></table></section>
"""


def test_dram_module_section_and_timezone() -> None:
    data = parse_offline("dramexchange", DRAM)
    assert [row["value"] for row in data] == ["22.50", "12.45"]
    assert all(row["source_event_at"] == "2026-11-23T07:00:00+00:00" for row in data)
    assert all(row["unit_verified"] is False for row in data)
    with pytest.raises(SchemaChanged):
        parse_offline("dramexchange", DRAM.replace("22.50", ""))
    with pytest.raises(SchemaChanged):
        parse_offline("dramexchange", DRAM.replace("Session Average", "Spot Average"))


def test_sentiment_is_never_an_automatic_trade_signal() -> None:
    cnn = parse_offline(
        "cnn", '<div data-source="cnn-fear-greed" data-score="65" data-category="Greed"></div>'
    )
    assert cnn["value"] == "65" and cnn["automated_trading_allowed"] is False
    pizza = parse_offline(
        "pizzint", '<div data-source="pizzint-status" data-status="elevated"></div>'
    )
    assert pizza["status"] == "elevated" and pizza["automated_trading_allowed"] is False
    with pytest.raises(SchemaChanged):
        parse_offline("cnn", '<div data-source="cnn-fear-greed" data-score="102"></div>')


def test_naver_yield_and_source_time() -> None:
    item = parse_offline(
        "naver",
        '<span data-symbol="US2YT=RR" data-yield="4.650" '
        'data-time="2026-11-23T16:00:00+09:00"></span>',
    )
    assert item["source_event_at"] == "2026-11-23T07:00:00+00:00"
    with pytest.raises(SchemaChanged):
        parse_offline("naver", '<span data-symbol="US2YT=RR" data-yield="4.6"></span>')


def test_seibro_rank_and_scope() -> None:
    html = (
        '<table data-source="seibro-top50"><tbody><tr><td>1</td><td>미국</td>'
        "<td>US67066G1040</td><td>Synthetic</td><td>100</td><td>50</td>"
        "<td>150</td><td>50</td></tr></tbody></table>"
    )
    rows = parse_offline("seibro", html, {"country": "US", "period": "1", "basis": "4"})
    assert rows[0]["top50_coverage"] and rows[0]["currency"] == "USD"
    with pytest.raises(ValueError):
        parse_offline("seibro", html, {"country": "ZZ", "period": "1", "basis": "4"})


def test_fixed_policy_no_arbitrary_http_or_ip() -> None:
    assert all(item.url.startswith("https://") for item in SOURCES.values())
    with pytest.raises(KeyError):
        parse_offline("https://127.0.0.1/", "<p>bad</p>")
    with pytest.raises(ValueError):
        SourcePolicy("bad", "http://127.0.0.1/secret")
    with pytest.raises(ValueError):
        SourcePolicy("bad", "https://127.0.0.1/secret")
    with pytest.raises(ValueError):
        SourcePolicy("bad", "https://169.254.169.254/latest/meta-data")
