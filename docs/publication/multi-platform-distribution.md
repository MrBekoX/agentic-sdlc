# Multi-platform distribution candidate

All five adapters are included in this preparation. This is an installation and
publication checklist, not a public listing or a guarantee of live model behavior.
The historical 0.4.3 release verdict remains in `../release-evidence-0.4.3.md`.

## Install, update and uninstall

Prerequisites: use the runtime and Node.js in the same OS environment, with `node`
on the hook shell PATH (`node.exe` is selected by Codex on native Windows). Python
3.12+ and Git are needed for helper/validation workflows. Keep the full plugin
directory: isolated SKILL.md copies omit shared contracts, scripts and reviewers.

| Platform | Install | Update | Included behavior and limits |
|---|---|---|---|
| Claude Code | In a shell, `claude plugin marketplace add MrBekoX/agentic-sdlc`, then `claude plugin install agentic-sdlc@mrbekox`; an extracted package also loads through `claude --plugin-dir <package>` | In a shell, `claude plugin marketplace update mrbekox`, then `claude plugin update agentic-sdlc@mrbekox`; in the session, `/reload-plugins` | Skills, command, agents, native JS workflows and Claude hooks; preserve native trust/permissions. |
| Codex | `codex plugin marketplace add MrBekoX/agentic-sdlc` (source access required), then `codex plugin add agentic-sdlc@mrbekox`; for a local catalog use its actual marketplace name | For a configured Git source, `codex plugin marketplace upgrade <marketplace-name>` refreshes the catalog snapshot. Refresh the selected local package through the Plugins UI or the native recopy sequence below, then start a new chat and review changed hooks in `/hooks` | Shared skills and eight separately trusted hooks. Compatibility manifest retained; public directory projection excludes lifecycle hooks. |
| Kimi Code | `/plugins install <package-directory>` or `/plugins install https://github.com/MrBekoX/agentic-sdlc`; `/plugins marketplace <marketplace-kimi.json-path-or-url>` browses the custom catalog | Reinstall a changed local source; in `/plugins` Installed tab press Enter for an available update, then `/reload` or `/new` | Skills, command, agents, sessionStart router and three PreToolUse command guards. No verified Kimi write/Stop readers or Claude Workflow runtime. |
| ZCode | Settings → Plugins → Discover → + → Add marketplace; select the directory containing root `marketplace.json` or the GitHub repository, then Install and Enable | Refresh marketplace; Manage installed → Check for updates → apply; start a new session | Skills, command, agents, shell-free argv hooks for command guards, advisory writes and startup. No verified Stop/flow readers or distributable Workflow script API. |
| Grok CLI | `grok plugin install <package-directory> --trust`, then `grok plugin enable agentic-sdlc`; `grok plugin marketplace add <source>` registers a catalog | `grok plugin marketplace update <name>` and `grok plugin update agentic-sdlc`; press r in Plugins or start a new session | Skills, command, agents and three command guards. Rhai workflows are separate project/user catalogs, not delivered to a customer's project by plugin install. No verified write/Stop/startup readers. |

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

For Codex, adding or upgrading a marketplace is separate from copying a plugin
into the install cache. Editing a local source does not edit the installed copy.
After refreshing the source, repeat `codex plugin add agentic-sdlc@<marketplace-name>`
to recopy it; this sequence was verified on CLI 0.162.1. There is no `codex plugin update` command in
CLI 0.162.1. Do not edit the cache or rewrite `config.toml` by hand.
On that binary, `marketplace add <local-directory>` returned a Git-only ref error;
the isolated test instead used the documented personal catalog at
`~/.agents/plugins/marketplace.json`. Git-backed marketplace registration is a
separate, untested transport in that check.

| Platform | Uninstall | Retained data and configuration |
|---|---|---|
| Claude Code | In a shell, `claude plugin uninstall agentic-sdlc@mrbekox`; select the installed `--scope` when needed, then `/reload-plugins` | Removing the last installed scope normally removes saved plugin data; `--keep-data` retains it. Data can also remain when shared or installation records cannot be read. Marketplace registration and the original source are separate. |
| Codex | `codex plugin remove agentic-sdlc@<marketplace-name>`, then start a new chat | Removes this plugin's configuration and local cache. Other plugins and unrelated settings must remain. Removing a catalog is a separate `codex plugin marketplace remove <marketplace-name>` operation; only remove an unused catalog. |
| Kimi Code | In the TUI, `/plugins remove agentic-sdlc`, confirm the prompt, then `/reload` or `/new` | Removes the installed record; the managed copy remains on disk. Kimi does not delete those files automatically. |
| ZCode | Settings → Plugins → Manage installed → plugin detail → Uninstall | Use the native UI. Persistent-data retention is not specified by the reviewed documentation; do not promise that uninstall deletes it. |
| Grok CLI | `grok plugin uninstall agentic-sdlc`, confirm the native prompt, then reload Plugins or start a new session | Native uninstall supports `--keep-data` to retain plugin data. The marketplace and original source are separate. |

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
the stdin `cwd` still identifies the target project for git checks. `KIMI_PLUGIN_ROOT`
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
skips in the delivery report. Windows and Linux runs do not establish macOS results.
CI remains manual while the existing account billing blocker prevents jobs starting.

Native preparation on 2026-10-10: Claude Code 2.1.296 accepted the clean marketplace
and plugin manifests with strict validation, without warnings. Grok 1.0.50 accepted
the Grok manifest and listed its skill/command/agent directories and hooks. Codex
0.162.1 installed the extracted local package into an isolated empty test home;
`plugin/read` exposed 16 skills and 8 hook declarations and `hooks/list` returned
8 untrusted records with no errors. No hook trust was granted or model turn run;
this does not prove hook execution. Kimi 2.1.1 is present but its interactive native
installer was not exercised; ZCode CLI is absent. Windows and Linux serialized
adapter replay each returned 15 tests / OK with no skips after runtime prerequisites
were supplied. These observations bind the labelled candidate fixture; rebuild and
repeat against the eventual release commit before publication.

`tests/test_native_distribution_lifecycle.py` adds a no-model, isolated Codex
local-catalog install/refresh/remove check, with unrelated plugin/profile
sentinels. It does not grant hook trust or mutate the personal profile. Missing
CLI support is an explicit skip. On Windows with CLI 0.162.1 it executed one
test, OK: initial install, changed-source recopy via repeated `plugin add`,
uninstall and preserved unrelated settings/plugin. This is local-copy evidence;
it does not prove remote transport, hook execution or live skill behavior.

Archive member checks now also enforce Windows device-name, invalid-character
and trailing-dot/space rules on every build host, before extraction can sanitize
member names. The deterministic CI matrix prepares Windows, Linux and macOS;
macOS remains unexecuted until an actual job/host result is recorded.
The filename contract follows [Windows naming rules](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file)
and [Python's reserved-path reference](https://docs.python.org/3/library/os.path.html#os.path.isreserved);
the implementation also runs on the repository's Python 3.12 floor.

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

No directory submission, tagging, external publication, trust mutation or merge is
performed by this preparation. Native clean install/update and live behavior must
be checked on each intended runtime/version before a broader release claim.

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
