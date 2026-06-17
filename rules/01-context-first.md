# Rule 01 — Context First

## Purpose
Avoid solving the wrong problem. Understand before you change.

## When applied
Before any edit, plan, or recommendation — especially in unfamiliar code.

## Required
- Read the files you intend to change **and** their callers/tests/config first.
- Identify existing conventions (naming, structure, error handling, test style) and follow them.
- For broad questions ("where/how is X done"), use a **subagent / Explore** so exploration doesn't bloat the main context.
- State what you learned (key files, architecture, constraints) before proposing a change.

## Forbidden
- Editing a file you haven't read in this session.
- Assuming an API/signature/behavior without checking the real code.
- Reading hundreds of files unscoped ("infinite exploration") in the main loop — scope it or delegate.

## Checklist
- [ ] Target file(s) read.
- [ ] Callers / tests / config that depend on it read.
- [ ] Existing conventions identified.
- [ ] Heavy exploration delegated to a subagent.
