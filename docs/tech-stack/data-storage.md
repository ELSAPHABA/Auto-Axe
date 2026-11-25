# 데이터베이스·시계열·분석 저장소 기술 설계

## 1. 기본 선택

PostgreSQL 17 + psycopg 3 + SQLAlchemy/Alembic을 기본 원장으로 한다. native RANGE partitioning, B-tree/BRIN, JSONB, COPY/batch insert로 초기 시계열 요구를 처리한다. TimescaleDB/ClickHouse는 실제 저장량·질의·운영 비용에서 이점이 확인되면 별도 ADR로 검토한다. SQLite는 단위 테스트용 단순 fixture에 한정하고 실제 동시성 테스트는 PostgreSQL에서 실행한다.

Parquet + PyArrow는 연구용 불변 데이터셋/허가된 원본 아카이브, DuckDB는 read-only 분석 query, pandas는 피처/모델 입력. 초기에는 private filesystem volume, 확장 시 S3 호환 object store(사용권·비용 확인)로 변경할 수 있는 artifact interface. Valkey는 선택적 최신값 캐시/알림으로만 사용하고 주문·조건·Job 원장의 유일 저장소로 쓰지 않는다.

## 2. 논리 스키마

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

관측값 key 후보: series_id, instrument_id, source_id, source_event_at, source_event_key, revision; source definition/contract/quote_currency/unit/schema version/quality/permission/available_at/ingested_at 보존. 누락 timestamp는 임의 현재 시각을 원본 시각으로 만들지 않는다. 원본 시각 없는 수집은 collected_at을 분리하고 품질 상태 표시. source_event_at이 null인 시계열은 정규화된 명시적 partition timestamp와 별도 dedupe key 사용. Decimal은 NUMERIC(실제 상품 precision/scale 검증 후), 분석 수익률/확률은 double precision, timestamptz UTC, JSONB는 유동 메타데이터·graph config·보조 payload로 제한한다.

관측·틱·1Hz 스냅샷은 partition timestamp의 월별 RANGE를 시작점으로 하며 고빈도 raw는 일/주 파티션을 실측 후 채택. 최신값과 장기 시계열 분리. index: (series_id, instrument_id, event_at DESC), BRIN(time) 대형 append-only 테이블 후보. PostgreSQL 파티션 unique에는 partition key가 포함되어야 하므로 전역 dedupe가 필요한 source_event_id는 별도 unpartitioned registry의 unique key 및 같은 트랜잭션으로 보장. retention 삭제와 event replay/checkpoint 수명 정합성 필요.

단일 1Hz sampler N종목 × 세션 초 수의 row 증가를 기준으로 volume/size를 추정하고 actual load test 후 retention 결정. 시장 휴장·장외·누락 스냅샷 구분; 사용자 데이터 이용권보다 긴 보관 금지. archive는 허용된 데이터만, 삭제/정정 정책과 백업 수명도 일치시킨다.

## 4. 상태와 감사

workflow_versions/group_versions는 배포/실행에 고정; dependency FK 및 삭제 정책, 순환은 application validation + transaction lock으로 처리. node_state key=(run_id,node_id,activation_id,reset_epoch), optimistic version. 같은 event 재처리 방지 및 원자적 outbox. reset은 상태만 초기화하고 주문/체결·중단·risk·idempotency 원장은 유지한다. 주문 attempt는 immutable history와 허용 상태 전이, broker order ID/계좌/모드 unique. 불명 제출은 reconciliation 전 재전송 금지.

감사 event는 actor, client, resource, action, decision, reason, request_id, time, redacted diff, correlation. 일반 앱은 append-only 제한, 관리자의 별도 복구/보관 정책은 감사에 남긴다. password/token/secret/민감 계좌 원문 로그 금지.

## 5. 분석 및 복구

데이터셋 manifest: cutoff, source revision/permission, calendar version, adjustment policy, instruments, feature code commit, schema, 파일 SHA-256, 생성시각. Parquet partition(dataset_version/date 등); staging→atomic publish, checksum 검증. DuckDB query는 allowlist path만, 사용자 임의 SQL/URL 금지. 모델 artifact는 내부 신뢰 저장소/서명·해시 확인 후 로드, 외부 pickle 금지.

백업: pg_dump + WAL archiving/PITR 도입 단계 구분, 암호화된 off-host 백업, 복원 테스트. artifact/IdP DB/필수 설정·비밀 복구 절차 별도. 스냅샷과 DB 참조 버전 일치 검증. migration은 staging 복제본에서 expand/contract 테스트, destructive change 이전 backup. RPO/RTO는 [운영 문서](./infrastructure.md)의 목표를 측정하고 복구 후 주문 대사 및 명시적 재무장.

[PostgreSQL partitioning](https://www.postgresql.org/docs/17/ddl-partitioning.html) · [DuckDB Parquet](https://duckdb.org/docs/stable/data/parquet/overview) · [PyArrow](https://arrow.apache.org/docs/python/)
