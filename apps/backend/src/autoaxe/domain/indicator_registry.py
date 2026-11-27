"""Phase 2 logical indicator catalog. Registration is not data-source permission."""

from dataclasses import dataclass

from autoaxe.domain.catalog import catalog


@dataclass(frozen=True)
class IndicatorDefinition:
    id: str
    label: str
    category: str
    source_id: str
    unit: str
    cadence: str
    note: str = ""


STATIC = (
    IndicatorDefinition(
        "NASDAQ100_MEXC_PERP_USDT",
        "MEXC Nasdaq 연동 영구선물 (REST)",
        "market",
        "mexc",
        "USDT/contract",
        "5m",
        "CME NQ와 다름; 5분 REST 조회, 거래세션·실시간성 미검증; WS 비활성",
    ),
    IndicatorDefinition(
        "NASDAQ100_BINANCE_QQQ_PERP_USDT",
        "Binance QQQ ETF 연동 영구선물 (REST)",
        "market",
        "binance_futures",
        "USDT/QQQ",
        "5m",
        "QQQ ETF 연동, NQ·NDX·MEXC와 다름; 거래세션·실시간성 미검증",
    ),
    IndicatorDefinition(
        "NASDAQ100_CME_NQ_YAHOO_DELAYED",
        "CME NQ 비교 (지연)",
        "market",
        "yfinance",
        "USD/index_point",
        "1m",
        "CME delayed",
    ),
    IndicatorDefinition(
        "US_STOCK_DAILY_CUM_VOLUME_1S_NVDA",
        "NVDA 누적 거래량",
        "equities",
        "yfinance",
        "shares",
        "local_1hz",
        "Yahoo 틱 1Hz 보장 아님",
    ),
    IndicatorDefinition(
        "US_STOCK_DAILY_CUM_VOLUME_1S_QLD",
        "QLD 누적 거래량",
        "equities",
        "yfinance",
        "shares",
        "local_1hz",
        "ETF",
    ),
    IndicatorDefinition(
        "NVDA_FUNDAMENTALS",
        "NVDA 재무비율",
        "equities",
        "yfinance",
        "mixed",
        "daily",
        "TTM/forward/ROE 원본 구분",
    ),
    IndicatorDefinition(
        "QLD_FUNDAMENTALS",
        "QLD 재무비율",
        "equities",
        "yfinance",
        "mixed",
        "daily",
        "ETF 기업비율 기본 null",
    ),
    IndicatorDefinition(
        "NVDA_DAILY_OHLCV",
        "NVDA 일봉·기술지표",
        "equities",
        "yfinance",
        "USD",
        "1d",
        "조정 과거봉, 거래소 세션 및 PIT 검증 별도",
    ),
    IndicatorDefinition(
        "QLD_DAILY_OHLCV",
        "QLD 일봉·기술지표",
        "equities",
        "yfinance",
        "USD",
        "1d",
        "조정 과거봉, 거래소 세션 및 PIT 검증 별도",
    ),
    IndicatorDefinition("US_CPI", "미국 CPI", "macro", "bls", "index", "release"),
    IndicatorDefinition(
        "US_NONFARM_PAYROLL", "미국 비농업 고용", "macro", "bls", "thousand", "release"
    ),
    IndicatorDefinition("US_UNEMPLOYMENT", "미국 실업률", "macro", "bls", "percent", "release"),
    IndicatorDefinition("US_PCE", "미국 PCE", "macro", "bea", "percent", "release"),
    IndicatorDefinition("US_GDP", "미국 GDP", "macro", "bea", "percent", "release"),
    IndicatorDefinition(
        "US_RETAIL_SALES", "미국 소매판매", "macro", "census", "percent", "release"
    ),
    IndicatorDefinition(
        "US_FED_TARGET_RANGE",
        "Fed 목표금리 범위",
        "rates",
        "fed",
        "percent",
        "decision",
        "상·하한 별도",
    ),
    IndicatorDefinition(
        "BOJ_POLICY_TARGET",
        "BOJ 정책 목표금리",
        "rates",
        "boj",
        "percent",
        "decision",
        "실효금리와 구분",
    ),
    IndicatorDefinition("BOE_BANK_RATE", "BoE Bank Rate", "rates", "boe", "percent", "decision"),
    IndicatorDefinition(
        "BOJ_EFFECTIVE_CALL_RATE",
        "BOJ 무담보 익일물 실효금리",
        "rates",
        "boj",
        "percent_per_annum",
        "1d",
        "공식 일별 평균 실효금리; 정책 목표와 별개",
    ),
    IndicatorDefinition("ECB_DFR", "ECB 예금금리", "rates", "ecb", "percent", "decision"),
    IndicatorDefinition(
        "US_ECONOMIC_CALENDAR",
        "경제지표 일정·실제값",
        "calendar",
        "official_calendar",
        "event",
        "release",
        "수정·발표 시각 분리",
    ),
    IndicatorDefinition(
        "US_CORPORATE_GUIDANCE",
        "기업 공시·가이던스",
        "calendar",
        "sec_edgar",
        "reported",
        "release",
        "GAAP/조정 검수",
    ),
    IndicatorDefinition(
        "US_OPTIONS_EXPIRATION", "OCC 옵션 만기", "calendar", "occ", "session", "schedule"
    ),
    IndicatorDefinition(
        "CME_INDEX_EXPIRATION", "CME 지수 선물 만기", "calendar", "cme", "session", "schedule"
    ),
    IndicatorDefinition(
        "US_SINGLE_STOCK_FUTURE_EXPIRATION",
        "개별주식 선물 만기",
        "calendar",
        "cme",
        "session",
        "schedule",
    ),
    IndicatorDefinition(
        "US_WITCHING",
        "트리플·쿼드러플 위칭",
        "calendar",
        "official_calendar",
        "classification",
        "schedule",
        "4 family evidence",
    ),
    IndicatorDefinition(
        "CNN_FEAR_GREED_CNN",
        "CNN Fear & Greed",
        "sentiment",
        "cnn",
        "index",
        "unknown",
        "CNN 지정 URL, 권한 미확인",
    ),
    IndicatorDefinition(
        "PENTAGON_PIZZA_PIZZINT",
        "DOUGHCON",
        "sentiment",
        "pizzint",
        "level",
        "5m",
        "PizzINT 공개 API 단계(1~5); 자동 주문 신호 금지",
    ),
    IndicatorDefinition(
        "SEIBRO_TOP50_USD",
        "SEIBro 해외주식 TOP50 결제",
        "industry",
        "seibro",
        "USD",
        "period",
        "전체 시장·개인 주문 아님",
    ),
    IndicatorDefinition(
        "DRAM_DDR5_UDIMM_AUTO",
        "DDR5 UDIMM 16GB 4800/5600",
        "industry",
        "dramexchange",
        "unverified",
        "weekly",
        "Session Average; 원본 단위 검수 전 수집값 반영 금지",
    ),
    IndicatorDefinition(
        "DRAM_DDR5_RDIMM_AUTO",
        "DDR5 RDIMM 32GB 4800/5600",
        "industry",
        "dramexchange",
        "unverified",
        "weekly",
        "Session Average; 원본 단위 검수 전 수집값 반영 금지",
    ),
)


def all_indicators() -> list[IndicatorDefinition]:
    records = {item.id: item for item in STATIC}
    for series in catalog().values():
        if series.id not in records:
            records[series.id] = IndicatorDefinition(
                series.id,
                series.id.replace("_", " "),
                "market" if series.source_id not in {"manual:" + series.id} else "manual",
                series.source_id,
                series.unit,
                series.interval,
                "등록만 완료; 권한 확인 전 외부 자동수집 비활성",
            )
    return sorted(records.values(), key=lambda item: (item.category, item.id))
