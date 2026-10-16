# root-cause-fix — work-type core

Shared core for `root-cause-fix` work. Two entry points read this file: the standalone `root-cause-fix` skill, and `agentic-sdlc-pipeline` Steps 8–13 for this work type. It holds only what both need — the depth rules and the implementation steps. The caller owns the envelope: the mechanism decision, spec and plan, scope lock, approval, the final audit, and the final report.

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

## Core steps
1. **TDD / Regression test (RED)** (contract 05) — Write a failing test that reproduces the bug. **Confirm it actually fails** (show output) before writing any fix.
2. **Implementation (GREEN)** — Minimal code to pass the test. Only files in plan scope. No unrelated refactor, no scope-creep, don't break the architecture, justify any new abstraction.
3. **Test Run** — Run the targeted test, then the full suite where feasible. **Show real output.**
   **Loop A — test fail:** analyze → fix → retest. Use the runtime loop tool when available; otherwise record each fail -> fix -> retest cycle with the Loop Iteration template and command evidence. Don't proceed while red.
4. **Security Analysis (#1)** (contract 06) — Review the diff: input validation, auth/authorization (incl. IDOR), secret leakage, injection, race conditions, data-loss risk, permission issues, dependency risk. Mask any secret (`***MASKED***`).
   **Loop B — finding:** fix → re-run security analysis → re-run tests.
5. **Refactor** (contract 07) — Only necessary cleanup; behavior unchanged; improve readability, reduce duplication/complexity.
6. **Retest** — Re-run the full suite after refactor; **show output**. (Loop A applies again if red.)
7. **Final Review** — Review `git diff`: summarize changed files, remaining risks, anything left open. Confirm only intended files changed and no secrets are present.

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
