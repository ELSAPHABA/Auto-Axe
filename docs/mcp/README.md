# Auto-Axe MCP 명세

> 2026-11-25 · 사용자 승인 아키텍처: 단일 통합 Auto-Axe MCP + 내부 도메인 모듈화, NH투자증권 연동용 외부 nhplug-mcp 분리. 아직 구현·배포되지 않았다.

## 문서 구성

| 문서 | 범위 |
|---|---|
| [specification.md](./specification.md) | 기능·아키텍처·프로토콜·배포 및 개발 단계 |
| [tools.md](./tools.md) | 도메인별 Tool 카탈로그, 입력·출력·실행 규칙 |
| [resources-prompts.md](./resources-prompts.md) | Resource URI 및 Prompt 템플릿 |
| [security.md](./security.md) | 인증·인가·승인·감사·오류 및 보안 검수 |
| [nhplug-integration.md](./nhplug-integration.md) | 공식 nhplug-mcp의 확인된 기능, 조회 연동 및 실주문 한계 |

## 핵심 결정

- Auto-Axe MCP는 플랫폼 기능을 하나의 MCP endpoint로 제공한다. 10개 논리 모듈은 독립 서버가 아니다.
- 프론트엔드/API와 MCP는 공통 Application Service를 호출한다. DB, 브로커 자격증명, 임의 명령 실행을 직접 노출하지 않는다.
- 외부 [nhplug-mcp](https://github.com/PLUG-OpenAPI/nhplug-mcp)는 별도 연결·프로세스로 사용한다. 확인된 버전은 조회 전용으로 주문을 거부한다. 실제 주문 MCP로 사용할 수 없는 상태이므로 LIVE 주문 제출은 차단한다. 공식 SDK 대안은 별도 검토 및 사용자 승인 대상이다.
- 사용자/에이전트의 권한 범위 내에서 플랫폼의 모든 승인된 업무 기능과 리소스에 접근할 수 있도록 점진적으로 구현한다. 모든 에이전트에게 전권을 부여한다는 뜻은 아니다.

[전체 기능](../function/specification.md) · [전체 설계](../design/specification.md) · [Workflow](../function/trading-workflow.md) · [금요일 종가매수](../function/friday-close-strategy.md) · [주식 그룹](../function/stock-groups.md).
