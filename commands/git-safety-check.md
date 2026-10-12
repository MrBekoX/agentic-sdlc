---
description: Read-only pre-commit git safety check (status, diff, log, secret scan). Never commits or pushes.
allowed-tools: ["Bash(git status)", "Bash(git diff --no-ext-diff --no-textconv --stat)", "Bash(git diff --no-ext-diff --no-textconv)", "Bash(git log --oneline -n 10)", "Bash(git diff --cached --name-only)", "PowerShell(git status)", "PowerShell(git diff --no-ext-diff --no-textconv --stat)", "PowerShell(git diff --no-ext-diff --no-textconv)", "PowerShell(git log --oneline -n 10)", "PowerShell(git diff --cached --name-only)", "Read", "Grep"]
---

# git-safety-check — Git Safety Check

> **Read-only** only. Never commits or pushes. Governing contract: 08. Match the user's language.

## Commands
```bash
git status
git diff --no-ext-diff --no-textconv --stat
git diff --no-ext-diff --no-textconv
git log --oneline -n 10
```
`--no-ext-diff --no-textconv` keeps a repository-configured diff program from running or rewriting what you review. These exact commands are pre-approved; any other form asks first.

## Secret scan (read-only)
Check staged changes for leaks with git alone — no `grep` or other shell pipe, so it works in PowerShell-only Windows shells as well as POSIX shells. Both commands print file names only, never a matched value; the marker search is not pre-approved, so approve it when asked:
```bash
git diff --cached --name-only
git diff --cached --name-only --text --no-ext-diff --no-textconv -i -G "pass(word|wd)[[:space:]]*[:=]|secret|api[_-]?key|connection[_ ]?string|bearer[[:space:]]|token|-----BEGIN"
```
- The full name list shows staged credential files such as `.env`, `id_rsa` or `*.pem`; the `-G` list shows staged files whose changed lines contain a secret marker.
- Open each listed file with the Read or Grep tool — never build a shell command from a file name. Judge each marker line without echoing it. On a suspicious match: **do not print the real value** — report `file:line` and the risk type, with the value replaced by `***MASKED***`.

## Pre-commit checklist
1. Did **only the intended** files change? (any unexpected file?)
2. No secret / token / connection-string leak?
3. Were build/test commands run, and results shown?
4. Is the change focused on **one problem**?
5. Correct branch (not `main` / `master`)?
6. Is the commit message clear? *(Never commit without user approval — only propose.)*

## Note
Commit/push happen **only on user request** — never automatically (contract 08).
