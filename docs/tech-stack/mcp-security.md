# MCP·인증·보안 기술 스택

[Auto-Axe 전체 플랫폼 보안 설계](./security.md)와 함께 적용한다. MCP의 도메인별 scope·리소스 정책, 외부 기본 차단, 직접 LIVE 주문 제출 금지 및 기존 [MCP 보안 요구사항](../mcp/security.md)은 그대로 유지한다. 웹/DB/스크래퍼/공급망/사고 대응 요구는 상위 문서에서 관리한다.

## 1. MCP

공식 Python MCP SDK를 사용해 단일 Auto-Axe MCP 서버에 10개 도메인(market, indicator, stock_group, workflow, prediction, backtest, portfolio, collector, system, trading intent)을 등록한다. Tools/Resources/Prompts는 [기존 카탈로그](../mcp/tools.md), [Resources/Prompts](../mcp/resources-prompts.md)를 구현한다. FastAPI API와 Pydantic DTO, Application Service, authorization/Job/error contract 공유. SDK와 protocol revision은 실제 지원 Host/Inspector 호환성을 확인하고 lock한다. 직접 JSON-RPC 구현을 피한다. 실험적 MCP Tasks/구독·세션 기능을 무조건 지원한다고 가정하지 않는다.

| 전송 | 구현 |
|---|---|
| 로컬 stdio | 같은 코드베이스의 별도 entrypoint, OS process identity, stdout protocol only, 로그 stderr |
| 로컬 HTTP | 인증된 loopback, Host/Origin 검증 |
| 외부 | Caddy HTTPS → private MCP ASGI process, Streamable HTTP /mcp |
| nhplug-mcp | 별도 stdio 연결, 조회 allowlist 및 제한 timeout; 외부 비공개 |

원격은 기본 off. admin이 활성화한 endpoint + OAuth discovery 및 resource metadata; GET/POST/DELETE/SSE는 협상 revision에 따른다. proxy streaming buffering/timeout 및 connection close/reconnect를 실제 테스트. 요청 단위 token·scope 검증, session ID 인증 대체 금지. 장기 Job은 durable job ID로 조회/취소, 연결 종료가 자동 취소를 의미하지 않음.

## 2. 인증 기술

웹 세션은 [공통 기술 계약](./contracts.md) §6의 PostgreSQL BFF 세션, MCP OAuth 토큰과 stdio identity는 별개다. 공통 DTO/Graph schema/event 계약은 동일하지만 MCP JSON-RPC 형식은 유지한다.

Keycloak을 자체 호스팅 OIDC/OAuth IdP 초기 선택. Caddy reverse proxy TLS termination + 내부 private network. MCP는 OAuth 2.1 요구를 적용하는 Resource Server로 구성하고 Python SDK token verifier와 검증된 JWT/JWKS library(예: PyJWT[crypto]) 또는 introspection을 사용. Keycloak 지원만으로 MCP 완전 호환을 보장하지 않으며 protected resource metadata, authorization server discovery, PKCE S256, resource/audience, client registration/redirect, revocation, Host별 OAuth 플로우 검증 후 공개한다. DCR 필요 Host는 관리자 승인된 최소 scope 등록 정책 및 호환성 테스트 후 허용. 지원 안 되는 Host는 우회 없이 비활성.

Web UI: same-origin backend session/BFF, Authorization Code + PKCE, HttpOnly Secure SameSite cookie, CSRF 보호(쓰기), logout/revocation, browser에는 브로커 비밀·장기 refresh token 전달 금지. token/session storage 및 rotation은 서버측, MCP 클라이언트는 별도 OAuth client 및 audience/scope. stdio는 제한된 로컬 서비스 identity/OS 권한으로 공통 인가를 거치며 자동 관리자 아님.

## 3. 권한·안전

MCP 연결 및 승인된 자동 Workflow의 실행 수명은 분리한다. 네트워크 연결 종료·개별 MCP client grant 폐기·원격 MCP 기능 OFF는 해당 연결의 신규 요청과 스트림을 차단하되, 독립적으로 유효한 사람 사전 승인과 계좌 거래 권한을 가진 Workflow는 계속 실행할 수 있다. 클라이언트 권한에만 의존한 미승인 단발 주문·대기 작업은 재인가 실패 시 진행하지 않는다. Workflow 승인 철회는 해당 실행의 신규 주문을 차단하고 미제출 의도·예약을 정리하며, 계좌 거래 권한 철회는 해당 계좌 전체 신규 주문을 차단한다. 전역/계좌 Kill Switch는 지정 범위에서 우선한다. 공통 인가·승인·위험 정책의 상태를 확인할 수 없는 장애에서는 신규 주문을 fail closed 처리한다. 원격 MCP만 OFF인 상태와 공통 인가 장애를 구분한다. 이미 브로커로 제출된 주문은 자동 청산하거나 취소 성공으로 간주하지 않고 대사한다.

- 서버에서 issuer/audience/exp/nbf/signature/allowed algorithm/client/scope/principal 검증. introspection/JWKS 및 revocation 정책, 짧은 access token 수명, 위험 변경 즉시 grant 확인. 토큰 전달(pass-through) 금지.
- RBAC + resource-level policy (owner/account/mode/data permission/approved version), scope 예: market:read, workflow:draft:write, workflow:execute:paper, trading:intent:write. 기본 deny, 고위험 action은 추가 승인/MFA/expected_version/idempotency.
- Tool annotation/모델 프롬프트/Host 승인 UI는 서버 인가 대체 불가. 미구현 tool은 capabilities에 노출하지 않는다. 원격·로컬 모두 직접 주문 제출 도구 없음.
- 사용자 입력은 Pydantic schema, 길이/기간/개수 제한. SSRF/DNS rebinding, arbitrary SQL/shell/path/URL 금지, 외부 데이터·뉴스 prompt injection 방어. 도메인 로직이 반환하는 safe DTO만 노출.
- 외부 client registry: 승인/만료/폐기, 허용 scope/계좌, last_used. 관리자 kill/disable이 신규 및 기존 연결의 보호 요청을 차단하도록 검사하고 세션 종료·캐시 무효화.
- rate limit은 애플리케이션/프록시의 검증된 기능으로 IP·client·principal·tool별 설정(기본 Caddy에 고급 WAF 기능이 있다고 가정하지 않음). Job quotas, body limits, timeouts, audit redaction.

## 4. 네트워크와 비밀

Caddy 공개 443(인증서 발급 필요 시 80 redirect/challenge만), 외부에서 DB/Valkey/collector/worker/Executor/nhplug/관리 포트 차단. Keycloak은 필요한 로그인/discovery/token 경로만 공개하고 admin console은 사설 관리 경계. Origin/Host/forwarded header trust proxy 검증, 최소 CORS, TLS 1.2+ (1.3 권장), 내부 경계에 따라 TLS/mTLS. reverse proxy 우회 접근 방지. VPN/IP allowlist 선택, 인증 대체 불가. Compose network 분리 및 egress 제한은 host firewall/환경의 실제 정책으로 검증한다.

secrets는 gitignored .env.example과 실제 secret 파일 분리, 최소 파일 권한, 운영 secret store 후보, rotation/backup; Docker Compose secrets 자체가 암호화 저장소라는 주장 금지. executor의 broker secret은 다른 컨테이너에 mount하지 않음. 로그/trace/metrics에서 token·계좌·개인정보 마스킹. 별도 audit ledger, 보존·권한·삭제 정책.

## 5. 테스트

MCP Inspector 및 실제 로컬/외부 Host에서 initialize/tool/resource/prompt, schema, pagination, long job, cancel/reconnect, 오류 검증. 외부 무인증/만료/철회/잘못된 issuer·audience·scope, 악성 Host/Origin, SSRF, 타 계좌, 과도한 요청, read-only write, 직접 주문, 원격 off, OAuth discovery/PKCE/redirect 검증. 실패 시 원격 기본 차단.

[공식 MCP SDK](https://github.com/modelcontextprotocol/python-sdk) · [MCP authorization](https://modelcontextprotocol.io/specification) · [Keycloak](https://www.keycloak.org/documentation) · [Caddy](https://caddyserver.com/docs/) · [기존 보안 명세](../mcp/security.md)
