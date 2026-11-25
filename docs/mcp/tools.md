# 도메인별 MCP Tool 기능 명세

> 모든 이름은 Auto-Axe가 구현할 계약이다. 외부 nhplug-mcp의 실제 이름과 구분한다. 기능 지원 여부는 서버 capabilities에서 조회한다. 기본 인가 및 공통 응답/오류 계약은 [specification.md](./specification.md), [security.md](./security.md) 참조.

표의 scope는 최소 필요 권한이며 리소스 소유권·모드·승인·데이터 이용권을 추가 검증한다. 모든 조회에 기간/개수 제한과 시점·단위 정보 적용. ID는 정규화된 내부 식별자이며 임의 경로나 브로커 비밀을 받지 않는다.

## 1. Market

| Tool | 주요 입력 | 결과 |
|---|---|---|
| market_get_quote | instrument_id, as_of? | 최신 시세·통화·비교 기준·상태 |
| market_get_quotes | instrument_ids, as_of? | 일괄 시세·종목별 오류 |
| market_get_ohlcv | instrument_id, interval, start/end, adjustment, cursor | OHLCV, 확정봉, 원본 시간 |
| market_get_volume | instrument_id, kind, period | 거래량/당일 누적량 구분 |
| market_get_long_short | futures_symbol, ratio_kind, period, start/end? | 4종 통계 및 원본 시각 |
| market_search_instruments | query, market?, type?, cursor | 상품 ID/시장/소스 |
| market_get_session | exchange, date | 세션·휴장·조기 폐장 |

scope: market:read. [무료 수집](../indicator-collection/Free_Data_Collection.md). BTC 현물과 선물 비율, 주식과 연동 파생상품, 실제 분봉과 로컬 1초 스냅샷을 혼동하지 않는다.

## 2. Indicator

| Tool | 주요 입력 | 결과 |
|---|---|---|
| indicator_list | category?, cursor | 지표 정의·단위·가용성 |
| indicator_get_latest | series_id, as_of? | 최신 관측값·품질 |
| indicator_get_history | series_id, start/end, cursor | 시계열·정정 이력 |
| indicator_compare | series_ids, period, alignment | 정렬된 비교 자료 |
| indicator_get_correlation | series_ids, window, method, as_of | 상관계수·유효 표본, 필요 시 Job |
| indicator_calculate_technical | instrument_id, indicator, params, interval, as_of | SMA/EMA/RSI/MACD 등·확정봉·워밍업 |
| indicator_get_economic_calendar | start/end, region | 예정/실제/수정 시각·값 |
| indicator_get_expiration_calendar | start/end, product, event_type | 만기·위칭·DTE |
| indicator_get_news_sentiment | instrument_id, window, source?, confidence? | 감정·신뢰도·기사 시각·모델 |

scope: indicator:read; 대규모 분석은 indicator:analyze 추가. 권한/역사 가용성/실제 제공 주기를 검증하며 미확정 자료는 UNKNOWN.

## 3. Stock Group

| Tool | 주요 입력 | 결과 / scope |
|---|---|---|
| stock_group_list | query?, cursor | 그룹 목록 / stock_group:read |
| stock_group_get_members | group_id, version | 구성·가중치 / read |
| stock_group_get_metrics | group_id, version, metric_ids, period, as_of | 그룹 수익률·시장폭·coverage / read |
| stock_group_compare | group_ids/versions, metric, period | 상대 수익률 / read |
| stock_group_create | name, members, weights, idempotency_key | 신규 초안·버전 / stock_group:write |
| stock_group_update | group_id, expected_version, patch | 새 버전 / write |
| stock_group_clone | group_id, version, name | 복제 / write |
| stock_group_delete | group_id, expected_version | 참조 제약 검사 후 삭제 / stock_group:delete |
| stock_group_get_versions | group_id, cursor | 이력 / read |
| stock_group_export | group_id, version | 안전한 JSON / read |
| stock_group_import | graph_or_members_json, idempotency_key | 검증된 초안 / write |

[그룹 명세](../function/stock-groups.md). 활성 실행에 고정된 구성은 변경하지 않는다. 삭제 시 참조 무결성 및 감사 버전 보존.

## 4. Workflow

영속 mode enum은 BACKTEST, DRY_RUN, PAPER_LOCAL, PAPER_BROKER, LIVE이다. PAPER는 UI 집계 라벨이며 입력 mode로 받지 않는다. MCP의 workflow_start는 DRY_RUN/PAPER_LOCAL/PAPER_BROKER에만 허용하고 LIVE 시작은 별도 신뢰 UI의 사람 승인·활성화 경계를 따른다. Workflow graph/settings DTO에는 priority, 종목별 1회/일별 최대 매수·매도량/금액, risk profile, source series/fallback, freshness 및 reset/activation 정책을 포함한다. 상태 조회는 refresh_generation/evaluation_seq, source provenance·TTL, CONFLICT_HELD/예약·한도 사유를 반환한다.

| Tool | 주요 입력 | 결과 / scope |
|---|---|---|
| workflow_list | filters, cursor | 목록 / workflow:read |
| workflow_get | workflow_id, version | 노드·엣지·정책 / read |
| workflow_create | name, graph, idempotency_key | 초안 / workflow:draft:write |
| workflow_update | workflow_id, expected_version, patch | 새 초안 / draft:write |
| workflow_delete | workflow_id, expected_version | 참조 해제 확인 / workflow:delete |
| workflow_clone | workflow_id, version, name | 복제 초안 / draft:write |
| workflow_list_node_types | category?, schema_version? | 노드·타입·포트 / read |
| workflow_validate | workflow_id/version 또는 graph | 오류 위치·의존성·위험 / read |
| workflow_get_dependencies | workflow_id, version?, direction | 정방향·역방향 참조 / read |
| workflow_get_status | workflow_id, run_id? | 서버 조건식 결과·경로·충족 시각, 원본/유효 조건값·달성 횟수·래치/만료·현재 주기·다음 리셋 / read |
| workflow_get_active | mode?, cursor | 활성 정의 수·실행 수 / read |
| workflow_get_logs | run_id, cursor, level? | 평가·주문 상태·감사 참조 / read |
| workflow_get_versions | workflow_id, cursor | 버전 / read |
| workflow_export | workflow_id, version | JSON / read |
| workflow_import | graph_json, idempotency_key | 검증된 초안 / draft:write |
| workflow_list_templates | cursor | 템플릿 / read |
| workflow_dry_run | workflow_id, version, inputs, as_of | 주문 없는 실행/Job / workflow:execute:dry_run |
| workflow_request_deploy | workflow_id, version, mode, risk_profile_ref | 승인 요청 / workflow:deploy:request |
| workflow_start | workflow_id, approved_version, mode, idempotency_key | 실행 ID (PAPER_LOCAL/PAPER_BROKER/DRY_RUN) / workflow:execute:paper_local, paper_broker 또는 dry_run |
| workflow_pause | run_id, reason | 일시정지 상태 / workflow:pause |
| workflow_stop | run_id, reason | 중단 래치·대사 상태 / workflow:stop |

LIVE 시작/배포는 실제 주문 지원과 별도 승인 전 차단. MCP는 승인 자체를 부여하지 않는다. [Workflow 명세](../function/trading-workflow.md): 순차/AND/OR/분기/Interrupt, 조건 전용 참조 호출, 버전 고정·순환 방지·참조 중 삭제 금지. 기존 그래프에서 AND로 연결된 조건은 모두 TRUE, OR는 하나 이상 TRUE일 때 해당 복합 조건 충족이며 조회 결과를 대시보드와 동일하게 반환한다. 하위 호출과 복수 실행의 중복 집계 금지. 조건 참조에서 실제 주문 부작용 금지.

workflow_create/update/import/export/get/validate의 그래프 계약에 조건별 satisfaction_policy(LATCHED/CONTINUOUS, required_hits, hold_until)와 Workflow reset_policy(reset_business_days=1/5/20/직접 N, calendar_id/version, timezone)를 포함한다. 서버에서 양의 정수·기간·달력·버전 및 모드 유효성을 검증한다. 기존 실행은 불변 버전을 유지한다. 조회 상태는 raw_result/effective_result, hit_count, latched_at, expires_at, reset_epoch, next_reset_at 및 기존 연결식 결과를 포함하며 UI와 동일하다. MCP 설정 변경으로 주문 원장·리스크·중단 래치를 초기화하거나 즉시 LIVE 실행을 허용하지 않는다.

## 5. Prediction

| Tool | 주요 입력 | 결과 / scope |
|---|---|---|
| prediction_get_monday_forecast | instrument_id, target, mode, as_of, model_version? | 확률·수익률·위험·보류 상태 / prediction:read |
| prediction_get_weekly_features | week_id, feature_set_version, cutoff | 주간 피처·시점 / read |
| prediction_get_similar_patterns | prediction_id, k | 과거 사례·거리 정의 / read |
| prediction_get_feature_importance | prediction_id/model_version | 기여도·단위 / read |
| prediction_get_model_metrics | model_id/version, evaluation_window | OOS·calibration·표본 / read |
| prediction_list_models | filter, cursor | 모델 버전·검증 상태 / read |
| prediction_train_model | feature_set_version, target, mode, train_window, params, idempotency_key | Job / prediction:train |
| prediction_compare_models | model_versions, evaluation_window | 비교 리포트 / prediction:read |
| prediction_get_training_status | job_id | 작업 상태 / read |
| prediction_cancel_training | job_id | 취소 요청 / prediction:train |

[금요일 종가매수](../function/friday-close-strategy.md). RESEARCH_EOD의 실주문 연결 금지, 시점 누수 차단, 학습 완료와 배포 승인을 구분한다.

## 6. Backtest

| Tool | 주요 입력 | 결과 / scope |
|---|---|---|
| backtest_create | workflow_id/version, period, universe, capital, cost_model, data_version, idempotency_key | Job / backtest:execute |
| backtest_get_status | job_id | 상태·진행률 / backtest:read |
| backtest_get_result | job_id | 성과·MDD·Sharpe·비용·가정 / read |
| backtest_get_trades | job_id, cursor | 모의 거래 / read |
| backtest_compare | job_ids | 동일 조건 비교·차이 / read |
| backtest_cancel | job_id | 취소 요청 / backtest:execute |

실제 계좌와 격리; 연구용 종가 체결 가정 및 미래정보 사용 금지. Job 결과·검증 조건 버전 보존.

## 7. Portfolio

| Tool | 주요 입력 | 결과 |
|---|---|---|
| portfolio_get_balance | account_ref, as_of? | 잔고·통화 |
| portfolio_get_positions | account_ref, cursor | 보유 수량·평균가 |
| portfolio_get_pnl | account_ref, period | 실현/미실현 손익·비용 |
| portfolio_get_history | account_ref, period, cursor | 허용 거래 이력 |
| portfolio_get_exposure | account_ref, grouping | 종목/섹터 비중 |
| portfolio_get_risk | account_ref | 한도·위험 상태 |

scope: portfolio:read 및 계좌 소유권 검증. 실제 NH 계좌 조회는 별도 read-only adapter가 검증된 이후 제공하며 upstream이 직접 제공하지 않는 손익/노출/위험은 Auto-Axe의 검증된 계산 결과다. 미구현 시 NOT_IMPLEMENTED.

## 8. Collector

| Tool | 주요 입력 | 결과 / scope |
|---|---|---|
| collector_list | cursor | 수집기·소스 / collector:read |
| collector_get_status | collector_id | 연결·수신·오류 / read |
| collector_get_health | collector_id | 지연·결측·권한 / read |
| collector_get_schedule | collector_id | 주기 / read |
| collector_refresh | collector_id, idempotency_key | Job / collector:manage |
| collector_update_schedule | collector_id, expected_version, schedule | 검증된 설정 변경 / manage |
| collector_start | collector_id | 상태 / manage |
| collector_stop | collector_id, reason | 상태 및 영향 / manage |

허가 미확인 소스 활성화 금지. 최소 호출 간격 및 비용 0 정책은 Tool로 우회할 수 없다.

## 9. System

| Tool | 주요 입력 | 결과 |
|---|---|---|
| system_get_health | service? | 상태·장애 |
| system_get_services | filter? | 등록 서비스 |
| system_get_metrics | service, window | 허용 메트릭 |
| system_get_logs | service, period, level, cursor | 마스킹된 제한 로그 |
| system_get_config | service, allowlisted_keys | 공개 가능한 설정 |
| system_get_errors | service?, cursor | 구조화 오류 |
| system_get_resource_usage | service?, window | CPU/RAM/Storage |
| system_get_capabilities | domain? | 구현 여부·모드·권한 상태·계약 버전 |
| system_get_job_status | job_id | 공통 Job 상태 |

scope: system:read, 로그는 system:logs:read, Job은 본래 작업 소유권/권한을 추가 적용. 임의 시스템 파일, 키, DB 접근·코드 실행 도구 금지.

## 10. Trading (주문 준비 및 내부 상태만)

단발 MCP 주문 의도는 MANUAL_OR_AI로 분류하며 개별 사람 승인 없이는 제출할 수 없다. 사전 승인된 AUTO_WORKFLOW의 권한을 단발 주문에 재사용할 수 없다. Executor가 Coordinator 우선순위·계좌/종목/모드 한도·예약·충돌 및 승인 상태를 검증한다. [실행 명세](../tech-stack/trading-integration.md).

| Tool | 주요 입력 | 결과 / scope |
|---|---|---|
| trading_get_orders | account_ref, mode, period, cursor | 내부 원장/허용된 조회 / trading:read |
| trading_get_fills | account_ref, mode, order_id?, cursor | 체결 조회·대사 / read |
| trading_preview_order | account_ref, instrument_id, side, qty, order_type, price? | 주문 의도 초안·예상 비용 / trading:preview |
| trading_validate_order | intent_id 또는 preview | 데이터·한도·모드 검증 / trading:preview |
| trading_create_order_intent | validated_preview_ref, idempotency_key | 주문 의도만 저장 / trading:intent:write |
| trading_request_approval | intent_id, expected_version | 사람 승인 요청 / trading:approval:request |
| trading_request_cancel | order_ref, reason, idempotency_key | 취소 의도/요청 기록만 / trading:cancel:request |

통합 MCP에는 trading_execute, trading_submit_order, 실제 정정/취소, 승인 우회 도구를 등록하지 않는다. request_cancel은 실제 취소 완료가 아니다. 실제 주문 제출·정정·취소는 사용자 승인된 nhplug-sdk 기반 독립 Trading Executor의 담당 범위다. 통합 MCP는 요청 및 상태 조회까지만 지원한다. Executor 구현·공식 API 지원 확인·모의 검증·별도 LIVE 활성화 승인 전 실주문은 불가하다. [NH 연동 경계](./nhplug-integration.md).

## 11. 계약 예시

```json
{
  "tool": "workflow_get_status",
  "arguments": {"workflow_id": "example-wf", "run_id": "example-run"}
}
```

```json
{
  "schema_version": "1",
  "request_id": "example-request",
  "status": "ok",
  "data": {
    "run_id": "example-run",
    "mode": "PAPER_LOCAL",
    "condition_expression": "A AND B",
    "result": "FALSE",
    "input_results": ["TRUE", "FALSE"]
  },
  "quality_status": "fresh"
}
```

위 JSON은 계약 예시이며 실제 MCP wire envelope 또는 현재 실행값이 아니다. 실제 JSON Schema·필수 필드·범위·enum·에러 테스트는 Tool 구현과 함께 작성한다.
