---
name: feature-build
description: This skill should be used first when the user asks to add or build a new feature, endpoint, screen, flow, or capability and has not requested the full agentic-sdlc-pipeline SDLC envelope. Use for focused new functionality through implementation-control; do not use for bug/root-cause fixes, test-only work, behavior-preserving refactors, or explicit spec+plan+TDD+security+PR-ready agentic-sdlc-pipeline requests.
argument-hint: "<feature name or id>"
---

# Skill: feature-build

> **Argument:** `/feature-build $ARGUMENTS` — if given, that is the target feature; otherwise ask. Match the user's language.

Builds a new feature in small, reversible, convention-respecting steps.

## Orchestration (consult first)
Per the **`dispatch-strategy`** skill: delegate codebase scoping/exploration and fixed-pattern multi-file generation to **sub-agents**; fan out verification (test/lint/security lenses) to a **dynamic-workflow**. Keep design/ordering decisions and interdependent code in the main loop.

## Flow
1. **Requirement analysis** — what the feature must do; who uses it; constraints.
2. **Scope map** — affected layers/files, existing signatures/conventions to follow, integration points. For multi-file features, fan this out with a workflow/sub-agents (don't scan serially in the main loop). Output feeds the spec.
3. **Spec** (contract 02) — business rules · acceptance criteria (testable) · edge cases · definition of done · must-not-change behaviors. Use `spec-plan-author` → `spec-plan-critic` for depth.
4. **Plan + approval** (contract 03) — small single-purpose tasks, each mapped to acceptance criteria, files + TDD points named. **Get user approval before big changes.** Optionally lock with built-in `/goal`.
5. **Implementation** — follow the existing architecture and conventions; only files in scope; justify new abstractions. Write interdependent code in the main loop, delegate independent fixed-pattern pieces.
6. **Test** (contract 05) — TDD: failing test first (show RED), then code (GREEN); run suite, show output. Loop fail→fix→retest with `/loop`.
7. **Security analysis** (contract 06) — validation, authN/authZ (IDOR), secrets, injection, dependency risk, logging hygiene. Fix→re-check→retest on findings.
8. **Refactor** (contract 07) — only if needed; behavior unchanged; retest after.
9. **Documentation** (contract 09) — update stale docs, env vars, API signatures, setup.
10. **Implementation control** — run **`implementasyon-control`** before finalizing; complete any gap and re-run. Don't give the final answer if a critical step is missing.

## Final Response
What was built · files changed · tests run (with result) · security notes · remaining risks · user actions needed.

## Limits
- One feature = one task set. No unrelated refactor (contract 04).
- Adding packages / migrations / commit / push require user approval (contract 08).
