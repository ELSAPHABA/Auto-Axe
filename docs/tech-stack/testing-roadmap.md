# 검증 전략 및 단계별 기술 도입

## 1. 테스트 구성

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

| 단계 | 산출물 | exit criteria |
|---|---|---|
| 0. 기술 검증 | uv/pnpm/SDK 호환 matrix, Compose dev, DB/CI skeleton, ADR | Python/Node/nhplug/MCP/DB 설치 및 smoke, 라이선스 검토 |
| 1. 수집·저장 기반 | registry, collector adapters, migrations, durable event/quality, CLI migration | 기존 Binance/yfinance/Treasury PoC parity, reconnect·dedupe·stale·permission gate |
| 2. 전체 지표 및 대시보드 | 주식 1Hz, 기업지표/고저가, Nasdaq/DRAM/SEIBro/위칭, UI | 권한 확인 소스 활성화, 미검증 표시, 실시간 갱신/계약 테스트 |
| 3. 그룹/Workflow Core | graph/version/dependency, node engine, reset/latched/continuous, editor, dry-run | 순차/논리/분기/재사용/중단·리셋·경쟁·재시작 검증 |
| 4. 전체 트리거/분석 | P0~P2 기존 기능, 그룹 집계, 예측/백테스트 Job, Friday UI, 알림/성과 | point-in-time/replay·비용·walk-forward·버전, 부족 데이터 fail closed |
| 5. NHPLUG paper | 독립 조회 MCP, SDK Executor 모의, 주문 원장/리스크/대사 | 공식 계약 및 모의 권한 검증, UNKNOWN 재전송 차단, kill/recovery |
| 6. 통합 MCP | 10 도메인 Tools/Resources/Prompts, local/remote, IdP/권한 | 로컬·실제 외부 Host, OAuth/권한/폐기, 직접 주문 거부, job 상태 일관 |
| 7. 운영 검증 | Compose staging/prod, backup, metrics, load, security | 복원/배포 rollback, 권한 및 환경 격리, 운영 절차; LIVE 여전히 별도 승인 |
| 8. LIVE(조건부) | 명시적 승인된 운영 Executor | 사용자 승인, 계좌/한도/거래 유형/모의 성과/대사/리스크·데이터권한 검증 전 비활성 |

읽기 MCP 기반은 1~2단계부터 병행 가능, 도메인 기능 완성에 따라 등록한다. 단계 순서는 기능 축소가 아니다. 기존 명세의 수용 테스트는 모두 유지하며 완료 기준에 매핑한다.

## 3. 우선 검증할 미확정 사항

- 정확한 Python/Node 및 SDK major/minor 교집합, MCP revision/Host OAuth discovery·등록·audience 상호운용성.
- MEXC Protobuf 전환/실제 구독·지연, yfinance NVDA/QLD 1Hz 샘플 원본 빈도, 공급자 이용·저장·자동거래 권한, 승인형 Scrapling 파서·실제 릴리스/브라우저 sandbox 및 egress 통제 호환성.
- 정확한 NHPLUG 주문 API·상품/모의 지원, 수수료·계좌별 한도·체결 대사 및 idempotency 기능, 종목 master 형식.
- 시계열 행수/retention·저장 및 백업 규모, PostgreSQL queue p95·동시성, 목표 장비/예산/도메인, RPO/RTO.
- 주간 모델에 충분한 point-in-time history 확보, 백테스트 baseline과 검증 임계값, 뉴스 감정 모델 권한·평가.
- 사용자 지정 리스크 한도·LIVE 활성화·원격 MCP client 정책. 초기 기본 비활성.

## 4. 요구사항 추적

[기능 명세 FR](../function/specification.md) → [수집](./data-collection.md) / [Frontend](./frontend.md) / [Workflow](./workflow-engine.md) / [분석](./quant-analytics.md) / [주문](./trading-integration.md) / [MCP](./mcp-security.md)로 매핑하고 구현 이슈마다 FR/수용 테스트 ID를 기록한다. ADR 변경 시 해당 문서 및 API/event schema와 테스트를 함께 수정한다.
