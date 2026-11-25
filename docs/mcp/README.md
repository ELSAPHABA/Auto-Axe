# Auto-Axe MCP 명세

> 단일 통합 Auto-Axe MCP와 내부 도메인 모듈, 별도 NH 조회용 nhplug-mcp 및 독립 SDK Executor를 구현한다. 운영 구현·배포는 아직 없다.

## 문서 구성

| 문서 | 범위 |
|---|---|
| [specification.md](./specification.md) | 기능·아키텍처·프로토콜·배포 및 개발 단계 |
| [tools.md](./tools.md) | 도메인별 Tool 카탈로그, 입력·출력·실행 규칙 |
| [resources-prompts.md](./resources-prompts.md) | Resource URI 및 Prompt 템플릿 |
| [security.md](./security.md) | 인증·인가·승인·감사·오류 및 보안 검수 |
| [nhplug-integration.md](./nhplug-integration.md) | 공식 nhplug-mcp 조회 연동 및 nhplug-sdk 실주문 실행 명세 |

## 핵심 결정

- Auto-Axe MCP는 플랫폼 기능을 하나의 통합 MCP 서버로 제공한다. 10개 논리 모듈은 독립 서버가 아니다. 로컬 stdio/loopback HTTP와 외부 HTTPS Streamable HTTP 접속을 모두 지원한다. 외부 접속은 관리자가 명시적으로 활성화하고 OAuth 인증, TLS, 클라이언트별 권한/철회, 네트워크 격리 및 감사 정책을 적용한다. 독립 nhplug-mcp와 주문 실행 계층은 직접 외부 공개하지 않는다.
- 프론트엔드/API와 MCP는 공통 Application Service를 호출한다. DB, 브로커 자격증명, 임의 명령 실행을 직접 노출하지 않는다.
- 외부 [nhplug-mcp](https://github.com/PLUG-OpenAPI/nhplug-mcp)는 별도 연결·프로세스로 사용한다. 확인된 버전은 조회 전용으로 주문을 거부한다. 실제 주문은 사용자 승인에 따라 공식 [nhplug-sdk](https://github.com/PLUG-OpenAPI/nhplug-sdk) 기반 독립 Trading Executor가 담당한다. 구현·모의 검증 및 별도 실거래 활성화 승인 전 LIVE 제출은 비활성이다.
- 사용자/에이전트의 권한 범위 내에서 플랫폼의 모든 승인된 업무 기능과 리소스에 접근할 수 있도록 점진적으로 구현한다. 모든 에이전트에게 전권을 부여한다는 뜻은 아니다.

[전체 기능](../function/specification.md) · [전체 설계](../design/specification.md) · [Workflow](../function/trading-workflow.md) · [금요일 종가매수](../function/friday-close-strategy.md) · [주식 그룹](../function/stock-groups.md).
