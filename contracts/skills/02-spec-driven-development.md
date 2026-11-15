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

For deeper specs, the spec/plan loop drafts the spec with `spec-plan-author` and checks it with a fresh `spec-plan-critic` (workflow `spec-plan-draft`). In a feature flow the same loop drafts the plan from the spec, and both go to one review gate in the gated form (contract 03). Record the spec as a markdown file when the work is substantial.

## Bugfix exception
A bugfix needs no spec. Its plan carries `flow: bugfix` and `spec: none` in its frontmatter, states the bug in a `## Bug` section (expected, actual, reproduction) and its criteria in its own `## Acceptance Criteria` section, both before the first task. Those criteria follow the rules above: testable, with `AC<n>` ids that the tasks cite. `spec: none` is valid only together with `flow: bugfix`.

## Forbidden
- Large implementation without a spec, except a bugfix plan under the bugfix exception.
- Leaking the **HOW** (files/tasks/code) into the spec — that belongs in the plan (contract 03).
- Unfalsifiable acceptance criteria.

## Checklist
- [ ] Problem + business rules stated.
- [ ] Every acceptance criterion is testable and has an `AC<n>` id.
- [ ] Edge cases enumerated.
- [ ] Must-not-change behaviors listed.
- [ ] Spec stays code-independent.
