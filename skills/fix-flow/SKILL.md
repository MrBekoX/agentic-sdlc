---
name: fix-flow
description: Main workflow for fixing a bug, error, broken behavior, failing test, production issue, or any user-reported problem. Use when something is wrong and needs a root-cause fix delivered through spec → plan → TDD → security → verification. Technology-agnostic.
argument-hint: "<bug description or issue id>"
---

# Skill: fix-flow

> **Argument:** `/fix-flow $ARGUMENTS` — if `$ARGUMENTS` is given, that is the target bug/issue; otherwise ask the user what the problem is. Reply in Turkish.

The primary fix workflow. Resolves a problem at its **root cause**, with the smallest change, verified by tests and a double security pass, and audited before the final answer. It is a **gated, looped** flow — don't skip steps; a red gate means go back, not forward.

## Orchestration (consult first)
Before heavy/independent/parallelizable steps, the **`orchestration`** skill chooses the mechanism (main loop / sub-agent / dynamic-workflow / agent-team). Delegate heavy root-cause exploration and multi-lens verification; don't run everything serially in the main loop.

## Flow (with gates)

### 1. Issue / Bug Analysis
State: what is the bug; expected behavior; actual behavior; how to reproduce; affected files; risky areas. If it can't be reproduced, say so explicitly.

### 2. Context Gathering
Read the relevant code, tests, logs, and config. Check for prior patches/refactors in the area. (If heavy/independent → delegate to a **sub-agent**; intermediate reads stay in its context.)

### 3. Spec (the WHAT — code-independent) — rule 02
Problem definition · acceptance criteria (each testable) · edge cases · definition of done · **must-not-change behaviors**. For deep specs use `spec-plan-author` → `spec-plan-critic` (workflow `spec-plan-draft`).
**Gate:** spec exists and criteria are testable.

### 4. Plan (the HOW) — rule 03
Break into small single-purpose tasks; each maps to acceptance criteria, each is testable; name files + TDD points; flag risky steps; request approval if the fix is large/architectural.
**Gate:** every acceptance criterion has a task.

### 5. Goal lock — built-in `/goal`
Run the built-in **`/goal`** with a measurable end-state (e.g. *"the failing test in X passes, full suite green, no other behavior changed"*). This locks scope and keeps a fresh evaluator checking the condition each turn, preventing scope creep. (If `/goal` is unavailable, do it manually: restate the goal, lock scope, re-confirm acceptance criteria, list non-goals.) Use the **Goal Lock** template below.

### 6. TDD / Regression test (RED) — rule 05
Write a failing test that reproduces the bug. **Confirm it actually fails** (show output) before writing any fix.

### 7. Implementation (GREEN)
Minimal code to pass the test. Only files in plan scope. No unrelated refactor, no scope-creep, don't break the architecture, justify any new abstraction.

### 8. Test Run
Run the targeted test, then the full suite where feasible. **Show real output.**
**Loop A — test fail:** analyze → fix → retest. Manage with built-in **`/loop`** (or manually) using the **Loop Iteration** template. Don't proceed while red.

### 9. Security Analysis (#1) — rule 06
Review the diff: input validation, auth/authorization (incl. IDOR), secret leakage, injection, race conditions, data-loss risk, permission issues, dependency risk. Mask any secret (`***MASKED***`).
**Loop B — finding:** fix → re-run security analysis → re-run tests.

### 10. Refactor — rule 07
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
- **Test fail** → analyze → fix → retest (`/loop`).
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
- Commit/push/merge only on user request (rule 08). Security findings: mask, never print real values.
