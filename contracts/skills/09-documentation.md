# Contract 09 — Documentation

## Purpose
Keep just enough documentation accurate and useful — no more.

## When applied
When behavior, public APIs, setup, or architecture decisions change; when asked for docs.

## Required
- Update docs that the change makes stale (README setup, API signatures, env vars, runbooks).
- Document **why** for non-obvious decisions; link to deeper material instead of duplicating it.
- Keep code comments about intent ("why"), not restating the code ("what").
- Record significant architecture decisions as short ADRs when applicable.

## Forbidden
- Leaving documented behavior contradicting actual behavior.
- Auto-generating verbose READMEs the user didn't ask for.
- Duplicating reference docs that live elsewhere (link instead).
- Comments that just paraphrase the code.

## Checklist
- [ ] Stale docs touched by this change updated.
- [ ] Non-obvious decisions explained (why).
- [ ] No contradiction between docs and behavior.
- [ ] No unrequested doc bloat.
