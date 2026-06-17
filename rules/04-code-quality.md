# Rule 04 — Code Quality

## Purpose
Keep changes simple, surgical, and consistent with the codebase.

## When applied
Whenever writing or editing code.

## Required
- Minimum code that solves the problem; match surrounding style and conventions.
- Clear, intention-revealing names. Handle real error paths.
- Every changed line should trace directly to the request.
- Remove imports/variables/functions **your** change orphaned.
- Justify any new abstraction with a real, present need.

## Forbidden
- Speculative features, configurability, or flexibility that wasn't asked for.
- Abstractions for single-use code; error handling for impossible scenarios.
- "Improving" adjacent code, comments, or formatting unrelated to the task.
- Refactoring things that aren't broken (do that via `refactor-flow` with approval).
- Deleting pre-existing dead code unless asked — mention it instead.
- Duplicating what a linter/formatter enforces deterministically.

## Checklist
- [ ] Could this be meaningfully shorter/simpler?
- [ ] Does every changed line trace to the request?
- [ ] Names clear; error paths handled?
- [ ] No unrelated edits in the diff?
- [ ] New abstractions justified?
