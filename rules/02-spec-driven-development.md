# Rule 02 — Spec-Driven Development

## Purpose
A spec turns a vague request into testable, agreed-upon criteria before code is written.

## When applied
Before any non-trivial implementation (new feature, multi-file change, behavior change). Trivial edits skip it.

## Required
A spec (the **WHAT**, independent of code) must state:
- Problem / requirement.
- Business rules / domain rules.
- Acceptance criteria — each **testable** ("given X input, returns Y"; vague "should work" is banned).
- Edge cases — empty/null, boundaries, conflicts, authorization, error paths.
- Definition of done.
- Must-not-change behaviors (regression surface).

For deeper specs, the `spec-plan-author` → `spec-plan-critic` loop (workflow `spec-plan-draft`) drafts and adversarially checks it; record the spec as a markdown file when the work is substantial.

## Forbidden
- Large implementation without a spec.
- Leaking the **HOW** (files/tasks/code) into the spec — that belongs in the plan (rule 03).
- Unfalsifiable acceptance criteria.

## Checklist
- [ ] Problem + business rules stated.
- [ ] Every acceptance criterion is testable.
- [ ] Edge cases enumerated.
- [ ] Must-not-change behaviors listed.
- [ ] Spec stays code-independent.
