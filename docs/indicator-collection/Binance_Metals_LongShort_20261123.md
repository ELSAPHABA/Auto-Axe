# Binance 구리·은 및 롱숏 지표 수집 및 검증

> 실측일: 2026-11-23. REST 검증과 실제 장시간 WS 수신 검증은 구분한다.

## 금속 가격 지표

Binance USDⓈ-M Futures 공식 `GET /fapi/v1/exchangeInfo`의 실제 응답에서 다음 두 계약은 `TRADING`, `TRADIFI_PERPETUAL`, `USDT` 호가이다. `/fapi/v1/ticker/price` 및 `/fapi/v1/klines?interval=1m&limit=2` 요청도 HTTP 200에 정상 가격/캔들 반환.

| 지표 | Binance 심볼 | Auto-Axe series | 기본 수집 | 정의 |
|---|---|---|---|---|
| 구리 가격 동향 | `COPPERUSDT` | `COPPER_BINANCE_PERP` | Binance Futures `@aggTrade` 실시간 WS | 구리 **연동 USDT 결제 영구선물**; LME/COMEX 현물 또는 선물 원계약 아님 |
| 은 가격 동향 | `XAGUSDT` | `SILVER_BINANCE_PERP` | Binance Futures `@aggTrade` 실시간 WS | 은 **연동 USDT 결제 영구선물**; 은 현물 또는 COMEX 원계약 아님 |

기존 금 `XAUUSDT`, WTI `CLUSDT`, Brent `BZUSDT`와 함께 `wss://fstream.binance.com/market/stream?streams=...`에 구독한다. 이 주소는 2026년 Binance USDⓈ-M 선물 WebSocket 라우팅 변경 후의 경로이다. 실제 틱은 거래소 계약에 새 거래가 발생할 때마다 발행되며 무지연 기준시장 가격 보장은 아니다.

## Binance 롱숏 비율 API

**실시간 틱/WS로 게시되는 '공식 포지션·계정 롱숏 비율'은 확인되지 않음.** Binance Futures는 다음 **최소 5분 간격 REST 통계**를 제공한다. 공식 지원 period는 `5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d`이다. 실험에서 `period=1m` 요청 시 HTTP 200 빈 배열 반환; 따라서 지원 주기로 간주하지 않는다.

| 종류 | Endpoint (`https://fapi.binance.com`) | 응답 필드·정의 |
|---|---|---|
| 전체 거래자 계정 Long/Short | `/futures/data/globalLongShortAccountRatio` | `longAccount`, `shortAccount`, `longShortRatio`, `timestamp` — 계정 수의 비율, 포지션 규모 아님 |
| 상위 트레이더 계정 Long/Short | `/futures/data/topLongShortAccountRatio` | `longAccount`, `shortAccount`, `longShortRatio`, `timestamp` |
| 상위 트레이더 포지션 Long/Short | `/futures/data/topLongShortPositionRatio` | `longShortRatio`, `timestamp` 및 공급자 원문 필드; 계정 비율과 구분 |
| Taker Buy/Sell 거래량 비율 | `/futures/data/takerlongshortRatio` | `buyVol`, `sellVol`, `buySellRatio`, `timestamp` — **거래 공격성 비율이지 실제 오픈 롱숏 포지션 비율 아님** |

실제 Binance REST 요청에서 **BTCUSDT, XAUUSDT, XAGUSDT, COPPERUSDT, CLUSDT** 모두 각 네 가지 API가 HTTP 200에 `limit=2`의 데이터 두 행을 반환했다. 샘플 시간 및 값은 실행 시 달라지므로 보관 시 `timestamp`를 사용한다.

실시간 대안으로 Binance의 `@aggTrade` 스트림에서 체결 방향을 `m`(buyer is maker) 등을 활용해 거래자 주도 매수·매도 압력을 **자체 계산**할 수는 있다. 그러나 이는 **공식 롱숏 계정/포지션 비율과 다르며** 어느 거래자가 실제 롱 포지션을 유지하는지는 알 수 없다. PoC는 공식 5분 통계를 제공한다.

공개 market-data 접근은 지역·상품·이용조건과 호출 한도에 따라 다르다. 새 시계열 데이터는 `provider`, `symbol`, `kind`, `ratio_definition`, `period`, `source_event_at`, `received_at`, `raw_response_fields`를 기록한다. 5분 주기 자료를 1분마다 요청할 수 있더라도 동일 `timestamp`의 중복 레코드를 쌓지 않는다.

## 실행

```bash
python -m pip install -r docs/examples/requirements.txt

# 5개 금속/원유 연동 선물: 금 XAU, 은 XAG, 구리 COPPER, WTI CL, Brent BZ + BTC Spot
python docs/examples/realtime_collector.py binance-live

# 모든 5개 선물 최근 체결 가격 REST
python docs/examples/realtime_collector.py binance-futures

# 전체 심볼 (BTC, 금/은/구리/WTI/Brent) 롱숏 4종의 최신 5분 데이터
python docs/examples/realtime_collector.py binance-longshort --ratio-period 5m

# BTC+은+구리만, 전체 계정 및 상위 포지션 비율
python docs/examples/realtime_collector.py binance-longshort --ratio-symbols BTCUSDT XAGUSDT COPPERUSDT --ratio-types global_accounts top_positions

# 운영에서 충분한 주기로 반복 폴링 (1회 예시 주기 300초)
python docs/examples/realtime_collector.py binance-longshort --interval 300
```

## 출처

- [Binance USDⓈ-M Futures 시장 데이터](https://developers.binance.com/en/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information)
- [Global Long/Short Account Ratio](https://developers.binance.com/en/docs/derivatives/usds-margined-futures/market-data/rest-api/Long-Short-Ratio)
- [Top Trader Long/Short Account Ratio](https://developers.binance.com/en/docs/derivatives/usds-margined-futures/market-data/rest-api/Top-Trader-Long-Short-Ratio)
- [Top Trader Long/Short Position Ratio](https://developers.binance.com/en/docs/derivatives/usds-margined-futures/market-data/rest-api/Top-Trader-Long-Short-Ratio)
- [Taker Buy/Sell Volume](https://developers.binance.com/en/docs/derivatives/usds-margined-futures/market-data/rest-api/Taker-BuySell-Volume)
- [기존 시장 데이터 수집 정책](./Market_Source_Policy_20261123.md) · [Binance 지원범위](./Binance_API_Coverage.md)
