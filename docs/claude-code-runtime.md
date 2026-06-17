# Claude Code Runtime

## Scope

AGENTIC-SDLC has native packaging for Claude Code and Codex. OpenCode, Kimi Code, and other Agent Skills runtimes are supported through the portable runtime adapter in [`runtime-adapter.md`](./runtime-adapter.md) when they can load standard `SKILL.md` directories and provide equivalent tool evidence or a documented degraded path.

## Plugin Shape

The expected native runtime shape is a local/development Claude Code and Codex plugin. Other Agent Skills runtimes consume the same `skills/` content through the adapter model rather than Claude-specific plugin metadata. The metadata here does not publish the plugin by itself. No CI workflow is configured for now; publishing requires a separate, explicit manual release process.

```text
.claude-plugin/plugin.json
.claude-plugin/marketplace.json
.codex-plugin/plugin.json
hooks/hooks.json
hooks/hooks-codex.json
skills/
agents/
commands/
workflows/
contracts/skills/
scripts/
```

Skills are intentionally stored in root `skills/`. Do not move them to `.claude/skills/` or `.codex/skills/`; that would duplicate the source of truth and break the repo tests.

## Hook Runtime

`hooks/hooks.json` uses `${CLAUDE_PLUGIN_ROOT}` for portable Claude paths. `hooks/hooks-codex.json` uses `${PLUGIN_ROOT}` for portable Codex paths.

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

Runtime concepts used by the skills:

| Concept | Runtime Mechanism |
|---|---|
| Load a skill | Claude Code skill invocation |
| Dispatch subagent | Agent / Task facility when available |
| Dynamic workflow | Claude Code Workflow facility when available; in Codex/OpenCode/Kimi Code, map to subagent fan-out, parallel local tools, cloud delegation, native agent mechanisms, or a documented degraded main-loop path |
| Slash command | `commands/*.md` |
| Plugin hook | `hooks/hooks.json` |
| Runtime plugin root | `${CLAUDE_PLUGIN_ROOT}` in Claude Code; `${PLUGIN_ROOT}` in Codex; configured plugin/skill root in OpenCode/Kimi Code |

If a runtime capability is unavailable in the current version/configuration, fall back to the nearest supported mechanism and state the fallback in the final report.

## Spec/Plan Runtime Split

Claude Code can run `workflows/spec-plan-draft.js` as a JavaScript dynamic workflow. Non-Claude Agent Skills runtimes do not use that runtime. Therefore:

- `spec-authoring` and `plan-authoring` remain standalone prompt-level entry skills.
- `agentic-sdlc-pipeline` must not call `spec-authoring` or `plan-authoring` for its internal steps 4-5.
- In Claude Code, `agentic-sdlc-pipeline` uses `spec-plan-draft`.
- In Codex, OpenCode, Kimi Code, and similar runtimes, `agentic-sdlc-pipeline` uses its embedded author/critic adapter: main-loop draft, fresh-context critic when available, revise, save artifact, validate.

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
