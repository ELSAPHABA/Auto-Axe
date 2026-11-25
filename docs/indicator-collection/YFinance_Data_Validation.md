# yfinance 무료 시장지표 지원 검증

> 검증 기준: 2026-11-22 (한국시간). 사용자 제공 [yfinance API Reference](https://ranaroussi.github.io/yfinance/reference/index.html) 및 개별 Yahoo Finance 종목 페이지를 대조했다. **Yahoo Finance 웹 가격의 실제 수신 여부와 무지연 실시간성은 개별 심볼·거래소·지역·장 상태마다 다르다.** 사용 전 개인용 연구/자동수집 권한을 [yfinance 법적 안내](https://ranaroussi.github.io/yfinance/)에서 확인한다.

## 결론 요약

| 목표 | 검증한 Yahoo 심볼 | 1분봉·일봉 조회 | yfinance WS API 사용 가능성 | **실제 지연 없는 실시간 지원** | 판정 |
|---|---|---|---|---|---|
| VIX 지수 | `^VIX` | 조회 가능한 Yahoo 심볼, API 응답·1분봉 여부 환경별 테스트 | WS API는 있지만 `^VIX` 이벤트 전달 보증 없음 | **검증되지 않음** | **준실시간 후보(지수), 공식 일별 Cboe와 교차검증** |
| 미국 10년 국채금리 지표 | `^TNX` | Yahoo CBOE 10Y 금리 지표 시계열 | WS가 해당 지표 구독을 지원하는지 별도 테스트 | **검증되지 않음** | **미 국채 Treasury par yield 공식 실시간 제공이 아님** |
| 미국 5년 국채금리 지표 | `^FVX` | Yahoo 5Y yield 지표 | 미보증 | 미보증 | 비교용/지연 가능 |
| 미국 단기국채 13주 지표 | `^IRX` | Yahoo 단기 T-bill 지표 | 미보증 | 미보증 | 비교용/지연 가능 |
| 미국 30년 국채금리 지표 | `^TYX` | Yahoo 30Y yield 지표 | 미보증 | 미보증 | 비교용/지연 가능 |
| WTI 원유 | `CL=F` | Yahoo에 상품 존재, 일중/일별 조회 시도 가능 | 심볼 구독 성패 시험 필요 | **아님: Yahoo에서 Delayed Quote 표시** | **NYMEX WTI 선물**, EIA WTI 현물과 다름 |
| Brent 원유 | `BZ=F` | Yahoo에 상품 존재, 일중/일별 조회 시도 가능 | 심볼 구독 성패 시험 필요 | **아님: Yahoo에서 Delayed Quote 표시** | **NYMEX Brent Last Day Financial Futures**, ICE 원유선물/현물과 다름 |

- Yahoo의 `^TNX`, `^FVX`, `^IRX`, `^TYX`는 **CBOE/시장 수익률 지표**이며 미국 재무부가 하루 한 번 발표하는 [Daily Treasury Par Yield Curve](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics)의 값이나 현물국채 실시간 체결 수익률을 직접 보장하지 않는다. **단위·스케일은 Yahoo 메타데이터와 Treasury 값으로 검증**하고 모든 때에 임의로 10을 곱하거나 나누지 않는다.
- `CL=F`의 원유 계약 월물은 시장이 롤오버할 때 바뀔 수 있다. `BZ=F`는 Yahoo에서 **NY Mercantile - Delayed Quote**, `Brent Crude Oil Last Day Financial Futures`라고 표시된다. ICE Brent 원계약과 혼용하지 않는다.

## 1. 공식 라이브러리가 실제 지원하는 기능

- [yfinance API Reference](https://ranaroussi.github.io/yfinance/reference/index.html): `yf.Ticker(...).history()`, `yf.download(...)`, `yf.WebSocket`, `yf.AsyncWebSocket`.
- [`yfinance.download` 명세](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html): `interval="1m"`, `2m`, `5m`, `15m`, `30m`, `60m`, `1h`, `1d` 등 분봉/일봉; 일반적으로 일중 시계열 조회 기간 **최대 60일**, 더 짧은 1분봉 제한이 있을 수 있다.
- [WebSocket 예제](https://ranaroussi.github.io/yfinance/reference/yfinance.websocket.html): 실시간 가격 업데이트를 `ws.subscribe([...])` / `ws.listen(callback)` 형태로 스트리밍하고 클라이언트에 `WebSocket`/ `AsyncWebSocket`이 존재한다. **공식 예제는 `AAPL`, `BTC-USD`; ^VIX/^TNX/CL=F/BZ=F에 대해 동일한 이벤트 스트림을 보장한다는 문서는 아니다.**
- [법적 제한](https://ranaroussi.github.io/yfinance/): yfinance는 Yahoo와 제휴·인증된 라이브러리가 아니며 Yahoo 공개 인터페이스를 사용하는 **개인 연구·교육용 도구**, Yahoo Finance 자료의 이용 권한·보관·재배포는 Yahoo 약관에 종속된다. 무료 패키지 설치 = 자동 저장/상용 API 권한이 아니다.

## 2. 실행 검증

Python 3.11 이상에서:

```bash
pip install yfinance
python docs/examples/yfinance_probe.py
```

스크립트는 각 심볼의 최근 1분봉(존재시)/일봉, 종목명·거래소·원본 시간·데이터 제공 지연 필드를 점검한다. **값이 최근 시각이라는 것만으로 실시간 무지연을 판정하지 않음**. 장 마감·휴장에는 1분봉이 끊기므로 WS 부정 결과로 결론 내리지 않는다.

**선택적 WS 수신 시험** (수신 이벤트가 없는 경우 타임아웃으로 종료):

```bash
python docs/examples/yfinance_probe.py --websocket --ws-seconds 45
```

사용 가능한 WebSocket 상품이라도 **거래소 delayed quote 상품은 여전히 delayed**다. 최신 yfinance 버전이 공개 API를 바꾸면 해당 버전 문서 기준 업데이트한다.

## 3. 공급원별 운영 역할 및 fallback

| 데이터 | 1차 무료 신뢰 소스 | yfinance 용도 | 운영 실패·권한 미확인 시 |
|---|---|---|---|
| VIX | yfinance `^VIX` 기본; [Cboe EOD CSV](https://www.cboe.com/tradable_products/vix/vix_historical_data) | 지연 가능 실험 조회·대조 (`^VIX`) | 장중 수동 |
| 미 국채 수익률 | yfinance 3M/5Y/10Y/30Y, 2Y 네이버 허가 후; [Treasury 일별](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed) | 장중 수익률 지표 관찰 (`^TNX` 등) | 장중 수동 |
| WTI·Brent | Binance 연동 영구선물 기본; [EIA 현물 일별](https://www.eia.gov/opendata/documentation.php) | 선물 동향 별도 관찰 (`CL=F`, `BZ=F`) | 선물/현물 분리해 수동 |

`source=Yahoo`, `method=yfinance`, `quote_delay_minutes`(실제 알려질 때만), `instrument_type`, `contract`, `last_bar_at`, `downloaded_at`, `data_license_status`, `validated_against`를 기록한다. 권한·지연 확인을 전제로 VIX·국채 3M/5Y/10Y/30Y 및 지정 주식·ETF 지표에 기본 적용하고, 원자재·BTC Yahoo 가격은 별도 비교용으로 제한한다.

## 4. Yahoo 종목 원본 근거

- [`^VIX` CBOE Volatility Index](https://finance.yahoo.com/quote/%5EVIX/)
- [`^TNX` CBOE Interest Rate 10 Year T Note](https://finance.yahoo.com/quote/%5ETNX/)
- [`^FVX` Treasury Yield 5 Years](https://finance.yahoo.com/quote/%5EFVX/)
- [`^IRX` 13 Week Treasury Bill](https://finance.yahoo.com/quote/%5EIRX/)
- [`^TYX` Treasury Yield 30 Years](https://finance.yahoo.com/quote/%5ETYX/)
- [`CL=F` WTI crude](https://finance.yahoo.com/quote/CL%3DF/)
- [`BZ=F` Brent Last Day Financial](https://finance.yahoo.com/quote/BZ%3DF/)


## 5. 추가 심볼 조회 검증

국채 5개 만기는 3개월 `^IRX`, 2년 네이버 `US2YT=RR`(허가 전 Treasury `BC_2YEAR` 일별 fallback), 5년 `^FVX`, 10년 `^TNX`, 30년 `^TYX`이다. 2년 선물 `2YY=F`·`ZT=F`는 현물 파 수익률과 다르다. 2026-11-22 Yahoo chart 실조회에서 `^UST2Y`, `^US2Y`, `US2Y`는 404; `2YY=F`는 2-Year Yield Futures로 조회됨을 확인했다.

VIX `^VIX`는 기본 지표이고 `CL=F`, `BZ=F`, `GC=F`, `BTC-USD`는 별도 비교 시계열이다. Gold API 현물 추정 참고와 Binance 기본 계약 가격은 분리한다. [적용 정책](./Market_Source_Policy_20261123.md).

2026-11-22 Yahoo chart 직접 조회에서 `^IRX`, `^FVX`, `^TNX`, `^TYX`, `CL=F`, `BZ=F`, `GC=F`, `BTC-USD`는 HTTP 200과 Yahoo 시계열 메타데이터를 반환했다. **모든 심볼에 대해 yfinance 1분봉, WS 실시간 수신, 무지연 보장을 검증했다는 의미는 아니다.** 실시간이 아니라 최신 제공봉 조회임을 UI·DB에 표시한다.
