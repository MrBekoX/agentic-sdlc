# feature-build — work-type core

Shared core for `feature-build` work. Two entry points read this file: the standalone `feature-build` skill, and `agentic-sdlc-pipeline` Steps 8–13 for this work type. It holds only what both need — the depth rules and the implementation steps. The caller owns the envelope: the mechanism decision, spec and plan, scope lock, approval, the final audit, and the final report.

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

## Core steps
1. **Failing test** (contract 05) — identify the project's available test command, write the smallest test for the requested behavior and run it; show RED caused by the missing behavior before implementation. A missing runner does not authorize installing packages: use an already available equivalent that executes the intended tests, or report the prerequisite for approval. Preserve failure exit status; a fallback runner must exit nonzero when an assertion fails, not catch failures and return success.
2. **Implementation + verification** — follow the existing architecture and conventions; only files in scope; justify new abstractions. Write interdependent code in the main loop, delegate independent fixed-pattern pieces. Make the RED test GREEN, then run the suite and show output. Use the runtime loop tool when available; otherwise record each fail -> fix -> retest cycle with command evidence.
3. **Security analysis** (contract 06) — validation, authN/authZ (IDOR), secrets, injection, dependency risk, logging hygiene. Fix→re-check→retest on findings.
4. **Refactor** (contract 07) — only if needed; behavior unchanged; retest after.
5. **Documentation** (contract 09) — update stale docs, env vars, API signatures, setup.
