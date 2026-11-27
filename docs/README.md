# Auto-Axe 문서

> 구현 기준선. 기능·설계·데이터 소스·기술 스택·보안 요구사항을 하나의 일관된 설계로 적용한다. 문서 동결은 운영 구현·공급자 권한·실측·LIVE 승인을 의미하지 않는다. 변경 필요 시 해당 요구사항·기술 명세·수용 테스트를 함께 개정한다.

## 문서 적용 기준

| 영역 | 기준 문서 |
|---|---|
| 기능 및 동작 | [기능 명세](./function/specification.md), 도메인별 상세 기능 명세 |
| 시스템·UI | [시스템 설계](./design/specification.md), [UI 디자인](./design/frontend.md) |
| 무료 데이터·상품 정의 | [수집 카탈로그](./indicator-collection/Free_Data_Collection.md), [시장 소스 정책](./indicator-collection/Market_Source_Policy_20261123.md) |
| 구현 기술·저장·배포 | [기술 스택](./tech-stack/README.md), [공통 기술 계약](./tech-stack/contracts.md) 및 영역별 기술 명세 |
| 보안·실거래 | [전체 보안](./tech-stack/security.md), [MCP 보안](./mcp/security.md), [주문 실행](./tech-stack/trading-integration.md); 제한 정책 우선 |
| 검수 | 각 명세의 수용 기준과 [개발·검증 계획](./tech-stack/testing-roadmap.md) |

공급원·라이브러리 실측일, upstream 버전 및 API 적용일, 예시 timestamp는 근거로 유지한다. 과거 설계 변경 이력은 Git 커밋에서 확인한다. 공식 NHPLUG 원본 자료와 기존 수집 예제는 참조/PoC로 유지하며 운영 계약을 대체하지 않는다.

## 기능 및 설계

- [시스템 설계 명세서](./design/specification.md)
- [프론트엔드 디자인 명세서 (Live3x 레퍼런스)](./design/frontend.md)
- [기능 명세서](./function/specification.md)
- [매수·매도 Workflow 명세서](./function/trading-workflow.md)
- [주식 그룹 및 집계 트리거 명세서](./function/stock-groups.md)
- [금요일 종가매수 분석·예측 시스템 명세서](./function/friday-close-strategy.md)

- [지표 수집 문서 모음](./indicator-collection/README.md)
- [수집기 및 검증용 예제 코드](./examples/realtime_collector.py)

## MCP 연동

- [통합 MCP 명세 인덱스](./mcp/README.md)
- [기능 및 아키텍처](./mcp/specification.md) · [Tools](./mcp/tools.md) · [Resources/Prompts](./mcp/resources-prompts.md) · [보안](./mcp/security.md) · [nhplug-mcp 조회 및 nhplug-sdk 주문 연동](./mcp/nhplug-integration.md)

## 기술 스택

- [기술 스택 및 구현 기준](./tech-stack/README.md)

- [전체 플랫폼 보안 설계](./tech-stack/security.md)

## 개발 실행 계획 및 작업 인계

- [Phase 0~8 개발 실행 계획](./development/PHASE_PLAN.md) — 기존 전역 로드맵의 세부 작업 및 종료 검증 기준
- [현재 작업 맥락 및 사용자 명세](../.ai-context/CONTEXT.md) — 새 세션 시작 시 필독
- [Phase 작업 기록 양식](../.ai-context/PHASE_LOG_TEMPLATE.md) · [최초 계획 기준선](../.ai-context/phases/planning-baseline.md)
- [Phase 1 데이터 수집·저장 구현](./development/PHASE_01_IMPLEMENTATION.md)
- [Phase 2 지표·스크래퍼·대시보드 구현](./development/PHASE_02_IMPLEMENTATION.md)
- [Phase 2 세션 진행 및 인계](../.ai-context/phases/phase-02/2026-11-27-01.md)
- [Phase 2 미완료 보강 세션 및 후속 인계](../.ai-context/phases/phase-02/2026-11-27-02.md)
- [Phase 2 개인·교육·비영리 목적 정정 및 권한 분리](../.ai-context/phases/phase-02/2026-11-27-03.md)
- [개인·교육·비영리 데이터 사용 정책](./indicator-collection/PERSONAL_EDUCATIONAL_USE.md)
- [개발 트러블슈팅 인덱스](./troubleshooting/README.md) — Phase별 재현·조사·원인·해결·검증
