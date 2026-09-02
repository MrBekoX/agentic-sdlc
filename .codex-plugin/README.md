# AGENTIC-SDLC For Codex

This plugin packages AGENTIC-SDLC for Codex using the shared root `skills/` tree, a Codex manifest, and Codex interface metadata.

## Load Model

Codex reads:

| File | Purpose |
|---|---|
| `.codex-plugin/plugin.json` | Codex plugin metadata and interface block. |
| `skills/*/SKILL.md` | Shared skill source. |
| `hooks/hooks-codex.json` | Codex hook config: blocking `PreToolUse`, bootstrap `SessionStart`, and advisory/env-gated `Stop` backstops after hook review/trust. |

The manifest points to:

```json
{
  "skills": "./skills/"
}
```

The `interface` block supplies Codex display metadata, capabilities, default prompts, website, privacy policy, and terms links.

## Install

Codex discovers the default personal marketplace at `~/.agents/plugins/marketplace.json`. Its `agentic-sdlc` entry should point at `~/.codex/plugins/agentic-sdlc`, which can be a real copy or a symlink/junction to this clone. In the default personal marketplace, the `./plugins/agentic-sdlc` source path resolves to that plugin directory.

Example `~/.agents/plugins/marketplace.json`:

```json
{
  "name": "personal",
  "interface": {
    "displayName": "Personal"
  },
  "plugins": [
    {
      "name": "agentic-sdlc",
      "source": {
        "source": "local",
        "path": "./plugins/agentic-sdlc"
      },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Developer Tools"
    }
  ]
}
```

```bash
codex plugin add agentic-sdlc@personal
```

Start a new Codex thread after install or reinstall so the runtime reloads plugin skills and hooks. If Codex reports bundled hooks pending review, open `/hooks` and review the plugin commands before relying on them.

## Runtime Root

Codex resolves plugin paths through:

```text
${PLUGIN_ROOT}
```

Examples:

```bash
python3 "${PLUGIN_ROOT}/scripts/detect_context.py" --path .
python3 "${PLUGIN_ROOT}/scripts/validate_artifacts.py" --mode plan --file docs/agentic-sdlc/plans/example.md --spec docs/agentic-sdlc/specs/example.md --strict
```

Do not use `${CLAUDE_PLUGIN_ROOT}` in Codex-only examples.

## Routing And Pipeline Use

Codex uses activated skill instructions and available Codex tools. It does not expose the same Claude Code `Skill`, `Workflow`, and `Agent` transcript events.

`using-agentic-sdlc` still routes narrow work to the smallest sufficient independent skill. `agentic-sdlc-pipeline` remains the full-envelope escalation path for end-to-end or high-risk work.

## Pipeline Behavior In Codex

Codex has no Claude Code Workflow runtime. Therefore `agentic-sdlc-pipeline` does not call the `spec-plan-draft` JavaScript workflow. It uses the embedded author/critic adapter:

Emit `Runtime: Codex` once. At each gate below, emit `Codex Adapter Gate: <gate>` so `codex exec --json` transcripts have deterministic evidence. When Codex has no native `Skill` transcript event, record `Delegation Degraded: native Skill transcript events unavailable`; the adapter still runs the step by loading or activating the relevant `SKILL.md` instructions.

1. Activate `dispatch-strategy` before heavy, independent, or parallel decisions.
2. Run `detect_context.py` through `${PLUGIN_ROOT}`.
3. Draft the spec inside `agentic-sdlc-pipeline` using the spec contract and `spec-plan-author` role instructions.
4. Run a fresh-context critic pass with `spec-plan-critic` instructions when Codex subagents are available; otherwise record a degraded inline critic pass.
5. Save `docs/agentic-sdlc/specs/<work_id>.md` and run `validate_artifacts.py --mode spec`.
6. Draft and critic-review the plan inside `agentic-sdlc-pipeline`.
7. Save `docs/agentic-sdlc/plans/<work_id>.md` and run `validate_artifacts.py --mode plan --strict`.
8. Activate the selected core workflow skill before implementation edits.
9. Activate `security-audit`, `implementation-control`, and `completion-claim-gate` at their gates.

During Codex pipeline and eval runs, do not run recursive cleanup deletes for generated caches such as `__pycache__`. Leave or report them instead; cleanup is not a pipeline gate and may create permission-denial noise in procedure transcripts.

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
| Pre-final audit | `implementation-control` |
| Final evidence claim | `completion-claim-gate` |

## Hooks In Codex

The Codex manifest declares `"hooks": "./hooks/hooks-codex.json"`. It wires blocking `PreToolUse` guards for commit secrets, destructive shell commands, branch policy, literal writes, and opt-in flow ordering; `SessionStart` bootstrap context; and `Stop` continuation backstops for completion claims and flow evidence. Every path resolves through `${PLUGIN_ROOT}`. The config is deliberately NOT named `hooks/hooks.json`: Claude Code would auto-load that default filename with the wrong root variable. Non-managed plugin-bundled command hooks require Codex review/trust before they run. Several controls remain intentionally bounded: branch blocking and flow ordering are env-gated, Stop hooks continue the turn rather than undoing effects, and parser errors fail open.

## Requirements

- Codex CLI/runtime with plugin marketplace support.
- Node.js on `PATH` for manual hook-script checks and local gates.
- Python 3 for validators, probes, and local gates.
- Git for branch, diff, commit, PR, and worktree flows.

## Evaluation

Codex trigger evidence is not directly comparable to Claude Code trigger evidence. `scripts/run_codex_trigger_eval.py` is a route-classifier proxy because Codex does not expose Claude-style `Skill` tool events in the same way.

Use Codex eval output as evidence for Codex routing only. Use procedure transcripts or runtime-adapter evidence patterns to support claims about the pipeline following its Codex path.

## Artifact Layouts And Per-Package Evidence

Work-package artifacts resolve in two layouts: the legacy flat `docs/agentic-sdlc/{specs,plans}/<id>.md` (back-compat, unchanged) and the per-package canonical `docs/agentic-sdlc/<slug>/{spec,plan,evidence}/<work_id>.md`, where `<slug>` is lowercase kebab-case `^[a-z0-9][a-z0-9-]{0,63}$` and never a reserved name (`specs`, `plans`, `evidence`, `notes`, `spec`, `plan`).

Per-package evidence persists to `docs/agentic-sdlc/<slug>/evidence/<work_id>.md` — per-package only (flat packages get no evidence), overwritten in place per run (single canonical file, last run wins), git-ignored, and with no validator (it never gates resolution). That evidence write is performed by the main pipeline finalize step, not the read-only `implementation-auditor` sub-agent.

Per-package plan change-detection runs as a filesystem scan, not a `git status` query: the whole `docs/` tree is git-ignored, so `git status` never reports new per-package plans and the resolver scans the filesystem instead.

## Troubleshooting

See [`../docs/troubleshooting.md`](../docs/troubleshooting.md) for plugin loading, missing Node, Codex eval warnings, and common procedure-eval failures.
