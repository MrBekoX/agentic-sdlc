# AGENTIC-SDLC for Grok CLI (experimental adapter)

Grok CLI is an experimental adapter. It was **not a 0.4.3 release target**; the
next release includes it as an experimental adapter. Native install, discovery,
refresh and uninstall passed on Grok CLI 1.0.50 on Windows, Linux and macOS, and
hook registration and delivery of the three guards passed on Grok CLI 1.0.92 on Linux
(see [Native evidence](#native-evidence)); live skill behavior is not proven. See the [current distribution guide](../docs/publication/multi-platform-distribution.md)
for installation, evidence limits and the remaining publication steps.

This package shares the root `skills/`, `commands/` and `agents/` sources. The
Grok manifest is `.grok-plugin/plugin.json`; its personal marketplace index is
`.grok-plugin/marketplace.json` (`name=mrbekox`). Keep the complete package,
including `hooks/`, `scripts/` and `contracts/`.

## Local install

Get the package: a package directory is an extracted copy of this repository's
files. Clone the repository, or download and extract its source ZIP or a release
archive (maintainers build one with `python3 scripts/build_release.py --output agentic-sdlc.zip`;
GitHub Releases are not published yet). Prefer a path without `#`: Grok reads
`#` specially (see the `#` note under [Update and versioning](#update-and-versioning)).
Nothing inside the folder needs editing.

Use the full package directory, with Grok and Node in the same OS
environment and `node` available on the hook shell PATH. Helper workflows also
need Python 3 (3.12 is tested; the helpers skills run are kept import-compatible with 3.8
by a static check, not a runtime test) and Git. Run:

```text
grok plugin install <package-directory> --trust
grok plugin details agentic-sdlc
grok inspect --json
```

`grok inspect --json` lists 17 plugin skills. The directory install does not
depend on the maintainer's checkout. The native runs on Grok 1.0.50 used an
extracted package; a clone install was not tested on 1.0.50. Historical note: a Grok
1.0.34 clone install failed while copying `.git`; if a clone install fails, use an
extracted archive.

The directory install also enables the plugin; `grok plugin enable agentic-sdlc`
is only needed after a `grok plugin disable`. Use an absolute or `./`-relative
package path.

The shipped catalog `.grok-plugin/marketplace.json` names this repository as a
remote `url` source: Grok cannot point a catalog entry at the catalog's own root
(`"./"` parses as an empty path and the entry is skipped — observed on 1.0.50).
Once the repository is public, register it with
`grok plugin marketplace add https://github.com/MrBekoX/agentic-sdlc`, then:

```text
grok plugin marketplace list
grok plugin list --json --available
grok plugin install agentic-sdlc --trust
```

Grok names a marketplace after its source's last path segment, not the catalog
`name`, so use the name `grok plugin marketplace list` prints. Source access and
organization policy still apply. See [distribution details](../docs/publication/grok-marketplace.md).
The shipped `url` source carries no `sha`. A personal `grok plugin marketplace add`
accepts that, but the official xai-org/plugin-marketplace requires a full
40-character `sha` on every `url` source, and an install under `[marketplace] require_sha = true`
(a `[marketplace]` table in the Grok config) or `GROK_MARKETPLACE_REQUIRE_SHA=1` refuses an unpinned source (marketplace README and
`09-plugins.md`, checked 2026-11-21). Pin a real commit before any official submission.

Installation requires `--trust`. Pick up changes with `r` in the Plugins tab
(`/plugins`) or a new session.

Folder trust also gates the guards. On Grok 1.0.92 `grok inspect --json` lists the
plugin's `hooks/hooks-grok.json` with `waitsForFolderTrust: true`: an interactive
session runs plugin hooks only in a trusted folder (`/hooks-trust`, or launch with
`--trust`), and until then they are skipped without an error. A headless `grok -p` run
counts the folder as trusted for your own and plugin hooks (`10-hooks.md`, read
2026-11-22). Trust the repository before relying on the guards in the TUI.

## Using it and paths

- Invoke `/using-agentic-sdlc`, or `/agentic-sdlc:using-agentic-sdlc` on a name collision.
- The router selects the smallest sufficient skill; the pipeline owns the full SDLC envelope.
- `git-safety-check` is the manual command under `commands/`.
- Hook launchers are fixed `node -e` strings. Node reads `process.env.GROK_PLUGIN_ROOT`,
  joins a fixed handler name and imports a file URL; installed-path bytes never
  become shell command text. Grok does not provide Codex's `commandWindows` selector.
- Grok supplies `GROK_PLUGIN_ROOT` and the `CLAUDE_PLUGIN_ROOT` alias to plugin
  hooks only. A skill the model picks is read as plain text with no variable
  substitution, so skills resolve helpers with their **Plugin root** rule: the
  folder two levels above the `SKILL.md` path shown in the skill listing.

## Hooks and limits

`hooks/hooks-grok.json` wires three `PreToolUse` command guards on
`Bash|run_terminal_command`: `scan-commit.mjs`, `destructive-command-guard.mjs`
and `branch-guard.mjs`. They read stdin JSON (`toolInput.command`, with
`tool_input.command` fallback) and local Git state; guards can return
`hookSpecificOutput.permissionDecision: "deny"`, which Grok honors at any exit code
(`10-hooks.md`); the model sees `Hook denied: <reason>`. The branch guard's warn/block
mode follows the configured house policy. No MCP server or network integration
is declared. Durable plugin state belongs under `GROK_PLUGIN_DATA`.

Write scanning, startup and Stop/flow readers remain unwired: this candidate
does not verify their Grok payload/reader contracts. The Grok hook guide
(`10-hooks.md`, checked 2026-11-21) gives `Stop` a camelCase payload with
`stopHookActive` and `lastAssistantMessage` (a script reading `.stop_hook_active`
must switch to `.stopHookActive`), and for `SessionStart` stdout is ignored. Among
the shared Stop handlers, the completion and flow guards read Claude transcripts or
Codex rollouts, and all three (they and `worktree-scan.mjs`) test the snake_case
`stop_hook_active`. `session-start.mjs` delivers its context on stdout. Neither
works on Grok as written, so both stay unwired until a Grok output mode exists. The Claude and Codex transcript readers must not be wired merely
because Grok exposes a Stop event.

Grok workflows live in project `.grok/workflows/*.rhai` or user
`~/.grok/workflows/*.rhai` catalogs. The repository contains
`spec-plan-draft.rhai`, `multi-lens-review.rhai` and `skill-draft.rhai`, but
plugin installation does not place them into a customer's workflow catalog.
If a named script is present and workflows are enabled, use
`/workflow spec-plan-draft` (or the other named loop). Otherwise use
`spawn_subagent` with author → critic → revise, saved artifacts and
`scripts/validate_artifacts.py`. Do not call Claude JS `Workflow` on Grok.

The flow runner's spec/plan loop needs no catalog entry. The runner writes spec and
plan in the main loop by default, and its own loop (`start --option loop`) is the
default loop; the Grok workflow engine runs only when the user asks for it
explicitly and the reason is recorded. When a work package's draft step runs as
a Grok workflow, `sdlc next` copies the plugin's
`workflows/grok/spec-plan-draft.rhai` byte for byte into the package
(`docs/agentic-sdlc/<slug>/draft/engine/spec-plan-draft.rhai`), records its
sha256 and prints the launch: the `workflow` tool with
`source: {type: "script_path"}` naming that copy, the runner's args and an
`agent_budget` that covers every agent call of the loop. Launch that staged copy
as printed. Its read-only author and critic agents read the prompts the runner
staged, and a `draft-scribe` agent writes their answers and runs the runner's
`draft-check` and `ingest-draft` commands. Without the workflow tool, the
runner prints one role card at a time for `spawn_subagent` instead.
The staged script has not run on a live Grok client yet: the gate pins its
structure, and a reviewer ran it under standalone Rhai 1.27 beside the Claude
engine.

Two `spec-plan-draft.rhai` files exist on purpose; they are different programs
with different consumers, not copies:

- `.grok/workflows/spec-plan-draft.rhai` is the 0.6.0 project-catalog script. A
  Grok session in a clone of this repository reaches it with
  `/workflow spec-plan-draft`. It is not delivered by `grok plugin install`,
  because `plugin.json` has no workflows component.
- `workflows/grok/spec-plan-draft.rhai` is the 0.7.0 runner engine. The flow
  runner stages it into the work package byte for byte and records its sha256;
  it ships in the plugin package.

Merging them would break the engine contract (`tests/test_grok_rhai_workflows.py`)
and the byte-for-byte ship check. The catalog script is to be removed in a
follow-up, once the skills that name `/workflow spec-plan-draft` move onto the
runner.

## Update and versioning

For an added Git marketplace, refresh it by the name `grok plugin marketplace list`
shows (the source's last path segment), then update the installed plugin:

```text
grok plugin marketplace update <source-name>
grok plugin update agentic-sdlc
```

On Grok 1.0.50, local `plugin update` does not recopy the installed directory (it
reports the plugin as already live), and reinstalling the same source reports
"already installed". To refresh a local install, review retained data, run
`grok plugin uninstall agentic-sdlc`, then install the refreshed directory again
(verified natively on 1.0.50); reload the Plugins tab or start a new session.
A moving Git branch supports a genuine update, observed in an offline Git fixture. Paths
containing `#` should be installed with `grok plugin install . --trust` from inside
that directory.
`scripts/bump_version.py` tracks both Grok manifest versions and `VERSION`;
`tests/test_grok_packaging.py` checks their agreement.

## Uninstall

Run `grok plugin uninstall agentic-sdlc` (Grok does not prompt). Add
`--keep-data` when plugin data must survive removal. Reload the Plugins tab or
start a new session. Keep unrelated plugins/settings and the source directory;
marketplace removal is a separate operation. See the
[lifecycle guide](../docs/publication/multi-platform-distribution.md).

## Native evidence

Grok CLI 1.0.50 passed the native lifecycle on Windows, Linux and macOS on
2026-10-12 in isolated profiles: `grok plugin install --trust`, `grok inspect --json`
listing 17 plugin skills, uninstall plus reinstall of a version-bumped copy, and
uninstall, with unrelated files kept (E3, E8, E13 in the
[compatibility matrix](../docs/publication/compatibility-matrix.md)). Temporary
trust and the moving-branch update fixture are recorded in
[marketplace readiness](../docs/publication/marketplace-readiness-2026-10-11.md).
Those lifecycle runs did not exercise hooks.

Hook evidence, Grok CLI 1.0.92 on Linux, 2026-11-22 (E32, E33): the CLI from the
official `x.ai/cli/install.sh` installer into a separate folder with an isolated home;
`grok plugin install --trust` of the package; `grok inspect --json` lists the plugin hook
file. Headless `grok -p` turns in default mode, with a `[model.*]` entry pointing at a
local OpenAI-compatible endpoint that scripts one `run_terminal_command` call (no xAI
account or login), were refused with `Hook denied: ...` by each of the three guards
(`git reset --hard`, a commit on `main` in block mode, a commit of a staged secret), the
uncommitted change survived, and with the plugin uninstalled the same call ran. Skill
triggering and Grok-model behavior were not measured; a turn with a Grok model needs
`grok login` or an xAI API key.
No official catalog submission or release tagging is performed here. Follow the
[publication checklist](../docs/publication/grok-marketplace.md).

## Official sources (checked 2026-10-10)

- [Plugin install, update and catalogs](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/09-plugins.md)
- [Hook fields, environments and shell behavior](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/10-hooks.md)
- [Official marketplace contribution requirements](https://github.com/xai-org/plugin-marketplace/blob/main/CONTRIBUTING.md)
