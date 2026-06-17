---
name: spec-flow
description: Use when the user asks only for a spec, acceptance criteria, requirements contract, or WHAT document without asking for a plan or implementation; routes unclear design intent to mind-spark and uses spec-plan-draft in spec mode.
argument-hint: "<thing to specify>"
---

# Skill: spec-flow

> **Argument:** `/spec-flow $ARGUMENTS` - if given, that is the target spec; otherwise infer from the latest user prompt. Match the user's language.

Own the WHAT only: problem, business rules, acceptance criteria, edge cases, definition of done, and must-not-change behavior. Do not write an implementation plan and do not edit product code.

## Route First

- If the design intent is ambiguous, use `mind-spark` first and turn the approved design into the spec input.
- If the user asks for HOW, tasks, implementation steps, or sequencing, use `plan-flow` instead.
- If the user asks to build, fix, test, secure, and finalize end-to-end, return to `using-agentic-sdlc` routing and escalate to `dev-flow` when the full envelope is needed.

## Flow

1. Identify the target behavior, audience, constraints, and explicit non-goals from the prompt and available context.
2. Read only the local context needed to avoid an off-target spec.
3. Invoke the named workflow `spec-plan-draft` with `mode:"spec"` and non-empty context. In Claude Code, use the Workflow tool. In Codex or a degraded runtime, draft manually and state that workflow invocation was unavailable.
4. If a durable artifact is requested or the work is substantial, save the spec as `docs/specs/<name>.md`.
5. Validate saved specs with `python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_artifacts.py" --mode spec --file docs/specs/<name>.md` when that path is available. In Codex plugin contexts, use the equivalent `${PLUGIN_ROOT}` path if needed.
6. Present decision points and stop. Do not continue to plan or implementation unless the user asks.

## Output

Return:

1. Spec summary.
2. Spec body or saved path.
3. Decision points, if any.
4. Evidence: context read, workflow/degraded path, and validator result if saved.

## Red Flags

- Producing HOW/tasks in a spec-only request.
- Implementing code or writing tests.
- Generating a generic spec without concrete context.
- Treating an ambiguous idea as specified instead of routing to `mind-spark`.
