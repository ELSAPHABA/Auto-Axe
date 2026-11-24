# Auto-Axe 무료 데이터 수집 명세

> 기준일: 2026-11-24. 유료 데이터 피드는 제외한다. 이 문서는 현재 적용할 지표별 수집 정책을 정의하며, 구현 여부·검증 결과·권한 상태는 각각 구분한다.

## 1. 공통 수집 정책

- 무료 공식 API, WebSocket, 다운로드 파일(RSS/Atom/ICS/CSV/JSON)을 우선한다. 무료 API 키가 필요한 경우도 포함하되 데이터 이용권을 별도로 확인한다.
- `API` / `WEBSOCKET`: 문서화된 API·공개 스트림. `SCRAPE`: 제공자가 자동 수집·저장·활용을 허용하는 경우에만 공개 HTML을 파싱. `MANUAL`: 자동 수집이 불가능하거나 허가되지 않은 경우 허용된 범위에서 수동 입력. `DERIVED`: 확보한 원본 데이터로 로컬 계산.
- 데이터 주기는 `LIVE`(거래 등 발생 시 푸시), `NEAR`(지연·캐시 가능한 최신 스냅샷), `EVENT`(공시·발표), `EOD`(일별), `WEEKLY`(주간), `MONTHLY`(월별)로 구분한다. 조회 빈도와 원본 갱신 주기는 다르다.
- 무료 열람과 자동 수집·영구 저장·재배포 권한은 별개다. 권한 미확인 소스는 `permission_required`로 관리하고 기본 비활성화한다. 로그인·CAPTCHA·접근 제한 우회, 비공개 API 역공학, 차단 회피용 프록시 회전은 하지 않는다.
- 동일 정의의 데이터에만 대체 출처를 적용한다. 현물·선물·영구선물, 호가통화, 지수·ETF, 발표값·수정값은 별도 시계열로 저장한다. 지연 데이터를 반복 조회해 실시간 관측으로 표기하지 않는다.
- 원본 기준시각, 수집시각, 출처, 갱신주기, 품질·권한 상태를 기록한다. 데이터 미수집·누락은 0으로 채우지 않는다.
- [현재 시장 소스 정책](./Market_Source_Policy_20261123.md) · [수집기 아키텍처](./Collector_Design.md) · [지표별 출처 목록](./Indicator_Data_Sources.md)

## 2. 시장 가격 및 거래 통계

### 2.1 원자재·암호화폐·나스닥 100

| 지표 | 우선 수집 출처·방법 | 대안 및 보조 경로 | 수동·결측 처리 | 빈도 및 주의사항 |
|---|---|---|---|---|
| 금 가격 동향 | **Binance Futures `XAUUSDT` 영구선물 실시간 WS** | Gold API 현물 추정은 별도 참고 | 장애·장시간 제약 시 결측/수동 | Binance 금 연동 영구선물은 현물 XAU/USD·COMEX `GC=F`와 별개 |
| 은 가격 동향 | **Binance Futures `XAGUSDT` 실시간 WS** | Spot silver 원본은 별도 | 시세 불가 시 결측·수동 | 은 연동 영구선물, 현물/COMEX 선물 아님 |
| 구리 가격 동향 | **Binance Futures `COPPERUSDT` 실시간 WS** | Spot copper 원본은 별도 | 시세 불가 시 결측·수동 | 구리 연동 영구선물, 현물/COMEX 선물 아님 |
| WTI 가격 동향 | **Binance Futures `CLUSDT` 영구선물 실시간 WS** | EIA `PET.RWTC.D` (일별 현물 참고) | 서비스 장애 시 결측·수동 | Binance 영구선물과 NYMEX `CL=F` 선물은 다름 |
| Brent 가격 동향 | **Binance Futures `BZUSDT` 영구선물 실시간 WS** | EIA `PET.RBRTE.D` (일별 현물 참고) | 서비스 장애 시 결측·수동 | Binance 영구선물과 NYMEX `BZ=F` 선물은 다름 |
| 비트코인 | **Binance Spot `BTCUSDT` 무료 WS 실시간 체결** | Coinbase `BTC-USD` 공개 WS (별도 호가/거래소) | 장애 시 수동 | BTC/USDT와 BTC/USD, Yahoo 집계 시세는 별도 시계열 |
| 나스닥 100 선물·연동 신호 | **MEXC NAS100_USDT 공개 Futures WS/REST** (실시간 저지연 후보, 실제 메시지 검증 전) | Binance QQQUSDT 영구선물(다른 기초상품), Yahoo `NQ=F` 1분봉(실제 CME NQ이나 지연 시세) | 공식 CME 실시간 데이터는 권한/비용 필요; 무료 시 지연 비교 데이터 사용 | **MEXC Protobuf WS 전환 2026-12-01**, 심볼/시간/지연 테스트 필요. 지수 연동 영구선물과 NQ 실제 선물 혼동 금지. [명세](./Nasdaq100_Futures_Data_Sources.md) |
| Binance 롱숏·Taker 통계 4종 | Binance Futures 공개 REST `/futures/data/*` | 동일 정의의 허용 출처만 대체 | 결측 처리 | 5분 이상 집계; 6개 선물 심볼, 총 24개 시계열. [상세](./Binance_Metals_LongShort_20261123.md) |

**Binance 원자재 가격**

- 기본 소스는 금 `XAUUSDT`, 은 `XAGUSDT`, 구리 `COPPERUSDT`, WTI `CLUSDT`, Brent `BZUSDT`의 TradFi USDT 영구선물 `@aggTrade` 스트림이다. 거래 발생 시 갱신되며 거래시간 밖에는 새 체결이 없을 수 있다.
- 은·구리의 계약 상태 `TRADING / TRADIFI_PERPETUAL` 및 REST 1분봉 지원을 실측 확인했다. 내부 ID는 `SILVER_BINANCE_PERP`, `COPPER_BINANCE_PERP`. 원자재 현물 또는 COMEX/NYMEX/ICE 만기선물과 혼합하지 않는다.
- 금 현물 추정 참고값은 [Gold API](https://gold-api.com/docs)의 `gold-spot-reference`로 별도 수집한다.
- EIA 무료 API 키: `https://api.eia.gov/v2/seriesid/PET.RWTC.D?api_key=YOUR_KEY` 및 `.../PET.RBRTE.D` — **WTI/Brent 일별 현물**; 갱신이 완료된 일별값만 사용.
- 특정 거래소/시세 사이트의 브라우저 화면은 장중 참고할 수 있어도 무료 **기계적 수집 허용**이 확인되지 않으면 자동 크롤러를 만들지 않는다. 공식 보고서 파일만 허용 범위에서 다운받는다.
- 장중 관측이 꼭 필요한 경우 `value_source=manual`, `source_market=spot|futures`, `exchange`, `contract_month`, `delayed_minutes`(표시된 경우)을 입력. **일별 현물 vs 월별 평가 vs 장중 선물 차이**를 반드시 분리.

**비트코인**

- **기본 거래 시세:** Binance Spot `BTCUSDT@trade` WebSocket. Coinbase `BTC-USD`는 거래소와 호가통화가 다른 보조 무료 체결 스트림이다. Yahoo `BTC-USD`를 기본 수집하지 않는다.

- [Coinbase 거래 체결/호가 WS](https://docs.cdp.coinbase.com/exchange/websocket-feed/overview): `wss://ws-feed.exchange.coinbase.com` 구독 `{"type":"subscribe","product_ids":["BTC-USD"],"channels":["ticker","heartbeat"]}` (무키).
- [Binance market-data-only WS](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md): `wss://data-stream.binance.vision/stream?streams=btcusdt@trade/btcusdt@kline_1m`, trade 실시간, `k.x=true` 마감 1분봉. 연결 시간/핑·퐁/호가통화/지역제한 준수.
- USD / USDT를 같은 자산 가격처럼 합치지 않는다. 24x7 UTC 시간축 사용.

**Binance 거래 통계**

- **공식 롱숏 비율 4종:** 전체 계정, 상위 계정, 상위 포지션, Taker 매수·매도 거래량 비율. Binance `/futures/data/*` 무료 공개 REST의 **최소 5분 집계**로 수집한다. 실시간 WS 틱이 아니며, Taker 매수·매도 비율은 포지션 롱숏 비율과 다르다.
- `python docs/examples/realtime_collector.py binance-live`: BTC Spot + 금·은·구리·WTI·Brent 5개 영구선물.
- `python docs/examples/realtime_collector.py binance-longshort --ratio-period 5m --interval 300`: 6개 Binance 선물 심볼의 롱숏·Taker 통계 5분 간격 조회.
- [상세 응답 검증과 API 구분](./Binance_Metals_LongShort_20261123.md) · [Python 수집기](../examples/realtime_collector.py).

**나스닥 100**

MEXC `NAS100_USDT`는 지수 연동 영구선물이며 실시간 수신·지연은 아직 검증하지 않았다. 2026-12-01 Protobuf WebSocket 전환에 맞춰 사양을 확인한다. Binance `QQQUSDT`는 ETF 연동 별도 계약, yfinance `NQ=F`는 실제 CME 선물의 지연 1분봉 비교용이다. [상세 명세](./Nasdaq100_Futures_Data_Sources.md).

### 2.2 변동성 및 미국 국채 수익률

| 지표 | 우선 수집 출처·방법 | 대안 및 보조 경로 | 수동·결측 처리 | 빈도 및 주의사항 |
|---|---|---|---|---|
| VIX | **yfinance `^VIX`** (우선) / Cboe 무료 일별 CSV 검증 | Cboe Quote Dashboard 자동 추출 금지 | 데이터 권한·지연 문제 시 장중 수동 | **yfinance 분봉 수신 검증, 무지연 보장 없음** |
| 미국 국채 금리 3M·2Y·5Y·10Y·30Y | **3M/5Y/10Y/30Y: yfinance `^IRX/^FVX/^TNX/^TYX`; 2Y: 네이버 `US2YT=RR` (승인 시)** | 네이버 robots 차단으로 무허가 시 [Treasury 공식 XML `BC_2YEAR`](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed) 일별 대체 | 2Y 일중값 수동 기록 | Yahoo 지표·네이버 게시 수익률·Treasury 일별값을 별도 표기 |

- **기본:** VIX `yfinance ^VIX`, 국채 3M `^IRX`, 5Y `^FVX`, 10Y `^TNX`, 30Y `^TYX`. **2Y 지정 출처:** [네이버 `US2YT=RR`](https://m.stock.naver.com/marketindex/bond/US2YT=RR). 실측 JSON의 `closePrice`·`localTradedAt`는 확인했으나 `robots.txt` 전체 차단으로 무허가 스크래핑은 비활성화. 허가 전에는 Treasury `BC_2YEAR` 공식 일별값 사용. [최신 정책](./Market_Source_Policy_20261123.md).

- VIX [Cboe 공식 EOD CSV](https://www.cboe.com/tradable_products/vix/vix_historical_data): `https://cdn-api.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv`. 시장 운영시간의 실제 스트리밍이 아니다. Cboe Quotes Dashboard에 명시된 **자동화 추출 금지**를 준수한다.
- Treasury [일별 공식 파 수익률](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics), [XML 제공 안내](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed): 2Y/10Y 등 단위 `percent`. [FRED DGS2/DGS10](https://fred.stlouisfed.org/series/DGS10)은 무료 개인 조회 참고만. 국채 현물 수익률과 국채 선물 가격은 전혀 다른 값.
- VIX 및 3M/5Y/10Y/30Y yfinance 분봉은 무지연 실시간 수익률이 아님. 2Y는 네이버 자동수집 허가 전까지 Treasury 공식 일별만 사용한다.
- **FRED 주의:** API 이용약관은 별도의 무허가 데이터 저장/캐싱/DB 편입 및 AI 개발/학습 관련 제한을 명시한다. Auto-Axe의 영속 DB에 FRED 반환값을 무조건 적재하지 말 것. [FRED 이용약관](https://fred.stlouisfed.org/legal/terms/). 가능한 경우 데이터 원 발행기관(EIA/Treasury/BOJ/ECB)의 허용된 공개 다운로드로 대체한다.

**yfinance 검증 범위:** [YFinance_Data_Validation.md](./YFinance_Data_Validation.md) 참고. 2026-11-22 `^VIX`, `^TNX`, `CL=F`, `BZ=F`의 일봉·1분봉 수신을 확인했으나 **2026-11-23부터 원유·금·BTC의 기본 가격은 Binance로 전환**했다.

## 3. 미국 주식·ETF 지표

| 지표 | 우선 수집 출처·방법 | 대안 및 보조 경로 | 수동·결측 처리 | 빈도 및 주의사항 |
|---|---|---|---|---|
| 미국 주식·ETF 1초 주기 누적 거래량 | **yfinance `AsyncWebSocket` → `day_volume`** (NVDA·QLD 등) | 이벤트별 원본 갱신 후 로컬 1Hz 스냅샷; 별도 공식 무지연 SIP 권한 미확인 | Yahoo 메시지 지연/라이선스 문제 시 미수집·수동 검증 | **로컬 1초 기록만 보장, Yahoo 1초 WS 업데이트·무지연·체결별 거래량은 미보장.** [기술 명세](./YFinance_1s_Stock_Cumulative_Volume.md) |
| 미국 개별주식 PER·PBR·ROE | **yfinance `Ticker.info`: `trailingPE`/`forwardPE`/`priceToBook`/`returnOnEquity`** | 공개 기업 재무제표와 해당 시점 주가로 직접 재산출·검증 가능 | 수집 제한/결측 시 원자료 확인 | 원본 ROE는 ratio, forward PER은 예상 EPS 기반. ETF QLD를 기업 지표로 혼용하지 않음. [설계](./YFinance_Valuation_and_Moving_Averages.md) |
| 이동평균선(SMA·EMA) | **yfinance `Ticker.history`의 OHLCV** | SMA/EMA 직접 계산 (5·20·60·120·200일 등) | 봉 또는 가격 원본 부재 시 결측 | 종가 기준·배당/분할 조정·확정봉/진행봉을 구별. [설계](./YFinance_Valuation_and_Moving_Averages.md) |
| 최근 5·10·20거래일 최고·최저가 (미국 주식·ETF) | **yfinance 일봉 `High`/`Low` → rolling max/min 로컬 계산** | 주말·휴장일 제외한 실제 거래일 N개 기준, 일봉 확정 후 저장 | 일봉 미확정·누락 시 결측 처리 | **총 6개 지표** (`HIGH/LOW_5D/10D/20D`). 장중 돌파는 전일 이전 N개 확정봉 기준. [산출 명세](./YFinance_Valuation_and_Moving_Averages.md) |
| 해외주식 매수·매도 결제 통계 (서학개미 동향) | **[한국예탁결제원 SEIBro 종목별내역(주식TOP50)](https://seibro.or.kr/websquare/control.jsp?w2xPath=/IPORTAL/user/ovsSec/BIP_CNTS10013V.xml&menuNo=921)**; 화면 로더·XML 확인, 공식 공개 자동 API 미확인 | WebSquare UI의 기간·국가·매수/매도/순매수 결제금액 **허가된 스크래핑 예정**; 권리 검토 전 비활성 | **SEIBro 화면 수동 기록** | **결제 기준, TOP50, USD; 실시간 체결·개인계정 원장 아님**. [필드·제약](./SEIBro_Overseas_Stock_Flows.md) |
| 기업 실적 가이던스 | **SEC EDGAR** submissions JSON + 8-K Atom/RSS, 문서/Exhibit 원문 | 회사 공식 IR 보도자료 및 허용된 HTML, RSS 없는 경우 | PDF·콜에서 매출/EPS 전망을 근거 링크와 함께 입력 | `EVENT`: 신규 공시/보도자료 |

### 3.1 누적 거래량

yfinance WebSocket `day_volume` 수신값을 캐시하고 로컬 스케줄러가 매초 스냅샷을 기록한다. 새 메시지가 없으면 직전 원본 시각을 유지하고 `no_update/stale` 상태를 표시한다. 실제 종목의 WS 수신 빈도와 지연은 미검증이며, 통합시장 초당 체결량과 다르다. [1초 수집 상세](./YFinance_1s_Stock_Cumulative_Volume.md).

### 3.2 기업 재무지표 및 기술지표

- PER 후행/예상, PBR은 일별 조회를 기본으로 하고 ROE는 실적 공시 후 갱신한다. ETF와 일반 기업의 재무지표 정의를 구분한다.
- SMA·EMA는 가격 이력에서 직접 계산한다. SMA 5·20·60·120·200일, EMA 12·26일 등 설정 가능한 윈도우를 사용한다.
- 최근 5·10·20거래일의 `High` 최댓값과 `Low` 최솟값을 각각 산출한다. 확정 일봉 기준, 장중 돌파에는 직전 N개 완료 일봉만 사용한다.
- 배당·분할 조정, 확정봉, 거래소 휴장, 워밍업 결측 및 재무제표 공개 시점을 보존한다. 현재 재무값을 과거 백테스트에 소급 적용하지 않는다.
- [계산식·Python 예제 및 저장 스키마](./YFinance_Valuation_and_Moving_Averages.md).

### 3.3 해외주식 결제 통계

SEIBro의 국가·조회기간별 해외주식 TOP50 매수·매도·순매수 결제금액(USD)을 수집한다. 화면 로더와 XML은 확인했으나 공식 공개 자동 API는 확인되지 않았으며 WebSquare 스크래핑은 권한 확인 후 구현한다. 체결량, 전체 해외주식 합계, 개인계좌 거래 원장과 구분한다. [상세 명세](./SEIBro_Overseas_Stock_Flows.md).

### 3.4 기업 실적 가이던스

- 회사 CIK(10자리 padding) → `https://data.sec.gov/submissions/CIK0000320193.json` 같은 공식 [SEC API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces).
- 신규 공시 Atom `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&company=&dateb=&owner=exclude&count=100&output=atom` 또는 기업별 IR RSS / 뉴스.
- 공시에서 `8-K Item 2.02`와 첨부 `Exhibit 99.1` 찾기 → `revenue`, `EPS`, `margin`, `outlook`, `guidance` → `Q/FY`, `GAAP/adjusted`, `low/high`, `issued_at` 구조화.
- 실제 게시 순서가 **회사 IR → SEC 제출**일 수 있으므로 핵심 종목의 공시 외에 **자사 IR 보도자료** 허용 HTML/JSON/XML/보도자료 RSS 수집기를 추가. 공시가 늦으면 시차 기록.
- SEC 식별 가능한 User-Agent + 합산 초당 10요청 이하 + 429 존중 ([SEC Fair Access](https://www.sec.gov/about/developer-resources)). 원문/첨부 경로, 최초 조회시각 저장.
- **애널리스트 컨센서스 = 회사 가이던스가 아님.** 무료 소스로 완전한 종목별 컨센서스 숫자 자동화가 확인되지 않으면 `manual`로 입력, 확인 출처/관측시점 명시.

## 4. 경제·정책·파생상품 일정

### 4.1 경제지표 일정과 실제 발표값

| 지표 | 우선 수집 출처·방법 | 대안 및 보조 경로 | 수동·결측 처리 | 빈도 및 주의사항 |
|---|---|---|---|---|
| 미국 지표·금리 발표 일정 | [BLS 일정 ICS](https://www.bls.gov/schedule/news_release/bls.ics), FOMC 일정, BEA 발표 일정 | BEA/FOMC/Census 등 공식 HTML/RSS/ICS | 일정 변경·공식 문서 PDF를 수동 입력 | `EVENT`: 공고 즉시 또는 변경시 |
| 미국 지표 실제 발표값 | [BLS v2 API](https://www.bls.gov/developers/api_signature_v2.htm), BEA API, Census API | BLS [CPI 보도자료](https://www.bls.gov/news.release/cpi.htm), [고용보고서](https://www.bls.gov/news.release/empsit.htm), BEA 공식 발표 HTML (허용 범위) | 원문 확인 후 수치·최초 발표·수정여부 수동 입력 | `EVENT`; API가 원문보다 늦을 수 있음 |

- 일정: [BLS 공식 ICS](https://www.bls.gov/schedule/news_release/bls.ics) (CPI/NFP/PPI), [BEA 일정](https://www.bea.gov/news/schedule) (GDP/PCE), [Fed FOMC 일정](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm), [Census 일정](https://www.census.gov/economic-indicators/). ICS 공식 다운로드 → HTML/RSS 허용 파싱 → 수동 순.
- 실제 수치: BLS `POST https://api.bls.gov/publicAPI/v2/timeseries/data/` 예 `CUUR0000SA0`(CPI-U), `CES0000000001`(취업자), `LNS14000000`(실업률). [BLS API FAQ](https://www.bls.gov/developers/api_faqs.htm): 미등록/등록 일일 요청 제한 준수. [BLS CPI release](https://www.bls.gov/news.release/cpi.htm) 보도자료는 API 반영 전 원문 확인 가능하지만 페이지의 차기 값 갱신을 무조건 단정하지 않는다.
- BEA 무료 데이터 API [개발자 페이지](https://www.bea.gov/resources/for-developers), CPI와 PCE는 서로 다른 지표; BEA GDP·PCE 원문 공개 페이지 허용 크롤링. `forecast`(컨센서스)는 공공기관 발표 자료에서 대체로 제공하지 않으므로 **검증된 무료 표준값 부재 시 `manual`**.
- `scheduled_at`(예정), `released_at`(공개), `first_seen_at`(수신), `period`(대상월/분기), `actual_first`, `revised`, `previous`, `consensus_if_available` 분리. 미국 동부 시간대 DST 적용.

### 4.2 중앙은행 정책금리

| 지표 | 우선 수집 출처·방법 | 대안 및 보조 경로 | 수동·결측 처리 | 빈도 및 주의사항 |
|---|---|---|---|---|
| 미국 기준금리 | Fed [FOMC 공식 결정](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm), [FRED DFEDTARL/U](https://fred.stlouisfed.org/docs/api/fred/) 개인 조회 | FOMC 공개 보도자료 HTML (허용 시) | 공식 결정 성명 및 발효일 기록 | `EVENT`, 후행 공식 시계열 |
| 일본 기준금리 | [BOJ 무료 2026 통계 API](https://www.stat-search.boj.or.jp/info/api_manual_en.pdf) 실효콜금리 + 정책 결정문 | [BOJ 통화정책 성명](https://www.boj.or.jp/en/mopo/mpmdeci/) 공개 HTML/PDF (허용 시) | PDF 성명 정책 목표금리 수동 확인 | `EVENT` 목표치 / 통계는 일별 실효치 |
| 영국 기준금리 | [BoE 공개 Bank Rate CSV](https://www.bankofengland.co.uk/boeapps/database/Bank-Rate.asp) `IUDBEDR` | BoE 공식 MPC 성명 HTML (허용 시) | 정책 결정·발효시점 확인 | `EVENT` / 일별 Bank Rate |
| 유로존(ECB) 기준금리 | [ECB SDMX 공개 API](https://data.ecb.europa.eu/help/api/data) DFR | [ECB 공식 결정 RSS](https://www.ecb.europa.eu/home/html/rss.en.html) / 보도자료 (허용 시) | 원문 결정금리 수동 확인 | `EVENT` / 일별 DFR; **EU 전체 단일금리 아님** |

| 기관 | 무료 자동 경로 | 발표 즉시 조치 | 별도 의미 |
|---|---|---|---|
| 미국 Fed | FOMC 공식 성명 HTML/일정 감시 | 결정문 목표구간 숫자 수집, 이후 원기관/FRED 보조 확인 | 목표 하단·상단/실효금리 다름 |
| 일본 BOJ | 무료 [2026 BOJ 통계 API](https://www.stat-search.boj.or.jp/info/api_manual_en.pdf) 실효 콜금리 | [통화정책 결정문](https://www.boj.or.jp/en/mopo/mpmdeci/) 공개 HTML·PDF 수집 | overnight 실효금리와 목표정책 별개 |
| 영국 BoE | 공개 통계 `IUDBEDR` [CSV 다운로드](https://www.bankofengland.co.uk/boeapps/database/Bank-Rate.asp) | [MPC 결정문](https://www.bankofengland.co.uk/monetary-policy-summary-and-minutes) 허용 파싱 | 결정 발표/적용일 분리 |
| 유로존 ECB | [SDMX API](https://data.ecb.europa.eu/help/api/data), 키 `FM.D.U2.EUR.4F.KR.DFR.LEV` | [ECB RSS](https://www.ecb.europa.eu/home/html/rss.en.html) 발표 감시 | DFR은 유로존; EU 전체 아님 |

예시: `https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.DFR.LEV?lastNObservations=5&format=csvdata`. BOJ: `https://www.stat-search.boj.or.jp/api/v1/getDataCode?format=json&lang=en&db=FM01&code=STRDCLUCON,STRDCLUCONH,STRDCLUCONL&startDate=202501` (정책 결정 목표가 아닌 시장 실효율). 변동이 없는 결정도 `no_change` 이벤트로 남긴다.

### 4.3 파생상품 만기 및 위칭 이벤트

| 지표 | 우선 수집 출처·방법 | 대안 및 보조 경로 | 수동·결측 처리 | 빈도 및 주의사항 |
|---|---|---|---|---|
| 파생상품 만기 | [OCC/OIC Expiration Calendar](https://www.optionseducation.org/referencelibrary/expiration-calendar) 공식 공개 자료, CME 상품 계약 사양 | 거래소 공개 이벤트 표/캘린더의 허용된 자동 파싱 | 예외·휴장·AM/PM 결제 등 수동 교차검증 | **예정 이벤트**; 실시간 DTE는 자체 계산 |
| 미국 트리플·쿼드러플 위칭 | OCC/OIC·Cboe·CME 계약별 공식 만기 일정 | 분기 셋째 금요일 후보 생성 후 공식 확인 | 미확인 시 보류 | 별도 이벤트 유형·플래그·DTE 및 거래일 수 계산. [명세](./US_Equity_Witching_Calendar.md) |

[OCC/OIC 공개 만기 달력](https://www.optionseducation.org/referencelibrary/expiration-calendar), Cboe 상품 설명/계약별 일정, CME 상품별 만기 명세를 무료 공개 페이지/파일에서 읽는다. 일반적인 월간 규칙 계산은 **예비 후보일 생성용**이고 실제 확정은 상품 계약/휴장 공지로 교차검증. OCC 2026-06-19 Juneteenth에 명목 expiration date와 processing date가 다른 사례([OCC 인포메모](https://infomemo.theocc.com/infomemos?number=56694))를 반영. `expiry_date`, `last_trade_at`, `processing_at`, `settlement_at`, `exercise_style`, `am_pm`, `source_url` 각각 저장. 공식 캘린더의 기계 판독이 어려우면 수동.

**미국 위칭 이벤트:** `TRIPLE_WITCHING`과 `QUADRUPLE_WITCHING`을 별도 관리한다. 주식 옵션·지수 옵션·지수 선물의 동시 만기는 트리플, 실제 개별주식 선물의 동시 만기까지 확인되면 쿼드러플로 분류한다. CME의 2026년 개별주식 선물 재도입 이후 계약별 검증이 필수이며, 미확인 자료는 `PENDING_VERIFICATION`으로 관리한다. 다음 각 유형의 DTE와 공통 위칭 플래그를 로컬 계산한다. [상세 명세](./US_Equity_Witching_Calendar.md).

## 5. 산업 및 시장심리 보조 지표

### 5.1 DRAM 모듈 현물가격

| 지표 | 우선 수집 출처·방법 | 대안 및 보조 경로 | 수동·결측 처리 | 빈도 및 주의사항 |
|---|---|---|---|---|
| DDR5 UDIMM 16GB 및 RDIMM 32GB 가격 | 공개 무료 API 미확인 | **DRAMeXchange 홈페이지 Module Spot Price → 지정 두 행 Session Average** (승인 후) | 허용된 범위에서 수동 확인, 불가 시 결측 | 주간 원본 갱신, 일 1회 점검; 권한 확인 전 비활성. [명세](./DRAMeXchange_Module_Spot_Prices.md) |

[DRAMeXchange](https://www.dramexchange.com/)의 `Module Spot Price` 표에서 `DDR5 UDIMM 16GB 4800/5600` 및 `DDR5 RDIMM 32GB 4800/5600` 행의 `Session Average`를 각각 독립 지표로 수집한다. 모듈의 주간 원본 갱신시각(GMT+8)을 보존하고 일 1회 점검한다. 자동 수집·저장·활용 권한을 확인한 후 HTML 스크래핑을 활성화하며, DRAM 칩 현물가격이나 계약가격과 혼용하지 않는다. [상세 명세](./DRAMeXchange_Module_Spot_Prices.md).

### 5.2 CNN 공포·탐욕 지수

| 지표 | 우선 수집 출처·방법 | 대안 및 보조 경로 | 수동·결측 처리 | 빈도 및 주의사항 |
|---|---|---|---|---|
| 미국 주식 CNN 공포·탐욕 | **공식 무료 API 미확인**; CNN 비문서화 JSON은 권한 확인 전 운영 제외 | CNN 원본 화면 자동 추출도 사용권 미확인 → 기본 비활성 | CNN [Fear & Greed](https://edition.cnn.com/markets/fear-and-greed) 화면의 `score/category/as_of` 기록 | 수동 스냅샷. CNN 수치가 실시간 틱인지 미보장 |

**지정 수집 대상:** [CNN International Fear & Greed](https://edition.cnn.com/markets/fear-and-greed), `source_url=https://edition.cnn.com/markets/fear-and-greed`. HTML 페이지의 `span.market-data-poller[data-data-url]`는 비공식 `https://production.dataviz.cnn.io/index/fearandgreed/graphdata`를 가리키는 것이 확인되었으나 공식 공개 개발자 API가 아니며 **[CNN Terms](https://www.cnn.com/terms)는 자동화된 데이터 수집·스크래핑을 금지**한다. 따라서 소스 URL을 지정·문서화하되 **실제 스크래핑 구현/자동 호출은 CNN의 명시적 허가 후에만**, 그 전에는 지정된 CNN URL에서 수동으로 `score`, `rating`, `as_of` 입력.

수동 입력 필드는 `score`(0~100), `sentiment_category`(원본 rating), `source_as_of`(화면에 있을 때만), `captured_at`, URL이다. 403/429·스키마 변경 시 우회하지 않는다. 자체 심리지표를 만들 경우 독립 시계열로 관리한다.

### 5.3 펜타곤 피자지수

| 지표 | 우선 수집 출처·방법 | 대안 및 보조 경로 | 수동·결측 처리 | 빈도 및 주의사항 |
|---|---|---|---|---|
| 펜타곤 피자지수 | 공개 JSON **/api/dashboard-data** 확인 (robots/Terms 권한 확인 필요) | Google Maps Popular Times 외부 추출·축적은 정책상 제한 → 기본 제외 | [PizzINT](https://www.pizzint.watch/) 상태·관찰시각·분류를 수동 기록 | 실험적 `MANUAL`; 시장 신호로 자동 주문 금지 |

**지정 수집 대상:** [PizzINT](https://www.pizzint.watch/), `source_url=https://www.pizzint.watch/`. 이전 `pentagon.pizza`는 대상에서 제외한다. 수집 순서: PizzINT 측에 공개 JSON API의 자동 호출 권한·robots 정책을 확인 → **허가 확인 시** `GET https://www.pizzint.watch/api/dashboard-data` → API 사용 불가능할 때 사이트가 **별도로 스크래핑을 승인한 경우에만** HTML → 그 외에는 PizzINT 화면 수동 관찰. 2026-11-22 직접 요청에서 이 API는 HTTP 200 JSON (`overall_index`, `defcon_level`, `active_spikes`, `timestamp`, `data[].current_popularity`, `data[].is_spike`, `data[].recorded_at`)을 반환했으며 일부 식당 값이 `null`. **단, `/robots.txt`는 `/api/`를 Disallow하고 [Terms](https://www.pizzint.watch/terms)는 합리적인 공개 API 이용은 허용하되 API 범위 밖 스크래핑을 금지하므로, URL이 응답한다고 무조건 자동화를 활성화하지 않는다.** 현재 정책 충돌/권한 확인 전 운영 상태는 `permission_required`, `manual`. Google Maps 원자료 직접 스크래핑은 하지 않는다.

Google Maps Popular Times 원천 데이터를 추출하는 문서화된 무료 REST API는 확인되지 않았고, [Google Places 데이터 정책](https://developers.google.com/maps/documentation/places/web-service/policies)은 외부 추출·저장 및 재배포를 제한한다. 서드파티 피자지수 페이지의 직접 스크래핑도 원천 콘텐츠 권리 검토가 필요하다. `activity_label`, `activity_score_if_public`, `observed_at`, `source_url`, `manual_note`만 기록하고 **객관적 예측력/자동매매 신호로 확정하지 않는다**.

## 6. 수집기 운영 및 권한 관리

### 6.1 스크래핑 운영 체크리스트

1. **허용 출처를 선택**: 정책·robots.txt·서비스 이용권 확인. **robots 허용만으로 저작권/데이터 재배포 허가가 주어지는 것은 아니다.**
2. 공식 기관부터 `RSS/Atom/ICS/CSV/JSON` 우선. HTML만 가능하면 정부 발표/기업 IR 중 약관 허용된 페이지를 `requests + BeautifulSoup`로 파싱. 타임스탬프와 원본 링크 저장.
3. 정해진 간격/조건부 GET/429 백오프, 도메인별 총 요청 제한. 403/캡차를 우회하지 않는다.
4. HTML 구조 변경 시 **빈 데이터 성공으로 처리하지 말고 `manual_review_required`**로 전환. 소스가 발표한 시각과 수집 시각 분리.
5. 예제: [무료 수집 Quickstart](./Realtime_Quickstart.md) / [공개 수집 Python](../examples/realtime_collector.py). 수동: [수동 입력 가이드](./Manual_Collection.md).

### 6.2 소스별 주요 이용약관

- [Yahoo 자동 수집 제한](https://legal.yahoo.com/us/en/yahoo/terms/product-atos/apitnc/index.html): 비문서화 `chart/v8`와 `yfinance`를 **승인된 무료 운영 소스라고 분류하지 않음**.
- [Cboe 호가 테이블 자동추출 금지](https://www.cboe.com/data/quotes/vix/options): VIX 장중 호가 웹 스크래핑을 권장하지 않음.
- [Google Places 정책](https://developers.google.com/maps/documentation/places/web-service/policies): Popular Times 별도 DB 저장/추출 배제.
- [CME 웹데이터 대량 추출 제한](https://www.cmegroup.com/articles/faqs/access-to-cme-group-settlement-data-faq.html): 공개 차트의 HTML/WebSocket 역공학으로 무단 수집 금지.
- [SEC Fair Access](https://www.sec.gov/about/developer-resources): 10 req/s 이하, 사용자 에이전트 연락처 필요.
- [BLS 자동 조회 제한](https://www.bls.gov/bls/blsterms.htm): 초당 여러 번 반복 추출하면 차단될 수 있음.
- [FRED API 이용약관](https://fred.stlouisfed.org/legal/terms/): 저장/캐싱/DB·AI 관련 제한 및 원 소스의 저작권 필수 확인.
- [CNN Terms](https://www.cnn.com/terms): 자동 수집 제한, 명시적 허가 전 비활성.
- [PizzINT Terms](https://www.pizzint.watch/terms): API 범위 밖 스크래핑 제한 및 robots 정책 확인.
- [DRAMeXchange Terms of Use](https://www.dramexchange.com/About/TermsOfUse): 자동 수집·저장·활용 권한 확인 전 비활성.
- 네이버 증권, SEIBro의 스크래핑은 각각의 서비스 정책·권리 확인 후에만 활성화한다.

## 7. 관련 문서

- [Realtime_Quickstart.md](./Realtime_Quickstart.md): 실행 명령, 수집 예제 및 폴링 권장값.
- [Manual_Collection.md](./Manual_Collection.md): 수동 입력 항목 및 CSV 포맷.
- [Collector_Design.md](./Collector_Design.md): failover, 정규화, 이벤트·시각·백테스트 설계.
- [Indicator_Data_Sources.md](./Indicator_Data_Sources.md): 전체 지표별 출처 인덱스.
- [Real_Time_Data_Sources.md](./Real_Time_Data_Sources.md): 실시간·준실시간 가격 수집.
- [YFinance_Data_Validation.md](./YFinance_Data_Validation.md): yfinance 실제 검증 기록.
- [Binance_API_Coverage.md](./Binance_API_Coverage.md): Binance API 검증 결과.
