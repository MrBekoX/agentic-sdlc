---
description: Read-only pre-commit git safety check (status, diff, log, secret scan). Never commits or pushes.
allowed-tools: ["Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Read", "Grep"]
---

# git-safety-check — Git Safety Check

> **Read-only** only. Never commits or pushes. Governing contract: 08. Match the user's language.

## Commands
```bash
git status
git diff --stat
git diff
git log --oneline -n 10
```

## Secret scan (read-only)
Check staged changes for leaks:
```bash
git diff --cached | grep -nEi "password=|secret|api[_-]?key|connection[_ ]?string|bearer |token|-----BEGIN" # agentic-sdlc:allow-secret
```
- On a suspicious match: **do not print the real value** — mask it and report `file:line` + risk type.

## Pre-commit checklist
1. Did **only the intended** files change? (any unexpected file?)
2. No secret / token / connection-string leak?
3. Were build/test commands run, and results shown?
4. Is the change focused on **one problem**?
5. Correct branch (not `main` / `master`)?
6. Is the commit message clear? *(Never commit without user approval — only propose.)*

## Note
Commit/push happen **only on user request** — never automatically (contract 08).
