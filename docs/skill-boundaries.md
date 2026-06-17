# Skill Boundaries

This document is the source-of-truth map for when the current Claude Code skills should own a request.

| Skill | Owns | Does Not Own |
|---|---|---|
| `dev-flow` | Production-impacting end-to-end work requiring spec, plan, TDD, security, review, and final audit. | Narrow bug fix, test-only change, simple code review. |
| `feature-flow` | New feature or endpoint with implementation and tests. | Existing broken behavior root cause. |
| `fix-flow` | Bug fix or failing behavior requiring root cause and regression test. | Net-new product capability. |
| `refactor-flow` | Behavior-preserving restructure guarded by characterization tests. | Behavior-changing feature/fix work. |
| `test-flow` | Writing or fixing tests without production behavior change. | Owning feature/fix implementation. |
| `orchestration` | Deciding whether work should run in main loop, subagent, workflow, or agent-team. | Performing the domain work itself. |
| `security-review` | Security audit for code, diff, design, or dependency changes. | General maintainability review. |
| `code-review` | Quality review of code/diff/file with fresh context. | Applying received reviewer feedback. |
| `receiving-code-review` | Verifying and applying external review comments. | Producing a fresh review from scratch. |
| `implementasyon-control` | Mandatory pre-final audit that required flow was followed. | Planning or implementing the work. |
| `completion-claim-gate` | Evidence check before saying done/fixed/passing/complete. | Replacing tests, security review, or implementation audit. |
| `mind-spark` | Ambiguous design/build intent before spec. | Clear bug fix, test-only, security review, or code review. |
| `writing-skills` | Creating, changing, evaluating, or packaging Claude Code skills. | Ordinary application feature work. |

## Layer Ownership

| Layer | Owns |
|---|---|
| `rules/` | Durable policy and behavioral contract. |
| `hooks/` | Deterministic enforcement and warnings. |
| `skills/` | Procedure and agentic workflow. |
| `agents/` | Review, audit, and specialist roles. |
| `workflows/` | Deterministic multi-agent author/critic loops. |
| `commands/` | Explicit manual checks. |
| `scripts/` | Machine-checkable helpers. |
