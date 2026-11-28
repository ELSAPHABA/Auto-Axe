# Auto-Axe 기술 스택

> 구현 기술 기준선(v1.0). 승인된 기능·보안·수집 권한 제약을 유지한다. 선정 기술은 구현 기준이며 실제 설치·호환성·벤치마크·배포 완료를 의미하지 않는다.

## 1. 선정 원칙

실행 정책의 구현 기준은 조건 충족 시 관련 데이터 즉시 갱신, 원본 시계열 분리·VIX TTL 10초, 토스증권 2Y 우선/실패 시 임시 Treasury fallback, 사전 전략 승인/개별 주문 승인, 계좌별 Order Coordinator 및 5개 실행 모드(BACKTEST/DRY_RUN/PAPER_LOCAL/PAPER_BROKER/LIVE), 리셋/활성화 멱등 키, MCP 연결과 자동매매 수명 분리이다. 상세 계약은 [수집](./data-collection.md), [Workflow](./workflow-engine.md), [Trading](./trading-integration.md), [보안](./security.md)에 정의한다.

- 개인/소규모 운영을 출발점으로 하여 자체 호스팅 가능한 오픈소스 중심 구성, 최소 서비스 수, 운영 비용 및 장애 복구 난이도를 우선한다. 무료 데이터 정책은 유지하며 인프라·거래 수수료까지 무료라고 가정하지 않는다.
- Python 데이터 생태계와 기존 수집 PoC, 공식 nhplug Python SDK를 활용한다. 화면과 그래프 편집은 TypeScript로 타입을 고정한다.
- 논리적으로 모듈화하되 초기에는 하나의 backend 코드베이스, PostgreSQL 인스턴스 내 Database/Role 분리 및 역할별 프로세스로 배포한다. 주문 실행기는 처음부터 독립 신뢰 경계로 분리한다.
- 원본 이벤트와 시점 정합성, 조건 상태와 주문 원장을 우선한다. UI·MCP·캐시는 진실 원장이 아니다.
- 모든 승인 기능(P0~P2)을 포함한다. 초기 단계의 구현 순서는 기능 삭제나 LIVE 거래 승인으로 해석하지 않는다.

## 2. 기술 스택 요약

| 영역 | 기본 선정 | 확장/조건부 |
|---|---|---|
| 런타임 | Python 3.12, uv, Node.js 24 LTS, pnpm | 실제 SDK·OS 호환성 확인 후 기준 조정 |
| Backend | FastAPI, Uvicorn, Pydantic, SQLAlchemy 2.x, psycopg 3, Alembic, OpenAPI 3.1, Versioned JSON Schema, Pydantic Event Envelope, openapi-typescript | 부하 확인 후 프로세스 확장 |
| Frontend | React, TypeScript, Vite, React Router, TanStack Query, Zustand, CSS variables/Tailwind CSS, @xyflow/react, Lightweight Charts, Apache ECharts, TanStack Table/Virtual, React Hook Form/Zod | ELK.js (자동 레이아웃) |
| 수집 | asyncio, httpx, websockets, yfinance, feedparser, icalendar, [Scrapling](https://github.com/D4Vinci/Scrapling) | lxml (XML), protobuf, 공식 API별 어댑터 |
| 저장 | PostgreSQL 17, native partitioning, JSONB, Parquet, PyArrow, DuckDB | Valkey (캐시·실시간 알림), 별도 분석 DB는 병목 입증 시 |
| 실행/작업 | 자체 Python 상태 머신, PostgreSQL transactional outbox·durable job table, APScheduler(스케줄 계산/기동 보조), exchange-calendars | 메시지 브로커 또는 Temporal은 별도 ADR 이후 |
| 분석/ML | NumPy, pandas, SciPy, statsmodels, scikit-learn | PyMC, XGBoost, LightGBM, CPU 우선 |
| NH나무 | 공식 nhplug-mcp(별도 Node.js 프로세스), nhplug-sdk/PyPI nhplug(격리 Executor) | API별 실제 지원 및 모의투자 검증 |
| MCP | 공식 Python MCP SDK, stdio / HTTPS Streamable HTTP, FastAPI 공통 Application Service | Host·SDK·protocol revision 호환성 고정 |
| 인증·보안 | Keycloak(OIDC/OAuth), Caddy HTTPS reverse proxy, RBAC+리소스 정책, nftables, 격리 scraper, OWASP ASVS 기반 검수 | WireGuard 관리 VPN, SOPS+age, WAF/CrowdSec는 운영 요건에 따라 |
| 인프라 | Linux, Docker Engine, Docker Compose, GitHub Actions, GHCR | 운영 확장 시 관리형 DB/객체 저장소 등 |
| 관측/QA | pytest, Hypothesis, Ruff, mypy, Vitest, Playwright, Testcontainers, Prometheus, Grafana, OpenTelemetry | Loki/Tempo는 필요한 시점에 |

데이터 수집은 Scrapling을 사용한다. fetchers extra의 브라우저 전이 의존성은 허용된 렌더링 필요 시 검증하며 Playwright는 프론트 E2E 도구로 직접 사용한다. [전체 플랫폼 보안](./security.md)은 MCP·웹·DB·스크래퍼·주문 실행기를 포괄한다.

위 런타임·DB major는 보수적인 초기 목표이며 최신 버전 강제 사용이 아니다. 보안 지원 기간·아키텍처·라이선스·SDK 의존성의 교집합을 설치 검증하고 lockfile/image digest를 고정한다. 외부 데이터 사용권과 툴의 오픈소스 라이선스는 별도 검토한다.

## 3. 문서 인덱스

[공통 기술 계약](./contracts.md)은 REST·그래프·이벤트·데이터 타입·DB/Role·BFF 세션·스크래퍼 내부 API·SSE 복구·Frontend 필수 라이브러리 및 Phase 0~8을 정의한다.

| 문서 | 범위 |
|---|---|
| [contracts.md](./contracts.md) | 공통 기술 계약 및 검수 기준 |
| [architecture.md](./architecture.md) | 프로세스·모듈 경계, 통신, 디렉터리, 도입 결정 |
| [backend.md](./backend.md) | API, Application Service, Job, 이벤트 계약 |
| [frontend.md](./frontend.md) | 화면·노드 에디터·실시간 UI 기술 |
| [data-collection.md](./data-collection.md) | 지표별 어댑터·스케줄·검증 |
| [data-storage.md](./data-storage.md) | DB 모델·파티션·시계열·백업·분석 저장 |
| [workflow-engine.md](./workflow-engine.md) | 그래프 실행·상태·리셋·복구·리스크 |
| [quant-analytics.md](./quant-analytics.md) | 그룹, 피처, 금요일 예측, 백테스트, 뉴스 |
| [trading-integration.md](./trading-integration.md) | NHPLUG 및 격리 주문 실행 |
| [mcp-security.md](./mcp-security.md) | MCP SDK, 외부 인증·인가·네트워크 |
| [security.md](./security.md) | 전체 플랫폼 위협 모델, Zero Trust 경계, 비밀, 스크래핑·주문 안전, 운영·사고 대응 |
| [infrastructure.md](./infrastructure.md) | Compose, CI/CD, 운영, 확장 |
| [testing-roadmap.md](./testing-roadmap.md) | 테스트 전략, 단계별 개발, 검수·미결정 사항 |

## 4. 기존 설계와 연결

[시스템 설계](../design/specification.md) · [프론트엔드 명세](../design/frontend.md) · [전체 기능](../function/specification.md) · [Workflow](../function/trading-workflow.md) · [주식 그룹](../function/stock-groups.md) · [금요일 전략](../function/friday-close-strategy.md) · [무료 수집 정책](../indicator-collection/Free_Data_Collection.md) · [MCP 명세](../mcp/README.md) · [NHPLUG](../nhplug/README.md)

기능·수집 권한·보안 요구사항을 충족하는 기술 기준을 적용한다. 정확한 버전·운영 파라미터는 호환성·비용·성능·보안 검증 후 고정하고 기준 변경 시 ADR 및 관련 수용 테스트를 함께 개정한다.
