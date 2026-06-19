---
name: using-agentic-sdlc
description: Use first in any language for meta-routing of explicit AGENTIC-SDLC routing questions, quoted prompts asking which project skill owns the work, or session-local scope shifts. Routes to the smallest sufficient skill and escalates to agentic-sdlc-pipeline only for full SDLC; evidence-before-claim done/fixed/passing gates belong to completion-claim-gate.
---

<SUBAGENT-STOP>
If you were dispatched as a subagent for a bounded task, skip this bootstrap unless the task is explicitly about choosing AGENTIC-SDLC skills.
</SUBAGENT-STOP>

# Skill: using-agentic-sdlc

## Invariant
Every prompt is routed to the smallest sufficient skill before acting — agentic-sdlc-pipeline only for the full envelope.

This is the bootstrap router for the AGENTIC-SDLC skill system.

## Priority

1. User instructions and repository instructions are highest priority.
2. AGENTIC-SDLC skills guide how to do the work.
3. Default model behavior fills gaps only when no skill or instruction applies.

If a user instruction conflicts with a skill, follow the user instruction and state the trade-off when it affects safety, verification, or scope.

## Routing Rule

Before acting, ask which AGENTIC-SDLC skill owns the request.

Use the smallest skill that satisfies the user's current prompt.

Resolve conflicts by semantic intent before domain nouns. Do not rely on exact keywords or the prompt language.

- Any-language brainstorming, option exploration, or uncertain direction -> `mind-spark`, not generic `brainstorming` or an implementation skill.
- If another plugin exposes a same-purpose process skill, prefer the AGENTIC-SDLC skill listed here for AGENTIC-SDLC prompts; do not replace `mind-spark` with `superpowers:brainstorming`.
- Any-language plan-only, HOW, task breakdown, or no direct code/fix yet -> `plan-authoring`, even when the prompt mentions a bug, failing behavior, or fix.
- For any-language plan-only/HOW/no direct code or fix yet prompts, activate `plan-authoring` immediately; never ask for bug details first or say you will use `plan-authoring` after details arrive.
- Any-language end-to-end/full-envelope prompts that ask for spec, plan, TDD, security/audit, and release-readiness -> `agentic-sdlc-pipeline`, not `mind-spark`, even if they mention design or requirements.
- Any-language test-only requests about missing unit/regression/e2e tests, coverage, or test strategy -> `test-authoring`, before reading files.
- Any-language behavior-preserving refactor prompts about preserving behavior while cleaning up, simplifying, or restructuring -> `safe-refactor` before Glob/Read/file-existence checks; the selected skill owns missing-target clarification.
- Any-language received-review-feedback prompts about PR comments, reviewer comments, bot feedback, or CI review output -> `feedback-triage`, not a fresh `code-quality-review`.
- Any-language orchestration decision prompts comparing main loop, subagents, workflows, or agent-teams -> `dispatch-strategy` before answering. Do not choose a mechanism directly without activating the skill.
- Any-language final audit or process audit prompt asking whether spec/plan/TDD/security flow was followed before the final response -> `implementasyon-control`. Treat it as an active audit task now, not a passive session preference; the audit intent requires a Skill call even when no implementation evidence exists, then report missing evidence. Do not run `git diff`/`status`/`log` or read files first, and do not ask the user for branch/file/change details before activating — the skill's auditor inspects the diff; the Skill call is the first action.
- Any-language clear implementation prompts that ask to add, build, develop, apply, or implement a feature/endpoint -> `feature-build` unless they explicitly ask only for brainstorming/spec/plan/tests/review or ask for the full pipeline.
- For final audit/process audit prompts, activate `implementasyon-control` with the Skill tool; do not answer from memory or summarize without activation.
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
- Final implementation or process audit -> `implementasyon-control`.
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
- In Codex (the other supported runtime), follow activated skill instructions and the portable capability matrix in `docs/runtime-adapter.md`. Treat Claude Code Workflow-only gates as runtime-adapted: use subagents, parallel local tools, native agent mechanisms, or documented degraded main-loop execution as the skill specifies.
- Resolve plugin-root paths by runtime: `${CLAUDE_PLUGIN_ROOT}` in Claude Code, `${PLUGIN_ROOT}` in Codex. Use the matching runtime root for `contracts/skills/`, `scripts/`, `hooks/`, and bundled files.
- If a required skill or workflow mechanism is unavailable, state the degraded path and use the smallest safe fallback.
- Match the user's language unless they request otherwise.
