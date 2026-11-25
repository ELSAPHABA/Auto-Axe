# Workflow 실행 엔진 기술 설계

> [확정 Workflow 기능](../function/trading-workflow.md), [그룹](../function/stock-groups.md), [금요일 전략](../function/friday-close-strategy.md)을 구현하기 위한 기술 명세. n8n·ComfyUI는 UI 레퍼런스이며 매매 실행 엔진으로 사용하지 않는다.

## 1. 기술 선정

Python typed dataclass/Pydantic graph DTO, 자체 event-driven 상태 머신, PostgreSQL 영속 상태·outbox·checkpoint. graph 검증에는 Python graphlib 및 필요 시 NetworkX(순환/의존성/경로 분석)를 사용한다. APScheduler는 기동 보조, exchange-calendars는 달력 계산 후보. Airflow는 배치 DAG 중심, n8n은 범용 자동화, Temporal은 내구 실행 기능이 있으나 현재 복잡한 장중 상태/그래프/리스크 제약의 도메인 의미를 대신하지 못하고 초기 운영 부담이 커 보류. 동일 거래 상태와 주문 원장 위에서 deterministic replay를 먼저 구현한다.

## 2. 실행 계약

Graph version: graph_id, version, node_types/schema versions, edges, output ports, dependencies, calendar/reset policy, deployment status. 저장 전 schema/port/type/required input/Fork-Join/순환/참조 검증. dependency의 reverse index, 참조 중 삭제 금지(초안·저장본·배포본·활성 실행), version pin. 동일 조건 재사용은 parent run과 독립 invocation/activation state, 결과 포트 TRUE/FALSE/UNKNOWN만. 참조 순환·깊이 제한, 하위 호출 실패/timeout은 UNKNOWN. 조건용 하위 Workflow에서는 매매 등 side effect 차단.

Node registry: Market/Indicator/Group/Prediction/Condition/Logic/Control/Stateful/Action/Stop/Notification 등 기존 명세 전체. node evaluator는 typed inputs, EvalContext(event_at, available_at, run_id, graph_version, clock, reset_epoch), prior_state → result(new_state, raw_result, effective_result, emitted_actions) 형태로 테스트 가능한 순수 평가를 우선한다. I/O는 adapter/use case로 분리. arbitrary eval/exec 또는 외부 코드 실행 금지.

| 논리 | 정책 |
|---|---|
| AND | FALSE 우선, 모두 TRUE면 TRUE, 나머지 UNKNOWN |
| OR | TRUE 우선, 모두 FALSE면 FALSE, 나머지 UNKNOWN |
| NOT | TRUE/FALSE 반전, UNKNOWN 보존 |
| Sequential | 활성화 조건 및 prior node 상태 확인, 미선택/미평가와 FALSE 구분 |
| IF/Switch/Fork/Join | 명시적 포트·branch selection·join policy, 미선택 경로 side effect 금지 |
| LATCHED | 고유 유효 달성 사건 N회 이후 유효 기한 내 effective TRUE, 재무장·중복 방지 |
| CONTINUOUS | 현재 valid raw TRUE만 TRUE, FALSE/UNKNOWN 즉시 반영 |
| Stop | 별도 우선 감시, 신규 주문 차단, pending 처리 정책 및 알림; 자동 청산과 다름 |

raw/effective condition은 데이터 freshness/권한·위험 게이트와 구분한다. 유효 래치가 있어도 주문 시 stale/권한/위험/중단 gate를 통과해야 한다. 트리거 hit counting은 명세의 달성 사건 및 재무장 규칙 적용(동일 TRUE 샘플 반복을 N회로 세지 않음). 상승 후 하락/하락 후 상승 극값, 가격 기준 시각, cooldown, debounce, 상태 초기화는 node config+state version으로 명시한다.

## 3. 실행 및 복구

```mermaid
flowchart TD
  M[Market or schedule event] --> K[Load pinned graph and state]
  K --> X[Independent stop and data gate]
  X -->|blocked| S[Persist reason and stop state]
  X -->|allowed| V[Evaluate selected path]
  V --> T[Commit state + consumed event + outbox]
  T --> I{Order action?}
  I -->|yes| R[Durable order intent]
  I -->|no| N[Wait next event]
  R --> E[Isolated executor recheck]
```

run 단위 single-writer(짧은 transaction advisory/row lock 또는 lease + fencing, partitioned owner). 이벤트 source ordering 및 late/out-of-order policy를 명시하고 committed observation에서만 평가한다. node_state/state_version, consumed_event key, run transition, generated action idempotency key를 원자 커밋. commit 실패는 재평가 가능, 중복 intent 생성 금지. stop과 주문 제출 경쟁은 executor에서 최종 DB gate/직렬화 규칙으로 재검증하되 이미 브로커로 전송 중인 요청을 취소할 수 있다고 보장하지 않는다. crash restart는 DB checkpoint 및 pending event replay, 새 process가 예전 lease를 덮지 못하도록 fencing. UNKNOWN, 데이터 단절, 실행 버전 불일치에서 fail closed.

거래일 reset: calendar_id/version, session timezone, 1/5/20/N 세션, reset_epoch. 첫 유효 세션부터 N번째 정규장 종료 경계; scheduler가 고유 reset key 생성. reset transaction에서 횟수·래치·재무장·진행 상태를 갱신. 늦은 이전 epoch 이벤트는 현 epoch count 오염 금지. 주문·체결·미체결·Kill Switch·리스크·idempotency 보존. 중단된 run이 단순 reset으로 재활성화되지 않음. 복구 시 missed reset을 검증/재생, 세션/달력 변경 정책 기록.

## 4. 모드 및 UI

BACKTEST: virtual clock 및 historical available_at, 외부 주문 호출 금지. DRY_RUN: 현재 신호와 의도 검증, 제출 없음. PAPER: simulator 또는 승인된 모의 endpoint의 별도 adapter/계좌 원장. LIVE: 별도 명시적 승인된 Executor만, 기본 비활성. 모든 모드 동일 순수 평가기 및 graph schema, 별도 상태·계좌·artifact.

메인 활성 수는 활성/감시/대기 정의 ID dedupe, 하위 호출/과거 backtest 제외, 모드별 구분. 상세 SSE는 server snapshot, raw/effective, hit_count, required_hits, reset_epoch, expires_at, path, reason, version. UI 연결 상태는 매매 엔진의 실행 여부와 분리.

## 5. 수용 테스트

순차·논리·분기·중첩·재사용, 순환/삭제 race, TRUE 반복·중복·UNKNOWN·재무장·만료, 1/5/20/N 휴장 및 조기폐장/DST/재시작, stale gate, 동시 stop/intent, process kill 전후 commit·lease 만료·outbox 중복, 모드 격리. 모든 기존 P0~P2 트리거의 golden fixture 및 동일 입력 replay 결과 비교. 리스크·실주문 검증은 [Trading](./trading-integration.md).
