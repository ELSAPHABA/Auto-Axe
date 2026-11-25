# 퀀트 분석·피처·예측·백테스트 기술 스택

## 1. 선택

| 기술 | 역할 |
|---|---|
| NumPy / pandas | 시계열·벡터 연산, rolling, 피처·그룹 |
| SciPy / statsmodels | 통계 검정, 회귀, 신뢰구간, 효과크기 |
| PyArrow / Parquet / DuckDB | 버전 고정 데이터셋, 큰 기간 질의 |
| scikit-learn | Pipeline, StandardScaler, LogisticRegression, KNeighborsClassifier, RandomForest, probability calibration |
| PyMC (조건부) | Bayesian Logistic 모델 비교 및 불확실성 |
| XGBoost / LightGBM (조건부) | 제한된 복잡도 tree boosting 비교 |
| exchange-calendars | 시장 달력 + 공식 일정 검증 |
| 자체 event-driven backtest | 실제 Workflow와 동일 evaluator, virtual clock, cost/fill model |
| VADER 또는 검증된 로컬 금융 NLP 모델(후보) | 뉴스 감정 기초/금융 도메인 비교, 자동 주문 신호는 별도 검증 |
| Git commit + manifest + skops/안전한 모델 직렬화 | 학습/배포 버전·재현성; 외부 pickle 금지 |

GPU, 유료 LLM API, 분산 학습, 대형 feature store는 기본 불필요. 초기 모델은 최근 3년 완전 거래 주로 표본이 약 150개 내외(휴장 제외 전후 달라짐)인 작은 데이터 문제로 다룬다. 복잡 모델을 기본 전략으로 채택하지 않고 시간순 baseline보다 개선되는지 확인한다.

## 2. 피처 및 주식 그룹

공급원에서 얻은 PER trailing/forward, PBR, ROE는 별도 원본 정의 및 available_at 저장. OHLCV 기반 SMA 5/20/60/120/200, EMA, 5/10/20 실제 거래일 rolling high/low, 거래량/변동성/추세/상대 강도는 산식 단위 테스트 후 계산. 장중 돌파의 기준값은 직전 확정 N봉; 확정봉 포함 EOD 산식과 분리. 기업 행동/조정 가격 버전 및 수정 자료 처리. ETF 기업 ROE 등 정의 불가 시 null.

그룹은 동일 시각/기준가의 종목별 return 먼저 계산한 뒤 평균/가중평균/중앙값, 상승·하락·보합 수 및 비율, 조건부 평균 상승/하락률·강도·coverage 및 그룹 간 차이. 시가총액 가중은 point-in-time 확보 시만 활성. 기본 strict coverage와 명시적 partial policy, group composition/version 및 weights 고정. 그룹은 매매 상품 아님. 실시간은 incremental cache 후보이나 DB 재계산 결과와 검증한다.

## 3. Friday Close 전용 연구

[전략 상세 명세](../function/friday-close-strategy.md)의 MONDAY_CLOSE, MONDAY_GAP, MONDAY_INTRADAY를 별도 라벨·모델로 구현. NASDAQ-100 ^NDX 주 분석, ^IXIC/QQQ/QLD 및 거시·그룹 보조. 실제 주문 ETF 모델과 지수 방향 모델 분리. 금요일/월요일 모두 거래 세션 존재, 초기 완전 월~금 주, ET/DST/조기 폐장. 각 target의 label_available_at이 cutoff 이전인 표본만 학습. 금요일 확정 종가 연구 모델과 금요일 장마감 이전 실거래 가능 cutoff 모델을 절대 혼용하지 않는다.

Pipeline:
1. 원본 데이터 가용성과 권한 registry → dataset manifest 고정, 결측/정정/기업행동 검증.
2. 주 단위 sample 및 point-in-time as-of join, 미래 데이터/현재 재무비율 소급 금지.
3. baseline (historical up frequency, majority, 단순 시장 패턴), L2 Logistic + scaling, KNN 유사 주.
4. 시간 순서 train/validation/test, walk-forward expanding/rolling, label 공개 시점에 따른 purge/gap. TimeSeriesSplit은 기반 도구이며 불규칙한 휴장 주·겹치는 라벨은 custom splitter로 통제한다.
5. calibration은 train 내부 시간순 holdout, Brier score/log loss/AUC/accuracy, confidence interval, coverage/abstain 및 out-of-sample 성과; 예상 수익률·하방 위험은 별도 모델/분포.
6. 비용·슬리피지·체결 가능 시각 반영, 거래비용 차감 성과, drawdown, turnover, benchmark, 표본수 및 불확실성.
7. 검증/승인된 모델만 deploy, 주간 재학습, 금요일 cutoff 추론, 월요일 결과 확정 대사. 예측·실제 관측·모델 revision 불변 저장.

뉴스 감정: 공식 IR/공시 및 허용 RSS 우선, source/published_at/available_at/article ID·hash·언어·중복·정정 처리. VADER는 일반 감정 baseline, 금융 특화 모델은 라이선스·언어·도메인 validation 후 사용. LLM/뉴스 텍스트를 명령으로 처리하지 않으며 출처와 신뢰도 낮은 정보는 UNKNOWN. PizzINT는 기존 정책상 자동 주문 트리거로 사용하지 않는다.

## 4. Backtest 및 Job

자체 deterministic replay: historical events sorted by available_at + stable tie-break, virtual clock, graph/feature/data/calendar version pin. 실제 엔진과 evaluator 공유, simulated execution adapter, 수수료/슬리피지/spread/세션/부분체결/거래 가능 종목 및 position limits. 주문 시점보다 앞선 체결 가격을 참조하지 않음. 조정가격 연구와 실제 체결 가격 구분. vectorized pandas 연구는 후보 탐색 보조이며 최종 Workflow backtest는 상태형 이벤트 replay.

CPU job worker는 기간/자원/동시 실행 제한, progress/cancel checkpoint, artifact checksum. ML 실험 레지스트리는 PostgreSQL + manifest 초기 선택; MLflow는 실험 규모에 따라 도입. seed, 코드 commit, lock hash, input dataset, feature definitions, cutoff, hyperparams, metrics, model artifact hash, 승인자 기록.

## 5. 검증

[그룹 명세](../function/stock-groups.md), [Friday 전략](../function/friday-close-strategy.md), [재무/이동평균](../indicator-collection/YFinance_Valuation_and_Moving_Averages.md). 미래정보 주입 테스트, 생존편향/누락/정정, 휴장/DST, walk-forward 분할 검증, baseline 비교, 재현성, 부족한 표본 시 배포 금지. 모델 성과·승률을 구현 전 약속하지 않는다.

[scikit-learn TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html) · [statsmodels](https://www.statsmodels.org/) · [scikit-learn model persistence](https://scikit-learn.org/stable/model_persistence.html)
