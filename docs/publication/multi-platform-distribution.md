# Multi-platform distribution candidate

All five adapters are included in this preparation. This is an installation and
publication checklist, not a public listing or a guarantee of live model behavior.
The historical 0.4.3 release verdict remains in `../release-evidence-0.4.3.md`.

## Install and update

Prerequisites: use the runtime and Node.js in the same OS environment, with `node`
on the hook shell PATH (`node.exe` is selected by Codex on native Windows). Python
3.12+ and Git are needed for helper/validation workflows. Keep the full plugin
directory: isolated SKILL.md copies omit shared contracts, scripts and reviewers.

| Platform | Install | Update | Included behavior and limits |
|---|---|---|---|
| Claude Code | `/plugin marketplace add MrBekoX/agentic-sdlc`, then `/plugin install agentic-sdlc@mrbekox`; an extracted package also loads through `claude --plugin-dir <package>` | `/plugin marketplace update mrbekox`, `/plugin update agentic-sdlc@mrbekox`, then `/reload-plugins` | Skills, command, agents, native JS workflows and Claude hooks; preserve native trust/permissions. |
| Codex | Add the repository marketplace or a local catalog entry whose source is the extracted plugin, then `codex plugin add agentic-sdlc@<marketplace-name>` | Refresh the marketplace and update/reinstall its local source using the Plugins UI, then start a new chat; review changed hook definitions in `/hooks` | Shared skills and eight separately trusted hooks. Compatibility manifest retained; public directory projection excludes lifecycle hooks. |
| Kimi Code | `/plugins install <package-directory>` or `/plugins install https://github.com/MrBekoX/agentic-sdlc`; `/plugins marketplace <marketplace-kimi.json-path-or-url>` browses the custom catalog | Reinstall a changed local source; in `/plugins` Installed tab press Enter for an available update, then `/reload` or `/new` | Skills, command, agents, sessionStart router and three PreToolUse command guards. No verified Kimi write/Stop readers or Claude Workflow runtime. |
| ZCode | Settings → Plugins → Discover → + → Add marketplace; select the directory containing root `marketplace.json` or the GitHub repository, then Install and Enable | Refresh marketplace; Manage installed → Check for updates → apply; start a new session | Skills, command, agents, shell-free argv hooks for command guards, advisory writes and startup. No verified Stop/flow readers or distributable Workflow script API. |
| Grok CLI | `grok plugin install <package-directory> --trust`, then `grok plugin enable agentic-sdlc`; `grok plugin marketplace add <source>` registers a catalog | `grok plugin marketplace update <name>` and `grok plugin update agentic-sdlc`; press r in Plugins or start a new session | Skills, command, agents and three command guards. Rhai workflows are separate project/user catalogs, not delivered to a customer's project by plugin install. No verified write/Stop/startup readers. |

Local/extracted directory installs do not require this checkout or a maintainer
drive. Repository installs require user access to the selected source. Anonymous
installation needs public access; do not infer private-source authentication support
from another platform's git behavior. Do not silently grant hook trust or change
experimental runtime settings.

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
