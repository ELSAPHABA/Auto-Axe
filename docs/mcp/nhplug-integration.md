# NH투자증권 nhplug-mcp 독립 연동 명세

> 2026-11-25 GitHub 원본 확인. 사용자 지정 외부 MCP는 [PLUG-OpenAPI/nhplug-mcp](https://github.com/PLUG-OpenAPI/nhplug-mcp)이다. 확인한 main commit: c61e38ca37de801911ac6c29a685077802513d44, package/server version 0.1.0. 현재 **조회 전용**이라 실제 주문 실행을 지원하지 않는다. 이는 구현 차단 사항이며 주문 가능하다고 문서화하지 않는다.

## 1. 확인된 upstream 기능

| 항목 | 실제 확인 |
|---|---|
| 저장소 | NH투자증권 Open API 로컬 MCP sample, MIT |
| 실행 | TypeScript, Node.js >=18, stdio (src/index.ts) |
| 자산군 | 국내주식 krstock, 해외주식 gbstock |
| 목록 규모 | README의 REST 53개·실시간 27채널 표기; MCP의 실제 등록 도구는 아래 6개이며 실시간 WS 구독 Tool 존재를 가정하지 않음 |
| 인증 | 앱키/시크릿 기반 토큰 처리, REST Input_0 봉투 자동 처리 |
| 주문 | 매수·매도·정정·취소 거부, NHPLUG_ENABLE_TRADING 제거 |
| 검증 | README·src/index.ts·src/tools.ts·src/spec.ts·package.json 확인; 실계좌 및 실제 호출 테스트는 미수행 |

| upstream Tool | 역할 |
|---|---|
| list_apis | 자산군/category/keyword 기반 조회 가능한 API 목록, operationId |
| describe_api | operationId 입력 스키마, 주문 API의 형식 설명 가능 |
| call_api | operationId와 input으로 허용 조회 수행, 주문 API 거부 |
| get_stock_price | 국내주식 현재가 |
| get_stock_balance | 국내주식 잔고 |
| list_accounts | 계좌 목록 |

src/tools.ts에서 isTrading인 API를 목록에서 제외하고 call_api에서 거부한다. src/spec.ts에서 주문 경로/태그로 판정한다. 실제 주문을 실행하는 MCP 도구는 없다. README의 주문 테스트 스크립트는 MCP 외부의 사람이 실행하는 테스트이며 Auto-Axe가 우회 호출하지 않는다. operationId와 Python SDK URI 경로를 혼용하지 않는다.

근거: [고정 README](https://github.com/PLUG-OpenAPI/nhplug-mcp/blob/c61e38ca37de801911ac6c29a685077802513d44/README.md) · [등록 도구](https://github.com/PLUG-OpenAPI/nhplug-mcp/blob/c61e38ca37de801911ac6c29a685077802513d44/src/tools.ts) · [주문 분류](https://github.com/PLUG-OpenAPI/nhplug-mcp/blob/c61e38ca37de801911ac6c29a685077802513d44/src/spec.ts) · [진입점](https://github.com/PLUG-OpenAPI/nhplug-mcp/blob/c61e38ca37de801911ac6c29a685077802513d44/src/index.ts).

## 2. 연결 구조

```mermaid
flowchart LR
  H[AI Host] --> A[Auto-Axe 통합 MCP]
  H --> N[독립 nhplug-mcp STDIO]
  N --> R[NHPLUG 조회 API]
  A --> I[Auto-Axe 주문 의도 / 승인 요청]
  I --> G[리스크 검사]
  G -. LIVE 제출 차단 .-> X[별도 실행 서비스 미확정]
  A --> P[Portfolio read-only adapter]
  P -. 권한 검증 후 별도 MCP Client .-> N2[격리된 nhplug-mcp 프로세스]
  N2 --> R
```

Host는 필요하면 두 MCP 연결을 개별 등록한다. 플랫폼 내부 계좌 조회가 필요하면 Auto-Axe의 격리된 read-only integration worker가 독립 MCP Client로 연결한다. Host 직접 연결과 플랫폼 worker는 별개 프로세스·계정이며 Auto-Axe 서버가 Host에 연결된 MCP를 자동 제어할 수 있다고 가정하지 않는다. 조회 결과는 allowlist 및 계좌 소유권 검사, 마스킹·단위 정규화 후 Application Service로 전달한다. 외부 raw call_api를 일반 Auto-Axe Tool로 무제한 전달하지 않는다. NH 자격증명은 해당 격리 프로세스에만 주입한다.

## 3. 실행 구성

공식 README는 로컬 npx 또는 clone/build 후 node dist/index.js를 안내한다. Auto-Axe 운영은 검증한 commit과 lockfile을 고정하고 재현 가능한 빌드를 사용한다. 부팅마다 최신 main 실행 금지. 실제 앱키를 Git/대화/설정 예제에 넣지 않는다. 로컬 Host의 환경 변수 저장 방식과 운영 Secret Manager는 구분한다.

| 환경 변수 | 의미 |
|---|---|
| NHPLUG_APP_KEY / NHPLUG_APP_SECRET | 격리 프로세스에 전달할 발급 키 |
| NHPLUG_BASE_URL | 나무 운영 https://api.nhplug.com:8443 / 모의 https://moapi.nhplug.com:8443 |
| NHPLUG_AUTH_URL | 운영 인증 https://api.nhplug.com:8443 (모의 호출도 운영 인증) |
| NHPLUG_DEFAULT_ACCOUNT | 필요 시 제한된 계좌 설정; 기본적으로 명시적 계좌 매핑 |
| NHPLUG_ALLOW_HOSTS | 추가 허용 호스트 설정; 운영 기본 미사용 |

N2 사용 시 BASE/AUTH를 N2 공식 도메인으로 함께 맞춘다. 허용 호스트, TLS, 환경·계좌 분리 및 네트워크 정책 적용. 모의/운영 대상 설정을 명시하고 기본 모의 조회부터 검증한다. stdout은 MCP 프로토콜 전용, stderr 로그는 민감 정보 마스킹. 실제 지원 Host·transport는 호환성 시험으로 결정한다.

## 4. 조회 어댑터 및 상태 계약

- list_apis → describe_api → 허용된 operationId call_api. 국내 현재가/잔고 단축 도구 및 계좌 목록 사용 가능. 해외 종목/계좌는 번들 스키마와 실제 응답 검증을 거쳐 매핑한다. 메타 도구에서 시세·계좌 조회만 allowlist하고 미확인 operationId는 거부.
- 계좌 식별자는 내부 account_ref로 매핑하고 응답은 소유권과 최소 공개 범위를 검증한다. NHPLUG가 제공하지 않는 포트폴리오 손익/위험 계산은 별도 Application Service로 수행.
- HTTP/JSON-RPC 성공만으로 업무 성공을 단정하지 않는다. upstream은 rsp_cd/rsp_msg 업무 판정을 그대로 전달하므로 API별 공식 규격에 따라 해석한다. 호출 제한·인증 실패·데이터 없음 및 조회 기준시각을 보존한다.
- 오류 시 BROKER_UNAVAILABLE/STALE_DATA/UNKNOWN 등으로 처리한다. 조회 실패를 주문 성공·잔고 0으로 변환하지 않는다. upstream 변경 시 schema drift, allowlist, 주문 차단, 모의 환경 테스트를 다시 수행한다.

## 5. 실제 주문 실행 한계 및 후속 결정

사용자가 선택한 nhplug-mcp는 유지하되, 현재 버전으로 실제 매수/매도/정정/취소를 수행할 수 없다. 따라서 Auto-Axe는 주문 의도, preview, 검증, 승인 요청 및 모의 엔진까지만 정의하며 LIVE 제출은 NOT_IMPLEMENTED/BROKER_UNAVAILABLE로 차단한다. upstream의 안전 제한을 제거하거나 우회하는 fork, 임의 REST proxy, 주문 테스트 스크립트 호출을 구현하지 않는다.

공식 README가 안내하는 [nhplug-sdk](https://github.com/PLUG-OpenAPI/nhplug-sdk) 기반 독립 주문 실행 서비스는 **대안 후보이며 아직 채택 승인되지 않았다.** 향후 사용자 승인 후 공식 API의 거래 지원·모의/운영·계좌·시장·주문 유형·호출 제한·이용권을 검증하여 별도 설계를 확정한다. 승인된 경우에도 deterministic 주문 실행 서비스, 전용 자격증명, 위험 검사, 사람/사전 승인 정책, Kill Switch, 주문 의도 고유 키, 접수·체결 대사 및 미확인 응답 재전송 금지를 적용한다. 통합 Auto-Axe MCP에 실제 주문 제출 도구를 추가하지 않는다.

## 6. 검증 단계

1. 고정 버전 build 및 stdio handshake/tools/list, 도구 스키마 저장.
2. 허용 조회 및 mock 환경에서 계좌 매핑·응답/단위·인증·호출 제한 검증.
3. 주문 기능 미노출·차단은 무자격증명 mock/stub 또는 소스/계약 테스트로 검증; 실제 주문 호출 시험 금지.
4. 외부 독립 연결과 Auto-Axe read-only adapter의 격리, 타 계좌 접근 차단, 키 및 로그 마스킹.
5. 조회 장애·schema 변경·재접속 검증. LIVE 제출은 별도 지원 및 승인 전 차단.

공식 명세: [NHPLUG](https://www.nhplug.com/llms.txt), [NHPLUG SDK](https://github.com/PLUG-OpenAPI/nhplug-sdk). [보안](./security.md) · [Tools](./tools.md) · [Workflow](../function/trading-workflow.md).
