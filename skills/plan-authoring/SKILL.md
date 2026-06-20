---
name: plan-authoring
description: Use first in any language when the user asks only for an implementation plan, task breakdown, HOW document, sequencing, ordered steps, or verification/TDD points without writing code, including no-direct-fix prompts and underspecified plan-only prompts. Activate before asking for missing bug details or clarification; not for spec-only, test-only, code implementation, or ambiguous design exploration.
---

# Skill: plan-authoring

> **Argument:** `/plan-authoring $ARGUMENTS` - if given, that is the target plan; otherwise infer from the latest user prompt. Match the user's language.

## Invariant
A plan maps every acceptance criterion to a small, testable task — HOW, not new WHAT.

Own the HOW only: implementation tasks, ordering, affected surfaces, TDD points, verification, risks, and acceptance-criteria mapping. Do not edit product code.

This is a standalone entry skill. `agentic-sdlc-pipeline` owns its own end-to-end Plan phase and must not call `plan-authoring` as an internal substep.

## Runtime Bindings

- **Hook:** `session-start.mjs` injects `using-agentic-sdlc` as the session-local router. That hook may route directly to `plan-authoring` for HOW-only prompts; this does not require `agentic-sdlc-pipeline`.
- **Contracts:** Apply the runtime-local contract files as the primary behavior contract:
  - Claude Code: `${CLAUDE_PLUGIN_ROOT}/contracts/skills/03-plan-mode.md`
  - Codex: `${PLUGIN_ROOT}/contracts/skills/03-plan-mode.md`
  Use `02-spec-driven-development.md` from the same runtime root only as the source-WHAT coverage contract; do not rewrite the spec.
- **Agents:** Use `spec-plan-draft` only when the runtime exposes the named Claude Code Workflow. In Codex (the other supported runtime) or a degraded runtime, run the author -> critic -> revise adapter with `spec-plan-author` and `spec-plan-critic` role instructions manually or through available subagents, then state the adapter path used.
- **Validator:** Saved plans use the runtime-local validator with `--mode plan`:
  - Claude Code: `${CLAUDE_PLUGIN_ROOT}/scripts/validate_artifacts.py`
  - Codex: `${PLUGIN_ROOT}/scripts/validate_artifacts.py`

## Route First

- If a HOW-only prompt is underspecified, stay in `plan-authoring` and ask for the missing WHAT, ticket, bug details, or acceptance criteria here; do not defer activation until after clarification.
- If there is no approved spec, ticket, or clear WHAT, use `spec-authoring` first or ask for the missing behavior contract.
- If the user is still exploring direction, use `mind-spark` before spec or plan work.
- If the user asks to execute the plan, return to `using-agentic-sdlc` routing. Use `agentic-sdlc-pipeline` only for full-envelope end-to-end implementation; otherwise use the focused implementation skill such as `feature-build`, `root-cause-fix`, `safe-refactor`, or `test-authoring`.

## Flow

1. Locate the approved spec, ticket, design, or explicit WHAT in the current session or files.
2. Refuse to invent missing behavior. If the WHAT is absent or contradictory, stop and ask for clarification or route to `spec-authoring`.
3. Use `spec-plan-draft` only when the runtime exposes the named Claude Code Workflow. In Codex (the other supported runtime) or a degraded runtime, run the author -> critic -> revise adapter with `spec-plan-author` and `spec-plan-critic` role instructions manually or through available subagents, then state the adapter path used.
4. If a durable artifact is requested or the work is substantial, save the plan as `docs/plans/<name>.md`.
5. Validate saved plans with `python "<runtime-root>/scripts/validate_artifacts.py" --mode plan --file docs/plans/<name>.md --spec docs/specs/<name>.md --strict`, resolving `<runtime-root>` from the active runtime as described in `docs/runtime-adapter.md`.
6. Present open decisions and stop. Do not implement unless the user asks.

## Output

Return:

1. Plan summary.
2. Task breakdown or saved path.
3. Acceptance-criteria mapping.
4. Verification plan.
5. Evidence: source WHAT, contract(s) applied, workflow/degraded path, agent bindings, and validator result if saved.

## Tripwires

- Planning without a clear WHAT.
- Editing code, tests, docs, or config as part of plan-only work.
- Escalating to `agentic-sdlc-pipeline` just because a plan exists.
- Continuing from plan to implementation without a fresh routing decision.
- Rewriting spec content instead of mapping the approved WHAT to implementation tasks.
