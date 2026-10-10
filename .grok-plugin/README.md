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
need Python 3.12+ and Git. Run:

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

To register this package as a personal marketplace, additionally run:

```text
grok plugin marketplace add <package-directory>
grok plugin marketplace list
grok plugin list --json --available
```

Use `grok plugin install agentic-sdlc --trust` only when the available list
contains that entry. Historical name lookup for this catalog's `source: "./"`
failed on Grok 1.0.34; use the directory install above if it is absent.
Remote GitHub/git sources are documented too; source access and organization
policy still apply. See [distribution details](../docs/publication/grok-marketplace.md).

Installation requires `--trust`, and the plugin must be enabled. Pick up changes
with `r` in the Plugins tab (`/plugins`) or a new session.

## Using it and paths

- Invoke `/using-agentic-sdlc`, or `/agentic-sdlc:using-agentic-sdlc` on a name collision.
- The router selects the smallest sufficient skill; the pipeline owns the full SDLC envelope.
- `git-safety-check` is the manual command under `commands/`.
- Hook launchers are fixed `node -e` strings. Node reads `process.env.GROK_PLUGIN_ROOT`,
  joins a fixed handler name and imports a file URL; installed-path bytes never
  become shell command text. Grok does not provide Codex's `commandWindows` selector.
- Grok supplies `GROK_PLUGIN_ROOT` and the `CLAUDE_PLUGIN_ROOT` alias to plugin
  hooks. For skill helpers, resolve the installed skill/root rather than assuming
  the working project contains this repository.

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

For an added marketplace, refresh it; then update the installed plugin:

```text
grok plugin marketplace update mrbekox
grok plugin update agentic-sdlc
```

For a refreshed local package, repeat the directory install when there is no
remote update to fetch. Reload the Plugins tab or start a new session.
`scripts/bump_version.py` tracks both Grok manifest versions and `VERSION`;
`tests/test_grok_packaging.py` checks their agreement.

Static packaging and relocated handler replays do not prove native install,
trust, update or skill-trigger behavior. No official catalog submission or
release tagging is performed here. Follow the
[publication checklist](../docs/publication/grok-marketplace.md).

## Official sources (checked 2026-10-10)

- [Plugin install, update and catalogs](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/09-plugins.md)
- [Hook fields, environments and shell behavior](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/10-hooks.md)
- [Official marketplace contribution requirements](https://github.com/xai-org/plugin-marketplace/blob/main/CONTRIBUTING.md)
