---
name: safe-refactor
description: This skill should be used first before answering or asking which module when the user asks to refactor, restructure, clean up, simplify, improve readability/maintainability, reduce duplication, or change architecture without changing behavior. Includes characterization tests and approval for broad scope; do not use for bug fixes, new features, or test-only work.
argument-hint: "<target module/area>"
---

# Skill: safe-refactor

> **Argument:** `/safe-refactor $ARGUMENTS`. Match the user's language. Governing contract: 07.

Improves structure while **preserving behavior**.

## Orchestration (consult first)
Per **`dispatch-strategy`** and `docs/runtime-adapter.md`: large multi-file refactors fan out to a dynamic-workflow or runtime equivalent (worktree isolation for parallel edits when available); heavy reference analysis goes to a subagent or documented degraded path.

## Flow
1. **Characterize current behavior** — identify the behavior that must not change. If tests don't cover it, **add characterization tests first** and see them pass (show output). This is the safety net.
2. **Define scope** — what is being restructured and what is explicitly out of scope. Use the runtime goal tool when available; otherwise write the Goal Lock template inline and treat it as the scope lock.
3. **Approval gate** — for large/architectural refactors, get user approval before starting.
4. **Small steps** — one structural change at a time (extract, rename, dedupe, simplify). After **each** step run the relevant tests and **show output**. Use the runtime loop tool when available; otherwise record each fail -> fix -> retest cycle with command evidence.
5. **No behavior change** — if a "refactor" alters behavior, stop: that is a feature/fix, not a refactor.
6. **Security re-check** (contract 06) if the refactor touches auth/config/data paths.
7. **Implementation control** — run **`implementasyon-control`** before finalizing.

## Final Response
What was restructured · files changed · proof behavior is unchanged (tests green before & after, with output) · remaining risks.

## Forbidden
- Refactoring without a passing-test safety net.
- Mixing behavior changes into the refactor.
- Large architectural change without approval.
- Drive-by refactors bundled into unrelated work.
