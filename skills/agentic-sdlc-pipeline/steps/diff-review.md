# Diff review

Review the whole change against the plan and the Scope Lock with read-only git commands. This step reads git; it never stages, commits or rewrites anything.

## 1. Read the change
Run each command on its own:

```
git status
git diff --no-ext-diff --no-textconv --stat <base>
git diff --no-ext-diff --no-textconv <base>
git log --oneline -n 10
```

- `<base>` is `base_commit` in `<package>/state.json`. When it is null (a repository with no commit yet), use `git status` and read every file it lists.
- `--no-ext-diff --no-textconv` keeps a repository-configured diff program from running or rewriting what you review.
- `git diff` does not show untracked files: read each new file that `git status` lists with `??`.
- Leave the work package folder (`docs/agentic-sdlc/`) out of the review: it is the run's own record.

## 2. Secret scan
Use git and the read and search tools only, with no shell pipe:

```
git diff --name-only <base>
git diff --name-only --text --no-ext-diff --no-textconv -i -G "pass(word|wd)[[:space:]]*[:=]|secret|api[_-]?key|connection[_ ]?string|bearer[[:space:]]|token|-----BEGIN" <base>
```

- The first list shows credential files such as `.env`, `id_rsa`, `*.pem` or `*.key`. The second lists files whose changed lines hold a secret marker. Both print file names only.
- Search the new untracked files for the same markers with the search tool.
- Open each listed file with the read or search tool; never build a shell command from a file name. Judge each marker line without echoing it.
- A real or likely secret: never print it. Report `file:line` and the risk type, with the value as `***MASKED***`.

## 3. Check
1. Only the intended files changed: compare with "Files allowed to change" in the Scope Lock of `context.md` and with the files the plan names.
2. The change matches the spec and the plan, and nothing is outside the plan.
3. No secret, token, key or connection string.
4. No formatting noise, debug output, commented-out code or stray files.
5. The tests are meaningful, and their runs were recorded.
6. No unintended breaking change. New env vars are in `.env.example`. Docs the change made stale are updated.
7. The change is focused on one problem, and the branch is not `main` or `master` (unless the run started with branch policy `stay`).

Fix what this run caused (a debug line, a stray file it created) and say so; a source fix reopens the earlier checks that depend on the source. Report everything else. Never revert the user's own changes.

## 4. Write the report
Write the file the card's `outputs=` line names:

```md
# Diff review
Base: <base> | Branch: <branch>
Changed files: <path>: expected | unexpected (<why>)
Untracked files: <path>: expected | unexpected (<why>)
Secret scan: clean | <file:line> <risk type> ***MASKED***
Checklist: 1 ok, 2 ok, ... (a finding names its file:line)
Potential issues:
Cleanups applied:
Proposed commit message: `<type>(<scope>): <summary>`
```

The line `# Diff review` must appear exactly like that, on its own line. Write the report in this visit: a file left from an earlier visit, or rewritten byte for byte, does not count. The commit message is a proposal for the user; never stage or commit.

## Finish
Write the report, then run the card's `then=` command.
