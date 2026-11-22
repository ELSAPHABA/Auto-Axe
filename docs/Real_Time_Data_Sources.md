# Auto-Axe 실시간·준실시간 데이터 소스 실전 조사

> 조사일: **2026-11-22 (KST)**. 기존 [일별·공식 데이터 카탈로그](./Indicator_Data_Sources.md)를 대체하지 않고 보완한다. 주요 출처의 공개 문서에서 제공 기능을 확인했지만 **각 API에 실제 키로 접속해 실시간 데이터 수신까지 성공했다는 뜻은 아니다**. 유료 접근권, 응답 예시, UI·스크래핑 약관은 배포 직전 재확인.
>
> **실시간의 의미**: `source_event_at`(거래소 체결/발표 시각)과 `received_at`의 차이를 직접 측정해야 한다. 시장 시세의 real-time, 10~20분 delayed, 공급자 캐시가 있는 near-real-time, 하루·월에 한 번 게시되는 official fix는 완전히 다르다. `poll_every=1s`로 바꿔도 데이터 자체의 지연은 줄지 않는다.

## 한눈에 보는 선택표

| 목표값 | 최선의 실시간 경로 | 저비용/공개 경로 | 스크래핑 / 불가능성 | 권장 운영 |
|---|---|---|---|---|
| **미국 주식 CNN 공포·탐욕** | CNN 콘텐츠 사용 계약/인덱스 공식 제공 협의 | CNN 비문서화 JSON `production.dataviz.cnn.io/index/fearandgreed/graphdata` | CNN 페이지 DOM 추출도 약관 검토 필요, 원지표 자체 비연속 갱신 | **C 실험**; 점수와 원본 timestamp를 저장 |
| **기업 가이던스** | 실시간 뉴스·재무 벤더 + 계약 | **SEC Latest Filings Atom/RSS**, 원문 8-K/Ex99.1, 기업 IR RSS/보도자료 | 기업 IR 허용 범위 HTML 파싱 / 사이트별 셀렉터 | **A** 신규 공시 이벤트, NLP/규칙 추출 |
| **금 현물 XAU/USD** | 권리 보유 OTC/벤치마크 실시간 벤더 | [Gold API](https://gold-api.com/docs) `/price/XAU` 무키 폴링 | HTML 가격 대신 합법적인 JSON 우선 | **B** 30~60초, 공급자 갱신시간 중복제거 |
| **금 선물 GC** | **CME 유료 WS** / **Databento Live GLBX.MDP3** / **Massive Futures WS** | 지연 선물 feed (계약 요금제 확인) | 시세 웹사이트 HTML 추출은 지연·저작권 문제 | **A 계약형** 틱/호가 |
| **WTI CL** | CME NYMEX 유료 WS / Databento / Massive | EIA 일별 현물은 **실시간 아님** | Yahoo `CL=F` 브라우저값은 비공식·지연 가능 | 계약형 CL 선물 틱 + EIA 종가를 따로 |
| **Brent BZ** | ICE Brent 관련 라이선스 피드 / CME Brent 관련 별도 상품(실제 계약 확인) | EIA 일별 현물은 **실시간 아님** | Yahoo `BZ=F` 비공식/지연 | **ICE 브렌트 원계약**과 WTI 상품·거래소 표기 |
| **Dubai 원유** | **Platts Dubai·Argus Dubai 평가가격 구독/라이선스**, 관련 Oman/Dubai 파생상품 계약 | IMF `POILDUBUSDM` **월간만** | 공개 웹에서 일중 Dubai spot 평가가 자동 수집된다고 가정하지 않음 | 실제 평가가격은 계약형, 프록시는 별도 시리즈 |
| **VIX 지수** | **Cboe Global Indices Feed** 또는 라이선스 제공사 실시간 인덱스 | Cboe `VIX_History.csv` 종가/EOD | **Cboe quotes dashboard의 자동 추출은 명시적으로 금지** | 공식 유료 feed; 지연판은 지연 표기 |
| **미국 국채 금리** | 라이선스 **on-the-run cash Treasury** 호가·거래 데이터 (벤더/브로커) | FRED DGS*, Treasury Daily Par Yield **하루 한 번** | `^TNX` 등은 지수/비공식 프록시, 직접 국채 수익률 아님 | 2Y/10Y cash yield와 ZN/UB futures 분리 |
| **미국 국채 선물** | CME/CBOT ZT·ZF·ZN·ZB·UB 실시간 WS | 지연 거래소 선물 피드 | Yahoo `ZN=F` 등은 참고·검증용 | 틱과 rollover 관리 |
| **펜타곤 피자지수** | **허가받은 원천 혼잡 데이터 공급자**만 가능 | [pentagon.pizza](https://www.pentagon.pizza/) 화면 수동 참조 | **Google Maps Popular Times 자동 추출·저장/스크래핑은 약관 위험** | 외부 참고 링크, 자동 매매 입력 불가 |
| **경제지표 실제 발표·캘린더** | **Trading Economics calendar WebSocket** 등 상용 이벤트 피드 | BLS ICS, FOMC/BEA/Census 공식 사이트, 공식 발행기관 발표 파일 | 공식 달력 HTML/RSS/ICS 파싱(robots/약관 준수) | 스케줄은 1일+발표 전 재검; 실제 값은 스트림 |
| **옵션·선물 만기 이벤트** | OCC/Cboe/CME 계약·캘린더 공식 업데이트 + 해당 종목 실시간 OI/호가 계약 | OCC/OIC 캘린더·CME contract specs | 공공 페이지 허용된 범위 HTML 파싱 | 만기일은 사전 확정 이벤트, DTE 초 단위 계산 |
| **미국·일본·영국·유로존 정책금리** | Fed/BOJ/BoE/ECB **금리 결정 성명** 즉시 감시 또는 상용 이벤트 WS | 공식 RSS/보도자료/발표 캘린더, FRED/BOJ/BoE/ECB API | 공식 페이지 공지 추출 가능하나 소스 수정 주기 주의 | 발표 시 변경 이벤트 기록; 매초 변하는 호가 아님 |
| **비트코인 BTC** | **Coinbase Exchange WebSocket** `BTC-USD`, Binance Spot WS `BTCUSDT` | CoinGecko REST (집계·캐시, 무료 제약) | 스크래핑 불필요 | 무료 공개 WS 우선, 틱·봉·거래소 분리 |

**우선순위:** 무료 즉시 작동 가능한 BTC WS·Gold API·SEC RSS·BLS ICS → 유료 시세 계약(CME/Cboe/ICE/국채 cash) → 가이던스·실제 경제발표 상용 스트림 → 비공식 CNN은 계약 검토 후 선택. **실시간을 충족하지 못한 항목은 “실시간 수집 가능”으로 표기하지 않는다.**

## 1. 실시간 시장 시세: 공통 유료 공급자

### CME Group Real-Time Futures and Options Data API (거래소 직공급)

- 공식 문서: [CME 실시간 Futures·Options WebSocket](https://www.cmegroup.com/market-data/real-time-futures-and-options-data-api.html).
- CME가 제공하는 **JSON WebSocket**: 체결, top-of-book, 일일 통계. 공식 문서상 top-of-book 메시지 **500ms conflation**. 구독 가능한 상품: NYMEX WTI CL, COMEX Gold GC, CBOT Treasury ZT/ZF/ZN/ZB/UB 등(상품·권한 최종 확인).
- 공식 페이지에 **전송 사용량 요금 + ILA 등 라이선스 비용** 별도 표시. 거래소 데이터의 *개인 비표시/사업체 표시·재배포/자동매매* 사용에 따라 계약 분류가 달라진다.
- WS 서버 인증 정보/토큰/구독 심볼은 실제 계약·개발자 포털에서 발급; **인터넷에서 임의 엔드포인트를 추측하여 구성하지 않는다**.

### Databento Live

- [공식 라이브 Quickstart](https://databento.com/docs/quickstart/live), [라이선스](https://databento.com/docs/portal/live-data).
- `pip install databento`. CME Globex `GLBX.MDP3`에 Live 클라이언트로 `trades`, `ohlcv-1s`, MBP 등을 구독. **원시 프로토콜은 TCP 기반이며 일반 WebSocket URL이 아니다.**
- 예 (실제 인증 키/거래소 사용권 필수):
  ```python
  import os, databento as db
  client = db.Live(key=os.environ["DATABENTO_API_KEY"])
  client.subscribe(dataset="GLBX.MDP3", schema="trades",
                   stype_in="parent", symbols="ES.FUT")
  client.add_callback(print)
  client.start()
  client.block_for_close(timeout=15)
  ```
- `ES.FUT`는 공식 검증 예제. **CL, GC, 금리선물로 변경하기 전에** symbol mapping 및 실제 거래소 entitlement 확인. ICE Brent는 `GLBX.MDP3`가 아니므로 같은 데이터셋을 강제로 쓰지 않는다.

### Massive (구 Polygon.io)

- [공식 Futures WebSocket](https://massive.com/docs/websocket/quickstart?assetClass=futures&display=all&license=personal), [Indices API](https://massive.com/indices), [Futures 정식 제공 발표](https://massive.com/blog/futures-data-has-arrived).
- 주식·옵션·지수·선물·외환·암호화폐마다 상품 및 권한이 다른 REST/WS 인터페이스. **실시간/지연 단계는 플랜별 상이**. Cboe의 VIX는 모든 기본 플랜에 포함된다고 가정하지 않는다.
- 예시 선물 콘트랙트 검색 `GET https://api.massive.com/futures/v1/contracts?product_code=CL` (키/요금제에 따른 접근); 실제 WS 연결/이벤트명은 로그인한 공식 API 문서의 상품별 스키마를 따라간다.
- 상용 앱 재배포·display license가 기본 개인용 WebSocket 가격에 포함된다고 가정하지 않는다.

### Trading Economics (다자산 + 거시 이벤트)

- [Markets Streaming](https://docs.tradingeconomics.com/markets/streaming/), [Economic Calendar Streaming](https://docs.tradingeconomics.com/economic_calendar/streaming/), [Financials Earnings Streaming](https://docs.tradingeconomics.com/financials/streaming/).
- 공식 Python 패키지 `tradingeconomics`가 WS 인증과 재연결을 처리. 문서 예제의 `te.subscribe('CL1:COM')`은 유가 선물계열 **서비스 제공 심볼**이고 EIA WTI 현물 `PET.RWTC.D`와 다른 값이다. 선택 심볼의 실제 coverage/quote latency는 계정별 확인.
- API key 단독의 demo 구독과 실서비스 `key:secret` 권한은 다르다. 경제지표 actual, previous, forecast는 상용 이벤트 스트림으로 수신 가능.

## 2. 항목별 수집 구현

### 2.1 CNN 공포·탐욕

- 원본 [CNN 지수 페이지](https://www.cnn.com/markets/fear-and-greed) 및 *비공식* `GET https://production.dataviz.cnn.io/index/fearandgreed/graphdata`. 커뮤니티 [2026 파서](https://github.com/wildsurfer/cnn-fear-and-greed-parse)와 [필드 관찰 보고](https://github.com/qte77/analyze-stock-kpi/blob/main/docs/cnn-fg-api.md).
- 이 URL은 CNN이 공식·영속적으로 보장한 API가 아니다. 무키로 응답할 때도 **데이터 라이선스·자동 수집·상용 활용 권리는 검토 필요**. 접근 차단 시 브라우저 UA 사칭·IP 회전·CAPTCHA 우회로 계속 긁지 않는다.
- 조건부 PoC: 적법한 접근권을 확보한 경우에만 JSON을 5~15분 폴링, `fear_and_greed` 아래 `score`, `rating`, `timestamp` 등의 실제 응답 구조를 런타임에서 확인. 제공자가 값·시각을 바꾸지 않으면 **동일 스냅샷 반복 기록하지 않음**. 이는 **공식 보증 실시간 틱이 아니라 최신 제공 스냅샷**.
- 사업용 대안: 주식 지수, breadth, put/call, VIX 등 계약된 스트림으로 독립 제작한 `AUTO_AXE_SENTIMENT`. CNN 지수라는 명칭 사용 금지.

### 2.2 기업 가이던스

- 공식 [SEC Latest Filings RSS](https://www.sec.gov/about/rss-feeds), [SEC 개발자 리소스](https://www.sec.gov/about/developer-resources); EDGAR 최신 파일용 Atom URL 예:
  ```text
  https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&company=&dateb=&owner=exclude&count=100&output=atom
  ```
- **SEC는 Latest Filings와 관련 RSS가 가능한 한 실시간에 가깝다고 공식 설명**. 그러나 수리 승인 후 공개 지연은 보통 약 1~3분, 부하 시 그보다 길 수 있다. [SEC FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions).
- 60~120초 간격으로 Atom의 `id/link/updated` 확인 → 8-K `Item 2.02` 및 Exhibit 99.1 확인 → IR 실적 발표문 파싱 → `fiscal_year`, `quarter`, `revenue_min/max`, `EPS_adjusted_min/max`, `guidance_updated_at`, `first_seen_at` 저장. 숫자를 단위/GAAP 여부/회계연도와 분리하여 추출하지 말 것.
- 실시간 뉴스 벤더/SEC EDGAR Public Dissemination Service는 더 짧은 지연을 위한 상용 대안. Trading Economics earnings WS는 **실적 발표 데이터** 스트림이지만 기업 자체 미래 가이던스를 포괄적으로 제공한다고 단정하면 안 된다.
- SEC **식별 가능한 User-Agent**, 통합 IP당 **10 req/s 이하** 및 429 대응. 공시 URL·원문 해시·표현/버전 전체를 저장.

### 2.3 금값

- 공개 REST: `curl https://api.gold-api.com/price/XAU`; [API 문서](https://gold-api.com/docs), [가격 페이지](https://gold-api.com/assets/gold), [약관](https://gold-api.com/terms).
- `price`와 `updatedAt` 확인; **USD/troy oz**인지 응답 필드로 재확인. 가격에 공급원 캐시와 거래 시간 지연이 있을 수 있다. 문서상 무료 무키/real-time endpoint 사용량 제한이 없다고 하나 **약관은 초당 복수 요청의 남용을 금지**하므로 30~60초 권장.
- 진짜 선물 틱은 COMEX `GC` 계약 feed, 런던 벤치마크는 [LBMA](https://www.lbma.org.uk/prices-and-data/precious-metal-prices) 라이선스, **금 현물 XAU ≠ GC 선물 ≠ LBMA Gold Price**.

### 2.4 WTI·Brent·Dubai

- **WTI 실시간 대용이 아니라 별도 상품:** NYMEX `CL` 선물(거래소 유료 실시간 feed). 현물 WTI `PET.RWTC.D`는 [EIA API](https://www.eia.gov/opendata/documentation.php)의 **일별**; 이 값 자체를 매초 갱신할 공식 무료 소스는 아님.
- **Brent:** ICE Brent 선물/가격 평가 라이선스 피드. 특정 CME Brent 관련 파생상품과 **ICE 원계약이 같다고 간주하지 말 것**. EIA `PET.RBRTE.D`는 현물 *일별*.
- **Dubai:** Dubai/Oman 평가가격은 Platts/Argus 등의 정기 평가·계약형 데이터; [IMF/FRED POILDUBUSDM](https://fred.stlouisfed.org/series/POILDUBUSDM)는 월평균. 실시간 숫자가 필요한 경우 Dubai/Oman 관련 선물 계약을 별도 실시간 프록시로 사용하되 원유 산지·성질·결제방법이 다르다는 점 명시.
- 시계열 모델: `commodity=WTI|BRENT|DUBAI`, `instrument_type=SPOT_ASSESSMENT|FUTURE`, `venue`, `contract`, `expiry`, `front_month_roll_rule`. 별도의 forward curve 없이는 월물 rollover 때 발생하는 인위적 가격 점프가 수익률에 섞인다.
- Yahoo 웹시세 `CL=F`, `BZ=F`, `GC=F`는 탐색/보조대조용으로도 **공식 무료 실시간 API가 아니다**. 웹 요청 역공학/스크래핑의 안정성·지연·사용권을 보장하지 않으므로 실시간 주문 신호에 사용하지 않는다.

### 2.5 VIX

- 공식 [Cboe Global Indices Feed](https://www.cboe.com/data/global-indices-feed) = VIX 등 지수의 실시간 스트리밍(계약). [공식 VIX 과거 CSV](https://www.cboe.com/tradable_products/vix/vix_historical_data) = EOD, 실시간 아님.
- Massive indices 등 제공사에서도 `VIX` 심볼 제공·패키지/실시간 권리를 별도 확인.
- **스크래핑 배제:** Cboe [Quotes Dashboard](https://www.cboe.com/data/quotes/vix/options)는 자동추출 소프트웨어로 지연 호가 테이블을 다운로드하는 것을 명시적으로 금지. 이를 회피하는 Playwright/API 사칭 예제를 제공하지 않는다.
- `^VIX`(비공식 페이지), `VX`(CFE VIX 선물), `VIXY`(ETF)는 **서로 다른 상품**.

### 2.6 미국 국채

- [Treasury Par Yield Curve](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics), [FRED DGS10](https://fred.stlouisfed.org/series/DGS10) 일별은 **실시간 수익률이 아님**.
- 라이선스 있는 현물 국채 시장 데이터 공급자로 on-the-run 2Y/5Y/10Y/30Y 국채의 best bid/ask와 유통 수익률을 수신하면 실시간 관측 가능. 일부 브로커는 국채 개별 CUSIP 호가/체결 접근을 제공하지만 API 상품·재배포 권한 확인.
- 저렴한 동적 대용은 CME/CBOT Treasury futures `ZT`, `ZF`, `ZN`, `ZB`, `UB`; **선물 가격 110-xxx는 10Y 수익률 4.x%와 직접 같은 값이 아님**. CTD·conversion factor·수익률 모델 없이 1:1 변환 금지.
- Yahoo `^TNX` 등은 벤치마크 지수형 quote; DGS10 현물 일별과 정확히 동일하지 않으며 라이선스/지연/웹 구조 검증 필요.

### 2.7 펜타곤 피자지수

- [pentagon.pizza](https://www.pentagon.pizza/) 외부 참고 링크/수동 관찰만 기본.
- Google Places UI Kit `gmp-place-popular-times`는 **화면에 혼잡 정보를 렌더링**하는 컴포넌트로, Google Places API가 외부 정량 저장 가능한 Popular Times REST 필드를 제공한다는 뜻이 아니다. [UI Kit](https://developers.google.com/maps/documentation/javascript/places-ui-kit/place-details), [Google 정책](https://developers.google.com/maps/documentation/places/web-service/policies).
- Maps Popular Times / Maps 페이지의 숫자·SVG·내부 XHR·DOM을 스크래핑해 외부 DB에 축적하는 방식은 약관과 충돌할 가능성이 커서 실행 예제를 배포하지 않는다. 사이트 소유자/혼잡 데이터 공급자에게 **원자료·API·재사용 허락**을 받아야 함.
- 승인된 공급원 확보 시 `store_id`, `observation_time`, `crowding`, `relative_baseline`, `coverage`를 관찰 지표로 저장; 국제 정세와의 상관을 검증 없이 트레이딩 인과 신호로 사용하지 않는다.

### 2.8 경제·금리 발표 일정과 **실제 발표값**

- 무료 일정: [BLS ICS](https://www.bls.gov/schedule/news_release/bls.ics), [BEA schedule](https://www.bea.gov/news/schedule), [FOMC calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm), [Census Indicators](https://www.census.gov/economic-indicators/). 캘린더는 **예정 이벤트**, 실제 CPI·NFP 등 수치는 별도 공식 발표 파일/API에서 발표 후 수집.
- **상용 실시간 actual·consensus WS:** [Trading Economics Calendar Streaming](https://docs.tradingeconomics.com/economic_calendar/streaming/). `te.login(KEY_OR_KEY_SECRET)`, `te.subscribe('calendar')`, `te.run(callback)`. message 필드 `calendarId`, `event`, `country`, `actual`, `previous`, `forecast`, `teforecast`, `date`.
- 긴급성 높은 발표는 예정시각 전후에만 공식 보도자료/통계 API 주기를 5~15초까지 조절하되 **제공기관의 허용량과 publication time 확인**, 실제 시차는 별도 계측. 문서화된 발표 API가 없으면 허용된 HTML/CSV/JSON 공식 발표자료 페이지를 파싱. 유명 금융 포털 스크래핑은 데이터 정확성·약관·타임스탬프 검토 선행.
- 예정된 8:30 ET 발표가 시차에 따라 21:30 또는 22:30 KST가 될 수 있으므로 IANA timezone `America/New_York` 사용.

### 2.9 파생상품 만기

- [OCC/OIC 옵션 만기 캘린더](https://www.optionseducation.org/referencelibrary/expiration-calendar), [Cboe 상품별 옵션 달력](https://www.cboe.com/tradable_products/), [CME Contract Specs/Expiration](https://www.cmegroup.com/education/courses/micro-e-mini-futures/managing-micro-e-mini-futures-expiration).
- **만기일은 원래 초 단위로 가격처럼 변하는 스트림이 아니다.** 다가오는 만기·최종거래·만기결제 시점을 정확히 저장하고 매초 DTE를 계산한다. 거래소 휴장/임시 일정 변경만 감시.
- **2026-06-19 미국 Juneteenth**가 분기 셋째 금요일과 겹치는 사례처럼 일반 '셋째 금요일' 계산으로 상품별 최종거래일을 확정하면 오류. SPX AM/PM, 주간 옵션, VIX 파생, 선물 실물·현금결제를 각각 구분.
- 실시간 max pain/감마익스포저 등은 별도 **옵션 chain + 거래량/OI(실시간 OI가 아니라 보통 일별 갱신)** 권리 필요. 옵션 만기일만으로 이런 값 자동 생성 불가.

### 2.10 미국·일본·영국·유로존 기준금리

- **미국:** Fed [FOMC 성명/발표](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)를 먼저 감시해 target lower/upper 변경 이벤트 기록; FRED `DFEDTARL`/`DFEDTARU`/`DFF`는 후속 공식 시계열 확인용. FRED API의 `real-time`은 *ALFRED 빈티지/개정시점* 기능도 뜻하므로 거래소 실시간 틱을 의미하지 않는다.
- **일본:** BOJ [통화정책 결정](https://www.boj.or.jp/en/mopo/outlook/index.htm) 및 BOJ 발표자료, API 익일물 무담보 콜 실효금리(목표금리와 구분).
- **영국:** BoE [MPC 금리결정](https://www.bankofengland.co.uk/monetary-policy-summary-and-minutes) / `IUDBEDR` Bank Rate 확정 시계열.
- **유로존:** ECB [Monetary policy decisions](https://www.ecb.europa.eu/press/pr/date/html/index.en.html) / [SDMX 예금금리 DFR](https://data.ecb.europa.eu/data/datasets/FM/FM.D.U2.EUR.4F.KR.DFR.LEV).
- 정책금리는 결정·유효일에 **점프하는 상태변수**: `announced_at` vs `effective_from` 보존. 1초마다 공식 값을 폴링하는 대신 발표 예약 시간대에 감시 강화. 시장이 예상하는 미래금리는 Fed Funds/SOFR/OIS 관련 실시간 계약을 **별도 데이터로 저장**.
- ECB 정책금리는 **유로존**의 공통 통화정책이며 EU 비유로 회원국 전체의 단일 정책금리가 아님.

### 2.11 비트코인

- **Coinbase Exchange 공개 WS:** `wss://ws-feed.exchange.coinbase.com`; 메시지 `{"type":"subscribe","product_ids":["BTC-USD"],"channels":["ticker","heartbeat"]}`. [Coinbase 도움말](https://help.coinbase.com/en/developer-platform/websocket-feeds/exchange). `ticker`는 거래 발생 기반 업데이트, `heartbeat`는 연결 상태/누락 추적.
- **Binance Spot 공개 WS:** `wss://stream.binance.com:9443/ws/btcusdt@trade` (체결), `wss://stream.binance.com:9443/ws/btcusdt@kline_1m` (진행 중 1분봉). [공식 스트림 문서](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md). 연결은 24시간 제한·ping/pong 및 메시지 제한이 있어 자동 재접속 필요.
- USD와 USDT 호가 차이, 거래소별 스프레드 및 가짜 '통합 BTC 기준값' 주의. 24×7 UTC, 일간 봉 기준시점 고정. Binance 일부 국가/네트워크에서 접근 제한 가능.
- 다음 문서의 [실행형 데모](./Realtime_Quickstart.md)에 실제 WS 수신 코드 제공.

## 3. 스크래핑 허용성 원칙

| 사이트/출처 | 권장 방법 | 자동 HTML 수집 판정 |
|---|---|---|
| SEC EDGAR | 공식 Atom/RSS·JSON·공시 링크 | 공개 파싱 가능, Fair Access 준수 (10 req/s 이하·식별 UA) |
| BLS/BEA/FOMC/BOJ/BoE/ECB | 공식 ICS/RSS/CSV 우선 → 공식 공개 HTML 파싱 | robots.txt·Terms 준수, DOM 변경·발표시각 리스크 |
| 개별 기업 IR | RSS/보도자료 공식 다운로드 → 허용 HTML | 기업별 약관/robots/저작권·인용 처리 필요 |
| CNN | 비공식 JSON·DOM (검토용) | 공식 API 아님; 승인 전 상용 수집 보류 |
| Yahoo Finance, Investing.com 등 | 공식 API 계약/데이터 벤더 우선 | 개인 웹 접속을 자동 재배포·틱 데이터 사용권으로 가정 금지 |
| **Cboe Quotes Dashboard** | 공식 피드 계약 | **자동추출 명시 금지** |
| **Google Maps Popular Times** | 제휴 데이터/허용 UI 표시 | **지도의 데이터를 외부 추출·저장하는 스크래핑 배제** |
| pentagon.pizza | 링크·수동 보기, 공급자 허가 | 허가 없는 복제·제3자 Maps 내용 역추출 금지 |

스크래핑이 허용된 사이트라도 `robots.txt`, 이용약관, `ETag`/`If-Modified-Since`, 낮은 폴링 빈도, 고정 식별 UA, 429/403 즉시 중지, 셀렉터 스냅샷 테스트, 원문 출처 링크, `source_published_at` vs `fetched_at` 기록이 필요하다. 로그인/유료벽/지리적 차단/캡차를 우회하지 않는다.

## 4. 실전 데이터 품질·비용 심사표

수집기 승인 전에 각 공급자에 대해 다음을 실제 점검한다.

1. **접속/인증:** 구독 권한, key 별 비밀관리, REST/WS 샘플 10개 이상 실수신.
2. **시차:** `source_event_at`(발생) / `provider_published_at`(공표) / `received_at`(우리 서버) / `processed_at`(DB 반영); 50·95·99백분위 지연과 stale 임계치 기록.
3. **데이터 정의:** spot vs futures, ICE vs CME, front-month rollover, NYMEX CL vs EIA 현물, AM/PM settlement, DGS10 vs ZN.
4. **접근권:** API 사용료 외 거래소 entitlement/ILA + 비표시(non-display) + 상업용 + 외부 제공/대시보드 display/캐시 권리.
5. **생존성:** WebSocket 종료→백오프→재구독→gap backfill, 소스 변경/차단 시 정상 기능과 거래 차단 조건.
6. **백테스트 PIT:** 당시 최초 공개된 값과 현재 revised 값 분리; 경제 발표 `forecast/actual/revised`과 기업 가이던스 변동을 append-only 유지.
7. **실시간 정의:** 계약상 지연 10분/15분이면 UI에 반드시 `delayed` 표시. 도착시간만 최근이라고 '실시간' 표기 금지.

## 5. 바로 실행할 코드와 시작 순서

- [Realtime_Quickstart.md](./Realtime_Quickstart.md): Python 설치/환경변수/실행 명령, curl, REST 폴링, 공개 WS, 허가된 스크래핑 예제, 외부 유료 벤더 코드 및 장애 처리.
- [examples/realtime_collector.py](./examples/realtime_collector.py): 공개 BTC WS, Gold API, SEC 최신 공시 RSS, BLS 발표일정, VIX 종가, FRED/EIA 스냅샷을 정규화 JSON Lines로 출력하는 실행 샘플.
- [examples/requirements.txt](./examples/requirements.txt), [examples/.env.example](./examples/.env.example): 의존성 및 선택적 인증키 견본.
- 기존 [Collector_Design.md](./Collector_Design.md): 생산 시스템용 표준 스키마와 PIT·신뢰성 설계.
