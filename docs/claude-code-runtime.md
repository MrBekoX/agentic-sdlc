# Claude Code Runtime

## Scope

AGENTIC-SDLC currently targets Claude Code only. Codex, Cursor, Kimi, OpenCode, Gemini, Pi, and other harnesses are deferred.

## Plugin Shape

The expected runtime shape is a local/development Claude Code plugin. The metadata here does not publish the plugin by itself; publishing requires a separate, explicit release process that is not present in CI.

```text
.claude-plugin/plugin.json
.claude-plugin/marketplace.json
hooks/hooks.json
skills/
agents/
commands/
workflows/
rules/
scripts/
```

Skills are intentionally stored in root `skills/`. Do not move them to `.claude/skills/`; that would duplicate the source of truth and break the repo tests.

## Hook Runtime

`hooks/hooks.json` uses `${CLAUDE_PLUGIN_ROOT}` for portable paths. Claude Code resolves this variable to the installed plugin directory.

Requirements:

- `node` must be available on `PATH` for hook execution.
- `python` must be available for local quality gates.
- Git-dependent flows should run inside a real git checkout.

## Local `.claude/`

The repo may contain `.claude/settings.json` for local workspace settings. This is not the skill source. It should not contain a duplicate skill tree.

## Non-Git Workspace Behavior

Some flows are git-aware. In a non-git workspace:

- `detect_context.py` and validator tests still work.
- Branch guards cannot determine the current branch.
- Commit, PR, release, and worktree steps must be skipped with an explicit note.

## Tool Mapping

Claude Code concepts used by the skills:

| Concept | Claude Code Mechanism |
|---|---|
| Load a skill | Claude Code skill invocation |
| Dispatch subagent | Agent / Task facility when available |
| Dynamic workflow | Workflow facility when available |
| Slash command | `commands/*.md` |
| Plugin hook | `hooks/hooks.json` |
| Runtime plugin root | `${CLAUDE_PLUGIN_ROOT}` |

If a Claude Code capability is unavailable in the current version/configuration, fall back to the nearest supported mechanism and state the fallback in the final report.

## Skill Frontmatter Policy

The repo gate intentionally accepts the frontmatter keys used by this lab:

- `name`
- `description`
- `license`
- `allowed-tools`
- `metadata`
- `compatibility`
- `user-invocable`
- `argument-hint`
- `model`
- `disable-model-invocation`

Packaging tools may enforce a stricter subset. Treat `scripts/check_all.py` and `tests/skills/harness.py` as the repo-valid contract; treat packaging-tool validation as the package-valid contract.
