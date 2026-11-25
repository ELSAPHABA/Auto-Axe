# Binance 무료 공개 API — Auto-Axe 지표 커버리지 검증

> 2026-11-23(KST) 실측. Binance 공식 현물 `https://data-api.binance.vision/api/v3/exchangeInfo`, USDⓈ-M 선물 `https://fapi.binance.com/fapi/v1/exchangeInfo`, 옵션 `https://eapi.binance.com/eapi/v1/exchangeInfo`를 **인증 없이 HTTP 200** 수신해 실제 심볼·거래상태를 검증했다. 별도 무료 종목 1분봉은 Spot `/api/v3/klines`, 선물 `/fapi/v1/klines`에서 검증. Binance 사용·자동 저장 및 지역 제한은 별도 준수한다.

## 0. 수집 범위

**두바이유는 Auto-Axe 수집 대상에서 전면 제외한다.** 원유 수집 대상은 WTI 및 Brent만 남긴다. 관련 월간 데이터 조회·수동 입력·대체상품도 활성화하지 않는다.

## 1. 대상 분야 커버리지

실측 당시 조사한 16개 분야와 은·구리의 직접/간접 대응을 구분한다. 이는 전체 플랫폼의 최종 지표 수가 아니다.

- **원자산/가까운 가격 계열 수집 가능 6분야**: 비트코인(Spot 직거래), 금(금 연계 Spot 및 금 TradFi 영구선물), 은·구리·WTI·Brent(TradFi 영구선물). **금·유가 선물은 원래의 금 현물 및 NYMEX 선물가격과 동일 상품 아님.**
- **관련 파생상품만 있는 2분야**: VIX 관련 `UVXYUSDT`(UVXY ETF 연계), 미국 국채 관련 `TMFUSDT`, `TBTUSDT`(20년 초과 국채 레버리지·인버스 ETF 연계). **VIX `^VIX` 지수 및 3M/2Y/5Y/10Y/30Y 수익률 데이터의 직접 대체 불가**.
- **부분적으로 지원 1분야**: Binance 자체 암호화폐/귀금속 옵션 **만기일·행사가·미결제약정**을 `eapi`로 조회. 미국 상장주식/지수 옵션의 OCC 만기·CME 원유/금 선물 만기 목록을 대신하지는 못한다.
- **해당 수치 직접 제공 미확인 9분야**: CNN 공포·탐욕, PizzINT 피자지수, 기업 실적 forward guidance, 경제지표 예정 일정, 실제 경제지표 발표값, 미국 Fed 기준금리, 일본 BoJ 기준금리, 영국 BoE 기준금리, 유로존 ECB 정책금리.

**정리:** 6개 가격 분야에 직접 또는 연동 계약이 있으며 VIX·국채는 관련 ETF 파생상품만, 옵션 만기는 Binance 자체 상품 범위에 한한다. 원 지표 지원 개수로 단순 합산하지 않는다.

## 2. 직접 시장 조회 항목

| Auto-Axe 분야 | Spot Binance | USDⓈ-M Futures | 확인된 상태 (2026-11-23) | Auto-Axe 원래 시리즈와의 차이 |
|---|---|---|---|---|
| 비트코인 | `BTCUSDT`, `BTCUSDC` | `BTCUSDT` | **TRADING** / 최근 1분봉 확인 | Binance Spot BTC/USDT는 yfinance `BTC-USD`의 USD 집계가 아니라 **USDT 가격** |
| 금 | `PAXGUSDT`, `XAUTUSDT` (금 연계 토큰) | `XAUUSDT` TradFi 영구선물 | **TRADING** / 최근 1분봉 확인 | 금 토큰·영구선물은 Gold API XAU 현물가 및 COMEX `GC=F`와 다른 자산·계약 |
| 은 | 직접 은 현물 없음 | `XAGUSDT` TradFi 영구선물 | **TRADING** / REST 1분봉 확인 | 은 연동 선물, 현물/COMEX와 다름 |
| 구리 | 직접 구리 현물 없음 | `COPPERUSDT` TradFi 영구선물 | **TRADING** / REST 1분봉 확인 | 구리 연동 선물, 현물/COMEX와 다름 |
| WTI | 직접 Spot 없음 | `CLUSDT` TradFi 영구선물 | **TRADING** / 최근 1분봉 확인 | Binance 영구선물은 EIA WTI 현물·NYMEX `CL=F` 선물이 아님 |
| Brent | 직접 Spot 없음 | `BZUSDT` TradFi 영구선물 | **TRADING** / 최근 1분봉 확인 | Binance 영구선물은 EIA Brent 현물·NYMEX `BZ=F` 선물이 아님 |

Binance 공지: `CLUSDT`, `BZUSDT`는 2026-04-01에 출시된 **USDT 결제 영구선물**, 1단위 원유 배럴 가상 기초자산. [바이낸스 원유 상품 공지](https://www.binance.com/en/support/announcement/detail/e7a10ca855524655ab3dea73add40ef4). `XAUUSDT`는 2026-01-05 출시 [금 TradFi 영구선물](https://www.binance.com/en/support/announcement/detail/ecf7318c0d434c339e80878588e700d0). 귀금속·원유 TradFi 계약 거래시간/가격지수 산식은 **2026-09-15** 변경되어, 출시 시점의 24/7 설명을 그대로 적용하면 안 된다. [거래시간 개정](https://www.binance.com/en-BH/support/announcement/detail/f69c05ebdba7422e9c614685abe84dc5).

## 3. 관련 ETF 파생상품만 지원

| 관심 지표 | Binance Futures 실제 확인 | 무엇을 추적하는가 | 판정 |
|---|---|---|---|
| Cboe VIX `^VIX` | `UVXYUSDT` **TRADING** | ProShares Ultra VIX Short-Term Futures ETF 연동 영구선물; 원 VIX 수준이 아니며 일일 레버리지·롤 영향을 받음 | **원 VIX 미지원, 간접 프록시만** |
| 미국 국채 3M·2Y·5Y·10Y·30Y 수익률 | `TMFUSDT`, `TBTUSDT` **TRADING** | 미국 장기국채 **20+년 ETF**의 레버리지·인버스 방향성에 대한 영구선물 | **다섯 만기 수익률 원본 모두 미지원** |

[UVXY 연계상품 설명](https://www.binance.com/en/academy/articles/leveraged-etfs-you-can-trade-on-binance-futures), [TMF/TBT 출시 공지](https://www.binance.com/en/support/announcement/detail/a827177a387e4ebea830110ba222ca48). VIX와 금리만기 수익률은 기존 **yfinance/Treasury** 수집을 유지한다.

## 4. Binance 자체 옵션 만기 지원 (범위 제한)

- [Options API](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-options/api/rest-api/market-data): `GET https://eapi.binance.com/eapi/v1/exchangeInfo`.
- `optionSymbols[].symbol`, `underlying`, `expiryDate`(Unix ms UTC), `strikePrice`, `side`, `status` 추출.
- **실측**: 조회 시 총 **1,840개 옵션 계약**, `TRADING` 1,840개. 기초자산별: BTC 740, ETH 634, BNB 208, SOL 84, XAU 52, DOGE 44, XAG 42, XRP 36.
- **주의:** Binance 옵션 만기만 나타낸다. 미국 주식·Cboe 옵션의 OCC 만기 또는 CME/ICE 원자재 선물 만기 캘린더를 대체할 수 없다. 해당 공시 달력은 원래의 무료 공식 수집기를 유지한다.

## 5. 2026-11-23 실제 요청 결과

| API | HTTP | 등록 심볼/계약 수 | 주의 |
|---|---:|---:|---|
| Spot `/api/v3/exchangeInfo` | 200 | 3,751 | **등록 전체**이며 모두 `TRADING` 상태라는 뜻 아님 |
| USDⓈ-M `/fapi/v1/exchangeInfo` | 200 | 956 | **등록 전체**; 계약별 `status` 검사 필수 |
| Options `/eapi/v1/exchangeInfo` | 200 | 1,840 | 실조회 기준 전부 `TRADING` |

REST 최신 두 개의 1분봉 `limit=2` 또한 **선물 `BTCUSDT`, `XAUUSDT`, `CLUSDT`, `BZUSDT`, `TMFUSDT`, `TBTUSDT`**, 현물 `BTCUSDT`, `PAXGUSDT`, `XAUTUSDT`에서 모두 HTTP 200·2행을 확인했다. `UVXYUSDT`는 선물 ExchangeInfo `TRADING` 확인(봉 별도 시험 미수행).

## 6. 운영 권장 API / 예제

무료·공개 시장데이터 **API 키 불필요**. Spot은 `data-api.binance.vision`이 공식 공개 데이터용 호스트다. 거래는 하지 않으며 시세/만기만 조회한다.

```bash
# 거래 가능 심볼 및 계약 구조
curl 'https://data-api.binance.vision/api/v3/exchangeInfo'
curl 'https://fapi.binance.com/fapi/v1/exchangeInfo'
curl 'https://eapi.binance.com/eapi/v1/exchangeInfo'

# Spot BTC 1분봉, 금 연계 토큰 1분봉
curl 'https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=2'
curl 'https://data-api.binance.vision/api/v3/klines?symbol=PAXGUSDT&interval=1m&limit=2'

# 금·WTI·Brent 영구선물 1분봉
curl 'https://fapi.binance.com/fapi/v1/klines?symbol=XAUUSDT&interval=1m&limit=2'
curl 'https://fapi.binance.com/fapi/v1/klines?symbol=CLUSDT&interval=1m&limit=2'
curl 'https://fapi.binance.com/fapi/v1/klines?symbol=BZUSDT&interval=1m&limit=2'
```

실제 수집 전 `exchangeInfo`의 `TRADING`·거래 세션 및 거주지역 상품 제공 여부를 확인. Binance USDⓈ-M Futures는 2026-04-23 이후 **반드시** `/market/stream` 또는 `/market/ws` 라우팅을 사용한다 ([공식 2026년 WS 변경 안내](https://developers.binance.me/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/Important-WebSocket-Change-Notice)). Binance USDⓈ-M Futures는 [REST·WebSocket 공개 API](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/Introduction)를 지원하며, Spot 공개 market-data 사용법은 [Binance 공식 개발자 문서](https://developers.binance.com/en/docs/products/spot/rest-api). WebSocket 예: `wss://fstream.binance.com/market/stream?streams=btcusdt@aggTrade/xauusdt@kline_1m/clusdt@kline_1m/bzusdt@kline_1m` — **공식 스트림 문법을 기반으로 한 예시이며 본 조사에서 장시간 WS 실제 이벤트 수신은 별도 시험하지 않았다**.

Binance Spot BTC/USDT 및 금·은·구리·WTI·Brent 연동 영구선물 체결 스트림은 기본 시장가격 공급원이다. VIX·국채 3M/5Y/10Y/30Y는 yfinance, 2Y는 네이버 최우선(실패/실행 불가 시에만 Treasury 임시 일별 fallback). [시장 데이터 소스 정책](./Market_Source_Policy_20261123.md).

무료 실증 재실행: `python docs/examples/binance_coverage_probe.py`. 수집기·시장지표 구별: [YFinance_First_Collection.md](./YFinance_First_Collection.md).

## 7. 거래 통계

Binance 공식 롱숏 4종(전체 계정, 상위 계정, 상위 포지션, Taker 매수·매도 거래량 비율)은 BTCUSDT 선물 및 금·은·구리·WTI·Brent 연동 선물의 `/futures/data/*` 공개 REST 최소 5분 집계로 수집한다. BTC 가격은 Spot, 비율은 Futures로 별도 표기한다. Taker 거래량 비율은 포지션 비율이 아니며 WS 실시간 틱으로 표시하지 않는다. [API·실측 및 실행 명세](./Binance_Metals_LongShort_20261123.md).
