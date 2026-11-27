# Auto-Axe agent handoff

Before editing, read [.ai-context/CONTEXT.md](.ai-context/CONTEXT.md), the latest linked Phase log, [docs/README.md](docs/README.md), and the authorized Phase of [PHASE_PLAN.md](docs/development/PHASE_PLAN.md). Verify the real branch, HEAD, work tree and remote, then reconcile them with the log. The user's latest explicit requirements override earlier instructions; record modifications and approvals without losing prior history.

Latest Phase 2 start: [.ai-context/phases/phase-02/2026-11-27-01.md](.ai-context/phases/phase-02/2026-11-27-01.md) and [Phase 2 verification/blocked sources](docs/development/PHASE_02_IMPLEMENTATION.md). The fact that fixture parsers and a private broker app exist is NOT authorization to fetch real websites or evidence that Keycloak/mTLS is deployed. Preserve fail-closed defaults; do not mark external scrapers operational from synthetic tests.

Use the existing Phase 0–8 numbering and original specification/contract/SEC acceptance criteria. A later Phase requires its dependency gates and user authorization. Development, fixture, paper, and LIVE approval are separate; no provider or brokerage calls without the required permission, and no direct order submissions from REST/MCP. Never store real credentials, tokens, account data, private keys, or raw tool transcripts.

Update the phase log using [.ai-context/PHASE_LOG_TEMPLATE.md](.ai-context/PHASE_LOG_TEMPLATE.md) at entry, material milestones/errors, interruption, and exit. Include exact commands, real verification outcomes, failures and next actions. Keep CONTEXT synchronized while retaining historical specification. Do not claim unrun checks passed, and verify the saved commit/remote before reporting.

User requirement (2026-11-27): separately maintain [development troubleshooting](docs/troubleshooting/README.md), one linked Phase document per Phase, with symptoms, reproduction/environment, investigation evidence, verified root cause vs hypothesis, rejected approaches, fixes, regression results and residual risks. Update when problems occur; never replace the operational handoff or include secrets.
