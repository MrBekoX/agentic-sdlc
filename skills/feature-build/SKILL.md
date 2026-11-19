---
name: feature-build
description: This skill should be used first in any language to add a new feature, endpoint, screen, or capability without the full agentic-sdlc-pipeline envelope, via implementation-control. Not for bug/root-cause fixes, test-only work, or behavior-preserving refactors. Not for steps inside an active agentic-sdlc-pipeline run.
---

# Skill: feature-build

> **Argument:** `/feature-build $ARGUMENTS` — if given, that is the target feature; otherwise ask. Match the user's language.

Builds a new feature in small, reversible, convention-respecting steps.

## Invariant
The feature is built to an agreed, testable spec — test-first — and only the agreed scope ships.

## Tripwires
- writing code before a testable acceptance criterion exists
- scope creeping past the spec
- claiming done before exercising the feature path

## Proof
Acceptance criteria → tests (RED→GREEN), the feature path exercised, full suite green, the diff scoped to plan.

## Excuse → check
| Excuse | Check |
|---|---|
| "The spec is obvious, skip it." | Unwritten specs drift mid-build. Write the criteria first. |
| "It compiles." | Compiling is not working. Exercise the feature. |

## Depth contract (proportional — scale rigor to the change)
Each acceptance criterion is an observable, testable check (Given/When/Then or equivalent) — a behaviour you can watch pass or fail, not a feature name — and each maps to a test you saw go RED before it went GREEN. The feature path is exercised end to end and the observed result is shown (the response body, the row written, the rendered state), never inferred from a green build. Each new abstraction is justified by a need present in this change; a "we'll want this later" interface is scope creep, not design. Scale to the work: a one-field addition earns one tight criterion and one test, not a ceremony — short and concrete, never short and unverified.

## Excuse -> check
| Excuse | Check |
|---|---|
| "The criteria are obvious, I'll just build." | Write them as testable checks first — obvious behaviour is the cheapest to pin and the easiest to drift from mid-build. |
| "Types check, so the feature works." | Exercise the actual path and show what it produced; type-clean is not working. |
| "I'll add this interface now, we'll need it later." | Name the need in THIS change it serves, or drop it until the need is real. |

## No placeholders
Do not ship "should work", acceptance criteria written as feature names instead of testable checks, a "done" claim with no exercised path and observed result, or a speculative abstraction parked "for later". If a criterion can't be stated as a check, the behaviour isn't specified yet — say so.

## Shallow example (reject this)
A feature whose only evidence is "build passes, endpoint added" — the path never exercised, no RED→GREEN test, no observed output — is shallow. Reject.

## Call-order guard — dispatch-strategy first

After loading `feature-build`, do not read files, run shell commands, or take any other action until you have called `Skill` -> `agentic-sdlc:dispatch-strategy` to set the working strategy for this task (in a runtime without a `Skill` tool, read the installed `dispatch-strategy` `SKILL.md`; that read is the activation, and a missing `Skill` tool is not a reason to stop). Required even when the likely answer is "small single-file work; main loop is enough" — making the decision explicit is the point. The skill then runs under the chosen mechanism; the Orchestration section below applies it (reads fan out, writes stay serial).

## Orchestration — fan out scope and verification, you coordinate (consult `dispatch-strategy` first)
Two read-only fan-out points: the **scope map** (one `context-analyst` per affected layer, in a single message) and **verification** (test / lint / security lenses in parallel — `security-reviewer` for the security lens). Dispatch each set concurrently and stay the **coordinator**: merge the layer maps into one scope, read the verification results, decide. Interdependent code and ordering decisions stay in the main loop; writes stay serial — never two agents on one file.
- **Degrade:** inside a delegated sub-agent (no nesting) or a runtime without parallel agents → run scope/verification in the main loop and flag `Delegation Degraded: parallel specialists unavailable`.

## Flow
1. **Requirement analysis** — what the feature must do; who uses it; constraints.
2. **Scope map** — affected layers/files, existing signatures/conventions to follow, integration points. For multi-file features, fan this out with the runtime's workflow/subagent/parallel equivalent (don't scan serially in the main loop). Output feeds the spec.
3. **Spec** (contract 02) — business rules · acceptance criteria (testable) · edge cases · definition of done · must-not-change behaviors. Use `spec-plan-author` → `spec-plan-critic` for depth.
4. **Plan + approval** (contract 03) — small single-purpose tasks, each mapped to acceptance criteria, files + TDD points named. **Get user approval before big changes.** Use the runtime goal tool when available; otherwise write the Goal Lock template inline and treat it as the scope lock.

**Save the spec and plan before the first test edit.** Step 10's resolver and the flow hooks read these files, not the chat, so a spec or plan kept only in the conversation blocks `implementation-control`. Write each with the file-edit tool (never a shell redirect), use one `<work_id>` for both, and fix the file until its command exits 0:
- `docs/agentic-sdlc/specs/<work_id>.md` with `work_id` and `status` frontmatter, then `python3 "<runtime-root>/scripts/validate_artifacts.py" --mode spec --file docs/agentic-sdlc/specs/<work_id>.md --strict`.
- `docs/agentic-sdlc/plans/<work_id>.md` with `work_id`, `spec: ../specs/<work_id>.md`, `branch` (the output of `git branch --show-current`) and `status` frontmatter, then `python3 "<runtime-root>/scripts/validate_artifacts.py" --mode plan --file docs/agentic-sdlc/plans/<work_id>.md --spec docs/agentic-sdlc/specs/<work_id>.md --strict`.
- `status` is `reviewed` once drafted and `approved` after the user approves; acceptance criteria carry `AC<n>` ids that the plan's tasks cite.

**Plugin root (`<runtime-root>`):** the installed agentic-sdlc folder, two levels above this `SKILL.md` (`<runtime-root>/skills/<name>/SKILL.md`) — never the user's working directory. Claude Code substitutes `${CLAUDE_PLUGIN_ROOT}`; Claude Code and ZCode substitute `${CLAUDE_SKILL_DIR}/../..`; Kimi Code substitutes `${KIMI_SKILL_DIR}/../..`; a SessionStart line `Plugin root (resolved by this hook…)` names it on Claude Code, Codex, ZCode and Cursor; Codex and Grok CLI show this skill's absolute path in the skill listing. A `${…}` token still shown literally is unresolved: never pass it to a shell. Confirm `<runtime-root>/scripts/validate_artifacts.py` exists and write that absolute path, quoted for your shell, into commands; if it cannot be confirmed, stop the step and report `plugin root unresolved` — never run a same-named file from the user's project. Run helpers with `python3` (Python 3.8+), or `py -3` on Windows when `python3` is missing or is the Microsoft Store alias.

Read [references/core.md](references/core.md) before step 5 and run the steps marked "core step" exactly as its `## Core steps` section writes them. Resolve the link from this installed skill's directory. In Claude Code, use `Read`; in Codex, use the available file-reading tool for the exact installed reference path. Reload it after resume, compaction, or a supplied summary.

5. **Failing test** — core step 1.
6. **Implementation + verification** — core step 2.
7. **Security analysis** — core step 3.
8. **Refactor** — core step 4.
9. **Documentation** — core step 5.
10. **Implementation control** — run **`implementation-control`** before finalizing; complete any gap and re-run. Don't give the final answer if a critical step is missing.

## Final Response
What was built · files changed · tests run (with result) · security notes · remaining risks · user actions needed.

## Limits
- One feature = one task set. No unrelated refactor (contract 04).
- Adding packages / migrations / commit / push require user approval (contract 08).
