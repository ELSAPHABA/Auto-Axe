# Phase 1 — 시장 데이터 수집·저장 기반

2026-11-27 KST. [계획](PHASE_PLAN.md) · [상세 작업 로그](../../.ai-context/phases/phase-01/2026-11-27-01.md) · [트러블슈팅](../troubleshooting/phase-01.md).

후속 세션: [스케줄러·복구·PoC 보강 기록](../../.ai-context/phases/phase-01/2026-11-27-02.md). 기존 57개 시계열에 11개 참고 원본을 추가했다(5 REST snapshot, Gold reference, EIA 2, Cboe EOD, Coinbase, BTC 1m 확정봉). 모든 추가 원본은 권한 확인 전 자동 실행 차단.

## 구성 및 계약

| 작업 | 구현 | 검증 범위/제약 |
|---|---|---|
| P1.1 | domain/catalog.py, domain/market.py, catalog.source_registry, permission_versions, instrument_mapping | 57 시계열 정의(6 가격, 24 비율, Yahoo 5, Naver 1, Treasury 5, 수동 15, 합성 1). 실제 외부 사용권 미확인, 기본 차단 |
| P1.2 | 0002_market.py, infrastructure/market_store.py, market_api.py | PG17 실제 DB: Decimal, revision, dedup, 월 partition 및 default, PIT, 최신값, cursor snapshot/version. 장기 retention/운영 부하 미검증 |
| P1.3 | infrastructure/jobs.py, application/market_worker.py | SKIP LOCKED claim/lease/heartbeat/retry/cancel, outbox/inbox 원자 커밋, relay ack 및 version gap. 외부 실행 없음 |
| P1.4 | adapters/providers.py, transport.py, application/collection.py | Binance BTC Spot trade, XAU/XAG/COPPER/CL/BZ USDT perpetual aggTrade, 4 ratio 종류 × 6 symbols, fixture parser/REST/WS/recovery. 실제 공급자 호출·자동 주기 실행 미활성 |
| P1.5 | Yahoo VIX 및 4 국채 지표, Naver 2Y, Treasury daily parser/selection | source-specific freshness, separate UST_2Y_NAVER/UST_2Y_TREASURY, provenance; Naver 권한/실제 scraping 및 publication schedule 검증 별도 |
| P1.6 | adapters/manual.py, entrypoints/market_cli.py | CSV preview/import 및 독립 review; permission gate, self-review 금지. 실제 수동 데이터 미입력 |
| P1.7 | tests/test_phase1_providers.py, test_phase1_db.py, Compose CI | 실제 PostgreSQL + 합성 수집 작업; disconnect/gap/error 정규화 및 계약 회귀. 장기 외부 운영 검증은 별도 |

이 표는 구현 기반 검증과 운영 이용권 승인을 구별한다. FR-001~007, FR-101~106, FR-108~111의 해당 기반을 다루며 모든 지표 계산/UI/운영 가동을 완료했다는 의미가 아니다. FR-007 전체 지표 계산·대시보드는 Phase 2 이후.

## 재현

```sh
uv sync --project apps/backend --locked --group collection-smoke
uv run --project apps/backend --locked ruff check apps/backend
uv run --project apps/backend --locked mypy apps/backend/src
uv run --project apps/backend --locked python -m autoaxe.adapters.schema --check
uv run --project apps/backend --locked pytest apps/backend/tests
pnpm contracts:types
pnpm typecheck
pnpm lint
pnpm test
pnpm build
python scripts/init_dev_env.py
docker compose --env-file .env.phase0 -f infra/compose/dev.yaml up --build -d --wait
docker compose --env-file .env.phase0 -f infra/compose/dev.yaml --profile fixture-collect run --rm fixture-collector
docker compose --env-file .env.phase0 -f infra/compose/dev.yaml --profile fixture-collect down
```

실제 smoke에서 job 86a73ff5-629d-4260-bc10-3f642af5ebd2 succeeded, observation 5504e118-5dcb-4c16-aac0-0a7f058966f9, FIXTURE_PRICE=123.45 USD, quality valid, revision/mapping/permission/snapshot version 1. API `GET /api/v1/market/observations?series_id=FIXTURE_PRICE`, loopback 18174, response environment fixture. PostgreSQL/API/Web healthy, migration exit 0. down 후 ps -a 비어 있음, Volume 보존.

조회 API: GET /api/v1/market/series, /api/v1/indicators, /api/v1/market/observations. 마지막 API는 series_id 및 cutoff/quality/keyset pagination 계약. 시계열별 committed snapshot_version을 cursor에 유지. 기본 cutoff는 DB 시각; source_event_at/received_at/available_at/ingested_at 분리.

CLI: `uv run --project apps/backend --locked python -m autoaxe.entrypoints.market_cli catalog`; `manual-preview <csv>` (DB 불필요); `manual-import <csv>`, `manual-review <observation_id> --reviewer <id> --status checked|rejected --reason <reason>`는 명시적으로 제한된 fixture write DSN 필요. fixture-collect --key <key> 는 합성 작업만 수행. 환경 변수 값은 로컬 비밀 설정이며 저장 금지.

## 후속 구현

- 0003_polling: 기존 DB에 durable polling slot, source circuit, active job index 추가. 24개 롱숏 시계열 300초 cadence, 중복 및 overlapping jobs 방지, 재시작 복구, 429 Retry-After/403 차단 및 permission version 변경 검증.
- application/stream_worker.py: DB checkpoint를 재연결에 전달하고 원자적 체결 적재, gap 복구 및 권한 변경 fence. 실제 외부 WS 미호출.
- CLI 합성 반복 수집: `docker compose --env-file .env.phase0 -f infra/compose/dev.yaml --profile fixture-collect run --rm --build fixture-collector /app/.venv/bin/python -m autoaxe.entrypoints.market_cli fixture-poll --cycles 2 --sleep 5`.
- CLI offline reference: `reference-preview <source> <json> --received-at <aware ISO datetime> [--symbol <symbol>]`; `reference-import`는 같은 인자와 scoped fixture write DSN, 원본 권한 필요. 원본 PoC 기능 중 시장 참고값의 정규화 계약을 보강하며 실제 HTTP 수집 권한과 분리한다.

## 남은 운영 게이트

Phase 1 개발 fixture 종료 검증: 구현 commit f1352a69e6d4115bf016029fc8cee97e29a27a69, backend 66 passed locally, [GitHub Actions 45854005885](https://github.com/ELSAPHABA/Auto-Axe/actions/runs/45854005885) completed/success. contracts-backend, frontend(Playwright 포함), fixture-compose, secret-scan 모두 성공. 실제 운영 권한이나 실제 데이터 품질 보증과는 별개.

공급자 이용권/재배포 및 rate limit, Binance spot historical raw ID 권한, Yahoo 실제 지연, Naver 승인형 Scrapling, Treasury 발표 시각/일정, 장시간 외부 collector 서비스 및 실제 소스 reconnect, 운영 retention/load/backup/security, 인증 및 UI는 미검증 또는 후속 구현. 300s scheduler는 fixture로 검증하며 외부 provider 활성화와 별개. 경제·공시·캘린더 PoC는 Phase 2 범위. Treasury daily timestamp 미확인 시 null 및 UNKNOWN 유지; fallback은 표시용이며 장중 동일 소스인 것처럼 수익률 연결 금지. LIVE·실계좌·외부 MCP 계속 차단.
