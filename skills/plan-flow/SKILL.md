---
name: plan-flow
description: Use when the user asks only for an implementation plan, task breakdown, HOW document, sequencing, or execution steps without asking to implement; requires an approved spec or clear WHAT and uses spec-plan-draft in plan mode.
argument-hint: "<thing to plan>"
---

# Skill: plan-flow

> **Argument:** `/plan-flow $ARGUMENTS` - if given, that is the target plan; otherwise infer from the latest user prompt. Match the user's language.

Own the HOW only: implementation tasks, ordering, affected surfaces, TDD points, verification, risks, and acceptance-criteria mapping. Do not edit product code.

## Runtime Bindings

- **Hook:** `session-start.mjs` injects `using-agentic-sdlc` as the session-local router. That hook may route directly to `plan-flow` for HOW-only prompts; this does not require `dev-flow`.
- **Contracts:** Apply `${CLAUDE_PLUGIN_ROOT}/contracts/skills/03-plan-mode.md` as the primary behavior contract. Use `${CLAUDE_PLUGIN_ROOT}/contracts/skills/02-spec-driven-development.md` only as the source-WHAT coverage contract; do not rewrite the spec.
- **Agents:** `spec-plan-draft` calls `spec-plan-author` to draft and `spec-plan-critic` to audit the plan. If the workflow/agent runtime is unavailable, draft manually in the main loop and explicitly mark the degraded path.
- **Validator:** Saved plans use `${CLAUDE_PLUGIN_ROOT}/scripts/validate_artifacts.py` with `--mode plan`.
- In Codex plugin contexts, resolve the same plugin-root paths with `${PLUGIN_ROOT}`.

## Route First

- If there is no approved spec, ticket, or clear WHAT, use `spec-flow` first or ask for the missing behavior contract.
- If the user is still exploring direction, use `mind-spark` before spec or plan work.
- If the user asks to execute the plan, return to `using-agentic-sdlc` routing. Use `dev-flow` only for full-envelope end-to-end implementation; otherwise use the focused implementation skill such as `feature-flow`, `fix-flow`, `refactor-flow`, or `test-flow`.

## Flow

1. Locate the approved spec, ticket, design, or explicit WHAT in the current session or files.
2. Refuse to invent missing behavior. If the WHAT is absent or contradictory, stop and ask for clarification or route to `spec-flow`.
3. Invoke the named workflow `spec-plan-draft` with `mode:"plan"` and the approved WHAT as non-empty context. In Claude Code, use the Workflow tool. In Codex or a degraded runtime, draft manually and state that workflow invocation was unavailable.
4. If a durable artifact is requested or the work is substantial, save the plan as `docs/plans/<name>.md`.
5. Validate saved plans with `python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_artifacts.py" --mode plan --file docs/plans/<name>.md --spec docs/specs/<name>.md --strict` when a spec file exists and that path is available. In Codex plugin contexts, use the equivalent `${PLUGIN_ROOT}` path if needed.
6. Present open decisions and stop. Do not implement unless the user asks.

## Output

Return:

1. Plan summary.
2. Task breakdown or saved path.
3. Acceptance-criteria mapping.
4. Verification plan.
5. Evidence: source WHAT, contract(s) applied, workflow/degraded path, agent bindings, and validator result if saved.

## Red Flags

- Planning without a clear WHAT.
- Editing code, tests, docs, or config as part of plan-only work.
- Escalating to `dev-flow` just because a plan exists.
- Continuing from plan to implementation without a fresh routing decision.
- Rewriting spec content instead of mapping the approved WHAT to implementation tasks.
