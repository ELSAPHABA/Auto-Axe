# Auto-Axe 무료 지표 데이터 소스 요약

> 최신 수집 정책: **yfinance가 지원하는 시장가격·수익률 지표는 yfinance 우선**. 미지원/비해당 자료는 기관 무료 API·RSS·ICS·CSV → 허용된 스크래핑 → 수동 입력. 유료 피드 제외. 정확한 근거는 [YFinance_First_Collection.md](./YFinance_First_Collection.md).

## 국채 — 고정 5종

| 만기 | Auto-Axe 식별자 | 기본 소스 |
|---|---|---|
| 3개월 | `UST_3M` | yfinance `^IRX` |
| 2년 | `UST_2Y` | US Treasury 무료 XML `BC_2YEAR` |
| 5년 | `UST_5Y` | yfinance `^FVX` |
| 10년 | `UST_10Y` | yfinance `^TNX` |
| 30년 | `UST_30Y` | yfinance `^TYX` |

참고: `2YY=F`와 `ZT=F`는 2년물 **선물**로 현물 파 수익률에 대응하지 않는다. Treasury XML에서는 5개 만기의 공식 일별 수익률을 모두 별도로 교차검증할 수 있다.

## 나머지 요청 지표

| 지표 | 우선 무료 소스 | 비고 |
|---|---|---|
| VIX | **yfinance `^VIX`** | 무지연 미보증; Cboe CSV는 일별 확인용 |
| WTI | **yfinance `CL=F`** | NYMEX 원유선물; EIA 일별 WTI 현물과 별개 |
| Brent | **yfinance `BZ=F`** | NYMEX Brent Financial 선물; EIA 현물과 별개 |
| 금 선물 | **yfinance `GC=F`** | COMEX 금선물; 금 현물가격은 Gold API 유지 |
| 비트코인 | **yfinance `BTC-USD`** | Coinbase/Binance 공개 WS는 개별 거래소 체결값 보조 |
| Dubai 현물 | World Bank 공개 월별 자료 | 동일한 Dubai spot 일별 yfinance ticker 미확인 |
| CNN 공탐 | [edition.cnn.com](https://edition.cnn.com/markets/fear-and-greed) | 허가 전 자동 스크래핑 불가 → 수동 |
| PizzINT 피자 | [pizzint.watch](https://www.pizzint.watch/) | JSON 존재, robots·약관 권한 확인 전 수동 |
| 기업 가이던스 | SEC EDGAR·기업 공식 IR RSS | 이벤트 원본 |
| 경제지표·발표일정 | BLS·BEA·FOMC·Census | 원기관 공식 |
| 파생상품 만기 | OCC/OIC·CME 공식 일정 | 계약별 최종 거래/처리일 별개 |
| 미국·일본·영국·유로존 정책금리 | Fed·BOJ·BoE·ECB 공식 발표/API | 시장 금리지표로 정책금리 대체 금지 |

**yfinance는 공식 데이터 라이선스의 대체가 아니다.** 무료·지연·개인연구 조건과 `source_event_at`, `received_at`을 기록한다.

더 자세한 문서: [무료 전체 카탈로그](./Free_Data_Collection.md) · [시장 데이터 기본 설계](./YFinance_First_Collection.md) · [실행 명령](./Realtime_Quickstart.md).
