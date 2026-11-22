# 실시간·준실시간 시장 데이터 — 무료 전용 조사

> 2026-11-22. **유료 소스, 데이터 구독, 거래소 사용료가 필요한 피드는 설계 범위에서 제외**. 구체 API 엔드포인트·정의·약관·수동 전환 조건은 [Free_Data_Collection.md](./Free_Data_Collection.md)에 통합.

## 실제 무료 스트리밍

- **BTC/USD Coinbase Exchange WebSocket**: `wss://ws-feed.exchange.coinbase.com` ; 구독 `{"type":"subscribe","product_ids":["BTC-USD"],"channels":["ticker","heartbeat"]}`. 무료 공개 거래 기반 ticker. [공식 문서](https://docs.cdp.coinbase.com/exchange/websocket-feed/overview).
- **BTC/USDT Binance Spot WebSocket**: `wss://data-stream.binance.vision/stream?streams=btcusdt@trade/btcusdt@kline_1m`; 체결과 **확정 시에만** 1분봉 기록. [공식 문서](https://developers.binance.com/en/docs/products/spot/web-socket-streams).
- **XAU/USD 금 현물 근사**: `GET https://api.gold-api.com/price/XAU`; 무료 REST 스냅샷이며 스트리밍 틱은 아니다. [공식 API](https://gold-api.com/docs).
- **기업 가이던스**: SEC 8-K 최신 Atom 및 제출 JSON+전용 기업 IR RSS를 짧은 간격으로 확인. [SEC API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces). 가이던스 원문에서 FY/Q/GAAP/EPS/매출을 별도로 추출해야 한다.
- **경제/정책 결정**: 공식 RSS(미국 Fed 정책 `https://www.federalreserve.gov/feeds/press_monetary.xml`, BOJ `https://www.boj.or.jp/en/rss/whatsnew.xml`, ECB `https://www.ecb.europa.eu/rss/press.html`), BLS ICS 및 BLS API. 이들은 **발표 이벤트**이지 밀리초 체결 데이터가 아니다.

## 실시간 데이터로 오인하면 안 되는 무료 출처

| 데이터 | 공개 소스 | 실제 공개 빈도 |
|---|---|---|
| WTI/Brent 현물 | EIA `PET.RWTC.D`/`PET.RBRTE.D` | 거래일 일별 |
| Dubai 가격 | World Bank Pink Sheet, IMF/FRED `POILDUBUSDM` | 월별 |
| Cboe VIX | 공식 `VIX_History.csv` | 거래일 종가/일별 OHLC |
| 미국 국채 시장 수익률 곡선 | Treasury XML/CSV | 거래일 일별 |
| 정책금리 | 중앙은행 성명과 공식 시계열 | 결정 이벤트/일별 |
| 만기 달력 | OCC/OIC·CME 공개 캘린더 | 사전 확정+예외 공지 |

무료 공식 실시간 피드가 없다고 해서 웹사이트에 표시된 숫자를 무단 스크래핑하지 않는다. **Cboe quotes dashboard·Google Maps Popular Times·TradingView의 무허가 데이터 자동추출을 설계에서 배제**한다. CNN 비공식 `production.dataviz.cnn.io` 엔드포인트는 실험 사례로만 기록하고 기본 수집기에는 포함하지 않는다. 공개 웹 차트의 `CL=F`, `BZ=F`, `^VIX`, `^TNX` 등은 **지연 및 이용권 미검증**이므로 실시간 API로 분류하지 않는다.

## 동적 대체값과 원 지표 분리

- WTI·Brent: 일별 현물과 장중 선물가격은 서로 다른 상품이다.
- Dubai vs Oman: 같은 가격지표가 아니다. 무료 Gulf Mercantile Exchange 일별 보고서가 있다 해도 `Dubai spot`으로 저장하지 않는다.
- 국채: Treasury 10Y 수익률과 선물가격은 직접 비교 불가.
- VIX: 지수와 VIX 선물·ETF는 별개.
- 피자지수 및 CNN: 정량 API와 이용권이 확보되지 않으면 수동 메모.

## 다음 문서

- [무료 데이터 전수 카탈로그](./Free_Data_Collection.md)
- [실행형 무료 수집 Quickstart](./Realtime_Quickstart.md)
- [수동 수집 절차](./Manual_Collection.md)
- [무료 수집 데이터베이스·재연결 설계](./Collector_Design.md)


## 지정 웹 출처·yfinance 갱신

- 피자지수 원본 **[pizzint.watch](https://www.pizzint.watch/)**: 사이트 공개 `/api/dashboard-data` JSON 확인; robots의 `Disallow: /api/` 및 Terms의 API 범위 외 스크래핑 금지 때문에 **권한 확인 전 수동**. 허용된 API 이용을 우선하고 비허용 HTML 직접 스크래핑은 하지 않음.
- 공탐지수 원본 **[edition.cnn.com](https://edition.cnn.com/markets/fear-and-greed)**: 페이지에 비공식 CNN 데이터 URL 표시 확인, 그러나 [CNN Terms](https://www.cnn.com/terms)가 자동 추출을 금지하여 **명시적 허가 전 수동**.
- **yfinance** `^VIX`/`^TNX`/`CL=F`/`BZ=F`: 무료 1분봉 응답 수신 성공, **실시간 체결/지연 없음은 검증되지 않음**. `CL=F`/`BZ=F` Yahoo Delayed Quote, Dubai 현물 일별 검증된 티커 없음. 자세한 실험결과 [YFinance_Data_Validation.md](./YFinance_Data_Validation.md).
