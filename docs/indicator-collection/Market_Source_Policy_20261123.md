# Auto-Axe 시장 데이터 소스 정책

## 1. 적용 범위

시장가격은 Binance 공개 체결 스트림을 기본으로 한다. VIX 및 국채 3M/5Y/10Y/30Y와 미국 주식·ETF의 지정 지표는 yfinance를 사용한다. 네이버 증권 `US2YT=RR`을 최우선 원본(`UST_2Y_NAVER`)으로 지정한다. 스크래핑 실패 또는 권한·접근 제한으로 실행할 수 없는 경우에만 미국 재무부 `BC_2YEAR` 일별값(`UST_2Y_TREASURY`)을 임시 fallback으로 표시한다. 네이버 정상 수집 복구 즉시 우선 원본으로 복귀하고 전환 사유·시각·원본을 기록한다. 자동화·저장·활용 권한 확인 전에는 네이버 요청을 실행하지 않으며 접근 제한을 우회하지 않는다. 원본별 데이터 정의·시각·신선도를 분리하고 일별 fallback을 장중 실시간 수익률로 사용하지 않는다.

## 2. 대상별 기본 데이터 소스

| 지표 | 기본 공급원 | 내부 식별자 | 정확한 상품 정의 |
|---|---|---|---|
| 금 가격 동향 | **Binance Futures WS** `XAUUSDT@aggTrade` | `GOLD_BINANCE_PERP` | Binance TradFi 금 연동 영구선물 **USDT 기준** |
| 은 가격 동향 | **Binance Futures WS** `XAGUSDT@aggTrade` | `SILVER_BINANCE_PERP` | 은 연동 USDT 영구선물 |
| 구리 가격 동향 | **Binance Futures WS** `COPPERUSDT@aggTrade` | `COPPER_BINANCE_PERP` | 구리 연동 USDT 영구선물 |
| WTI 가격 동향 | **Binance Futures WS** `CLUSDT@aggTrade` | `WTI_BINANCE_PERP` | Binance 원유 연동 영구선물 **USDT 기준** |
| Brent 가격 동향 | **Binance Futures WS** `BZUSDT@aggTrade` | `BRENT_BINANCE_PERP` | Binance Brent 연동 영구선물 **USDT 기준** |
| 비트코인 | **Binance Spot WS** `BTCUSDT@trade` | `BITCOIN_BINANCE_SPOT` | Binance BTC/USDT 현물 **USDT 기준** |
| 미국 개별주식 PER·PBR·ROE | **yfinance `Ticker.info` 후행/예상 PER·PBR·ROE 스냅샷** | `EQUITY_PER_TTM`, `EQUITY_PER_FORWARD`, `EQUITY_PBR`, `EQUITY_ROE` | 일별/실적 갱신시점 분리, ETF 결측 기본. [명세](./YFinance_Valuation_and_Moving_Averages.md) |
| 이동평균선(SMA·EMA) | **yfinance OHLCV로 로컬 산출** | `SMA_N`, `EMA_N` + interval | 확정 일봉/분봉 기준, 조정종가·워밍업 및 백테스트 시점 보존. [명세](./YFinance_Valuation_and_Moving_Averages.md) |
| 최근 5·10·20거래일 최고·최저가 | **yfinance `High`·`Low` 일봉 → rolling 최댓값·최솟값 로컬 계산** | `HIGH_5D/10D/20D`, `LOW_5D/10D/20D` | 실제 거래 세션 N개 기준. 일봉 확정 후 당일 포함, 장중 비교는 직전 N개 확정봉 기준. [명세](./YFinance_Valuation_and_Moving_Averages.md) |
| 미국 주식·ETF 초단위 누적 거래량 (NVDA·QLD 등) | **yfinance WebSocket `day_volume` + 로컬 1초 주기 스냅샷** | `US_STOCK_DAILY_CUM_VOLUME_1S` + symbol | 원본 WS 이벤트 주기는 불규칙, 새 값 없으면 `stale/no_update`로 직전 값 표시; 진정한 무지연 초봉 또는 SIP 통합 체결량 아님. [명세](./YFinance_1s_Stock_Cumulative_Volume.md) |
| 나스닥 100 선물·연동 신호 | **MEXC `NAS100_USDT` 무료 Futures WebSocket(개발/검증 후보)**; Binance `QQQUSDT` 별도 보조, yfinance `NQ=F` 지연 CME 기준 | `NASDAQ100_MEXC_PERP_USDT` / 별도 2시리즈 | MEXC는 지수 연동 영구선물, Binance는 QQQ ETF 연동 계약, Yahoo는 CME 실제 NQ 지연 시세. WS 수신 미검증; [조사 문서](./Nasdaq100_Futures_Data_Sources.md) |
| VIX | yfinance `^VIX` | `VIX` | Cboe VIX 지수, 원본 기준 TTL 10초; 지연 가능 |
| 미국 국채 3개월 | yfinance `^IRX` | `UST_3M` | Yahoo 13주물 금리지표 |
| 미국 국채 2년 | **네이버 증권 `US2YT=RR` 최우선; 실패/실행 불가 시에만 Treasury `BC_2YEAR` 임시 일별 fallback** | `UST_2Y` (논리); `UST_2Y_NAVER` / `UST_2Y_TREASURY` (원본) | 네이버 게시 수익률 및 Treasury 공식 par yield를 별도 유지 |
| 미국 국채 5년 | yfinance `^FVX` | `UST_5Y` | Yahoo 5년물 금리지표 |
| 미국 국채 10년 | yfinance `^TNX` | `UST_10Y` | Yahoo 10년물 금리지표 |
| 미국 국채 30년 | yfinance `^TYX` | `UST_30Y` | Yahoo 30년물 금리지표 |

- Binance **실시간**은 **해당 Binance 계약/현물 시장의 최신 거래 이벤트**라는 뜻이다. 현물 금(XAU/USD)이나 CME 금·원유 선물 자체의 틱을 대체할 수 없다. 스트림 연결 성공 ≠ 지연 0 검증.
- Binance 원유·금 TradFi 계약은 거래시간·휴장·유동성 제한이 있을 수 있다. 이벤트 수신이 없을 때는 최신 시각만으로 시장이 열렸다고 간주하지 않는다.
- Binance `USDT` 호가를 `USD` 호가나 USD 현물 벤치마크로 환산 없이 합치지 않는다.
- 기존 현물 원본값이 필요한 경우 **Gold API 현물 참고값**(별도 `gold-spot-reference`), **EIA WTI/Brent 일별 현물**, **Treasury 공식 5개 만기 일별**, **Cboe VIX EOD**를 원본 시계열로 *분리*한다.
- **두바이유는 수집 대상에서 제외**되어 있다.

## 3. 국채 2년물 수집 및 검증 근거

네이버 증권 `US2YT=RR`을 최우선 원본(`UST_2Y_NAVER`)으로 지정한다. 스크래핑 실패 또는 권한·접근 제한으로 실행할 수 없는 경우에만 미국 재무부 `BC_2YEAR` 일별값(`UST_2Y_TREASURY`)을 임시 fallback으로 표시한다. 네이버 정상 수집 복구 즉시 우선 원본으로 복귀하고 전환 사유·시각·원본을 기록한다. 자동화·저장·활용 권한 확인 전에는 네이버 요청을 실행하지 않으며 접근 제한을 우회하지 않는다. 원본별 데이터 정의·시각·신선도를 분리하고 일별 fallback을 장중 실시간 수익률로 사용하지 않는다.

전환 후 일별 Treasury 값은 별도 원본과 freshness를 유지한다. 실거래 Workflow는 원본 고정 기본이며 명시적 fallback 허용 및 품질 검증 없이는 UNKNOWN. [공통 시계열 계약](../tech-stack/data-storage.md) · [신선도](../tech-stack/data-collection.md).

원본 페이지: [m.stock.naver.com/marketindex/bond/US2YT=RR](https://m.stock.naver.com/marketindex/bond/US2YT=RR).

2026-11-23 HTTP 실증:
- 원본 HTML: HTTP 200.
- 실제 화면 데이터 공급 엔드포인트: `GET https://m.stock.naver.com/front-api/marketIndex/bondList?countryCode=USA` → HTTP 200 JSON.
- 해당 레코드 선택: `result[].reutersCode == "US2YT=RR"`.
- 주요 필드: `closePrice`(수익률 숫자 문자열), `localTradedAt`(타임존 포함 관측시각), `priceDataType`, `delayTime`, `marketStatus`, `name`.
- 실측 응답 예시는 `closePrice="4.6490"`, `localTradedAt="2026-11-20T17:05:00-05:00"`, `priceDataType="REALTIME"`, `delayTime=0`이었다.

## 4. 수집 PoC 실행

```bash
python -m pip install -r docs/examples/requirements.txt
# Binance 시장에서 실제 틱이 발생하면 즉시 출력, 끊어지면 백오프 재연결
python docs/examples/realtime_collector.py binance-live
# Binance 선물 REST 마지막 가격 단발 조회
python docs/examples/realtime_collector.py binance-futures
# 금 연동 영구선물 단발 조회(기존 gold 명령 호환)
python docs/examples/realtime_collector.py gold
# 금 현물 참고 지표는 별도이며 기본 실시간 시세로 사용하지 않음
python docs/examples/realtime_collector.py gold-spot-reference
# Binance가 해당 원본을 제공하지 않는 지표만 yfinance
python docs/examples/realtime_collector.py yf-market
# 공식 2년물 일별 fallback/5개 만기 전체 검증
python docs/examples/realtime_collector.py treasury-five
```

`binance-live`는 Binance Spot `BTCUSDT@trade` 및 Futures `XAUUSDT/XAGUSDT/COPPERUSDT/CLUSDT/BZUSDT@aggTrade`를 **동시 처리**, WebSocket 재연결 및 트레이드 ID·거래량·타임스탬프 보존. 실운영에는 거래 시간 정책 확인, 누락 구간 REST 백필, 연결 상태 감지, 레이트 리밋 준수가 추가 필요하다.

## 5. 거래 통계

Binance 공식 롱숏 4종(전체 계정, 상위 계정, 상위 포지션, Taker 매수·매도 거래량 비율)은 BTCUSDT 선물 및 금·은·구리·WTI·Brent 연동 선물의 `/futures/data/*` 공개 REST 최소 5분 집계로 수집한다. BTC 가격은 Spot, 비율은 Futures로 별도 표기한다. Taker 거래량 비율은 포지션 비율이 아니며 WS 실시간 틱으로 표시하지 않는다. [API·실측 및 실행 명세](./Binance_Metals_LongShort_20261123.md).

```bash
python docs/examples/realtime_collector.py binance-longshort --ratio-period 5m --interval 300
```

## 6. 출처

- [Binance Spot market-data documentation](https://developers.binance.com/en/docs/products/spot/web-socket-streams)
- [Binance USDⓈ-M Futures market streams](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/Introduction)
- [Binance API 검증 및 관련 계약 차이](./Binance_API_Coverage.md)
- [네이버 원본 2년물](https://m.stock.naver.com/marketindex/bond/US2YT=RR)
- [U.S. Treasury 공식 일별 수익률 XML](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed)
