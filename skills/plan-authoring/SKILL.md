---
name: plan-authoring
description: This skill should be used first in any language when the user asks only for an implementation plan, task breakdown, HOW document, sequencing, ordered steps, or verification/TDD points without writing code, including no-direct-fix prompts and underspecified plan-only prompts. It applies before asking for missing bug details or clarification; not for spec-only, test-only, code implementation, or ambiguous design exploration.
---

# Skill: plan-authoring

> **Argument:** `/plan-authoring $ARGUMENTS` - if given, that is the target plan; otherwise infer from the latest user prompt. Match the user's language.

## Invariant
A plan maps every acceptance criterion to a small, testable task — HOW, not new WHAT.

Own the HOW only: implementation tasks, ordering, affected surfaces, TDD points, verification, risks, and acceptance-criteria mapping. Do not edit product code.

This is a standalone entry skill. `agentic-sdlc-pipeline` owns its own end-to-end Plan phase and must not call `plan-authoring` as an internal substep.

## Depth contract (proportional)
Every task carries: the exact files (Create/Modify), a RED test point (concrete name + what it asserts), and a runnable verification (the command to run and the expected pass/fail). No "Non-task step" deferrals — security and audit are real tasks with their own verification, or they are explicitly out of scope with a reason.

## Excuse -> check
| Excuse | Check |
|---|---|
| "Security/audit happens later in the gates." | Then it is a task with a command, not a deferral. Name what runs and what proves it. |
| "Each task is obvious." | Then give its exact command and expected output; obvious tasks are the cheapest to make concrete. |
| "Compiles, so it works." | Compiling is not the verification. State the test that exercises the behaviour. |

## No placeholders
Ban "Non-task step", "as appropriate", and tasks with no runnable verification. A task a reviewer cannot run is not a task.

## Runtime Bindings

- **Hook:** on Claude Code, Codex and ZCode the SessionStart hook (`session-start.mjs`, `session-start-codex.mjs`) injects `using-agentic-sdlc` as the session-local router; Kimi Code selects it through `sessionStart.skill`; Grok CLI has no startup router. The router may route directly to `plan-authoring` for HOW-only prompts; this does not require `agentic-sdlc-pipeline`.
- **Plugin root (`<runtime-root>`):** the installed agentic-sdlc folder, two levels above this `SKILL.md` (`<runtime-root>/skills/<name>/SKILL.md`) — never the user's working directory. Claude Code substitutes `${CLAUDE_PLUGIN_ROOT}`; Claude Code and ZCode substitute `${CLAUDE_SKILL_DIR}/../..`; Kimi Code substitutes `${KIMI_SKILL_DIR}/../..`; a SessionStart line `Plugin root (resolved by this hook…)` names it on Claude Code, Codex and ZCode; Codex and Grok CLI show this skill's absolute path in the skill listing. A `${…}` token still shown literally is unresolved: never pass it to a shell. Confirm `<runtime-root>/scripts/validate_artifacts.py` exists and write that absolute path, quoted for your shell, into commands; if it cannot be confirmed, stop the step and report `plugin root unresolved` — never run a same-named file from the user's project. Run helpers with `python3` (Python 3.8+), or `py -3` on Windows when `python3` is missing or is the Microsoft Store alias.
- **Contracts:** Apply `<runtime-root>/contracts/skills/03-plan-mode.md` as the primary behavior contract. Use `02-spec-driven-development.md` from the same folder only as the source-WHAT coverage contract; do not rewrite the spec.
- **Agents:** Use `spec-plan-draft` when the runtime exposes the named loop. Claude Code: the named `Workflow` `agentic-sdlc:spec-plan-draft` with `args:{mode:"plan", context:<approved spec>, pluginRoot:"<runtime-root>"}`. Grok CLI (experimental adapter): `/workflow spec-plan-draft` or the `workflow` tool with name `spec-plan-draft` and args `{mode:"plan", context:<approved spec>}` when `.grok/workflows/spec-plan-draft.rhai` is in the catalog — do not call Claude JS `Workflow`. If Grok workflows are disabled or that script is not in the catalog, use `spawn_subagent` author (`spec-plan-author`) -> critic (`spec-plan-critic`) -> revise (up to 2 rounds until the critic returns clean, then present the **revised** draft and residual decision points). In Codex (the other supported runtime) or any other degraded runtime, run that same author -> critic -> revise adapter. The critic pass is **mandatory and must run in a fresh context** (a separate subagent/specialist) wherever the runtime exposes one; a same-context inline critic is a **degraded** path that must be flagged `Delegation Degraded: fresh-context critic unavailable` and held to extra scrutiny — never presented as an equal substitute. State the adapter path used.
- **Validator:** Saved plans use `<runtime-root>/scripts/validate_artifacts.py` with `--mode plan`.

## Route First

- If a HOW-only prompt is underspecified, stay in `plan-authoring` and ask for the missing WHAT, ticket, bug details, or acceptance criteria here; do not defer activation until after clarification.
- If there is no approved spec, ticket, or clear WHAT, use `spec-authoring` first or ask for the missing behavior contract.
- If the user is still exploring direction, use `mind-spark` before spec or plan work.
- If the user asks to execute the plan, return to `using-agentic-sdlc` routing. Use `agentic-sdlc-pipeline` only for full-envelope end-to-end implementation; otherwise use the focused implementation skill such as `feature-build`, `root-cause-fix`, `safe-refactor`, or `test-authoring`.

## Flow

1. Locate the approved spec, ticket, design, or explicit WHAT in the current session or files.
2. Refuse to invent missing behavior. If the WHAT is absent or contradictory, stop and ask for clarification or route to `spec-authoring`.
3. Use `spec-plan-draft` when the runtime exposes the named loop (Claude Code `Workflow` `agentic-sdlc:spec-plan-draft`; Grok CLI `/workflow spec-plan-draft` or the `workflow` tool with name `spec-plan-draft`). In Codex or when the named Grok catalog script is unavailable, run the author (`spec-plan-author`) -> critic (`spec-plan-critic`) -> revise adapter (loop author->critic->revise for up to 2 rounds until the critic returns clean, then present the **revised** draft and any residual decision points — never stop at the critic's first findings; feed them back and revise before presenting). The critic pass is **mandatory and must run in a fresh context** (a separate subagent/specialist) wherever the runtime exposes one; a same-context inline critic is a **degraded** path that must be flagged `Delegation Degraded: fresh-context critic unavailable` and held to extra scrutiny — never presented as an equal substitute. State the adapter path used. Do not call Claude JS `Workflow` on Grok.
4. If a durable artifact is requested or the work is substantial, save the plan as `docs/agentic-sdlc/plans/<work_id>.md` with `work_id`, `spec`, `branch`, and `status` frontmatter.
5. Validate saved plans with `python3 "<runtime-root>/scripts/validate_artifacts.py" --mode plan --file docs/agentic-sdlc/plans/<work_id>.md --spec docs/agentic-sdlc/specs/<work_id>.md --strict`, resolving `<runtime-root>` as described under **Plugin root** above.
6. Present open decisions and stop. Do not implement unless the user asks.

## Output

Return:

1. Plan summary.
2. Task breakdown or saved path.
3. Acceptance-criteria mapping.
4. Verification plan.
5. Evidence: source WHAT, contract(s) applied, workflow/degraded path, agent bindings, and validator result if saved.

## Artifact layouts

Plans resolve in two layouts: the legacy flat `docs/agentic-sdlc/plans/<id>.md` (back-compat) and the per-package canonical `docs/agentic-sdlc/<slug>/{spec,plan,evidence}/<work_id>.md`, where `<slug>` is lowercase kebab-case `^[a-z0-9][a-z0-9-]{0,63}$` and never a reserved name (`specs`, `plans`, `evidence`, `notes`, `spec`, `plan`). Save to whichever layout the work package uses; the resolver discovers both.

## Tripwires

- Planning without a clear WHAT.
- Editing code, tests, docs, or config as part of plan-only work.
- Escalating to `agentic-sdlc-pipeline` just because a plan exists.
- Continuing from plan to implementation without a fresh routing decision.
- Rewriting spec content instead of mapping the approved WHAT to implementation tasks.
