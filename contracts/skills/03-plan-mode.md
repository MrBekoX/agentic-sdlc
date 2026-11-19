# Contract 03 — Plan Before Code

## Purpose
Separate planning from implementation so you don't build the wrong thing. The plan is the **HOW**.

## When applied
For any change that is multi-file, architectural, or in unfamiliar code. Skip for changes you could describe as a one-sentence diff.

**Prompt-driven skills** (`agentic-sdlc-pipeline`, `feature-build`, `root-cause-fix`, `plan-authoring`): `spec-plan-author` drafts the plan and a fresh `spec-plan-critic` checks it (the `spec-plan-draft` workflow, or the runtime's author -> critic -> revise adapter); every task cites the approved spec's criteria, and the saved plan passes `validate_artifacts.py --mode plan --strict`. Only a standalone `plan-authoring` plan whose WHAT has no saved spec file is spec-less and cites its own criteria (contract 02).

**Runner flows (`scripts/sdlc.py`) only:** the main loop writes the plan. With an approved spec, every task cites the spec's criteria. Without one (a bugfix, a feature run without the spec option, a plan run with no imported spec), the plan carries its own `## Acceptance Criteria` section before the first task and is stamped `spec: none` with its flow (contract 02, spec-less plan); a bugfix plan also carries `## Bug`. The plan is approved at its own gate (`plan-review`), so the default feature flow has one gate and the full flow has two, the spec's and the plan's; the light form has no reader and no gate. The runner's joint spec/plan loop (`spec+plan`: both drafted by `spec-plan-author`, checked by a fresh critic, one review gate together) is an opt-in path.

## Required
- Use plan mode for non-trivial work; if it goes sideways, **stop and re-plan** instead of pushing.
- A plan maps **every acceptance criterion → at least one task**.
- Tasks are small, single-purpose, independently compilable/testable, ordered by dependency.
- Each task names concrete files (Create/Modify) and TDD points (which failing test first).
- Mark risky steps, rollback approach, and where user approval is needed.
- Draft with `spec-plan-author` and check with a fresh `spec-plan-critic` (workflow `spec-plan-draft`): required in the prompt-driven skills, opt-in in a runner flow (`scripts/sdlc.py`).
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
