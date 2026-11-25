# 공통 기술 계약

> 구현 기준. REST/MCP, Workflow, 이벤트, 데이터 및 서비스 경계를 정의한다. 실제 OpenAPI 파일·JSON Schema·migration·코드 생성물은 관련 Phase에서 본 계약에 따라 작성·검증한다. 예시는 합성 데이터이며 실제 시세·거래가 아니다. 기존 기능·거래 승인·수집 권한 정책을 변경하지 않는다.

## 1. REST API 및 공통 DTO

FastAPI/Pydantic 모델이 REST 계약의 단일 원천이며 OpenAPI 3.1 문서를 결정론적으로 생성한다. `packages/contracts/openapi.json`을 저장하고 `openapi-typescript`로 TypeScript 타입을 생성한다. 수동 복제 타입은 금지하고 UI 도메인 표현만 별도 adapter로 매핑한다. CI는 schema/type 재생성 diff, 호환성 검사, Python/TS 계약 테스트를 수행한다. Swagger UI 및 OpenAPI 공개 범위는 기존 인증·보안 정책을 따른다.

- 공용 경로 `/api/v1/`, 명시적인 method/operationId, stable resource ID, 요청·응답·오류·페이지·보안 scheme을 명세한다. MCP는 동일 Application Service/DTO/인가를 이용하되 JSON-RPC 및 MCP 프로토콜 자체의 형식을 보존한다.
- 일반 응답은 `{data, meta}`, 목록은 `{data, meta: {next_cursor, ...}}`, 변경 응답에는 resource ID/version 및 request_id. 장기 작업은 HTTP 202와 job_id/status, 204는 본문 없음.
- 오류는 `{error: {code, message, reason, retryable, request_id, details?}}`. 400 invalid request, 401 unauthenticated, 403 forbidden, 404 not found(타인 자원 열거 방지), 409 conflict/version/idempotency mismatch, 422 schema/domain validation, 429 rate limit(Retry-After), 503 dependency unavailable. FastAPI validation 오류도 공통 형식으로 변환. stacktrace/비밀 노출 금지.
- 변경 요청은 해당 use case의 expected_version과 Idempotency-Key를 적용한다. 키는 actor/resource/action/mode 및 canonical payload hash와 결합하고 동일 요청은 원래 결과, 다른 payload는 CONFLICT. 인증 actor는 서버가 결정한다.
- 호환 가능한 optional 필드 추가는 consumer 계약 검증 후 허용한다. 기존 의미·타입 변경은 migration 및 version 변경, breaking REST 변경은 새 major path로 분리. ID/enum 의미 재사용 금지.

## 2. Workflow 그래프 JSON 계약

JSON Schema Draft 2020-12를 사용한다. `packages/contracts/workflow/v1.schema.json` 및 노드 catalog의 버전별 schema를 저장한다. Pydantic discriminated union에서 schema를 생성/검증하고 편집기·REST/MCP import/export·Workflow Engine·백테스트가 동일 계약을 사용한다. schema_version은 형식 버전, workflow_version은 전략 불변 버전, node_schema_version은 노드별 설정 규격이다. 마이그레이션은 새 draft만 생성하며 배포/실행/백테스트에 고정된 원본은 불변이다.

| 영역 | 필드 |
|---|---|
| Workflow | schema_version, workflow_id, workflow_version, name, mode, priority, reset_policy, execution_policy, risk_profile_ref, dependency_refs |
| Node | node_id, node_type, node_schema_version, config; typed input/output ports, condition policy/source pin/freshness |
| Edge | edge_id, source_node_id, source_port, target_node_id, target_port |
| 참조 | workflow/group/node catalog/calendar version, indicator/series IDs, 승인된 모델 버전 정책 |
| Presentation | 별도 presentation_version, node positions, viewport, layout, UI-only labels |

mode enum은 BACKTEST, DRY_RUN, PAPER_LOCAL, PAPER_BROKER, LIVE. PAPER는 표시용 집계다. 각 모드의 배포/run은 mode/계좌/위험 정책을 별도 불변 설정으로 고정하고 다른 모드 승인·상태를 재사용하지 않는다. graph의 mode와 요청된 실행 모드는 일치해야 한다. 승인 해시는 실행 graph/config/dependencies/mode/risk policy를 포함하며 UI 좌표는 제외한다. canonical payload는 버전 지정 UTF-8 직렬화(객체 키 정렬, Decimal 문자열·UTC timestamp 정규화, 배열 순서 유지)의 SHA-256으로 계산한다. NaN/Infinity/중복 JSON key 금지.

간략 예시(실제 node catalog 및 risk/approval/port validation 별도):

```json
{
  "schema_version": 1,
  "workflow_id": "wf_001",
  "workflow_version": 3,
  "mode": "PAPER_LOCAL",
  "priority": 50,
  "reset_policy": {"business_days": 5, "calendar_id": "XNYS", "calendar_version": "fixture-1", "timezone": "America/New_York"},
  "nodes": [
    {"node_id": "c1", "node_type": "indicator", "node_schema_version": 1,
     "config": {"indicator_id": "VIX", "operator": "LTE", "threshold": 20, "freshness_seconds": 10}},
    {"node_id": "n2", "node_type": "condition_result", "node_schema_version": 1, "config": {}}
  ],
  "edges": [
    {"edge_id": "e1", "source_node_id": "c1", "source_port": "result", "target_node_id": "n2", "target_port": "condition"}
  ]
}
```

구조 검증 외 서버 graph semantic validation(포트·타입·필수 입력·순환·참조·권한·한도·조건 호출 부작용 금지) 필수. 임의 eval/코드 실행 금지. [Workflow 실행](./workflow-engine.md) 및 [기능 명세](../function/trading-workflow.md)를 적용한다.

## 3. Common Event Envelope

Pydantic discriminated payload models 및 versioned JSON Schema를 `packages/contracts/events/`에 생성한다. 이벤트는 사실/상태 변화이며 명령과 구분한다. event_type 이름을 통일한다(DB outbox column도 동일). aggregate version은 동일 origin DB/aggregate 내 단조 증가 값이며 전역 commit 순서가 아니다.

| 필드 | 의미 |
|---|---|
| event_id, event_type, schema_version | 고유 immutable ID, 종류, payload 계약 버전 |
| origin_db, aggregate_type, aggregate_id, aggregate_version | 원장/집계 식별 및 순서 |
| source, series_id, source_event_at | 외부 관측의 출처·원본 시계열·원본 시각; 비해당/미확인 null |
| occurred_at, available_at, committed_at | 도메인 발생·이용 가능·영속화 기록 시각; committed_at은 전역 순서 근거 아님 |
| correlation_id, causation_id | 요청/원인 연결(최초 causation_id null) |
| mode, account_ref | 비거래 이벤트 null, 실행 이벤트 mode 및 해당 계좌 |
| payload | event_type별 typed payload; Decimal 문자열, 비밀 및 권한 제한 자료 제외 |

```json
{
  "event_id": "evt_fixture_001",
  "event_type": "market.price.updated",
  "schema_version": 1,
  "origin_db": "autoaxe_market",
  "aggregate_type": "market_series",
  "aggregate_id": "GOLD_BINANCE_PERP",
  "aggregate_version": 42,
  "source": "binance",
  "series_id": "GOLD_BINANCE_PERP",
  "source_event_at": "2026-11-25T14:30:00Z",
  "occurred_at": "2026-11-25T14:30:00Z",
  "available_at": "2026-11-25T14:30:00.120Z",
  "committed_at": "2026-11-25T14:30:00.150Z",
  "correlation_id": "corr_fixture_001",
  "causation_id": null,
  "mode": null,
  "account_ref": null,
  "payload": {"symbol": "XAUUSDT", "price": "4100.50", "currency": "USDT"}
}
```

초기 이벤트 catalog: market.price.updated, indicator.updated(정정/revision 포함), condition.satisfied, refresh.requested, refresh.completed, workflow.reset, workflow.stopped, order.intent.created, order.conflict.detected, order.filled(부분체결 및 broker fill ID), job.status.changed, authorization.revoked.

생산자의 상태 변경과 outbox는 같은 DB transaction. 전달은 at-least-once, 소비자는 event_id unique inbox와 local state/outbox를 원자 커밋 후 ack. duplicate/late/gap/unsupported schema는 재시도/격리, 필수 신호는 UNKNOWN 또는 fail closed. 소비자 checkpoint를 영속화하고 미전달 행을 재탐색한다. cross-DB 순서는 수신 모드의 durable ingress/evaluation_seq로 기록하며 과거 주문을 소급 변경하지 않는다. 전송 retry와 외부 주문 재시도를 구분한다.

## 4. 데이터 타입 및 시간

| 의미 | Python / PostgreSQL | JSON/TypeScript |
|---|---|---|
| 가격·수량·잔고·수수료·체결금액·실제 손익 | Decimal / NUMERIC(상품별 precision/scale) | canonical decimal string / string |
| 개수·순번·영업일 | int / INTEGER 또는 BIGINT | 안전 정수 범위 내 number, 범위 초과 BIGINT는 string |
| 통계 수익률·피처·예측 확률 | float64 / DOUBLE PRECISION | finite number |
| 시각 | aware datetime / TIMESTAMPTZ | ISO 8601 UTC(Z), 원본 timezone/session 별도 |
| ID·통화·단위·enum | typed ID/string | string/enum |
| 결측 | None / NULL | null + quality/reason |

Decimal을 float에서 직접 생성하지 않고 원본 문자열로 파싱한다. 반올림/tick/lot/scale은 상품·거래소·브로커 규칙을 명시 적용하며 임의 절삭/축소 금지. JavaScript number는 금융 원장 권위 연산에 사용하지 않는다. 퍼센트·%p·bp·통화/USDT 및 계약을 별도 단위로 보존한다. NaN/Infinity는 저장/전송하지 않고 null+quality로 정규화한다. UTC와 시장 로컬 calendar/DST, source_event_at/available_at/received_at/ingested_at을 구분한다.

## 5. Database 및 Role 분리

초기 PostgreSQL 17 단일 인스턴스 내 별도 Database와 login role을 구성하고 필요 시 LIVE 인스턴스를 물리적으로 분리한다. 단일 인스턴스는 HA나 OS 수준의 완전 격리가 아니다.

| Database | 소유 데이터 |
|---|---|
| autoaxe_dev / autoaxe_test | 개발/자동 테스트, 합성 데이터 및 별도 역할; 운영 자격증명 없음 |
| autoaxe_market | 공통 허용 시장 데이터·series/catalog/수집 Job/outbox |
| autoaxe_app | Auto-Axe 권한·사용자 매핑, BFF 세션, draft/공통 정의와 버전, 배포 참조 registry, control Job/outbox |
| autoaxe_backtest | BACKTEST 데이터셋/모델/연구 및 실행·재생 상태/가상 원장 |
| autoaxe_dry_run | DRY_RUN 실행·의도·이력, 브로커 주문/체결 없음 |
| autoaxe_paper_local | PAPER_LOCAL Workflow/시뮬레이터/위험·가상 주문 원장 |
| autoaxe_paper_broker | PAPER_BROKER Workflow/공식 모의 주문·체결·위험 원장 |
| autoaxe_live | LIVE Workflow/승인/주문·체결·위험 원장 |
| autoaxe_identity | Keycloak 전용 DB, Auto-Axe 앱 세션과 별개 |

공통 정의는 app DB에서 관리하고 승인된 불변 graph/group/model/calendar/risk 버전과 입력 reference를 대상 모드 DB에 snapshot/import한다. mode DB 내부 Workflow 실행·node state·order intent·승인 grant·위험 예약·주문/체결·Kill Switch·outbox·inbox·감사는 같은 transaction boundary에 둔다. mode DB가 원장 소유자이며 UI/API/MCP 집계는 인가된 read projection으로 조회한다. BACKTEST/DRY_RUN에는 해당 모드 실행 및 필요한 가상/의도 상태만 저장한다.

DB 사이 PostgreSQL FK/단일 ACID transaction을 가정하지 않는다. 공통 시장 데이터는 immutable observation ID/revision/available_at 및 제한 read/이벤트 계약으로 이용한다. 정의/참조/배포는 control DB의 version 및 durable reference reservation을 먼저 확정하고 mode DB가 idempotent import/ack; terminal 실행/실패 대사 뒤 예약 해제. 삭제와 배포 경쟁은 control registry transaction에서 직렬화하고 대기/불명 예약이 있으면 삭제 차단. cross-DB 전달은 outbox/inbox 및 retry/reconciliation으로 처리한다. 승인/권한 철회는 해당 mode gate에 durable revoke/fence를 반영한 뒤 완료로 표시한다. 공통 인가 상태 확인 불가 또는 동기화 불일치 시 신규 주문 차단; 제출 중 주문은 대사한다. MCP client 폐기만으로 독립 승인 전략을 중단하지 않는다.

PUBLIC CONNECT/기본 권한 제한, DB별 owner/migration/runtime/read/relay/Executor role 분리. runtime superuser/CREATEDB/CREATEROLE 금지. 모드별 credential/pool/allowlist 및 연결 시작 시 환경 검증; LIVE Executor에 paper/dev 쓰기 권한 없음, 역방향도 금지. API는 해당 use case별 제한 role/권한으로 접근하며 브로커 비밀 없음. 스크래퍼 DB 연결 불가. 복원/backup/PITR 후 모드별 일관성 및 브로커 대사 확인 전 LIVE 재무장 금지.

## 6. BFF 인증 세션 저장소

Keycloak은 OIDC/OAuth 사용자 인증·MFA·토큰 발급 담당. FastAPI BFF는 `autoaxe_app.identity.web_sessions`에 opaque random session ID의 hash, principal_ref, token reference 또는 암호화된 서버측 token, created/last_seen/idle/absolute expiry, CSRF secret/reference, authorization version, revoked_at을 영속화한다. 쿠키는 HttpOnly/Secure/SameSite, 좁은 scope, 세션 식별자만 저장한다. 로그인/권한 변경 시 회전, logout/revoke server state 검사, CSRF/Origin 검증, 만료 청소 및 동시 갱신 잠금. 토큰 암호화 키는 DB/backup과 별도 secret, 로그/trace에 원문 금지. 기존 보안 정책의 세션 시간 기준을 적용한다.

Valkey는 선택적 cache/알림이며 session authority가 아니다. 폐기된 세션을 캐시로 재허용하지 않는다. DB/인가 확인 불가 시 보호 요청 차단. MCP 원격 OAuth 및 stdio 신원은 BFF cookie와 분리하고 공통 권한 정책을 사용한다.

## 7. Scrapling Job/Result 내부 API

FastAPI private scrape-broker에서 `/internal/v1/scrape/jobs/claim`, `/internal/v1/scrape/jobs/{job_id}/heartbeat`, `/internal/v1/scrape/jobs/{job_id}/result`를 구현한다. collector/scheduler가 durable job을 등록하고 isolated worker가 pull/claim한다. 내부 mTLS 서비스 인증(전용 인증서/identity, rotation), 작업 scope 및 lease/fencing token을 적용한다. worker는 broker 외 내부 접근·DB/브로커 비밀이 없다.

- 요청: job_id, source_id, adapter_version, schema_version, 허용 enum/range parameters, deadline_at, timeout_seconds, permission/mapping version, job nonce 및 lease token. 사용자 임의 URL·코드·shell/SQL/파일 경로 금지.
- 결과: job_id, source_id, adapter_version, lease token, status, source timestamps, collected_at, observation candidates(typed unit/value/provenance/quality), error_code/retryable. 응답 크기/개수 제한. raw evidence는 권한/보존 정책에 맞는 참조만.
- broker는 worker 신원·lease/nonce/source/adapter/권한·크기·schema를 재검증하고 만료/철회/중복 결과를 거부 또는 기존 처리 반환. validation writer만 적재 및 outbox 기록. lease 만료 회수·제한 retry·heartbeat·deadline·결과 멱등성. 외부 통신은 [수집](./data-collection.md) 및 [보안](./security.md)의 최신 정책을 따른다.

## 8. SSE Snapshot + Version

브라우저 기본 복구는 REST snapshot + SSE delta/invalidation. 장기 SSE replay 저장소는 초기 필수 아님. 동일 origin BFF cookie, 서버 권한 확인, heartbeat/bounded buffer.

1. 구독 ready 후 이벤트를 버퍼링하면서 snapshot을 조회한다. snapshot은 resource/aggregate ID, mode, version(또는 version vector), as_of를 포함한다.
2. delta의 aggregate version이 snapshot 이하이면 무시, 연속 버전이면 적용. 누락/역전/overflow/권한 변경/미지원 schema/coalesced invalidation은 snapshot 재조회. 복수 aggregate별 version을 관리하며 전역 commit cursor로 오용하지 않는다.
3. 재접속 시 항상 snapshot 재동기화 및 reconnecting/stale 표시. Last-Event-ID는 보조이며 장기 replay를 보장하지 않는다. Workflow 실행은 UI 연결과 독립.
4. TanStack Query key는 account/mode/resource/version/기간 구분. UI coalescing은 표시 최적화만 허용하고 원본·업무 이벤트·평가 로그는 원장에 남긴다. 상세 로그는 cursor pagination REST.
5. snapshot/delta 모두 인가 검사, 세션 만료/폐기 시 stream 종료. 권한 상실 cache 제거. DB/인가 장애 시 과거 화면을 정상 상태로 표시하지 않는다.

## 9. Frontend 필수 및 선택 라이브러리

필수: React, TypeScript, Vite, React Router, TanStack Query, Zustand, Tailwind CSS/CSS variables, @xyflow/react(React Flow), TradingView Lightweight Charts, Apache ECharts, TanStack Table/Virtual, React Hook Form/Zod. 개발/검증 필수: Vitest, Testing Library, Playwright(UI E2E), TypeScript/ESLint/Prettier. ELK.js 자동 레이아웃은 선택이며 실행 순서 변경 금지. 수집 프레임워크 Scrapling과 UI E2E Playwright를 구분한다. 라이선스/버전은 Phase 0에서 검증한다.

## 10. 구현 단계 및 계약 검수

전역 개발 단계는 [testing-roadmap.md](./testing-roadmap.md)의 Phase 0~8만 사용한다. 도메인 세부 작업은 해당 Phase의 하위 작업으로 관리하며 선행 의존성 충족 시 병렬 개발 가능. Phase 0에서 OpenAPI/TS 생성, schema version, DB/role skeleton 및 계약 fixture를 검증하고 실제 도메인 스키마는 관련 Phase에서 완성한다.

| 검수 | 필수 수용 기준 |
|---|---|
| API | OpenAPI/TS drift, strict compile, 오류 매핑, pagination/version/idempotency |
| Graph | 구조/semantic validator, migration, 승인 해시와 presentation 분리, UI/API/MCP/backtest round-trip |
| Event | schema/duplicate/late/gap/unknown version, outbox/inbox crash/recovery, cross-DB 실패 주입 |
| 데이터 | Decimal precision/round-trip, UTC/DST, invalid number/null quality |
| DB | CONNECT/role, 잘못된 모드/credential, cross-mode 쓰기 차단, 참조 삭제 경쟁/revoke fence |
| 세션 | fixation/expiry/revocation/CSRF 및 DB 장애 fail closed |
| Scraper | mTLS/lease/nonce/권한/크기/schema/중복 결과와 격리 |
| SSE | 최초 snapshot race, gap/duplicate/overflow/reconnect, 권한 철회, cache 모드 분리 |
| Frontend/로드맵 | 필수 UI 기능/라이선스/빌드, Phase별 수용 기준, LIVE 별도 승인 |

[API](./backend.md) · [DB](./data-storage.md) · [Workflow](./workflow-engine.md) · [보안](./security.md) · [Frontend](./frontend.md)
