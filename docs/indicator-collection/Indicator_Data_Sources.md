# Auto-Axe 수집 지표별 기본 소스 — 2026-11-23

| 지표 | 기본 공급원 | 갱신 / 주의 |
|---|---|---|
| 금 가격 동향 | Binance Futures `XAUUSDT` | 금 연동 영구선물 라이브 틱. 금 현물/COMEX 선물 아님 |
| 은 가격 동향 | Binance Futures `XAGUSDT` | 실시간 금속 연동 영구선물, 현물/COMEX 선물 아님 |
| 구리 가격 동향 | Binance Futures `COPPERUSDT` | 실시간 금속 연동 영구선물, 현물/COMEX 선물 아님 |
| WTI 가격 동향 | Binance Futures `CLUSDT` | 원유 연동 영구선물 라이브 틱. NYMEX 선물 아님 |
| Brent 가격 동향 | Binance Futures `BZUSDT` | 원유 연동 영구선물 라이브 틱. ICE/NYMEX 선물 아님 |
| 비트코인 | Binance Spot `BTCUSDT` | Spot 실시간 체결, USD가 아닌 USDT 호가 |
| VIX | yfinance `^VIX` | Cboe 원지수 후보, 지연 가능. `UVXYUSDT`는 대체 불가 |
| 미국 국채 3개월 | yfinance `^IRX` | 13-week Bill 지표, 지연 가능 |
| 미국 국채 2년 | Naver `US2YT=RR` **승인 후에만 수집** | [원본 페이지](https://m.stock.naver.com/marketindex/bond/US2YT=RR). `robots.txt` 차단으로 현재 기본은 Treasury `BC_2YEAR` 공식 일별 |
| 미국 국채 5년 | yfinance `^FVX` | 지연 가능 |
| 미국 국채 10년 | yfinance `^TNX` | 지연 가능 |
| 미국 국채 30년 | yfinance `^TYX` | 지연 가능 |
| CNN 공포·탐욕 | [CNN](https://edition.cnn.com/markets/fear-and-greed) | 자동 스크래핑 허가 전 수동 |
| 펜타곤 피자지수 | [PizzINT](https://www.pizzint.watch/) | 수집 권한 확인 전 수동 |
| 기업 가이던스 | SEC EDGAR/기업 IR | 원문과 추출 수치 구분 |
| 미국 경제지표 일정·실제값 | BLS·BEA·Census 공개 자료 | 발표와 수정 이력 구분 |
| 파생 만기 캘린더 | OCC·CME·Binance Options (각 상품별) | 거래소/계약마다 다름 |
| 중앙은행 금리 (Fed·BoJ·BoE·ECB) | 각 중앙은행 공식 발표/공개 시계열 | 실시간 시장 금리와 다름 |

**두바이유는 수집 대상에 포함하지 않는다.** 시장가격은 Binance 공개 시세, VIX·3M/5Y/10Y/30Y 수익률은 yfinance, 2Y는 네이버 원본 허가 시 스크래핑 / 무허가 동안 Treasury 공식 데이터가 기준이다.

[최신 소스 정책](./Market_Source_Policy_20261123.md) · [수집기](../examples/realtime_collector.py).

## 구리·은 및 Binance 롱숏 비율 추가 (2026-11-23)

- **구리:** Binance Futures `COPPERUSDT`, 내부 `COPPER_BINANCE_PERP`; **은:** `XAGUSDT`, 내부 `SILVER_BINANCE_PERP`. 두 종목 모두 실측 `TRADING / TRADIFI_PERPETUAL`, REST 1분봉 지원. 기존 Binance Futures `@aggTrade` 실시간 스트림의 구독 목록에 추가했다. USDT 표시 영구선물은 원자재 현물 또는 거래소 만기선물과 다르다.
- **공식 롱숏 비율 4종:** 전체 계정, 상위 계정, 상위 포지션, Taker 매수·매도 거래량 비율. Binance `/futures/data/*` 무료 공개 REST의 **최소 5분 집계**로 수집한다. 실시간 WS 틱이 아니며, Taker 매수·매도 비율은 포지션 롱숏 비율과 다르다.
- `python docs/examples/realtime_collector.py binance-live`: BTC Spot + 금·은·구리·WTI·Brent 5개 영구선물.
- `python docs/examples/realtime_collector.py binance-longshort --ratio-period 5m --interval 300`: 6개 Binance 선물 심볼의 롱숏·Taker 통계 5분 간격 조회.
- [상세 응답 검증과 API 구분](./Binance_Metals_LongShort_20261123.md) · [Python 수집기](../examples/realtime_collector.py).
