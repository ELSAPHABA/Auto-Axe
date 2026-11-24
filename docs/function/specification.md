# Auto-Axe 기능 명세서

> 기준일: 2026-11-24 · 기존 지표 수집 정책을 통합한 기능 요구사항. 예제 구현과 운영 기능은 구분한다.

## 1. 목적 및 범위

NH나무 OpenAPI 기반 알고리즘·패턴 매매 퀀트 시스템에 필요한 시장·경제·기업·산업 지표를 무료 소스로 수집하고 분석용 피처로 변환한다. 현재 확정된 범위는 지표 수집·계산 정책, 노드 기반 매수·매도 Workflow, 전체 추가 트리거·상세 기능·편집기 UI, 주식 그룹 및 금요일 종가매수 분석·예측 시스템이다. 세부 주문 유형·브로커 API·리스크 한도 수치와 신규 데이터 권한은 별도 검증 대상이다.

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

ComfyUI/n8n과 유사한 블록 편집 방식으로 사용자가 조건·트리거·논리·주문 노드를 드래그 및 연결한다. 상세 규칙, 승인된 추가 트리거와 상세 기능은 [매수·매도 Workflow 명세](./trading-workflow.md)를 참조한다.

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
| FR-511 | 추가 논리 및 실행 제어 | NOT, IF/ELSE, N-of-M, Wait, Timeout, Reset, Cooldown, 제어된 반복 |
| FR-512 | 추가 기술적 트리거 | 이동평균 교차, 5/10/20일 고저가 돌파, 갭·지지/저항, 거래량/RVOL, RSI/MACD/ROC, ATR/볼린저밴드/실현 변동성 |
| FR-513 | 추가 시장·거시 트리거 | VIX/CNN, 롱숏/Taker, 금리·금리차, 경제/실적 발표, 가이던스, 위칭/DTE, DDR5, 교차자산, 거래시간 |
| FR-514 | 포지션·위험·시스템 트리거 | 손익·익절·손절·트레일링, 일일 손실·주문/포지션 한도·스프레드, 피드/API 이상 |
| FR-515 | 모의 실행·백테스트·재생 | 동일 엔진으로 Dry-run 및 당시 데이터·비용·슬리피지·부분체결 검증 |
| FR-516 | 주문 안전 및 감사 | 중복 방지, Kill Switch, 리스크/품질 게이트, 체결 대사, 감사 로그 |
| FR-517 | 편집기 UI 및 디버깅 | 좌측 노드 라이브러리·중앙 캔버스·우측 설정·하단 로그·상단 툴바, 경로 강조, 미니맵·Undo/Redo·복사/붙여넣기 |
| FR-518 | Workflow 관리 | 저장·복제·버전·템플릿·JSON 가져오기/내보내기·변수·Sub-workflow |
| FR-519 | 주문 제어 | 분할 매수/매도, 익절/손절, 트레일링, OCO, 이벤트 거래 금지 구간 |
| FR-520 | 다중 전략 | Watchlist 종목별 실행, 전략 충돌 방지, 계좌 수준 조정 |
| FR-521 | 승인·알림·성과 | 승인 노드, 배포 승인, 권한, 결과/오류 알림, 성과 리포트 |
| FR-522 | 사용자 주식 그룹 | 생성/편집/검색/복제/삭제, 구성 종목 및 가중치 버전, JSON 가져오기/내보내기 |
| FR-523 | 그룹 집계 | 평균/가중/중앙 수익률, 상승·하락·보합 종목 수와 비중, 조건부 평균 상승·하락률, 시장폭·분산·강도·상대수익률 |
| FR-524 | 그룹 트리거 | 그룹 수치 비교/돌파/순차 반전, 그룹 간 비교, 구성종목 ALL/ANY/N-of-M, 독립 중단 연결 |
| FR-525 | 그룹 품질 및 UI | 동일 기준시각·가격·세션, coverage·결측 검증, 그룹 카드·상세·Workflow 설정 및 버전 고정 |
| FR-526 | 조건 분기 및 합류 | TRUE/FALSE/UNKNOWN 경로, 중첩 분기, Switch, 명시적 Fork/Join, 미선택 경로 실행 금지 |
| FR-527 | Workflow 조건 재사용 | 저장된 Workflow 전체를 하나의 WorkflowCondition 블록으로 참조, 명시적 ConditionResult, 버전 고정·상태 격리·순환 참조 금지·조건 호출의 주문 부작용 차단 |
| FR-528 | Workflow 참조 삭제 제한 | 다른 Workflow에서 참조 중이면 삭제 불가; UI/API 공통 제약, 참조 목록 및 해제 후 삭제, 활성/비활성/초안 및 고정 실행 검증 |
| FR-529 | Workflow 실행 상태 모니터링 | 메인 활성 Workflow 개수, 목록 및 상세의 조건 충족/미충족/감시/미평가/미선택/UNKNOWN 상태, 실제 경로 및 평가 시각 표시 |

위 추가 기능과 [Workflow 상세 명세](./trading-workflow.md)의 모든 P0~P2 항목은 사용자 승인 개발 범위다. 주식 그룹은 [별도 상세 명세](./stock-groups.md)를 따른다. **상태형 조건과 전체 중단을 서버 실행 엔진에서 관리**하고 실제 주문과 신호를 분리하는 구조로 설계한다. 중단 자체로 보유 포지션을 자동 청산하지 않는다.

## 8. 금요일 종가매수 (Friday Close Strategy)

독립 카테고리에서 최근 3년간 월~금 나스닥 및 관련 지표의 상황과 다음 주 월요일의 수익률 사이의 관계를 분석하고 조건부 상승 확률을 예측한다. 5년·10년 비교, 통계적 불확실성, 모델 검증, 전용 UI 및 기존 Workflow 연동을 포함한다. [상세 명세](./friday-close-strategy.md).

| ID | 기능 | 요구사항 |
|---|---|---|
| FR-601 | 독립 전략 카테고리 | 금요일 종가매수 전용 분석 화면, 지수/실제 종목 및 기간 선택 |
| FR-602 | 주간 데이터셋 | 3년 기본, 5/10년 비교, 월~금 지표 및 다음 월요일 라벨, 한 주 한 표본, 거래소 세션 및 as-of 검증 |
| FR-603 | 3종 예측 목표 | 금요일 종가→월요일 종가(주 목표), 금요일 종가→월요일 시가, 월요일 시가→종가 |
| FR-604 | 분석 피처 | 가격·기술지표·VIX·국채·달러·관련 시장·경제 이벤트 및 기존 그룹/산업/심리/뉴스/롱숏 지표의 가용 이력 |
| FR-605 | 통계 분석 | Pearson/Spearman, Mutual Information, 조건부 확률, 분위수, Bootstrap, 피처 상관, 표본 수 및 불확실성 |
| FR-606 | 예측 모델 | 기준 상승 빈도, L2 Logistic Regression, Bayesian Logistic, KNN 유사 패턴, Random Forest/XGBoost/LightGBM 비교 |
| FR-607 | 모델 및 수익률 검증 | Walk-forward, 시간순 전처리·튜닝·보정, 정확도/Brier/Log Loss, 비용 차감 수익률·MDD·Sharpe·손익비 |
| FR-608 | 연구/실행 모델 분리 | RESEARCH_EOD와 EXECUTION_PRE_CLOSE 분리, 실제 주문 전 cutoff 및 장중 자료 확보, 미래정보 누수 차단 |
| FR-609 | 결과 UI 및 모델 관리 | 3종 확률, 예상 수익률·하방 위험, 기여 요인, 유사 사례, 검증 결과, 주간 재학습, 모델·예측 버전 및 보류 상태 |
| FR-610 | Workflow 연동 | 예측 확률·예상 수익률·하방 위험·신뢰도·유사도·검증 상태 트리거, 연구 모델 실주문 연결 금지 |

가격·시세·지표의 역사적 가용 범위와 데이터 이용권, 모델·매매 임계값은 검증한다. 실제 예측값이나 실현 수익률은 아직 없다.

## 9. 수용 테스트 및 구현 상태

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
| Workflow | 순차·AND·OR·상태형 반전·전체 중단, 조건 분기·합류, 재사용 결과·상태 격리·순환 참조 방지, 참조 삭제 제약, 활성 수와 조건 상태, 중복 주문 차단 및 모의 실행 검증 |
| 주식 그룹 | 수익률·시장폭 산식, 가중치·coverage·그룹 버전·중단 및 백테스트 검증 |
| 금요일 종가매수 | 주간 라벨·휴장·cutoff, 시점 정합성, 시간순 검증·확률 보정, 모델/예측 버전, 연구용 실주문 차단, Workflow 품질 게이트 |

현재 저장소에는 [수집 예제](../examples/realtime_collector.py) 및 검증 스크립트가 있다. Binance 시세·롱숏 및 일부 yfinance 분봉은 기존 문서에서 실측 결과를 확인할 수 있다. 주식 1Hz 누적량, 재무·기술지표, Nasdaq 연동, SEIBro, DRAM, 위칭의 운영 구현은 완료되지 않았다. 권한 제한과 실제 수신 검증은 배포 전 별도 통과 조건이다.

## 10. 향후 기능 확정 대상

Workflow 편집기 UI 및 모든 추가 트리거·상세 기능, 사용자 정의 주식 그룹, 금요일 종가매수 분석·예측 기능을 확정했다. 개별 전략 템플릿의 파라미터, 백테스트 체결 모델의 세부 방식, 리스크 한도 수치, NH나무 인증·주문·취소·체결·잔고 API 계약, 뉴스 소스/모델 및 신규 데이터 권한은 추가 검증·설계 대상이다. Workflow 편집기·실행 엔진·뉴스 분석·금요일 예측 모델·전용 UI·주문 연동은 현재 미구현이다.
