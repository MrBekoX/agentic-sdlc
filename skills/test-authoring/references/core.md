# test-authoring — work-type core

Shared core for `test-authoring` work. Two entry points read this file: the standalone `test-authoring` skill, and `agentic-sdlc-pipeline` Steps 8–13 for this work type. It holds only what both need — the depth rules and the implementation steps. The caller owns the envelope: the mechanism decision, spec and plan, scope lock, approval, the final audit, and the final report.

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

## Core steps
1. Identify what behavior needs proving and at which level (unit/integration/regression/e2e).
2. Write the test; step 3 shows how to prove it can fail.
3. Make the test pass without changing production behavior. For a test of existing behavior, show it fail under a temporary mutation of the code it guards, then revert the mutation; for a characterization test, capture the baseline. If the test exposes a real production defect, stop and report it as bug-fix work instead of changing production code here.
4. Run targeted tests, then the suite; show output. Use the runtime loop tool when available; otherwise record each fail -> fix -> retest cycle with command evidence.
5. Review: are the assertions meaningful? Edge cases covered? Any flaky timing/order dependence?

## Test types
- **Unit** — one unit in isolation; fast; dependencies faked.
- **Integration** — real collaboration across components/boundaries (DB, queue, HTTP).
- **Regression** — reproduces a past bug so it can't return.
- **E2E** — user-facing flow through the whole system.

## Principles
- **TDD:** a test is proven by watching it fail for the reason it guards — a failing run for new expectations, or a temporary mutation for existing behavior — before it passes. Production code is not changed in test-only work.
- **Arrange / Act / Assert**; one clear reason to fail per test.
- **Descriptive names** stating scenario + expectation (e.g. `returns_401_when_token_expired`).
- **Test doubles:** prefer real objects; use mock/fake/stub only at true boundaries. Assert **behavior**, not the mock.
- **Meaningful coverage:** a test that can't fail for a real reason is noise. Cover edge cases — empty/null, boundaries, error paths, authorization.
- Prefer the smallest scope that proves the behavior; run the full suite before claiming done.
- **Always show real test output.**

## Forbidden
- "Passed" without output.
- Changing production code in test-only work.
- Assertion-free tests, or tests asserting mocks instead of behavior.
- Over-mocking that turns the test into a tautology.
