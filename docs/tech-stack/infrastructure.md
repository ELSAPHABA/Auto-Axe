# 인프라·DevOps·운영 기술 설계

실행 환경은 BACKTEST/DRY_RUN/PAPER_LOCAL/PAPER_BROKER/LIVE로 구분한다. PAPER_LOCAL에는 증권사 주문 비밀을 제공하지 않고 PAPER_BROKER는 공식 모의 endpoint 및 모의 계좌만 허용한다. LIVE는 별도 승인 프로필 및 계좌·비밀·원장으로 격리한다.

## 1. 배포 전략

[전체 플랫폼 보안 설계](./security.md)의 SEC 요구사항을 적용한다. 기본 외부 ingress 차단, 관리 VPN 또는 사설망, host nftables/동등 방화벽과 Docker forwarding 정책을 실제 테스트한다. 스크래퍼는 전용 제한 egress gateway 이외의 외부 통신 및 내부 서비스 접근을 차단하고, broker는 고정 job/result 계약만 허용한다. 운영 비밀은 역할별 mount 및 회전, off-host 암호화 백업, 이미지 서명/취약점 검사, 보안 사고 대응 훈련을 적용한다. 외부 MCP 및 LIVE 기본 비활성 유지.

Linux 단일 서버 또는 개인 홈서버/VM + Docker Engine/Compose를 초기 기준으로 한다. CPU/RAM/SSD 및 네트워크 비용을 측정하며 AWS 등 특정 클라우드·Kubernetes·대형 메시지 클러스터를 기본 필수로 두지 않는다. 실제 호스트와 도메인/예산은 사용자 지정 전까지 미확정이다. 단일 호스트는 HA가 아니며 장애 시 안전하게 중단하고 복구한다.

| 서비스 | 프로필/네트워크 |
|---|---|
| caddy + web | edge; 공개 HTTPS, SPA 정적 파일 |
| api, mcp | app; private upstream, mcp external off 기본 |
| collector, scheduler, workflow, worker, relay | app/data; provider egress 필요한 역할만 |
| scrape-broker / scraper-worker / egress-gateway | scraper 전용 격리 zone, source allowlist와 검증된 typed result; worker에 DB·브로커 자격증명 없음 |
| postgres | private data; named volume, DB role 분리 |
| keycloak | private auth/data, 별도 database/role |
| nhplug-read | private broker-read, 별도 계정 credential |
| executor-paper | 명시적 paper profile, broker sandbox allowlist |
| executor-live | 별도 승인된 프로필/host 또는 격리 네트워크, 기본 미기동 |
| valkey | optional cache; DB truth와 분리 |
| prometheus/grafana | ops private; dashboard 관리 VPN/사설망 |
| research artifact volume | private, worker writer 제한, DB metadata |

local/dev: fixtures + PostgreSQL + API/web, 필요 시 Keycloak 및 모의 executor. paper/staging: 실제 허용 source·MCP 및 모의 검증, 별도 DB/credential. live: 별도 승인 구성, 별도 계좌/호스트 allowlist/데이터 원장 경계. Compose profile만 안전 장치로 의존하지 않고 실행 모드/credential/DB 권한을 검증한다.

## 2. 빌드 및 CI/CD

Python uv lock, Node pnpm lock, runtime major pin, image digest 및 공급망 스캔. multi-stage Dockerfile, non-root user, read-only filesystem 가능한 역할, cap_drop, resource limit, tmpfs, 최소 네트워크, liveness/readiness 구분. GPU 없는 CPU 이미지 기본, Scrapling 수집 의존성 및 필요한 브라우저 전이 의존성은 승인된 scraper-worker image에 격리한다. Playwright는 UI E2E 용도로만 직접 사용한다.

GitHub Actions:
- PR: Ruff format/lint, mypy, pytest/Hypothesis, PostgreSQL Testcontainers integration, TypeScript check, ESLint/Prettier, Vitest, Playwright, OpenAPI generated type drift, markdown link check.
- main/tag: reproducible build, SBOM(예: Syft), Trivy/vulnerability scan, GHCR image push, pinned Actions revisions/least permissions. 공급자 키나 live credential을 PR CI에 제공하지 않음.
- 배포: staging migration 및 smoke, 승인 후 production deploy. DB migration은 단일 실행, backup/rollback 확인. 서비스 health 및 event lag, data gate 확인. LIVE executor는 CI/CD 자동 기동 금지, 별도 운영 승인.

서비스 이미지 rollback은 데이터 schema 호환 범위 내에서만; migration에 expand/contract 전략. DB 복구 시 broker 대사를 완료하기 전 executor 비활성.

## 3. 관측 및 운영

Prometheus metrics + Grafana dashboard + structlog JSON logs, OpenTelemetry SDK trace. exporter는 private, credential/계좌/고카디널리티 ID를 metrics label에 사용하지 않는다. 시작에는 Docker logs rotation과 제한된 로컬 trace/log; Loki/Tempo는 로그량/조사 필요 시 채택.

| 지표 | 경보/행동 |
|---|---|
| provider last_event_age, source delay, stale rate, gap/reconnect | 데이터 품질 gate, reconnect, 알림 |
| collector queue depth, ingest lag, DB batch latency | backpressure, writer 조정, gap 처리 |
| workflow evaluation lag, job lease expiry, reset lag, consumer lag | 장애 감지·안전 차단·재처리 |
| order UNKNOWN, reconciliation mismatch, risk rejection, kill switch | 즉시 신규 주문 차단/운영자 확인 |
| API p95/errors, SSE reconnect, auth denial/rate limit | 부하/보안 조사 |
| DB connections, disk, WAL, backup age, restore test | 저장소 보호/확장 |
| TLS expiry, secret rotation, external MCP status | 만료/권한 확인 |

목표 SLO(실측 전 가설): 100종목 1Hz 샘플·20개 활성 workflow 합성 workload, 내부 event 처리 p95 500ms 이내(외부 공급자 지연 제외), 조회 p95 300ms 이내(캐시/기간 명시), data backlog와 DB disk budget 측정. SLA/거래 성능 보장 아님. 목표 RPO 5분/PITR, RTO 2시간은 WAL archive 및 off-host 복원 시험 통과 후만 운영 목표로 채택. 초기 pg_dump만으로 5분 RPO를 주장하지 않는다.

## 4. 확장 기준

DB/collector/worker의 p95, backlog, disk/retention, 동시 사용자, 비용을 기록하고 병목이 확인될 때 수직 확장 → worker 분리/replica → DB 튜닝/파티션 → 필요 시 Valkey 또는 별도 queue/TSDB/객체 저장소. Kafka/Temporal/K8s/managed cloud는 load test·운영 인력·장애 격리 이점이 비용을 상회할 때 ADR. 고가용성이 필요한 LIVE 단계에는 별도 executor host, DB HA/복제, 백업/복구·failover 대사 설계 검토. 상태 머신/계좌의 단일 제출 권한을 유지하며 이중 실행 금지.

[Docker Compose](https://docs.docker.com/compose/) · [GitHub Actions](https://docs.github.com/actions) · [Prometheus](https://prometheus.io/docs/) · [Grafana](https://grafana.com/docs/) · [OpenTelemetry](https://opentelemetry.io/docs/)
