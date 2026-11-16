# Branch

Make sure the work happens on a work branch, never on the default branch, before any source change (a refactor writes its characterization tests earlier; that is expected). The check passes off `main` and `master`, or when the run started with branch policy `stay` and the user's quote.

In the commands below, `<python>` is the interpreter that starts the card's `then=` line and `<root>` is the card's `root=` value. Run them with `-B`, as the `then=` line does: it keeps `__pycache__` out of the plugin folder. `<slug>` is the last part of the card's `package=` value.

## 1. See where you are
Run, read-only:
- `git status --short`
- `git branch --show-current`
- `git rev-parse HEAD`

Not a git repository: there is no branch to make. Say so in one line and finish.

## 2. Pick the branch
- Already on a work branch that suits this work: keep it.
- On `main`, `master` or a detached HEAD: create a work branch from the current commit with `git switch -c <prefix>/<short-name>` (or `git checkout -b`). The prefix follows the work type: `feature/`, `fix/` for a bugfix, `refactor/`, `test/`; `security/` or `chore/` when the work is that. Keep the name short, lowercase and hyphenated, for example `fix/login-validation`.
- Creating a local branch is part of an implementation request. "Do not commit", "do not push" or "leave the changes uncommitted" limit publishing, not branching: create the branch anyway. Only an explicit "no branch" or "stay on this branch" restricts it.
- Branch from the current commit only. The runner fixed the run's base commit at start, so a branch from a newer main would count every upstream change as this work's. If the user wants the latest main, say so: they update main and start a new run.

Then show the user the branch name and the HEAD commit in one line.

## 3. Ask first when
- the user's words may forbid a new branch;
- the working tree holds uncommitted changes that are not part of this work, and the new branch would carry them;
- the branch name you want already exists and is not this work's.

Ask one question with `"<python>" -B "<root>/scripts/sdlc.py" ask --slug <slug> --kind consent --question "<question>"`, then end your turn. The runner waits for the answer and prints how to record it.

## 4. When the step cannot pass
The user refuses a work branch, or git cannot create one (for example a read-only `.git`): never work around the check. Tell the user the step passes only on a work branch, or in a run started again with branch policy `stay` and their quote. Then end your turn. Record their decision with one of:
- `"<python>" -B "<root>/scripts/sdlc.py" halt --slug <slug> --reason "<their words>"` (stop for now);
- `"<python>" -B "<root>/scripts/sdlc.py" abandon --slug <slug> --quote "<their words>"` (end the run for good).

## Branch safety rules
These hold for the whole run, in every step:
- Never change source files on the default branch (`main`, `master`). The work package under `docs/agentic-sdlc/` is the run's own record.
- Do not fetch or pull for this run: its base commit is fixed. Never reset or rewrite a branch.
- Never stage for a commit, commit, push, merge or open a pull request unless the user explicitly asks for it. Propose; the user decides.
- Never run `reset --hard`, `clean -fdx`, `push --force`, `branch -D`, `stash` or anything else that hides or discards work. Never switch away from uncommitted work that is not yours.
- Stay in this checkout: the work package lives here, so do not move the work to another worktree or clone.

## Finish
Run the card's `then=` command.
