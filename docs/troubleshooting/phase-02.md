# Phase 2 트러블슈팅

[현재 Phase 2 운영 기록](../../.ai-context/phases/phase-02/2026-11-27-01.md)과 함께 읽는다. 사용자 2026-11-27 별도 상세 기록 요구에 따른 문서이다.

이 문서에는 문제의 증상과 정확한 재현 절차·환경, 조사/증거, 확인된 원인과 가설, 기각한 해결책, 변경 파일·기술 계약, 실제 재검증 결과, 잔여 위험을 별도로 기록한다. 원본 로그 전체나 비밀정보는 저장하지 않는다.

## TS-02-01 — Scrapling Selector API mismatch
- 재현: Python 3.12.10, uv 0.13.10, Scrapling 0.5.1; uv run --project apps/scraper --locked pytest apps/scraper/tests -q. 초기 5 tests 중 2 failures.
- 원문 증상: AttributeError: 'Selectors' object has no attribute 'get_all'. Did you mean: 'getall'? (parsers.py:23).
- 확인된 원인: 실제 Scrapling 반환 타입의 getall() 메서드를 get_all()로 잘못 가정. 외부 DOM 변경 및 차단과 무관.
- 수정: parsers.py text()에서 getall() 사용. 권한/격리 정책 변경 없음.
- 기각: 브라우저·stealth·proxy 우회, selector 감지 우회는 해당 오류와 관계 없으므로 시행하지 않음.
- 잔여: 실제 사이트 DOM/스크래핑 권한 미확인. 수정 후 검증 결과는 Phase log에 기입.

## TS-02-02 — Windows zoneinfo 및 Decimal 집계 타입
- 증상: Scrapling 첫 오류 수정 후 timezone fixture에서 ZoneInfoNotFoundError: 'No time zone found with key Asia/Taipei'. Backend mypy에서 sum(Decimal list)의 반환값이 Decimal | float | None으로 추론되어 Feature 매개변수 타입 오류 1건. Ruff formatter 전 E501 긴 행 4건.
- 원인: Windows Python 3.12 시스템 tzdata 미제공; Python sum 기본 시작값 int 0; 포맷터 전 긴 문자열.
- 수정: apps/scraper/pyproject.toml에 tzdata>=2025.1 추가, scraper uv.lock에 2026.6 설치. indicator_math.py의 합계 시작값 Decimal(0) 지정, Ruff format을 사용하여 긴 인자 목록 분리.
- 기각: 시스템 시계 변경, timezone 생략, mypy strict 정책 완화, 스크래퍼 browser/stealth 우회는 해당 문제에 무관하므로 시행하지 않음.
- 검증: 격리 scraper 5 passed in 0.42s, 백엔드 재검증 진행 중. 실제 웹 사이트의 source timestamp 검증은 별도 미완료.

## TS-02-03 — Playwright selector ambiguity / synthetic SSE proxy
- 증상: 최초 Phase 2 Playwright 실행에서 getByText('123.45') strict mode failure. 대상 요소 두 개: 실제 Fixture 값과 설명문 문구. 또한 fixture SSE route가 없는 단독 Vite preview에서 localhost:8000 ECONNREFUSED proxy 오류. 사용자의 실제 데이터 결측과는 무관.
- 원인: 텍스트 selector가 유일하지 않았고 E2E가 SSE만 mock 처리하지 않음.
- 수정: .indicator-value에 범위를 제한한 locator 및 고정 SSE ready 이벤트 route fixture 추가. 실제 네트워크 대신 테스트 응답을 보낼 뿐 실제 연결 성공으로 주장하지 않음.
- 재검증: 수정된 pnpm test:e2e 결과를 Phase log에 기록.

## TS-02-04 — ECharts JSDOM layout/canvas 부재
- 증상: 새 합성 차트가 Vitest에서는 테스트 성공하지만 HTMLCanvasElement.getContext() not implemented 와 ECharts zero width/height warning 다수. Playwright 실제 브라우저와 JSDOM 동작 환경이 다름.
- 수정: SVG 렌더러를 사용하고, 실제 레이아웃 폭이 0인 테스트 환경에서는 ECharts 초기화를 생략하며 의미 있는 대체 텍스트/ARIA 표기를 유지. 브라우저에서는 크기가 확보되면 그린다.
- 재검증: 전체 UI unit + 실제 Playwright 재실행; synthetic chart 외 승인 없는 공급자 차트를 생성하지 않음.

## TS-02-05 — 중복 실행된 PostgreSQL 통합 테스트에서 교차 DB 연결 타임아웃
- 재현: Phase 2 최종 전체 `uv run --project apps/backend --locked pytest apps/backend/tests -q --tb=short`를 서로 다른 로컬 도구 세션으로 두 번 동시에 실행하고, 같은 Windows Docker 엔진에서 Phase2 Docker Compose 이미지를 빌드했다. 먼저 시작한 suite는 77 passed (추가 expiration test 전). 나중 suite는 78 passed / 1 failed / 2 warnings / 208.00s.
- 실패 원문: `test_db.py::test_database_role_matrix:72`의 `pytest.raises(psycopg.OperationalError, match="permission denied")` 조건 불일치. 실제 예외는 `connection timeout expired; host localhost port 3017 (::1 and 127.0.0.1)`. 테스트는 타 DB 접근 거부를 기대했으나 그 시점에 host mapped port 자체가 응답하지 않았다.
- 조사: 동일 소스/DB 권한 테스트가 별도 앞선 단독 테스트에서는 통과했으며 새 Phase 2 DDL은 특정 실행 모드 전체 CONNECT 권한을 허용하지 않는다. 두 독립 Testcontainers PG17 테스트/Compose 빌드를 한 Windows Docker 엔진에서 동시에 실행한 환경 부하가 잠재 원인이다. **현재까지 자원 경합은 가설**이며 PostgreSQL 접근 권한을 잘못 설정했다는 증거 없음.
- 기각: `permission denied` 대신 `timeout`도 성공으로 처리하게 검사 조건을 완화하면 보안 격리 테스트가 실제 DB 접근 거부를 검증하지 못한다. DB 역할 추가·권한 완화, 우회하지 않는다.
- 조치: 중복 suite가 종료됐음을 확인하고 Compose build/smoke 완료 후 실제 PG role matrix를 단독으로 재실행, 정확한 결과를 기록할 것. CI는 한 job의 단일 pytest 명령으로 병렬 실행하지 않는다.
- 검증 및 잔여: 재검증 결과를 Phase log에 기입. Docker Desktop 고부하의 지속 여부를 별도 모니터링, 신규 schema가 실제 CONNECT 권한에 미치는 영향도 조회 필요.
- 단독 재검증: 중복 전체 suite/Compose를 종료하고 `uv run --project apps/backend --locked pytest apps/backend/tests/test_db.py -q --tb=short`를 단일 프로세스로 실행: 1 passed, 1 preexisting deprecation warning in 30.92s. 기존 cross-DB 실제 `permission denied` 기대가 통과했고 DB role 정책 변경 없이 복구. 자원 경합의 직접 증명은 아니나 병렬/빌드 동시 실행 상황의 일시적 포트 타임아웃이라는 가설을 지지. CI에서는 single full suite, 테스트 조건 완화 없음.

## TS-02-06 — 읽기 전용 Scrapling 테스트 컨테이너 Pytest cache 경고
- 재현: `docker compose --env-file .env.phase0 -f infra/compose/dev.yaml --profile scraper-fixture run --rm --build scraper-fixture`; network_mode none/read_only=true의 /app 경로에 pytest cache 생성 실패. `PytestCacheWarning: could not create cache path /app/.pytest_cache/... [Errno 30] Read-only file system`. 테스트 결과 자체는 5 passed, 1 warning in 0.67s.
- 원인: pytest cacheprovider가 설치/소스 디렉터리에 cache를 기본 저장하려는 동작. 운영 환경 보안정책(read_only)은 정상 기능.
- 해결: apps/scraper/Dockerfile의 pytest 실행에 `-p no:cacheprovider`를 추가해 cache 플러그인만 사용하지 않음. 파일시스템 read_only를 해제하거나 불필요한 writable layer 추가하지 않음.
- 재검증: 로컬 재빌드/CI 결과는 Phase log에 기록. 네트워크 차단과 캐시 설정은 별개.
- 재검증 완료: `docker compose ... --profile scraper-fixture run --rm --build scraper-fixture` → `5 passed in 0.54s`, 캐시 경고 제거, `network_mode: none`·read_only 유지.

## TS-02-07 — ECharts 패키지 초기 번들 크기 경고
- 증상: 프런트엔드 첫 Vite build에서 ECharts를 메인 페이지에 정적 import하면 전체 초기 JS가 크게 증가. 이후 구성에서도 `Some chunks are larger than 500 kB after minification` 경고가 남음.
- 조사: `apps/web/src/dashboard.tsx`에서 `FixtureChart` 정적 import 시 초기 렌더 경로에 ECharts 전체 시각화 라이브러리가 포함됨. 실제 금융 데이터 없음에도 브라우저가 차트 코드를 초기 다운로드할 이유가 없음.
- 해결: `React.lazy(() => import('./fixture-chart'))` 및 Suspense로 선택적 합성 차트 코드 분리. 실제 build: 초기 index JS 312.23kB(gzip 98.80kB), 별도 fixture-chart JS 504.47kB(gzip 173.45kB). chart 미사용 화면에 메인 번들 강제 포함하지 않음.
- 재검증: Vite build 및 Playwright E2E 통과. 차트 chunk 자체는 500kB 경고 임계값보다 4.47kB 커서 **경고 미해결**. 나중 실제 차트 구현 시 필요한 ECharts 컴포넌트만 로드하는 최적화/예산측정 및 브라우저 성능 테스트 필요. 경고 한도만 올려 숨기는 방식은 기각.

## TS-02-08 — Vitest include 글로브가 SSE 테스트 누락
- 증상: `apps/web/src/live.test.ts`에 SnapshotGate 순서/replay/gap/reconnect 테스트 2개를 추가했지만 `pnpm test`가 계속 `src/App.test.tsx`의 테스트 2개만 실행함. 모든 테스트 통과라고 보고하면 실제 신규 SSE 계약 테스트를 놓치는 문제.
- 확인된 원인: `apps/web/vite.config.ts`의 Vitest 설정 `include: ["src/**/*.test.tsx"]`에서 `.test.ts` 확장자를 제외함.
- 해결: `include: ["src/**/*.test.tsx", "src/**/*.test.ts"]`를 명시. 테스트 코드를 .tsx로 위장하거나 실행되지 않는 채 성공 주장하지 않음.
- 재검증: 최초 설정 수정 직후 `pnpm format:check`가 vite.config.ts 포맷 경고로 exit1; `prettier --write vite.config.ts` 후 `pnpm typecheck/lint/format:check/test` 전부 exit0. `src/App.test.tsx` 2개와 `src/live.test.ts` 2개, **2 test files / 4 passed in 11.24s**. 기존 2 passed에서 SSE 2 tests가 실제 실행되도록 수정.
