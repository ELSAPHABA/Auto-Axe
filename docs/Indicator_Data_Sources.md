# 시장·거시·대체지표 데이터 수집원 카탈로그

- 기준일: **2026-11-22 (Asia/Seoul)**
- 대상: Auto-Axe (NH나무 OpenAPI 기반 퀀트 플랫폼)
- 범위: 미국 주식 공포·탐욕, 기업 가이던스, 금, WTI/Brent/Dubai, VIX, 미국 국채, 피자지수, 거시 발표일정, 파생상품 만기일, 미국·일본·영국·유로존 금리, 비트코인.
- 근거 수준: **A** 공식 발행기관/거래소 API·파일, **B** 공개 중개 시계열/제3자 제공, **C** 비공식 엔드포인트·실험적 수집. A도 *실시간/상업 재배포 권리*를 자동으로 의미하지 않는다.
- 원칙: **발표값, 실시간 호가, 최종 확정치, 월평균, 예상 이벤트**를 동일한 빈도와 확정도로 혼동하지 않는다.

## 1. 수집 경로 요약

| 지표 | 권장 수집원 | 실현 가능한 기본 빈도 | 접근 | 근거 | 주의 |
|---|---|---|---|---|---|
| 미국 주식 공포·탐욕지수 | CNN 웹페이지 (비공식 JSON은 검증용으로만) | 당일 스냅샷(제공자 갱신 불명) | 문서화된 공개 API 없음 | C | 콘텐츠 사용권·엔드포인트 불안정 |
| 기업 가이던스 | SEC EDGAR / 기업 IR 보도자료·실적발표 | 공시 이벤트 단위 | SEC 무료, 텍스트 파싱 필요 | A | 기업 전망과 컨센서스 분리 |
| 금 (XAU/USD) | Gold API 가격 / World Bank Pink Sheet 월간 / 라이선스 LBMA | 준실시간 추정 / 월간 / 벤치마크 1일 2회 | 제3자 무료·유료 혼합 | B/A | 비벤치마크 spot과 LBMA fix 구분 |
| WTI / Brent 현물 | EIA PET.RWTC.D / PET.RBRTE.D, FRED DCOIL* | 거래일 일별 | EIA 키 무료, FRED 키 무료 | A/B | 선물 근월물과 혼동 금지 |
| Dubai crude | IMF/FRED POILDUBUSDM, World Bank Pink Sheet | **월평균** | 무료 공개 시계열 | B | 일별 Dubai 평가가격은 보통 계약형 |
| VIX | Cboe 공식 일별 CSV | 거래일 일별 OHLC | 공개 파일 | A | 실시간 별도 라이선스 |
| 미국 국채 | Treasury Daily Par Yield Curve / FRED DGS* | 거래일 일별 | 공공 데이터 | A/B | 가격이 아닌 *시장 수익률* |
| 피자지수 | pentagon.pizza / PizzINT 사이트 관찰 | 비표준·실험 | 정식 수치 API 없음 | C | 검증·라이선스 및 추출 금지 가능성 |
| 경제·금리 발표 일정 | BLS ICS, FOMC, BEA, Census | 일정 변경 시 재동기화 | 공개 캘린더/웹 | A | 예정치와 실제 발표/수정치 구분 |
| 파생상품 만기일 | OCC/OIC·Cboe·CME 달력/계약명세 | 거래소 이벤트 단위 | 공개 문서 | A | 상품별·휴장일 예외 |
| 미국 정책금리 | Fed/FRED DFEDTARL/DFEDTARU; DFF | 결정 이벤트/일별 | FRED 키 | A/B | 목표구간 상·하단과 실효치 분리 |
| 일본 금리 | BOJ 결정문 + BOJ 통계 API | 정책 이벤트/익일물 일별 | 공개 데이터 | A | BOJ 실효 overnight 값 ≠ 목표 |
| 영국 금리 | BoE Bank Rate IUDBEDR | 일별/결정 이벤트 | 공개 통계 | A | 이력 변경일 유지 |
| 유로존 금리 | ECB DFR (예금금리) SDMX | 일별/결정 이벤트 | 공개 API | A | **유로존** 값이지 EU 단일 정책금리 아님 |
| Bitcoin | Coinbase/Binance 공개 API, CoinGecko | 1분~일별 OHLCV·가격 | 무료 제한/유료 | A/B | 거래소·호가통화 구분, 24×7 |

## 2. 미국 주식 공포·탐욕지수 (Fear & Greed)

- **원지표:** [CNN Fear & Greed](https://www.cnn.com/markets/fear-and-greed); 보통 0~100 스코어이며 CNN 방식에 따른 합성 지표. CNN의 데이터 가공·지수 정의 변경 가능성에 유의한다.
- **접근:** CNN은 공개 문서화된 안정적 개발자 API를 제공하는 것으로 확인되지 않았다. 커뮤니티에서 사용하는 비공식 JSON 경로 `https://production.dataviz.cnn.io/index/fearandgreed/graphdata`는 **운영 필수 의존성으로 취급하지 말 것**. 파서 구현 사례: [cnn-fear-and-greed-parse](https://github.com/wildsurfer/cnn-fear-and-greed-parse).
- **법무/신뢰도:** 브라우저 접근 가능성과 데이터 수집·재배포 허가를 동일시하지 않는다. 비공식 호출이 차단되거나 스키마/원본이 바뀔 수 있다. 서비스 약관·지수 사용권 확인 전 데이터 적재 및 대외 제공 보류 권고.
- **대체:** 허용된 데이터 소스를 이용해 **Auto-Axe 자체 감성 복합지표** 구축(예: S&P500 125일 MA 이격, NYSE 52주 신고가/신저가, breadth, put/call, VIX, 고수익채 spread, 주식-국채 상대 수익률). 단순 가중합으로 CNN 원지표를 *복제한 것*처럼 표기하지 말고 독립 지표로 이름·방법론·버전을 기록한다.
- **저장:** `index_name`, `score`, `scale_min=0`, `scale_max=100`, `method_version`, `source`, `captured_at`, `as_of`, `license_status`, `confidence`. 히스토리 백필 불완전 가능성.

## 3. 기업 가이던스 및 시장 컨센서스

- **공식 무료 근거:** [SEC EDGAR API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
  - `https://data.sec.gov/submissions/CIK##########.json` (CIK **10자리 0 패딩**): 공시 목록·접수일·accession·문서 탐색.
  - `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`: 표준화된 **보고 재무실적** 수집. *미래 실적 가이던스 통합 필드가 아니다.*
  - 제출 원문 **8-K** 및 **Exhibit 99.1 (earnings release)**, 10-Q/10-K, 기업 IR 자료의 `guidance`, `outlook`, `expects`, `FY/Q revenue`, `EPS` 문구 파싱. 본문 HTML/첨부 PDF 또는 실적콜 transcript(상용 사용권 주의).
- **실적 가이던스:** 기업 경영진이 제시한 매출/EPS/마진/CapEx 전망. **컨센서스:** 증권사 애널리스트들의 예측치 집계. 동일하지 않음. 리비전, GAAP vs adjusted, EPS 희석 여부, 회계연도/분기, 통화·단위, 범위의 low/high/중앙값을 구별한다.
- **수집 운영:** 종목→CIK 매핑 → EDGAR filings 신규 등록 확인 → 액세션/문서/공시시각 저장 → 텍스트 파싱 → 구조화 → 원문 링크 및 발췌 범위 기록 → 사람/모델 검증. SEC 요청 제한 정책(통상 **초당 10회 이하**, 명시적 식별 **User-Agent**) 준수. [SEC Fair Access](https://www.sec.gov/about/developer-resources).
- **상용 대안:** LSEG I/B/E/S, FactSet, Bloomberg, S&P Capital IQ 등은 컨센서스와 상세 포워드 추정치를 제공할 수 있으나 **상품별 커버리지·API·라이선스 견적 확인 필요**. 무료 표준화 가이던스/컨센서스 전 종목 제공을 가정하지 않는다.
- **PIT 필수:** `guidance_issued_at`, `first_seen_at`, `fiscal_period`, `metric`, `gaap_basis`, `low/high`, `prior_value`, `source_document`, `extraction_version`; 해당 시점에 알려진 수치만 백테스트 입력한다.

## 4. 금값

- **무료 근사 현물가격:** [Gold API](https://gold-api.com/) `GET https://api.gold-api.com/price/XAU` (USD/troy oz 표시; API 응답의 통화와 단위를 반드시 점검). [FAQ](https://gold-api.com/faqs) 및 [이용약관](https://gold-api.com/terms) 참고. 공급원은 제3자 종합가격이며 **공식 LBMA Gold Price가 아니다**. 무료 현재가와 과거 OHLC·사용량 제한/상업 조항은 플랜별 재확인.
- **월별 공공 데이터:** [World Bank Commodity Markets (Pink Sheet)](https://www.worldbank.org/en/research/commodity-markets) 금 월간 가격 다운로드. 장기 거시지표에 적합하나 일중 매매 신호에 부적절.
- **국제 벤치마크:** [LBMA Gold Price](https://www.lbma.org.uk/prices-and-data/precious-metal-prices) (London 10:30, 15:00의 경매 참조가격). 운영·재배포에는 ICE Benchmark Administration 등 권리자의 허가/라이선스가 필요할 수 있다. [과거 표 Members Portal 이동 공지](https://www.lbma.org.uk/articles/lbma-benchmark-prices-data-tables-are-moving).
- **구별:** XAU/USD OTC spot, LBMA AM/PM, COMEX GC 선물은 다른 series. `instrument_type`, `currency`, `unit=USD/troy_oz`, `market_timezone`, `price_type` 저장.

## 5. 국제유가: WTI / Brent / Dubai

### WTI·Brent 현물 일별

- **공식 EIA** [Open Data API](https://www.eia.gov/opendata/documentation.php), [현물 시계열 페이지](https://www.eia.gov/dnav/pet/pet_pri_spt_s1_d.htm)
  - WTI Cushing: series `PET.RWTC.D`, 예시 `GET https://api.eia.gov/v2/seriesid/PET.RWTC.D?api_key=YOUR_EIA_KEY`
  - Brent: series `PET.RBRTE.D`, 예시 `GET https://api.eia.gov/v2/seriesid/PET.RBRTE.D?api_key=YOUR_EIA_KEY`
  - 요청 전 EIA API 버전·응답 JSON 구조·정식 갱신 주기를 실제 점검한다. 일반 단위 USD/barrel, 거래일 일별 관측.
- **FRED 재배포:** [DCOILWTICO](https://fred.stlouisfed.org/series/DCOILWTICO), [DCOILBRENTE](https://fred.stlouisfed.org/series/DCOILBRENTE). API 접근법은 아래 국채 섹션 참조. 소스 provenance로 EIA/FRED를 모두 저장한다.

### Dubai (주로 Dubai Fateh)

- **IMF 기반 공개 월간:** [FRED `POILDUBUSDM`](https://fred.stlouisfed.org/series/POILDUBUSDM), 일반적으로 USD/barrel **월평균**; [World Bank Pink Sheet](https://www.worldbank.org/en/research/commodity-markets)도 월간 참조.
- **일별/근실시간 필요 시:** Platts, Argus, ICE/거래소 또는 라이선스 공급원 견적·상품 정의 확인. Dubai 현물 평가가격과 Oman/Dubai 파생상품을 동일하게 간주하지 않는다.
- **데이터 검증:** `grade=WTI_CUSHING|BRENT|DUBAI`, `assessment_method`, `spot_or_futures`, `period=daily|monthly`, `currency=USD`, `unit=bbl`. **Dubai 월평균을 일별 WTI/Brent와 forward fill 해 동시 발표된 일별 신호처럼 쓰지 않는다.**

## 6. VIX (미국 변동성지수)

- **Cboe 공식** [Historical VIX](https://www.cboe.com/tradable_products/vix/vix_historical_data): 일별 **Open/High/Low/Close** CSV `https://cdn-api.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv`. CDN 주소 변경 가능하므로 공식 랜딩 페이지를 정기 기준점으로 삼는다.
- **실시간:** [Cboe Global Indices Feed](https://www.cboe.com/data/global-indices-feed) 등 계약형 시장데이터. 사이트 내 실시간 숫자 표시가 API의 무단 재배포 허가를 뜻하지 않는다.
- **주의:** VIX 지수 레벨(연율화 기대 변동성 %)과 VX 선물 가격, 옵션 내재변동성·실현변동성, VIX9D/VIX3M을 구분. EOD 거래일 기준.

## 7. 미국 국채

- **미국 재무부 원본:** [Daily Treasury Par Yield Curve](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics) 및 [Interest Rates Data CSV Archive](https://home.treasury.gov/interest-rates-data-csv-archive/). 만기별 1M~30Y 시장 **파 수익률**(%)을 날짜별 수집. 2026년 일별 CSV 예시: `https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/2026/all?type=daily_treasury_yield_curve` — 배포 구조 변경 가능, 실제 응답 검증 후 사용.
- **FRED 사용 편의:** [DGS2](https://fred.stlouisfed.org/series/DGS2) (2Y), [DGS10](https://fred.stlouisfed.org/series/DGS10) (10Y), [DGS30](https://fred.stlouisfed.org/series/DGS30) (30Y), [DFII10](https://fred.stlouisfed.org/series/DFII10) (10Y TIPS 실질금리), [T10Y2Y](https://fred.stlouisfed.org/series/T10Y2Y) (10Y-2Y 스프레드).
  - 예: `GET https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&api_key=YOUR_FRED_KEY&file_type=json`
  - [FRED series/observations 공식 문서](https://fred.stlouisfed.org/docs/api/fred/series_observations.html).
- **주의:** Treasury par-yield curve는 개별 CUSIP 채권 실거래가격이 아니다. [FiscalData Average Interest Rates](https://fiscaldata.treasury.gov/api-documentation/)는 정부 전체 국채 잔액 **평균 지불금리**로서 DGS10 같은 시장 수익률과 다름. 직접 채권가격·호가·거래량은 FINRA/거래소/벤더 상품별 확인.

## 8. 피자지수 (Pentagon Pizza Index / PizzINT)

- **관찰용:** [pentagon.pizza](https://www.pentagon.pizza/)와 피자 배달·주변 음식점 혼잡을 기반으로 한 PizzINT 개념. 소셜미디어·언론에 자주 등장하나 표준화된 공식 거시경제 지표도 검증된 이벤트 예측기계도 아니다.
- **중요한 기술적 한계:** Google Places UI Kit의 `gmp-place-popular-times`는 UI 컴포넌트이지 공식 구조화 **수치 추출 REST API가 아니다**. [Places UI Kit](https://developers.google.com/maps/documentation/javascript/places-ui-kit/place-details), [Google Places 서비스 정책](https://developers.google.com/maps/documentation/places/web-service/policies). Google Maps 혼잡도/Popular Times를 스크레이핑·저장·재배포하는 방식은 정책 위반 위험이 높다.
- **권고:** Auto-Axe에는 **참조 링크/외부 페이지 표시 수준**, 또는 제공자와 명시적 데이터 이용 계약 후 수집기 구현. 임의 HTML/Maps 역공학 추출을 정식 수집 경로로 설계하지 말 것.
- **연구형 자체 지표를 만들 경우:** 원천 관측에 합법적 접근이 가능할 때만 장소별 기준시간대, 평시 평균 대비 이상치, 관측 편향, 지연과 허위양성 검증. 정치·안보 사건과의 단순 상관관계를 인과·예측력으로 표시하지 않는다.

## 9. 금리 및 주요 경제지표 발표일정

- **미국 BLS:** 공식 [Release Calendar](https://www.bls.gov/schedule/news_release/) 및 iCalendar `https://www.bls.gov/schedule/news_release/bls.ics`. CPI, 고용보고서(NFP), PPI 등 이벤트 종목명/현지 발표 예정 일시 추출.
- **미국 BEA:** [발표 일정](https://www.bea.gov/news/schedule) — GDP, PCE 개인소비지출·물가, personal income/outlays.
- **미국 Census:** [Economic Indicators calendar](https://www.census.gov/economic-indicators/) — 소매판매, 내구재 주문 등; 연도별 캘린더 경로가 변경될 수 있음.
- **Fed FOMC:** [FOMC meeting calendars](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm). 회의 시작·종료일, 금리 결정·성명 예정 발표시각·의사록과 기자회견은 서로 별도 이벤트.
- **향후 확장:** 일본 BOJ / 영국 BoE MPC / ECB 통화정책 일정, ISM·ADP(민간 및 라이선스 가능), 증권거래소 휴장 캘린더.
- **수집:** ICS는 `UID`/`DTSTART`/`SUMMARY`/`LAST-MODIFIED`/취소 상태를 유지하고 변경 감시. HTML은 확정 URL + 공지 수정 추적. **시간대는 America/New_York (EST/EDT 자동 전환)**에서 UTC로 저장하여 Asia/Seoul UI에 표기.
- **일정과 발표값 분리:** `scheduled_at` != `released_at`; 결과값 수집은 각 통계기관 API 별도 연결. 컨센서스 `forecast`, 최초 발표 `actual_first`, 수정된 최신치 `actual_revised`, `previous` 구분. 예정표가 곧 지표 수치 데이터가 아님.

## 10. 파생상품 만기일 (미국 주식·지수 옵션 / 지수선물)

- **OCC/OIC:** [Options Expiration Calendar](https://www.optionseducation.org/referencelibrary/expiration-calendar), 거래소별 정기·주간·월간·분기 만기와 휴장 예외.
- **Cboe:** [Options Calendar and product specifications](https://www.cboe.com/tradable_products/) — SPX AM/PM 결제, VIX 옵션 등 상품별 최종거래·결제 스케줄이 다른 점 필수 검증.
- **CME:** [Micro E-mini expiration](https://www.cmegroup.com/education/courses/micro-e-mini-futures/managing-micro-e-mini-futures-expiration) 및 CME 개별 Contract Specs/Product Calendar. ES/MES, NQ/MNQ 등 분기 만기는 계약별 마지막 거래시각·현금결제 규칙 확인.
- **대표 분기 셋째 금요일(2026):** 3/20, 6/19, 9/18, 12/18. 다만 **2026-06-19 미국 Juneteenth 휴일**이라 옵션의 실제 거래·만기처리·결제 일정은 OCC/Cboe 공식 일정이 우선이다. 일반 달력 계산값만으로 거래 가능성을 판단하지 말 것.
- **운영 데이터 모델:** `exchange`, `root_symbol`, `contract_id`, `expiry_date`, `last_trade_at`, `settlement_at`, `settlement_type`, `exercise_style`, `am_pm`, `holiday_override`. '네 마녀의 날'은 시장 설명용 레이블일 뿐 개별 상품 만기 정답 데이터가 아니다.

## 11. 기준금리 — 미국·일본·영국·유로존

| 지역/기관 | 공식/중개 시계열과 접근법 | 무엇을 뜻하는가 | 주의 |
|---|---|---|---|
| 미국 Fed | FRED [DFEDTARL](https://fred.stlouisfed.org/series/DFEDTARL), [DFEDTARU](https://fred.stlouisfed.org/series/DFEDTARU), [DFF](https://fred.stlouisfed.org/series/DFF); FOMC 성명 | 연방기금금리 **목표 범위 하단/상단**, 실제 **실효금리** | 세 수치는 다름 |
| 일본 BOJ | [Time Series Data Search / API](https://www.stat-search.boj.or.jp/), [영문 API 매뉴얼](https://www.stat-search.boj.or.jp/info/api_manual_en.pdf) + BOJ 통화정책 결정문 | 익일 무담보 콜금리의 실효치 및 별도 정책 목표 | 익일물 실현금리=정책목표로 단정 금지 |
| 영국 BoE | [BoE Statistical Interactive Database](https://www.bankofengland.co.uk/boeapps/database/Bank-Rate.asp), **IUDBEDR**(일별), IUMBEDR(월말), IUMABEDR(월평균) | Bank Rate | 일별·월간 시리즈 혼동 금지 |
| 유로존 ECB | [ECB SDMX API](https://data.ecb.europa.eu/help/api/data), DFR `FM.D.U2.EUR.4F.KR.DFR.LEV` | 예금금리(Deposit Facility Rate) | EU 전체를 대표하는 단일 금리가 아님 |

- **미국 FRED 호출 예:** `GET https://api.stlouisfed.org/fred/series/observations?series_id=DFEDTARU&api_key=YOUR_FRED_KEY&file_type=json`
- **일본 BOJ 호출 예 (실효 콜금리):** `GET https://www.stat-search.boj.or.jp/api/v1/getDataCode?format=json&lang=en&db=FM01&code=STRDCLUCON,STRDCLUCONH,STRDCLUCONL&startDate=202501` (API 매뉴얼에 따라 코드·기간을 검증). **목표금리는 별도 정책 결정문에서 이벤트 추출**.
- **ECB API 호출 예:** `GET https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.DFR.LEV?lastNObservations=5&format=csvdata` ([시계열 설명](https://data.ecb.europa.eu/data/datasets/FM/FM.D.U2.EUR.4F.KR.DFR.LEV)).
- **필드:** `jurisdiction`, `bank`, `rate_type=target_lower|target_upper|effective|deposit_facility|bank_rate`, `rate_pct`, `valid_from`, `announced_at`, `effective_date`; 각국 정책회의 일정은 9절 경제달력에 통합한다.
- **EU 표현:** ECB는 **유로존 21개국(불가리아 2026-01-01 가입; [ECB 공식 발표](https://www.ecb.europa.eu/press/pr/date/2026/html/ecb.pr260101~c830245e42.en.html))**의 통화정책을 담당. 비유로 EU 회원국에는 별도 중앙은행 정책금리가 존재할 수 있다. 국가별 EU 전체 비교는 범위를 명시.

## 12. 비트코인

- **거래소 현물 (1차 후보):** Coinbase Exchange Public API: [공식 API 문서](https://docs.cdp.coinbase.com/exchange/reference/exchangerestapi_getproductcandles), 예시 `GET https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=3600`; `GET https://api.exchange.coinbase.com/products/BTC-USD/ticker`. 무인증 공개 경로는 호출 제한, 캔들 수 제한, 누락 구간/과거 조회 범위 및 지역 접근성을 테스트해야 함.
- **대체 거래소:** [Binance Spot REST](https://developers.binance.com/en/docs/products/spot/rest-api) `GET https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=500` 및 `/api/v3/ticker/price?symbol=BTCUSDT`. BTC**USDT**와 BTC**USD**는 다른 호가통화. 공개 경로 지역·정책 제한 가능.
- **집계/기준가격:** [CoinGecko API](https://www.coingecko.com/en/api), 예 `https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=30`, `/coins/bitcoin/ohlc?vs_currency=usd&days=30`. 무료 역사·OHLC 범위, granularity, 인증, 호출량 및 상업적 재사용은 당시 플랜 기준 확인.
- **저장:** `venue`, `symbol`, `base=BTC`, `quote=USD|USDT|KRW`, `bar_open_at`, `bar_close_at`, `open/high/low/close`, `volume_base`, `volume_quote`, `is_closed`. **24시간 365일 UTC** 캔들과 NYSE 거래일 캘린더를 같은 기준으로 자르지 않는다.

## 13. 공급자 선택 기준과 최소 검증

**권장 1순위:** 발행기관/거래소 공식 API → 공식 CSV/ICS → FRED 등 출처가 명시된 중개 채널 → 권리 정리가 된 상용 마켓데이터 → 비공식/웹 추출 실험 채널.

1. **정합성**: 실제 sample 응답 3건 이상, 빈 값·정정·휴장·DST·법정휴일·분기 특수일 검사.
2. **시의성**: source `observation_date`, `published_at`, `ingested_at`, `revision_at` 개별 기록.
3. **비용/법무**: 개발자 키, 무료 티어 제한, 상업 이용·캐시·가공·재배포 가능 여부 별도 기록. 화면 접근만으로 API 재배포 허가를 추론하지 않음.
4. **백테스트**: revised/latest 값으로 과거 신호를 역산하지 말고 당시 실제 이용 가능했던 **point-in-time** 관측·가이던스·일정을 저장.
5. **실서비스**: 비공식 CNN/pizza 수집이 실패해도 가격·이벤트 파이프라인과 주문 엔진은 계속 동작하도록 격리.

추가 구현 명세는 [Collector_Design.md](./Collector_Design.md) 참조.
