# Phase <NN> — <세션 기록 ID>

> 사용법: 복사하여 `.ai-context/phases/phase-NN/<YYYY-MM-DD>-<sequence>.md` 등 충돌 없는 경로에 저장. 사용자 요구에 따라 큰 기록은 10,000~30,000토큰 목표, 필요한 경우 보조 파일로 분할/링크. 실제 증거 기반으로 작성. 내용 없는 항목 생략. 기존 로그와 CONTEXT를 읽고 병합하고, 변경 전 요구와 최종 결정 및 이력 유지. 비밀/원본 도구 payload 절대 기록 금지.

## METADATA (메타데이터)
- repo URL / actual branch / session ID (없으면 논리 ID) / timezone and date / base HEAD / 관련 커밋 / working tree state / log version.
- Phase/hierarchical work package / status NOT_STARTED, IN_PROGRESS, BLOCKED, IMPLEMENTED_UNVERIFIED, VERIFIED, NOT_APPLICABLE(근거).
- [CONTEXT](../../CONTEXT.md), [Phase plan](../../../docs/development/PHASE_PLAN.md), relevant original spec paths/sections.

## TASK (작업 목표)
- 이번 사용자 요청과 original goal, 해당 Phase의 entry/exit 및 범위. 후속 요구.

## USER SPECIFICATION (사용자 명세)
- 직접 사용자 지시 전체 실질 내용; new/changed/superseded/unchanged, 이전 및 최종, 승인 일자·범위, 검증되지 않은 해석 별도. 참조하는 기존 문서와 정확한 FR/SEC/MCP/contract IDs.

## CURRENT STATE (현재 상태)
- 실제 구현/운영/Git 상태, 각 subtask status 및 현재 중단점. 이전 완료 작업과 이번 작업 구분. 코드 작성/테스트/외부 권한/LIVE 각각 별도.

## ARCHITECTURE / DECISIONS (아키텍처 및 의사결정)
- 기존 계약/새 ADR/검토 대안/선택 이유, rejected reason, impact/rollback, user approved vs agent proposal vs hypothesis. 원본 문서 및 테스트 동시 갱신 여부.

## DONE (완료된 작업)
- subtask ID, FR/SEC, file/function/schema, 실제 evidence, commit, result; verified vs unverified.

## IN PROGRESS (진행 중인 작업)
- 정확한 파일/함수/line/branch/last successful operation, partially written state, next action, 예상 결과 및 검증.

## PLANNED / DECIDED (계획 및 확정 사항)
- 승인/계획 별도로, 구현되지 않은 사항과 선행 조건/의존성.

## FAILED / UNRESOLVED (실패 및 미해결 사항)
- 문제 → 조사 → root cause(가설 vs verified) → 변경 → 검증 → remaining. 정확한 오류/명령/버전/영향/실패한 대안과 이유; 비밀 redacted.
- 별도 [트러블슈팅 인덱스](../../../docs/troubleshooting/README.md) 및 phase-NN.md에도 상세 재현, 원인, 대안, 수정, 재검증, 잔여 위험을 기록하고 상호 링크. 사용자 2026-11-27 지시.

## FILES (관련 파일)
- path / status / purpose / key identifiers / relevant commits / artifacts.
- 기존 변경 보존, 영향받는 원문 및 acceptance map.

## VERIFICATION (검증)
| 요구사항/테스트 ID | 명령 및 환경/fixture | 결과/exit code/통과·실패·skip 수 | evidence path/commit | remaining/gate |
|---|---|---|---|---|
- 실제 실행한 명령만 성공 기록. 미실행은 not run 사유. Provider live/paper/mock/CI distinction, secret-free.
- Phase gate checklist with status, acceptance source. No fabricated status.

## ENVIRONMENT / GIT STATE (환경 및 Git 상태)
- local checkout remote branch HEAD/staging/untracked/uncommitted; remote branch SHA; installed exact versions/lock hash; ports/processes/services/deploy status; verified scope. Unknown explicitly. Final commit SHA may be referenced by Git history if self-reference.

## AGENT STATE (에이전트 상태)
- delegated tasks/IDs/status/outputs/verification and unfinished; no claimed agents if none.

## NEXT (후속 작업)
- ordered executable next actions, exact command/path and preconditions, rollback if needed. No reasking already-known user data.

## DO NOT (금지 사항)
- global context prohibitions plus phase-specific rejected approaches/immutable artifacts/operational restrictions.

## SESSION HISTORY (세션 이력)
- timestamped material event, user direction, evidence/decision, status transition, link prior records. Avoid raw tool calls/response dumps.

## 기록 체크

- [ ] 기존 context 및 관련 phase log 읽고 merge
- [ ] 사용자 메시지의 실질적 요구 누락 없음, 변경·승인 범위 표시
- [ ] 상태·실패·검증·정확한 다음 단계 명시
- [ ] 별도 Phase 트러블슈팅 문서 갱신 및 상호 링크
- [ ] secret/민감정보 제거, 원본 tool payload 제외
- [ ] CONTEXT와 phase log를 실제 코드/commit에 맞춰 갱신, 원격 저장 확인
