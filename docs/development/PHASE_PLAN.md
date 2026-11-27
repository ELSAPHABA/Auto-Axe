# Auto-Axe 개발 실행 계획 (Phase 0–8)

> 2026-11-26 작성. 기준 커밋: `da26b439e1d2deaabed7138ee3f83897a44e023c`. 이 문서는 [기존 전역 로드맵](../tech-stack/testing-roadmap.md)을 실행 가능한 하위 작업으로 분해한 계획이며 별도 전역 Phase, 신규 기능 승인, 기술 변경, 실거래 승인이 아니다.
> 진행 상태 및 사용자 명세: [CONTEXT](../../.ai-context/CONTEXT.md). 기록 양식: [PHASE_LOG_TEMPLATE](../../.ai-context/PHASE_LOG_TEMPLATE.md). 최초 계획 기록: [planning-baseline](../../.ai-context/phases/planning-baseline.md).

## 1. 개발 원칙 및 진입/종료 기준

- [docs/README.md](../README.md)의 문서 적용 기준과 제한 정책 우선 원칙 준수. 사용자 최신 지시 > 기존 명세 > 이 문서의 제안. 변경이 필요한 경우 영향받는 기능/기술/보안 문서 및 수용 테스트를 함께 갱신하고 사용자 승인 여부 명시.
- Phase 0~8만 전역 단계로 사용한다. 하위 작업 ID는 P0.1 등으로 기록한다(기능 우선순위 P0~P2와 혼동 금지). 각 Phase는 구현 착수 전 기준 커밋, 선행 gate, 범위, 미결정을 기록하고 실제 구현 후 검증 증거와 차단 사항으로 종료한다.
- 상태: NOT_STARTED / IN_PROGRESS / BLOCKED / IMPLEMENTED_UNVERIFIED / VERIFIED / NOT_APPLICABLE(근거 필수). 부분 통과와 전체 통과를 구분. 권한이 필요한 공급자·실계좌 시험이 미실시되면 해당 gate는 BLOCKED/UNVERIFIED. Phase 자체의 기술 완료와 해당 기능의 운영 활성화 승인은 다르다.
- 합성/적법한 fixture로 선검증. 무료 데이터 이용권(조회·저장·가공·재배포·자동매매 각각) 미확인 시 자동 실행 금지. 어떤 Phase도 실제 금융 거래를 승인하지 않는다. LIVE 기본 OFF, Phase 8은 별도 명시적 사용자 승인 및 모든 관련 gate 통과 전 착수 금지.
- 개발·검증·운영 Git 상태와 문서를 동기화. 완료 보고는 코드, 테스트, 로그 요약, 실제 커밋/환경으로 입증. 테스트 명령 아래는 실행 예정 예시이며 아직 실행한 적 없다. 실제 패키지명/경로/스크립트가 생긴 뒤 기록을 업데이트.
- 계획된 경로는 기존 architecture.md §3의 제안 구조를 기준으로 하며 실제 작업 트리 검증 후 확정. 변경 없음에도 매 Phase 시작/종료/중단에 인계 문서를 갱신.
- 단계별 병렬화는 독립 계약 및 선행 gate 확보 시에만 허용. 공유 schema/migrations/lockfiles는 단일 담당자 또는 직렬 통합. 서브에이전트 사용 여부는 향후 환경과 사용자 지시에 따름.

## 2. 의존성과 통합 순서

| Phase | 선행 조건 | 산출물 및 다음 단계로 전달할 계약 |
|---|---|---|
| 0 | 기준 문서 동결, 계획 기록 | 설치/호환 matrix, repo scaffold, OpenAPI/JSON Schema/TS, DB role, CI 및 fixture |
| 1 | 0의 runtime, 계약, DB smoke | registry, raw series, observation/revision, job/outbox/inbox, 조회 API |
| 2 | 1의 수집/권한/저장/조회 계약 | 전체 indicator catalog, UI/BFF/SSE, typed scrape broker |
| 3 | 1의 이벤트, 2의 UI/지표 계약 | versioned groups/graphs/runs, evaluator, editor, dry-run, refresh/reset |
| 4 | 3의 evaluator, 2의 피처/데이터 | 확장 node catalog, research dataset/model, replay/backtest, 결과 UI |
| 5 | 3·4의 intent/위험/실행 계약; NH 검증 | 격리 Executor, PAPER_LOCAL/PAPER_BROKER, 승인 및 대사 |
| 6 | domain use case 완료 및 2의 인증, 5의 주문 경계 | 단일 MCP, Tools/Resources/Prompts, scope 및 Host 검증 |
| 7 | 0~6의 필수 수용 테스트 | staging/production 운영 gate, 복구·부하·보안 증거 |
| 8 | 7 완료 + 별도 사용자 승인 및 계좌/권한/리스크 | 조건부 LIVE 운영 구성, 통제된 검증 및 중단/대사 절차 |

MCP read adapter/공통 service는 Phase 1~2부터 준비 가능. Phase 3에서 기본 위험/Stop/intent 계약을 구현하되 SDK 제출은 Phase 5 전 금지. Phase 4에서 simulator/replay의 연구용 인터페이스를 만들고 Phase 5의 PAPER_LOCAL 원장/위험과 통합. Phase 2의 BFF/SEC 통제를 Phase 7까지 미루지 않는다.

## 3. Phase 0 — 기술 검증 및 개발 환경

목표: 후속 기능의 공통 기반을 만들고 불확실한 호환성과 신뢰 경계를 검증한다.
기준: tech-stack/{README,architecture,contracts,backend,data-storage,infrastructure,security,testing-roadmap}.md, mcp/nhplug-integration.md, nhplug/README.md.

| ID | 작업 | 산출/수용 기준 |
|---|---|---|
| P0.1 | 로컬 Git 및 문서 preflight | branch/HEAD/status/remote 확인, 기존 파일/맥락 읽기, 구현 범위와 FR/SEC/MCP/계약 trace 등록; 미확정은 별도 |
| P0.2 | 호환성과 공급망 | Python 3.12+uv, Node 24 LTS+pnpm, PostgreSQL 17 기준; SDK nhplug, nhplug-mcp, Python MCP SDK, Scrapling 및 필요 시 browser sandbox, 라이선스/보안 지원/OS/arch 확인. 실제 버전·lock/digest·실행 명령 기록, 불가시 ADR |
| P0.3 | Monorepo skeleton | apps/backend/src/autoaxe/{domain,application,adapters,infrastructure,entrypoints}, apps/web, apps/executor, packages/contracts, infra, tests/fixtures, .github/workflows; domain에서 framework/SDK import 금지; Executor 별도 패키지/credential |
| P0.4 | 공통 DTO/API/schema | /api/v1/ health/fixture, {data,meta}/{error}, UTC aware/Decimal 문자열/finite 통계/nullable quality, expected_version/Idempotency-Key/hash; OpenAPI 3.1 → packages/contracts/openapi.json → openapi-typescript; workflow Draft 2020-12 및 event envelope 초기 versioned fixture, actual domain schema는 해당 단계 |
| P0.5 | 개발 DB/Role 및 migration | PostgreSQL 17, dev/test 별도, market/app/identity/5 mode DB·role skeleton, PUBLIC 제한, runtime superuser 금지, 실제 role denial test; cross-DB ACID/FK 가정 금지 |
| P0.6 | dev Compose·CI | fixture-only API/web/db 및 별도 Executor skeleton, external MCP/LIVE off, sample config만; uv/pnpm lock, lint/typing/test/schema drift/secret scan; SDK smoke는 credential 없는 import/contract까지만, 실제 endpoint 검증은 별도 |
| P0.7 | 종료 검수 | 설치/빌드/스모크/실제 PostgreSQL role matrix/Decimal UTC roundtrip/schema generation strict compile, 라이선스·의존성 결과 및 실패 재현을 Phase log에 기록 |

예정 명령(실제 workspace 구성에 맞춰 확정): git status --short --branch; git rev-parse HEAD; python --version; uv --version; node --version; pnpm --version; docker compose version; uv sync --locked; uv run ruff check .; uv run mypy ...; uv run pytest; pnpm install --frozen-lockfile; pnpm exec tsc --noEmit; pnpm exec vitest run; pnpm build; docker compose -f <실제 dev compose 경로> config; alembic upgrade head(대상 DB 명시). CI에서 generated artifacts diff 확인. 외부 API 실측을 설치 테스트로 허위 기록 금지.

Exit: 기존 roadmap Phase 0 및 contracts §10의 초기 API/Graph/Event/Data/DB/Frontend 계약을 증거로 통과. 이후 구체 도메인 계약까지 구현되었다고 주장하지 않는다.

## 4. Phase 1 — 수집·저장 기반

기준: FR-001~007, FR-101~106/108~111 기초, indicator-collection/{README,Collector_Design,Market_Source_Policy_20261123,Free_Data_Collection,Binance_API_Coverage,Binance_Metals_LongShort_20261123,YFinance_First_Collection,YFinance_Data_Validation,Manual_Collection,Realtime_Quickstart}.md; tech-stack/{data-collection,data-storage,backend,contracts}.md. PoC는 보존하며 운영 코드와 분리한다.

| ID | 작업 | 검증/산출 |
|---|---|---|
| P1.1 | source/instrument/series registry, permission gate | 비용 0, 상품·venue·currency·unit·source timestamp·권한/약관/검증일·mapping version. unverified/blocked 자동 ingest/use 차단, 수동 검수 |
| P1.2 | 시장 원장, migrations, query | immutable observations/revisions/latest, 복합 키, source_event_at/available_at/received_at/ingested_at 구분, native partitioning, provenance, typed Decimal/UTC, cursor/as_of/quality |
| P1.3 | Durable job/outbox/inbox | SKIP LOCKED claim/lease/token/heartbeat/retry/dedupe, at-least-once, version/gap, mode ingress, DB transaction rollback/crash, no global sequence ordering assumption |
| P1.4 | Binance | Spot BTCUSDT trade + XAUUSDT/XAGUSDT/COPPERUSDT/CLUSDT/BZUSDT futures aggTrade, REST recovery, reconnect/ping/gap; futures market path wss://fstream.binance.com/market/stream?streams=...; 6 futures symbols × 4 ratio kinds = 24 series, 5m aggregates/300s poll, BTC price Spot vs futures ratio |
| P1.5 | VIX/국채 | ^VIX TTL 10초, ^IRX/^FVX/^TNX/^TYX TTL 5분; UST_2Y_NAVER 최우선 승인형, 실패/실행 불가 때만 UST_2Y_TREASURY BC_2YEAR 임시 일별 fallback, 복귀, provenance, 전환 간 변화량 금지; Treasury XML 5개 만기 검증 |
| P1.6 | 수동 입력/CLI migration | 기존 manual_record.py·realtime_collector.py 기능 parity, URL/단위/관측·입력시각/입력자/검수, 권한 우회 금지; 기존 PoC 보존. 조회 API /api/v1/market, /indicators; 읽기 MCP 기반 가능 |
| P1.7 | 복구·품질 | duplicate/late/revision/no_data/no_update/stale/disconnected, 429 Retry-After/5xx backoff/403 차단, bounded backpressure, provider contract fixture, fake WS, Testcontainers 및 replay |

Exit: FR-001~007 및 해당 시장 수집 계약, PoC parity(동일 입력 대비 결과), 권한 gate 및 실제 DB recovery 테스트. 실제 제공자 호출 별도 opt-in 및 source별 권한/실측 증거 없으면 운영 비활성.

## 5. Phase 2 — 전체 지표 및 대시보드

기준: FR-107,201~211,301~310,401~404; design/frontend.md, tech-stack/{frontend,data-collection,contracts,security}.md; 모든 indicator 상세 문서.

| ID | 작업 | 검증/산출 |
|---|---|---|
| P2.1 | BFF·인가와 UI shell | Keycloak OIDC, PostgreSQL opaque hashed web_sessions, server tokens, CSRF/Origin/expiry/revoke, RBAC/resource scope, Caddy private upstream, secure cookies, fixture dev auth 분리; SEC-01/02/03/05 |
| P2.2 | 주식/ETF | yfinance AsyncWebSocket day_volume cache+monotonic 1Hz sampler, NVDA/QLD, source age/receive age/세션 리셋·감소 검증; 로컬 1Hz != 공급자 1Hz/SIP; trailingPE/forwardPE/priceToBook/returnOnEquity, ETF null; SMA 5/20/60/120/200, EMA 12/26 등, HIGH/LOW_5D/10D/20D 확정봉(장중 직전 N봉), adjustment/warmup/PIT |
| P2.3 | Nasdaq/경제/정책 | MEXC NAS100_USDT 후보 Protobuf 전환 예정 2026-12-01 재검증, Binance QQQUSDT 별도, Yahoo NQ=F 지연 CME; BLS/BEA/Census/FOMC 일정 및 actual/revision 분리, Fed target range/FRED, BOJ 목표 vs 실효, BoE IUDBEDR, ECB DFR |
| P2.4 | 캘린더/가이던스 | SEC EDGAR 8-K/Exhibit 99.1/IR, GAAP/adjusted, fiscal period·low/high·first_seen_at; OCC/CME/Cboe/Binance Options 만기, nominal/last_trade/processing/settlement, 4 family YES/NO/UNKNOWN triple/quad 판정, DTE 실제 세션 |
| P2.5 | 격리 Scrapling | private broker FastAPI mTLS claim/heartbeat/result, source_id allowlist, lease/fencing/nonce/deadline/size/schema/revoke, worker DB/거래 비밀 없음, sandbox/egress/private IP/DNS/redirect/subresource 방어. HTTP 우선, 필요한 정상 렌더링만 승인; Playwright는 UI E2E 직접 사용 |
| P2.6 | 승인형 산업/심리 | CNN 지정 URL score/category; PizzINT 공개 JSON API DOUGHCON(`defcon_level` 1~5)만, 5분 영속 스케줄·전용 Docker 실행, 실패 시 미수집, 금융 판단/자동 주문 금지; SEIBro TOP50 USD 결제(매수/매도/순매수, 기간/국가, 전체 시장 아님); DRAM DDR5 UDIMM 16GB 4800/5600, RDIMM 32GB 4800/5600, Module Spot Price Session Average/Last Update GMT+8; Naver 2Y 실제 승인형 parser; 미승인/실패는 null/manual/quarantine |
| P2.7 | 대시보드 및 상세 | Live3x 레퍼런스의 dark token/시장 온도계/시세카드/sparkline/글로벌 롱숏 토글/RatioBar 및 4종 상세/캔들·거래량·SMA/EMA·고저가/지표·일정·품질/공급원 정의; React Router, Query/Zustand, Lightweight Charts/ECharts, Table/Virtual, RHF/Zod, responsive/accessibility |
| P2.8 | 실시간 UI | SSE ready→buffer→REST snapshot→version delta, gap/overflow/reconnect/권한 폐기→resync, heartbeat/세션/모드별 cache, UI coalescing만 허용, polling fallback; 실제 화면 Vitest/Playwright 및 contract |

Exit: 모든 지표의 registry/정의 및 상태 표시, fixture/권한 gate/실시간 reconnect 검증, 허용 source만 활성; 외부 권한 미확인 소스와 MEXC/yfinance 원본 실측 실패를 가짜 실시간으로 표시하지 않는다. SEC-04/07 및 BFF/SSE/scraper contracts §6~8 검수.

## 6. Phase 3 — 그룹 및 Workflow Core

기준: function/{trading-workflow,stock-groups,specification}.md, design/frontend.md §4.4~4.5, tech-stack/{workflow-engine,contracts,data-storage,frontend}.md.
FR-501~505,506~508 기초,511,517~518,522~532 중심; 주문은 intent-only. FR-510/516/520/521의 위험·승인 인터페이스 선행, 실제 실행 Phase 5.

| ID | 작업 | 검증/산출 |
|---|---|---|
| P3.1 | 그룹 definition/version | CRUD/search/clone/import/export, members/weights, immutable refs/deletion constraints, 평균/가중/중앙/breadth/조건부 수익률/분산/강도/상대수익률; 동일 세션/as-of/기준가/coverage |
| P3.2 | versioned graph | discriminated node catalog, typed ports/edges, semantic/cycle/ref validation, immutable deployed version, canonical approval SHA-256(excludes UI position), migration draft-only, control registry reference reservation/import ack/delete race |
| P3.3 | evaluator | run single-writer/lease fencing, committed snapshot, durable evaluation_seq, raw/effective TRUE/FALSE/UNKNOWN, AND/OR/NOT, sequential, IF/Switch/Fork/Join, SKIPPED vs FALSE vs UNEVALUATED, Wait/Timeout/Cooldown/controlled loop |
| P3.4 | stateful conditions | price threshold/N%/reversal/intensity, group comparator/cross/reversal/ALL/ANY/N-of-M, LATCHED 1~N dedupe/rearm/expiry, CONTINUOUS immediate, 1/5/20/custom N sessions reset(calendar_id/version/DST/early close) preserving order/fills/stop/risk/idempotency |
| P3.5 | reuse & dependency | WorkflowCondition pinned whole workflow, explicit ConditionResult, child state parent/root/path/activation isolation, no order/cancel/liquidation effects, cross-workflow cycles, delete blocked incl draft/inactive/active fixed reference |
| P3.6 | immediate refresh & safety | condition valid satisfaction triggers RefreshCoordinator for related dependencies, dedupe/rate limit/timeout/barrier committed snapshot re-evaluation, stale/UNKNOWN and source TTL, source pin/fallback provenance, durable activation/reset keys, independent Stop all branches, restart replay |
| P3.7 | editor and monitoring | React Flow palette/canvas/inspector/logs/toolbar, undo/redo/minimap/copy paste/template/version/import export, branch highlight, raw/effective/hit/reset/time/reasons, active top-level definition count dedup excluding children/backtest, per mode/run details, connected AND/OR summary not separate group |
| P3.8 | dry-run integration | DRY_RUN intents only, no external order, version/approval interfaces, stop/duplicate/crash/lock/replay property tests, UI/API/engine round-trip |

Exit: graph contracts §2,10; complete relevant workflow/group acceptance sections; reset, reference deletion/concurrency, refresh race, stop race, stale and UNKNOWN tests with evidence. No SDK/order credential.

## 7. Phase 4 — 전체 트리거 및 퀀트 분석

기준: FR-509,512~515,519~521의 비브로커 기능, FR-601~610, remaining FR-506~508/511/523~524; function/friday-close-strategy.md, tech-stack/quant-analytics.md.

| ID | 작업 | 검증/산출 |
|---|---|---|
| P4.1 | 기술·거시·뉴스 트리거 | SMA cross, high/low, gap/support/resistance/RVOL/RSI/MACD/ROC/ATR/Bollinger/realized vol, VIX/CNN/ratio/rates/spread/economic/guidance/witching/DTE/DDR5/cross asset/session; news model source/license/confidence 검증 전 비활성 |
| P4.2 | 실행 제어 및 전략 | 손익/stop/take profit/trailing/spread/limit/feed risk, event blackout, split/OCO state model, watchlist/variables/sub-workflow, approval request/notification/performance, order coordinator interfaces; broker-specific semantics는 P5 |
| P4.3 | point-in-time dataset | 3년 기본, 5/10년 비교, 한 주 한 표본, 3 labels Fri close→Mon close/open, Mon open→close, 거래소 세션/휴장/조기 종료, available_at cutoff, 수정·재무 snapshots·미확정봉 미래 누수 금지, Parquet/PyArrow/DuckDB manifest |
| P4.4 | 통계/모델 | Pearson/Spearman/MI/conditional probabilities/quantile/bootstrap/sample uncertainty, base frequency, L2 Logistic/KNN 우선, Bayesian Logistic/RF/XGBoost/LightGBM 비교, 과대적합/표본 부족 시 보류, finite probabilities/return/downside separate |
| P4.5 | walk-forward 및 replay | 시간순 preprocessing/tuning/calibration, Brier/log loss/accuracy, 비용/슬리피지/부분체결/가상 clock, Sharpe/MDD/손익비, deterministic evaluator reuse, safe artifact serialization no external pickle, dataset/model/code version |
| P4.6 | Friday dashboard & integration | RESEARCH_EOD vs EXECUTION_PRE_CLOSE 별도 피처/모델/성과, weekly train/Fri inference/Mon reconciliation, 3 targets/return/risk/contribution/similar cases/metrics, model approval and confidence/freshness gating, research model cannot generate live action |
| P4.7 | backtest/job/UI | durable job progress/cancel, reproducible report, trade log and data gaps, versioned input hashes; approved node catalog coverage against all P0~P2 functional features, no silent omission |

Exit: no look-ahead test, cutoff and model artifact tamper, walk-forward reproducibility, cost model, simulator replay parity, feature/node registry mapping to FR, insufficient history/permission gate. Unsupported data/model is explicit blocked, not synthetic production. Model selection threshold remains empirically validated/user policy, not invented.

## 8. Phase 5 — NHPLUG PAPER_BROKER 및 PAPER_LOCAL

기준: FR-510,514~516,519~521,705; tech-stack/trading-integration.md, function/trading-workflow.md, mcp/nhplug-integration.md, nhplug original docs. No LIVE.

| ID | 작업 | 검증/산출 |
|---|---|---|
| P5.1 | upstream contract | 공식 nhplug-mcp 실제 등록 6 tools/operationId read allowlist, stdio private; SDK/PyPI nhplug API/version, environment URLs/ports/token/WS master format, supported order/asset/paper endpoints/fees, verify CA; docs claim vs 실제 응답 구분 |
| P5.2 | Executor boundary | apps/executor 별도 패키지/image/network/role/secret, mode/account allowlist, read MCP no order, general API/MCP no direct submit, paper credential cannot reach live, BACKTEST/DRY_RUN/PAPER_LOCAL/PAPER_BROKER/LIVE DB 분리 |
| P5.3 | approval/risk | pre-approved immutable automatic strategy vs per-order manual/AI approval, canonical hash/version/account/mode/instrument/quantity/limits/expiry; fail closed on missing authorization or quality; durable revoke fence prior to success |
| P5.4 | Order Coordinator | per account/mode priority, maximum buys/sells separately per action/day qty/value, exposure/reservation, contradictory intent CONFLICT_HELD, stop vs submission serialization, fill-based release/partial/OCO/limits, final validation |
| P5.5 | order ledger & reconciliation | intent/attempt/order/fill/risk/audit in same mode DB, broker status vs intent, duplicate idempotency, timeout UNKNOWN blocks retransmission, reconcile using official reference/fills, restart/lease, Kill Switch persistent, cancel/close separate explicit policy |
| P5.6 | simulator & official paper | deterministic PAPER_LOCAL no broker credential; PAPER_BROKER sandbox only, actual user-authorized paper account and permitted endpoint validation; mock first, never fallback to LIVE |
| P5.7 | integration/exit | negative permission/mode test, duplicate/crash/unknown/partial/stop/kill/revoke, reconciliation and paper evidence, account permissions and limits unresolved listed; UI PAPER aggregates local+broker but ledgers separate |

Exit: fake SDK/real DB safety gate + authorized official paper test and reconciliation; actual account/credentials/limits and order-type support unresolved until verified. Paper failure cannot authorize LIVE. SEC-06/07/10.

## 9. Phase 6 — 통합 MCP

FR-701~708, MCP-001~010 and all acceptance in docs/mcp/{specification,tools,resources-prompts,security,nhplug-integration}.md; tech-stack/mcp-security.md.

| ID | 작업 | 검증/산출 |
|---|---|---|
| P6.1 | single MCP | official Python SDK, separate entrypoint, common Application Service, stdio stdout protocol/stderr log, local loopback auth; capabilities/version/error mapping |
| P6.2 | catalog | market, indicator, stock_group, workflow, prediction, backtest, portfolio, collector, system, trading(preview/intent only) 10 domains, exact tools names/input/output/scopes from docs/mcp/tools.md; resources autoaxe:// and prompts per catalog; unsupported not exposed |
| P6.3 | job and authorization | read-only vs write, Viewer/Analyst/Strategist/Operator, resource ownership/mode/account, expected_version/idempotency, cancellation/status, common policy/audit, prompt text is not auth |
| P6.4 | remote | Caddy HTTPS Streamable HTTP /mcp, Keycloak OAuth/discovery/audience/PKCE/client registration/scope/revoke/Host/Origin/TLS/rate-limit, admin external off by default, private DB/NH/executor, no browser BFF token reuse |
| P6.5 | lifecycle and host tests | MCP disconnect/client grant revoke/external OFF stops new requests/streams but independently valid human-preapproved workflow may continue; workflow/ account revoke or unknown common authorization stops new orders; already submitted reconcile. Inspector, actual local/remote Host opt-in, direct LIVE submit denied, consistent REST/UI/MCP |

Exit: complete catalog trace and auth/error/contract tests; actual Host compatibility and external exposure remain gated by user/admin and security validation. No live start tool.

## 10. Phase 7 — 운영 검증

기준: tech-stack/{infrastructure,security,testing-roadmap,contracts}.md, mcp/security.md. 
- P7.1 Linux Docker Compose dev/staging/prod, Caddy/Keycloak/DB/worker/executor zones; non-root/read-only/cap_drop/seccomp, host nftables Docker forwarding IPv4/IPv6, restricted egress, no external DB/admin/SDK. 실제 target hardware/domain/비용은 사용자 확정 필요.
- P7.2 CI/CD reproducible pinned builds, GHCR, SBOM/Syft/Trivy/Gitleaks/pip-audit/npm audit, least privilege; PR synthetic only, production secret unavailable; migrations expand/contract, staging smoke, rollback; LIVE never auto-start.
- P7.3 Prometheus/Grafana/OTel structured logs, collector age/queue/lag, order UNKNOWN/reconcile/kill, API/SSE/DB/backup/TLS alerts; private ops and no sensitive labels.
- P7.4 Load test k6/Locust, 100 symbols 1Hz + 20 workflows hypothesis, internal p95 500ms excluding upstream; query p95 300ms hypothesis, actual hardware, query range, disk/WAL/retention/budget, bottleneck-based ADR; no SLA claim.
- P7.5 Failure/recovery: process kill, DB restore/off-host encrypted backup/PITR, schema migration rollback, secret rotation, reauthorization/reconciliation before rearm. RPO 5m/RTO 2h only after demonstrated WAL/PITR; single host not HA.
- P7.6 SEC-01~10 full matrix: invalid/revoked/session CSRF; BOLA/roles; external ports/network; SSRF/scraper compromised; secret leak; trade safety; stale/poisoned artifact; supply chain; DoS/restore; audit/incident drills. ZAP staging, synthetic only. Remediate/retest or explicitly block.
Exit: test evidence and runbooks/rollback/restore/gates, staging approval separate from real production; LIVE still off.

## 11. Phase 8 — LIVE (조건부, 미승인)

진입 전 모든 관련 gate, 권한, 공급자 자동매매 이용권, NH official order/paper support, actual paper results/reconciliation, user-approved account/mode/instruments/order types/limits, approval expiry, model eligibility and operational readiness. 사용자에게 확인 가능한 자료 제시 후 명시적 승인. Phase 진행 요청 자체를 LIVE 주문 승인으로 해석하지 않는다.
- P8.1 명시 승인 범위 및 금지/중단/롤백 절차, credential/network/DB allowlist 검증. 별도 프로필/계좌/호스트 고려, CI auto-start 금지.
- P8.2 승인된 운영 설정과 최종 fail-closed gates. 검증은 허가 범위에 한정; 개별 실제 주문 또는 거래 실행에 대한 승인 범위 초과 금지.
- P8.3 주문/체결·미결/UNKNOWN 대사, audit and stop, monitoring, incident runbook. 미승인/불명확/한도 미확정이면 BLOCKED.
Exit: 별도 사용자 승인 및 운영 검증 증거가 있어야만 해당 승인 범위에 한해 상태 변경.

## 12. 추적 매트릭스 및 공통 DoD

FR-001~007 → P1/P2, FR-101~111 → P1/P2, FR-201~211 → P2, FR-301~310 → P2, FR-401~404 → P2, FR-501~532 → P3/P4/P5(각 하위 작업의 매핑 포함), FR-601~610 → P4, FR-701~708/MCP-001~010 → P6 및 P5. SEC-01/02/03/05 P0/P2/P6/P7, SEC-04 P2/P7, SEC-06 P3/P5/P7, SEC-07 P1~5/P7, SEC-08 P0/P7, SEC-09 P0~7, SEC-10 P3/P5/P6/P7. 전체 검증은 P7 및 LIVE preflight. 정확한 ID별 수용 조건은 원문을 우선하고 각 구현 log/test mapping으로 보완.
- 테스트: Python pytest/pytest-asyncio/Hypothesis/Ruff/mypy; TS tsc/ESLint/Prettier/Vitest/Testing Library/Playwright; DB Testcontainers/Alembic; respx/fake WS; MCP Inspector/Host; 보안·운영 위 P7. 실제 명령/결과/환경/fixture version 기록.
- gate evidence: 테스트 ID/FR/SEC/contract, 명령, 환경/버전, exit code 및 실패 수, 적법한 fixture 출처, 결과·로그 경로, 대상 커밋, 미실행 사유. 실제 기능과 mock, 공급자 운영 권한과 무료 접근, paper와 LIVE 구분.
- Phase 종료마다 CONTEXT 및 phases/<phase>/... 를 갱신하고 원문 명세의 변경이 있으면 ADR/테스트 동시 수정. 기록까지 commit 후 원격 readback, 다음 Phase 및 정확한 최초 작업 지정.

## 13. 미확정 결정 및 위험 등록

| ID | 확인 필요 | 처리 단계 |
|---|---|---|
| R01 | Python/Node/nhplug/MCP/Scrapling 버전 교집합, 라이선스, sandbox | 0, 2, 5, 6 |
| R02 | source별 자동 조회/저장/재배포/거래 권리·호출 제한, MEXC 전환 및 NVDA/QLD WS 실측, VIX TTL 충족 | 1–2, 7 |
| R03 | CNN/SEIBro/DRAM/Naver 스크래핑 허가와 DOM·시간·단위/수동 검수; PizzINT DOUGHCON 공개 API 범위·스키마 검증; Cboe dashboard 자동 추출 금지 | 2 |
| R04 | point-in-time history와 모델 최소 표본/기준 모델/임계값/뉴스 모델 권한 | 4 |
| R05 | 정확한 NH master parsing, 주문 API/계좌/상품/모의 지원·수수료·한도·idempotency/대사 | 5 |
| R06 | MCP revision/host interoperability, OAuth registration/audience, 외부 정책 | 0, 6 |
| R07 | 운영 host/도메인/예산/retention/부하/RPO/RTO, backup 및 보안 승인 | 7 |
| R08 | 사용자 지정 리스크 한도/계좌/실주문 유형/LIVE 승인 | 5, 8 |

이 계획 수립 시점에는 모든 Phase 0~8이 NOT_STARTED였다. 이후 실제 진행 상태 및 검증 결과는 [CONTEXT](../../.ai-context/CONTEXT.md)와 연결된 Phase 기록에서 확인한다. 기준선 자료의 조사 결과를 향후 코드/권한/성능 검증으로 착각하지 않는다.
