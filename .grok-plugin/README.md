# AGENTIC-SDLC for Grok CLI (experimental adapter)

Grok is included in the current five-platform distribution preparation. Its
runtime coverage remains experimental: historically it was **not a 0.4.3 release target**.
See the [current distribution guide](../docs/publication/multi-platform-distribution.md)
for installation, evidence limits and the remaining publication steps.

This package shares the root `skills/`, `commands/` and `agents/` sources. The
Grok manifest is `.grok-plugin/plugin.json`; its personal marketplace index is
`.grok-plugin/marketplace.json` (`name=mrbekox`). Keep the complete package,
including `hooks/`, `scripts/` and `contracts/`.

## Local install

Use an extracted full package directory, with Grok and Node in the same OS
environment and `node` available on the hook shell PATH. Helper workflows also
need Python 3 (3.12 is tested; the helpers skills run are kept import-compatible with 3.8
by a static check, not a runtime test) and Git. Run:

```text
grok plugin install <package-directory> --trust
grok plugin enable agentic-sdlc
grok plugin details agentic-sdlc
grok inspect --json
```

The documented directory install does not depend on the maintainer's checkout.
A historical Grok 1.0.34 clone install failed while copying `.git`; an extracted
package avoids copying repository internals. That observation is not a fresh
installer test on Grok 1.0.50.

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

Installation requires `--trust`. Pick up changes with `r` in the Plugins tab
(`/plugins`) or a new session.

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
`hookSpecificOutput.permissionDecision: "deny"`. The branch guard's warn/block
mode follows the configured house policy. No MCP server or network integration
is declared. Durable plugin state belongs under `GROK_PLUGIN_DATA`.

Write scanning, startup and Stop/flow readers remain unwired: this candidate
does not verify their Grok payload/reader contracts. The Claude and Codex
transcript readers must not be wired merely because Grok exposes a Stop event.

Grok workflows live in project `.grok/workflows/*.rhai` or user
`~/.grok/workflows/*.rhai` catalogs. The repository contains
`spec-plan-draft.rhai`, `multi-lens-review.rhai` and `skill-draft.rhai`, but
plugin installation does not place them into a customer's workflow catalog.
If a named script is present and workflows are enabled, use
`/workflow spec-plan-draft` (or the other named loop). Otherwise use
`spawn_subagent` with author → critic → revise, saved artifacts and
`scripts/validate_artifacts.py`. Do not call Claude JS `Workflow` on Grok.

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

Native Windows install/remove, temporary trust and moving-branch update evidence
is recorded in [current readiness](../docs/publication/marketplace-readiness-2026-10-11.md).
It does not prove native hook delivery or skill-trigger behavior. No official catalog submission or
release tagging is performed here. Follow the
[publication checklist](../docs/publication/grok-marketplace.md).

## Uninstall

Run `grok plugin uninstall agentic-sdlc` (Grok does not prompt). Add
`--keep-data` when plugin data must survive removal. Reload the Plugins tab or
start a new session. Keep unrelated plugins/settings and the source directory;
marketplace removal is a separate operation. See the
[lifecycle guide](../docs/publication/multi-platform-distribution.md).

## Official sources (checked 2026-10-10)

- [Plugin install, update and catalogs](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/09-plugins.md)
- [Hook fields, environments and shell behavior](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/10-hooks.md)
- [Official marketplace contribution requirements](https://github.com/xai-org/plugin-marketplace/blob/main/CONTRIBUTING.md)
