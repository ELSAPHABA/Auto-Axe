# 데이터베이스·시계열·분석 저장소 기술 설계

## 1. 기본 선택

[공통 기술 계약](./contracts.md) §4~6에 따라 PostgreSQL 단일 인스턴스에 Database/Role을 분리한다. autoaxe_market(공통 시장), autoaxe_app(정의·권한·BFF 세션), autoaxe_backtest/autoaxe_dry_run/autoaxe_paper_local/autoaxe_paper_broker/autoaxe_live(모드별 원장), autoaxe_identity(Keycloak 전용), autoaxe_dev/autoaxe_test(개발/테스트). LIVE 물리 분리는 필요 시 적용하며 별도 credential 및 DB CONNECT 제한을 사용한다.

[전체 플랫폼 보안 설계](./security.md)의 데이터 등급·DB 역할·암호화·감사·백업 정책을 적용한다. scraper-worker에는 DB credential을 부여하지 않고 broker/검증 계층만 결과를 적재한다. 거래 비밀은 DB 일반 조회와 연구 artifact에서 제외하며 DB 접근 제약과 API 리소스 정책을 함께 검증한다.

PostgreSQL 17 + psycopg 3 + SQLAlchemy/Alembic을 기본 원장으로 한다. native RANGE partitioning, B-tree/BRIN, JSONB, COPY/batch insert로 초기 시계열 요구를 처리한다. TimescaleDB/ClickHouse는 실제 저장량·질의·운영 비용에서 이점이 확인되면 별도 ADR로 검토한다. SQLite는 단위 테스트용 단순 fixture에 한정하고 실제 동시성 테스트는 PostgreSQL에서 실행한다.

Parquet + PyArrow는 연구용 불변 데이터셋/허가된 원본 아카이브, DuckDB는 read-only 분석 query, pandas는 피처/모델 입력. 초기에는 private filesystem volume, 확장 시 S3 호환 object store(사용권·비용 확인)로 변경할 수 있는 artifact interface. Valkey는 선택적 최신값 캐시/알림으로만 사용하고 주문·조건·Job 원장의 유일 저장소로 쓰지 않는다.

## 2. 논리 스키마

아래 표는 논리 도메인 스키마이며 하나의 DB에 모두 배치한다는 의미가 아니다. market/catalog/indicator 수집은 market DB, identity/공통 정의는 app DB, research/backtest는 backtest DB 및 허용 artifact, 실행 상태/승인/위험/주문/체결/감사는 각 모드 DB에 배치한다. ops outbox/inbox/jobs는 해당 원장의 DB 안에 둔다. 공통 정의와 시장 관측은 versioned snapshot/reference로 소비한다.

| 스키마 | 주요 테이블 |
|---|---|
| identity | principals, roles, grants, client_registry, account_access |
| catalog | instruments, series, source_registry, instrument_mappings, calendars, calendar_versions |
| market | observations, ohlcv, volume_snapshots, long_short_stats, source_events, latest_observations |
| indicator | indicator_observations, economic_events, event_revisions, features, group_metrics |
| strategy | stock_groups, stock_group_versions, group_members, workflows, workflow_versions, workflow_dependencies, workflow_runs, node_states, workflow_reset_cycles, condition_results |
| research | datasets, feature_sets, model_versions, predictions, backtests, artifacts, backtest_trades |
| trading | order_intents, risk_decisions, approvals, order_attempts, broker_orders, fills, reconciliations, kill_switches, account_risk_state |
| ops | jobs, job_attempts, outbox, consumer_inbox, checkpoints, collector_health, audit_events |

별도 schema/DB role로 권한 범위를 제한한다. Executor는 trading의 필요한 테이블/프로시저와 최소 read contract만 접근. Keycloak DB/role 분리. 일반 조회 role은 비밀/원장 변경 권한 없음. identity는 IdP의 인증정보를 재구현하지 않고 플랫폼 권한·연결 매핑만 저장한다.

## 3. 시계열 계약

논리 지표 indicator_id와 실제 원본 series_id를 분리한다. source registry/mapping은 indicator_id, series_id, instrument_id, provider, contract, unit, currency, frequency, priority, equivalence policy, mapping_version, permission, freshness_policy를 보존한다. UST_2Y 논리 지표의 최우선 원본은 UST_2Y_TOSS(ROB.US2YT-RR), 임시 fallback은 UST_2Y_TREASURY(BC_2YEAR)이며 별도 원본 시계열로 저장한다. 활성 공급원 선택·실패 사유·전환 시각·복귀를 versioned provenance에 기록한다. 연속 수익률/EDGE/이동평균 등의 계산은 원본 전환 경계에서 이어 붙이지 않고 재기준화 또는 UNKNOWN 처리한다. 원본 고정이 기본이며 명시적으로 허용된 동등/호환 정의의 fallback만 Workflow에 사용한다. UST_2Y_TOSS는 Session 23 사용자 승인으로 자동매매 판단 허용 대상이다. Workflow는 현재 permission version과 gate(trading), fetch/storage 권한, 검수 완료 및 관측값 automated_trading_allowed=true, 정상 health, 960초 receipt 상한을 모두 검사한다. 원본 시각이 필수이면 UNKNOWN; 기존 false 관측값은 소급 변경하지 않는다.

관측값 key 후보: series_id, instrument_id, source_id, source_event_at, source_event_key, revision; source definition/contract/quote_currency/unit/schema version/quality/permission/available_at/ingested_at 보존. 누락 timestamp는 임의 현재 시각을 원본 시각으로 만들지 않는다. 원본 시각 없는 수집은 collected_at을 분리하고 품질 상태 표시. source_event_at이 null인 시계열은 정규화된 명시적 partition timestamp와 별도 dedupe key 사용. Decimal은 NUMERIC(실제 상품 precision/scale 검증 후), 분석 수익률/확률은 double precision, timestamptz UTC, JSONB는 유동 메타데이터·graph config·보조 payload로 제한한다.

관측·틱·1Hz 스냅샷은 partition timestamp의 월별 RANGE를 시작점으로 하며 고빈도 raw는 일/주 파티션을 실측 후 채택. 최신값과 장기 시계열 분리. index: (series_id, instrument_id, event_at DESC), BRIN(time) 대형 append-only 테이블 후보. PostgreSQL 파티션 unique에는 partition key가 포함되어야 하므로 전역 dedupe가 필요한 source_event_id는 별도 unpartitioned registry의 unique key 및 같은 트랜잭션으로 보장. retention 삭제와 event replay/checkpoint 수명 정합성 필요.

단일 1Hz sampler N종목 × 세션 초 수의 row 증가를 기준으로 volume/size를 추정하고 actual load test 후 retention 결정. 시장 휴장·장외·누락 스냅샷 구분; 사용자 데이터 이용권보다 긴 보관 금지. archive는 허용된 데이터만, 삭제/정정 정책과 백업 수명도 일치시킨다.

## 4. 상태와 감사

한 모드의 Workflow state·intent·승인·risk reservation·order/fill ledger·outbox를 같은 DB transaction 경계에 둔다. cross-DB 시장/정의/권한 이벤트는 durable outbox/inbox 및 mode별 ingress를 사용한다. 승인 철회는 해당 mode gate에 반영 후 완료, 공통 인가 확인 실패/불일치 시 신규 주문 fail closed. [DB 및 Role 계약](./contracts.md) §5.

strategy에 workflow_run_modes, evaluation_seq/snapshot input references, refresh_generations, activation/invocation identity를 저장한다. trading에 strategy_approval_grants, order_conflicts, order_reservations, account/mode/instrument/session별 risk counters 및 priority enqueue ordering을 저장한다. mode enum은 BACKTEST, DRY_RUN, PAPER_LOCAL, PAPER_BROKER, LIVE이며 PAPER는 집계 라벨이다. order_intents는 canonical key unique 및 payload_hash 비교, 승인 grant 버전, risk reservation 상태를 영속화한다. reset_epoch/activation_id가 신규 유효 실행과 retry를 분리한다. 일별 위험 카운터는 계좌의 지정 거래 세션으로 계산하며 Workflow reset으로 초기화하지 않는다.

workflow_versions/group_versions는 배포/실행에 고정; 동일 DB 내부 dependency FK와 application validation/transaction lock을 적용한다. DB 간 참조는 app DB의 durable reservation/import ack/terminal release로 관리하고, 불명 참조는 삭제 차단한다. cross-DB FK/단일 transaction을 가정하지 않는다. node_state key=(run_id,node_id,activation_id,reset_epoch), optimistic version. 같은 event 재처리 방지 및 원자적 outbox. reset은 상태만 초기화하고 주문/체결·중단·risk·idempotency 원장은 유지한다. 주문 attempt는 immutable history와 허용 상태 전이, broker order ID/계좌/모드 unique. 불명 제출은 reconciliation 전 재전송 금지.

감사 event는 actor, client, resource, action, decision, reason, request_id, time, redacted diff, correlation. 일반 앱은 append-only 제한, 관리자의 별도 복구/보관 정책은 감사에 남긴다. password/token/secret/민감 계좌 원문 로그 금지.

## 5. 분석 및 복구

데이터셋 manifest: cutoff, source revision/permission, calendar version, adjustment policy, instruments, feature code commit, schema, 파일 SHA-256, 생성시각. Parquet partition(dataset_version/date 등); staging→atomic publish, checksum 검증. DuckDB query는 allowlist path만, 사용자 임의 SQL/URL 금지. 모델 artifact는 내부 신뢰 저장소/서명·해시 확인 후 로드, 외부 pickle 금지.

백업: pg_dump + WAL archiving/PITR 도입 단계 구분, 암호화된 off-host 백업, 복원 테스트. artifact/IdP DB/필수 설정·비밀 복구 절차 별도. 스냅샷과 DB 참조 버전 일치 검증. migration은 staging 복제본에서 expand/contract 테스트, destructive change 이전 backup. RPO/RTO는 [운영 문서](./infrastructure.md)의 목표를 측정하고 복구 후 주문 대사 및 명시적 재무장.

[PostgreSQL partitioning](https://www.postgresql.org/docs/17/ddl-partitioning.html) · [DuckDB Parquet](https://duckdb.org/docs/stable/data/parquet/overview) · [PyArrow](https://arrow.apache.org/docs/python/)
