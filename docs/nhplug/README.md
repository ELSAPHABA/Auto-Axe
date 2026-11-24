# NHPLUG 공식 프로젝트 바로가기

Auto-Axe의 NH투자증권 연동에 사용하는 공식 GitHub 저장소입니다.

- **PLUG-OpenAPI 공식 GitHub 조직:** [github.com/PLUG-OpenAPI](https://github.com/PLUG-OpenAPI)

| 프로젝트 | 바로가기 | Auto-Axe에서의 용도 |
|---|---|---|
| **nhplug-sdk** | [PLUG-OpenAPI/nhplug-sdk](https://github.com/PLUG-OpenAPI/nhplug-sdk) | Python SDK `nhplug`를 이용한 실제 매수·매도 주문 실행 및 증권사 API 연동. 주문은 Auto-Axe의 격리된 Trading Executor가 담당 |
| **nhplug-mcp** | [PLUG-OpenAPI/nhplug-mcp](https://github.com/PLUG-OpenAPI/nhplug-mcp) | 별도 독립 MCP를 통한 NHPLUG 시세·잔고·계좌 등 조회. 현재 주문 실행은 지원하지 않음 |

## 관련 내부 문서

- [NHPLUG MCP/SDK 통합 및 주문 경계 명세](../mcp/nhplug-integration.md)
- [통합 MCP 아키텍처](../mcp/specification.md)
- [Workflow 기능 명세](../function/trading-workflow.md)

## 이 디렉터리의 자료

- [llms.txt](./llms.txt)
- [llms-full.txt](./llms-full.txt)
- [NHPLUG 해외주식 종목정보파일](./nhplug%20%ED%95%B4%EC%99%B8%EC%A3%BC%EC%8B%9D%20%EC%A2%85%EB%AA%A9%EC%A0%95%EB%B3%B4%ED%8C%8C%EC%9D%BC.txt)

> 위 링크는 원본 저장소로 이동하는 바로가기이며, 원본 코드의 사본이나 Git 서브모듈이 아닙니다. SDK 및 MCP의 지원 기능·버전은 사용 시 원본 저장소에서 확인하세요.
