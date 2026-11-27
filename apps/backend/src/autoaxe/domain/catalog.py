"""Fixed source definitions from Market_Source_Policy_20261123; no implicit permission."""

from autoaxe.domain.market import Series

FUTURES = {
    "XAUUSDT": ("GOLD_BINANCE_PERP", "gold", "gold"),
    "XAGUSDT": ("SILVER_BINANCE_PERP", "silver", "silver"),
    "COPPERUSDT": ("COPPER_BINANCE_PERP", "copper", "copper"),
    "CLUSDT": ("WTI_BINANCE_PERP", "wti", "oil"),
    "BZUSDT": ("BRENT_BINANCE_PERP", "brent", "oil"),
}
RATIOS = {
    "global_accounts": ("globalLongShortAccountRatio", "longShortRatio"),
    "top_accounts": ("topLongShortAccountRatio", "longShortRatio"),
    "top_positions": ("topLongShortPositionRatio", "longShortRatio"),
    "taker_volume": ("takerlongshortRatio", "buySellRatio"),
}
YAHOO = {"VIX": "^VIX", "UST_3M": "^IRX", "UST_5Y": "^FVX", "UST_10Y": "^TNX", "UST_30Y": "^TYX"}
TREASURY = {
    "3M": "BC_3MONTH",
    "2Y": "BC_2YEAR",
    "5Y": "BC_5YEAR",
    "10Y": "BC_10YEAR",
    "30Y": "BC_30YEAR",
}
SOURCE_URLS = {
    "binance_spot": "https://developers.binance.com/en/docs/products/spot/web-socket-streams",
    "binance_futures": "https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/Introduction",
    "yfinance": "https://finance.yahoo.com/",
    "naver": "https://m.stock.naver.com/marketindex/bond/US2YT=RR",
    "treasury": "https://home.treasury.gov/treasury-daily-interest-rate-xml-feed",
    "gold_reference": "https://gold-api.com/docs",
    "eia": "https://www.eia.gov/opendata/",
    "cboe_eod": "https://www.cboe.com/tradable_products/vix/vix_historical_data",
    "coinbase": "https://docs.cdp.coinbase.com/exchange/websocket-feed/overview",
    "mexc": "https://www.mexc.com/futures/NAS100_USDT",
    "bls": "https://www.bls.gov/schedule/",
    "bea": "https://www.bea.gov/news/schedule",
    "census": "https://www.census.gov/economic-indicators/",
    "fed": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    "fred": "https://fred.stlouisfed.org/",
    "boj": "https://www.boj.or.jp/en/mopo/",
    "boe": "https://www.bankofengland.co.uk/boeapps/database/Bank-Rate.asp",
    "ecb": "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/key_ecb_interest_rates/",
    "sec_edgar": "https://www.sec.gov/edgar/search/",
    "occ": "https://www.optionseducation.org/referencelibrary/expiration-calendar",
    "cme": "https://www.cmegroup.com/tools-information/calendars/expiration-calendar.html",
    "cnn": "https://edition.cnn.com/markets/fear-and-greed",
    "pizzint": "https://www.pizzint.watch/terms",
    "dramexchange": "https://www.dramexchange.com/",
    "seibro": "https://seibro.or.kr/websquare/control.jsp",
    "fixture": "https://github.com/ELSAPHABA/Auto-Axe",
}
MANUAL = {
    "DRAM_DDR5_UDIMM_16GB_SESSION_AVG": "USD/module",
    "DRAM_DDR5_RDIMM_32GB_SESSION_AVG": "USD/module",
    "CNN_FEAR_GREED": "index",
    "SEIBRO_OVS_STOCK_TOP50_SETTLEMENT": "USD",
    "VIX_INTRADAY": "index_point",
    "UST_2Y_INTRADAY": "percent",
    "UST_10Y_INTRADAY": "percent",
    "WTI_FUTURES_INTRADAY": "USD/bbl",
    "BRENT_FUTURES_INTRADAY": "USD/bbl",
    "EARNINGS_CONSENSUS": "typed",
    "EARNINGS_GUIDANCE_EXCEPTION": "typed",
    "US_EQUITY_WITCHING_VERIFY": "typed",
    "EXPIRATION_EXCEPTION": "typed",
    "ECONOMIC_FORECAST": "typed",
}
MANUAL_URLS = {
    "DRAM_DDR5_UDIMM_16GB_SESSION_AVG": "https://www.dramexchange.com/",
    "DRAM_DDR5_RDIMM_32GB_SESSION_AVG": "https://www.dramexchange.com/",
    "CNN_FEAR_GREED": "https://edition.cnn.com/markets/fear-and-greed",
    "SEIBRO_OVS_STOCK_TOP50_SETTLEMENT": "https://seibro.or.kr/",
    "VIX_INTRADAY": "https://www.cboe.com/tradable_products/vix/",
    "UST_2Y_INTRADAY": "https://m.stock.naver.com/marketindex/bond/US2YT=RR",
}
for _sid in MANUAL:
    SOURCE_URLS["manual:" + _sid] = MANUAL_URLS.get(
        _sid,
        "https://github.com/ELSAPHABA/Auto-Axe/blob/main/docs/indicator-collection/Manual_Collection.md",
    )


def catalog() -> dict[str, Series]:
    rows = [
        Series(
            "NASDAQ100_MEXC_PERP_USDT",
            "NASDAQ100_MEXC_PERP_USDT",
            "mexc",
            "NAS100_USDT",
            "index_linked_perpetual",
            "USDT/contract",
            "USDT",
            "snapshot",
            None,
        ),
        Series(
            "BITCOIN_BINANCE_SPOT",
            "BITCOIN_BINANCE_SPOT",
            "binance_spot",
            "BTCUSDT",
            "spot_crypto",
            "USDT/BTC",
            "USDT",
            "trade",
            10,
        ),
    ]
    for sym, (sid, commodity, unit) in FUTURES.items():
        rows.append(
            Series(
                sid,
                sid,
                "binance_futures",
                sym,
                f"commodity_{commodity}_linked_perpetual",
                f"USDT/{unit}_contract_unit",
                "USDT",
                "trade",
                10,
            )
        )
        rows.append(
            Series(
                sid + "_SNAPSHOT",
                sid,
                "binance_futures",
                sym,
                f"commodity_{commodity}_linked_perpetual",
                f"USDT/{unit}_contract_unit",
                "USDT",
                "snapshot",
                10,
            )
        )
    for sym in ("BTCUSDT", *FUTURES):
        for kind in RATIOS:
            sid = f"BINANCE_{kind.upper()}_{sym}"
            rows.append(
                Series(
                    sid, sid, "binance_futures", sym, "futures_ratio", "ratio", "USDT", "5m", 600
                )
            )
    for sid, sym in YAHOO.items():
        rows.append(
            Series(
                sid,
                sid,
                "yfinance",
                sym,
                "volatility_index" if sid == "VIX" else "treasury_yield_index",
                "index_point" if sid == "VIX" else "percent",
                None,
                "1m",
                10 if sid == "VIX" else 300,
            )
        )
    rows.append(
        Series(
            "UST_2Y_NAVER",
            "UST_2Y",
            "naver",
            "US2YT=RR",
            "us_two_year_treasury_yield",
            "percent",
            None,
            "snapshot",
            300,
        )
    )
    for tenor, sym in TREASURY.items():
        sid = "UST_2Y_TREASURY" if tenor == "2Y" else f"UST_{tenor}_PAR_YIELD"
        rows.append(
            Series(
                sid,
                "UST_2Y" if tenor == "2Y" else sid,
                "treasury",
                sym,
                "official_daily_par_yield",
                "percent",
                None,
                "1d",
                None,
                2,
            )
        )
    for sid, unit in MANUAL.items():
        rows.append(
            Series(sid, sid, "manual:" + sid, sid, "manual_observation", unit, None, "manual", None)
        )
    rows.append(
        Series(
            "PENTAGON_PIZZA_PIZZINT",
            "PENTAGON_PIZZA_PIZZINT",
            "pizzint",
            "DOUGHCON",
            "sentiment_level",
            "level",
            None,
            "5m",
            None,
        )
    )
    rows.extend(
        [
            Series(
                "GOLD_SPOT_REFERENCE",
                "GOLD_SPOT_REFERENCE",
                "gold_reference",
                "XAUUSD",
                "third_party_spot_estimate",
                "USD/troy_oz",
                "USD",
                "snapshot",
                None,
            ),
            Series(
                "WTI_EIA_DAILY",
                "WTI_EIA_DAILY",
                "eia",
                "PET.RWTC.D",
                "official_daily_spot",
                "USD/bbl",
                "USD",
                "1d",
                None,
            ),
            Series(
                "BRENT_EIA_DAILY",
                "BRENT_EIA_DAILY",
                "eia",
                "PET.RBRTE.D",
                "official_daily_spot",
                "USD/bbl",
                "USD",
                "1d",
                None,
            ),
            Series(
                "VIX_CBOE_EOD",
                "VIX_CBOE_EOD",
                "cboe_eod",
                "VIX",
                "volatility_index_eod",
                "index_point",
                None,
                "1d",
                None,
            ),
            Series(
                "BITCOIN_COINBASE_USD",
                "BITCOIN_COINBASE_USD",
                "coinbase",
                "BTC-USD",
                "spot_crypto",
                "USD/BTC",
                "USD",
                "trade",
                10,
            ),
            Series(
                "BTCUSDT_BINANCE_SPOT_1M_CLOSE",
                "BTCUSDT_BINANCE_SPOT_1M_CLOSE",
                "binance_spot",
                "BTCUSDT",
                "spot_crypto",
                "USDT/BTC",
                "USDT",
                "1m",
                None,
            ),
        ]
    )
    for symbol, kind in (("NVDA", "us_equity"), ("QLD", "us_etf")):
        volume = f"US_STOCK_DAILY_CUM_VOLUME_1S_{symbol}"
        fundamentals = f"{symbol}_FUNDAMENTALS"
        bars = f"{symbol}_DAILY_OHLCV"
        rows.extend(
            [
                Series(volume, volume, "yfinance", symbol, kind, "shares", "USD", "local_1hz", 5),
                Series(
                    fundamentals,
                    fundamentals,
                    "yfinance",
                    symbol,
                    kind,
                    "mixed",
                    "USD",
                    "daily",
                    None,
                ),
                Series(bars, bars, "yfinance", symbol, kind, "USD", "USD", "1d", None),
            ]
        )
    rows.extend(
        [
            Series(
                "CNN_FEAR_GREED_CNN",
                "CNN_FEAR_GREED_CNN",
                "cnn",
                "FEAR_GREED",
                "sentiment_index",
                "index",
                None,
                "snapshot",
                None,
            ),
            Series(
                "DRAM_DDR5_UDIMM_AUTO",
                "DRAM_DDR5_UDIMM_AUTO",
                "dramexchange",
                "DDR5 UDIMM 16GB 4800/5600",
                "module_spot_session_average",
                "unverified",
                None,
                "weekly",
                None,
            ),
            Series(
                "DRAM_DDR5_RDIMM_AUTO",
                "DRAM_DDR5_RDIMM_AUTO",
                "dramexchange",
                "DDR5 RDIMM 32GB 4800/5600",
                "module_spot_session_average",
                "unverified",
                None,
                "weekly",
                None,
            ),
        ]
    )
    rows.append(
        Series(
            "FIXTURE_PRICE",
            "FIXTURE_PRICE",
            "fixture",
            "FIXTURE",
            "synthetic",
            "USD",
            "USD",
            "trade",
            10,
        )
    )
    return {r.id: r for r in rows}
