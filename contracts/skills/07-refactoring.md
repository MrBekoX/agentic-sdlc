# Contract 07 — Refactoring

## Purpose
Improve structure without changing behavior — safely and reversibly.

## When applied
When code needs restructuring for readability/maintainability, or during the refactor step of a flow (the work-type core's refactor step; Step 12 of `agentic-sdlc-pipeline`).

## Required
- **Behavior must not change.** Secure current behavior with tests **first**; if coverage is missing, add characterization tests before refactoring.
- Proceed in small steps; run tests after each step and show output.
- Reduce duplication and unnecessary complexity; improve names and readability.
- Get user approval for large/architectural refactors before starting.

## Forbidden
- Refactoring without a passing test safety net.
- Mixing behavior changes into a refactor commit.
- Large architectural changes without approval.
- "Drive-by" refactors bundled into an unrelated task (contract 04).

## Checklist
- [ ] Tests green before refactor.
- [ ] Small, isolated steps.
- [ ] Tests green after each step (output shown).
- [ ] Behavior provably unchanged.
- [ ] Approval obtained for large refactors.
