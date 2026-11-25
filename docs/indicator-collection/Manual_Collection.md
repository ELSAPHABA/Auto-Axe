# Auto-Axe 수동 수집 레지스트리 및 입력 절차

> 무료 자동 수집으로 동일 정의와 시각의 데이터를 얻을 수 없을 때, 허용 범위에서만 수동 기록한다. 수동 입력을 자동 수집으로 표시하지 않는다. [시장 데이터 소스 정책](./Market_Source_Policy_20261123.md)을 따른다.

## 수동 항목 목록

| series_id | 화면/공식 출처 | 입력 항목 | 기록 시기 | 구별해야 할 것 |
|---|---|---|---|---|
| `DRAM_DDR5_UDIMM_16GB_SESSION_AVG` / `DRAM_DDR5_RDIMM_32GB_SESSION_AVG` | [DRAMeXchange](https://www.dramexchange.com/) Module Spot Price | 지정 Item, Session Average, 섹션 Last Update, 단위 확인 | 주간 발표 확인 | 수동 적재도 허용 범위 확인 필수; 권한 미확인 시 비활성. [명세](./DRAMeXchange_Module_Spot_Prices.md) |
| `CNN_FEAR_GREED` | [CNN Fear & Greed](https://edition.cnn.com/markets/fear-and-greed) | `score` (0~100), `category`, 화면 기준시각·조회시각 | 정기 점검(예: 미국 장 중/종료 후) | CNN 제공 점수 vs 자체 심리지표 |
| `SEIBRO_OVS_STOCK_TOP50_SETTLEMENT` | [SEIBro 해외주식 종목별내역 TOP50](https://seibro.or.kr/websquare/control.jsp?w2xPath=/IPORTAL/user/ovsSec/BIP_CNTS10013V.xml&menuNo=921) | 국가·조회기간·조회기준일·매수결제/매도결제/순매수결제(USD), 종목코드·종목명·순위 | 결제 결과 게시 후 수동 조회 | **전체 시장 합계나 실시간 체결 데이터 아님.** [상세](./SEIBro_Overseas_Stock_Flows.md) |
| `PENTAGON_PIZZA` | [PizzINT](https://www.pizzint.watch/) | 화면의 활동 상태/공개 지수(있는 경우), 측정시각·관찰 메모 | 필요시 | Google Maps 외부 축적 금지; 독립·검증된 경제지표 아님 |
| `VIX_INTRADAY` | [Cboe VIX](https://www.cboe.com/tradable_products/vix/) | 표기된 VIX 수준, 사이트 시각·지연표시 | 장중값이 꼭 필요할 때 | 공식 Cboe **일별 CSV**와 별도 |
| `UST_2Y_INTRADAY` | [네이버 지정 페이지](https://m.stock.naver.com/marketindex/bond/US2YT=RR) | 수익률 %, 원본 시각·지연 | 자동화 허가 전 허용 수동 조회 | 기본 운영은 Treasury BC_2YEAR 일별; 금리 선물로 대체 금지 |
| `UST_10Y_INTRADAY` | [Treasury 공식 일별](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics) 외 수동 장중 수익률 출처 | 원본 출처, 현물/지표형, 10Y %, 화면 지연 | 장중 추적 필요 시 | 국채 현물 수익률 vs 선물 가격 |
| `WTI_FUTURES_INTRADAY` | 공개적으로 열람 가능한 거래소/상품 페이지 | 가격 USD/bbl, 거래소·선물 월물, 지연표시 | 장중값이 필요할 때 | EIA WTI 현물 **일별**과 별도 |
| `BRENT_FUTURES_INTRADAY` | ICE 등 상품 표시 화면 | 가격 USD/bbl, 거래소·월물·지연 | 장중값이 필요할 때 | 현물 Brent 일별과 별도 |
| `EARNINGS_CONSENSUS` | 각 기업 IR 및 권한 있는 공개 금융 자료 | ticker, 회계연도/분기, forecast EPS/revenue, 애널리스트 수(명시된 경우), 날짜 | 실적 전 예상치 비교 필요 시 | SEC **회사 자체 guidance**와 분리 |
| `EARNINGS_GUIDANCE_EXCEPTION` | 기업 공식 IR PDF/실적콜 등 | metric, 범위, FY/Q, GAAP 여부, 최초 발표, 원문 링크 | 자동 parser 실패 시 | 리뷰필요 사유 기록 |
| `US_EQUITY_WITCHING_VERIFY` | OCC/OIC·Cboe·CME 공식 계약 일정 | 실제 4개 상품군별 YES/NO/UNKNOWN, ET 세션 및 근거 링크 | 주간 확인·휴장/상장/정정 시 | 미확인 시 트리플/쿼드러플 단정 금지. [분류 기준](./US_Equity_Witching_Calendar.md) |
| `EXPIRATION_EXCEPTION` | [OCC 공식](https://www.optionseducation.org/referencelibrary/expiration-calendar), [CME 공식](https://www.cmegroup.com/tools-information/calendars/expiration-calendar.html) | 상품별 명목 만기·최종거래·처리·결제일 | 휴일/특별처리 공지 시 | 달력의 일반 셋째 금요일 규칙으로 대체 금지 |
| `ECONOMIC_FORECAST` | 적법하게 공개된 컨센서스 원문 | 지표명·예상치·조사시점·단위 | 주요 발표 직전 | 공식 actual과 별개; 허위 컨센서스 생성 금지 |

**정책금리 Fed/BOJ/BoE/ECB는 공식 공개 RSS/페이지/API로 감지**하므로 전체가 수동은 아니다. RSS 파싱이 실패하거나 성명에서 정책 목표 수치 추출이 불확실한 경우 **해당 이벤트만 수동 검수**한다.

## 권장 CSV/JSONL 구조

CSV 헤더(UTC ISO 8601 표준):

```csv
series_id,instrument_type,source_url,as_of_utc,collected_at_utc,frequency,value,unit,category,quote_currency,exchange,contract,source_delay_minutes,operator,note,verification_status
```

예시(실제 관측값이 아닌 **형식 예시**):

```csv
series_id,instrument_type,source_url,as_of_utc,collected_at_utc,frequency,value,unit,category,quote_currency,exchange,contract,source_delay_minutes,operator,note,verification_status
CNN_FEAR_GREED,SENTIMENT,https://edition.cnn.com/markets/fear-and-greed,,2026-11-22T12:00:00Z,snapshot,65,index,greed,,,,,manual-user,Source had no explicit as-of,unverified
```

- 화면에 데이터 기준시각이 없으면 `as_of_utc`는 **비워 둔다**. 현재 시각으로 추정해 넣지 않는다.
- `collected_at_utc`는 실제 입력시간. 0이나 결측치를 실측치로 취급하지 않는다.
- `verification_status`: `unverified|checked|rejected`; 수동 입력은 자동 데이터와 충돌하면 별도 진실성 검증이 필요하다.
- 저작권 있는 화면/원본 내용을 통째로 복제하지 않고 숫자·최소한의 메타데이터·출처 링크만 보관(사용권 확인 필수).
- 수동 관측은 **자료를 확인한 시각 이후부터만** 백테스트에서 이용 가능. 날짜·시간이 불명확하면 PIT 전략 입력에서 제외.

## 입력·검증 흐름

1. 수집기가 자동 소스 사용 불가/정책 제한/필수 필드 누락 시 `manual_required` 이벤트 생성.
2. 해당 출처를 사람이 열어 대상 수치와 원상품 구분 확인 → `as_of`가 명시되어 있으면 기록.
3. CSV 한 행 또는 UI 수동 폼에 입력하고 `operator`, 원문 URL, 조회시각, 지연표시·단위를 기록.
4. 가능한 경우 다른 **무료 공식** 발표 자료로 교차검증하고 `checked` 처리.
5. DB에서 `provider=manual`로 별도 저장하고, 자동 데이터와 혼합 평균을 내지 않는다.

## 미지원·제약 상태

- **피자:** Google Popular Times 수치용 무료 구조화 API 미확인. Google Maps 스크래핑으로 이 문제를 해결하지 않는다.

기본 시장가격은 Binance Spot BTC 및 금·은·구리·WTI·Brent 연동 영구선물이다. yfinance VIX·국채 3M/5Y/10Y/30Y는 지연 가능 지표이며 주식·ETF 지정 데이터에도 사용한다. 수동 WTI/Brent 실제 만기선물 및 현물, Yahoo 비교값은 Binance 계약과 독립 시계열이다. 네이버 2Y 자동 수집은 허가 전 비활성, Treasury BC_2YEAR 일별 fallback. CNN/PizzINT/SEIBro/DRAM의 자동·수동 저장 및 활용 모두 권한 범위를 확인한다. PizzINT는 자동 주문 신호에서 제외한다.
