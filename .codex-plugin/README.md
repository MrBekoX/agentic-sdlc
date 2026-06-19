# AGENTIC-SDLC For Codex

This plugin packages AGENTIC-SDLC for Codex using the shared root `skills/` tree, a Codex manifest, and Codex interface metadata.

## Load Model

Codex reads:

| File | Purpose |
|---|---|
| `.codex-plugin/plugin.json` | Codex plugin metadata and interface block. |
| `skills/*/SKILL.md` | Shared skill source. |
| `hooks/hooks.json` | Codex default hook config: SessionStart bootstrap only after hook review/trust. |

The manifest points to:

```json
{
  "skills": "./skills/"
}
```

The `interface` block supplies Codex display metadata, capabilities, default prompts, website, privacy policy, and terms links.

## Install

Codex discovers the default personal marketplace at `~/.agents/plugins/marketplace.json`. Its `agentic-sdlc` entry should point at `~/plugins/agentic-sdlc`, which can be a real copy or a symlink/junction to this clone.

```bash
codex plugin add agentic-sdlc@personal
```

Start a new Codex thread after install or reinstall so the runtime reloads plugin skills. If Codex reports bundled hooks pending review, open `/hooks` and trust the `SessionStart` hook before relying on startup context.

## Runtime Root

Codex resolves plugin paths through:

```text
${PLUGIN_ROOT}
```

Examples:

```bash
python3 "${PLUGIN_ROOT}/scripts/detect_context.py" --path .
python3 "${PLUGIN_ROOT}/scripts/validate_artifacts.py" --mode plan --file docs/plans/example.md --spec docs/specs/example.md --strict
```

Do not use `${CLAUDE_PLUGIN_ROOT}` in Codex-only examples.

## Routing And Pipeline Use

Codex uses activated skill instructions and available Codex tools. It does not expose the same Claude Code `Skill`, `Workflow`, and `Agent` transcript events.

`using-agentic-sdlc` still routes narrow work to the smallest sufficient independent skill. `agentic-sdlc-pipeline` remains the full-envelope escalation path for end-to-end or high-risk work.

## Pipeline Behavior In Codex

Codex has no Claude Code Workflow runtime. Therefore `agentic-sdlc-pipeline` does not call the `spec-plan-draft` JavaScript workflow. It uses the embedded author/critic adapter:

1. Activate `dispatch-strategy` before heavy, independent, or parallel decisions.
2. Run `detect_context.py` through `${PLUGIN_ROOT}`.
3. Draft the spec inside `agentic-sdlc-pipeline` using the spec contract and `spec-plan-author` role instructions.
4. Run a fresh-context critic pass with `spec-plan-critic` instructions when Codex subagents are available; otherwise record a degraded inline critic pass.
5. Save `docs/specs/<name>.md` and run `validate_artifacts.py --mode spec`.
6. Draft and critic-review the plan inside `agentic-sdlc-pipeline`.
7. Save `docs/plans/<name>.md` and run `validate_artifacts.py --mode plan --strict`.
8. Activate the selected core workflow skill before implementation edits.
9. Activate `security-audit`, `implementasyon-control`, and `completion-claim-gate` at their gates.

`spec-authoring` and `plan-authoring` remain standalone prompt-level skills. They are not internal pipeline substeps.

## How Independent Skills Feed The Pipeline

Focused skills are independently routable in Codex and also serve as pipeline building blocks:

| Pipeline need | Skill |
|---|---|
| New feature or endpoint | `feature-build` |
| Bug or regression | `root-cause-fix` |
| Behavior-preserving refactor | `safe-refactor` |
| Test-only work | `test-authoring` |
| Execution mechanism choice | `dispatch-strategy` |
| Security gates | `security-audit` |
| Pre-final audit | `implementasyon-control` |
| Final evidence claim | `completion-claim-gate` |

## Hooks In Codex

The publishable Codex manifest does not declare a top-level `hooks` field. Codex auto-detects hooks/hooks.json; no manifest hooks field is required. Codex can discover the plugin-default `hooks/hooks.json`, which wires only `SessionStart` to `hooks/session-start-codex.mjs` through `${PLUGIN_ROOT}`. Non-managed plugin-bundled command hooks require Codex review/trust before they run. Command-blocking guardrails remain Claude-only in this release; Codex guardrail behavior is carried by skills, contracts, manual checks, and explicit script runs where appropriate.

## Requirements

- Codex CLI/runtime with plugin marketplace support.
- Node.js on `PATH` for manual hook-script checks and local gates.
- Python 3 for validators, probes, and local gates.
- Git for branch, diff, commit, PR, and worktree flows.

## Evaluation

Codex trigger evidence is not directly comparable to Claude Code trigger evidence. `scripts/run_codex_trigger_eval.py` is a route-classifier proxy because Codex does not expose Claude-style `Skill` tool events in the same way.

Use Codex eval output as evidence for Codex routing only. Use procedure transcripts or runtime-adapter evidence patterns to support claims about the pipeline following its Codex path.

## Troubleshooting

See [`../docs/troubleshooting.md`](../docs/troubleshooting.md) for plugin loading, missing Node, Codex eval warnings, and common procedure-eval failures.
