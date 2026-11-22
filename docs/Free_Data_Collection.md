# Auto-Axe 무료 데이터 수집 소스 명세 (2026-11-22)

## 정책 및 판정 기준

이 문서는 Auto-Axe의 **유일한 수집 우선순위 기준**이다. 월 구독·사용량 과금·거래소 유료 피드는 범위에서 제외한다. 모든 목표에 대해 **① 무료 공식·허용 API/WebSocket/다운로드 → ② 자동 수집이 허용된 웹페이지·RSS/Atom/ICS 스크래핑 → ③ 수동 입력** 순으로 선택한다.

- `API`: 문서화된 공공기관 REST/JSON/CSV, 공개·무료 WS. 제3자 무료 키가 필요한 API도 포함하되 API 이용권·데이터 저작권을 별도 검토.
- `SCRAPE`: 제공자의 약관·robots·사용량·저작권 범위에서 **허용될 때만** 공개 HTML/RSS 파싱. 로그인 우회·API 역공학·차단 우회·캡차·프록시 회전은 하지 않는다.
- `MANUAL`: 본문의 무료 경로로 원하는 시점/정의를 보장할 수 없거나 자동화가 금지·불확실한 경우. 수동 조회 URL, 입력 필드, 갱신 주기를 반드시 기록.
- `LIVE`: 공급자가 거래/발표 발생 시 푸시. `NEAR`: 무료 호스트 최신 스냅샷(캐시/지연 미보장). `EVENT`: 공시·발표가 새로 게시될 때만 변경. `EOD`/ `MONTHLY`: 해당 주기만 제공.
- **절대 원칙:** 갱신 주기가 긴 무료 데이터의 반복 폴링으로 “실시간 관측”을 만들지 않는다. 무료 차트·웹페이지의 표시 시각과 그 차트 내용에 대한 **자동 저장 권한**은 다르다.

## 전체 항목별 최종 수집 방법 (우선순위)

| 지표 | 1순위 무료 API·WS·파일 | 2순위 스크래핑 (허용 시) | 3순위 수동 수집 | 데이터 빈도 / 상태 |
|---|---|---|---|---|
| 미국 주식 CNN 공포·탐욕 | **공식 무료 API 미확인**; CNN 비문서화 JSON은 권한 확인 전 운영 제외 | CNN 원본 화면 자동 추출도 사용권 미확인 → 기본 비활성 | CNN [Fear & Greed](https://www.cnn.com/markets/fear-and-greed) 화면의 `score/category/as_of` 기록 | 수동 스냅샷. CNN 수치가 실시간 틱인지 미보장 |
| 기업 실적 가이던스 | **SEC EDGAR** submissions JSON + 8-K Atom/RSS, 문서/Exhibit 원문 | 회사 공식 IR 보도자료 및 허용된 HTML, RSS 없는 경우 | PDF·콜에서 매출/EPS 전망을 근거 링크와 함께 입력 | `EVENT`: 신규 공시/보도자료 |
| 금 (XAU/USD) | [Gold API](https://gold-api.com/docs) `GET https://api.gold-api.com/price/XAU` | 필요 없음 | API 장애 시 제공자 화면 확인 | `NEAR` 제3자 현물 추정, `updatedAt` 사용 |
| WTI 원유 | [EIA API](https://www.eia.gov/opendata/documentation.php) `PET.RWTC.D` | 공식 EIA 게시 데이터 CSV/HTML 대체 (약관 준수) | **장중 선물가격 필요 시** 무료 차트 수동 조회, 상품·지연 표시 | 원유 **현물 공식 EOD**; 무료 검증된 자동 틱 없음 |
| Brent 원유 | [EIA API](https://www.eia.gov/opendata/documentation.php) `PET.RBRTE.D` | 공식 EIA 공개 시계열 HTML/CSV | 장중 Brent 가격 수동 입력 (선물/현물 구분) | **EOD**; 무료 검증된 자동 틱 없음 |
| Dubai 원유 | [World Bank Pink Sheet](https://www.worldbank.org/en/research/commodity-markets) **월간**; [FRED POILDUBUSDM](https://fred.stlouisfed.org/series/POILDUBUSDM) 개인 조회용 | 출처가 허락하는 게시 자료만; GME Oman 보고서는 **Dubai spot 아님** | Dubai 평가가격의 최신 공개 표·날짜·정의 수동 기록 | **MONTHLY** / 장중 Dubai 원값 자동 수집 불가 |
| VIX | [Cboe VIX Historical CSV](https://www.cboe.com/tradable_products/vix/vix_historical_data) | Cboe 호가 대시보드 자동 추출 **명시 금지** | 장중 VIX를 필요로 할 때 Cboe 공개 화면에서 수동·지연명시 | **EOD**; 무료 공식 실시간 API 없음 |
| 미국 국채 수익률 | [Treasury Par Yield CSV/XML](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed) (1/2/5/10/30년 등) | Treasury 공개표 (자동화 허용 시) | 장중 2Y/10Y 현물 수익률 수동 조회·타입 기록 | **EOD** 공식 곡선; 장중 자동 실시간 없음 |
| 펜타곤 피자지수 | 확인된 무료·합법적인 **수치 API 없음** | Google Maps Popular Times 외부 추출·축적은 정책상 제한 → 기본 제외 | [pentagon.pizza](https://pentagon.pizza/) 상태·관찰시각·분류를 수동 기록 | 실험적 `MANUAL`; 시장 신호로 자동 주문 금지 |
| 미국 지표·금리 발표 일정 | [BLS 일정 ICS](https://www.bls.gov/schedule/news_release/bls.ics), FOMC 일정, BEA 발표 일정 | BEA/FOMC/Census 등 공식 HTML/RSS/ICS | 일정 변경·공식 문서 PDF를 수동 입력 | `EVENT`: 공고 즉시 또는 변경시 |
| 미국 지표 실제 발표값 | [BLS v2 API](https://www.bls.gov/developers/api_signature_v2.htm), BEA API, Census API | BLS [CPI 보도자료](https://www.bls.gov/news.release/cpi.htm), [고용보고서](https://www.bls.gov/news.release/empsit.htm), BEA 공식 발표 HTML (허용 범위) | 원문 확인 후 수치·최초 발표·수정여부 수동 입력 | `EVENT`; API가 원문보다 늦을 수 있음 |
| 파생상품 만기 | [OCC/OIC Expiration Calendar](https://www.optionseducation.org/referencelibrary/expiration-calendar) 공식 공개 자료, CME 상품 계약 사양 | 거래소 공개 이벤트 표/캘린더의 허용된 자동 파싱 | 예외·휴장·AM/PM 결제 등 수동 교차검증 | **예정 이벤트**; 실시간 DTE는 자체 계산 |
| 미국 기준금리 | Fed [FOMC 공식 결정](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm), [FRED DFEDTARL/U](https://fred.stlouisfed.org/docs/api/fred/) 개인 조회 | FOMC 공개 보도자료 HTML (허용 시) | 공식 결정 성명 및 발효일 기록 | `EVENT`, 후행 공식 시계열 |
| 일본 기준금리 | [BOJ 무료 2026 통계 API](https://www.stat-search.boj.or.jp/info/api_manual_en.pdf) 실효콜금리 + 정책 결정문 | [BOJ 통화정책 성명](https://www.boj.or.jp/en/mopo/mpmdeci/) 공개 HTML/PDF (허용 시) | PDF 성명 정책 목표금리 수동 확인 | `EVENT` 목표치 / 통계는 일별 실효치 |
| 영국 기준금리 | [BoE 공개 Bank Rate CSV](https://www.bankofengland.co.uk/boeapps/database/Bank-Rate.asp) `IUDBEDR` | BoE 공식 MPC 성명 HTML (허용 시) | 정책 결정·발효시점 확인 | `EVENT` / 일별 Bank Rate |
| 유로존(ECB) 기준금리 | [ECB SDMX 공개 API](https://data.ecb.europa.eu/help/api/data) DFR | [ECB 공식 결정 RSS](https://www.ecb.europa.eu/home/html/rss.en.html) / 보도자료 (허용 시) | 원문 결정금리 수동 확인 | `EVENT` / 일별 DFR; **EU 전체 단일금리 아님** |
| 비트코인 | [Coinbase Exchange WS](https://docs.cdp.coinbase.com/exchange/websocket-feed/overview) BTC-USD, [Binance Spot WS](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md) BTCUSDT | 필요 없음 | 드문 장애 상황에만 참고값 입력 | **LIVE**, 공개 데이터 WS |

**실시간 동적 가격 무료 커버리지:** 비트코인은 무료 WebSocket, 금은 무키 최근가격 REST가 확실하다. **WTI/Brent/Dubai/VIX/미국 국채**는 공식 무료 데이터로 원하는 실시간 체결/호가/현물 평가값까지 구현 가능하다고 주장할 수 없다. 공개 경로는 EOD/월간으로 유지하고 필요한 장중 값은 `manual`과 원상품 식별자를 별도 기록한다.

## 지표별 적용 상세

### 1. CNN 공포·탐욕: 운영 기본 = 수동

원본 [CNN Fear & Greed](https://www.cnn.com/markets/fear-and-greed). 커뮤니티가 사용한 `https://production.dataviz.cnn.io/index/fearandgreed/graphdata`는 문서화되지 않은 엔드포인트이며 공개 접근 가능성과 자동 수집/저장 허가가 동일하지 않다. 403/429·스키마 변경 시 차단 우회하지 않는다. **문서화된 이용 허가가 확인되기 전에는 자동 호출 코드로 기본 제공하지 않음**. `score`(0~100), `sentiment_category`, `source_as_of`(화면에 기재되어 있을 때만), `captured_at`, URL을 기록. 대안은 무료 허용 소스로 직접 만든 독립 심리지표를 별도 이름으로 설계한다.

### 2. 기업 가이던스: 무료 공식 공시가 가장 빠른 범용 경로

- 회사 CIK(10자리 padding) → `https://data.sec.gov/submissions/CIK0000320193.json` 같은 공식 [SEC API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces).
- 신규 공시 Atom `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&company=&dateb=&owner=exclude&count=100&output=atom` 또는 기업별 IR RSS / 뉴스.
- 공시에서 `8-K Item 2.02`와 첨부 `Exhibit 99.1` 찾기 → `revenue`, `EPS`, `margin`, `outlook`, `guidance` → `Q/FY`, `GAAP/adjusted`, `low/high`, `issued_at` 구조화.
- 실제 게시 순서가 **회사 IR → SEC 제출**일 수 있으므로 핵심 종목의 공시 외에 **자사 IR 보도자료** 허용 HTML/JSON/XML/보도자료 RSS 수집기를 추가. 공시가 늦으면 시차 기록.
- SEC 식별 가능한 User-Agent + 합산 초당 10요청 이하 + 429 존중 ([SEC Fair Access](https://www.sec.gov/about/developer-resources)). 원문/첨부 경로, 최초 조회시각 저장.
- **애널리스트 컨센서스 = 회사 가이던스가 아님.** 무료 소스로 완전한 종목별 컨센서스 숫자 자동화가 확인되지 않으면 `manual`로 입력, 확인 출처/관측시점 명시.

### 3. 금

`curl https://api.gold-api.com/price/XAU`, [공식 무료 API](https://gold-api.com/docs), [업데이트 시각 의미](https://gold-api.com/faqs). `price`, `updatedAt` 파싱. 30~60초 추천 폴링(제안값), 갱신 없으면 같은 값 중복 기록하지 않음. spot 추정가격과 금 선물/런던 벤치마크를 혼합하지 않는다. API 장애 시 Gold API 홈페이지 수동 확인.

### 4. WTI / Brent / Dubai 원유

- EIA 무료 API 키: `https://api.eia.gov/v2/seriesid/PET.RWTC.D?api_key=YOUR_KEY` 및 `.../PET.RBRTE.D` — **WTI/Brent 일별 현물**; 갱신이 완료된 일별값만 사용.
- 두바이 원유: [World Bank Pink Sheet 월간](https://www.worldbank.org/en/research/commodity-markets) 파일 또는 [FRED POILDUBUSDM](https://fred.stlouisfed.org/series/POILDUBUSDM) **월평균**. 별도의 Oman 관련 선물 표시가격은 Dubai 현물 평가값과 별도 상품이며 대체하지 않는다.
- 특정 거래소/시세 사이트의 브라우저 화면은 장중 참고할 수 있어도 무료 **기계적 수집 허용**이 확인되지 않으면 자동 크롤러를 만들지 않는다. 공식 보고서 파일만 허용 범위에서 다운받는다.
- 장중 관측이 꼭 필요한 경우 `value_source=manual`, `source_market=spot|futures`, `exchange`, `contract_month`, `delayed_minutes`(표시된 경우)을 입력. **일별 현물 vs 월별 평가 vs 장중 선물 차이**를 반드시 분리.

### 5. VIX / 미국 국채

- VIX [Cboe 공식 EOD CSV](https://www.cboe.com/tradable_products/vix/vix_historical_data): `https://cdn-api.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv`. 시장 운영시간의 실제 스트리밍이 아니다. Cboe Quotes Dashboard에 명시된 **자동화 추출 금지**를 준수한다.
- Treasury [일별 공식 파 수익률](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics), [XML 제공 안내](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed): 2Y/10Y 등 단위 `percent`. [FRED DGS2/DGS10](https://fred.stlouisfed.org/series/DGS10)은 무료 개인 조회 참고만. 국채 현물 수익률과 국채 선물 가격은 전혀 다른 값.
- VIX/국채 장중값 자동 무료 피드를 검증하지 못한 경우 **스크래핑을 무작정 추가하지 않고 수동 기록**(원래 현물/지수 정의, 게시시각, 링크, 데이터 지연).
- **FRED 주의:** API 이용약관은 별도의 무허가 데이터 저장/캐싱/DB 편입 및 AI 개발/학습 관련 제한을 명시한다. Auto-Axe의 영속 DB에 FRED 반환값을 무조건 적재하지 말 것. [FRED 이용약관](https://fred.stlouisfed.org/legal/terms/). 가능한 경우 데이터 원 발행기관(EIA/Treasury/BOJ/ECB)의 허용된 공개 다운로드로 대체한다.

### 6. 펜타곤 피자지수: 수동

[pentagon.pizza](https://pentagon.pizza/)의 공개 Activity Index를 **화면에서 수동 관찰**한다. Google Maps Popular Times에서 숫자를 추출하는 문서화된 무료 REST API는 확인되지 않았고, [Google Places 데이터 정책](https://developers.google.com/maps/documentation/places/web-service/policies)은 외부 추출·저장 및 재배포를 제한한다. 서드파티 피자지수 페이지의 직접 스크래핑도 원천 콘텐츠 권리 검토가 필요하다. `activity_label`, `activity_score_if_public`, `observed_at`, `source_url`, `manual_note`만 기록하고 **객관적 예측력/자동매매 신호로 확정하지 않는다**.

### 7. 경제지표 발표 일정·실제 수치

- 일정: [BLS 공식 ICS](https://www.bls.gov/schedule/news_release/bls.ics) (CPI/NFP/PPI), [BEA 일정](https://www.bea.gov/news/schedule) (GDP/PCE), [Fed FOMC 일정](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm), [Census 일정](https://www.census.gov/economic-indicators/). ICS 공식 다운로드 → HTML/RSS 허용 파싱 → 수동 순.
- 실제 수치: BLS `POST https://api.bls.gov/publicAPI/v2/timeseries/data/` 예 `CUUR0000SA0`(CPI-U), `CES0000000001`(취업자), `LNS14000000`(실업률). [BLS API FAQ](https://www.bls.gov/developers/api_faqs.htm): 미등록/등록 일일 요청 제한 준수. [BLS CPI release](https://www.bls.gov/news.release/cpi.htm) 보도자료는 API 반영 전 원문 확인 가능하지만 페이지의 차기 값 갱신을 무조건 단정하지 않는다.
- BEA 무료 데이터 API [개발자 페이지](https://www.bea.gov/resources/for-developers), CPI와 PCE는 서로 다른 지표; BEA GDP·PCE 원문 공개 페이지 허용 크롤링. `forecast`(컨센서스)는 공공기관 발표 자료에서 대체로 제공하지 않으므로 **검증된 무료 표준값 부재 시 `manual`**.
- `scheduled_at`(예정), `released_at`(공개), `first_seen_at`(수신), `period`(대상월/분기), `actual_first`, `revised`, `previous`, `consensus_if_available` 분리. 미국 동부 시간대 DST 적용.

### 8. 파생상품 만기

[OCC/OIC 공개 만기 달력](https://www.optionseducation.org/referencelibrary/expiration-calendar), Cboe 상품 설명/계약별 일정, CME 상품별 만기 명세를 무료 공개 페이지/파일에서 읽는다. 일반적인 월간 규칙 계산은 **예비 후보일 생성용**이고 실제 확정은 상품 계약/휴장 공지로 교차검증. OCC 2026-06-19 Juneteenth에 명목 expiration date와 processing date가 다른 사례([OCC 인포메모](https://infomemo.theocc.com/infomemos?number=56694))를 반영. `expiry_date`, `last_trade_at`, `processing_at`, `settlement_at`, `exercise_style`, `am_pm`, `source_url` 각각 저장. 공식 캘린더의 기계 판독이 어려우면 수동.

### 9. 정책금리 4개 지역

| 기관 | 무료 자동 경로 | 발표 즉시 조치 | 별도 의미 |
|---|---|---|---|
| 미국 Fed | FOMC 공식 성명 HTML/일정 감시 | 결정문 목표구간 숫자 수집, 이후 원기관/FRED 보조 확인 | 목표 하단·상단/실효금리 다름 |
| 일본 BOJ | 무료 [2026 BOJ 통계 API](https://www.stat-search.boj.or.jp/info/api_manual_en.pdf) 실효 콜금리 | [통화정책 결정문](https://www.boj.or.jp/en/mopo/mpmdeci/) 공개 HTML·PDF 수집 | overnight 실효금리와 목표정책 별개 |
| 영국 BoE | 공개 통계 `IUDBEDR` [CSV 다운로드](https://www.bankofengland.co.uk/boeapps/database/Bank-Rate.asp) | [MPC 결정문](https://www.bankofengland.co.uk/monetary-policy-summary-and-minutes) 허용 파싱 | 결정 발표/적용일 분리 |
| 유로존 ECB | [SDMX API](https://data.ecb.europa.eu/help/api/data), 키 `FM.D.U2.EUR.4F.KR.DFR.LEV` | [ECB RSS](https://www.ecb.europa.eu/home/html/rss.en.html) 발표 감시 | DFR은 유로존; EU 전체 아님 |

예시: `https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.DFR.LEV?lastNObservations=5&format=csvdata`. BOJ: `https://www.stat-search.boj.or.jp/api/v1/getDataCode?format=json&lang=en&db=FM01&code=STRDCLUCON,STRDCLUCONH,STRDCLUCONL&startDate=202501` (정책 결정 목표가 아닌 시장 실효율). 변동이 없는 결정도 `no_change` 이벤트로 남긴다.

### 10. 비트코인

- [Coinbase 거래 체결/호가 WS](https://docs.cdp.coinbase.com/exchange/websocket-feed/overview): `wss://ws-feed.exchange.coinbase.com` 구독 `{"type":"subscribe","product_ids":["BTC-USD"],"channels":["ticker","heartbeat"]}` (무키).
- [Binance market-data-only WS](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md): `wss://data-stream.binance.vision/stream?streams=btcusdt@trade/btcusdt@kline_1m`, trade 실시간, `k.x=true` 마감 1분봉. 연결 시간/핑·퐁/호가통화/지역제한 준수.
- USD / USDT를 같은 자산 가격처럼 합치지 않는다. 24x7 UTC 시간축 사용.

## 자동 스크래핑 운영 체크

1. **허용 출처를 선택**: 정책·robots.txt·서비스 이용권 확인. **robots 허용만으로 저작권/데이터 재배포 허가가 주어지는 것은 아니다.**
2. 공식 기관부터 `RSS/Atom/ICS/CSV/JSON` 우선. HTML만 가능하면 정부 발표/기업 IR 중 약관 허용된 페이지를 `requests + BeautifulSoup`로 파싱. 타임스탬프와 원본 링크 저장.
3. 정해진 간격/조건부 GET/429 백오프, 도메인별 총 요청 제한. 403/캡차를 우회하지 않는다.
4. HTML 구조 변경 시 **빈 데이터 성공으로 처리하지 말고 `manual_review_required`**로 전환. 소스가 발표한 시각과 수집 시각 분리.
5. 예제: [무료 수집 Quickstart](./Realtime_Quickstart.md) / [공개 수집 Python](./examples/realtime_collector.py). 수동: [수동 입력 가이드](./Manual_Collection.md).

## 반드시 주의할 이용약관

- [Yahoo 자동 수집 제한](https://legal.yahoo.com/us/en/yahoo/terms/product-atos/apitnc/index.html): 비문서화 `chart/v8`와 `yfinance`를 **승인된 무료 운영 소스라고 분류하지 않음**.
- [Cboe 호가 테이블 자동추출 금지](https://www.cboe.com/data/quotes/vix/options): VIX 장중 호가 웹 스크래핑을 권장하지 않음.
- [Google Places 정책](https://developers.google.com/maps/documentation/places/web-service/policies): Popular Times 별도 DB 저장/추출 배제.
- [CME 웹데이터 대량 추출 제한](https://www.cmegroup.com/articles/faqs/access-to-cme-group-settlement-data-faq.html): 공개 차트의 HTML/WebSocket 역공학으로 무단 수집 금지.
- [SEC Fair Access](https://www.sec.gov/about/developer-resources): 10 req/s 이하, 사용자 에이전트 연락처 필요.
- [BLS 자동 조회 제한](https://www.bls.gov/bls/blsterms.htm): 초당 여러 번 반복 추출하면 차단될 수 있음.
- [FRED API 이용약관](https://fred.stlouisfed.org/legal/terms/): 저장/캐싱/DB·AI 관련 제한 및 원 소스의 저작권 필수 확인.

## 다음 문서

- [Realtime_Quickstart.md](./Realtime_Quickstart.md): 복사해서 실행할 명령·예제·폴링 권장값.
- [Manual_Collection.md](./Manual_Collection.md): 최종 수동 분류 항목 및 CSV 포맷.
- [Collector_Design.md](./Collector_Design.md): 소스 단계별 failover, 이벤트·시각·백테스트 설계.
