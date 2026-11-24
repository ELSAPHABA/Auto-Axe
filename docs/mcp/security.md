# MCP 인증·인가·승인 및 보안 명세

## 1. 신뢰 경계

Auto-Axe MCP는 플랫폼의 사용자 권한 범위 내 업무 접근 인터페이스다. AI Host의 모델 판단, 도구 승인 UI, Tool annotations 및 프롬프트는 서버 인가를 대체하지 않는다. 독립 nhplug-mcp는 별도 자격증명·프로세스·네트워크 경계에서 조회만 수행한다. 실주문 실행 서비스는 공식 nhplug-sdk 기반 독립 Trading Executor로 확정하며, 구현·모의 검증 및 실거래 활성화 승인 전 비활성이다.

## 2. 인증

- 원격 endpoint는 TLS 및 OAuth 2.1 기반 Resource Server. 인증 서버/OIDC 제품은 구현 단계에서 확정한다. 공식 MCP authorization의 discovery, 보호 리소스 metadata, WWW-Authenticate 등은 선택한 protocol revision/SDK에 맞춘다.
- 모든 요청의 issuer, audience/resource, 서명 또는 introspection, 만료, scope, client 및 사용자 신원을 확인한다. MCP 연결/세션 ID를 인증으로 사용하지 않는다. 토큰을 타 서버에 그대로 전달하지 않는다. stdio 로컬 개발은 OS 프로세스 실행 경계와 별도 로컬 권한 정책.
- 서버가 부여한 actor_id, user_id, tenant/owner_ref, account_ref를 이용하며 요청 본문이 주장하는 사용자 ID를 신뢰하지 않는다. 서비스 계정과 사용자 위임을 구분한다.
- Origin 검증 및 DNS rebinding/SSRF 방어, 허용 Host·네트워크·요청 크기 제한. NH API 비밀키·토큰·계좌 정보는 전용 비밀 저장소 및 마스킹; MCP payload, 로그, Prompt, Git, 브라우저에 노출하지 않는다.

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

참조: [MCP 명세](https://modelcontextprotocol.io/specification) · [공식 Python SDK 인증](https://py.sdk.modelcontextprotocol.io/run/authorization/) · [NH 연동](./nhplug-integration.md).
