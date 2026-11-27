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
| P2.6 산업·심리 | DRAM named Module 2 row, Session Average/Last Update GMT+8, SEIBro TOP50 USD결제, CNN 지정 사이트 score/category, Naver 2Y typed offline parser; PizzINT는 아래 최신 공개 API 전용 DOUGHCON 계약 적용 | **실제 DOM 셀렉터 미검증** (HTML 대상에 한함), fixture 전용 data-source 속성 사용; 사이트별 robots/ToS/저장/배포 권한, 동적 정상 렌더링, 공식 요청 계약/셀렉터 확인 후에만 실제 수집 가능 |
| P2.7 UI | React Router, Query, Zustand, Tailwind/CSS dark 대시보드, source/quality 표시, 전체 지표 필터, BTC Spot/USDT perp 구분, 글로벌 long-short toggle 4종 및 Taker 설명, 모바일 대응, ECharts synthetic demo, 상태/상세 페이지 | 실제 캔들·거래량·SMA/EMA/고저가와 데이터 서버 연결 및 ECharts/Lightweight-charts 라이브 정보/데이터 권한/성능과 시각 검증. Phase 3 그룹/워크플로는 placeholder |
| P2.8 SSE | fixture-only `ready` event, heartbeat no-store, TypeScript `SnapshotGate` snapshot/replay/gap/overflow/resync, ready→REST snapshot buffering, disconnect/reconnect invalidation, Vitest unit | 실제 DB aggregate event/version SSE producer, session/revoke-aware stream, coalescing/backpressure/overflow & long-lived connection load, polling fallback 및 multi-mode 운영 미검증 |

**핵심:** 내부 데이터 원장/계산/fixture 파서·대시보드 코드는 구현·검증할 수 있으나, 이는 CNN/PizzINT/SEIBro/Naver/DRAM에 실제 접속해 지표를 수집할 수 있다는 뜻이 아니다. 이 사이트들의 수집 경로는 기본 BLOCKED다. 사용자 의도에 맞춰 무료 데이터만 대상으로 하지만 무료 가격이 곧 수집·저장·재배포 권한을 의미하지 않는다.

최신 정정: 위 문단은 최초 Phase2 fixture 검증 기준선이다. 2026-11-27 사용자 요청으로 PizzINT의 DOUGHCON 공개 API 전용 5분 collector/ledger/BFF 및 Docker 배포 경로를 후속 구현했고 별도 PostgreSQL/Docker 환경의 실제 API 저장을 검증했다. 실제 운영 인스턴스는 source grant, runtime DB/private network 및 인증 설정이 필요하다. 다른 사이트들의 차단 조건은 유지한다. [운영 절차](../../infra/compose/README.md#pizzint-doughcon-collector), [최신 검증](../../.ai-context/phases/phase-02/2026-11-27-06.md) 참조.

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

## 2026-11-27 Phase 2 잔여 개발 보강 — 범위 및 작동 방법

사용자 최신 요청은 기존 Fixture 기반을 넘어서 **미완료 Phase2를 마저 개발**하는 것이다. [세부 후속 세션 로그](../../.ai-context/phases/phase-02/2026-11-27-02.md), [추가 트러블슈팅 TS-02-11~14](../troubleshooting/phase-02.md)와 함께 읽어야 한다. 이전 원본 기능·보안 요구사항을 축소/취소하지 않는다.

| Phase 기준 | 추가로 실제 구현된 코드 | 여전히 미구현·외부 승인이 필요한 것 |
|---|---|---|
| P2.1 BFF/인가 | 기존 session·scope 검증을 이용한 별도 공식 이벤트/시장 시계열 읽기 API, DB app-runtime과 market-read를 분리하여 서버가 허가를 확인 | Keycloak·Caddy HTTPS 및 실제 계정/인증서/mTLS 서비스 환경 |
| P2.2 주식/ETF | 승인된 market ledger에서 원본 시각별 historical series만 BFF 제공, UI에서 인증된 값만 시각화 | Yahoo AsyncWebSocket 실제 NVDA/QLD day_volume 연결, 시장 캘린더·SMA/EMA 라이브 계산과 1Hz sampler 지속 실행 |
| P2.3 공식 경제 | BLS Public Data API v1 bounded POST real transport 기능, CPI/NFP/실업률 식별자 allowlist, 분리된 25건/UTC day quota, 출처 허가 및 one-shot opt-in, 실제 HTTP는 수행 안 함 | 명시적 관리자 source 권한 확인, 실제 이용권/호출 검증, BEA/Census/중앙은행 Fed/BOJ/BoE/ECB 지표별 공식 API 연결, MEXC Protobuf |
| P2.4 일정/공시 | 수정 이력의 PostgreSQL append/revision, source/event lock, available_at PIT, 개인 조회와 재배포 권한 분리, 원본시각 구분 | SEC 8-K/IR Exhibit 99.1 전문 구조적 가이던스, OCC/CME/Cboe/Binance Options 실만기 세션 |
| P2.5 격리 수집 | PinnedHTTPS 수동 공개 IP/TLS SNI 검증, DNS 사설·혼합 리졸브 거부, redirect·oversize·압축 차단, permission pre/post | 실제 worker mTLS identity/lease network broker 연결, 컨테이너 egress 정책·브라우저 subresource enforcement |
| P2.6 심리/산업 | PizzINT 공개 JSON API DOUGHCON 단일 수치, 고정 TLS reader, 5분 영속 스케줄러·원장·인증 BFF 연결 및 전용 운영 Docker 구성; HTML/수동 폴백 제거 | 운영 DB/IdP의 실제 설정 및 배포, CNN/DRAM/SEIBro/Naver 약관·robots·DOM/실측 셀렉터, generic worker mTLS 배포 |
| P2.7 UI | 권한형 공식 이벤트 table(revision/actual/출처) 및 authorized source history/quality 차트 추가, 기존 합성 차트 분리 | 실제 봉·거래량·SMA/EMA/고저가 차트, 실소스별 polling/market session |
| P2.8 실시간 | 기존 fixture SSE gate 유지, 인증된 history는 REST no-store로 별도 조회 | durable SSE DB event producer, session/revoke stream, gap/backpressure/reconnect 운영 검증 |

### 한 번의 승인형 BLS 수집 (운영 정보 없으면 실행하지 말 것)

정확한 소스별 이용약관과 저장 권한을 관리자 절차로 승인하고 PostgreSQL 17 market database `catalog.source_registry`에 권한 증거·version을 남긴 후, 보호된 runtime DB role의 server-only DSN을 환경변수 `AUTOAXE_MARKET_RUNTIME_DSN`로 연결해야 한다. BLS 무등록 API는 요청일당 25회 제한을 강제하며, 매 호출은 **요청 전 원자적 예약 + 독립 커밋**을 수행하고 실패한 요청도 quota가 차감된다. 디폴트에서는 아무 호출도 하지 않고 자동 반복·retry·배포가 없다.

```sh
uv run --project apps/backend --locked python -m autoaxe.entrypoints.official_cli --execute-approved --series CUUR0000SA0
```

CLI 실행은 사용자/관리자의 별도 승인과 정책 확인 후에만 가능하다. 해당 명령은 이전 세션에서 네트워크로 실행하지 않았으며 mock contract만 검증했다. `--execute-approved`가 없거나 server DB 권한이 없으면 실제 네트워크 호출 전에 거부한다. 백엔드 `GET /api/v1/dashboard/official-events`와 `GET /api/v1/dashboard/authorized/market/{series_id}`는 현재 공급자 승인과 세션/indicators:read를 검사한다. Auto-Axe는 개인·비영리 목적이 기본인 프로젝트이며 별도 모드가 없다. 서버 설정 `AUTOAXE_OWNER_SUBJECT_REF`가 로그인한 소유자와 일치하면 이미 승인된 저장 자료를 개인적으로 조회할 수 있다. 일치하지 않거나 미설정 시 제3자 재배포 권한이 필요하다. 이 식별자는 UI 옵션이 아니며 실제 소스의 수집·보관 승인 절차를 대체하지 않는다.

### 남은 활성화 게이트

프로젝트는 사용자 지시에 따라 **개인용·교육용·비영리이며 공개 서비스 목적이 아님**. 개인 열람/분석과 제3자에게 재배포하는 행위는 다른 권한이다. [개인·교육 목적 이용 정책](../indicator-collection/PERSONAL_EDUCATIONAL_USE.md)을 우선 적용한다. 비영리성만으로 공급자가 금지한 HTML 스크래핑·자동화/이용량 제한이 해제되지는 않는다.

실제 데이터 접근권한·사용약관/robots 확인 및 법적 저장·재배포 허가, Keycloak realm/HTTPS/mTLS 구성, 공식 원본 응답 및 시간 정의 검증, Docker egress private DNS·redirect/브라우저 리소스 방어, source-specific real DOM golden fixture, 지표 실시간 SSE producer를 먼저 확정해야 한다. **이 게이트 없이 현재 구현을 실데이터 수집 운영 완성으로 표시하지 않는다.** Phase 2의 개발 범위도 각 미구현 항목을 추후 계속 추적하며 Phase3 권한 승인은 별개다.

### 후속 개발 로컬 검증

- Backend 전체 Ruff/format/strict mypy(49 source files)/OpenAPI schema check 성공, pytest **88 passed/7 dependency warnings/90.13s** (3 실제 PostgreSQL 17 integration suites 포함).
- 별도 scraper Ruff/format/mypy 5 modules 성공, pytest **9 passed**; Docker Compose network_mode:none, read_only isolated scraper **9 passed/0.66s**.
- Frontend Prettier/typecheck/lint/unit **5 passed**, Vite build success(679 modules), Playwright Chromium **1 passed**. ECharts SVG 503.18kB > 500kB 기존 chunk 경고는 지속되며 향후 성능 개선 항목. 새 auth mock으로 e2e 개발 proxy 오류 제거.
- 기존 개발 PostgreSQL volume에 0005 migration 성공: Docker up --build -d --wait 시 migrate exit0, PG/API/Web healthy. 대시보드 96 indicator (1 fixture/95 unverified), auth 미설정 공식 이벤트 엔드포인트 HTTP 503으로 차단. Docker down(no -v) 및 ps -a empty, 데이터 volume 보존.
- 이는 **구현 및 격리/합성 검증**이다. 실제 BLS/SEC/시장 API 호출, source rights·Keycloak+mTLS 운영 경계와 실시간 SSE, 실제 주문 실행은 전부 미검증/비활성.
- [후속 개발 구현 커밋 7e68159](https://github.com/ELSAPHABA/Auto-Axe/commit/7e68159f84e0f0b2587b6a0f8e7f73adee2f53f1)에 대한 [GitHub Actions 45928981099](https://github.com/ELSAPHABA/Auto-Axe/actions/runs/45928981099)는 completed/success, 4/4 jobs. 허가된 실제 웹 소스나 배포 검증의 증거로 확대 해석하지 말 것.

## 개발 Fixture 최종 검증 (2026-11-27)

- Backend Ruff/mypy 42 files/schema: 통과. 전체 PostgreSQL 통합 포함 pytest **79 passed / 2 deprecation warnings / 118.90s**. 초기 병렬 테스트 중 포트 타임아웃 실패는 별도 [TS-02-05](../troubleshooting/phase-02.md)에 기록, 단독 재검증 1 passed/30.92s, 정책 완화 없음.
- 격리 Scrapling Ruff/mypy 4 files/pytest **5 passed**, network_mode none+read_only Docker scraper **5 passed / 0 warnings / 0.54s**. 실제 사이트 DOM·권한 검증과는 구분.
- React TypeScript/ESLint/Prettier 성공, Vitest **4 passed** (App 2 + SSE gate 2), Vite build 성공, Playwright Chromium **1 passed** (모바일 390px). ECharts lazy bundle 504.47kB 경고는 보존.
- 기존 PG volume 0004 migration exit0; Compose PG/API/Web healthy, `GET /api/v1/dashboard/indicators?limit=100` **96 indicators, 1 synthetic, 95 unverified/null**, root HTTP 200; down/ps -a clean, disposable volume 보존.
- pnpm audit 및 backend pip-audit no known vulnerabilities (unpublished local backend excluded), **실제 외부 공급자 접속이나 주문 없음**. 원격 CI/commit 검증은 Phase 2 로그 종료 섹션 참조.
- **GitHub 최종 구현 CI:** `main` 구현 커밋 `1bd6c8a`의 [Actions run 45926311285](https://github.com/ELSAPHABA/Auto-Axe/actions/runs/45926311285)는 **completed/success, 4/4 jobs**. 초기 CI에서만 발생한 Linux `mypy --config-file` 주석 누락 두 건은 [TS-02-09](../troubleshooting/phase-02.md)에 자세히 기록하고 코드 수정 후 재검증했다. 이 성공은 Fixture/인가 차단 경계를 검증한 것으로, 운영 실제 사이트 접근 권한을 부여하지 않는다.
