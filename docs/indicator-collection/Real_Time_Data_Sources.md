# Auto-Axe 실시간·준실시간 무료 가격 데이터

> Binance 공개 WebSocket은 시장가격의 기본 공급원이다. 해당 계약의 실제 체결만 실시간으로 취급하고 세션·원본 시각·지연을 구분한다.

| 항목 | 기본 스트림 | 데이터 정의 |
|---|---|---|
| 미국 주식·ETF 누적 거래량 (NVDA·QLD 등) | yfinance `AsyncWebSocket` 수신 `day_volume` → 로컬 1Hz 스냅샷 | 1초마다 최근 누적값 또는 `stale/no_update` 기록; WS 원본 갱신 매초·무지연 보장 없음. [상세](./YFinance_1s_Stock_Cumulative_Volume.md) |
| 금 연동 가격 | `wss://fstream.binance.com/market/stream?streams=xauusdt@aggTrade` | Binance `XAUUSDT` TradFi 영구선물 체결 |
| 은 연동 가격 | `wss://fstream.binance.com/market/stream?streams=xagusdt@aggTrade` | Binance 은 연동 영구선물 체결 |
| 구리 연동 가격 | `wss://fstream.binance.com/market/stream?streams=copperusdt@aggTrade` | Binance 구리 연동 영구선물 체결 |
| WTI 연동 가격 | `wss://fstream.binance.com/market/stream?streams=clusdt@aggTrade` | Binance `CLUSDT` 영구선물 체결 |
| Brent 연동 가격 | `wss://fstream.binance.com/market/stream?streams=bzusdt@aggTrade` | Binance `BZUSDT` 영구선물 체결 |
| 비트코인 | `wss://data-stream.binance.vision/stream?streams=btcusdt@trade` | Binance Spot BTC/USDT 체결 |
| Binance 선물 롱숏 4종 | 공개 REST 최소 5분 집계 | 계정·포지션·Taker 거래량 지표, WS 틱 아님. [상세](./Binance_Metals_LongShort_20261123.md) |
| 나스닥 100 지수 연동 영구선물(후보) | MEXC Futures `NAS100_USDT` WebSocket (Protobuf 사양 확인 필요) | 무료 저지연 후보, 실시간 메시지 직접 검증 전. 실제 CME NQ와 별개 |
| 나스닥 100 관련 QQQ 연동 선물(보조) | Binance Futures `QQQUSDT` WebSocket (구독 동작 검증 전) | QQQ ETF 연동 영구선물; NQ·NDX 수준과 별개 |
| 실제 CME 나스닥 100 선물(지연) | yfinance `NQ=F` 1분봉 | Yahoo의 CME 지연 시세; 라이선스된 실시간 피드가 아님 |
| VIX 원지수 | yfinance `^VIX` | 원본 TTL 10초, 지연 가능 최신봉, 미검증 WS 미사용 |
| 미국 국채 3M/5Y/10Y/30Y | yfinance `^IRX/^FVX/^TNX/^TYX` | 지연 가능한 금리지표 |
| 미국 국채 2Y | [Naver `US2YT=RR`](https://m.stock.naver.com/marketindex/bond/US2YT=RR) 최우선 | 허가 전 자동화 금지; 실패/실행 불가 시에만 Treasury XML 임시 일별 fallback. 원본 분리·복구 시 복귀 |

확인된 네이버 원본 백엔드 JSON은 `https://m.stock.naver.com/front-api/marketIndex/bondList?countryCode=USA`에 `reutersCode=US2YT=RR`, `closePrice`, `localTradedAt`, `priceDataType`, `delayTime`, `marketStatus` 필드가 있다. **인터페이스가 공개되어 있다고 수집 권한이 있는 것은 아니다.** 강제로 접근 제한을 우회하지 않는다.

금 현물 추정 참고는 Gold API 별도 `gold-spot-reference` 명령. VIX 공식 일별 Cboe CSV, Treasury 5개 만기 공식 일별 XML, EIA 유가 현물 일별 데이터는 개별 원본 검증·장기 백테스트용이다.

실행:
```bash
python docs/examples/realtime_collector.py binance-live
python docs/examples/realtime_collector.py binance-longshort --ratio-period 5m --interval 300
python docs/examples/realtime_collector.py yf-market --symbols VIX UST_3M UST_5Y UST_10Y UST_30Y
python docs/examples/realtime_collector.py treasury-five
```

[시장 데이터 소스 정책](./Market_Source_Policy_20261123.md) · [Binance 검증](./Binance_API_Coverage.md).
