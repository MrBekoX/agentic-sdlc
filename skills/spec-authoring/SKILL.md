---
name: spec-authoring
description: This skill should be used first in any language when the user asks only to write or extract a spec, acceptance criteria, requirements contract, WHAT document, or problem/business rules/edge cases/definition of done. Not for plan/HOW, code, tests, or ambiguous design exploration.
---

# Skill: spec-authoring

> **Argument:** `/spec-authoring $ARGUMENTS` - if given, that is the target spec; otherwise infer from the latest user prompt. Match the user's language.

## Invariant
A spec defines WHAT and its acceptance criteria, code-independent — and every criterion must be testable.

Own the WHAT only: problem, business rules, acceptance criteria, edge cases, definition of done, and must-not-change behavior. Do not write an implementation plan and do not edit product code.

This is a standalone entry skill. `agentic-sdlc-pipeline` owns its own end-to-end Spec phase and must not call `spec-authoring` as an internal substep.

## Depth contract (proportional — scale rigor to the change)
For each acceptance criterion give Given/When/Then **and** the failure it guards. For each edge case give the concrete unhandled scenario, not a category name. A security note must cite the input->sink it reasons about, or state "no external input reaches this code, because <reason>" — never a bare "safe".

## Excuse -> check
| Excuse | Check |
|---|---|
| "The criteria are obvious." | Then write them as Given/When/Then; obvious behaviour is the cheapest to make testable. |
| "Security is N/A here." | Then name the input that does NOT reach a sink and why — a one-line dismissal without that is a finding. |
| "It's a small change." | A small change gets a short spec, not a vague one. Short and concrete, never short and hand-wavy. |

## No placeholders
Do not ship "TBD", "as appropriate", "out of scope" (without the reason it's out), or a "decide later" section. If a decision is open, list it as a Decision Point with a recommendation.

## Shallow example (reject this)
A spec whose security section is only "treat as safe string handling only" and whose acceptance criteria are "should work" is shallow — it fills the sections without reasoning. Do not produce it.

## Runtime Bindings

- **Hook:** on Claude Code, Codex and ZCode the SessionStart hook (`session-start.mjs`, `session-start-codex.mjs`) injects `using-agentic-sdlc` as the session-local router; Kimi Code selects it through `sessionStart.skill`; Grok CLI has no startup router. The router may route directly to `spec-authoring` for WHAT-only prompts; this does not require `agentic-sdlc-pipeline`.
- **Plugin root (`<runtime-root>`):** the installed agentic-sdlc folder, two levels above this `SKILL.md` (`<runtime-root>/skills/<name>/SKILL.md`) — never the user's working directory. Claude Code substitutes `${CLAUDE_PLUGIN_ROOT}`; Claude Code and ZCode substitute `${CLAUDE_SKILL_DIR}/../..`; Kimi Code substitutes `${KIMI_SKILL_DIR}/../..`; a SessionStart line `Plugin root (resolved by this hook…)` names it on Claude Code, Codex and ZCode; Codex and Grok CLI show this skill's absolute path in the skill listing. A `${…}` token still shown literally is unresolved: never pass it to a shell. Confirm `<runtime-root>/scripts/validate_artifacts.py` exists and write that absolute path, quoted for your shell, into commands; if it cannot be confirmed, stop the step and report `plugin root unresolved` — never run a same-named file from the user's project. Run helpers with `python3` (Python 3.8+), or `py -3` on Windows when `python3` is missing or is the Microsoft Store alias.
- **Contracts:** Apply `<runtime-root>/contracts/skills/02-spec-driven-development.md` as the primary behavior contract. Also use `00-global-behavior.md` and `01-context-first.md` from the same folder for evidence and context discipline when available.
- **Agents:** Use `spec-plan-draft` when the runtime exposes the named loop. Claude Code: the named `Workflow` `agentic-sdlc:spec-plan-draft` with `args:{mode:"spec", context:<analysis + scope>, pluginRoot:"<runtime-root>"}`. Grok CLI (experimental adapter): `/workflow spec-plan-draft` or the `workflow` tool with name `spec-plan-draft` and args `{mode:"spec", context:<analysis + scope>}` when `.grok/workflows/spec-plan-draft.rhai` is in the catalog — do not call Claude JS `Workflow`. If Grok workflows are disabled or that script is not in the catalog, use `spawn_subagent` author (`spec-plan-author`) -> critic (`spec-plan-critic`) -> revise (up to 2 rounds until the critic returns clean, then present the **revised** draft and residual decision points). In Codex (the other supported runtime) or any other degraded runtime, run that same author -> critic -> revise adapter. The critic pass is **mandatory and must run in a fresh context** (a separate subagent/specialist) wherever the runtime exposes one; a same-context inline critic is a **degraded** path that must be flagged `Delegation Degraded: fresh-context critic unavailable` and held to extra scrutiny — never presented as an equal substitute. State the adapter path used.
- **Validator:** Saved specs use `<runtime-root>/scripts/validate_artifacts.py` with `--mode spec`.

## Route First

- If the design intent is ambiguous, use `mind-spark` first and turn the approved design into the spec input.
- If the user asks to extract problem, business rules, edge cases, or definition of done but the target behavior is missing, stay in `spec-authoring` and ask for the missing behavior/change context before drafting.
- If the user asks for HOW, tasks, implementation steps, or sequencing, use `plan-authoring` instead.
- If the user asks to build, fix, test, secure, and finalize end-to-end, return to `using-agentic-sdlc` routing and escalate to `agentic-sdlc-pipeline` only when the full envelope is needed.

## Flow

1. Identify the target behavior, audience, constraints, and explicit non-goals from the prompt and available context.
2. Read only the local context needed to avoid an off-target spec.
3. Use `spec-plan-draft` when the runtime exposes the named loop (Claude Code `Workflow` `agentic-sdlc:spec-plan-draft`; Grok CLI `/workflow spec-plan-draft` or the `workflow` tool with name `spec-plan-draft`). In Codex or when the named Grok catalog script is unavailable, run the author (`spec-plan-author`) -> critic (`spec-plan-critic`) -> revise adapter (loop author->critic->revise for up to 2 rounds until the critic returns clean, then present the **revised** draft and any residual decision points — never stop at the critic's first findings; feed them back and revise before presenting). The critic pass is **mandatory and must run in a fresh context** (a separate subagent/specialist) wherever the runtime exposes one; a same-context inline critic is a **degraded** path that must be flagged `Delegation Degraded: fresh-context critic unavailable` and held to extra scrutiny — never presented as an equal substitute. State the adapter path used. Do not call Claude JS `Workflow` on Grok.
4. If a durable artifact is requested or the work is substantial, save the spec as `docs/agentic-sdlc/specs/<work_id>.md` with `work_id` and `status` frontmatter.
5. Validate saved specs with `python3 "<runtime-root>/scripts/validate_artifacts.py" --mode spec --file docs/agentic-sdlc/specs/<work_id>.md`, resolving `<runtime-root>` as described under **Plugin root** above.
6. Present decision points and stop. Do not continue to plan or implementation unless the user asks.

## Output

Return:

1. Spec summary.
2. Spec body or saved path.
3. Decision points, if any.
4. Evidence: context read, contract(s) applied, workflow/degraded path, agent bindings, and validator result if saved.

## Artifact layouts

Specs resolve in two layouts: the legacy flat `docs/agentic-sdlc/specs/<id>.md` (back-compat) and the per-package canonical `docs/agentic-sdlc/<slug>/{spec,plan,evidence}/<work_id>.md`, where `<slug>` is lowercase kebab-case `^[a-z0-9][a-z0-9-]{0,63}$` and never a reserved name (`specs`, `plans`, `evidence`, `notes`, `spec`, `plan`). Save to whichever layout the work package uses; the resolver discovers both.

## Tripwires

- Producing HOW/tasks in a spec-only request.
- Implementing code or writing tests.
- Generating a generic spec without concrete context.
- Treating an ambiguous idea as specified instead of routing to `mind-spark`.
- Escalating to `agentic-sdlc-pipeline` without an implementation or end-to-end prompt.
