# Contract 10 — AI Agent Collaboration

## Purpose
Use delegation and orchestration so the main context stays clean and work parallelizes.

## When applied
When a task has independent/parallelizable parts, heavy exploration, multi-file generation, or multi-lens review.

## Required
- Let the **`orchestration`** skill choose the mechanism — it is the single decision authority.
- Mechanisms: **main loop** (interdependent code, design/ordering decisions, small single-file work); **sub-agent** (one independent piece: exploration, fixed-pattern multi-file generation, multi-file verification); **dynamic-workflow** (≈3+ similar verification/research/codegen, parallel via worktree isolation); **agent-team** (interactive multi-angle review — not in headless/CI).
- Keep intermediate work (reads, build output) inside the delegate; only the result returns to the main loop.
- Use a fresh-context reviewer (subagent / `code-review`) to check a diff the implementer just wrote.
- Use built-in **`/goal`** to hold a verifiable end-state across turns; built-in **`/loop`** to re-run on an interval.

## Forbidden
- Running independent/heavy work serially in the main loop and bloating context.
- Spinning up a workflow for a single check, or an agent-team for a simple handoff (use the smallest sufficient mechanism).
- Agent-team in headless/automated runs.

## Checklist
- [ ] Did `orchestration` pick the mechanism?
- [ ] Is heavy/independent work delegated, not inline?
- [ ] Smallest sufficient mechanism chosen?
- [ ] Fresh-context review used for the final diff?
