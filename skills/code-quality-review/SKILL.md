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

## Depth contract (proportional — scale rigor to the change)
Each finding cites the exact `file:line`, names the concrete consequence it carries — the bug it risks, the future change it would block, or the reader it would mislead — and gives the specific change, not a category like "improve naming" or "add error handling". A "no must-fix" verdict is itself evidence: name the lines you actually read and the properties you checked (this path handles the empty case; that error is propagated, not swallowed), so the all-clear is earned, not assumed. Scale to the diff: flag only what touches correctness, the stated requirement, or maintainability — leave taste alone, and don't manufacture findings to look thorough.

## Excuse -> check
| Excuse | Check |
|---|---|
| "Naming could be better." | Give the exact identifier, the name you'd use instead, and the wrong inference the current one invites in a reader. |
| "Looks maintainable." | Name the realistic future change, point at the line that would have to move for it, and show why it stays cheap. |
| "Probably a minor perf thing." | Show the input that makes it bite (the N, the unbounded set) at `file:line`, or drop it. |

## No placeholders
Do not write "consider refactoring" with no named target, "looks good" as a verdict, "improve naming" without the replacement, or a flat pile of nits with no must-fix / optional split. Every line of output points somewhere and proposes something concrete.

## Shallow example (reject this)
"Overall clean, maybe tidy some variable names." — no `file:line`, no consequence, no replacement name, no must-fix/optional split. It performs review without doing it. Reject.

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
