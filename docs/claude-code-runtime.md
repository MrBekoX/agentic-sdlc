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

The full-mode transcript must show native calls for the pipeline gates: `Skill` (`dispatch-strategy`, `completion-claim-gate`), `Workflow` (`spec-plan-draft`), `Read` of the selected work-type core file, and `Agent`/`Task` (`security-reviewer`, `implementation-auditor`, and `context-analyst` when used). Manual prose does not replace a tool call when the runtime supports that tool.

## Hooks

Claude Code wires the full hook set through `hooks/hooks-claude.json`:

- `PreToolUse`: commit secret scan, destructive-command guard, branch guard (all on `Bash|PowerShell`), and flow-order guard before active-flow source edits (`Write|Edit|MultiEdit|Bash|PowerShell`).
- `PostToolUse`: write secret scan (`Write|Edit|MultiEdit|NotebookEdit`).
- `SessionStart`: AGENTIC-SDLC bootstrap (including the line that the pipeline owns every step inside an active `agentic-sdlc-pipeline` run) and git status summary.
- `Stop`: completion-claim guard, flow-step evidence guard, and `worktree-scan.mjs`.

`flow-order-guard.mjs` and `flow-step-guard.mjs` both read `hooks/flow-requirements.json` through `flow-evidence.mjs`. They re-derive evidence from validated artifacts, real tool calls, and command transcripts; prose claims do not satisfy a step. They warn by default and block/deny only when `AGENTIC_FLOW_GATE_BLOCK=true`.

`flow-order-guard.mjs` runs on `Bash` and `PowerShell` too, with no `if` filter: a command that writes a source file (`sed -i`, a redirect, a heredoc, `tee`) is an edit, read by the same write-target recognizer the Codex guard uses, and a command that writes no source file stays silent. The current call is never its own evidence. At Stop, `flow-step-guard.mjs` counts shell writes as source edits (a shell write to a source-extension file outside the project too; PowerShell cmdlet writes such as `Set-Content` are not recognised), classifies paths relative to the project, and validates only the specs and plans this session wrote: an artifact from an earlier session satisfies a step only after it is rewritten; the step's other evidence, such as a `spec-plan-draft` `Workflow` call, still counts. A test command counts behind common wrappers and launchers, but not inside a heredoc body or a `#` comment. A path that names the project through a link (macOS `/var` is `/private/var`) is compared with its folder and the project folder resolved, which can only make it a source file. `flow-step-guard.mjs` reads every target as written before it resolves a link; the byte-locked `flow-order-guard.mjs` resolves its targets one by one, so a lookup that stalls on a dead network mount can still run it past its timeout.

The Stop guard also lists two warn-level steps for the house flows. `branch` flags a source edit while the Stop-time working directory is on `main` or `master`. `review-result` flags a reviewer that was dispatched (the control reviewers `implementation-control` / `implementation-auditor`, and where a flow has a security step, `security-audit` / `security-reviewer`; for `agentic-sdlc-pipeline` only the `Agent` dispatches of `implementation-auditor` and `security-reviewer`, matched by exact name) when the only result is a launch receipt (`toolUseResult.status` `async_launched` or `remote_launched`) or no completed result exists. A runtime task-notification with `completed`, or an in-flight Stop `background_tasks` subagent naming that reviewer, clears it ([hooks](https://code.claude.com/docs/en/hooks), fetched 2026-10-07). Neither step ever blocks or denies, even with `AGENTIC_FLOW_GATE_BLOCK=true`; `branch-guard.mjs` remains the commit and push guard.

For `agentic-sdlc-pipeline`, the `dispatch`, `security` and `control` steps match the `Skill` call to `dispatch-strategy` and the `Agent` dispatches of `security-reviewer` and `implementation-auditor` by exact name. Its `red-first` step makes `flow-order-guard.mjs` look for a test command before the first production edit; whether that run failed is checked only by the offline strict grader. `flow-step-guard.mjs` also warns when a pipeline turn ends on the `dispatch-strategy` decision, and blocks that only when `AGENTIC_FLOW_GATE_BLOCK=true`. On Claude Code the flow hooks activate a flow from a top-level `Skill` tool call (a sub-agent's `Skill` call activates nothing) or from a slash-command start: a pipeline run started with `/agentic-sdlc-pipeline` or `/agentic-sdlc:agentic-sdlc-pipeline` (recorded as `<command-name>/agentic-sdlc:agentic-sdlc-pipeline</command-name>` in headless `claude -p` on Claude Code 2.1.302; an interactive-session start was not captured) is gated the same way. Details: [`../hooks/README.md`](../hooks/README.md).

All paths resolve through `${CLAUDE_PLUGIN_ROOT}`. `node` must be on `PATH`.

Claude Code loads `hooks/hooks.json` by default and merges the manifest `hooks` file into it ([plugins reference](https://code.claude.com/docs/en/plugins-reference), read 2026-11-21). This repository keeps `hooks/hooks.json` absent, so only `hooks/hooks-claude.json` loads. A `hooks.json` at the package root is not loaded: on 2.1.330 (2026-11-21, isolated `CLAUDE_CONFIG_DIR`, `--plugin-dir`) probe hooks there never registered, while the same probes in `hooks/hooks.json` did. `.antigravity-plugin/hooks.json` is not loaded either, in a separate run the same day: with SessionStart and PreToolUse probes there, 2.1.330 registered 9 hooks and none came from the probe file. `hooks/hooks-claude.json` carries no `$comment` keys: 2.1.330 logged the two matcher-group keys (`PreToolUse[0]`, `PreToolUse[1]`) as unknown keys (`[WARN]` and `[ERROR]`) at every load, and `claude plugin validate --strict` did not report them; the third, handler-level key was not named in the log but was removed too, because the plugins reference documents no comment field; the wiring rationale lives in [hooks/README.md](../hooks/README.md#claude-code-wiring-notes-hooks-claudejson).

## Validating locally

CI pins Claude Code 2.1.319 and runs `claude plugin validate . --strict --json` and `claude plugin validate .claude-plugin/plugin.json --strict --json` on the git checkout, which, like a `build_release` package, has no gitignored `CLAUDE.md`. Both targets pass on a `build_release` package and on a `git archive HEAD` export with 2.1.319 and 2.1.330 (2026-11-21; the 2.1.319 and 2.1.330 runs on the export used an empty `HOME`, an empty `CLAUDE_CONFIG_DIR` and no API key). Run them on a `build_release` export, not on the working tree: a local, gitignored `CLAUDE.md` at the root makes `validate .` fail on 2.1.330 with `CLAUDE.md at the plugin root is not loaded as project context`, and the release archive excludes that file.

```bash
python3 scripts/build_release.py --output <scratch>/pkg.zip
python3 -m zipfile -e <scratch>/pkg.zip <scratch>/pkg
cd <scratch>/pkg && claude plugin validate . --strict --json
```

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

The repository gate rejects frontmatter keys outside that list. Public skill docs and new skills stay inside it. The external skill-creator validator is the stricter package contract. Agent role files have their own frontmatter shape (`name`, `description`, `tools`, `model`); Claude Code accepts `tools` as a comma-separated string or a YAML list ([sub-agents](https://code.claude.com/docs/en/sub-agents), read 2026-11-21), and `claude plugin validate` does not check tool names (on 2.1.330, 2026-11-21, an agent with `tools: NotATool, AlsoBogus` still passed `validate . --strict` with no finding). Treat `scripts/check_all.py` and `tests/skills/harness.py` as the current repo gate; treat external packaging validation as the stricter package-valid contract.

## Artifact Layouts And Per-Package Evidence

Work-package artifacts resolve in two layouts: the legacy flat `docs/agentic-sdlc/{specs,plans}/<id>.md` (back-compat, unchanged) and the per-package canonical `docs/agentic-sdlc/<slug>/{spec,plan,evidence}/<work_id>.md`, where `<slug>` is lowercase kebab-case `^[a-z0-9][a-z0-9-]{0,63}$` and never a reserved name (`specs`, `plans`, `evidence`, `notes`, `spec`, `plan`).

Per-package evidence persists to `docs/agentic-sdlc/<slug>/evidence/<work_id>.md` — per-package only (flat packages get no Finalize evidence), overwritten in place per run (single canonical file, last run wins), git-ignored, and with no validator (it never gates resolution; the Claude flow guards never activate on an evidence write). That evidence write is performed by the main pipeline finalize step, not the read-only `implementation-auditor` sub-agent.

From Step 8 the pipeline's main loop also writes a TDD evidence file, `docs/agentic-sdlc/<slug>/evidence/<work_id>.tdd.md` per-package or `docs/agentic-sdlc/evidence/<work_id>.tdd.md` flat, with every test run until `implementation-auditor` is dispatched; it is git-ignored, has no validator and never gates resolution.

Per-package plan change-detection runs as a filesystem scan, not a `git status` query: new generated plans can be git-ignored, so the resolver scans the filesystem; published plugin documentation is tracked separately.
