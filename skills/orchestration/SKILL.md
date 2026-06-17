---
name: orchestration
description: Decide HOW to run a task before starting it — main loop, sub-agent, dynamic-workflow, or agent-team. MUST consult when work has 2+ independent parts, heavy codebase exploration, verification/research fan-out, multi-file generation, or multi-angle review/audit. The single decision authority other work-skills (fix-flow, feature-flow, refactor-flow, test-flow, security-review, code-review) reference at their fan-out gates. Technology-agnostic.
user-invocable: true
---

# Skill: orchestration (the mechanism-decision authority)

> Before any non-trivial work, this skill answers "how should I run this?" Other work-skills reference it at fan-out gates. **Goal:** run parallelizable work in parallel; delegate independent work so the main context stays clean; never do heavy independent work serially in the main loop.

## The four options

| Option | Use for | How to invoke | Cost / caveat |
|---|---|---|---|
| **Main loop** (no delegation) | Interdependent code, sequencing/design decisions, small single-file work, user dialogue | — (you do it directly) | Cheapest; but doing heavy/independent work here **bloats context** |
| **Sub-agent** | One well-defined **independent** piece: codebase exploration/research, "build from this spec and report", fixed-pattern multi-file generation, multi-file verification | `Agent` tool (use `isolation:"worktree"` / `run_in_background` when useful) | Medium; intermediate work **stays in the sub-agent's context**, only the result returns |
| **Dynamic-workflow** | Large parallelizable work: **verification, research, OR code** (≈3+ similar items; deterministic phases, adversarial cross-check, loop-until-done, pipeline). Parallel code writing via worktree isolation | `Workflow` tool (JS: `agent()`/`parallel()`/`pipeline()`; `isolation:"worktree"` for parallel writes) | High but amortized; runs in background, returns structured results |
| **Agent-team** | Continuous, **interactive**, collaborative parallel work: multi-angle review (security/perf/test), competing-hypothesis debugging, independent module ownership; peers talk, a live lead steers | Natural language: "set up an agent team with roles … " | **Most expensive**; needs interaction, **not for headless/CI**; requires the experimental teams flag + a recent Claude Code |

## Runtime adapter

- **Claude Code:** `Dynamic-workflow` means the native JavaScript Workflow runtime. Use it only when its scale/repeatability properties matter.
- **Codex:** there is no Claude Workflow tool. Map `Dynamic-workflow` decisions to Codex subagent fan-out, parallel local tool calls, cloud delegation for larger implementation milestones, or a sequential degraded path with a note. Do not invent a workflow script requirement in Codex.
- **Spec/plan inside dev-flow:** Claude Code uses `spec-plan-draft`; Codex uses dev-flow's embedded author/critic adapter. Standalone `spec-flow` and `plan-flow` remain prompt-level entry skills, not dev-flow substeps.

## Decision tree
1. Is it **interdependent code** or a design/sequencing decision? → **Main loop**. (But hand independent sub-parts — exploration, fixed-pattern generation — to a **sub-agent**.)
2. Is it **large-scale and parallelizable** (≈3+ similar items — verification, research, **or code**; deterministic phases / adversarial cross-check; worktree isolation for parallel writes)? → **Dynamic-workflow**.
3. Is it a **single independent piece** whose intermediate steps you don't need in the main context? → **Sub-agent**.
4. Is it **interactive, collaborative, continuous** parallel work where peers talking + a live lead add value? → **Agent-team**.

> **Context-bloat heuristic (always apply):** if a task will produce many intermediate tool-calls/reads/builds you won't need later → **delegate** (sub-agent or workflow). Don't do it serially in the main loop.

## Mandatory gates (contracts)
- **Delegation required:** an **independent** piece whose intermediate work you don't need to keep (exploration, reference analysis, N-file fixed-pattern generation, multi-file verification) → **sub-agent**. Doing it serially in the main loop is forbidden.
- **Fan-out required:** ≈3+ similar **verification/research** items → **dynamic-workflow** (don't do them one-by-one inline).
- **All three can write code:** sub-agent, workflow (worktree-isolated parallel), and agent-team all write code. Choose by the **shape of the work**, not by authority. Use worktree isolation to avoid collisions in parallel writes.
- **Smallest sufficient mechanism (YAGNI):** cost ladder **Main loop < Sub-agent < Dynamic-workflow < Agent-team**. Don't build a workflow for one task; don't open an agent-team for a simple handoff.
- **Agent-team only when interactive:** in headless/automated/cron runs use a workflow instead.

## Anti-patterns (avoid)
- Doing everything serially in the main loop → context bloats, quality degrades.
- A workflow for a single dependency/check (needless weight).
- Not delegating an independent exploration/generation and pumping dozens of intermediate steps into the main context.
- Agent-team in headless mode.

## Relationship to work-skills
- **fix-flow / feature-flow:** scope/exploration + fixed-pattern multi-file generation → **sub-agent**; verification fan-out (tests/lint/security lenses) → **dynamic-workflow**.
- **security-review:** multiple lenses (injection / authz-IDOR / secrets / auth) → **dynamic-workflow** (parallel lenses) or **agent-team** (interactive review).
- **code-review:** fresh-context **sub-agent** so the reviewer isn't the author.
- **refactor-flow / test-flow:** large multi-file passes → **dynamic-workflow**; heavy reference analysis → **sub-agent**.
- Spec/plan drafting in Claude Code flows → `spec-plan-draft` workflow (author → critic), not shallow main-loop writing.
- Spec/plan drafting inside Codex `dev-flow` → embedded author/critic adapter with a fresh-context subagent critic when available. Standalone `spec-flow` and `plan-flow` remain independent prompt routes.

## Quick mapping (example → mechanism)
| Work | Mechanism |
|---|---|
| Verify N library versions / docs | Dynamic-workflow (fan-out) |
| "Where/how is X done" in the codebase | Sub-agent |
| Analyze a reference repo / external source | Sub-agent |
| Generate N similar files from one clear spec | Sub-agent |
| 100+ file bulk migration (parallel, worktree) | Dynamic-workflow |
| Review a diff from 4 security lenses in parallel | Dynamic-workflow |
| test + lint + typecheck + secret-scan in parallel | Dynamic-workflow |
| Interactively review a PR for security/perf/test | Agent-team |
| Debug with competing hypotheses in parallel | Agent-team |
| Small single-file fix / design decision | Main loop |
