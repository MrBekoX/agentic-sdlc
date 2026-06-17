---
name: spec-flow
description: Use when the user asks only for a spec, acceptance criteria, requirements contract, or WHAT document without asking for a plan or implementation; routes unclear design intent to mind-spark and uses spec-plan-draft in spec mode.
argument-hint: "<thing to specify>"
---

# Skill: spec-flow

> **Argument:** `/spec-flow $ARGUMENTS` - if given, that is the target spec; otherwise infer from the latest user prompt. Match the user's language.

Own the WHAT only: problem, business rules, acceptance criteria, edge cases, definition of done, and must-not-change behavior. Do not write an implementation plan and do not edit product code.

This is a standalone entry skill. `dev-flow` owns its own end-to-end Spec phase and must not call `spec-flow` as an internal substep.

## Runtime Bindings

- **Hook:** `session-start.mjs` injects `using-agentic-sdlc` as the session-local router. That hook may route directly to `spec-flow` for WHAT-only prompts; this does not require `dev-flow`.
- **Contracts:** Apply the runtime-local contract files as the primary behavior contract:
  - Claude Code: `${CLAUDE_PLUGIN_ROOT}/contracts/skills/02-spec-driven-development.md`
  - Codex: `${PLUGIN_ROOT}/contracts/skills/02-spec-driven-development.md`
  Also use `00-global-behavior.md` and `01-context-first.md` from the same runtime root for evidence and context discipline when available.
- **Agents:** `spec-plan-draft` calls `spec-plan-author` to draft and `spec-plan-critic` to audit the spec. If the workflow/agent runtime is unavailable, draft manually in the main loop and explicitly mark the degraded path.
- **Validator:** Saved specs use the runtime-local validator with `--mode spec`:
  - Claude Code: `${CLAUDE_PLUGIN_ROOT}/scripts/validate_artifacts.py`
  - Codex: `${PLUGIN_ROOT}/scripts/validate_artifacts.py`

## Route First

- If the design intent is ambiguous, use `mind-spark` first and turn the approved design into the spec input.
- If the user asks for HOW, tasks, implementation steps, or sequencing, use `plan-flow` instead.
- If the user asks to build, fix, test, secure, and finalize end-to-end, return to `using-agentic-sdlc` routing and escalate to `dev-flow` only when the full envelope is needed.

## Flow

1. Identify the target behavior, audience, constraints, and explicit non-goals from the prompt and available context.
2. Read only the local context needed to avoid an off-target spec.
3. Invoke the named workflow `spec-plan-draft` with `mode:"spec"` and non-empty context. In Claude Code, use the Workflow tool. In Codex or a degraded runtime, draft manually and state that workflow invocation was unavailable.
4. If a durable artifact is requested or the work is substantial, save the spec as `docs/specs/<name>.md`.
5. Validate saved specs with `python "<runtime-root>/scripts/validate_artifacts.py" --mode spec --file docs/specs/<name>.md`, resolving `<runtime-root>` as `${CLAUDE_PLUGIN_ROOT}` in Claude Code and `${PLUGIN_ROOT}` in Codex.
6. Present decision points and stop. Do not continue to plan or implementation unless the user asks.

## Output

Return:

1. Spec summary.
2. Spec body or saved path.
3. Decision points, if any.
4. Evidence: context read, contract(s) applied, workflow/degraded path, agent bindings, and validator result if saved.

## Red Flags

- Producing HOW/tasks in a spec-only request.
- Implementing code or writing tests.
- Generating a generic spec without concrete context.
- Treating an ambiguous idea as specified instead of routing to `mind-spark`.
- Escalating to `dev-flow` without an implementation or end-to-end prompt.
