# Compatibility matrix

Snapshot of how `agentic-sdlc` installs and runs on each supported runtime and operating
system. A cell says `passed` only when a recorded run in the [evidence log](#evidence-log)
backs it; every other cell is `not-run` with the reason. Reproduce a native lifecycle check
with `python3 scripts/check_native_lifecycle.py --package <extracted-package-directory>`
(isolated profiles, no model calls). Install, update and uninstall details live in
[multi-platform distribution](multi-platform-distribution.md); capability fallbacks live in
[runtime-adapter.md](../runtime-adapter.md#capability-fallbacks-on-all-five-runtimes).

All evidence below binds to one candidate package built from commit `02de556` of the
`fix/cross-platform-native-distribution` branch on 2026-10-12 (full archive sha256
`384c883c27f546ba62a7e95e9ba061a25a64089ebdaddb57e0c3b168edad3cfd`, archive verify and portability
check passed); later commits on the branch change only this document. Linux rows ran `scripts/check_native_lifecycle.py`; the Windows test host has no
Python, so its rows ran a shell harness that drives the Windows CLIs with the same isolation and
lifecycle steps (install, discovery, version-bumped refresh, uninstall, unrelated settings kept),
but its checks are lighter: it sees the refresh through a marker appended to one skill file, where
the checker compares every installed byte and the recorded version, and it checks the unrelated
setting once at the end instead of after every step. For Codex (E2) it also installs from a local
marketplace and counts the 16 skill folders in the installed copy, where the checker uses the
personal catalog and asks the app-server `skills/list` for 17 entries. No row ran a model turn or
granted Codex hook trust (Grok installs pass `--trust` inside the disposable profile only), and
every run left the host's real Claude, Codex, Grok and Kimi profiles unchanged. Repeat on the release commit before
publication.

## Platforms

| Platform | Native mechanism | Install | Update | Uninstall | Consent / trust | Limits |
|---|---|---|---|---|---|---|
| Claude Code | Plugin + marketplace (`.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`) | `claude plugin marketplace add <package-directory or MrBekoX/agentic-sdlc>`, then `claude plugin install agentic-sdlc@mrbekox` | `claude plugin marketplace update mrbekox`, then `claude plugin update agentic-sdlc@mrbekox` (only when the version changes) | `claude plugin uninstall agentic-sdlc@mrbekox` | Hooks run once the plugin is installed and enabled | Repository install needs a public or authorized repository |
| Codex | Plugin with compatibility manifest (`.codex-plugin/plugin.json`) and a marketplace (Claude-layout catalog or `~/.agents/plugins/marketplace.json`) | `codex plugin marketplace add <package-directory or MrBekoX/agentic-sdlc>`, then `codex plugin add agentic-sdlc@mrbekox` | `codex plugin marketplace upgrade <name>` for a Git catalog; repeat `codex plugin add` for a local source | `codex plugin remove agentic-sdlc@<marketplace-name>` | Each bundled hook must be trusted in `/hooks` before it runs | No `codex plugin update`; keep `#` out of local source paths |
| Kimi Code | Plugin (`.kimi-plugin/plugin.json`) with an optional custom catalog (`marketplace-kimi.json`) | `/plugins install <package-directory or GitHub URL>` in the TUI | Reinstall the changed directory, or Enter on an available update in `/plugins` | `/plugins remove agentic-sdlc` (managed copy stays on disk) | Hooks run once the plugin is installed | PreToolUse command guards only; bare skill names; warn-only output hidden |
| Grok CLI | Plugin (`.grok-plugin/plugin.json`) with a catalog (`.grok-plugin/marketplace.json`, remote `url` entry) | `grok plugin install <package-directory> --trust` (also enables) | Local: uninstall then install the new copy; Git catalog: `grok plugin marketplace update <source-name>` then `grok plugin update agentic-sdlc` | `grok plugin uninstall agentic-sdlc` (no prompt; `--keep-data`) | `--trust` at install | PreToolUse command guards only; Rhai workflows are not delivered by the plugin |
| ZCode | Plugin (`.zcode-plugin/plugin.json`) with the root `marketplace.json` catalog | Settings → Plugins → Add marketplace (root `marketplace.json` as a file source) → Install | Refresh the marketplace → Manage installed → Check for updates (only when the version changes) | Settings → Plugins → Manage installed → Uninstall | Newly installed plugins are enabled by default, so hooks run at install | Install is a desktop UI flow (the bundled agent CLI manages plugins only in Electron's Node mode, not a documented user path); Stop/flow guards not wired; workflows not deliverable |

## Verification by platform and operating system

| Platform | Windows | Linux | macOS |
|---|---|---|---|
| Claude Code | passed (E1, 2026-10-12, 2.1.296) | passed (E5, 2026-10-12, 2.1.282) | not-run: no macOS host; macOS was skipped at the maintainer's request on 2026-10-11 |
| Codex | passed (E2, 2026-10-12, codex-cli 0.162.1) | passed (E6, 2026-10-12, codex-cli 0.156.1) | not-run: no macOS host; macOS was skipped at the maintainer's request on 2026-10-11 |
| Kimi Code | passed (E4, 2026-10-12, 2.1.1) | not-run: the CLI is not installed on the Linux test host | not-run: no macOS host; macOS was skipped at the maintainer's request on 2026-10-11 |
| Grok CLI | passed (E3, 2026-10-12, 1.0.50) | not-run: the CLI is not installed on the Linux test host | not-run: no macOS host; macOS was skipped at the maintainer's request on 2026-10-11 |
| ZCode | not-run: the checker has no ZCode recipe and this candidate was not installed in ZCode; the desktop bundle's agent CLI 0.16.9 passed isolated validate/install/update/uninstall on base commit `3bcbf7b` on 2026-10-11 ([readiness ledger](marketplace-readiness-2026-10-11.md)) | not-run: no ZCode build on the Linux test host | not-run: no macOS host; macOS was skipped at the maintainer's request on 2026-10-11 |

## Evidence log

| ID | Date | Platform | OS | CLI version | Check | Result |
|---|---|---|---|---|---|---|
| E1 | 2026-10-12 | Claude Code | Windows | 2.1.296 | native_claude: isolated CLAUDE_CONFIG_DIR, marketplace add + install from a path with a space and non-ASCII characters, `claude plugin details` lists 17 skills (16 + command), version-bumped refresh observed in the installed bytes, uninstall, unrelated settings key kept | native_claude=passed |
| E2 | 2026-10-12 | Codex | Windows | codex-cli 0.162.1 | native_codex: isolated CODEX_HOME, local marketplace add + `codex plugin add`, installed copy has 16 skills, repeated add recopies the bumped source, `codex plugin remove` deletes the copy, unrelated profile kept | native_codex=passed |
| E3 | 2026-10-12 | Grok CLI | Windows | 1.0.50 | native_grok: isolated GROK_HOME, `grok plugin install --trust`, `grok inspect --json` lists 17 plugin skills, uninstall + reinstall of the bumped copy observed, uninstall removes the record, unrelated file kept | native_grok=passed |
| E4 | 2026-10-12 | Kimi Code | Windows | 2.1.1 | native_kimi: isolated KIMI_CODE_HOME, local `kimi web` REST API with its bearer token, install reports 16 skills / 1 command / 3 hooks with state ok, reinstall of the bumped copy observed in the managed copy, remove empties the list, unrelated file kept | native_kimi=passed |
| E5 | 2026-10-12 | Claude Code | Linux | 2.1.282 | native_claude via `scripts/check_native_lifecycle.py --platform all` (WSL Ubuntu 24.04): isolated install, 17 skills discovered, version-bumped refresh observed, uninstall, sentinel kept | native_claude=passed |
| E6 | 2026-10-12 | Codex | Linux | codex-cli 0.156.1 | native_codex via `scripts/check_native_lifecycle.py --platform all` (WSL Ubuntu 24.04): isolated local catalog install, app-server `skills/list` reports 17 plugin skills, recopy of the bumped source observed, remove, sentinel kept | native_codex=passed |
