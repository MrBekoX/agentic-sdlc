---
name: code-quality-review
description: This skill should be used first in any language for code-quality review of a diff, file, or PR before merge in a fresh context covering readability, maintainability, duplication, overengineering, naming, error handling, and performance. It is the AGENTIC-SDLC route for general code review. Not for security review (owned by security-audit) or reviewer/CodeRabbit feedback on your own change (owned by feedback-triage).
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

## Call-order guard — dispatch-strategy first

After loading `code-quality-review`, do not read files, run shell commands, or take any other action until you have called `Skill` -> `agentic-sdlc:dispatch-strategy` to set the working strategy for this task. Required even when the likely answer is "small single-file work; main loop is enough" — making the decision explicit is the point. The skill then runs under the chosen mechanism; the Orchestration section below applies it (reads fan out, writes stay serial).

## Orchestration — fan out per layer, you coordinate (consult `dispatch-strategy` first)
When the diff spans 2+ independent layers or file-groups, dispatch **one `code-reviewer` per layer in a single message** so they run concurrently — each sees only its slice of the diff + the criteria, not the authoring reasoning, so the pass is unbiased. For a structural change, add a `software-architect` instance for the architecture lens. You (main loop) stay the **coordinator**: merge findings, dedup, split must-fix from optional, decide. Reads fan out; any fix is applied serially in an implementation skill, never by two agents on one file.
- **Independent verdict:** when a clean/done call would mean judging code you wrote, route the merged findings through `implementation-auditor` (via `implementation-control`), not self-attestation.
- **Degrade:** a single-layer diff, or running inside a delegated sub-agent (no nesting), or a runtime without parallel agents → review in the main loop and record `Delegation Degraded: fresh-context specialist unavailable`, marked non-independent.
- **Higher-rigor pass:** the `multi-lens-review` workflow (preset `quality`) fans out the review lenses, then adversarially verifies each finding before you act on it.

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
