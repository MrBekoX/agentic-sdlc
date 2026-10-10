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

1. The selected marketplace is discoverable; inspect `codex plugin marketplace list`.
2. Its `agentic-sdlc` entry resolves to the intended source package.
3. The installed package contains the shared root `skills/` tree and its declared hooks.
4. The plugin was installed with `codex plugin add agentic-sdlc@<marketplace-name>`, using the actual marketplace name.
5. The manifest contains `"skills": "./skills/"` and `"hooks": "./hooks/hooks-codex.json"`.
6. Skills are under root `skills/`, not `.codex/skills/`.
7. The runtime guide in [`../.codex-plugin/README.md`](../.codex-plugin/README.md) matches the installed path.

The `@personal` catalog in the [Codex guide](../.codex-plugin/README.md#install) is a local authoring example, not an install-path requirement. Current Codex supports Git/repo marketplace sources and the legacy `.claude-plugin/marketplace.json` layout ([packaging guide](https://developers.openai.com/plugins/build/plugins), checked 2026-10-08); Git access still depends on repository visibility and authentication. Installing the same plugin from two sources can list it twice. Hook paths come from the installed `PLUGIN_ROOT`, not the marketplace source path or this checkout.

In that local example, `./plugins/agentic-sdlc` resolves under the home directory to `~/plugins/agentic-sdlc`, and installation uses `codex plugin add agentic-sdlc@personal`. Add a Git source with `codex plugin marketplace add owner/repo`. This repository's `.claude-plugin/marketplace.json` uses Claude's marketplace schema. These are catalog/source examples; hooks always use the installed package root.

## Claude Hooks Do Not Run

Check:

1. `.claude-plugin/plugin.json` declares `"hooks": "./hooks/hooks-claude.json"`.
2. `hooks/hooks-claude.json` is present in the plugin root.
3. `node` is on `PATH`.
4. `${CLAUDE_PLUGIN_ROOT}` resolves in the Claude Code plugin runtime.
5. The hook event matches the tool. `scan-commit.mjs` is wired on `Bash` and `PowerShell` and then decides for itself whether the command is a commit, including a git alias.

## Codex Hooks Are Not Running

Check:

1. `hooks/hooks-codex.json` is valid Codex hook JSON with a top-level `hooks` object (optional `description` metadata is supported), and `.codex-plugin/plugin.json` declares `"hooks": "./hooks/hooks-codex.json"`.
2. The plugin was reinstalled after hook config changes.
3. Start a new Codex thread so the declared Codex hook config is reloaded.
4. Open `/hooks` and review/trust the plugin-bundled commands if Codex marks them pending review; see [Codex hook trust](#codex-hook-trust) for each environment.
5. Node.js is on the hook process `PATH`: `node.exe` on native Windows, `node` on POSIX/WSL.
6. Codex exports `PLUGIN_ROOT` pointing at the installed package. All eight handlers have fixed environment-root launch code and a `commandWindows` override; see the [launch contract](runtime-adapter.md#codex-marketplace-hook-launch-contract).

Codex wires blocking `PreToolUse` guards, `SessionStart`, and advisory/env-gated `Stop` backstops. If startup context works but a command guard does not, compare the event/matcher in `hooks/hooks-codex.json`, confirm `node` is available, and run the hook script with a sanitized sample payload. Remember that unrecognized literal-write forms and internal parse errors deliberately fail open.

## Codex hook trust

Codex runs a non-managed plugin-bundled hook only after that hook is trusted. Trust each agentic-sdlc hook in the Codex `/hooks` view, then run the read-only post-install check from the installed plugin root and pass `--cwd <target-project>`, using the session project's path. Replace `agentic-sdlc@<marketplace-name>` below with your actual installed plugin ID. A fully trusted install prints `codex_hook_trust=trusted`.

| Environment | Codex config location | Trust step | `node` requirement | Check command | Verification state |
|---|---|---|---|---|---|
| Windows | `%USERPROFILE%\.codex\config.toml` | Open `/hooks` in Codex and trust each agentic-sdlc hook | `node.exe` on the `PATH` Codex runs hooks with | `py -3 scripts\check_codex_hook_trust.py --plugin agentic-sdlc@<marketplace-name> --cwd <target-project>` (or `python3`); needs Python 3.12 or newer | see ledger row `hook_trust_list_records` |
| macOS | `~/.codex/config.toml` | Open `/hooks` in Codex and trust each agentic-sdlc hook | `node` on the `PATH` Codex runs hooks with | `python3 scripts/check_codex_hook_trust.py --plugin agentic-sdlc@<marketplace-name> --cwd <target-project>` | not live-tested |
| Linux | `~/.codex/config.toml` | Open `/hooks` in Codex and trust each agentic-sdlc hook | `node` on the `PATH` Codex runs hooks with | `python3 scripts/check_codex_hook_trust.py --plugin agentic-sdlc@<marketplace-name> --cwd <target-project>` | not live-tested; WSL run pending in ledger row `hook_trust_list_records` |
| WSL | `~/.codex/config.toml` | Open `/hooks` in Codex and trust each agentic-sdlc hook | Native WSL `node` on `PATH`; load nvm before starting Codex if needed | `python3 scripts/check_codex_hook_trust.py --plugin agentic-sdlc@<marketplace-name> --cwd <target-project>`; pass `--codex <absolute-codex-path>` if needed | see ledger row `hook_trust_list_records` |

The check starts `codex app-server --stdio`, sends only `initialize`, `initialized` and `hooks/list`, writes no file, and prints five lines: `codex_hook_trust_plugin=`, `codex_hook_trust_counts=`, `codex_hook_trust_untrusted_events=`, `codex_hook_trust=` and `codex_hook_trust_next_step=`. It prints no hook key, hash or path.

- Exit 0: at least one hook of `--plugin` is listed and every one is `trusted` or `managed` (`codex_hook_trust=trusted`).
- Exit 1: at least one hook of `--plugin` is `untrusted` or `modified` (`codex_hook_trust=untrusted`); the events line names them.
- Exit 2: the plugin lists no hook (`codex_hook_trust=no-hooks`), a named error (`codex_hook_trust=error:<name>`, such as `codex_not_found`, `cwd_not_found`, `timeout`, `server_exited`, `rpc_error` or `malformed_response`), or a usage error, which prints usage on stderr and no five-line block. A `--plugin` value with a non-ASCII character is a usage error.

A bare `--codex` name (the default `codex`) is resolved only on absolute `PATH` entries and never from the current directory; relative or `~` entries are skipped, so a `codex` reachable only through one reports `error:codex_not_found`. Pass an explicit path with `--codex` in that case. On a timeout the check kills the server's whole process tree; on Windows it starts `taskkill` by its absolute `System32` path. On Windows the check needs Python 3.12 or newer, whose `shutil.which` handles `PATHEXT` for a path that has a directory part.

The check reports trust state only: it does not prove that a hook runs, that `node` is on `PATH`, or that a trusted hook has an effect. Trust is granted only through the `/hooks` review; no hand edit of `config.toml` and no trust-bypass flag is a trust step.

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

The `branch` and `review-result` steps are warn-only by design: they never block, even with `AGENTIC_FLOW_GATE_BLOCK=true`. For strict Codex evaluation, run the offline `python3 scripts/strict_flow_evidence.py --rollout <path> --cwd <dir>`, or set `AGENTIC_FLOW_STRICT_EVIDENCE=true` to make the live Codex `tests` evidence strict.

## Secret Scanner False Positive

The scanners never print secret values. If a warning is false positive:

1. Confirm the value is not a real credential.
2. Prefer environment variables or secret stores.
3. If the finding still looks wrong, stop and ask the maintainer. Do not look for a way to silence the scanner.

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
