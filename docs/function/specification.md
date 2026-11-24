# Auto-Axe 기능 명세서

> 기준일: 2026-11-24 · 기존 지표 수집 정책을 통합한 기능 요구사항. 예제 구현과 운영 기능은 구분한다.

## 1. 목적 및 범위

NH나무 OpenAPI 기반 알고리즘·패턴 매매 퀀트 시스템에 필요한 시장·경제·기업·산업 지표를 무료 소스로 수집하고 분석용 피처로 변환한다. 현재 확정된 범위는 지표 수집·계산 정책과 노드 기반 매수·매도 Workflow의 기본 기능이며, 세부 주문 유형·브로커 연동·리스크 한도 및 추가 트리거는 별도 확정 대상이다.

[시스템 설계](../design/specification.md) · [무료 수집 상세](../indicator-collection/Free_Data_Collection.md) · [지표 목록](../indicator-collection/Indicator_Data_Sources.md)

## 2. 공통 기능 요구사항

| ID | 기능 | 수용 기준 |
|---|---|---|
| FR-001 | 무료 소스 관리 | 유료 피드 제외, 출처·권한·상품 정의·주기 기록 |
| FR-002 | 자동 수집 | 허용 API/WS/공식 파일 우선, 승인형 스크래핑만 실행 |
| FR-003 | 수동 수집 | 원본 링크·값·기준시각·입력시각 보존, 권한 제한 우회 금지 |
| FR-004 | 정규화 | 단위·통화·상품 유형·UTC 시간 정규화, 미확인 값은 null |
| FR-005 | 품질 관리 | 결측·지연·연결 종료·중복·정정·스키마 오류 식별 |
| FR-006 | 데이터 조회 | 종목·지표·기간·출처·품질 기준으로 조회 가능하도록 설계 |
| FR-007 | 피처 산출 | 원본 및 계산 파라미터 추적, 확정봉과 당시 공개 자료만 사용 |

## 3. 시장 가격 및 거래 통계

| ID | 지표 | 기본 소스 | 갱신 |
|---|---|---|---|
| FR-101 | BTC 현물 | Binance Spot BTCUSDT | WS 체결 |
| FR-102 | 금 | Binance Futures XAUUSDT | WS 체결 |
| FR-103 | 은 | Binance Futures XAGUSDT | WS 체결 |
| FR-104 | 구리 | Binance Futures COPPERUSDT | WS 체결 |
| FR-105 | WTI | Binance Futures CLUSDT | WS 체결 |
| FR-106 | Brent | Binance Futures BZUSDT | WS 체결 |
| FR-107 | Nasdaq 100 연동 가격 | MEXC NAS100_USDT 후보 | WS, 실측 필요 |
| FR-108 | Binance 롱숏·Taker 비율 | Futures 공개 REST | 5분 이상 집계 |
| FR-109 | VIX | yfinance ^VIX | 1~5분 조회 |
| FR-110 | 미국 국채 3M/5Y/10Y/30Y | yfinance ^IRX/^FVX/^TNX/^TYX | 1~5분 조회 |
| FR-111 | 미국 국채 2Y | Treasury BC_2YEAR, 네이버 US2YT=RR 승인 후 | 현재 일별 |

- FR-102~106은 USDT 결제 연동 영구선물이다. 금 현물 Gold API, 원유 EIA 일별 현물, Coinbase BTC/USD는 별도 참고 시계열이다. 두바이유 제외.
- FR-107은 실제 CME NQ 선물이 아니다. Binance QQQUSDT는 ETF 연동 참고, yfinance NQ=F는 실제 CME 선물의 지연 비교 자료다. MEXC Protobuf 전환 및 실측 검증 필요.
- FR-108은 BTCUSDT와 5개 원자재 선물 각각 전체 계정, 상위 계정, 상위 포지션, Taker 매수·매도 거래량 비율을 수집해 24개 시계열을 구성한다. Taker 비율을 포지션 비율로 표시하지 않는다.
- FR-109~111은 무지연 보장 없음. Treasury 공식 5종 및 Cboe 일별 VIX는 별도 교차검증 자료다.

상세: [Binance](../indicator-collection/Binance_Metals_LongShort_20261123.md) · [Nasdaq](../indicator-collection/Nasdaq100_Futures_Data_Sources.md) · [시장 정책](../indicator-collection/Market_Source_Policy_20261123.md).

## 4. 미국 주식·ETF

| ID | 기능 | 입력 및 처리 | 주기 |
|---|---|---|---|
| FR-201 | 당일 누적 거래량 | yfinance AsyncWebSocket day_volume → 최신값 캐시 | 로컬 1초 |
| FR-202 | 후행 PER | trailingPE | 일별 |
| FR-203 | 예상 PER | forwardPE | 일별 |
| FR-204 | PBR | priceToBook | 일별 |
| FR-205 | ROE | returnOnEquity | 실적 발표 후 |
| FR-206 | SMA | OHLCV Close rolling mean, 5/20/60/120/200일 | 봉 확정 |
| FR-207 | EMA | OHLCV Close ewm, 12/26일 등 | 봉 확정 |
| FR-208 | 최고가 | HIGH_5D/HIGH_10D/HIGH_20D | 일봉 확정 |
| FR-209 | 최저가 | LOW_5D/LOW_10D/LOW_20D | 일봉 확정 |
| FR-210 | 서학개미 수급 | SEIBro 해외주식 TOP50 결제금액 | 원본 발표·조회기간 기준 |
| FR-211 | 기업 가이던스 | SEC EDGAR 8-K/Exhibit 99.1 및 회사 IR | 신규 공시 |

### 4.1 누적 거래량

NVDA·QLD 등 설정 종목의 최신 당일 누적 주 수를 매초 기록한다. 새 메시지가 없으면 원본 시각을 유지하고 no_update/stale로 표시한다. 최초 미수신은 null, 연결 종료는 disconnected로 처리한다. 거래일 변경·누적량 감소 시 세션 리셋을 검증한다. 분봉 거래량 및 통합시장 초당 체결량과 구분한다. 실제 WS 필드·시간 단위·갱신 빈도는 장중 검증 필요.

### 4.2 재무 및 기술지표

PER/PBR/ROE는 Ticker.info를 우선 사용한다. ROE 원본 ratio와 표시 percent를 구분하고 ETF에 기업 재무비율을 강제하지 않는다. SMA는 N개 종가 평균, EMA는 alpha=2/(N+1)로 계산하며 초기화·조정가격 정책을 보존한다. 고저가는 최근 N개 확정 거래 세션의 High 최댓값 및 Low 최솟값이다. 장중 돌파 기준은 직전 N개 완성 일봉만 사용한다. 주말·휴장일 제외, 워밍업 부족 시 null, 미래정보 소급 적용 금지.

### 4.3 결제 통계 및 가이던스

SEIBro는 국가·기간별 매수/매도/순매수 결제금액 USD를 수집한다. TOP50과 전체 합계, 결제와 체결을 구분한다. 승인 전 자동 스크래핑 비활성. 가이던스는 회계기간, GAAP/adjusted, 전망 범위, 원문 및 공개시각을 저장하며 애널리스트 컨센서스와 구분한다.

상세: [누적 거래량](../indicator-collection/YFinance_1s_Stock_Cumulative_Volume.md) · [재무·기술지표](../indicator-collection/YFinance_Valuation_and_Moving_Averages.md) · [SEIBro](../indicator-collection/SEIBro_Overseas_Stock_Flows.md).

## 5. 경제·정책 및 만기 이벤트

| ID | 기능 | 출처 및 처리 |
|---|---|---|
| FR-301 | 미국 경제 발표 일정 | BLS ICS, BEA, Census, FOMC 공식 일정 |
| FR-302 | 실제 발표값 | BLS/BEA/Census API 및 공식 보도자료 |
| FR-303 | 미국 정책금리 | Fed FOMC 목표구간 |
| FR-304 | 일본 정책금리 | BOJ 결정문, 실효 콜금리 별도 |
| FR-305 | 영국 정책금리 | BoE IUDBEDR 및 MPC 결정 |
| FR-306 | 유로존 정책금리 | ECB DFR SDMX 및 공식 결정 |
| FR-307 | 파생상품 만기 | OCC/OIC, Cboe, CME, Binance Options 계약별 공식 일정 |
| FR-308 | 트리플 위칭 | 주식 옵션·지수 옵션·지수 선물 동시 만기 확인 |
| FR-309 | 쿼드러플 위칭 | FR-308 구성 + 개별주식 선물 동시 만기 확인 |
| FR-310 | DTE 및 이벤트 플래그 | 확정 이벤트에서 로컬 계산 |

발표 예정·실제 공개·최초 수집·수정 시각과 actual/previous/consensus를 구분한다. 컨센서스가 확인되지 않으면 결측 또는 근거 있는 수동 입력. 정책 목표금리와 시장 실효금리, 결정일과 발효일을 분리한다. 만기는 명목 만기·최종 거래·처리·정산 시각을 분리하고 휴장 예외를 검증한다.

위칭은 분기 셋째 금요일을 후보로 생성하되 실제 계약을 확인한다. 4개 상품군 YES/NO/UNKNOWN을 기록하고 CME 개별주식 선물 재도입 이후에도 실제 계약 기준으로 판정한다. TRIPLE_WITCHING과 QUADRUPLE_WITCHING은 상호 배타적이며 미확인은 PENDING_VERIFICATION. IS_TRIPLE_WITCHING_DAY, IS_QUADRUPLE_WITCHING_DAY, IS_WITCHING_DAY, DTE_TRIPLE_WITCHING, DTE_QUADRUPLE_WITCHING, TRADING_DAYS_TO_WITCHING을 산출한다. [위칭 상세](../indicator-collection/US_Equity_Witching_Calendar.md).

## 6. 산업·시장심리 보조 지표

| ID | 지표 | 원본 및 처리 |
|---|---|---|
| FR-401 | DDR5 UDIMM 16GB 4800/5600 | DRAMeXchange Module Spot Price / Session Average |
| FR-402 | DDR5 RDIMM 32GB 4800/5600 | 동일 표의 별도 행 / Session Average |
| FR-403 | CNN 공포·탐욕 | CNN International Fear & Greed 지정 페이지 |
| FR-404 | 펜타곤 피자지수 | PizzINT 지정 페이지 |

DRAM은 두 독립 시계열을 유지하며 주간 원본 Last Update를 저장하고 일 1회 점검한다. 권한 확인 후 HTML 스크래핑, 단위 미확인 시 임의 확정 금지. CNN 및 PizzINT는 현재 수동 경로를 기본으로 하며 자동 수집은 명시적 허가 후에만 활성화한다. PizzINT 공개 JSON 응답 확인은 사용 허가를 뜻하지 않는다. 피자지수는 자동 주문 신호로 사용하지 않는다.

[DRAM 상세](../indicator-collection/DRAMeXchange_Module_Spot_Prices.md) · [수동 수집](../indicator-collection/Manual_Collection.md).

## 7. 매수·매도 Workflow

ComfyUI/n8n과 유사한 블록 편집 방식으로 사용자가 조건·트리거·논리·주문 노드를 드래그 및 연결한다. 상세 규칙, 추천 트리거와 추가 기능은 [매수·매도 Workflow 명세](./trading-workflow.md)를 참조한다.

| ID | 기능 | 요구사항 |
|---|---|---|
| FR-501 | 비주얼 Workflow 편집 | 블록 배치·드래그·입출력 연결 |
| FR-502 | 순차 조건 | 조건 1 → 조건 2 → 조건 N → 매수/매도 |
| FR-503 | AND 조건 | 모든 조건 충족 시 후속 실행 |
| FR-504 | OR 조건 | 하나 이상의 조건 충족 시 후속 실행 |
| FR-505 | 전체 중단 트리거 | 별도 트리거 충족 시 해당 Workflow 전체 중단 |
| FR-506 | 가격 트리거 | 목표가, N% 상승/하락 |
| FR-507 | 상태형 반전 트리거 | 상승 후 하락 또는 하락 후 상승 |
| FR-508 | 강도 트리거 | 상승/하락 강도, 기준·기간·산식 선택 |
| FR-509 | 뉴스 감정 트리거 | 긍정/부정 감정 분석, 출처·모델·권한 추가 검증 필요 |
| FR-510 | 매수·매도 액션 | 조건 충족 후 주문 실행 요청; 실제 브로커 지원·권한 확인 필요 |

추천 상세 기능은 추가 논리 노드(NOT, IF/ELSE, N-of-M), 모의 실행, 시간 제한·재무장·쿨다운, 백테스트, 위험 한도, 주문 대사, 상태·감사 로그다. **상태형 조건과 전체 중단을 서버 실행 엔진에서 관리**하고 실제 주문과 신호를 분리하는 방향을 권장한다. 중단 자체로 보유 포지션을 자동 청산하지 않는다.

## 8. 수용 테스트 및 구현 상태

| 검증 항목 | 통과 조건 |
|---|---|
| 시세 | 실제 상품 식별자·통화·시각·가격 검증, 서로 다른 계약 혼합 금지 |
| 롱숏 | 6종목×4통계, 지원 period 및 원본 timestamp 중복 제거 |
| 1Hz 누적량 | 새 메시지 없음·리셋·역순·연결 종료에서 올바른 상태 출력 |
| 기술지표 | 알려진 OHLCV로 계산 결과 일치, 미확정봉·워밍업 검증 |
| 경제 이벤트 | 최초값·수정값·시간대·발표 지연 구분 |
| 위칭 | 3종/4종/미확인/휴장 예외 테스트, 중복 분류 금지 |
| 스크래핑 | 권한 확인, 지정 행·열·시각 검증, 구조 변경 시 실패 처리 |
| 백테스트 | 당시 이용 가능했던 값만 조회, 미래정보 누수 방지 |
| Workflow | 순차·AND·OR·상태형 반전·전체 중단, 중복 주문 차단 및 모의 실행 검증 |

현재 저장소에는 [수집 예제](../examples/realtime_collector.py) 및 검증 스크립트가 있다. Binance 시세·롱숏 및 일부 yfinance 분봉은 기존 문서에서 실측 결과를 확인할 수 있다. 주식 1Hz 누적량, 재무·기술지표, Nasdaq 연동, SEIBro, DRAM, 위칭의 운영 구현은 완료되지 않았다. 권한 제한과 실제 수신 검증은 배포 전 별도 통과 조건이다.

## 9. 향후 기능 확정 대상

노드 기반 전략 편집·조건·트리거·매수/매도의 기본 요구사항은 확정했다. 추가 트리거의 채택 범위, 세부 전략 템플릿, 백테스트 체결 모델, 포트폴리오·리스크 한도, NH나무 인증·주문·취소·체결·잔고, 운영 알림은 추가 확정 대상이다. Workflow 편집기·실행 엔진·뉴스 분석·주문 연동은 현재 미구현이다.
