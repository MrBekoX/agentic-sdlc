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

## Orchestration (consult first)
Before heavy/independent/parallelizable steps, the **`dispatch-strategy`** skill chooses the mechanism (main loop / sub-agent / dynamic-workflow / agent-team) using `docs/runtime-adapter.md` for runtime-specific equivalents. Delegate heavy root-cause exploration and multi-lens verification; don't run everything serially in the main loop.

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

### 13. Implementation Control (mandatory) — run `implementasyon-control`
Trigger the **`implementasyon-control`** skill to audit that steps 1–12 were truly done.
**Loop C — control reports a gap:** complete the missing step → re-run `implementasyon-control`. **If a critical step is missing, do NOT give the final answer** — finish it or tell the user clearly.

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
