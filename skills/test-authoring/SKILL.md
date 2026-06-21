---
name: test-authoring
description: Use first in any language to write, add, repair, or design tests before inspecting code for test-only prompts covering unit, integration, regression, e2e, flaky/failing tests, meaningful assertions, coverage, test doubles, or test strategy. Test-only work that must not change production behavior; not for features, fixes, or refactors.
---

# Skill: test-authoring

> **Argument:** `/test-authoring $ARGUMENTS`. Match the user's language. Governing contract: 05.

Designs and writes meaningful tests, or repairs broken ones.

## Invariant
A test that has never failed proves nothing — each test must be able to fail for the reason it guards.

## Tripwires
- wrote the test green-first without ever seeing it fail
- asserting on implementation details instead of behavior
- coverage went up but no behavior is actually pinned

## Proof
Each new test shown failing for the right reason before it passes; for characterization tests, the captured baseline.

## Excuse → check
| Excuse | Check |
|---|---|
| "It obviously tests X." | Break X and watch the test fail — that is the only proof it tests X. |
| "Coverage is 100%." | Coverage is lines executed, not regressions caught. Assert behavior. |

## Depth contract (proportional — scale rigor to the change)
Scale the suite to the surface under test: a pure helper needs less than an auth path, but every test you do write must pin something real.
- Each test names the specific behaviour it guards **and** the concrete code mutation (flipped comparison, dropped branch, off-by-one) that would turn it red. If no mutation makes it fail, it pins nothing — delete or rewrite it.
- An edge case is a concrete input, not the phrase "edge cases": the empty/null value, the boundary value on both sides, the actual error or unauthorized path. Name the input.
- Assert the observable outcome the caller sees — the returned value, the raised error, the persisted state — not that a collaborator was invoked. A test that checks `mock.called` describes the test's own scaffolding.
- Show the failing run before the passing one; for characterization tests, capture the baseline first.

## Excuse -> check
| Excuse | Check |
|---|---|
| "The happy path is covered, good enough." | Name the boundary or error input that has no failing test yet, then add it. |
| "The mock returns X, so it works." | Assert the outcome the caller observes, not that the mock was called. |
| "I'll mark the edge cases later." | Write the concrete input now — empty, null, the boundary — or it never gets pinned. |

## No placeholders
Do not ship "covers edge cases" without listing each one as a concrete input. Do not ship a test name that fails to state scenario + expectation (`test_works` names nothing). Do not assert on a mock/spy in place of the behaviour the caller observes.

## Shallow example (reject this)
A test named `test_works` whose body asserts only `mock.called` pins nothing — flip any real logic and it still passes. Reject it: name the behaviour, name the input that would break it, and watch it go red first.

## Orchestration — fan out coverage analysis, you coordinate (consult `dispatch-strategy` first)
For a broad suite across several behavior-areas or modules, dispatch **one `test-engineer` per area in a single message** to analyze coverage gaps and judge whether existing tests pin real behavior — read-only, concurrent. You (main loop) stay the **coordinator**: merge the gap reports, prioritize, decide what to write. Writing/repairing the tests stays serial in the main loop (or worktree-isolated for a large multi-file pass) — never two agents on one file.
- **Degrade:** a single small target, or running inside a delegated sub-agent (no nesting), or a runtime without parallel agents → analyze in the main loop and flag `Delegation Degraded: parallel specialists unavailable`.

## Test types
- **Unit** — one unit in isolation; fast; dependencies faked.
- **Integration** — real collaboration across components/boundaries (DB, queue, HTTP).
- **Regression** — reproduces a past bug so it can't return.
- **E2E** — user-facing flow through the whole system.

## Principles
- **TDD:** failing test first (RED) → see it fail → minimal code (GREEN). For a bug, reproduce it with a test before fixing.
- **Arrange / Act / Assert**; one clear reason to fail per test.
- **Descriptive names** stating scenario + expectation (e.g. `returns_401_when_token_expired`).
- **Test doubles:** prefer real objects; use mock/fake/stub only at true boundaries. Assert **behavior**, not the mock.
- **Meaningful coverage:** a test that can't fail for a real reason is noise. Cover edge cases — empty/null, boundaries, error paths, authorization.
- Prefer the smallest scope that proves the behavior; run the full suite before claiming done.
- **Always show real test output.**

## Flow
1. Identify what behavior needs proving and at which level (unit/integration/regression/e2e).
2. Write the failing test; confirm it fails for the right reason.
3. Implement (or fix) the minimum to pass.
4. Run targeted tests, then the suite; show output. Use the runtime loop tool when available; otherwise record each fail -> fix -> retest cycle with command evidence.
5. Review: are the assertions meaningful? Edge cases covered? Any flaky timing/order dependence?

## Forbidden
- "Passed" without output.
- Implementation before the failing test for new behavior.
- Assertion-free tests, or tests asserting mocks instead of behavior.
- Over-mocking that turns the test into a tautology.
