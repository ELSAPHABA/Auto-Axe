# Backend 및 Application Service 기술 명세

## 1. 기술 구성

| 기술 | 사용 |
|---|---|
| Python 3.12 / uv | asyncio 기반 서비스, 의존성 및 lockfile |
| FastAPI / Uvicorn | REST, OpenAPI 3.1, SSE ASGI |
| Pydantic / pydantic-settings | DTO 검증, 구성, 환경별 설정 |
| SQLAlchemy 2.x + psycopg 3 | async DB 접근, UoW, connection pool |
| Alembic | schema migration, 배포 전 단일 실행 |
| httpx / websockets | provider REST 및 WebSocket |
| APScheduler | 주기/cron 계산과 스케줄러 기동 보조; 업무 상태는 DB가 소유 |
| structlog / OpenTelemetry | 구조 로그·correlation·trace |

블로킹 requests/yfinance 호출은 bounded thread 또는 별도 worker로 격리한다. CPU 모델/백테스트는 process worker. AsyncSession을 task 간 공유하지 않으며 네트워크 호출을 DB 트랜잭션 안에서 장시간 유지하지 않는다. 금액·주문 수량·가격은 Decimal, 분석 float는 명시적 구분; Pydantic으로 유효성 검증, Decimal JSON 문자열과 ISO 8601 UTC 시간 사용.

## 2. API 설계

[공통 기술 계약](./contracts.md) §1~4를 적용한다. Pydantic/FastAPI에서 OpenAPI 3.1 생성 → packages/contracts/openapi.json → openapi-typescript 생성 및 CI drift 검사. 공통 응답/error envelope, schema/version, idempotency, Decimal 문자열과 UTC를 표준화한다.

| 경로(초안) | 기능 |
|---|---|
| /api/v1/market/instruments, /quotes, /ohlcv, /long-short | 상품·시세·봉·비율 |
| /api/v1/indicators, /indicators/{id}/observations | 지표 카탈로그·시계열 |
| /api/v1/groups, /groups/{id}/versions, /metrics | 그룹 CRUD 및 집계 |
| /api/v1/workflows, /workflows/{id}/versions | 초안·저장·버전·의존성 |
| /api/v1/workflows/{id}/validate, /deploy, /runs | 검증·승인·실행 |
| /api/v1/runs/{id}, /stop, /events | 상태·중단·경로 |
| /api/v1/predictions/friday-close, /models | 예측·유사 패턴·모델 |
| /api/v1/backtests, /jobs/{id} | 백테스트·작업 상태·취소 |
| /api/v1/portfolio, /trading/intents | 제한 계좌 조회·주문 의도 |
| /api/v1/collectors, /system/health, /events | 수집 관리·시스템·SSE |

예시 URI는 계약 설계안이며 기존 MCP 도구명과 1:1 URL 대응을 강제하지 않는다. 조회 cursor pagination·max window·aggregation, write expected_version + Idempotency-Key, 별도 action 권한, 표준 오류 code/reason/retryable/request_id. 인증 actor는 서버에서 결정. OpenAPI를 기준으로 프론트엔드 타입을 생성하고 CI에서 drift를 검출한다. 실주문을 직접 제출하는 일반 REST/MCP endpoint는 제공하지 않는다.

응답 예시:

```json
{
  "data": {"series_id": "VIX", "value": null, "unit": "index"},
  "meta": {
    "source": "yfinance",
    "source_event_at": null,
    "collected_at": "2026-11-25T00:00:00Z",
    "quality": "no_data",
    "permission": "unverified",
    "schema_version": 1
  }
}
```

## 3. 공통 서비스 및 동시성

BFF 세션은 autoaxe_app의 PostgreSQL 서버 세션을 사용한다. Keycloak은 인증·토큰 발급 전용이며 세션/쿠키/권한 철회는 [공통 기술 계약](./contracts.md) §6. 스크래퍼는 private FastAPI Job/Result API + mTLS 서비스 인증/lease 계약(§7)을 사용한다.

공통 API/MCP/Job 계약에 mode enum(BACKTEST, DRY_RUN, PAPER_LOCAL, PAPER_BROKER, LIVE), immutable workflow_version, reset_epoch, activation_id, source series pin/fallback policy, freshness_policy, priority 및 매수·매도별 승인 한도, approval grant/payload hash를 포함한다. 평가 응답에 evaluation_seq/evaluation_at/snapshot input refs 및 refresh_generation/status/reason, 주문 응답에 CONFLICT_HELD 및 예약/한도 사유를 제공한다. 기존 UI PAPER 집계는 서버가 두 모드를 합산한다.

[전체 플랫폼 보안 설계](./security.md)의 SEC-01~SEC-10을 적용한다. 공통 인가 계층에서 REST/MCP/Job 동일 정책, CSRF·입력 검증·리소스 단위 권한·rate limit을 적용한다. 수집 broker는 등록 source_id 기반 제한 계약만 허용하고 scraper 결과를 신뢰하지 않으며 schema·권한·출처를 재검증한 후 원장에 적재한다.

API와 MCP가 동일 use case를 호출하며 서버에서 인증·인가·소유권·승인·모드·품질을 재검증한다. Repository/UoW 인터페이스로 DB 구현을 격리한다. 버전 증가와 FK/unique 제약으로 경쟁 쓰기 방지. 저장된 Workflow 수정 시 활성 버전 불변. 읽기만 허용된 연결에서 변경 use case 호출 금지. 요청 payload에 임의 SQL·shell·파일 경로·URL을 허용하지 않는다.

## 4. Durable Job 및 이벤트

job 테이블: id, kind, owner_ref, input_ref, input_version, idempotency_key, status, attempt, max_attempts, available_at, lease_until, lease_token, heartbeat_at, progress, result_ref, error_code, created_at, finished_at. 동일 actor/kind/key와 payload hash 비교; 다른 payload는 CONFLICT. worker claim은 짧은 transaction, SKIP LOCKED, fencing token으로 종료 기록 검증. 장기 작업은 heartbeat, lease 만료 회수, exponential backoff+jitter, terminal failure, 협력적 취소. 취소 요청과 실제 종료를 구분하고 CPU 작업은 체크포인트에서 중단한다. 주문은 일반 job 재시도 규칙의 대상이 아니다.

outbox는 [Common Event Envelope](./contracts.md) §3을 사용한다: event_id, event_type, schema_version, origin_db, aggregate_type/id/version, source/series_id/source_event_at, occurred_at/available_at/committed_at, correlation_id/causation_id, mode/account_ref, typed payload. 상태 변경과 같은 transaction에 기록, consumer별 durable inbox/checkpoint, 중복 event_id 제거. commit 순서를 보장하지 않는 sequence 숫자만을 안전한 전역 high-watermark로 사용하지 않는다. relay가 미전달 행을 재탐색하고 각 aggregate version의 순서·gap을 확인한다. 각 DB의 local transaction에서 outbox/inbox를 원자 커밋한다. cross-DB 전달은 at-least-once 및 reconciliation. UI 기본 복구는 snapshot/version 재조회이다.

SSE는 [Snapshot + Version 계약](./contracts.md) §8을 적용한다. 구독 ready 이후 snapshot을 조회하고 버퍼링된 delta를 aggregate version별로 대조한다. 누락/overflow/reconnect 시 최신 snapshot을 재조회한다. Last-Event-ID는 보조이며 장기 replay는 초기 필수 아님. 동일 origin BFF cookie, heartbeat, backpressure, 권한 철회/스트림 종료, UI coalescing만 허용한다. API replica는 DB 세션/알림과 snapshot을 사용해 sticky session에 의존하지 않는다.

## 5. 공식 참조

[FastAPI](https://fastapi.tiangolo.com/) · [SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html) · [Pydantic](https://docs.pydantic.dev/) · [Alembic](https://alembic.sqlalchemy.org/) · [PostgreSQL SELECT](https://www.postgresql.org/docs/17/sql-select.html) · [APScheduler](https://apscheduler.readthedocs.io/)
