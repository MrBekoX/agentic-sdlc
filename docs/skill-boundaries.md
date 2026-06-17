# Skill Boundaries

This document is the source-of-truth map for when the current Claude Code and Codex skills should own a request.

| Skill | Owns | Does Not Own |
|---|---|---|
| `using-agentic-sdlc` | Session-local routing, smallest-sufficient-skill selection, scope-shift tracking, and evidence-before-claim discipline. | Performing implementation, review, or audit work itself. |
| `agentic-sdlc-pipeline` | Full-envelope end-to-end implementation requiring spec, plan, TDD, security, review, final audit, and release/PR readiness. | Focused feature, fix, test, spec, plan, or review requests that do not need the full envelope. |
| `spec-authoring` | Spec-only WHAT work: requirements, acceptance criteria, behavior contract, edge cases, definition of done. | Planning HOW tasks or implementing the change. |
| `plan-authoring` | Plan-only HOW work: task breakdown, sequencing, affected surfaces, TDD points, verification plan. | Inventing missing WHAT or implementing the plan. |
| `feature-build` | New feature or endpoint with implementation and tests. | Existing broken behavior root cause. |
| `root-cause-fix` | Bug fix or failing behavior requiring root cause and regression test. | Net-new product capability. |
| `safe-refactor` | Behavior-preserving restructure guarded by characterization tests. | Behavior-changing feature/fix work. |
| `test-authoring` | Writing or fixing tests without production behavior change. | Owning feature/fix implementation. |
| `dispatch-strategy` | Deciding whether work should run in main loop, subagent, workflow, or agent-team. | Performing the domain work itself. |
| `security-audit` | Security audit for code, diff, design, or dependency changes. | General maintainability review. |
| `code-quality-review` | Quality review of code/diff/file with fresh context. | Applying received reviewer feedback. |
| `feedback-triage` | Verifying and applying external review comments. | Producing a fresh review from scratch. |
| `implementasyon-control` | Mandatory pre-final audit that required flow was followed. | Planning or implementing the work. |
| `completion-claim-gate` | Evidence check before saying done/fixed/passing/complete. | Replacing tests, security review, or implementation audit. |
| `mind-spark` | Ambiguous design/build intent before spec. | Clear bug fix, test-only, security review, or code review. |
| `skill-authoring` | Creating, changing, evaluating, or packaging Claude Code skills. | Ordinary application feature work. |

## Spec/Plan Boundary

`spec-authoring` and `plan-authoring` are standalone prompt-level routes. They are not agentic-sdlc-pipeline substeps.

When `agentic-sdlc-pipeline` needs spec and plan artifacts, it owns those phases directly:

- Claude Code: use `spec-plan-draft` workflow.
- Codex: use agentic-sdlc-pipeline's embedded author/critic adapter and validate the saved artifacts.

## Layer Ownership

| Layer | Owns |
|---|---|
| `contracts/skills/` | Durable skill behavior contracts. |
| `hooks/` | Deterministic enforcement and warnings. |
| `skills/` | Procedure and agentic workflow. |
| `agents/` | Review, audit, and specialist roles. |
| `workflows/` | Deterministic multi-agent author/critic loops. |
| `commands/` | Explicit manual checks. |
| `scripts/` | Machine-checkable helpers. |
