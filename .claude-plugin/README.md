# AGENTIC-SDLC For Claude Code

This plugin packages AGENTIC-SDLC as a Claude Code local/development plugin. It uses the shared root `skills/` tree plus Claude-native `Skill`, `Workflow`, `Agent`/`Task`, hook, and command mechanisms.

## Load Model

Claude Code reads:

| File | Purpose |
|---|---|
| `.claude-plugin/plugin.json` | Plugin metadata: name, version, description, author, license, homepage. |
| `.claude-plugin/marketplace.json` | Local marketplace source; `source` points at the repository root. |
| `skills/*/SKILL.md` | Shared skill source. |
| `workflows/*.js` | Claude Code dynamic workflow scripts. |
| `agents/*.md` | Fresh-context role contracts used by workflows and subagents. |
| `hooks/hooks.json` | Claude hook wiring. |
| `commands/*.md` | Manual slash commands such as `/git-safety-check`. |

Skills are intentionally stored in root `skills/`, not `.claude/skills/`. The local `.claude/` directory is workspace settings only.

## Runtime Root

Claude hook and script paths resolve through:

```text
${CLAUDE_PLUGIN_ROOT}
```

Examples:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/detect_context.py" --path .
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate_artifacts.py" --mode spec --file docs/specs/example.md
```

Do not hard-code machine-specific absolute paths into skills, hooks, evals, or generated artifacts.

## Routing And Pipeline Use

`using-agentic-sdlc` is the session-local router. It chooses the smallest sufficient skill for the prompt. Narrow requests should stay with focused skills such as `feature-build`, `root-cause-fix`, `safe-refactor`, `test-authoring`, `security-audit`, or `code-quality-review`.

`agentic-sdlc-pipeline` is the full-envelope escalation path. In Claude Code it must leave real transcript evidence:

1. `Skill` invocation for `agentic-sdlc:dispatch-strategy`.
2. `Bash`/`PowerShell` invocation of `detect_context.py`.
3. `Workflow` invocation of `agentic-sdlc:spec-plan-draft` with `mode:"spec"`.
4. `validate_artifacts.py --mode spec` after saving the spec.
5. `Workflow` invocation of `agentic-sdlc:spec-plan-draft` with `mode:"plan"`.
6. `validate_artifacts.py --mode plan --strict` after saving the plan.
7. `Skill` invocation for the selected core workflow: `feature-build`, `root-cause-fix`, `safe-refactor`, or `test-authoring`.
8. `Skill` invocation for `security-audit` at required security gates.
9. `Skill` invocation for `implementasyon-control` before final reporting.
10. `Skill` invocation for `completion-claim-gate` immediately before any done/fixed/passing/ready claim.

Manual prose does not replace those tool calls when the runtime supports them.

## How Independent Skills Feed The Pipeline

Focused skills are independently invocable. The pipeline reuses them instead of duplicating their internal logic:

| Pipeline stage | Claude Code mechanism |
|---|---|
| Spec and plan phases | Named workflow `agentic-sdlc:spec-plan-draft`. |
| Implementation core | Delegates to `feature-build`, `root-cause-fix`, `safe-refactor`, or `test-authoring`. |
| Security gates | Delegates to `security-audit`. |
| Pre-final audit | Delegates to `implementasyon-control`. |
| Final evidence claim | Delegates to `completion-claim-gate`. |

`spec-authoring` and `plan-authoring` remain standalone prompt-level skills. They are not internal pipeline substeps.

## Hooks In Claude Code

Claude Code wires the full hook surface in `hooks/hooks.json`:

| Event | Scripts |
|---|---|
| `PreToolUse` | `scan-commit.mjs`, `destructive-command-guard.mjs`, `branch-guard.mjs` |
| `PostToolUse` | `scan-write.mjs` |
| `SessionStart` | `session-start.mjs` |
| `Stop` | `completion-claim-guard.mjs` |

`scan-commit.mjs` and `destructive-command-guard.mjs` can block. `scan-write.mjs` warns. `branch-guard.mjs` warns by default and blocks only when `AGENTIC_BRANCH_GUARD_BLOCK=true`. `completion-claim-guard.mjs` warns by default and blocks only when `AGENTIC_COMPLETION_GATE_BLOCK=true`.

## Requirements

- Claude Code with local plugin/marketplace support.
- Node.js on `PATH` for `.mjs` hooks.
- Python 3 for deterministic scripts and local gates.
- Git for branch, diff, commit, PR, and worktree flows.

## Verification

Local static gate:

```bash
python3 scripts/bump_version.py --check
python3 scripts/check_all.py
python3 tests/skills/harness.py
python3 -m unittest discover -s tests -v
```

Claude live trigger and procedure evidence uses `scripts/run_trigger_eval.py`, `scripts/run_routing_eval.py`, and `scripts/run_procedure_eval.py`. A Claude trigger eval measures real `Skill`/`Read` activation in the stream-json transcript.

## Troubleshooting

See [`../docs/troubleshooting.md`](../docs/troubleshooting.md) for plugin visibility, hook execution, missing Node, protected branch behavior, secret scanner warnings, non-git workspaces, and eval failures.
