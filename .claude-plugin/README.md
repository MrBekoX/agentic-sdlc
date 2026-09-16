# AGENTIC-SDLC For Claude Code

This plugin packages AGENTIC-SDLC as a Claude Code local/development plugin. It uses the shared root `skills/` tree plus Claude-native `Skill`, `Workflow`, `Agent`/`Task`, hook, and command mechanisms.

## Load Model

Claude Code reads:

| File | Purpose |
|---|---|
| `.claude-plugin/plugin.json` | Plugin metadata: name, displayName, version, description, author, license, homepage. |
| `.claude-plugin/marketplace.json` | Local marketplace source; `source` points at the repository root. |
| `skills/*/SKILL.md` | Shared skill source. |
| `workflows/*.js` | Claude Code dynamic workflow scripts. |
| `agents/*.md` | Fresh-context role contracts used by workflows and subagents. |
| `hooks/hooks-claude.json` | Claude hook wiring, declared by `.claude-plugin/plugin.json`. |
| `commands/*.md` | Manual slash commands such as `/agentic-sdlc:git-safety-check`. |

Skills are intentionally stored in root `skills/`, not `.claude/skills/`. The local `.claude/` directory is workspace settings only.

## Runtime Root

Claude hook and script paths resolve through:

```text
${CLAUDE_PLUGIN_ROOT}
```

Examples:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/detect_context.py" --path .
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate_artifacts.py" --mode spec --file docs/agentic-sdlc/specs/example.md
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
9. `Skill` invocation for `implementation-control` before final reporting.
10. `Skill` invocation for `completion-claim-gate` immediately before any done/fixed/passing/ready claim.

Manual prose does not replace those tool calls when the runtime supports them.

## How Independent Skills Feed The Pipeline

Focused skills are independently invocable. The pipeline reuses them instead of duplicating their internal logic:

| Pipeline stage | Claude Code mechanism |
|---|---|
| Spec and plan phases | Named workflow `agentic-sdlc:spec-plan-draft`. |
| Implementation core | Delegates to `feature-build`, `root-cause-fix`, `safe-refactor`, or `test-authoring`. |
| Security gates | Delegates to `security-audit`. |
| Pre-final audit | Delegates to `implementation-control`. |
| Final evidence claim | Delegates to `completion-claim-gate`. |

`spec-authoring` and `plan-authoring` remain standalone prompt-level skills. They are not internal pipeline substeps.

## Hooks In Claude Code

Claude Code wires the full hook surface in `hooks/hooks-claude.json`:

| Event | Scripts |
|---|---|
| `PreToolUse` | `scan-commit.mjs`, `destructive-command-guard.mjs`, `branch-guard.mjs`, `flow-order-guard.mjs` |
| `PostToolUse` | `scan-write.mjs` |
| `SessionStart` | `session-start.mjs` |
| `Stop` | `completion-claim-guard.mjs`, `flow-step-guard.mjs`, `worktree-scan.mjs` |

`scan-commit.mjs` and `destructive-command-guard.mjs` can block. `scan-write.mjs` warns. `branch-guard.mjs` warns by default and blocks only when `AGENTIC_BRANCH_GUARD_BLOCK=true`. `completion-claim-guard.mjs` warns by default and blocks only when `AGENTIC_COMPLETION_GATE_BLOCK=true`.

`worktree-scan.mjs` scans the actual tracked/untracked bytes at Stop, reports only masked finding
labels/locations, and is advisory by default. `AGENTIC_WORKTREE_SCAN_BLOCK=true` asks Claude Code to
continue the turn, but cannot undo a secret that already reached disk.

The flow guards are the deterministic backstop for active implementation flows. `flow-order-guard.mjs` checks before source edits that required pre-edit evidence exists in the current turn; `flow-step-guard.mjs` checks at Stop that required flow steps have observable evidence. Both use `hooks/flow-requirements.json` and `flow-evidence.mjs`, warn by default, and block/deny only when `AGENTIC_FLOW_GATE_BLOCK=true`.

## Distribution paths

Four paths exist; each has its own go condition and state. The per-path verdicts are in [release readiness](../docs/release-readiness.md#distribution-paths-and-gono-go), and a state is a snapshot bound to the [release evidence ledger](../docs/release-evidence-0.4.3.md).

| Path | Prerequisites | Steps | Go condition | State |
|---|---|---|---|---|
| Claude own marketplace | Claude Code with plugin marketplace support; `node` on `PATH`; read access to `MrBekoX/agentic-sdlc`. | `/plugin marketplace add MrBekoX/agentic-sdlc`, then `/plugin install agentic-sdlc@mrbekox`. | Go condition: anonymous users need a public repository (a private one installs only through a git credential helper or SSH; a token only in an environment variable does not authenticate, [private repositories](https://code.claude.com/docs/en/plugin-marketplaces.md#private-repositories), observed 2026-09-14); both strict validations below pass; a clean install from an empty profile runs marketplace add, install, a new session or `/reload-plugins`, then skill, command and hook discovery plus one real invocation, with the clone transport (SSH or HTTPS) recorded. | State: BLOCKED. The repository is private and its unauthenticated URL returns 404 in `docs/publication/link-checks.json`; visibility is blocked by an unresolved Git history finding. |
| Claude community marketplace submission | A public repository; a recorded clean-package `claude plugin validate` result; maintainer form access (claude.ai form: Team or Enterprise with directory management; Console form: Developer, Admin or Owner role). | Submit the plugin root through [claude.com/docs/plugins/submit](https://claude.com/docs/plugins/submit); packet [`docs/publication/claude-community.md`](../docs/publication/claude-community.md). | Go condition: public repository and a passing `claude plugin validate` on the submitted root; acceptance is not guaranteed. Observed 2026-09-14: [code.claude.com/docs/en/plugins](https://code.claude.com/docs/en/plugins.md) says approved plugins "are pinned to a specific commit SHA" with CI bumping the pin as commits are pushed, and [claude.com/docs/plugins/submit](https://claude.com/docs/plugins/submit) says updates pushed to the repository "are picked up automatically", so every default-branch push after approval counts as publication. The pages name `claude-community` and `claude-plugins-official` as targets; neither is promised. | State: BLOCKED. Needs a public repository, the clean-package validation and maintainer form access. |
| Codex personal marketplace | Codex CLI 0.154.0; `node` on `PATH`; plugin at `~/plugins/agentic-sdlc`. | See [`../.codex-plugin/README.md`](../.codex-plugin/README.md): `codex plugin add agentic-sdlc@personal`, trust the hooks in `/hooks`, then run the hook trust check. | Go condition: catalog `~/.agents/plugins/marketplace.json` with top-level `"name": "personal"`; native `plugin/read` shows 16 skills and `hooks/list` shows 8 hooks; hook trust granted through the native `/hooks` protocol. | State: GAP. Final-package discovery and real-profile trust are not yet recorded. |
| OpenAI public directory | Maintainer-verified identity and Apps Management Write (`api.apps.write`). | Build the skills-only archive with `python3 scripts/build_release.py --output <zip> --skills-only`, verify it, then upload; see [`../.codex-plugin/README.md`](../.codex-plugin/README.md). | Go condition: a verified skills-only archive; submission, acceptance and publication are three separate stages, and the listing changes after publication only through a newly reviewed version. | State: BLOCKED. Needs verified identity, `api.apps.write` and a verified skills-only archive. |

### Verification

Native Claude validation is two separate checks:

```bash
claude plugin validate .claude-plugin/marketplace.json --strict
claude plugin validate .claude-plugin/plugin.json --strict
```

Marketplace validation checks no plugin contents; hook-config validity comes from the repository tests (`tests/test_hooks_policy.py`, `tests/test_skill_integration.py`). A strict `plugin.json` exit 1 in a working tree caused by an untracked local agent instruction file is not the clean-package result; that result comes from a package extracted from a verified release archive.

## Requirements

- Claude Code with local plugin/marketplace support. Versions re-captured on 2026-09-15: Windows 2.1.271 and WSL Ubuntu 24.04 2.1.269; see [CLI versions by platform](../docs/runtime-adapter.md#cli-versions-by-platform) for the last live-tested versions.
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

## Artifact Layouts And Per-Package Evidence

Work-package artifacts resolve in two layouts: the legacy flat `docs/agentic-sdlc/{specs,plans}/<id>.md` (back-compat, unchanged) and the per-package canonical `docs/agentic-sdlc/<slug>/{spec,plan,evidence}/<work_id>.md`, where `<slug>` is lowercase kebab-case `^[a-z0-9][a-z0-9-]{0,63}$` and never a reserved name (`specs`, `plans`, `evidence`, `notes`, `spec`, `plan`).

Per-package evidence persists to `docs/agentic-sdlc/<slug>/evidence/<work_id>.md` — per-package only (flat packages get no evidence), overwritten in place per run (single canonical file, last run wins), git-ignored, and with no validator (it never gates resolution). That evidence write is performed by the main pipeline finalize step, not the read-only `implementation-auditor` sub-agent.

Per-package plan change-detection runs as a filesystem scan, not a `git status` query: new generated plans can be git-ignored, so the resolver scans the filesystem; published plugin documentation is tracked separately.

## Troubleshooting

See [`../docs/troubleshooting.md`](../docs/troubleshooting.md) for plugin visibility, hook execution, missing Node, protected branch behavior, secret scanner warnings, non-git workspaces, and eval failures.
