# Phase 1 트러블슈팅

[Phase 기록](../../.ai-context/phases/phase-01/2026-11-27-01.md). 증거를 확보한 문제를 추가한다. 최초 preflight에서 Phase 0 로컬/원격 동일 tree 이력 분기 해결: [TS-00-08](phase-00.md#ts-00-08--로컬-github-인증-부재-및-이력-분기).

## TS-01-01 — 초기 Python 정적 검사 실패

- 재현: Phase 1 신규 코드 작성 후 프로젝트 uv 환경에서 `ruff check --fix apps/backend/src apps/backend/tests apps/backend/migrations`, `ruff format ...`, `ruff check ...`, `mypy --config-file apps/backend/pyproject.toml apps/backend/src`.
- 관측: 최초 Ruff 37건(12개 자동 수정, 25개 남음). formatter 이후 SQL/GRANT 긴 문자열 11개 E501 잔류. mypy는 adapters/manual.py:39에서 `Need type annotation for "result" [var-annotated]` 1건. 비통합 pytest 56 passed 및 실제 PG test 1 passed는 별도 증거로, 정적 검사 실패를 상쇄하지 않음.
- 원인: SQL DDL/테스트 SQL에 100자 초과 문자열, CSV 동적 타입 때문에 빈 list 원소 타입 추론 불가. formatter만으로 SQL 문자열 줄바꿈 불가.
- 해결: 0002_market.py의 SQL/GRANT 줄을 의미 유지하며 분리, jobs.py와 DB 테스트 SQL 분리, manual.py `list[Candidate]` 타입 명시. lint rule 완화/ignore 대신 실제 수정.
- 재검증: 최종 Ruff all checks passed; mypy success 26 source files; backend 59 passed (45.84s).

## TS-01-02 — PostgreSQL 조회가 방금 커밋한 관측을 누락

- 재현: series_version/월별 partition 추가 후 `pytest apps/backend/tests/test_phase1_db.py -q --tb=short`, test_ledger_jobs_and_mode_ingress에서 rows=[] (expected 2). 이전 동일 테스트는 통과.
- 조사: SQL의 snapshot/version 조건과 바인딩 순서를 확인. Windows host UTC 15:31:47.5958829Z → Linux Docker date 15:31:49.327589194Z → Windows host UTC 15:31:48.5989487Z. 컨테이너 시계가 host보다 최소 약 0.73초 앞섬. ingest는 PostgreSQL clock_timestamp(), 조회 기본 cutoff는 Windows host datetime.now(UTC)로 달라 commit 직후 ingested_at<=cutoff 조건에서 누락 가능.
- 수정: market API의 기본 cutoff와 future validation을 연결한 PostgreSQL의 clock_timestamp()로 결정, 테스트도 DB clock을 사용. 사용자 명시적 과거 cutoff와 source_event_at/received_at/available_at는 변경하지 않음. cutoff를 임의 미래로 밀거나 ingestion 필터 제거는 PIT 정확도를 깨므로 기각. 동일 series의 committed snapshot version을 cursor에 포함하여 페이지 사이 새 정정이 섞이지 않도록 함.
- 잔여: 실제 거래소/서버 NTP 및 commit timestamp/PIT 정확성은 운영 검증 대상. DB clock과 수집 호스트 차이를 시정한 것으로 주장하지 않음.
- 재검증: 수정 후 전체 backend 58 passed (80.18s), 이후 보강 및 최종 59 passed. Compose 실제 job/조회 성공, FIXTURE_PRICE 123.45.

## TS-01-03 — yfinance 타입 정보 누락

- 증상: mypy `Skipping analyzing "yfinance": module is installed, but missing library stubs or py.typed marker [import-untyped]`, 26 source files 중 1 오류.
- 수정: 라이브러리 경계의 해당 import만 targeted ignore[import-untyped]; 전역 mypy 엄격 검사 유지. 입력/출력 정규화와 mock transport 검증 별도. 실제 Yahoo 접근/지연/권한은 미검증.
- 재검증: 최종 mypy success 26 source files, backend 59 passed.

## TS-01-04 — 2년물 fallback 조회의 nullable row 타입

- 재현: Naver healthy + latest observation 존재/quality/TTL 검사 보강 후 mypy apps/backend/src. market_store.py:445–450에서 `Value of type "Any | None" is not indexable [index]` 4건. 또한 신규 테스트 SQL 한 줄 103자 E501.
- 원인: fetchone()은 None 가능; healthy = row and ... 결과를 통해 mypy가 원래 row 타입을 narrow하지 못함. 테스트 문자열은 formatter 선행으로 분리 가능.
- 해결: row is None을 먼저 처리. 승인된 Naver의 상태 기록 자체가 없으면 primary_status_unknown으로 멈추고, Treasury row 없으면 continue. 그 다음 non-null row의 최신값, quality, TTL 또는 official_daily metadata 검사. 타입 ignore/강제 cast로 nullable 처리를 감추지 않음. Ruff format 이후 check.
- 재검증: 최종 ruff all checks passed, mypy 26 source files success, schema check success, 실제 PG 포함 backend 59 passed / 2 deprecation warnings / 45.84s. 테스트가 권한 취소→fallback, primary 회복, manual review 및 checkpoint, relay까지 검증.
- 잔여: Treasury 발표 일정/aging과 외부 source activation은 실제 검증하지 않음.

## TS-01-05 — staged diff 비밀정보 검사 오탐 및 문서 공백

- 재현: git diff --cached --check에서 새 문서 11개 행의 trailing whitespace; 이후 pinned Gitleaks v8.30.0 redacted staged scan에서 generic-api-key 2건.
- 조사: 검출 위치는 Phase 1 log 25행의 lease/token 및 slash-delimited 함수 설명, Compose fixture-collector command 97행의 합성 idempotency identifier. 둘 모두 인증값이 아님. 실제 로컬 환경값은 열람하거나 기록하지 않음.
- 수정: 해당 문서 행의 후행 공백만 제거, 기능 설명을 자연어로 변경, 합성 idempotency identifier를 짧고 명백한 smoke로 변경. 검출 rule이나 scanner 비활성화하지 않음. 동일 합성 작업 계약이며 실제 권한 부여와 무관.
- 재검증: staged check 및 동일 scan 재실행 결과는 커밋/검증 기록 참조.

## TS-01-06 — 스케줄러/스트림 추가 후 정적 검사

- 재현: `ruff check apps/backend`, `ruff format apps/backend`, `mypy apps/backend/src`. 최초 polling/worker 긴 행 E501, formatter 이후 stream_worker.py:44 SELECT 104자 E501 및 mypy `Need type annotation for "checkpoints" [var-annotated]`.
- 원인: SQL 문자열 자동 줄바꿈 한계, psycopg 동적 row 타입에서 dict 타입 추론 불가.
- 해결: SQL을 인접 문자열로 분리, checkpoint dict[str, int] 명시. lint/type 규칙 우회하지 않음.
- 재검증: Ruff 통과, mypy 30 source files success, schema 검사 통과. 이전 PG 확장 test 1 passed in 53.95s. 최종 결과는 [후속 로그](../../.ai-context/phases/phase-01/2026-11-27-02.md).

## TS-01-07 — 공급자 오류 및 재시작 경계에서 중복 호출 위험

- 코드 조사에서 발견: 이전 runner에는 실제 durable scheduling과 provider 단위 429/403 차단 상태가 없고, unscoped claim은 서로 다른 수집 작업을 가져갈 수 있었음. 기존 helper만으로 재시작 중복과 권한 변경 중 결과 적재를 방지한다고 주장할 수 없음.
- 해결: 0003_polling durable slot/circuit, advisory leader lock, owner/series scoped claim, DB 기반 cooldown, 새 permission version 확인. 작업 시작/저장 시 버전 일치 확인, stale lease 처리. 스트림의 source→trade→series lock 순서 통일 및 checkpoint 재사용.
- 회귀: 실제 PG에서 24개 ratio 300초, 299초 중복 없음, 429 90초 차단, 403 차단과 version 갱신 후 재개, WS ID 3/4 백필과 중복 5, checkpoint 6, 권한 변경 이후 결과 폐기를 테스트하여 1 passed in 53.95s. 실제 공급자 권한/응답 검증은 별개.

## TS-01-08 — PoC 참고 시세의 상품 및 일별 최신값 혼동 위험

- 코드 조사: 기존 PoC의 REST snapshot, 현물 참고, EOD, 다른 거래소 원본과 주 시세 체결은 정의/통화/시간 해상도가 다르며, source_event_at 미상인 일별 값은 적재 순서만으로 최신 날짜를 결정하면 늦게 들어온 과거 날짜가 최신값을 덮을 수 있음.
- 해결: 11개 독립 참고 시계열 등록, offline reference parser와 import/preview, 날짜 기반 daily latest 비교, 정확 발표시간 미상은 null/UNKNOWN. 원본 PoC는 보존.
- 검증: 참고값 fixture 테스트 및 전체 backend suite 결과는 후속 로그 참조. 실제 서비스 호환/수집 권한은 미검증.

## TS-01-09 — Compose 선택 프로필 이미지 갱신 누락

- 재현: 기존 볼륨과 이미지가 남아 있는 Windows Docker 환경에서 `docker compose --env-file .env.phase0 -f infra/compose/dev.yaml up --build -d --wait` 후 `--profile fixture-collect run --rm fixture-collector /app/.venv/bin/python -m autoaxe.entrypoints.market_cli fixture-poll --cycles 2 --sleep 5`. PG/API/Web healthy, migrate exit 0, 수집 CLI exit 2: `invalid choice: 'fixture-poll'` (기존 catalog/manual-preview/fixture-collect/manual-import/manual-review만 표시).
- 원인: 기본 프로필의 up --build는 선택 프로필의 기존 fixture-collector 이미지를 재빌드하지 않음. 새 Python 소스와 오래된 별도 서비스 이미지가 불일치. 마이그레이션이나 parser 구현 문제가 아님.
- 해결: 선택 프로필 run에 --build 추가, CI 및 실행 문서에 동일 명령 반영. 기존 DB 볼륨 삭제 또는 임의 이미지 전체 삭제는 불필요하므로 하지 않음.
- 재검증: 두 cycle 모두 scheduled=1, processed=1, 신규 FIXTURE_PRICE 123.45 USD 두 건 valid 조회, down exit 0, ps -a 비어 있음. 이전 volume 유지. 후속 Phase log에 관측 ID 기록.
