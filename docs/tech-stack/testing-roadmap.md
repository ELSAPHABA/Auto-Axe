# 검증 전략 및 단계별 기술 도입

## 1. 테스트 구성

실행 계약의 필수 검수: 조건 충족 시 관련 타 조건 즉시 갱신 및 committed snapshot 재평가, refresh dedupe/timeout/원본 TTL(VIX 10초), 토스증권 2Y 우선 및 실패 시에만 Treasury 임시 fallback/복귀, source series 분리, 사전·개별 승인, Order Coordinator priority/매수·매도별 최대량·예약·충돌, reset/retry 멱등 키, 5개 모드 원장 격리, MCP disconnect/client revoke와 거래 승인 철회 구분. 합성 fixture로 우선 검증하고 실제 제공자·브로커 권한과 호환성 검증 전 LIVE 차단.

| 영역 | 도구·검증 |
|---|---|
| Python 단위 | pytest, pytest-asyncio, Hypothesis; 계산·parser·state transition, UNKNOWN·idempotency·달력 속성 |
| TypeScript | Vitest, Testing Library, strict tsc, ESLint; 노드·폼·차트 상태 |
| DB 통합 | Testcontainers PostgreSQL, Alembic upgrade, real transaction/lock/unique/FK, concurrent worker crash |
| 공급자 계약 | 허용 fixture, respx/httpx mock, WS fake server, response schema/version, 429/5xx/late/gap |
| 프론트 E2E | Playwright; 편집/참조/활성 상태/SSE/reconnect/접근성/반응형 |
| MCP | MCP Inspector, 실제 Host의 stdio/Streamable HTTP/OAuth, 권한·취소·capabilities |
| 보안/공급망 | Trivy/SBOM, Gitleaks, pip-audit/npm audit, OWASP ZAP staging, 악성 request/Origin/SSRF/role tests, scraper egress 및 격리 테스트; [SEC 수용 기준](./security.md) |
| 성능 | k6 또는 Locust(초기 k6), 합성 tick/1Hz/그래프/동시성, latency/backlog/resource |
| Trading | fake SDK, sandbox contract, stop race, timeout/UNKNOWN/partial fill/reconciliation, 모드 분리 |
| 운영 | process kill/restart, DB restore/PITR, replay, migration, credential rotation, degraded mode |

실측·검증은 별도 작업이다. PR CI는 합성/허용 fixture만 사용하고 real broker credential 없음. 외부 실시간 피드/모의 계좌 검증은 환경과 권한 확인 후 opt-in. 실제 사용자/계좌 데이터 fixture 금지.

## 2. 개발 단계 및 완료 기준

아래 Phase 0~8이 유일한 전역 개발 로드맵이다. 개별 기능 명세의 세부 작업 순서는 해당 Phase 내 하위 작업으로 관리한다. 선행 의존성을 충족한 작업은 병렬화할 수 있다. [공통 기술 계약](./contracts.md) §10의 테스트를 Phase별 완료 기준에 포함한다.

| 단계 | 산출물 | exit criteria |
|---|---|---|
| Phase 0 — 기술 검증 및 개발 환경 | uv/pnpm/SDK 호환 matrix, Compose dev, DB/Role 및 CI skeleton, OpenAPI 3.1/JSON Schema/Event Envelope 초기 fixture 및 생성 파이프라인 | Python/Node/nhplug/MCP/DB smoke, 라이선스, OpenAPI→TS drift, DB 격리·Decimal/UTC 계약 검증 |
| Phase 1 — 수집·저장 기반 | registry, collector adapters, migrations, durable event/quality, cross-DB outbox/inbox, CLI migration | 기존 Binance/yfinance/Treasury PoC parity, reconnect·dedupe·stale·permission gate |
| Phase 2 — 전체 지표 및 대시보드 | 주식 1Hz, 기업지표/고저가, Nasdaq/DRAM/SEIBro/위칭, Scrapling Job/Result API, 대시보드/BFF/SSE | 권한 확인 소스 활성화, 미검증 표시, 실시간 갱신/계약 테스트 |
| Phase 3 — 그룹/Workflow Core | versioned graph schema/dependency, node engine, reset/latched/continuous, 즉시 갱신, editor, dry-run | 순차/논리/분기/재사용/중단·리셋·경쟁·재시작 검증 |
| Phase 4 — 전체 트리거/분석 | P0~P2 기존 기능, 그룹 집계, 예측/백테스트 Job, Friday UI, 알림/성과 | point-in-time/replay·비용·walk-forward·버전, 부족 데이터 fail closed |
| Phase 5 — NHPLUG PAPER_BROKER 및 PAPER_LOCAL | 독립 조회 MCP, SDK Executor 모의, Order Coordinator, 승인·주문 원장/리스크/대사 | 공식 계약 및 모의 권한 검증, UNKNOWN 재전송 차단, kill/recovery |
| Phase 6 — 통합 MCP | 10 도메인 Tools/Resources/Prompts, local/remote, IdP/권한 | 로컬·실제 외부 Host, OAuth/권한/폐기, 직접 주문 거부, job 상태 일관 |
| Phase 7 — 운영 검증 | Compose staging/prod, backup, metrics, load, security | 복원/배포 rollback, 권한 및 환경 격리, 운영 절차; LIVE 여전히 별도 승인 |
| Phase 8 — LIVE(조건부) | 명시적 승인된 운영 Executor | 사용자 승인, 계좌/한도/거래 유형/모의 성과/대사/리스크·데이터권한 검증 전 비활성 |

읽기 MCP 기반은 Phase 1~2부터 병행 가능, 도메인 기능 완성에 따라 등록한다. 단계 순서는 기능 축소가 아니다. 기존 명세의 수용 테스트는 모두 유지하며 완료 기준에 매핑한다.

## 3. 우선 검증할 미확정 사항

- 정확한 Python/Node 및 SDK major/minor 교집합, MCP revision/Host OAuth discovery·등록·audience 상호운용성.
- MEXC Protobuf 전환/실제 구독·지연, yfinance NVDA/QLD 1Hz 샘플 원본 빈도, 공급자 이용·저장·자동거래 권한, 승인형 Scrapling 파서·실제 릴리스/브라우저 sandbox 및 egress 통제 호환성.
- 정확한 NHPLUG 주문 API·상품/모의 지원, 수수료·계좌별 한도·체결 대사 및 idempotency 기능, 종목 master 형식.
- 시계열 행수/retention·저장 및 백업 규모, PostgreSQL queue p95·동시성, 목표 장비/예산/도메인, RPO/RTO.
- 주간 모델에 충분한 point-in-time history 확보, 백테스트 baseline과 검증 임계값, 뉴스 감정 모델 권한·평가.
- 사용자 지정 리스크 한도·LIVE 활성화·원격 MCP client 정책. 초기 기본 비활성.

## 4. 요구사항 추적

[기능 명세 FR](../function/specification.md) → [수집](./data-collection.md) / [Frontend](./frontend.md) / [Workflow](./workflow-engine.md) / [분석](./quant-analytics.md) / [주문](./trading-integration.md) / [MCP](./mcp-security.md)로 매핑하고 구현 이슈마다 FR/수용 테스트 ID를 기록한다. ADR 변경 시 해당 문서 및 API/event schema와 테스트를 함께 수정한다.
