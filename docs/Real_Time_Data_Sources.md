# Auto-Axe 실시간·준실시간 무료 가격 데이터

> 2026-11-23 업데이트. **Binance 실시간 거래소 WebSocket을 가격 수집 우선 소스로 전환**했다. 단, 거래소 실시간 시세가 다른 거래소 원자산의 시세라는 뜻은 아니며 상품별 세션·지연을 따로 기록한다.

| 항목 | 기본 스트림 | 데이터 정의 |
|---|---|---|
| 금 연동 가격 | `wss://fstream.binance.com/stream?streams=xauusdt@aggTrade` | Binance `XAUUSDT` TradFi 영구선물 체결 |
| WTI 연동 가격 | `wss://fstream.binance.com/stream?streams=clusdt@aggTrade` | Binance `CLUSDT` 영구선물 체결 |
| Brent 연동 가격 | `wss://fstream.binance.com/stream?streams=bzusdt@aggTrade` | Binance `BZUSDT` 영구선물 체결 |
| 비트코인 | `wss://data-stream.binance.vision/stream?streams=btcusdt@trade` | Binance Spot BTC/USDT 체결 |
| VIX 원지수 | yfinance `^VIX` | 지연 가능한 최신 봉, **미검증 WebSocket 사용 안 함** |
| 미국 국채 3M/5Y/10Y/30Y | yfinance `^IRX/^FVX/^TNX/^TYX` | 지연 가능한 금리지표 |
| 미국 국채 2Y | [Naver `US2YT=RR`](https://m.stock.naver.com/marketindex/bond/US2YT=RR) | 값·갱신 시각 확인. `robots.txt: Disallow /`이므로 **허가 전 자동 스크래핑 금지**. 공식 Treasury XML 일별값 fallback |

확인된 네이버 원본 백엔드 JSON은 `https://m.stock.naver.com/front-api/marketIndex/bondList?countryCode=USA`에 `reutersCode=US2YT=RR`, `closePrice`, `localTradedAt`, `priceDataType`, `delayTime`, `marketStatus` 필드가 있다. **인터페이스가 공개되어 있다고 수집 권한이 있는 것은 아니다.** 강제로 접근 제한을 우회하지 않는다.

금 현물 추정 참고는 Gold API 별도 `gold-spot-reference` 명령. VIX 공식 일별 Cboe CSV, Treasury 5개 만기 공식 일별 XML, EIA 유가 현물 일별 데이터는 개별 원본 검증·장기 백테스트용이다.

실행:
```bash
python docs/examples/realtime_collector.py binance-live
python docs/examples/realtime_collector.py yf-market --symbols VIX UST_3M UST_5Y UST_10Y UST_30Y
python docs/examples/realtime_collector.py treasury-five
```

[최신 상세 설계](./Market_Source_Policy_20261123.md) · [Binance 검증](./Binance_API_Coverage.md).
