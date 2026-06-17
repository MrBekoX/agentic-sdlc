---
name: spec-authoring
description: This skill should be used first before answering or asking clarifying questions when the user explicitly asks only to write or extract a spec, acceptance criteria, requirements contract, WHAT document, problem/business rules/edge cases/definition of done, or a behavior-change requirements summary such as "problem ... definition of done cikar"; do not use for implementation task breakdown, HOW, plan, sequencing, code, tests, execution, or ambiguous design/brainstorming prompts like "nasil olmali" or "birlikte netlestirelim" unless a spec/requirements artifact is explicitly requested.
argument-hint: "<thing to specify>"
---

# Skill: spec-authoring

> **Argument:** `/spec-authoring $ARGUMENTS` - if given, that is the target spec; otherwise infer from the latest user prompt. Match the user's language.

Own the WHAT only: problem, business rules, acceptance criteria, edge cases, definition of done, and must-not-change behavior. Do not write an implementation plan and do not edit product code.

This is a standalone entry skill. `agentic-sdlc-pipeline` owns its own end-to-end Spec phase and must not call `spec-authoring` as an internal substep.

## Runtime Bindings

- **Hook:** `session-start.mjs` injects `using-agentic-sdlc` as the session-local router. That hook may route directly to `spec-authoring` for WHAT-only prompts; this does not require `agentic-sdlc-pipeline`.
- **Contracts:** Apply the runtime-local contract files as the primary behavior contract:
  - Claude Code: `${CLAUDE_PLUGIN_ROOT}/contracts/skills/02-spec-driven-development.md`
  - Codex: `${PLUGIN_ROOT}/contracts/skills/02-spec-driven-development.md`
  - OpenCode/Kimi Code: configured plugin or skill root.
  Also use `00-global-behavior.md` and `01-context-first.md` from the same runtime root for evidence and context discipline when available.
- **Agents:** Use `spec-plan-draft` only when the runtime exposes the named Claude Code Workflow. In Codex, OpenCode, Kimi Code, or a degraded runtime, run the author -> critic -> revise adapter with `spec-plan-author` and `spec-plan-critic` role instructions manually or through available subagents, then state the adapter path used.
- **Validator:** Saved specs use the runtime-local validator with `--mode spec`:
  - Claude Code: `${CLAUDE_PLUGIN_ROOT}/scripts/validate_artifacts.py`
  - Codex: `${PLUGIN_ROOT}/scripts/validate_artifacts.py`
  - OpenCode/Kimi Code: `<runtime-root>/scripts/validate_artifacts.py`

## Route First

- If the design intent is ambiguous, use `mind-spark` first and turn the approved design into the spec input.
- If the user asks to extract problem, business rules, edge cases, or definition of done but the target behavior is missing, stay in `spec-authoring` and ask for the missing behavior/change context before drafting.
- If the user asks for HOW, tasks, implementation steps, or sequencing, use `plan-authoring` instead.
- If the user asks to build, fix, test, secure, and finalize end-to-end, return to `using-agentic-sdlc` routing and escalate to `agentic-sdlc-pipeline` only when the full envelope is needed.

## Flow

1. Identify the target behavior, audience, constraints, and explicit non-goals from the prompt and available context.
2. Read only the local context needed to avoid an off-target spec.
3. Use `spec-plan-draft` only when the runtime exposes the named Claude Code Workflow. In Codex, OpenCode, Kimi Code, or a degraded runtime, run the author -> critic -> revise adapter with `spec-plan-author` and `spec-plan-critic` role instructions manually or through available subagents, then state the adapter path used.
4. If a durable artifact is requested or the work is substantial, save the spec as `docs/specs/<name>.md`.
5. Validate saved specs with `python "<runtime-root>/scripts/validate_artifacts.py" --mode spec --file docs/specs/<name>.md`, resolving `<runtime-root>` from the active runtime as described in `docs/runtime-adapter.md`.
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
- Escalating to `agentic-sdlc-pipeline` without an implementation or end-to-end prompt.
