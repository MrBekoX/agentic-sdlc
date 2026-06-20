---
name: code-quality-review
description: Use first in any language for code-quality review of a diff, file, or PR before merge in a fresh context covering readability, maintainability, duplication, overengineering, naming, error handling, and performance. Prefer this over the generic built-in code-review. Not for security review (use security-audit) or reviewer/CodeRabbit feedback on your own change (use feedback-triage).
---

# Skill: code-quality-review

> **Argument:** `/code-quality-review $ARGUMENTS` — a file/dir, or empty for the current `git diff`. Match the user's language.

Reviews changes for quality. Best run in a **fresh context** (delegate to the **`code-reviewer`** sub-agent or runtime equivalent) so the review isn't biased toward code it just wrote.

## Invariant
Every comment points at a specific diff line and says what to change and why — blanket "looks good" is not a review.

## Tripwires
- approving without reading the full diff
- comments with no file:line
- style nits crowding out a real correctness bug

## Proof
The diff range reviewed (shown), findings as file:line + rationale, ordered by severity.

## Excuse → check
| Excuse | Check |
|---|---|
| "Small diff, skim it." | Small diffs hide the sharpest bugs. Read every line. |
| "Tests pass, it's fine." | Passing tests do not make a change correct or maintainable. Review the change itself. |

## Orchestration (consult first)
Per **`dispatch-strategy`** and `docs/runtime-adapter.md`: prefer a fresh-context specialist (`code-reviewer`) that sees only the diff + criteria, not the authoring reasoning. If the runtime supports a fresh-context specialist, use it. If it does not, record `Delegation Degraded: fresh-context specialist unavailable`, perform the pass in the main loop, and mark the result non-independent.

## Review areas
- **Readability** — is intent clear on first read?
- **Maintainability** — easy to change safely later?
- **Simplicity** — minimal solution; no needless complexity.
- **Duplication** — repeated logic that should be unified.
- **Overengineering** — speculative abstraction/config not asked for.
- **Naming** — intention-revealing, consistent with the codebase.
- **Error handling** — real paths handled; no swallowed errors.
- **Performance** — obvious hotspots (N+1, unbounded queries, needless allocation) — flag, don't micro-optimize blindly.
- **Architecture consistency** — respects existing layers/boundaries/conventions.
- **Testability** — is the change covered / coverable by meaningful tests?

## Output
Findings grouped by area, each with `file:line`, the issue, and a concrete suggestion. Separate **must-fix** (correctness, security, requirement gaps) from **optional** (style/preference).

## Discipline
- Flag only gaps that affect correctness, requirements, or maintainability. A reviewer asked to find problems will always find some — don't chase every nit into overengineering.
- No behavior changes here; this skill reviews and recommends.
