# Auto-Axe
NH나무 OpenAPI 알고리즘 &amp; 패턴 매매 퀀트 시스템

## 문서

- [지표 수집 문서 모음](docs/indicator-collection/README.md)
- [전체 문서 인덱스](docs/README.md)
- [기술 스택 및 아키텍처 설계안](docs/tech-stack/README.md)
- [Phase별 개발 실행 계획](docs/development/PHASE_PLAN.md)
- [현재 작업 상태 및 새 세션 인계](.ai-context/CONTEXT.md)
- [Phase 0 개발 환경 및 검증](docs/development/PHASE_00_ENVIRONMENT.md)
- [Phase 1 데이터 수집·저장 구현](docs/development/PHASE_01_IMPLEMENTATION.md)
- [Phase 2 지표·격리 스크래퍼·대시보드 구현](docs/development/PHASE_02_IMPLEMENTATION.md)
- [개발 트러블슈팅](docs/troubleshooting/README.md)

## 개발 환경 (Phase 2)

현재는 시장 데이터 카탈로그·영속 저장·수집 작업·지표 계산·격리 스크래퍼 파서·대시보드 계약을 합성 fixture로 검증하는 개발 환경입니다. 실제 공급자의 사용·저장·재배포 권한 및 DOM은 검증되지 않았으며 해당 웹사이트 수집, 주문 및 외부 MCP는 비활성화되어 있습니다. 격리된 scraper worker의 샌드박스 테스트는 `docker compose --env-file .env.phase0 -f infra/compose/dev.yaml --profile scraper-fixture run --rm --build scraper-fixture`로 실행합니다.
Python 3.12, uv 0.13.10, Node.js 24.21.0, pnpm 12.9.1, Docker Compose를 사용합니다.

```sh
uv sync --project apps/backend --locked --group collection-smoke
uv sync --project apps/executor --locked
pnpm install --frozen-lockfile
uv run --project apps/backend --locked python -m autoaxe.adapters.schema --check
pnpm contracts:types
uv run --project apps/backend --locked pytest apps/backend/tests
pnpm test
pnpm build
```

로컬 PostgreSQL/API/Web 실행 및 종료는 [개발 Compose 가이드](infra/compose/README.md)를 참고하세요. 운영 배포 또는 LIVE 활성화 지시가 아닙니다.
