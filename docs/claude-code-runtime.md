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
hooks/hooks-claude.json
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
| Hook wiring | `hooks/hooks-claude.json`, declared by `.claude-plugin/plugin.json`. |
| Runtime plugin root | `${CLAUDE_PLUGIN_ROOT}`. |

## Pipeline Contract

In Claude Code, `agentic-sdlc-pipeline` must use the named Workflow `agentic-sdlc:spec-plan-draft` for its internal Spec and Plan phases. It must not call standalone `spec-authoring` or `plan-authoring` for steps 4-5.

The full-mode transcript must show native calls for the pipeline gates: `Skill`, `Workflow`, and, when used, `Agent`/`Task`. Manual prose does not replace a tool call when the runtime supports that tool.

## Hooks

Claude Code wires the full hook set through `hooks/hooks-claude.json`:

- `PreToolUse`: commit secret scan, destructive-command guard, branch guard, and flow-order guard before active-flow source edits.
- `PostToolUse`: write secret scan.
- `SessionStart`: AGENTIC-SDLC bootstrap and git status summary.
- `Stop`: completion-claim guard and flow-step evidence guard.

`flow-order-guard.mjs` and `flow-step-guard.mjs` both read `hooks/flow-requirements.json` through `flow-evidence.mjs`. They re-derive evidence from validated artifacts, real tool calls, and command transcripts; prose claims do not satisfy a step. They warn by default and block/deny only when `AGENTIC_FLOW_GATE_BLOCK=true`.

All paths resolve through `${CLAUDE_PLUGIN_ROOT}`. `node` must be on `PATH`.

## Local `.claude/`

The repo may contain `.claude/settings.json` for local workspace settings. That file is not the skill source and should not contain duplicate skills.

## Non-Git Workspaces

Git-aware flows should skip branch, commit, PR, release, and worktree steps with an explicit note when the active workspace is not a git checkout. Deterministic probes and artifact validators still work.

## Frontmatter Policy

Canonical `SKILL.md` frontmatter for new plugin skills should stay to:

- `name`
- `description`
- `license`
- `allowed-tools`
- `metadata`
- `compatibility`

The local parser may tolerate legacy or runtime-specific keys while older fixtures are retired, but public skill docs and new skills should not introduce them. Agent role files have their own frontmatter shape (`name`, `description`, `tools`, `model`). Treat `scripts/check_all.py` and `tests/skills/harness.py` as the current repo gate; treat external packaging validation as the stricter package-valid contract.
