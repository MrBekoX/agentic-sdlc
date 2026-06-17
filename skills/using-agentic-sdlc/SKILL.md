---
name: using-agentic-sdlc
description: Use when starting any AGENTIC-SDLC session or before deciding which project skill should handle a request; acts as the session-local router that chooses the smallest sufficient skill, escalates to dev-flow only for full SDLC work, and enforces evidence-before-claim behavior.
---

<SUBAGENT-STOP>
If you were dispatched as a subagent for a bounded task, skip this bootstrap unless the task is explicitly about choosing AGENTIC-SDLC skills.
</SUBAGENT-STOP>

# Skill: using-agentic-sdlc

This is the bootstrap router for the AGENTIC-SDLC skill system.

## Priority

1. User instructions and repository instructions are highest priority.
2. AGENTIC-SDLC skills guide how to do the work.
3. Default model behavior fills gaps only when no skill or instruction applies.

If a user instruction conflicts with a skill, follow the user instruction and state the trade-off when it affects safety, verification, or scope.

## Routing Rule

Before acting, ask which AGENTIC-SDLC skill owns the request.

Use the smallest skill that satisfies the user's current prompt.

- Ambiguous idea, design, or build intent -> `mind-spark`.
- Spec, acceptance criteria, WHAT document, or requirements contract only -> `spec-flow`.
- Plan, task breakdown, HOW document, or implementation steps only -> `plan-flow`.
- New feature or endpoint implementation -> `feature-flow`.
- Bug, failing behavior, or production issue -> `fix-flow`.
- Behavior-preserving restructure -> `refactor-flow`.
- Test-only work or test strategy -> `test-flow`.
- Security audit -> `security-review`.
- Code/diff quality review -> `code-review`.
- Received review feedback -> `receiving-code-review`.
- Parallelism/delegation decision -> `orchestration`.
- Final implementation audit -> `implementasyon-control`.
- Any done/fixed/passing/ready claim -> `completion-claim-gate` first.

Escalate to `dev-flow` only when the user asks for end-to-end implementation or the work needs the full SDLC envelope: spec, plan, implementation, tests, security review, final audit, and release/PR readiness. High-risk areas such as auth, payment, database migration, API contract, permissions, user data, token/session, or RLS also qualify when implementation is requested.

If no project skill is needed, answer directly and keep the routing decision implicit.

## Session-Local Memory

Track routing state in the conversation, not in a persistent file.

For each new user prompt, re-evaluate:

1. Current intent: idea, spec, plan, implementation, test, review, audit, or final claim.
2. Active skill, if any, and whether the user is continuing or changing scope.
3. Existing artifacts mentioned in-session: approved design, spec path, plan path, test output, review findings.
4. Scope shift: whether a focused request has turned into implementation or release readiness.
5. Escalation signal: whether the next correct owner is now `dev-flow`.

Examples:

- User starts with "write a spec" -> `spec-flow`; later says "now implement it with tests and security review" -> escalate to `dev-flow`.
- User starts with "plan this change" -> `plan-flow`; later says "just write the tests" -> route to `test-flow`, not `dev-flow`.
- User starts with "add this feature" -> `feature-flow`; later asks for PR-ready end-to-end SDLC evidence -> escalate to `dev-flow`.

## Invocation Discipline

- Invoke relevant process skills before implementation skills.
- Do not inline another skill's checklist when the runtime can invoke that skill.
- `dev-flow` is the full-envelope escalation path, not the default route.
- Step skills should not call `dev-flow` unless the user is intentionally escalating to the full flow.
- `spec-flow` and `plan-flow` are standalone prompt-level routes. When `dev-flow` needs spec/plan artifacts, it uses its own phase logic; in Codex that means dev-flow's embedded author/critic adapter, not invoking the standalone spec/plan skills.
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
- In Codex, follow the activated skill instructions and use available tools directly. Treat Claude Code Workflow-only gates as runtime-adapted: use Codex subagents, parallel local tools, or documented degraded main-loop execution as the skill specifies.
- If a required skill or workflow mechanism is unavailable, state the degraded path and use the smallest safe fallback.
- Match the user's language unless they request otherwise.
