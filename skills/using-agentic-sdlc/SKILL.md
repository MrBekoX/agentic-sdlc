---
name: using-agentic-sdlc
description: This skill should be used first in any language for meta-routing of explicit AGENTIC-SDLC routing questions, quoted prompts asking which project skill owns the work, or session-local scope shifts. Routes to the smallest sufficient skill and escalates to agentic-sdlc-pipeline only for full SDLC; evidence-before-claim done/fixed/passing gates belong to completion-claim-gate.
---

<SUBAGENT-STOP>
If you were dispatched as a subagent for a bounded task, skip this bootstrap unless the task is explicitly about choosing AGENTIC-SDLC skills.
</SUBAGENT-STOP>

# Skill: using-agentic-sdlc

## Invariant
Every AGENTIC-SDLC-owned prompt is routed to the smallest sufficient skill before acting — agentic-sdlc-pipeline only for the full envelope.

This is the bootstrap router for the AGENTIC-SDLC skill system.

## Depth contract (proportional — scale rigor to the change)
Every route names the **semantic intent verb** that selects the skill — explore vs. specify vs. plan vs. implement vs. audit — not a surface noun or keyword the prompt happens to contain. State the intent, then pick the **smallest sufficient** skill and say in one clause why a larger envelope isn't needed (e.g. "fix-now intent, single behavior, no spec/plan artifact asked for -> root-cause-fix; full envelope not requested"). An escalation to `agentic-sdlc-pipeline` must name the **full-envelope signal** that triggered it — an end-to-end ask, or a high-risk surface (auth, payment, DB migration, API contract, permissions, user data, token/session, RLS) with implementation requested — not "this feels big". Scale the routing rationale to the ask: a one-line route for an obvious focused prompt, an explicit intent + scope read when the prompt mixes nouns and intents.

## Excuse -> check
| Excuse | Check |
|---|---|
| "It mentions a bug, route to root-cause-fix." | Check whether the ask is to FIX now or to PLAN/spec it — intent over nouns. A bug noun under plan-only intent is `plan-authoring`. |
| "Big task, use the pipeline." | Name the full-envelope signal (end-to-end ask or high-risk surface + implementation). Without it, route the smallest sufficient focused skill. |
| "Mentions security, so security-audit." | Is the intent to AUDIT now, or to spec/plan/build with a security dimension? Route the verb, not the topic word. |
| "Unclear, default to the pipeline." | `agentic-sdlc-pipeline` is the full-envelope escalation, never the fallback. If intent is unresolved, name the candidate verb or ask — don't default up. |

## No placeholders
No route chosen on a keyword alone — every route carries its intent verb. No escalation to `agentic-sdlc-pipeline` as a default or because the work "seems large" without a named full-envelope signal. No "probably `feature-build`" / "likely a plan" without the stated intent that selects it. If the intent is genuinely split, name the two candidate verbs and the smallest skill each implies, then resolve by the dominant intent — don't route to the bigger envelope to be safe.

## Priority

1. User instructions and repository instructions are highest priority.
2. AGENTIC-SDLC skills guide how to do the work.
3. Default model behavior fills gaps only when no skill or instruction applies.

If a user instruction conflicts with a skill, follow the user instruction and state the trade-off when it affects safety, verification, or scope.

## Process owner

When another plugin exposes a same-purpose process skill, choose one process owner per phase **before** applying the routes below:

1. Follow the user's explicit plugin or skill choice, including `superpowers:brainstorming` or any other `superpowers:<skill>`. An explicit AGENTIC-SDLC choice selects the matching house skill. A newer explicit choice overrides the established owner.
2. Otherwise keep the established owner for the current phase, including across resume/compact. Loading this router or a focused skill does not transfer ownership.
3. With no established owner, work entering this router defaults to AGENTIC-SDLC. State the owner briefly when overlap matters, and track it in conversation context rather than a persistent file.

For a Superpowers-owned phase, use that owner's skill and handoff and stop house routing here. Never stack both plugins' processes for the same phase, including a second completion checklist. Re-evaluate at a new phase or explicit user change. Runtime security hooks still apply independently of the process owner; permission and evidence requirements remain in force.

Load the selected owner's actual instructions before substantive phase content. After resume, compaction, or a supplied summary, reload the selected procedure now even if the summary says it already began: preserve its owner and saved progress, not an assumption that its instruction body survived. Invoke its `Skill` in Claude Code or read its catalog-resolved `SKILL.md` in Codex, then continue from saved progress without repeating completed approvals. Reuse an actual body already present only in uninterrupted context; otherwise load it. If unavailable, report the gap instead of reconstructing the procedure from memory.

Qualify every target by plugin, for example `agentic-sdlc:mind-spark` or `superpowers:brainstorming`. Claude Code passes that identifier to `Skill`. Codex CLI selects the matching plugin's entry through `/skills` or `$`; a qualified identity here is not invented CLI command syntax. If activation is unavailable, read the selected owner's catalog-resolved `SKILL.md` and record the degraded mechanism; for house skills absent from the catalog read `<runtime-root>/skills/<skill>/SKILL.md` (see **Plugin root** under Platform Notes). Kimi Code resolves bare skill names only (`mind-spark`, not `agentic-sdlc:mind-spark`). Bare house names below identify skills from this plugin only. If the chosen skill cannot be found, report the limitation instead of substituting the other owner.

Overlap map (intent overlap does not make these procedures interchangeable):

| Phase | AGENTIC-SDLC identifier | Superpowers identifier |
|---|---|---|
| Intent / design | `mind-spark` | `brainstorming` |
| WHAT / HOW | `spec-authoring` / `plan-authoring` | `brainstorming` (WHAT overlap) / `writing-plans` |
| Test-first implementation | `test-authoring` / `feature-build` | `test-driven-development` |
| Debugging | `root-cause-fix` | `systematic-debugging` |
| Change review | `code-quality-review` | `requesting-code-review` |
| Received feedback | `feedback-triage` | `receiving-code-review` |
| Completion evidence | `completion-claim-gate` | `verification-before-completion` |
| Routing | `using-agentic-sdlc` | `using-superpowers` |
| Delegation | `dispatch-strategy` | `dispatching-parallel-agents` |
| Skill authoring | `skill-authoring` | `writing-skills` |

## Routing Rule

After the process-owner check selects AGENTIC-SDLC, ask which house skill owns the request.

Use the smallest skill that satisfies the user's current prompt.

Resolve conflicts by semantic intent before domain nouns. Do not rely on exact keywords or the prompt language.

- Any-language brainstorming, option exploration, or uncertain direction -> `mind-spark`, not generic `brainstorming` or an implementation skill.
- Any-language plan-only, HOW, task breakdown, or no direct code/fix yet -> `plan-authoring`, even when the prompt mentions a bug, failing behavior, or fix.
- For any-language plan-only/HOW/no direct code or fix yet prompts, activate `plan-authoring` immediately; never ask for bug details first or say you will use `plan-authoring` after details arrive.
- Any-language end-to-end/full-envelope prompts that ask for spec, plan, TDD, security/audit, and release-readiness -> `agentic-sdlc-pipeline`, not `mind-spark`, even if they mention design or requirements.
- Any-language test-only requests about missing unit/regression/e2e tests, coverage, or test strategy -> `test-authoring`, before reading files.
- Any-language behavior-preserving refactor prompts about preserving behavior while cleaning up, simplifying, or restructuring -> `safe-refactor` before Glob/Read/file-existence checks; the selected skill owns missing-target clarification.
- Any-language received-review-feedback prompts about PR comments, reviewer comments, bot feedback, or CI review output -> `feedback-triage`, not a fresh `code-quality-review`.
- Any-language orchestration decision prompts comparing main loop, subagents, workflows, or agent-teams -> `dispatch-strategy` before answering. Do not choose a mechanism directly without activating the skill.
- Any-language final audit or process audit prompt asking whether spec/plan/TDD/security flow was followed before the final response -> `implementation-control`. Treat it as an active audit task now, not a passive session preference; in Claude Code the audit intent requires a Skill call even when no implementation evidence exists, then report missing evidence. Codex activates the qualified skill or reads its instructions through the runtime adapter. Do not run `git diff`/`status`/`log` or read unrelated files first, and do not ask the user for branch/file/change details before activating — the skill's auditor inspects the diff.
- Any-language clear implementation prompts that ask to add, build, develop, apply, or implement a feature/endpoint -> `feature-build` unless they explicitly ask only for brainstorming/spec/plan/tests/review or ask for the full pipeline.
- For final audit/process audit prompts, activate `implementation-control` with the runtime mechanism above; do not answer from memory or summarize without activation.
- Implementation skills apply when the user asks to change files, fix behavior, add a feature, refactor, or write tests now.
- If the selected focused skill is underspecified, invoke it anyway before clarifying. Do not defer activation by saying you will use the skill after the user provides details.

- Ambiguous idea, design, or build intent -> `mind-spark`.
- Spec, acceptance criteria, WHAT document, or requirements contract only -> `spec-authoring`.
- Plan, task breakdown, HOW document, or implementation steps only -> `plan-authoring`.
- New feature or endpoint implementation -> `feature-build`.
- Bug, failing behavior, or production issue -> `root-cause-fix`.
- Behavior-preserving restructure -> `safe-refactor`.
- Test-only work or test strategy -> `test-authoring`.
- Security audit -> `security-audit`.
- Code/diff quality review -> `code-quality-review`.
- Received review feedback -> `feedback-triage`.
- Parallelism/delegation decision -> `dispatch-strategy`.
- Final implementation or process audit -> `implementation-control`.
- Any done/fixed/passing/ready claim -> `completion-claim-gate` first.

Escalate to `agentic-sdlc-pipeline` only when the user asks for end-to-end implementation or the work needs the full SDLC envelope: spec, plan, implementation, tests, security review, final audit, and release/PR readiness. High-risk areas such as auth, payment, database migration, API contract, permissions, user data, token/session, or RLS also qualify when implementation is requested.

If no project skill is needed, answer directly and keep the routing decision implicit.

## Session-Local Memory

Track routing state in the conversation, not in a persistent file.

For each new user prompt, re-evaluate:

1. Current intent: idea, spec, plan, implementation, test, review, audit, or final claim.
2. Active skill, if any, and whether the user is continuing or changing scope.
3. Existing artifacts mentioned in-session: approved design, spec path, plan path, test output, review findings.
4. Scope shift: whether a focused request has turned into implementation or release readiness.
5. Escalation signal: whether the next correct owner is now `agentic-sdlc-pipeline`.

Examples:

- User starts with "write a spec" -> `spec-authoring`; later says "now implement it with tests and security review" -> escalate to `agentic-sdlc-pipeline`.
- User starts with "plan this change" -> `plan-authoring`; later says "just write the tests" -> route to `test-authoring`, not `agentic-sdlc-pipeline`.
- User starts with "add this feature" -> `feature-build`; later asks for PR-ready end-to-end SDLC evidence -> escalate to `agentic-sdlc-pipeline`.

## Invocation Discipline

- Invoke relevant process skills before implementation skills.
- Do not inline another skill's checklist when the runtime can invoke that skill.
- `agentic-sdlc-pipeline` is the full-envelope escalation path, not the default route.
- Step skills should not call `agentic-sdlc-pipeline` unless the user is intentionally escalating to the full flow.
- `spec-authoring` and `plan-authoring` are standalone prompt-level routes. When `agentic-sdlc-pipeline` needs spec/plan artifacts, it uses its own phase logic; in Codex that means agentic-sdlc-pipeline's embedded author/critic adapter, not invoking the standalone spec/plan skills.
- Use `contracts/skills/` as the durable behavior contract layer; skills remain the runnable procedure layer.

## Evidence Discipline

Never claim work is done, fixed, passing, ready, safe, or verified without fresh evidence.

Before such a claim:
1. Identify the command, diff, transcript, or observation that proves it.
2. Run or inspect it after the latest change.
3. Read the full result, including failures and skips.
4. Match the evidence to the exact words of the claim.
5. Then report the claim with the evidence.

If evidence is missing, say it is uncertain and state what would verify it.

## Platform Notes

- In Claude Code, use the native Skill/Workflow/Agent mechanisms when available.
- In Codex (the other supported runtime), follow activated skill instructions and the portable capability matrix in `<runtime-root>/docs/runtime-adapter.md`. Treat Claude Code Workflow-only gates as runtime-adapted: use subagents, parallel local tools, native agent mechanisms, or documented degraded main-loop execution as the skill specifies.
- In ZCode (experimental adapter), the `Skill` tool and qualified `agentic-sdlc:<skill>` ids work after the plugin is installed and enabled; `$<skill>` and `/` → Skills also invoke. Hook processes receive `${ZCODE_PLUGIN_ROOT}`; skill text gets `${CLAUDE_SKILL_DIR}` substituted, not a plugin-root variable. Mechanism mappings live in `<runtime-root>/docs/zcode-runtime-adapter.md`.
- In Kimi Code (experimental adapter), invoke skills by bare name with `/skill:<name>`; the manifest's `skillInstructions` map Claude tool names to Kimi ones. There is no Workflow runtime: run the author -> critic -> revise fallback with Kimi agents.
- In Grok CLI (experimental adapter), invoke named loops with `/workflow spec-plan-draft` (or `multi-lens-review` / `skill-draft`) or the `workflow` tool when `.grok/workflows/<name>.rhai` is in the project catalog. Do not call Claude JS `Workflow`. Plugin install does not deliver those scripts. If they are missing, use `spawn_subagent` plus the documented author -> critic -> revise fallback. Hook processes receive `${GROK_PLUGIN_ROOT}`; a model-chosen skill is read as plain text, so resolve the root from its listed path.
- In Cursor, invoke a skill with `/<skill-name>` or by reading its installed `SKILL.md`. There is no Claude Workflow tool: use the author -> critic -> revise adapter and the roles in `agents/`. The sessionStart hook prints the plugin root. Hook commands read `CURSOR_PLUGIN_ROOT` inside Node.
- **Plugin root (`<runtime-root>`):** the installed agentic-sdlc folder, two levels above this `SKILL.md` (`<runtime-root>/skills/<name>/SKILL.md`) — never the user's working directory. Claude Code substitutes `${CLAUDE_PLUGIN_ROOT}`; Claude Code and ZCode substitute `${CLAUDE_SKILL_DIR}/../..`; Kimi Code substitutes `${KIMI_SKILL_DIR}/../..`; a SessionStart line `Plugin root (resolved by this hook…)` names it on Claude Code, Codex, ZCode and Cursor; Codex and Grok CLI show this skill's absolute path in the skill listing. A `${…}` token still shown literally is unresolved: never pass it to a shell. Confirm `<runtime-root>/scripts/validate_artifacts.py` exists and write that absolute path, quoted for your shell, into commands; if it cannot be confirmed, stop the step and report `plugin root unresolved` — never run a same-named file from the user's project. Run helpers with `python3` (Python 3.8+), or `py -3` on Windows when `python3` is missing or is the Microsoft Store alias. Use it for `contracts/skills/`, `scripts/`, `hooks/` and other bundled files.
- If a required skill or workflow mechanism is unavailable, state the degraded path and use the smallest safe fallback.
- Match the user's language unless they request otherwise.
