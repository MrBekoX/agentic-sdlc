---
name: root-cause-fix
description: Use first in any language to fix a bug, error, broken behavior, failing test, production issue, regression, or incident at its root-cause (reproduce, find and fix). Not for new features, pure refactors, or review feedback.
---

# Skill: root-cause-fix

> **Argument:** `/root-cause-fix $ARGUMENTS` — if `$ARGUMENTS` is given, that is the target bug/issue; otherwise ask the user what the problem is. Match the user's language.

The primary fix workflow. Resolves a problem at its **root cause**, with the smallest change, verified by tests and a double security pass, and audited before the final answer. It is a **gated, looped** flow — don't skip steps; a red gate means go back, not forward.

## Invariant
A bug is fixed only when a test that failed *because of it* now passes — and nothing else changed.

## Tripwires
- the fix went in but no test reproduced the bug first
- the change is widening past the one reported bug
- tempted to refactor unrelated code while here

## Proof
The regression test shown RED before the fix and GREEN after, plus the full-suite output.

## Excuse → check
| Excuse | Check |
|---|---|
| "The fix is obvious." | An obvious fix still needs the failing-then-passing test; obvious fixes mis-target often. |
| "The suite is slow." | A false "fixed" costs a round-trip plus a second bug. Run it. |

## Depth contract (proportional — scale rigor to the change)
Trace the actual causal chain for this bug: trigger -> the intermediate state it corrupts -> the specific line or condition that emits the wrong output. Say why your fix lands at that root layer rather than one call up where the bad value merely surfaces. The regression test names the exact wrong behavior it reproduces (the concrete value/effect, not "it breaks"). Each edge case is a concrete input that reaches the faulty line, not a category. Proportional: a one-line bug earns a one-line chain — still trigger->wrong-output, still concrete.

## Excuse -> check
| Excuse | Check |
|---|---|
| "Added a guard, it's fixed." | Then name what produced the bad value upstream and why guarding *here* is the root layer — not a band-aid catching a defect born elsewhere. |
| "The root cause is obvious." | Write the chain trigger->...->wrong output in one line. If you can't, you have a symptom, not the cause. |
| "It's an edge case." | Then state the concrete input that hits the faulty line and the wrong output it yields — a category name proves nothing. |

## No placeholders
Don't ship "added a defensive check" as the whole root-cause story; an "edge case" with no concrete triggering input; or a "root cause" that just restates the symptom in other words.

## Shallow example (reject this)
"Root cause: the function returned null. Fix: added a null check." That restates the symptom (null appeared) as if it were the cause. The real root cause names *why* it was null — which upstream path left it unset and under what trigger. Reject and trace it.

## Call-order guard — dispatch-strategy first

After loading `root-cause-fix`, do not read files, run shell commands, or take any other action until you have called `Skill` -> `agentic-sdlc:dispatch-strategy` to set the working strategy for this task. Required even when the likely answer is "small single-file work; main loop is enough" — making the decision explicit is the point. The skill then runs under the chosen mechanism; the Orchestration section below applies it (reads fan out, writes stay serial).

## Orchestration — fan out investigation and verification, you coordinate (consult `dispatch-strategy` first)
Two read-only fan-out points: **investigation** — heavy context-gathering goes to a `context-analyst` sub-agent, and when several root causes are plausible, dispatch **one `debugger` per competing hypothesis in a single message** so they're investigated concurrently; and **verification** — the test/lint/security lenses in parallel. You (main loop) stay the **coordinator**: weigh the hypotheses against evidence, pick the root layer, decide. The fix itself is written in the main loop (serial, in scope) — never fan out writers onto one file.
- **Degrade:** inside a delegated sub-agent (no nesting) or a runtime without parallel agents → investigate/verify in the main loop and flag `Delegation Degraded: parallel specialists unavailable`.

## Flow (with gates)

### 1. Issue / Bug Analysis
State: what is the bug; expected behavior; actual behavior; how to reproduce; affected files; risky areas. If it can't be reproduced, say so explicitly.

### 2. Context Gathering
Read the relevant code, tests, logs, and config. Check for prior patches/refactors in the area. (If heavy/independent → delegate to a **sub-agent**; intermediate reads stay in its context.)

### 3. Spec (the WHAT — code-independent) — contract 02
Problem definition · acceptance criteria (each testable) · edge cases · definition of done · **must-not-change behaviors**. For deep specs use the `spec-plan-author` -> `spec-plan-critic` adapter (`spec-plan-draft` in Claude Code; available subagents or main-loop degraded pass elsewhere).
**Gate:** spec exists and criteria are testable.

### 4. Plan (the HOW) — contract 03
Break into small single-purpose tasks; each maps to acceptance criteria, each is testable; name files + TDD points; flag risky steps; request approval if the fix is large/architectural.
**Gate:** every acceptance criterion has a task.

### 5. Goal lock
Use the runtime goal tool when available with a measurable end-state (e.g. *"the failing test in X passes, full suite green, no other behavior changed"*). Otherwise write the Goal Lock template inline and treat it as the scope lock.

### 6. TDD / Regression test (RED) — contract 05
Write a failing test that reproduces the bug. **Confirm it actually fails** (show output) before writing any fix.

### 7. Implementation (GREEN)
Minimal code to pass the test. Only files in plan scope. No unrelated refactor, no scope-creep, don't break the architecture, justify any new abstraction.

### 8. Test Run
Run the targeted test, then the full suite where feasible. **Show real output.**
**Loop A — test fail:** analyze → fix → retest. Use the runtime loop tool when available; otherwise record each fail -> fix -> retest cycle with the Loop Iteration template and command evidence. Don't proceed while red.

### 9. Security Analysis (#1) — contract 06
Review the diff: input validation, auth/authorization (incl. IDOR), secret leakage, injection, race conditions, data-loss risk, permission issues, dependency risk. Mask any secret (`***MASKED***`).
**Loop B — finding:** fix → re-run security analysis → re-run tests.

### 10. Refactor — contract 07
Only necessary cleanup; behavior unchanged; improve readability, reduce duplication/complexity.

### 11. Retest
Re-run the full suite after refactor; **show output**. (Loop A applies again if red.)

### 12. Final Review
Review `git diff`: summarize changed files, remaining risks, anything left open. Confirm only intended files changed and no secrets are present.

### 13. Implementation Control (mandatory) — run `implementation-control`
Trigger the **`implementation-control`** skill to audit that steps 1–12 were truly done.
**Loop C — control reports a gap:** complete the missing step → re-run `implementation-control`. **If a critical step is missing, do NOT give the final answer** — finish it or tell the user clearly.

### 14. Final Response
Report: what was fixed · which files changed · which tests ran (with result) · remaining risks · any action the user must take.

## Loop points (summary)
- **Test fail** → analyze → fix → retest (runtime loop tool or manual Loop Iteration artifact).
- **Security finding** → fix → re-check security → retest.
- **Implementation-control gap** → complete step → re-run control.

## Goal Lock template
```md
# Goal Lock
## Main Goal
## Non-Goals
## Acceptance Criteria
## Constraints
## Risk Areas
## Next Step
```

## Loop Iteration template
```md
# Loop Iteration
## Trigger
## Failed Check
## Root Cause
## Fix Plan
## Applied Fix
## Verification
## Continue or Exit Loop
```

## Limits
- One bug = one change set. No scope expansion; a new finding becomes a new task.
- Commit/push/merge only on user request (contract 08). Security findings: mask, never print real values.
