# Rule 05 — Testing

## Purpose
Tests are the verification loop. They prove behavior and catch regressions.

## When applied
Whenever changing behavior or fixing a bug.

## Required
- **Test-first (TDD):** write a failing test (RED) that captures the intended behavior, confirm it fails, then write the minimal code to pass (GREEN).
- For a bug: write a test that reproduces it before fixing.
- Prefer the smallest relevant test scope for speed; run the full suite before claiming done.
- Use Arrange / Act / Assert; descriptive test names stating the scenario.
- Tests must be meaningful (assert real behavior), not coverage theater.
- **Show actual test output.** Never say "passed" without it.

## Forbidden
- Claiming success without running tests and showing output.
- Writing the implementation before the failing test for new behavior.
- Tests asserting nothing, or asserting mocks instead of behavior.
- Skipping a failing test or hiding that a step was skipped.

## Checklist
- [ ] Failing test written and seen to fail (RED).
- [ ] Minimal code makes it pass (GREEN).
- [ ] Edge cases covered.
- [ ] Full suite run; real output shown.
