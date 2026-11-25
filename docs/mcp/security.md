# MCP 인증·인가·승인 및 보안 명세

[전체 플랫폼 보안](../tech-stack/security.md)과 [MCP 기술 명세](../tech-stack/mcp-security.md)의 Caddy/Keycloak, 네트워크·인증 및 출시 게이트를 적용한다. 이 문서는 MCP 도메인 권한과 동작 제약을 정의한다.

## 1. 신뢰 경계

Auto-Axe MCP는 플랫폼의 사용자 권한 범위 내 업무 접근 인터페이스다. AI Host의 모델 판단, 도구 승인 UI, Tool annotations 및 프롬프트는 서버 인가를 대체하지 않는다. 독립 nhplug-mcp는 별도 자격증명·프로세스·네트워크 경계에서 조회만 수행한다. 실주문 실행 서비스는 공식 nhplug-sdk 기반 독립 Trading Executor로 확정하며, 구현·모의 검증 및 실거래 활성화 승인 전 비활성이다.

## 2. 인증

- 원격 endpoint는 TLS 및 OAuth 2.1 기반 Resource Server. 인증 서버/OIDC 제품은 구현 단계에서 확정한다. 공식 MCP authorization의 discovery, 보호 리소스 metadata, WWW-Authenticate 등은 선택한 protocol revision/SDK에 맞춘다.
- 모든 요청의 issuer, audience/resource, 서명 또는 introspection, 만료, scope, client 및 사용자 신원을 확인한다. MCP 연결/세션 ID를 인증으로 사용하지 않는다. 토큰을 타 서버에 그대로 전달하지 않는다. stdio 로컬 개발은 OS 프로세스 실행 경계와 별도 로컬 권한 정책.
- 서버가 부여한 actor_id, user_id, tenant/owner_ref, account_ref를 이용하며 요청 본문이 주장하는 사용자 ID를 신뢰하지 않는다. 서비스 계정과 사용자 위임을 구분한다.
- Origin 검증 및 DNS rebinding/SSRF 방어, 허용 Host·네트워크·요청 크기 제한. NH API 비밀키·토큰·계좌 정보는 전용 비밀 저장소 및 마스킹; MCP payload, 로그, Prompt, Git, 브라우저에 노출하지 않는다.

### 2.1 외부 접속 네트워크 및 전송 보안

외부 원격 MCP 접속을 정식 지원하되 안전한 설정이 완료되기 전에는 기본 차단한다. 익명/무인증 인터넷 공개는 금지한다.

- 배포 경계: Internet/외부 Host → HTTPS Reverse Proxy 또는 API Gateway → 사설 네트워크의 통합 MCP → Application Service. 외부에는 MCP 경로와 인증에 필요한 제한된 discovery 경로만 노출하고 DB·큐·Executor·내부 관리 API·nhplug-mcp는 외부 접근을 차단한다. 방화벽의 기본 inbound deny, 허용 포트 및 서비스 간 최소 권한을 적용한다.
- TLS 1.2 이상(1.3 권장), 유효한 서버 인증서, 자동 갱신 및 만료 경보. 원격 평문 HTTP 요청은 토큰/본문 처리 전에 거절한다. 내부 전송도 신뢰 경계에 따라 TLS/mTLS 적용. 프록시를 거치지 않는 원본 포트 직접 접근은 차단한다.
- 요청 Host 및 제공된 Origin을 검증한다. CORS는 필요한 브라우저 origin만 허용하며 인증 수단으로 사용하지 않는다. DNS rebinding, SSRF, 요청 위조 및 헤더 변조 방어. 전달 헤더는 신뢰 프록시에서만 수용하고 외부 제공 X-Forwarded-* 값을 신뢰하지 않는다.
- 선택적으로 VPN/사설 네트워크, IP allowlist, WAF/DDoS 방어를 적용한다. IP만으로 인증하지 않는다. 클라우드 AI Host의 가변 출발지 주소 및 OAuth 호환성을 검증하여 실제 사용 가능한 정책을 설정한다.
- 로컬 stdio는 OS 사용자·프로세스 권한과 제한된 서비스 신원을 사용하고, 로컬 HTTP는 loopback에 바인딩하며 HTTP 인증을 적용한다. 로컬 모드가 원격 인증을 우회하는 경로가 되지 않도록 한다.

### 2.2 외부 클라이언트 인증 및 권한 관리

- 원격 MCP는 OAuth 2.1 기반 Resource Server로 운영한다. 별도 Authorization Server/IdP에서 사용자 로그인, 동의 및 토큰 발급을 담당한다. 대상 Host/SDK 및 protocol revision에 맞춘 protected resource metadata, authorization server discovery, Authorization Code + PKCE(S256) 및 redirect URI 검증을 적용한다. 서비스 계정 방식은 별도 승인된 Host가 지원할 때만 제한적으로 제공한다.
- 외부 클라이언트 등록 및 승인 정책을 구성한다. 클라이언트 ID, 이름, 소유자, 부여 scope, 허용 리소스/계좌, 등록/만료/폐기 시각과 마지막 사용 시각을 기록한다. 미승인 클라이언트의 권한 획득은 금지한다. 동적 등록을 지원하더라도 자동으로 고권한을 부여하지 않는다.
- 신규 외부 연결은 최소 조회 권한부터 시작한다. Workflow 초안 수정, 배포 요청, 수집기 관리, 계좌 조회, 주문 의도 등은 각각 명시적 scope 및 사용자 권한이 있어야 한다. 고위험 변경은 기존 승인 정책과 필요 시 재인증/MFA를 요구한다. 실제 주문 직접 제출 도구는 원격에도 제공하지 않는다.
- 짧은 수명의 access token, 안전한 refresh token 저장/회전 및 폐기 정책을 적용한다. 토큰은 Authorization 헤더로만 전달하고 URL/쿼리/로그에 기록하지 않는다. 인증 세션 또는 MCP 세션 ID만으로 권한을 인정하지 않는다. 상태형 MCP 세션을 사용할 때는 인증된 사용자·클라이언트에 바인딩하고 타인의 세션 ID 재사용을 차단한다.
- 관리자는 클라이언트별 접속 차단/권한 변경/토큰 철회 및 전체 외부 접속 비활성화를 수행할 수 있어야 한다. 철회된 연결은 다음 요청 및 활성 스트림에서 정책을 반영하며, 즉시 철회가 필요한 경우 introspection/denylist 등으로 만료까지의 허용을 방지한다. 이 기능은 기존 Workflow 중단·주문 취소와 별개이며 실행 중 작업의 처리 정책은 명시한다.

### 2.3 외부 운영 보안 및 장애 대응

- 사용자·클라이언트·IP·Tool 단위 호출 제한, 동시 연결/스트림·Job 한도, 요청 크기/타임아웃 및 재시도 제한. 인증 실패 폭증, 비정상 권한 요청, 대량 조회·과도한 Job, 승인 거절 등을 탐지하고 운영 알림 및 차단 정책을 적용한다.
- Streamable HTTP의 GET/POST/DELETE 및 SSE 사용 여부는 협상한 명세에 맞춰 지원한다. 모든 보호 요청에 인증·인가를 적용하고, 인증 전 discovery만 최소 공개한다. 스트리밍 프록시의 buffering/timeout 및 재접속 처리를 검증한다. 연결 해제는 주문이나 Job의 자동 취소를 의미하지 않는다.
- 외부 접속 감사 로그에 접속 유형(local/remote), 검증된 client_id/actor, 접속 시각, 요청 ID, 신뢰 경계에서 확인한 접속 IP(보존 및 마스킹 정책 적용), 권한/승인 결과, 토큰 식별자의 비민감 참조 및 호출 결과를 기록한다. 토큰 원문·NH 자격증명·불필요한 계좌 자료는 기록하지 않는다.
- 외부 접근 설정 변경, 클라이언트 권한 부여/철회, 보안 정책 변경은 관리자만 수행하며 감사한다. 인증 서비스 장애 시 fail closed. 인증서 만료, 정책 설정 오류 및 비정상 접근 발생 시 외부 접속만 안전하게 차단할 수 있도록 한다.
- 배포 전 실제 외부 네트워크의 MCP Client로 정상 인증 및 scope 허용 호출을 확인한다. 무인증, 만료/철회/다른 audience 토큰, 잘못된 Origin/Host, 직접 내부 포트 접근, 타 계정/세션 조회, 과도한 호출, 스트림 재접속, 원격 비활성화, 주문 직접 실행 거부를 검증한다.

## 3. 권한 프로파일

| 프로파일 | 허용 기능 예시 |
|---|---|
| Viewer | 허용 시장·지표·Workflow·시스템 조회 |
| Analyst | Viewer + 통계, 모의 백테스트, 모델 검증 |
| Strategist | Analyst + 그룹/Workflow 초안 생성·수정·검증 |
| Operator | 승인된 모의 실행·중단, 제한 수집기 관리 |
| Trading Executor | 일반 MCP의 역할이 아님; 향후 격리된 서비스 계정 및 별도 승인 정책 |

권한은 역할의 단순 상속으로 고정하지 않고 최소 scope로 구성. portfolio:read는 별도 계좌 권한을 필요로 하며 Viewer라고 자동 부여하지 않는다. 세부 scope는 [tools.md](./tools.md). 쓰기/삭제/운영/승인 요청은 독립 scope. 사용자 본인의 권한과 client grant의 교집합, 리소스 소유권, 계좌·실행 모드·승인·데이터 권리 검사. 매 호출마다 검사한다. 권한 없는 도구 목록 필터링은 협상한 프로토콜에서 허용되는 경우만 사용하며 실행 권한 검사를 생략하지 않는다.

## 4. 변경 및 주문 안전

- 초안 저장/수정은 불변 실행 버전을 바꾸지 않는다. 배포와 모의/실행 시작은 별도 권한. destructive action은 대상·영향·현재 버전을 확인하고 명시적 사용자 승인 정책 적용. 참조 중 삭제·순환 참조는 UI/API/MCP 모두 금지.
- 승인 요청에는 actor, action, canonical payload hash, resource/version, account/mode, expires_at을 묶는다. 승인자는 별도 신뢰 UI/권한에서 확인하며 AI가 자신의 요청을 승인하거나 payload 변경 후 재사용할 수 없다. 만료·철회·재사용을 차단한다.
- 주문 준비는 계좌·상품·방향·수량·가격·비용·위험·데이터 신선도·거래 세션·중단 상태를 검증하되 현재 LIVE 제출 도구 없음. 주문 의도/승인 요청은 접수·체결이 아니다. NH 조회 전용 MCP의 주문 차단을 변경하거나 우회하지 않는다. SDK 전용 자격증명은 격리 실행 서비스에만 부여하며 일반 MCP로 전달하지 않는다. 모의/운영 계좌 및 호출 호스트 일치 검증, 자동 운영 fallback 금지를 적용한다.
- 확정된 nhplug-sdk 기반 격리 실행 계층에서만 사용자 승인 정책, 위험 한도, Kill Switch, 중복 방지, 주문 대사 적용. 승인된 자동 Workflow의 사전 실행 한도와 단발 AI 요청은 구분한다. 응답 유실 후 브로커 대사 전 재전송 금지. 비상 중단은 신규 주문 차단이며 자동 청산과 별개다.
- 수집기 운영은 허용 주기/소스 및 무료 데이터 정책 유지. 임의 URL·SQL·shell·코드·비밀 조회 기능 금지. Prompt Injection을 포함한 외부 콘텐츠는 데이터로 취급하고 서버에서 권한/승인 검사.

## 5. 감사·가용성

audit_event: event_id, request_id, actor_ref, client_id, tool/resource, target_ref, sanitized_input 또는 hash, permission_decision, approval_ref, mode, version, timestamp_utc, result_status, reason, job/run/intent_ref. 민감 payload는 최소 보관·마스킹, 원본 비밀은 기록 금지. 감사 로그 변경 제한, 보존/삭제 기간·조회 권한 및 장애 알림은 운영 정책으로 확정한다.

사용자/Tool/서비스별 quota, concurrency, timeout, pagination, 응답 크기 제한, circuit breaker. 429/backoff 및 재시도 가능성 표시. 읽기 재시도와 쓰기 idempotency 분리. 서비스 장애 시 stale/UNKNOWN 및 이유를 반환하며 성공으로 위장하지 않는다. 데이터 이용권이 허용하는 범위에만 저장/제공한다.

## 6. 검수

인증 없음/만료/잘못된 audience, scope 부족·IDOR, 모드 혼용, 토큰 유출, 악성 뉴스/로그 prompt injection, 리소스 URI 경로 조작, Job 타인 접근, 참조 삭제 및 순환 경쟁, 버전 충돌, 중복 요청, 승인 만료·변조, Kill Switch, 주문 도구 미노출 및 직접 호출 거부를 테스트한다. NH 접근 불가 시 조회 오류를 표시하고 LIVE 주문으로 fallback하지 않는다.

참조: [공식 Python SDK HTTP 인증](https://py.sdk.modelcontextprotocol.io/run/authorization/) · [ASGI 및 HTTP 전송 보안](https://py.sdk.modelcontextprotocol.io/run/asgi/) · [MCP 명세](https://modelcontextprotocol.io/specification) · [공식 Python SDK 인증](https://py.sdk.modelcontextprotocol.io/run/authorization/) · [NH 연동](./nhplug-integration.md).
