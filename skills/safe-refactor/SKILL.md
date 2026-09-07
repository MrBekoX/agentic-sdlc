---
name: safe-refactor
description: Use first in any language to refactor, restructure, clean up, simplify, or reduce duplication without changing behavior. Activate this skill as the first action, before Glob/Read or file-existence checks and even for broad scope needing approval; announcing you will refactor is not the same as invoking it. Includes characterization tests and approval for broad scope. Not for bug fixes, new features, or test-only work.
---

# Skill: safe-refactor

> **Argument:** `/safe-refactor $ARGUMENTS`. Match the user's language. Governing contract: 07.

Improves structure while **preserving behavior**.

## Invariant
Same inputs, same outputs — before and after. A refactor that moves behavior is a change in disguise.

## Tripwires
- a test had to change for the suite to stay green
- "this is equivalent" said without capturing behavior to back it
- tidying one extra unrelated thing "while I'm here"

## Proof
Behavior captured as a snapshot before and after the change; the before/after **behavior-snapshot** diff is empty (the source diff is expected to be non-empty). Show the capture command and the empty snapshot diff.

## Excuse → check
| Excuse | Check |
|---|---|
| "Obviously equivalent." | Then the before/after behavior snapshot is identical — capture both and show the empty snapshot diff. |
| "Tests still pass." | They passed before too. Prove *this* change preserved behavior, not that the suite was already green. |

## Depth contract (proportional — scale rigor to the change)
Name the specific observable behaviors held invariant — concrete input->output pairs, side effects, and error paths — and the characterization that pins each. "Equivalent" must point at the captured before/after snapshot, never stand alone as a word. For each structural step (extract / rename / dedupe / simplify) state what moved and the evidence its observable behavior is unchanged for the inputs that hit the touched path. Proportional: a small local refactor pins the few behaviors it can perturb; it does not re-characterize the whole module.

## Excuse -> check
| Excuse | Check |
|---|---|
| "It's a pure rename, nothing to characterize." | Name the call sites and exported surface it touches; renaming an exported name changes behavior for every consumer that imports it. |
| "Smaller and cleaner, same result." | Show the before/after snapshot is identical for the inputs that hit the changed path — cleaner is not the same as equivalent. |
| "It's a minor tidy." | Then name the one behavior it *could* shift (an order, a default, an error case) and show that one is held — "minor" is where semantic drift hides. |

## No placeholders
Don't ship "behavior unchanged" with no captured snapshot, or let "equivalent" / "clean up" / "minor" stand in for a behavior you never characterized while it quietly hides a semantic shift.

## Shallow example (reject this)
"Refactored for clarity; the suite is green so behavior is preserved." Green before AND after is not proof *this* change preserved behavior — the suite was already green. Reject and capture the before/after snapshot for the inputs the change actually touches.

## Call-order guard — dispatch-strategy first

After loading `safe-refactor`, do not read files, run shell commands, or take any other action until you have called `Skill` -> `agentic-sdlc:dispatch-strategy` to set the working strategy for this task. Required even when the likely answer is "small single-file work; main loop is enough" — making the decision explicit is the point. The skill then runs under the chosen mechanism; the Orchestration section below applies it (reads fan out, writes stay serial).

## Orchestration — characterize in parallel, edit serially, you coordinate (consult `dispatch-strategy` first)
Characterizing current behavior across modules is a read-only fan-out: dispatch **one `software-architect` or `context-analyst` per module in a single message** to map the observable behavior and boundaries that must not move. You (main loop) stay the **coordinator**: assemble the safety net, then refactor. Large parallel *edits* are the dangerous part — run them **worktree-isolated** (a `Workflow` with worktree isolation), never two agents on one file; a small refactor just stays in the main loop.
- **Degrade:** inside a delegated sub-agent (no nesting) or a runtime without parallel agents → characterize/edit in the main loop and flag `Delegation Degraded: parallel specialists unavailable`.

## Flow
1. **Characterize current behavior** — identify the behavior that must not change. If tests don't cover it, **add characterization tests first** and see them pass (show output). This is the safety net.
2. **Define scope** — what is being restructured and what is explicitly out of scope. Use the runtime goal tool when available; otherwise write the Goal Lock template inline and treat it as the scope lock.
3. **Approval gate** — for large/architectural refactors, get user approval before starting.
4. **Small steps** — one structural change at a time (extract, rename, dedupe, simplify). After **each** step run the relevant tests and **show output**. Use the runtime loop tool when available; otherwise record each fail -> fix -> retest cycle with command evidence.
5. **No behavior change** — if a "refactor" alters behavior, stop: that is a feature/fix, not a refactor.
6. **Security re-check** (contract 06) if the refactor touches auth/config/data paths.
7. **Implementation control** — run **`implementation-control`** before finalizing.

## Final Response
What was restructured · files changed · proof behavior is unchanged (tests green before & after, with output) · remaining risks.

## Forbidden
- Refactoring without a passing-test safety net.
- Mixing behavior changes into the refactor.
- Large architectural change without approval.
- Drive-by refactors bundled into unrelated work.
