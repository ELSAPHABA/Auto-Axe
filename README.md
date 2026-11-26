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
- [개발 트러블슈팅](docs/troubleshooting/README.md)

## 개발 환경 (Phase 1)

현재는 시장 데이터 카탈로그·영속 저장·수집 작업 및 이벤트 기반을 합성 fixture로 검증한 개발 환경이며 실제 공급자 수집·주문·외부 MCP는 비활성화되어 있습니다.
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
