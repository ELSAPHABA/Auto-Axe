# Phase 0 트러블슈팅 (기존 기록 이관)

근거: [Phase 0 상세 기록](../../.ai-context/phases/phase-00/2026-11-26-01.md), [환경 검증](../development/PHASE_00_ENVIRONMENT.md). 이전 실제 검증 기록에 기반하며 이번 세션에서 과거 장애를 다시 재현하지 않았다.

## TS-00-01 — 개발 런타임 미설치
- 증상: PATH Python 3.13.9 (Anaconda), uv 명령 없음. 기존 명세는 Python 3.12.
- 조사: py launcher에서 3.12.10 확인. 글로벌 환경 변경은 다른 프로젝트 영향 우려.
- 해결: py -3.12 -m venv .venv-tools; 전용 uv 0.13.10 설치, backend/executor 각각 독립 uv.lock 및 venv. Docker Python 3.12.16.
- 검증: uv sync 및 SDK import, pytest. 원본 Phase 로그 참조.

## TS-00-02 — 타입 검사 실패
- 증상: Ruff E501, mypy 5건. FastAPI responses dict 및 SQLAlchemy URL host/port 타입 불일치.
- 원인: 추론한 dict 타입과 프레임워크 계약 차이, psycopg conninfo 값 타입.
- 해결: Ruff format, 명시적 dict[int|str, dict[str, Any]], host/port cast. Alembic path_separator=os. strict JSON의 1e999 overflow 추가 검증.
- 검증: mypy 15 sources clean, Ruff 통과, 관련 계약 회귀 테스트.

## TS-00-03 — Vitest 전이 의존성 보안 취약점
- 증상: pnpm audit에서 Vitest 3.2.7/@vitest/mocker/tinypool critical 2, moderate 3.
- 근거: GHSA-82fw-gwwq-j7x9, GHSA-5gmw-xhrv-c9v3, GHSA-85c8-ppgw-ccpr, GHSA-qxg6-89mg-rqv8.
- 해결: Vitest 4.1.12 exact pin, lock 갱신; 취약 경로 제거. 임의 audit ignore 대신 의존성 변경.
- 검증: pnpm audit --audit-level moderate exit0; tsc/lint/format/Vitest 2 tests/build 및 E2E 재실행.
- 범위: advisory 시점 검사, 전체 보안 보증 아님.

## TS-00-04 — Windows 포트 EACCES
- 증상: Playwright preview 4173 EACCES. netsh interface ipv4 show excludedportrange protocol=tcp에서 4120~4219, 5141~5240에 4173/5173 포함.
- 해결: OS 예약 범위 수정 대신 AUTOAXE_E2E_PORT 기본 18173, AUTOAXE_DEV_WEB_PORT 기본 18174. 내부 Vite 4173 유지.
- 검증: Chromium 1 passed, host HTTP 200. preview 종료 중 ELIFECYCLE은 teardown, 전체 exit0.

## TS-00-05 — Pydantic false 환경변수
- 증상: Compose migrate 성공, API 실패. Literal[False]가 문자열 false 거부.
- 해결: infrastructure/config.py explicit_false validator에서 문자열 false만 False로 변환; true/모호한 값 거부. MCP entrypoint에도 Settings 검증.
- 검증: false 허용/true 거부 회귀 테스트 및 API healthy.

## TS-00-06 — Vite read-only EROFS
- 증상: web exit1, .vite-temp/vite.config.ts.timestamp-*.mjs 쓰기 중 EROFS.
- 원인: 기본 bundled config loader가 임시 파일을 생성.
- 해결: apps/web/Dockerfile --configLoader runner, read_only 유지, healthcheck 추가. 파일시스템 보호 제거는 기각.
- 검증: web healthy; 이후 host 접근 실패는 TS-00-07 별도 원인.

## TS-00-07 — 내부 네트워크만 연결된 Web의 publish 실패
- 증상: 내부 API/Web 모두 healthy, host 127.0.0.1:18174 연결 거부, ps에 4173/tcp만 표시.
- 원인: internal-only app network에서 host port publish 불가.
- 해결: web만 edge bridge 추가, loopback publish. app/data network는 internal 유지.
- 검증: Compose up --wait exit0, 3 services healthy, migrate exit0, HTTP 200, API fixture flags false. Executor network none import 성공. down 후 ps -a empty.

## TS-00-08 — 로컬 GitHub 인증 부재 및 이력 분기
- 증상: git push origin main 대기, gh auth status 미로그인. 로컬 27cbcdb7b46ec7163e276baa6a9bb0874b82b5a4.
- 해결: push 중지 후 GitHub connector로 정확히 동일 tree b73d634a574521b35f9539bbe299ad186432cb33 생성 및 main fast-forward 49b6adf9a4ae20f940926d2a912811173bd7dea2.
- Phase 1 preflight: git fetch origin main; git diff --exit-code HEAD origin/main exit0; 보존 branch phase0-local-preserved; git rebase origin/main에서 동일 patch 자동 skip. main clean, 원격과 동일 HEAD. Force push나 파일 변경 없음.
- 원격 검증: Actions run 45847804990 completed/success (2026-11-27 재조회). 이후 직접 push 가능 여부 별도 확인 필요.
