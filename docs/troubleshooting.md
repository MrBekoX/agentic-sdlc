# Troubleshooting

## Claude Code Does Not See The Skills

Check:

1. The repo is installed as a Claude Code plugin or local marketplace source.
2. `.claude-plugin/plugin.json` exists.
3. Skills are under root `skills/`, not `.claude/skills/`.
4. The session was restarted after plugin installation.

## Hooks Do Not Run

Check:

1. `hooks/hooks.json` is present in the plugin root.
2. `node` is on `PATH`.
3. `${CLAUDE_PLUGIN_ROOT}` resolves in the Claude Code plugin runtime.
4. The hook event matches the tool invocation. For example, `scan-commit.mjs` only runs for `git commit*`.

## Branch Guard Only Warns

This is the default. To make protected branch commit/push attempts block:

```bash
AGENTIC_BRANCH_GUARD_BLOCK=true
```

The branch guard fails open if git is unavailable or the workspace is not a git repo.

## Secret Scanner False Positive

The scanners never print secret values. If a warning is false positive:

1. Confirm the value is not a real credential.
2. Prefer environment variables or secret stores.
3. If you must bypass a hook temporarily, use Claude Code hook controls and document why.

## Destructive Command Blocked

`destructive-command-guard.mjs` blocks deterministic high-risk commands such as:

- `git reset --hard`
- forceful `git clean`
- `rm -rf`
- `Remove-Item -Recurse -Force`

Use a scoped, reviewed command and get explicit approval for destructive cleanup.

## Tests Skip Node Checks

`tests/test_static_node.py` skips JavaScript syntax checks if `node` is unavailable. A skip is not a pass. Install Node before release verification.

## Workspace Is Not A Git Repo

Git-aware flow steps should be skipped with a note. To enable branch, commit, PR, worktree, and review-package behavior, run in a real git checkout.
