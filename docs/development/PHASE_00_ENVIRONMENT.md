# Phase 0 개발 환경 및 호환성 기준

> 이 문서는 Phase 0의 실제 설치/호환성 근거와 재현 명령을 기록한다. 전체 운영 아키텍처와 수용 기준은 [기술 스택](../tech-stack/README.md), [공통 계약](../tech-stack/contracts.md), [로드맵](../tech-stack/testing-roadmap.md) 및 [Phase 실행 계획](PHASE_PLAN.md) 우선. 실제 Phase 기록은 [인계 문서](../../.ai-context/CONTEXT.md)와 [Phase 0 기록](../../.ai-context/phases/phase-00/2026-11-26-01.md). 합성 fixture 전용이며 실제 브로커/시장 데이터·원격 MCP·운영 배포 미승인.

## 1. 검증 환경과 고정 버전

| 항목 | 확인한 버전/환경 | 근거·범위 |
|---|---|---|
| Git checkout | Windows x86_64, /elsaphaba/Auto-Axe | 초기 577b6533d5a09386bacd3ec371538c32ca975b54 → fast-forward f3bb388649429220f04cb38f62ee13bad367fd56 |
| Python | host py -3.12 = 3.12.10; Linux container 3.12.16 | PATH의 Anaconda 3.13.9는 사용하지 않음. pyproject requires-python >=3.12,<3.13 |
| uv | 0.13.10 | 호스트 전용 .venv-tools, Linux 빌드에도 고정 |
| Node.js | 24.21.0 | .node-version, host 및 node image |
| pnpm | 12.9.1 | packageManager, Linux/Windows frozen install |
| PostgreSQL | 17.12 | PostgreSQL 17 image digest와 실제 disposable DB Testcontainers |
| Docker | client/server 29.9.3, Docker Desktop 4.100.1, Compose 5.7.1 | linux/amd64 engine |
| Playwright | 1.65.1, Chromium v1255 (159.0.8154.6) | headless browser 테스트, 원격 공급원 요청 없음 |
| NHPLUG MCP | 0.1.0, c61e38ca37de801911ac6c29a685077802513d44 | upstream MIT; npm ci/build 및 실제 Python MCP stdio handshake, tools/list 6개, endpoint 호출 없음 |
| NHPLUG SDK | nhplug 0.4.2 | 독립 Executor venv·Linux 이미지, import only, MIT metadata |
| Python MCP | 1.30.0 | local stdio initialization/tools/list/call fixture, 실제 원격 Host/OAuth 미검증 |

고정 이미지:
- postgres:17@sha256:87c8b42f423b45d5247e6aa8fdb2e7762fec164c68a50fe3eb07e7bfcaf4dbcf
- python:3.12-slim-bookworm@sha256:44cf1793efa7c7a476bb0f2cff81443f4a072c90c1cb127e2924933daa3e8c64
- node:24.21.0-bookworm-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20
- ghcr.io/gitleaks/gitleaks:v8.30.0@sha256:691af3c7c5a48b16f187ce3446d5f194838f91238f27270ed36eef6359a574d9

CI actions pinned to checkout d23441a48e516b6c34aea4fa41551a30e30af803, setup-node 249970729cb0ef3589644e2896645e5dc5ba9c38, setup-uv 94527f2e458b27549849d47d273a16bec83a01e9 (official Git tag refs confirmed). uv lockfiles separate backend/executor, pnpm workspace lock root. Do not update lock implicitly while implementing a domain. Image digest and security support must be reviewed before any production release; this is a development pin, not perpetual safety.

## 2. Python installed dependency/license metadata

| 패키지 | 버전 | 설치 metadata 라이선스 표기 |
|---|---:|---|
| FastAPI | 0.165.0 | MIT |
| Uvicorn | 0.54.0 | BSD-3-Clause |
| Pydantic | 2.14.4 | MIT |
| pydantic-settings | 2.16.3 | MIT |
| SQLAlchemy | 2.1.9 | MIT |
| psycopg / psycopg-binary | 3.3.9 | psycopg LGPL-3.0-only; binary 배포 시 번들 라이선스 별도 검토 |
| Alembic | 1.20.1 | MIT |
| httpx | 0.28.1 | BSD License |
| websockets | 16.1.1 | BSD-3-Clause |
| mcp | 1.30.0 | MIT License |
| structlog | 26.1.0 | MIT OR Apache-2.0 |
| Scrapling | 0.5.1 | BSD License |
| yfinance | 1.8.0 | Apache Software License |
| feedparser | 6.0.14 | BSD-2-Clause |
| icalendar | 7.3.2 | BSD-2-Clause |
| pytest | 9.2.0 | MIT |
| Hypothesis | 6.170.17 | MPL-2.0 |
| Ruff | 0.17.6 | MIT |
| mypy | 2.4.1 | MIT |
| Testcontainers | 4.15.0 | Apache-2.0 |
| nhplug (executor only) | 0.4.2 | MIT License |

Source: installed metadata via scripts/compatibility_inventory.py, uv.lock, Python runtime tests. Note SQLAlchemy 2.x satisfies selected major; no domain SQLAlchemy API beyond initial migration yet. Scrapling Selector parsed local synthetic HTML, yfinance AsyncWebSocket exists (not connected), feedparser/icalendar imported. Browser fetchers/sandbox actual compatibility Phase 2. No scraper runs against a public site.

## 3. Frontend installed dependency matrix

| 패키지 | 고정 버전 | 검증 범위 |
|---|---|---|
| React / React DOM | 19.3.1 | fixture render/test/build |
| React Router | 7.18.7 | route navigation E2E |
| TanStack Query | 5.108.4 | mock and fixture HTTP health state |
| Zustand | 5.1.0 | dependency resolution; editor later |
| Tailwind CSS / vite plugin | 4.3.5 | generated CSS/build |
| @xyflow/react | 12.12.1 | installed, graph UI Phase 3 |
| Lightweight Charts | 5.3.0 | installed, chart implementation/NOTICE Phase 2 |
| ECharts | 6.1.0 | installed, chart implementation Phase 2/4 |
| TanStack Table | 8.21.3 | installed, table UI later |
| TanStack Virtual | 3.14.28 | installed, virtualized tables later |
| React Hook Form | 7.92.0 | installed, form contracts later |
| Zod | 4.6.7 | installed, form validation later |
| @hookform/resolvers | 5.9.2 | installed |
| Vite / react plugin | 7.3.8 / 5.2.0 | Linux and Windows build |
| TypeScript | 5.9.3 | strict tsc and generated API type |
| openapi-typescript | 7.13.0 | actual OpenAPI 3.1 generation |
| Vitest | 4.1.12 | patched version, test 2 passed |
| Testing Library React | 16.3.3 | fixture UI tests |
| Playwright | 1.65.1 | Chromium E2E |
| ESLint / TypeScript ESLint | 9.39.5 / 8.74.0 | passed |
| Prettier | 3.10.1 | passed |

`pnpm --filter @autoaxe/web licenses list --json` verified metadata in initial installation: MIT, MIT-0, Apache-2.0, BlueOak-1.0.0, Python-2.0, CC-BY-4.0, ISC, BSD-3-Clause, BSD-2-Clause, MPL-2.0, CC0-1.0, 0BSD, MIT OR CC0-1.0. License inventory is screening, not legal review of full text or production distribution; LGPL/MPL/CC attribution and Lightweight Charts NOTICE/attribution must be satisfied if distributed/used. Re-check after lock updates. Free-access data rights remain independent of the libraries' licenses. No paid feed selected.

## 4. Reproduction commands (project root)

PowerShell local example if uv not installed (already done on observed local host):

```powershell
py -3.12 -m venv .venv-tools
.\.venv-tools\Scripts\python.exe -m pip install uv==0.13.10
$uv = (Resolve-Path .venv-tools/Scripts/uv.exe).Path
& $uv sync --project apps/backend --python 3.12 --locked --group collection-smoke
& $uv sync --project apps/executor --python 3.12 --locked
pnpm install --frozen-lockfile
```

When using globally installed uv, replace `& $uv` with `uv`. Tests and contract verification:

```sh
uv run --project apps/backend --locked ruff check apps/backend/src apps/backend/tests apps/backend/migrations
uv run --project apps/backend --locked ruff format --check apps/backend/src apps/backend/tests apps/backend/migrations
uv run --project apps/backend --locked mypy --config-file apps/backend/pyproject.toml apps/backend/src
uv run --project apps/backend --locked python -m autoaxe.adapters.schema --check
uv run --project apps/backend --locked pytest apps/backend/tests
uv run --project apps/executor --locked pytest apps/executor/tests
uv run --project apps/executor --locked python -m autoaxe_executor
pnpm contracts:types
git diff --exit-code -- packages/contracts
pnpm typecheck
pnpm lint
pnpm format:check
pnpm test
pnpm build
pnpm --filter @autoaxe/web exec playwright install chromium
pnpm test:e2e
```

Schema regeneration intentionally changes generated JSON only when models/routes change: `uv run --project apps/backend --locked python -m autoaxe.adapters.schema`, then `pnpm contracts:types`. Source generated file drift should fail CI. Testcontainers starts a disposable PostgreSQL 17 test cluster with ephemeral random credentials. Never point provision() at a real DB. Test case exercises all ten DBs and runtime/migration/owner/read/relay and isolated executor roles, actual connection denial and Decimal/UTC. No domain data persisted.

Upstream MCP smoke (requires network only for repo and package installation):

```sh
git init .phase0-cache/nhplug-mcp
git -C .phase0-cache/nhplug-mcp fetch --depth 1 https://github.com/PLUG-OpenAPI/nhplug-mcp.git c61e38ca37de801911ac6c29a685077802513d44
git -C .phase0-cache/nhplug-mcp checkout --detach FETCH_HEAD
npm --prefix .phase0-cache/nhplug-mcp ci --ignore-scripts --no-audit --no-fund
npm --prefix .phase0-cache/nhplug-mcp run build
uv run --project apps/backend --locked python scripts/nhplug_mcp_smoke.py .phase0-cache/nhplug-mcp
```

Script accepts only pinned SHA, uses synthetic placeholders and localhost:9 for both API/auth URLs; only handshake and tools/list. Never call upstream broker tools in Phase 0.

## 5. Dev Compose and network boundary

[Compose guide](../../infra/compose/README.md). Local UI host 127.0.0.1:18174 -> web internal 4173, web reverse proxy /api -> private api:8000, data network isolated postgres:5432 and one-shot migrate only. Web/API read-only non-root, cap_drop, no new privileges, internal app/data networks; web alone also joins edge bridge for loopback host publishing. Vite uses --configLoader runner to avoid EROFS on the read-only filesystem. Actual Compose healthy, host HTTP 200 and API health fixture flags false verified; executor opt-in profile with network_mode none and no broker credentials, import smoke passed. No public DB port, no production profile, no remote MCP. 18173 for Playwright local preview separate from compose. On this Windows host 4173 and 5173 were OS-reserved, so configurable host ports used; do not alter host reservations. .env.phase0 is ignored; generate a local random disposable password. Runtime role passwords generated in-memory for fixture; not a production credential provisioning design. API is in-memory fixture only, no data store connection. DB roles tested independently. Initial migration marker intentionally not full market schema. Keycloak, Caddy and actual session/authorization/SSRF/scraper egress/real trade risk controls are later phase deliverables.

## 6. Security and residual checks

- Python pip-audit: no known vulnerabilities in installed backend dependency set or executor site-packages; local autoaxe packages skipped as not PyPI packages (not audited by this scan).
- First npm audit: Vitest 3.2.7 and @vitest/mocker/tinypool, 2 critical + 3 moderate. Advisories GHSA-82fw-gwwq-j7x9, GHSA-5gmw-xhrv-c9v3, GHSA-85c8-ppgw-ccpr, GHSA-qxg6-89mg-rqv8. Upgraded Vitest to exact 4.1.12 with patched mocker, removed vulnerable transitive path; subsequent pnpm audit --audit-level moderate exited 0 "No known vulnerabilities found". This is advisory snapshot only, not production security certification.
- Gitleaks redacted staged diff scan and CI tracked commits scan; no real secrets should be stored. Keep .env.phase0, .venv-tools, .phase0-cache, node_modules, test-results ignored. Never output Compose config with expanded password; config --quiet only.
- Full supply-chain SBOM/signing/Trivy/production image hardening, RPO/RTO, operational security test, source permissions/actual provider performance, NH paper order contract, MCP external Host OAuth and production environment remain later gates. Python and Node major versions selected by prior architecture remain unchanged; actual patch versions confirmed. Do not mistake software metadata for legal source-data usage rights.
