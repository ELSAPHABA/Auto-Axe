# Phase 2 — 지표·격리 스크래퍼·대시보드 개발 결과

2026-11-27 KST. 원본 [Phase 계획](PHASE_PLAN.md) §5의 P2.1~P2.8을 변경하지 않는다. [상세 세션 기록](../../.ai-context/phases/phase-02/2026-11-27-01.md) · [별도 트러블슈팅](../troubleshooting/phase-02.md) · [전체 운영 맥락](../../.ai-context/CONTEXT.md).

## 상태 정의

| 상태 | 의미 |
|---|---|
| VERIFIED / FIXTURE | 순수 계산, 합성 HTML/JSON/WS, 로컬/CI 테스트, 격리 DB 등 명시한 범위에서 검증됨 |
| IMPLEMENTED / UNVERIFIED | 어댑터·계약·구조 구현, 실물 DOM/API·운영 제약 및 권한은 미검증 |
| BLOCKED / NO AUTHORIZATION | 실제 운영 활성화에 필요한 source terms/API credentials/mTLS/Identity 등 없음. 실제 호출 금지 |
| NOT IMPLEMENTED | 요구사항이 설계에 존재하나 이번 구현에 없음; 다음 에이전트가 임의로 완료 표시 금지 |

### Phase 2 개별 작업 상태

| 작업 | 실제 산출 및 검증 범위 | 남아 있는 필수 게이트 |
|---|---|---|
| P2.1 BFF·인가 | Keycloak OIDC discovery/Authorization Code + PKCE(S256), state/nonce 해시, AES-GCM verifier, RS256 issuer/audience/nonce 검증, PostgreSQL 사용자 grant/web_session의 scoped hashed opaque cookie와 CSRF·Origin·만료·철회 및 버전 fence, 기본 비활성 auth routes. Caddyfile.example은 비배포 검토 자료 | 실제 Keycloak realm/client/DNS/TLS, 안전한 secret provisioning, 인증된 Caddy edge, IdP 교체 및 권한/계정 테스트 미실시 |
| P2.2 주식/ETF | `VolumeSampler`: NVDA/QLD day_volume local 1Hz sampling cache, age/received age, source timestamp & out-of-order/감소/세션 reset; `financial_snapshot`: NVDA TTM/forward/PBR/ROE, QLD ETF null; `derive_features`: 확정·이용가능 봉 SMA(5/20/60/120/200), EMA(12/26), HIGH/LOW(5/10/20), adjusted/unadjusted 분리 | Yahoo AsyncWebSocket 실제 연결, SIP/1Hz source 주기/지연, 실제 분봉·일봉·재무제표 소스 유효성, 거래소 캘린더 실측 필요 |
| P2.3 거시/정책/나스닥 | MEXC NAS100_USDT REST typed 후보, 지수/QQQ/지연 CME 구분, BLS actual CPI/NFP/실업률 데이터, BLS/BEA/Fed ics 일정, Fed/BOJ/BoE/ECB 수치 입력 정규화 | MEXC 2026-12-01 Protobuf WS 전환 실측, 공식 BEA/Census/FRED/API 권한, 나스닥 QQQ/선물 실제 API 및 정책 원본 조회, 공식 발표시각·revision 검증 |
| P2.4 일정·공시·만기 | `EventRevision`의 scheduled/released/first_seen/available/revision PIT; SEC Atom filing URL 후보만 추출·human review; `Guidance` GAAP/ADJUSTED/fiscal period/range 검증; OCC/CME 기반 네 제품군 YES/NO/UNKNOWN 및 triple/quad/세션 DTE. 0004 마이그레이션의 calendar/guidance tables | OCC/CME/Cboe/Binance Options 원본 공식 계약/만기·마감·결제 실제 세션 검증, Exhibit 99.1 parsing/full guidance workflow/human reviewer 운영 |
| P2.5 격리 Scrapling | 별도 `apps/scraper` Python 프로젝트/lock, 고정 source allowlist, offline Selector parsers, `scraper-fixture` network_mode none/read-only/caps off/pids/memory 제한; PostgreSQL `scrape_jobs` / lease·nonce/permission_version·revoke·idempotency/heartbeat/quarantine; 별도 private broker HTTP DTO | **실제 mTLS 검증기 미구현으로 endpoint가 의도적으로 503**; 운영 DNS/IP/redirect/subresource egress enforcement, 샌드박스 브라우저 렌더링 및 명시적 source 허가 미검증. 절대 임의로 활성화하지 말 것 |
| P2.6 산업·심리 | DRAM named Module 2 row, Session Average/Last Update GMT+8, SEIBro TOP50 USD결제, CNN 지정 사이트 score/category, PizzINT status, Naver 2Y typed offline parser; null/manual/quarantine, 주문신호 절대 금지 | **실제 DOM 셀렉터 미검증**, fixture 전용 data-source 속성 사용; 사이트별 robots/ToS/저장/배포 권한, 동적 정상 렌더링, 공식 요청 계약/셀렉터 확인 후에만 실제 수집 가능 |
| P2.7 UI | React Router, Query, Zustand, Tailwind/CSS dark 대시보드, source/quality 표시, 전체 지표 필터, BTC Spot/USDT perp 구분, 글로벌 long-short toggle 4종 및 Taker 설명, 모바일 대응, ECharts synthetic demo, 상태/상세 페이지 | 실제 캔들·거래량·SMA/EMA/고저가와 데이터 서버 연결 및 ECharts/Lightweight-charts 라이브 정보/데이터 권한/성능과 시각 검증. Phase 3 그룹/워크플로는 placeholder |
| P2.8 SSE | fixture-only `ready` event, heartbeat no-store, TypeScript `SnapshotGate` snapshot/replay/gap/overflow/resync, ready→REST snapshot buffering, disconnect/reconnect invalidation, Vitest unit | 실제 DB aggregate event/version SSE producer, session/revoke-aware stream, coalescing/backpressure/overflow & long-lived connection load, polling fallback 및 multi-mode 운영 미검증 |

**핵심:** 내부 데이터 원장/계산/fixture 파서·대시보드 코드는 구현·검증할 수 있으나, 이는 CNN/PizzINT/SEIBro/Naver/DRAM에 실제 접속해 지표를 수집할 수 있다는 뜻이 아니다. 이 사이트들의 수집 경로는 기본 BLOCKED다. 사용자 의도에 맞춰 무료 데이터만 대상으로 하지만 무료 가격이 곧 수집·저장·재배포 권한을 의미하지 않는다.

## 주요 파일과 계약

- `apps/backend/src/autoaxe/domain/indicator_registry.py`: 68 Phase1 시계열 + Phase2 논리 지표 정의. `all_indicators()`는 등록과 수집 권한을 구분한다.
- `apps/backend/src/autoaxe/domain/{indicator_math,volume,calendars,expirations}.py`: 공급자 없는 순수 계산·계약.
- `apps/backend/src/autoaxe/adapters/{macro_sources,dashboard_api}.py`: 공식 경제/정책/공시 데이터 오프라인 파서, fixture dashboard OpenAPI/JSON schema 및 SSE.
- `apps/backend/src/autoaxe/application/{oidc,scrape_broker}.py`와 `infrastructure/sessions.py`: opaque session 및 durable broker.
- `apps/backend/src/autoaxe/entrypoints/{auth,scrape_broker,api}.py`: 인증 경계, public app와 private broker app를 완전히 별도 인스턴스로 구성. 백엔드 fixture API는 실제 BFF 인증 동작을 보증하지 않는다.
- `apps/backend/migrations/versions/0004_phase2.py`: app identity, market indicators/calendar/guidance, ops scrape jobs/results, audit/version constraints. destructive downgrade 거부.
- `apps/scraper/src/autoaxe_scraper/{policy,parsers,__main__}.py`: 고정 URL 정책과 오프라인 HTML 파서. 실제 HTTP requests 혹은 DNS 호출 코드 없음.
- `apps/web/src/{App,dashboard,fixture-chart,api,live,store}.tsx|ts`: 화면, SSE reconciliation, synthetic chart.
- `infra/compose/dev.yaml`는 이전 PG/API/Web을 유지, scraper-fixture만 선택 프로필의 network none. 운영 broker/listener 실행 없음.

## 검증·실행 명령

Windows PowerShell에서 `$uv=(Resolve-Path .venv-tools/Scripts/uv.exe).Path` 사용; 다른 OS에서는 `uv`로 대체.

```sh
uv sync --project apps/backend --locked --group collection-smoke
uv run --project apps/backend --locked ruff check apps/backend/src apps/backend/tests apps/backend/migrations
uv run --project apps/backend --locked ruff format --check apps/backend/src apps/backend/tests apps/backend/migrations
uv run --project apps/backend --locked mypy apps/backend/src
uv run --project apps/backend --locked python -m autoaxe.adapters.schema --check
uv run --project apps/backend --locked pytest apps/backend/tests -q

uv sync --project apps/scraper --locked
uv run --project apps/scraper --locked ruff check apps/scraper
uv run --project apps/scraper --locked ruff format --check apps/scraper
uv run --project apps/scraper --locked mypy apps/scraper/src
uv run --project apps/scraper --locked pytest apps/scraper/tests -q

pnpm install --frozen-lockfile
pnpm contracts:types
pnpm typecheck
pnpm lint
pnpm format:check
pnpm test
pnpm build
pnpm test:e2e

python scripts/init_dev_env.py
docker compose --env-file .env.phase0 -f infra/compose/dev.yaml config --quiet
docker compose --env-file .env.phase0 -f infra/compose/dev.yaml up --build -d --wait
docker compose --env-file .env.phase0 -f infra/compose/dev.yaml --profile scraper-fixture run --rm --build scraper-fixture
docker compose --env-file .env.phase0 -f infra/compose/dev.yaml down
```

개발 Web `http://127.0.0.1:18174`. 공개 API: `GET /api/v1/dashboard/indicators?category=...&cursor=...`, `GET /api/v1/dashboard/stream`. `/api/v1/auth/*`는 실제 IdP 및 session DSN이 없으면 503/401. Private scrape broker `/internal/v1/scrape/jobs/*`는 공개 API에서 404, 별도 app에서도 TLS 서비스 identity 검증 구현 전 503.

## 보안 경계와 단계별 활성 조건

1. 소스별 사용약관/robots/공식 API 권한·저장·배포 검증과 evidence/version 기록을 승인; source_registry의 enabled/allow_fetch/allow_storage는 기본 false. 실제 외부 요청 없음.
2. TLS 및 Keycloak issuer/client, server-only encryption key, 세션 secret/rotation, RBAC/Origin/CSRF & OIDC end-to-end. Caddyfile.example은 검토용, 프로덕션 사용 전 보안/네트워크 검증 필수.
3. 증명 가능한 mTLS client certificate validation + private ingress, pinned DNS/TLS SNI/egress policy, RFC1918/loopback/DNS rebinding/redirect/subresource protection. 현재 브로커 HTTP는 fail closed; Header spoofing으로 인증 안 됨.
4. 실제 authorized DOM/response capture에 대한 selector/parse/golden fixture 비교, schema drift quarantine. 합성 `data-source` 속성은 실제 사이트에서 작동한다고 가정하지 않는다.
5. 공급자 계약/발표시각 및 데이터 지연 실측, market as_of/PIT와 frontend stream version consistency. 실제 캔들 및 장기 스케줄러 운영/재시작/복구, 사용자 그룹/워크플로·주문 결합은 별도 Phase.

**미해결 실측/승인 때문에 본 Phase의 운영 활성화는 BLOCKED.** 동일 기준을 [Phase 기록](../../.ai-context/phases/phase-02/2026-11-27-01.md) 및 [트러블슈팅](../troubleshooting/phase-02.md)과 일치시킨다.

## 개발 Fixture 최종 검증 (2026-11-27)

- Backend Ruff/mypy 42 files/schema: 통과. 전체 PostgreSQL 통합 포함 pytest **79 passed / 2 deprecation warnings / 118.90s**. 초기 병렬 테스트 중 포트 타임아웃 실패는 별도 [TS-02-05](../troubleshooting/phase-02.md)에 기록, 단독 재검증 1 passed/30.92s, 정책 완화 없음.
- 격리 Scrapling Ruff/mypy 4 files/pytest **5 passed**, network_mode none+read_only Docker scraper **5 passed / 0 warnings / 0.54s**. 실제 사이트 DOM·권한 검증과는 구분.
- React TypeScript/ESLint/Prettier 성공, Vitest **4 passed** (App 2 + SSE gate 2), Vite build 성공, Playwright Chromium **1 passed** (모바일 390px). ECharts lazy bundle 504.47kB 경고는 보존.
- 기존 PG volume 0004 migration exit0; Compose PG/API/Web healthy, `GET /api/v1/dashboard/indicators?limit=100` **96 indicators, 1 synthetic, 95 unverified/null**, root HTTP 200; down/ps -a clean, disposable volume 보존.
- pnpm audit 및 backend pip-audit no known vulnerabilities (unpublished local backend excluded), **실제 외부 공급자 접속이나 주문 없음**. 원격 CI/commit 검증은 Phase 2 로그 종료 섹션 참조.
