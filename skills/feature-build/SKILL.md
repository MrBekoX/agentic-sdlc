---
name: feature-build
description: Use first in any language to add a new feature, endpoint, screen, or capability without the full agentic-sdlc-pipeline envelope, via implementation-control. Not for bug/root-cause fixes, test-only work, or behavior-preserving refactors.
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

## Orchestration (consult first)
Per the **`dispatch-strategy`** skill and `docs/runtime-adapter.md`: delegate codebase scoping/exploration and fixed-pattern multi-file generation to subagents or runtime equivalents; fan out verification (test/lint/security lenses) to a dynamic-workflow or the runtime's parallel/degraded equivalent. Keep design/ordering decisions and interdependent code in the main loop.

## Flow
1. **Requirement analysis** — what the feature must do; who uses it; constraints.
2. **Scope map** — affected layers/files, existing signatures/conventions to follow, integration points. For multi-file features, fan this out with the runtime's workflow/subagent/parallel equivalent (don't scan serially in the main loop). Output feeds the spec.
3. **Spec** (contract 02) — business rules · acceptance criteria (testable) · edge cases · definition of done · must-not-change behaviors. Use `spec-plan-author` → `spec-plan-critic` for depth.
4. **Plan + approval** (contract 03) — small single-purpose tasks, each mapped to acceptance criteria, files + TDD points named. **Get user approval before big changes.** Use the runtime goal tool when available; otherwise write the Goal Lock template inline and treat it as the scope lock.
5. **Implementation** — follow the existing architecture and conventions; only files in scope; justify new abstractions. Write interdependent code in the main loop, delegate independent fixed-pattern pieces.
6. **Test** (contract 05) — TDD: failing test first (show RED), then code (GREEN); run suite, show output. Use the runtime loop tool when available; otherwise record each fail -> fix -> retest cycle with command evidence.
7. **Security analysis** (contract 06) — validation, authN/authZ (IDOR), secrets, injection, dependency risk, logging hygiene. Fix→re-check→retest on findings.
8. **Refactor** (contract 07) — only if needed; behavior unchanged; retest after.
9. **Documentation** (contract 09) — update stale docs, env vars, API signatures, setup.
10. **Implementation control** — run **`implementasyon-control`** before finalizing; complete any gap and re-run. Don't give the final answer if a critical step is missing.

## Final Response
What was built · files changed · tests run (with result) · security notes · remaining risks · user actions needed.

## Limits
- One feature = one task set. No unrelated refactor (contract 04).
- Adding packages / migrations / commit / push require user approval (contract 08).
