# 개발 계획 기준선 — planning-baseline-20261126

## METADATA (메타데이터)
- 2026-11-26 KST, repository ELSAPHABA/Auto-Axe, remote main baseline da26b439e1d2deaabed7138ee3f83897a44e023c, tree 188dc0e7c9e66ed7af9cbdb8ab5887eda94a59ee.
- Planning baseline only; not Phase 0. No supplied session ID. [Context](../CONTEXT.md), [plan](../../docs/development/PHASE_PLAN.md).

## TASK (작업 목표)
사용자는 코드 개발에 앞서 전체 /docs 설계 분석과 Phase 계획 수립 및 매 Phase 상세 기록/무손실에 가까운 세션 인계를 요청했다.

## USER SPECIFICATION (사용자 명세)
[CONTEXT §USER SPECIFICATION](../CONTEXT.md)의 13개 항목은 이번 직접 사용자 요청을 보존한다. 기존 기능/보안/데이터/거래 문서 우선, 추가 승인으로 오인하지 않는다. 기존 맥락 문서가 있으면 먼저 읽기 요청에 따라 immutable recursive tree 검사: 기존 .ai-context/ 없음.

## CURRENT STATE (현재 상태)
분석 기준 원격 파일 구조: .gitignore, LICENSE, README.md, docs/. 실제 app/infra/CI 없음. docs/examples만 PoC. Phase 0~8 NOT_STARTED. 최초 실제 작업 P0.1, 사용자의 다음 Phase 요청 이후. 

## ARCHITECTURE / DECISIONS (아키텍처 및 의사결정)
문제: 개발 단계 및 기록 방법 필요. 조사: docs/README의 authority matrix, testing-roadmap §2 및 contracts §10이 Phase 0~8을 유일한 전역 roadmap으로 명시. 결정: 이를 변경하지 않고 Pn.x work package/exit/dependency/FR-SEC crosswalk와 operational context를 별도 문서로 추가(계획상 선택, 추가 기능/실거래 사용자 승인 아님). 대안: 새 전역 번호 체계 또는 별개 MVP로 기능 축소 — 기존 문서와 불일치하여 채택하지 않음. 실제 코드/원본 설계 변경 없음.

## DONE (완료된 작업)
- remote metadata/tree inspected at known HEAD, recursive listing not truncated.
- documents hierarchy reviewed and functional IDs, architecture, market source policies, security and MCP catalogs extracted; PoC function/dependency list inspected. Original large NH source/master retained for targeted later checks.
- Phase work packages, source crosswalk, unresolved registry, execution gates and handoff structure drafted as linked documentation.

## FAILED / UNRESOLVED (실패 및 미해결 사항)
One initial oversized multi-file request hit tool-call cap ("Code Mode exceeded the maximum number of tool calls."); smaller groups used to recover. Long combined output truncated, targeted extracts used. No code or build failure as none run. NH llms-full and overseas master not exhaustively parsed. Provider rights, SDK versions, deployment parameters, paper evidence and LIVE authorization open as described in plan R01~R08. No local state inspected.

## FILES (관련 파일)
docs/development/PHASE_PLAN.md; .ai-context/CONTEXT.md; .ai-context/PHASE_LOG_TEMPLATE.md; .ai-context/phases/planning-baseline.md. Existing docs/README index extended to point to plan/context. Original specification and PoC unchanged by design.

## VERIFICATION (검증)
Remote metadata/tree and document reads only. No code test, build, actual provider or broker API call, local checkout, runtime or deployment. Documentation commit and branch readback should be verified through Git. Exact reference commit listed above; self commit via history.

## ENVIRONMENT / GIT STATE (환경 및 Git 상태)
Remote main known baseline, connector push allowed. Local work tree/staging/process/install unknown. No agents delegated.

## NEXT (후속 작업)
Read latest main and context; confirm planning commit. On user request for Phase 0 create phase-00 log, verify local Git/workspace and compatibility evidence, start P0.1 then plan sequence. Preserve all user instructions and actual progress. Do not start LIVE.

## DO NOT (금지 사항)
Do not claim Phase 0 completion, start code execution or any trade based on this planning session; do not rewrite canonical phase numbering or original docs; no secrets.

## SESSION HISTORY (세션 이력)
2026-11-26: baseline inspection → existing roadmap confirmed → subphase plan + lossless handoff structure drafted. No runtime work.
