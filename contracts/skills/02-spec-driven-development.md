# Contract 02 — Spec-Driven Development

## Purpose
A spec turns a vague request into testable, agreed-upon criteria before code is written.

## When applied
Before any non-trivial implementation (new feature, multi-file change, behavior change). Trivial edits skip it.

## Required
A spec (the **WHAT**, independent of code) must state:
- Problem / requirement.
- Business rules / domain rules.
- Acceptance criteria — each **testable** ("given X input, returns Y"; vague "should work" is banned) and labelled with an id (`AC1`, `AC2`, …) that plan tasks cite.
- Edge cases — empty/null, boundaries, conflicts, authorization, error paths.
- Definition of done.
- Must-not-change behaviors (regression surface).

**Prompt-driven skills** (`agentic-sdlc-pipeline`, `feature-build`, `root-cause-fix`, `spec-authoring`): `spec-plan-author` drafts the spec and a fresh `spec-plan-critic` checks it (the `spec-plan-draft` workflow, or the runtime's author -> critic -> revise adapter); a saved spec passes `validate_artifacts.py --mode spec --strict`. The pipeline, `feature-build` and `root-cause-fix` always save it to `docs/agentic-sdlc/specs/<work_id>.md`: their flow hooks look for it before the first source edit, and `implementation-control` resolves it.

**Runner flows (`scripts/sdlc.py`) only:** the spec follows the intent step: the user's request, the context and a short `design.md` (intent, non-goals, approaches, decisions `D<n>`, each marked `(user)` or `(author's call: <reason>)`). The main loop writes the spec in the spec and full flows, and in the feature flow when the run was started with the spec option. Every criterion names its source as `(source: request)`, `(source: D<n>)`, `(source: Q<n>)` or `(source: F<n>)`, so a reader can see who asked for it; `F<n>` is the user's change request at the gate, the reject record whose `seq` is n in `feedback.jsonl`. One fresh reader, a builder who has only `design.md` and the spec, returns the questions it would need answered; each is settled as answered, minor (an author's call) or theirs (the user's answer). The spec is approved at its own gate (`spec-review`). The runner's spec/plan loop (`spec-plan-author`, a fresh `spec-plan-critic`, `spec-plan-draft`) is an opt-in path (contract 03). Record the spec as a markdown file when the work is substantial.

## Spec-less plan
In a runner flow (`scripts/sdlc.py`), a bugfix, a feature run without the spec option and a plan run with no imported spec need no spec. Their plan carries `spec: none` and its flow (`flow: bugfix`, `flow: feature` or `flow: plan`) in its frontmatter, and its own `## Acceptance Criteria` section before the first task. Those criteria follow the rules above: testable, with `AC<n>` ids that the tasks cite. In a feature or plan flow each criterion names its source, `(source: request)`, `(source: D<n>)` or, for a change the user asked for at the plan gate, `(source: F<n>)`. A bugfix plan also states the bug in a `## Bug` section (expected, actual, reproduction) before the first task, and its criteria carry no sources: the bug report is the source. `spec: none` is valid only together with one of those three flows.

Outside the runner, only a standalone `plan-authoring` plan whose WHAT has no saved spec file takes this form, with `flow: plan`. The pipeline, `feature-build` and `root-cause-fix` never write a spec-less plan.

## Forbidden
- Large implementation without a spec, except a plan under the spec-less plan section.
- Leaking the **HOW** (files/tasks/code) into the spec — that belongs in the plan (contract 03).
- Unfalsifiable acceptance criteria.

## Checklist
- [ ] Problem + business rules stated.
- [ ] Every acceptance criterion is testable and has an `AC<n>` id.
- [ ] Edge cases enumerated.
- [ ] Must-not-change behaviors listed.
- [ ] Spec stays code-independent.
