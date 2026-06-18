---
name: test-authoring
description: Use first in any language to write, add, repair, or design tests before inspecting code for test-only prompts covering unit, integration, regression, e2e, flaky/failing tests, meaningful assertions, coverage, test doubles, or test strategy. Test-only work that must not change production behavior; not for features, fixes, or refactors.
argument-hint: "<area or test target>"
---

# Skill: test-authoring

> **Argument:** `/test-authoring $ARGUMENTS`. Match the user's language. Governing contract: 05.

Designs and writes meaningful tests, or repairs broken ones.

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
