---
name: refactor-flow
description: Generic workflow for refactoring code without changing behavior — secure behavior with tests first, then improve structure in small verified steps. Use for readability/maintainability/duplication cleanup or restructuring. Get approval for large architectural refactors.
argument-hint: "<target module/area>"
---

# Skill: refactor-flow

> **Argument:** `/refactor-flow $ARGUMENTS`. Reply in Turkish. Governing rule: 07.

Improves structure while **preserving behavior**.

## Orchestration (consult first)
Per **`orchestration`**: large multi-file refactors fan out to a **dynamic-workflow** (worktree isolation for parallel edits); heavy reference analysis goes to a **sub-agent**.

## Flow
1. **Characterize current behavior** — identify the behavior that must not change. If tests don't cover it, **add characterization tests first** and see them pass (show output). This is the safety net.
2. **Define scope** — what is being restructured and what is explicitly out of scope. Lock it (optionally built-in `/goal`).
3. **Approval gate** — for large/architectural refactors, get user approval before starting.
4. **Small steps** — one structural change at a time (extract, rename, dedupe, simplify). After **each** step run the relevant tests and **show output**. Loop fail→fix→retest with `/loop`.
5. **No behavior change** — if a "refactor" alters behavior, stop: that is a feature/fix, not a refactor.
6. **Security re-check** (rule 06) if the refactor touches auth/config/data paths.
7. **Implementation control** — run **`implementasyon-control`** before finalizing.

## Final Response
What was restructured · files changed · proof behavior is unchanged (tests green before & after, with output) · remaining risks.

## Forbidden
- Refactoring without a passing-test safety net.
- Mixing behavior changes into the refactor.
- Large architectural change without approval.
- Drive-by refactors bundled into unrelated work.
