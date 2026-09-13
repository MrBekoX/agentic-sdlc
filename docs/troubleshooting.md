# Troubleshooting

## Claude Code Does Not See The Skills

Check:

1. The repo is installed as a Claude Code plugin or local marketplace source.
2. `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` exist.
3. Skills are under root `skills/`, not `.claude/skills/`.
4. The session was restarted after plugin installation.
5. The runtime guide in [`../.claude-plugin/README.md`](../.claude-plugin/README.md) matches the installed path.

## Codex Does Not See The Plugin

Check:

1. The personal marketplace exists at `~/.agents/plugins/marketplace.json`.
2. Its `agentic-sdlc` entry points at `~/.codex/plugins/agentic-sdlc`.
3. `~/.codex/plugins/agentic-sdlc` is a real copy or symlink/junction to this plugin root.
4. The plugin was installed with `codex plugin add agentic-sdlc@personal`.
5. The manifest contains `"skills": "./skills/"` and `"hooks": "./hooks/hooks-codex.json"`.
6. Skills are under root `skills/`, not `.codex/skills/`.
7. The runtime guide in [`../.codex-plugin/README.md`](../.codex-plugin/README.md) matches the installed path.

`codex plugin add agentic-sdlc@personal` is the supported local install. Codex 0.153.0+ also has `codex plugin marketplace add` for a Codex-shaped catalog. This repo's `.claude-plugin/marketplace.json` is Claude's marketplace schema; do not add that file as a Codex marketplace.

## Claude Hooks Do Not Run

Check:

1. `.claude-plugin/plugin.json` declares `"hooks": "./hooks/hooks-claude.json"`.
2. `hooks/hooks-claude.json` is present in the plugin root.
3. `node` is on `PATH`.
4. `${CLAUDE_PLUGIN_ROOT}` resolves in the Claude Code plugin runtime.
5. The hook event matches the tool invocation. For example, `scan-commit.mjs` only runs for `git commit*`.

## Codex Hooks Are Not Running

Check:

1. `hooks/hooks-codex.json` is valid Codex hook JSON and has only the top-level `hooks` object, and `.codex-plugin/plugin.json` declares `"hooks": "./hooks/hooks-codex.json"`.
2. The plugin was reinstalled after hook config changes.
3. Start a new Codex thread so the declared Codex hook config is reloaded.
4. Open `/hooks` and review/trust the plugin-bundled commands if Codex marks them pending review.
5. `node` is on `PATH`.
6. `${PLUGIN_ROOT}` resolves in the Codex plugin runtime.

Codex wires blocking `PreToolUse` guards, `SessionStart`, and advisory/env-gated `Stop` backstops. If startup context works but a command guard does not, compare the event/matcher in `hooks/hooks-codex.json`, confirm `node` is available, and run the hook script with a sanitized sample payload. Remember that unrecognized literal-write forms and internal parse errors deliberately fail open.

## Branch Guard Only Warns

This is the default in Claude Code. To make protected branch commit/push attempts block:

```bash
AGENTIC_BRANCH_GUARD_BLOCK=true
```

The branch guard fails open if git is unavailable or the workspace is not a git repo.

## Completion Claim Guard Only Warns

This is the default in Claude Code. To block final completion claims that skip `completion-claim-gate`:

```bash
AGENTIC_COMPLETION_GATE_BLOCK=true
```

This deterministic guard complements the judgment gate. It does not replace `completion-claim-gate`.

## Flow Guard Only Warns

This is the default in Claude Code for `flow-order-guard.mjs` and `flow-step-guard.mjs`. To deny source edits or block Stop when active implementation-flow evidence is missing:

```bash
AGENTIC_FLOW_GATE_BLOCK=true
```

The flow guards re-derive evidence from the current transcript, validated `docs/agentic-sdlc/specs/` and `docs/agentic-sdlc/plans/` artifacts, real tool calls, and real commands. Prose such as "I ran the gate" does not satisfy a required step.

## Secret Scanner False Positive

The scanners never print secret values. If a warning is false positive:

1. Confirm the value is not a real credential.
2. Prefer environment variables or secret stores.
3. If you must bypass a hook temporarily, use runtime hook controls and document why.

## Destructive Command Blocked

`destructive-command-guard.mjs` blocks deterministic high-risk commands such as:

- `git reset --hard`
- forceful `git clean`
- recursive `rm` forms such as `rm -r`, `rm -rf`, `rm --recursive`, `/bin/rm -rf`, `sudo rm -rf`, `sudo FOO=bar rm -rf`, `command rm -rf`, `env FOO=bar rm -rf`, and `env -u FOO rm -rf`
- `Remove-Item -Recurse`, common aliases such as `ri`/`del`/`rd`/`rmdir`, and simple `powershell`/`pwsh -Command` wrappers

Use a scoped, reviewed command and get explicit approval for destructive cleanup.

## Tests Skip Node Checks

`tests/test_static_node.py` skips JavaScript syntax checks if `node` is unavailable. A skip is not a pass. Install Node before release verification.

## Workspace Is Not A Git Repo

Git-aware flow steps should be skipped with a note. To enable branch, commit, PR, worktree, and review-package behavior, run in a real git checkout.

## Codex Trigger Eval Is Not Comparable To Claude

`scripts/run_codex_trigger_eval.py` is a route-classifier proxy because Codex does not expose Claude-style `Skill` tool events. Do not compare Codex trigger rates directly to Claude trigger rates.

## Codex Plugin Warnings Mention Other Plugins

`codex exec` may print warnings from other installed user plugins, such as `defaultPrompt[0] must be at most 128 characters` or icon path warnings. If this repo's `.codex-plugin/plugin.json` is valid and the warning names another plugin, treat it as unrelated noise.

## Procedure Eval Reports Missing Skill Or Workflow

Check the runtime:

- Claude procedure evidence should show native `Skill` and, for pipeline spec/plan, `Workflow` events.
- Codex procedure evidence should show the embedded author/critic adapter path and validator commands instead of Claude Workflow events.

If the runtime lacks a native mechanism, the transcript must include an explicit `Delegation Degraded: <capability> unavailable` note plus the smallest safe fallback.

## Per-Package Artifacts And Evidence

Work-package artifacts resolve in two layouts: the legacy flat `docs/agentic-sdlc/{specs,plans}/<id>.md` (back-compat, unchanged) and the per-package canonical `docs/agentic-sdlc/<slug>/{spec,plan,evidence}/<work_id>.md`, where `<slug>` is lowercase kebab-case `^[a-z0-9][a-z0-9-]{0,63}$` and never a reserved name (`specs`, `plans`, `evidence`, `notes`, `spec`, `plan`).

Per-package evidence persists to `docs/agentic-sdlc/<slug>/evidence/<work_id>.md` — per-package only (flat packages get no evidence), overwritten in place per run (single canonical file, last run wins), git-ignored, and with no validator (it never gates resolution). That evidence write is performed by the main pipeline finalize step, not the read-only `implementation-auditor` sub-agent.

If a brand-new per-package plan is not discovered by `resolve_work_package.py`, remember that per-package plan change-detection runs as a filesystem scan, not a `git status` query: new generated plans can be git-ignored, so the resolver scans the filesystem; published plugin documentation is tracked separately.
