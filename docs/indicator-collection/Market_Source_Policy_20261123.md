# Auto-Axe 최신 데이터 소스 정책 (2026-11-23)

## 1. 변경 범위

2026-11-23 사용자 요청에 따라 yfinance의 **지연 가능 가격 시세** 수집을 Binance의 공개 체결 스트림으로 전환한다. 미국 국채 2년물의 목표 출처는 사용자가 지정한 [네이버 증권 2년물 `US2YT=RR`](https://m.stock.naver.com/marketindex/bond/US2YT=RR)이다.

## 2. 대상별 기본 데이터 소스

| 지표 | 기존 기본 | 새 기본 | 새 내부 식별자 | 정확한 상품 정의 |
|---|---|---|---|---|
| 금 가격 동향 | yfinance `GC=F` (금 선물), Gold API 현물 추정 | **Binance Futures WS** `XAUUSDT@aggTrade` | `GOLD_BINANCE_PERP` | Binance TradFi 금 연동 영구선물 **USDT 기준** |
| 은 가격 동향 | 해당 지표 미수집 | **Binance Futures WS** `XAGUSDT@aggTrade` | `SILVER_BINANCE_PERP` | 은 연동 USDT 영구선물 |
| 구리 가격 동향 | 해당 지표 미수집 | **Binance Futures WS** `COPPERUSDT@aggTrade` | `COPPER_BINANCE_PERP` | 구리 연동 USDT 영구선물 |
| WTI 가격 동향 | yfinance `CL=F` | **Binance Futures WS** `CLUSDT@aggTrade` | `WTI_BINANCE_PERP` | Binance 원유 연동 영구선물 **USDT 기준** |
| Brent 가격 동향 | yfinance `BZ=F` | **Binance Futures WS** `BZUSDT@aggTrade` | `BRENT_BINANCE_PERP` | Binance Brent 연동 영구선물 **USDT 기준** |
| 비트코인 | yfinance `BTC-USD` | **Binance Spot WS** `BTCUSDT@trade` | `BITCOIN_BINANCE_SPOT` | Binance BTC/USDT 현물 **USDT 기준** |
| VIX | yfinance `^VIX` | yfinance `^VIX` 유지 | `VIX` | Cboe VIX 지수 (지연 가능) |
| 미국 국채 3개월 | yfinance `^IRX` | 변경 없음 | `UST_3M` | Yahoo 13주물 금리지표 |
| 미국 국채 2년 | Treasury `BC_2YEAR` | **네이버 증권 `US2YT=RR`** *(승인 시에만)* | `UST_2Y` | 네이버 게시 2년물 수익률(%) |
| 미국 국채 5년 | yfinance `^FVX` | 변경 없음 | `UST_5Y` | Yahoo 5년물 금리지표 |
| 미국 국채 10년 | yfinance `^TNX` | 변경 없음 | `UST_10Y` | Yahoo 10년물 금리지표 |
| 미국 국채 30년 | yfinance `^TYX` | 변경 없음 | `UST_30Y` | Yahoo 30년물 금리지표 |

- Binance **실시간**은 **해당 Binance 계약/현물 시장의 최신 거래 이벤트**라는 뜻이다. 현물 금(XAU/USD)이나 CME 금·원유 선물 자체의 틱을 대체할 수 없다. 스트림 연결 성공 ≠ 지연 0 검증.
- Binance 원유·금 TradFi 계약은 거래시간·휴장·유동성 제한이 있을 수 있다. 이벤트 수신이 없을 때는 최신 시각만으로 시장이 열렸다고 간주하지 않는다.
- Binance `USDT` 호가를 `USD` 호가나 USD 현물 벤치마크로 환산 없이 합치지 않는다.
- 기존 현물 원본값이 필요한 경우 **Gold API 현물 참고값**(별도 `gold-spot-reference`), **EIA WTI/Brent 일별 현물**, **Treasury 공식 5개 만기 일별**, **Cboe VIX EOD**를 원본 시계열로 *분리*한다.
- **두바이유는 수집 대상에서 제외**되어 있다.

## 3. 네이버 2년물 실증

원본 페이지: [m.stock.naver.com/marketindex/bond/US2YT=RR](https://m.stock.naver.com/marketindex/bond/US2YT=RR).

2026-11-23 HTTP 실증:
- 원본 HTML: HTTP 200.
- 실제 화면 데이터 공급 엔드포인트: `GET https://m.stock.naver.com/front-api/marketIndex/bondList?countryCode=USA` → HTTP 200 JSON.
- 해당 레코드 선택: `result[].reutersCode == "US2YT=RR"`.
- 주요 필드: `closePrice`(수익률 숫자 문자열), `localTradedAt`(타임존 포함 관측시각), `priceDataType`, `delayTime`, `marketStatus`, `name`.
- 실측 응답 예시는 `closePrice="4.6490"`, `localTradedAt="2026-11-20T17:05:00-05:00"`, `priceDataType="REALTIME"`, `delayTime=0`이었다.

## 4. 코드 구현

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

`binance-live`는 Binance Spot `BTCUSDT@trade` 및 Futures `XAUUSDT/CLUSDT/BZUSDT@aggTrade`를 **동시 처리**, WebSocket 재연결 및 트레이드 ID·거래량·타임스탬프 보존. 실운영에는 거래 시간 정책 확인, 누락 구간 REST 백필, 연결 상태 감지, 레이트 리밋 준수가 추가 필요하다.

## 5. 출처

- [Binance Spot market-data documentation](https://developers.binance.com/en/docs/products/spot/web-socket-streams)
- [Binance USDⓈ-M Futures market streams](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/Introduction)
- [Binance API 검증 및 관련 계약 차이](./Binance_API_Coverage.md)
- [네이버 원본 2년물](https://m.stock.naver.com/marketindex/bond/US2YT=RR)
- [U.S. Treasury 공식 일별 수익률 XML](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed)

## 구리·은 및 Binance 롱숏 비율 추가 (2026-11-23)

- **구리:** Binance Futures `COPPERUSDT`, 내부 `COPPER_BINANCE_PERP`; **은:** `XAGUSDT`, 내부 `SILVER_BINANCE_PERP`. 두 종목 모두 실측 `TRADING / TRADIFI_PERPETUAL`, REST 1분봉 지원. 기존 Binance Futures `@aggTrade` 실시간 스트림의 구독 목록에 추가했다. USDT 표시 영구선물은 원자재 현물 또는 거래소 만기선물과 다르다.
- **공식 롱숏 비율 4종:** 전체 계정, 상위 계정, 상위 포지션, Taker 매수·매도 거래량 비율. Binance `/futures/data/*` 무료 공개 REST의 **최소 5분 집계**로 수집한다. 실시간 WS 틱이 아니며, Taker 매수·매도 비율은 포지션 롱숏 비율과 다르다.
- `python docs/examples/realtime_collector.py binance-live`: BTC Spot + 금·은·구리·WTI·Brent 5개 영구선물.
- `python docs/examples/realtime_collector.py binance-longshort --ratio-period 5m --interval 300`: 6개 Binance 선물 심볼의 롱숏·Taker 통계 5분 간격 조회.
- [상세 응답 검증과 API 구분](./Binance_Metals_LongShort_20261123.md) · [Python 수집기](../examples/realtime_collector.py).
