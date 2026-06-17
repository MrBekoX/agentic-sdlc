# Rule 07 — Refactoring

## Purpose
Improve structure without changing behavior — safely and reversibly.

## When applied
When code needs restructuring for readability/maintainability, or during step 9 of the default workflow.

## Required
- **Behavior must not change.** Secure current behavior with tests **first**; if coverage is missing, add characterization tests before refactoring.
- Proceed in small steps; run tests after each step and show output.
- Reduce duplication and unnecessary complexity; improve names and readability.
- Get user approval for large/architectural refactors before starting.

## Forbidden
- Refactoring without a passing test safety net.
- Mixing behavior changes into a refactor commit.
- Large architectural changes without approval.
- "Drive-by" refactors bundled into an unrelated task (rule 04).

## Checklist
- [ ] Tests green before refactor.
- [ ] Small, isolated steps.
- [ ] Tests green after each step (output shown).
- [ ] Behavior provably unchanged.
- [ ] Approval obtained for large refactors.
