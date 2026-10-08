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
| Manual safety command | `commands/*.md`, especially `/agentic-sdlc:git-safety-check`. |
| Hook wiring | `hooks/hooks-claude.json`, declared by `.claude-plugin/plugin.json`. |
| Runtime plugin root | `${CLAUDE_PLUGIN_ROOT}`. |

## Pipeline Contract

In Claude Code, `agentic-sdlc-pipeline` must use the named Workflow `agentic-sdlc:spec-plan-draft` for its internal Spec and Plan phases. It must not call standalone `spec-authoring` or `plan-authoring` for steps 4-5. Dynamic workflows are available on paid plans, with Anthropic API access, and on Amazon Bedrock, Google Cloud's Agent Platform, and Microsoft Foundry; on Pro, turn them on from `/config` ([workflows](https://code.claude.com/docs/en/workflows), fetched 2026-10-07). This is not a live test on 2.1.293.

The full-mode transcript must show native calls for the pipeline gates: `Skill`, `Workflow`, and, when used, `Agent`/`Task`. Manual prose does not replace a tool call when the runtime supports that tool.

## Hooks

Claude Code wires the full hook set through `hooks/hooks-claude.json`:

- `PreToolUse`: commit secret scan, destructive-command guard, branch guard, and flow-order guard before active-flow source edits.
- `PostToolUse`: write secret scan.
- `SessionStart`: AGENTIC-SDLC bootstrap and git status summary.
- `Stop`: completion-claim guard, flow-step evidence guard, and `worktree-scan.mjs`.

`flow-order-guard.mjs` and `flow-step-guard.mjs` both read `hooks/flow-requirements.json` through `flow-evidence.mjs`. They re-derive evidence from validated artifacts, real tool calls, and command transcripts; prose claims do not satisfy a step. They warn by default and block/deny only when `AGENTIC_FLOW_GATE_BLOCK=true`.

The Stop guard also lists two warn-level steps for the house flows. `branch` flags a source edit while the Stop-time working directory is on `main` or `master`. `review-result` flags a reviewer that was dispatched (the control reviewers `implementation-control` / `implementation-auditor`, and where a flow has a security step, `security-audit` / `security-reviewer`) when the only result is a launch receipt (`toolUseResult.status` `async_launched` or `remote_launched`) or no completed result exists. A runtime task-notification with `completed`, or an in-flight Stop `background_tasks` subagent naming that reviewer, clears it ([hooks](https://code.claude.com/docs/en/hooks), fetched 2026-10-07). Neither step ever blocks or denies, even with `AGENTIC_FLOW_GATE_BLOCK=true`; `branch-guard.mjs` remains the commit and push guard.

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

The repository gate rejects frontmatter keys outside that list. Public skill docs and new skills stay inside it. The external skill-creator validator is the stricter package contract. Agent role files have their own frontmatter shape (`name`, `description`, `tools`, `model`). Treat `scripts/check_all.py` and `tests/skills/harness.py` as the current repo gate; treat external packaging validation as the stricter package-valid contract.

## Artifact Layouts And Per-Package Evidence

Work-package artifacts resolve in two layouts: the legacy flat `docs/agentic-sdlc/{specs,plans}/<id>.md` (back-compat, unchanged) and the per-package canonical `docs/agentic-sdlc/<slug>/{spec,plan,evidence}/<work_id>.md`, where `<slug>` is lowercase kebab-case `^[a-z0-9][a-z0-9-]{0,63}$` and never a reserved name (`specs`, `plans`, `evidence`, `notes`, `spec`, `plan`).

Per-package evidence persists to `docs/agentic-sdlc/<slug>/evidence/<work_id>.md` — per-package only (flat packages get no evidence), overwritten in place per run (single canonical file, last run wins), git-ignored, and with no validator (it never gates resolution; the Claude flow guards never activate on an evidence write). That evidence write is performed by the main pipeline finalize step, not the read-only `implementation-auditor` sub-agent.

Per-package plan change-detection runs as a filesystem scan, not a `git status` query: new generated plans can be git-ignored, so the resolver scans the filesystem; published plugin documentation is tracked separately.
