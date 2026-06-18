---
name: feature-build
description: Use first in any language to add a new feature, endpoint, screen, or capability without the full agentic-sdlc-pipeline envelope, via implementation-control. Not for bug/root-cause fixes, test-only work, or behavior-preserving refactors.
---

# Skill: feature-build

> **Argument:** `/feature-build $ARGUMENTS` — if given, that is the target feature; otherwise ask. Match the user's language.

Builds a new feature in small, reversible, convention-respecting steps.

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
