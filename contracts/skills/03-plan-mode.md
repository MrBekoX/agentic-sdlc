# Contract 03 — Plan Before Code

## Purpose
Separate planning from implementation so you don't build the wrong thing. The plan is the **HOW**.

## When applied
For any change that is multi-file, architectural, or in unfamiliar code. Skip for changes you could describe as a one-sentence diff.

The plan comes from the spec. In the joint loop (`spec+plan`), the plan is drafted from that round's spec draft, a fresh critic checks both artifacts and the fit between them, and both go to one review gate together (in the gated form; the light form has no review gate). A plan-only flow starts from an approved spec. A bugfix plan has no spec: its own `## Bug` and `## Acceptance Criteria` sections, before the first task, take the spec's place (contract 02, bugfix exception).

## Required
- Use plan mode for non-trivial work; if it goes sideways, **stop and re-plan** instead of pushing.
- A plan maps **every acceptance criterion → at least one task**.
- Tasks are small, single-purpose, independently compilable/testable, ordered by dependency.
- Each task names concrete files (Create/Modify) and TDD points (which failing test first).
- Mark risky steps, rollback approach, and where user approval is needed.
- For deeper plans the spec/plan loop drafts with `spec-plan-author` and checks with a fresh `spec-plan-critic` (workflow `spec-plan-draft`).
- Optionally lock the plan with the built-in **`/goal`** so a fresh evaluator keeps you on the agreed end-state across turns.

## Forbidden
- Changing code without a plan for non-trivial work.
- Tasks that bundle several problems.
- Coverage gaps (an acceptance criterion with no task).
- Silent scope expansion mid-plan — a new finding becomes a new task, not a bigger diff.

## Checklist
- [ ] Each acceptance criterion maps to a task.
- [ ] Tasks are small, ordered, single-purpose.
- [ ] Files + TDD points named per task.
- [ ] Risky steps + rollback noted.
- [ ] Approval obtained where required.
