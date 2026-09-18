# Contract 08 — Git Safety

## Purpose
Prevent accidental, destructive, or secret-leaking git operations.

## When applied
Before any git operation; before finalizing a change set.

## Required
- **Commit / push / merge only on explicit user request.** Never automatic.
- Work on a feature branch; keep `main` / `master` clean.
- Before committing: run `git status` + `git diff`, confirm **only intended files** changed, scan the diff for secrets.
- Propose a clear commit message tied to the task; let the user commit.
- Run the read-only git-safety-check command as the pre-commit gate.
  Claude Code example: /agentic-sdlc:git-safety-check (Codex exposes the converted command as a skill).

## Forbidden
- Auto-committing or auto-pushing.
- Destructive operations on `main`/`master` (force-push, reset --hard, direct risky writes).
- Committing secrets/tokens/connection strings/keys (mask + report instead).
- Adding a Claude co-author trailer unless the user asks.
- `git add -A` / blanket staging without reviewing what it includes.

## Checklist
- [ ] `git status` + `git diff` reviewed.
- [ ] Only intended files changed.
- [ ] No secrets in the diff.
- [ ] Correct branch (not main/master).
- [ ] Tests run; results shown.
- [ ] User approved the commit/push.
