# Multi-platform distribution candidate

All five adapters are included in this preparation. This is an installation and
publication checklist, not a public listing or a guarantee of live model behavior.
The historical 0.4.3 release verdict remains in `../release-evidence-0.4.3.md`.

## Install, update and uninstall

Prerequisites: use the runtime and Node.js in the same OS environment, with `node`
on the hook shell PATH (`node.exe` is selected by Codex on native Windows). Node.js
22 (CI) and 24 (local) are the tested versions; hooks fail open, so a missing `node`
silently disables the guards. Python 3 and Git are needed for helper and validation
workflows (`python3`, or `py -3` on Windows when `python3` is missing or is the
Microsoft Store alias). Python 3.12 is the tested version; the helpers skills run are
kept import-compatible with 3.8 by a static check, not by a runtime test. Maintainer and
release tooling (`build_release.py`, `bump_version.py`, the Codex hook trust check, the
eval runners) needs Python 3.12. Keep the full plugin directory: isolated SKILL.md copies
omit shared contracts, scripts, reviewers and skill references such as the four work-type
`references/core.md` files that the focused skills and `agentic-sdlc-pipeline` read. Skills locate the installed plugin with
the **Plugin root** rule (two levels above the loaded `SKILL.md`); per-runtime
fallbacks are in [runtime-adapter.md](../runtime-adapter.md#capability-fallbacks-on-all-five-runtimes).

A package directory is an extracted copy of this repository's files: clone the
repository, or download and extract its source ZIP or a release archive (maintainers
build one with `python3 scripts/build_release.py --output agentic-sdlc.zip`; GitHub
Releases are not published yet). Keep `#` out of the path (Codex and Grok read `#`
specially). Nothing inside the folder needs editing.

Repository-URL installs (`MrBekoX/agentic-sdlc`, `https://github.com/...`) need a
public repository or credentials the runtime can use; until the repository is public,
install from an extracted package directory. Current per-platform and per-OS results:
[compatibility matrix](compatibility-matrix.md).

| Platform | Install | Update | Included behavior and limits |
|---|---|---|---|
| Claude Code | In a shell, `claude plugin marketplace add <package-directory>` (or the public `MrBekoX/agentic-sdlc`), then `claude plugin install agentic-sdlc@mrbekox`; `claude --plugin-dir <package>` loads a package for one session without installing it | In a shell, `claude plugin marketplace update mrbekox`, then `claude plugin update agentic-sdlc@mrbekox`; in the session, `/reload-plugins` | Skills, command, agents, native JS workflows and Claude hooks; preserve native trust/permissions. |
| Codex | `codex plugin marketplace add <package-directory>` (no `#` in the path; Codex reads `#` as a ref separator), or the public `MrBekoX/agentic-sdlc`, then `codex plugin add agentic-sdlc@mrbekox`; the personal catalog `~/.agents/plugins/marketplace.json` remains an option — add the entry to that file, do not replace other entries | `codex plugin marketplace upgrade <marketplace-name>` refreshes a Git catalog and reinstalls plugins installed from it; for a local source, repeat `codex plugin add agentic-sdlc@<marketplace-name>` to recopy; then start a new chat and review changed hooks in `/hooks` | Shared skills (the `git-safety-check` command is listed as a 17th skill) and eight separately trusted hooks. Compatibility manifest retained; public directory projection excludes lifecycle hooks. |
| Kimi Code | `/plugins install <package-directory>` or `/plugins install https://github.com/MrBekoX/agentic-sdlc`; `/plugins marketplace <marketplace-kimi.json-path-or-url>` browses the custom catalog | Reinstall a changed local source; in `/plugins` Installed tab press Enter for an available update, then `/reload` or `/new` | Skills (invoke by bare name, e.g. `/skill:mind-spark`), command, agents, sessionStart router and three PreToolUse command guards. No verified Kimi write/Stop readers or Claude Workflow runtime; warn-only guard output is not shown. |
| ZCode | Settings → Plugins → Discover → + → Add marketplace; choose the root `marketplace.json` **as a file source** (a directory or GitHub source is read through `.claude-plugin/marketplace.json` first and shows the Claude entry without ZCode's category, tags and translations), then Install. Newly installed plugins are **enabled by default**, which lets their hooks run: review the hook table before installing | Refresh marketplace; Manage installed → Check for updates → apply (offered only when the catalog version changes); start a new session | Skills, command, agents, shell-free argv hooks for command guards, advisory writes and startup. No verified Stop/flow readers; saved ZCode workflows (`.zcode/workflows/`) cannot be delivered by a plugin. |
| Grok CLI | `grok plugin install <package-directory> --trust` (an absolute or `./`-relative path; the install also enables the plugin). The shipped `.grok-plugin/marketplace.json` entry installs from the public GitHub repository; a marketplace is named after its source's last path segment, not the catalog `name` | For a local install, `grok plugin uninstall agentic-sdlc` then install the new copy (`update` reports a local install as already live; reinstalling over it reports AlreadyInstalled). For a Git marketplace, `grok plugin marketplace update <source-name>` then `grok plugin update agentic-sdlc`; press r in Plugins or start a new session | Skills, command, agents and three command guards. Rhai workflows are separate project/user catalogs, not delivered to a customer's project by plugin install. No verified write/Stop/startup readers. |
| Cursor | From the package directory, `python3 scripts/install_cursor_plugin.py install` (Windows: `py -3` when `python3` is missing or is the Microsoft Store alias). The destination is resolved from the current home directory. A team admin can instead import the repository in Dashboard → Plugins & MCPs; that reads `.cursor-plugin/marketplace.json` | `python3 scripts/install_cursor_plugin.py update`, then Developer: Reload Window. Files this installer did not write stay. A team marketplace refreshes from the dashboard | Shared skills, agents, the `git-safety-check` command, one rule, and the Cursor hook wire. No Claude Workflow runtime and no Claude transcript Stop readers. Native IDE discovery was not run in the packaging environment. |
| Google Antigravity (experimental) | Stage `.antigravity-plugin/plugin.json` as `<plugin-dir>/plugin.json` along with `skills/`, `contracts/`, `scripts/`, `assets/`, `commands/`, `workflows/`, `docs/`, and `agents/` into `<workspace>/.agents/plugins/agentic-sdlc/` (workspace) or `~/.gemini/config/plugins/agentic-sdlc/` (global); see [`.antigravity-plugin/README.md`](../../.antigravity-plugin/README.md) | Re-run the staging copy command from an updated checkout or extracted package directory | 16 shared skills, portable `<runtime-root>` resolution (two levels above `SKILL.md`), subagent delegation via `invoke_subagent` (`research` / `self`), and workspace `AGENTS.md` rule loading. No `hooks.json` wired (`toolCall` schema incompatibility) and no `.agent/workflows/*.md` dependency (deprecating October 19, 2026). |

Local/extracted directory installs do not require this checkout or a maintainer
drive. Repository installs require user access to the selected source. Anonymous
installation needs public access; do not infer private-source authentication support
from another platform's git behavior. Do not silently grant hook trust or change
experimental runtime settings.

Claude's session `/plugin` interface is a browser: its install shortcut opens
the plugin details. Use the shell commands above when a direct installation is
needed. Update is a shell subcommand. Install/uninstall default to user scope;
update auto-detects the most specific installed scope. Supply `--scope` to select
the intended installation explicitly.

For Codex, adding a local marketplace is separate from copying a plugin into the
install cache. Editing a local source does not edit the installed copy. After
refreshing the source, repeat `codex plugin add agentic-sdlc@<marketplace-name>`
to recopy it; this sequence was verified on CLI 0.162.1. There is no `codex plugin update` command in
CLI 0.162.1; `codex plugin marketplace upgrade <marketplace-name>` refreshes a Git catalog and
reinstalls the plugins installed from it. Do not edit the cache or rewrite `config.toml` by hand.
An earlier `marketplace add <local-directory>` failure was caused by a `#` in the test path:
Codex splits a marketplace source on `#` to read a ref, so keep `#` out of local source paths.

Releases: Claude Code, ZCode and Grok deliver an update only when the manifest/catalog
version changes. A release therefore bumps the version with `python3 scripts/bump_version.py <next>`
and moves the `Unreleased` CHANGELOG notes under it in the release pull request
(`bump_version.py --release-check` requires an empty `Unreleased` section).
The personal Grok catalog's remote `url` entry follows the repository's default branch, so
every push reaches its installs; the official xAI catalog entry must pin the release
commit's full `sha`. If the public repository ends up at a different URL than
`https://github.com/MrBekoX/agentic-sdlc`, update every place that pins
`MrBekoX/agentic-sdlc` before publishing (`git grep -n "MrBekoX/agentic-sdlc"` lists them):

- manifests: `homepage`/`repository` in `.claude-plugin/plugin.json`,
  `.codex-plugin/plugin.json`, `.grok-plugin/plugin.json`, `.kimi-plugin/plugin.json`
  (also its `interface.websiteURL`) and `.zcode-plugin/plugin.json`;
- catalogs: the `url` source in `.grok-plugin/marketplace.json` and the `source` in
  `marketplace-kimi.json`, plus the recorded checks in `docs/publication/link-checks.json`;
- `SECURITY.md` (advisory link) and `.github/ISSUE_TEMPLATE/config.yml`;
- `README.md`, the adapter READMEs (`.claude-plugin/`, `.codex-plugin/`, `.grok-plugin/`
  and the `.zcode-plugin/` README pair), `CHANGELOG.md`, `docs/plugin-readme.md`,
  `docs/runtime-adapter.md`, `docs/troubleshooting.md`, `docs/zcode-runtime-adapter.md`,
  `docs/release-readiness.md`,
  `docs/release-evidence-0.4.3.md`, `docs/release-evidence-0.5.0.md`, `docs/release-evidence-0.6.0.md` and the notes under `docs/publication/`;
- the tests that pin it: `tests/test_grok_packaging.py`, `tests/test_kimi_packaging.py`,
  `tests/test_packaging_metadata.py` and `tests/test_zcode_packaging.py`.

The owner URL `https://github.com/MrBekoX` in the `author`/`owner` fields changes only
if the owner changes; the `mrbekox` marketplace name is an identifier in every
`@mrbekox` install command, not a URL.

| Platform | Uninstall | Retained data and configuration |
|---|---|---|
| Claude Code | In a shell, `claude plugin uninstall agentic-sdlc@mrbekox`; select the installed `--scope` when needed, then `/reload-plugins` | Removing the last installed scope normally removes saved plugin data; `--keep-data` retains it. Data can also remain when shared or installation records cannot be read. Marketplace registration and the original source are separate. |
| Codex | `codex plugin remove agentic-sdlc@<marketplace-name>`, then start a new chat | Removes this plugin's configuration and local cache. Other plugins and unrelated settings must remain. Removing a catalog is a separate `codex plugin marketplace remove <marketplace-name>` operation; only remove an unused catalog. |
| Kimi Code | In the TUI, `/plugins remove agentic-sdlc`, confirm the prompt, then `/reload` or `/new` | Removes the installed record; the managed copy remains on disk. Kimi does not delete those files automatically. |
| ZCode | Settings → Plugins → Manage installed → plugin detail → Uninstall | Use the native UI. Persistent-data retention is not specified by the reviewed documentation; do not promise that uninstall deletes it. |
| Grok CLI | `grok plugin uninstall agentic-sdlc` (no confirmation prompt), then reload Plugins or start a new session | Native uninstall supports `--keep-data` to retain plugin data. The marketplace and original source are separate. |
| Cursor | `python3 scripts/install_cursor_plugin.py uninstall` | Deletes only paths listed in `.cursor-plugin/install-receipt.json` inside the destination. Other files in that folder, and every Cursor setting outside it, stay. A missing receipt refuses the uninstall. |
| Google Antigravity (experimental) | Remove the staged `<workspace>/.agents/plugins/agentic-sdlc` or `~/.gemini/config/plugins/agentic-sdlc` directory (or toggle via `/plugins`) | Only the staged plugin directory is removed; workspace and user configurations remain untouched. |

Native managers own their configuration changes. Install only the selected plugin
in the chosen scope; preserve unrelated catalog entries, plugins and settings.
These are customer instructions, not permission for an agent to remove a user's
installation or recursively clean caches.

## Runtime path contracts

Claude resolves `CLAUDE_PLUGIN_ROOT`; Codex exports `PLUGIN_ROOT`. Grok exports
`GROK_PLUGIN_ROOT` to hooks. Codex/Grok fixed Node launch code reads those environment
values, joins a fixed handler and imports a file URL, so installed-path bytes stay
outside shell source. Codex alone supports `commandWindows`; Grok does not.
Kimi executes `node "./hooks/<handler>.mjs"` with hook cwd equal to the plugin root;
git checks take the target project from the Bash tool's own `tool_input.cwd`
(resolved against the session cwd), falling back to the stdin `cwd`. `KIMI_PLUGIN_ROOT`
is a hook environment variable, not a promised Bash/skill-text alias. Its
skillInstructions resolve helper paths from the loaded Skill file's installed path.
ZCode passes `${ZCODE_PLUGIN_ROOT}/hooks/<handler>.mjs` as an argv element without a
shell. Mixing Windows Node and POSIX install paths is not a supported host setup.
On Windows, Kimi's main Bash tool requires Git for Windows. Its hook runner uses
the host's subprocess shell; the PowerShell adapter replay is additional shell
evidence, not proof of native Kimi hook delivery.

## Automated evidence

`scripts/check_plugin_portability.py` checks declared hook commands and transitive
module/resource dependencies; the skill harness, release builder and archive verifier
use the same byte-map check. Missing handlers/imports/helpers and absolute executable
paths have negative controls. The standalone CLI additionally requires all five
manifests. Public hook-free projection and arbitrary release-test fixtures validate
only their declared components.

`tests/test_multi_platform_portability.py` copies runtime files into a git-less temp
directory outside the checkout, with Unicode and shell-sensitive characters, then
executes shipped Grok/Kimi command strings and ZCode argv. It checks destructive
denial and project-cwd protected/feature branch behavior. Codex has its separate
eight-handler replay suite. These are handler/shell replays, not native trust,
installer or skill-trigger proof. No fresh model eval batch was run.

Record the final source commit, archive hashes, full gate counts, host names and
skips in the delivery report. Windows and Linux runs do not establish macOS results;
macOS has its own recorded run: after the maintainer skipped macOS on 2026-10-11, the
GitHub-hosted macOS native lifecycle job passed for all five platforms on 2026-10-12
([compatibility matrix](compatibility-matrix.md) E10–E14). The deterministic CI gate
remains manual, and the historical billing failure is not a fresh account check.

Native preparation on 2026-10-10: Claude Code 2.1.296 accepted the clean marketplace
and plugin manifests with strict validation, without warnings. Grok 1.0.50 accepted
the Grok manifest and listed its skill/command/agent directories and hooks. Codex
0.162.1 installed the extracted local package into an isolated empty test home;
`plugin/read` exposed 16 skills and 8 hook declarations and `hooks/list` returned
8 untrusted records with no errors. No hook trust was granted or model turn run;
this does not prove hook execution. Kimi 2.1.1 was present but its native installer
was not exercised that day (the 2026-10-12 lifecycle run below exercised it); no ZCode CLI was
present (the 2026-10-12 ZCode runs used the desktop bundle's agent CLI). Windows and Linux serialized
adapter replay each returned 15 tests / OK with no skips after runtime prerequisites
were supplied. These observations bind the labelled candidate fixture; rebuild and
repeat against the eventual release commit before publication.

`scripts/check_native_lifecycle.py --package <dir>` runs a no-model, isolated
install, discovery, refresh and uninstall through each vendor's own plugin
manager (Claude Code, Codex personal catalog, Grok, Kimi Code `kimi web` API;
ZCode reports `not-run:no_headless_installer`, so the ZCode rows of the matrix are
driven by `.github/scripts/zcode_agent_lifecycle.mjs` instead) and prints one
`native_<platform>=` line per platform. `tests/test_native_distribution_lifecycle.py`
covers it with fail-closed fake CLIs and, where a vendor CLI is installed, real
runs. The earlier Codex-only test it replaces executed one test, OK, on Windows
with CLI 0.162.1 (install, changed-source recopy, uninstall, preserved unrelated
settings). The 2026-10-12 results, bound to main `1a9ac73`, are in the
[compatibility matrix](compatibility-matrix.md#evidence-log); repeat on the release commit before publication.
This is local-copy evidence; it does not grant hook trust, mutate the personal
profile, or prove remote transport, hook execution or live skill behavior.

Archive member checks now also enforce Windows device-name, invalid-character
and trailing-dot/space rules on every build host, before extraction can sanitize
member names. The deterministic CI matrix prepares Windows, Linux and macOS and
remains manual. On macOS, the 2026-10-12 native lifecycle job built and verified a
release-format archive of main `1a9ac73` on a GitHub-hosted runner and passed for all five platforms
([compatibility matrix](compatibility-matrix.md) E10–E14).
The filename contract follows [Windows naming rules](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file)
and [Python's reserved-path reference](https://docs.python.org/3/library/os.path.html#os.path.isreserved);
the archive builder is release tooling and runs on Python 3.12, the floor for maintainer
and release tooling. The helpers skills run keep the separate Python 3.8 syntax floor
described under the prerequisites above.

Current [2026-10-11 preparation](marketplace-readiness-2026-10-11.md) adds native
Kimi authenticated management, Grok directory/Git lifecycle and Codex exact-hash
trust plus startup event delivery in isolated profiles. No model-backed skill
evaluation is implied. Grok 1.0.50 local update does not recopy and same-source
reinstall fails; see its [update instructions](grok-marketplace.md).
The clean committed-source exporter prepares official Grok/ZCode layouts without
rewriting the private original repository or claiming future public reachability.

## Manual publishing steps

1. Review the final diff, local gate and built full/skills-only ZIP identities.
   Confirm repository visibility and resolve the historical history/privacy finding
   before making a private repository public. No history rewrite is performed here.
2. Claude: submit from [Directory management](https://claude.ai/directory/manage)
   with the required paid account and clean-package validation. Follow the existing
   `claude-community.md` packet; acceptance is a separate vendor decision.
3. Codex: the local/personal marketplace can carry trusted hooks. The universal
   public directory uses `build_release.py --skills-only`, verified identity and
   portal submission permissions; follow `openai-skills-only.md`. No hook-bearing
   package is submitted to a channel that excludes hooks.
4. Grok: prepare a reviewed PR to [xai-org/plugin-marketplace](https://github.com/xai-org/plugin-marketplace).
   A remote source entry uses the actual repository URL and full 40-character commit
   SHA. Generate the component index and run that catalog's validators; do not invent
   a SHA or call a local `plugin validate` pass publication.
5. ZCode: follow [CONTRIBUTING](https://github.com/zai-org/zcode-plugins/blob/main/CONTRIBUTING.md)
   with `plugins/<name>/`, plugin-root English/Chinese README, matching marketplace
   and manifest versions, vendor validators/build tooling and native behavior
   evidence. The current hidden-directory README pair alone is not that submission
   layout. Vendor maintainers publish the immutable ZIP/hash channel.
6. Kimi: local directory, ZIP URL, GitHub URL and custom catalogs are documented.
   Official/Curated listing has no documented self-service submission contract;
   obtain the vendor's actual listing requirements before claiming readiness there.

No directory submission, tagging, external publication or source merge is
performed by this preparation. Authorized trust was confined to temporary profiles.
Native install/update/uninstall results bound to main `1a9ac73` are in the
[compatibility matrix](compatibility-matrix.md); repeat them on the release commit, and
check hook delivery and live behavior on each intended runtime/version, before a broader
release claim.

## Official sources (checked 2026-10-10)

- [Claude manifest/path rules](https://code.claude.com/docs/en/plugins-reference),
  [marketplaces](https://code.claude.com/docs/en/plugin-marketplaces),
  [plugin commands](https://code.claude.com/docs/en/plugins/cli-reference).
- [OpenAI packaging](https://developers.openai.com/plugins/build/plugins),
  [Codex hooks](https://learn.chatgpt.com/docs/hooks).
- [Kimi plugins](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/plugins.html),
  [hooks](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/hooks.html),
  [agents](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/agents.html).
- [ZCode plugins](https://zcode.z.ai/en/docs/plugin),
  [hooks](https://zcode.z.ai/en/docs/hooks),
  [changelog](https://zcode.z.ai/en/changelog).
- [Grok plugins](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/09-plugins.md),
  [hooks](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/10-hooks.md),
  [command runner](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-hooks/src/runner/command.rs).
