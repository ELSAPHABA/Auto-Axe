# MCP Resources 및 Prompts 명세

## 1. Resources

Resource는 읽기 전용 문맥 제공 인터페이스이며 Tool 실행을 유발하지 않는다. 아래 URI는 Auto-Axe 내부 식별자 예시이며 실제 HTTP 주소가 아니다. {id}/{version}은 URI template 변수로 등록한다. 권한이 있는 Resource만 읽을 수 있고, 캐시도 사용자/계좌/버전 경계를 유지한다. 최신값에는 기준 시각·품질·출처를 포함한다.

| URI | 내용 | 권한 |
|---|---|---|
| autoaxe://docs/specification | 전체 기능 명세 | docs:read |
| autoaxe://docs/design | 전체 시스템 설계 | docs:read |
| autoaxe://docs/mcp | MCP 명세 및 카탈로그 | docs:read |
| autoaxe://indicators/catalog | 지표·단위·소스 정책 | indicator:read |
| autoaxe://market/instruments | 상품 목록 | market:read |
| autoaxe://market/quotes/{instrument_id} | 최신 시세 | market:read |
| autoaxe://stock-groups/{id}/versions/{version} | 그룹 정의 | stock_group:read |
| autoaxe://workflows/{id}/versions/{version} | Workflow 불변 정의 | workflow:read |
| autoaxe://workflows/{id}/status/{run_id} | 실행 상태 | workflow:read |
| autoaxe://workflows/node-types | 노드 정의 | workflow:read |
| autoaxe://predictions/friday-close/latest | 최신 예측 및 모드 | prediction:read |
| autoaxe://predictions/{id} | 버전 고정 예측 | prediction:read |
| autoaxe://backtests/{id}/report | 검증 결과 | backtest:read |
| autoaxe://portfolio/{account_ref}/summary | 허용 계좌 요약 | portfolio:read |
| autoaxe://collectors/{id}/status | 수집 상태 | collector:read |
| autoaxe://system/health | 시스템 상태 | system:read |

리소스 목록/템플릿/읽기는 대상 SDK의 표준 기능 사용. 큰 결과는 제한된 요약 및 페이지 Tool을 제공한다. 임의 파일경로/URI fetch, 내부 네트워크 URL, 비밀 파일, 전체 DB dump 금지. Resources 미지원 Host도 주요 내용을 읽을 수 있도록 해당 조회 Tool을 제공한다(예: system_get_capabilities 및 문서 조회용 system_get_document(doc_id) / docs:read; allowlist만). 지원 버전에서만 변경 알림/구독을 사용한다.

## 2. Prompts

| Prompt | 인자 | 템플릿 목적 |
|---|---|---|
| analyze_market | market, as_of | 시장·거시·수급 분석 |
| analyze_stock | instrument_id, period | 종목·기술·재무 요약 |
| analyze_stock_group | group_id, version, period | 시장폭·상대 강도 분석 |
| create_trading_workflow | strategy_description, mode | 노드 카탈로그 기반 초안 작성·검증 |
| review_workflow | workflow_id, version | 논리·참조·위험 검토 |
| optimize_workflow | workflow_id, version, evaluation_window | 백테스트 비교·변경 초안 제안 |
| analyze_friday_close | instrument_id, mode, as_of | 예측·유사 사례·불확실성 분석 |
| review_portfolio_risk | account_ref | 보유·노출·위험 검토 |
| diagnose_system | service, period | 필터 로그·품질·원인 분석 |

Prompt는 메시지 템플릿이며 자동 실행 권한이나 사용자 승인으로 간주하지 않는다. 예를 들어 create_trading_workflow는 실제 주문이 아니라 초안 생성 및 검증을 권장한다. 뉴스·문서·로그·Tool 결과의 텍스트는 비신뢰 데이터로 취급하고 지시로 실행하지 않는다. 모든 호출은 별도 인증·인가·승인 정책을 적용한다.

## 3. 수용 테스트

- URI 템플릿 변수·버전·소유권 검증, 다른 사용자의 ID/계좌에 접근 금지.
- 문서/시세/조건 상태가 동일 Application Service 및 버전과 일치.
- Resources/Prompts를 미지원하는 Host는 기본 Tools로 사용 가능.
- 민감 정보 마스킹, 캐시 교차 사용자 유출 방지, 불필요한 대량 응답 제한.
- 악성 문서/뉴스의 명령문이 승인·주문·시스템 변경을 유발하지 않음.

[Tool 목록](./tools.md) · [보안](./security.md).
