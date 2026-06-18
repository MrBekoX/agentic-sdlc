# Claude Code Runtime

This file records Claude Code-specific assumptions. For the user-facing runtime guide, see [`../.claude-plugin/README.md`](../.claude-plugin/README.md). For Codex behavior, see [`../.codex-plugin/README.md`](../.codex-plugin/README.md).

## Native Shape

Claude Code is a supported release runtime for `agentic-sdlc`. The plugin shape is:

```text
.claude-plugin/plugin.json
.claude-plugin/marketplace.json
skills/
agents/
workflows/
hooks/hooks.json
commands/
contracts/skills/
scripts/
```

Skills are intentionally stored in root `skills/`. Do not duplicate them into `.claude/skills/`; that would create two sources of truth and break the repository tests.

## Runtime Mechanisms

| Concept | Claude Code mechanism |
|---|---|
| Load a skill | Native `Skill` invocation. |
| Dispatch a fresh-context specialist | `Agent` / `Task` facility when available. |
| Run spec/plan author-critic loop | Native `Workflow` invocation of `agentic-sdlc:spec-plan-draft`. |
| Manual safety command | `commands/*.md`, especially `/git-safety-check`. |
| Hook wiring | `hooks/hooks.json`. |
| Runtime plugin root | `${CLAUDE_PLUGIN_ROOT}`. |

## Pipeline Contract

In Claude Code, `agentic-sdlc-pipeline` must use the named Workflow `agentic-sdlc:spec-plan-draft` for its internal Spec and Plan phases. It must not call standalone `spec-authoring` or `plan-authoring` for steps 4-5.

The full-mode transcript must show native calls for the pipeline gates: `Skill`, `Workflow`, and, when used, `Agent`/`Task`. Manual prose does not replace a tool call when the runtime supports that tool.

## Hooks

Claude Code wires the full hook set through `hooks/hooks.json`:

- `PreToolUse`: commit secret scan, destructive-command guard, branch guard.
- `PostToolUse`: write secret scan.
- `SessionStart`: AGENTIC-SDLC bootstrap and git status summary.
- `Stop`: completion-claim guard.

All paths resolve through `${CLAUDE_PLUGIN_ROOT}`. `node` must be on `PATH`.

## Local `.claude/`

The repo may contain `.claude/settings.json` for local workspace settings. That file is not the skill source and should not contain duplicate skills.

## Non-Git Workspaces

Git-aware flows should skip branch, commit, PR, release, and worktree steps with an explicit note when the active workspace is not a git checkout. Deterministic probes and artifact validators still work.

## Frontmatter Policy

The repo gate accepts the frontmatter keys used by this lab:

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
