# agentic-sdlc

![agentic-sdlc](agentic-sdlc-image.png)

> An AGENTIC-SDLC skill library with adapters for **Claude Code**, **Codex**, **Kimi Code**, **ZCode**, **Grok CLI** and **Cursor**. It packages repeatable software-delivery procedure as skills, hooks, contracts, scripts, agents, workflows, and eval fixtures.
>
> `Version 0.5.0` - `MIT` - `Author: Beko` - <https://github.com/MrBekoX/agentic-sdlc>

---

## Scope

Claude Code, Codex, Kimi Code, ZCode, Grok CLI and Cursor are in packaging and portability scope. Claude Code and Codex retain their full runtime guard adapters; the others expose the documented subsets below. Native/live evidence is separate from packaging support. The five vendor-CLI lifecycle passes below do not include Cursor:

| Runtime | Read this first | Plugin entry point |
|---|---|---|
| Claude Code | [`.claude-plugin/README.md`](.claude-plugin/README.md) | [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) + [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json) |
| Codex | [`.codex-plugin/README.md`](.codex-plugin/README.md) | [`.codex-plugin/plugin.json`](.codex-plugin/plugin.json) |
| Kimi Code | [`.kimi-plugin/README.md`](.kimi-plugin/README.md) | [`.kimi-plugin/plugin.json`](.kimi-plugin/plugin.json) + [custom marketplace](marketplace-kimi.json) |
| ZCode | [`.zcode-plugin/README.md`](.zcode-plugin/README.md) | [`.zcode-plugin/plugin.json`](.zcode-plugin/plugin.json) + [marketplace](marketplace.json) |
| Grok CLI | [`.grok-plugin/README.md`](.grok-plugin/README.md) | [`.grok-plugin/plugin.json`](.grok-plugin/plugin.json) + [marketplace](.grok-plugin/marketplace.json) |
| Cursor | [`.cursor-plugin/README.md`](.cursor-plugin/README.md) | [`.cursor-plugin/plugin.json`](.cursor-plugin/plugin.json) + [marketplace](.cursor-plugin/marketplace.json) |

Installation/update/uninstall steps, verified root contracts and publishing limits for all five platforms are in [multi-platform distribution](docs/publication/multi-platform-distribution.md); the per-platform and per-OS verification results are in the [compatibility matrix](docs/publication/compatibility-matrix.md). Requirements on every platform: Node.js on the hook `PATH` (22 and 24 tested; a missing `node` silently disables the guards), Python 3 for helper workflows (3.12 tested; the helpers that skills run are kept import-compatible with Python 3.8 by a static check; maintainer and release tooling such as `build_release.py`, `bump_version.py`, the Codex trust check and the eval runners needs Python 3.12; `py -3` on Windows when `python3` is missing or is the Microsoft Store alias) and Git. Repository-URL installs use the public repository `MrBekoX/agentic-sdlc`; an extracted package directory installs from any local path without developer-specific setup, as long as the path contains no `#` (Codex and Grok read `#` specially). Kimi, ZCode and Grok are packaged adapters with limited runtime coverage; they do not inherit Claude/Codex transcript or Workflow behavior. The 0.4.3 release evaluation covered only Claude Code and Codex (its verdict was do-not-publish) and does not certify the other adapters' native lifecycle. Other harnesses remain deferred.

The [2026-10-11 marketplace preparation](docs/publication/marketplace-readiness-2026-10-11.md)
records isolated native checks and clean-source/vendor packet preparation; macOS was
skipped in that preparation. On 2026-10-12 native install, discovery, update and uninstall
passed for all five platforms on Windows, Linux and macOS (macOS: E10–E14), with no model
turn; see the [compatibility matrix](docs/publication/compatibility-matrix.md) (E1–E15).
Account eligibility, public source and vendor approval remain separate gates; nothing was published.

## Install

### Get the package

Every install below starts from a package directory: an extracted copy of this repository's files. Clone the repository, or download and extract its source ZIP or a release archive (maintainers build one with `python3 scripts/build_release.py --output agentic-sdlc.zip`; GitHub Releases are not published yet). Nothing inside the folder needs editing. Keep `#` out of the path (Codex and Grok read `#` specially). The repository is public since 2026-10-12, so repository-URL installs (`MrBekoX/agentic-sdlc`, `https://github.com/MrBekoX/agentic-sdlc`) also work without credentials.

### Claude Code

```text
claude plugin marketplace add <package-directory>
claude plugin install agentic-sdlc@mrbekox
```

Once the repository is public, `claude plugin marketplace add MrBekoX/agentic-sdlc` replaces the directory source. Hooks run once the plugin is installed and enabled. Run `/reload-plugins` or start a new session; `claude plugin details agentic-sdlc@mrbekox` lists 17 entries (16 skills and the `git-safety-check` command).

### Codex

```text
codex plugin marketplace add <package-directory>
codex plugin add agentic-sdlc@mrbekox
```

Once the repository is public, `codex plugin marketplace add MrBekoX/agentic-sdlc` replaces the directory source. Codex runs a bundled hook only after it is trusted: open `/hooks` in Codex and trust each agentic-sdlc hook. Then run the read-only post-install check from the package directory (the script is standalone, so any copy of the package works; it needs Python 3.12); a fully trusted install prints `codex_hook_trust=trusted`:

```bash
python3 scripts/check_codex_hook_trust.py --plugin agentic-sdlc@mrbekox --cwd <target-project>
```

Replace `<target-project>` with the session project's path. The per-environment trust steps, Codex config locations and exit codes are in [Codex hook trust](docs/troubleshooting.md#codex-hook-trust). A personal catalog (`~/.agents/plugins/marketplace.json`) is an optional alternative; see [Codex personal marketplace](#codex-personal-marketplace).

### Kimi Code

In the Kimi TUI:

```text
/plugins install <package-directory>
/plugins info agentic-sdlc
/reload
```

Hooks run once the plugin is installed. Invoke skills by bare name (`/skill:using-agentic-sdlc`). On Windows, Kimi's Bash tool needs Git for Windows.

### Grok CLI

```text
grok plugin install <package-directory> --trust
```

The install also enables the plugin; `grok plugin enable agentic-sdlc` is only needed after a `disable`. For a path containing `#`, `cd` into the package directory and run `grok plugin install . --trust`.

### ZCode

In the ZCode desktop client (builds for Windows x64/ARM64, macOS Apple Silicon/Intel DMG and Linux x64 AppImage): **Settings → Plugins → Add marketplace**, choose the package's root [`marketplace.json`](marketplace.json) **as a file source**, then **Install**. Newly installed plugins are enabled by default, so their hooks run at install: review the [hook wiring](#guardrails) first. Start a new session afterwards.

### Cursor

From the package directory:

```bash
python3 scripts/install_cursor_plugin.py install
```

On Windows, use `py -3` when `python3` is missing or is the Microsoft Store alias. The script resolves Cursor's documented local plugin directory from the current user's home (`~/.cursor/plugins/local/agentic-sdlc` on macOS and Linux, `%USERPROFILE%\.cursor\plugins\local\agentic-sdlc` on Windows). It copies this package there. A symlink from that folder to a checkout elsewhere is not loaded. Then run **Developer: Reload Window**, open **Customize**, and confirm `agentic-sdlc`. Node.js 22 or newer (`node` on `PATH`), Python 3.8+ and Git are required; a missing tool stops the install with `error=node_missing`, `error=python_missing` or `error=git_missing`.

In a project chat, start with `/using-agentic-sdlc`. A full delivery request uses `/agentic-sdlc-pipeline`. The read-only command is `/git-safety-check`. Teams can import `https://github.com/MrBekoX/agentic-sdlc` from **Dashboard → Plugins & MCPs → Add Marketplace**; that import reads [`.cursor-plugin/marketplace.json`](.cursor-plugin/marketplace.json). Nothing has been submitted to the public Cursor Marketplace.

### Update and uninstall

| Platform | Update | Uninstall |
|---|---|---|
| Claude Code | `claude plugin marketplace update mrbekox`, then `claude plugin update agentic-sdlc@mrbekox` (delivered only when the version changes) | `claude plugin uninstall agentic-sdlc@mrbekox` |
| Codex | There is no `codex plugin update`: for a local source repeat `codex plugin add agentic-sdlc@mrbekox`; for a Git catalog run `codex plugin marketplace upgrade <marketplace-name>` | `codex plugin remove agentic-sdlc@mrbekox` |
| Kimi Code | Reinstall the changed directory, or press Enter on an available update in `/plugins` | `/plugins remove agentic-sdlc` (the managed copy stays on disk) |
| Grok CLI | Local install: `grok plugin uninstall agentic-sdlc`, then install the new folder; Git catalog: `grok plugin marketplace update <source-name>`, then `grok plugin update agentic-sdlc` | `grok plugin uninstall agentic-sdlc` (no prompt; `--keep-data` keeps data) |
| ZCode | Refresh the marketplace → **Manage installed** → **Check for updates** (offered only when the version changes) → start a new session | **Settings → Plugins → Manage installed → Uninstall** (asks for confirmation) |
| Cursor | From the package directory, `python3 scripts/install_cursor_plugin.py update`, then **Developer: Reload Window** | `python3 scripts/install_cursor_plugin.py uninstall` (removes files this installer wrote; other files in that folder stay) |

Native install, discovery, update and uninstall of a package directory passed in all 15 platform × OS cells of the [compatibility matrix](docs/publication/compatibility-matrix.md), with no model turn. Not proven there: hook trust and delivery inside a live session, live skill and model behavior, ZCode's desktop GUI flow (the bundled agent CLI was used), Git-catalog update paths (Codex `marketplace upgrade`, Kimi Enter-update) and Kimi's TUI `/plugins install` (the `kimi web` API was used). Retained data and scope options are in [multi-platform distribution](docs/publication/multi-platform-distribution.md).

## Distribution paths

`agentic-sdlc` has four release-gated distribution paths. Each one has its own prerequisites, steps, go condition and state. A state is a snapshot bound to the [release evidence ledger](docs/release-evidence-0.5.0.md); the per-path go/no-go verdicts live in [release readiness](docs/release-readiness.md#distribution-paths-and-gono-go). Ready to submit never means submitted, accepted or published. A BLOCKED or GAP state concerns publication or a release gate; it does not mean the [Install](#install) steps above fail. Kimi, ZCode and Grok adapters are included in this distribution candidate; the historical four-path 0.4.3 verdict does not establish their native lifecycle or public-directory acceptance.

### Claude own marketplace

**Prerequisites.** Claude Code with plugin marketplace support, `node` on `PATH`, and either an extracted package directory or read access to `MrBekoX/agentic-sdlc`.

**Steps.** Add a package directory, or this repository, as a plugin marketplace, then install the plugin:

```text
claude plugin marketplace add <package-directory>
claude plugin marketplace add MrBekoX/agentic-sdlc
claude plugin install agentic-sdlc@mrbekox
```

Run one of the two `marketplace add` lines: the package directory and the public repository form both work. To load a package for one session without installing it, point Claude Code at its root instead:

```text
claude --plugin-dir /path/to/agentic-sdlc
```

After install, the `using-agentic-sdlc` router is available as a skill. Claude Code slash-command discovery comes from `commands/`, and Claude namespaces plugin commands as `<plugin>:<command>`, so this plugin's manual command is `/agentic-sdlc:git-safety-check`.

**Go condition.** Anonymous users need a public repository. A private repository installs only through a git credential helper or SSH; a token supplied only in an environment variable does not authenticate the install ([private repositories](https://code.claude.com/docs/en/plugin-marketplaces.md#private-repositories), observed 2026-09-14). `claude plugin validate .claude-plugin/marketplace.json --strict` and `claude plugin validate .claude-plugin/plugin.json --strict` pass as two separate checks. Since Claude Code 2.1.289, `claude plugin validate .` also checks the plugin beside a marketplace manifest ([plugins/publish](https://code.claude.com/docs/en/plugins/publish) and the 2.1.289 changelog, fetched 2026-10-07). Hook-config validity comes from the repository tests. A strict `plugin.json` exit 1 in a working tree, caused by the untracked `CLAUDE.md`, is not the clean-package result. The clean install starts from an empty profile: `claude plugin marketplace add MrBekoX/agentic-sdlc`, `claude plugin install agentic-sdlc@mrbekox`, a new session or `/reload-plugins`, then skill, command and hook discovery plus one real invocation, with the clone transport (SSH or HTTPS) recorded.

State: GAP. The repository is public since 2026-10-12, published with a rewritten history ([history map](docs/publication/history-map.md)); its unauthenticated URL returns 200 in [`docs/publication/link-checks.json`](docs/publication/link-checks.json). From the public repository, `claude plugin marketplace add MrBekoX/agentic-sdlc` and `claude plugin install agentic-sdlc@mrbekox` installed 0.5.0 with 16 skills in an isolated profile (Claude Code 2.1.282, Linux, 2026-10-12, no model call); the go condition's new-session discovery, real invocation and recorded clone transport are not recorded. Installs from a package directory are unaffected; native install, discovery, update and uninstall passed on Claude Code 2.1.296 (Windows), 2.1.282 (Linux) and 2.1.293 (macOS) (E1, E5, E10 in the [compatibility matrix](docs/publication/compatibility-matrix.md)).

### Claude community marketplace submission

**Prerequisites.** A public repository, a recorded clean-package `claude plugin validate ./plugin --strict` result, and a paid claude.ai plan. On Pro and Max the maintainer submits from their own account; on Team and Enterprise an Owner submits, and on Enterprise an Owner can grant the Directory permission ([plugins/publish](https://code.claude.com/docs/en/plugins/publish), fetched 2026-10-07). `claude-plugins-official` does not take directory submissions.

**Steps.** Submit from the developer portal at [claude.ai/directory/manage](https://claude.ai/directory/manage). The prepared packet is [`docs/publication/claude-community.md`](docs/publication/claude-community.md).

**Go condition.** The repository must be public, and `claude plugin validate` must pass on the submitted plugin root ([claude.com/docs/plugins/submit](https://claude.com/docs/plugins/submit), observed 2026-09-14). Acceptance is not guaranteed. Two Anthropic statements, both observed 2026-09-14, govern updates: [code.claude.com/docs/en/plugins](https://code.claude.com/docs/en/plugins.md) says approved plugins "are pinned to a specific commit SHA" and that CI bumps the pin automatically as new commits are pushed, and [claude.com/docs/plugins/submit](https://claude.com/docs/plugins/submit) says "updates pushed to your GitHub repo are picked up automatically". Every default-branch push after approval therefore counts as publication. The two pages name different target marketplaces, `claude-community` (the code.claude.com community-marketplace section) and `claude-plugins-official` (the claude.com submit page), as recorded on 2026-09-14; neither placement is promised.

State: BLOCKED. The path needs a public repository, the clean-package validation result and maintainer form access.

### Codex personal marketplace

**Prerequisites.** Codex with plugin marketplace support and Node.js on the hook process `PATH` (`node.exe` on native Windows, `node` on POSIX/WSL). Codex supplies the installed `PLUGIN_ROOT`; hooks do not depend on this checkout or a particular user's home/cache path. See the [marketplace launch contract](docs/runtime-adapter.md#codex-marketplace-hook-launch-contract). Native install, discovery, recopy and removal passed on 2026-10-12 with codex-cli **0.162.1** (Windows, macOS) and **0.156.1** (Linux) (E2, E11, E6 in the [compatibility matrix](docs/publication/compatibility-matrix.md)); discovery was earlier checked on 0.160.1 ([preparation evidence](docs/publication/codex-0.160.1-readiness.md)), and historical live hook captures remain versioned at 0.154.0.

**Steps.** Add a package directory (no `#` in its path) as a marketplace and install from it:

```text
codex plugin marketplace add <package-directory>
codex plugin add agentic-sdlc@mrbekox
```

Then trust each hook in `/hooks` and run the read-only trust check described under [Install → Codex](#codex). This route was exercised natively on Windows (E2); the Linux and macOS runs (E6, E11) installed the same package through a personal catalog. This repo's `.claude-plugin/marketplace.json` uses Claude's marketplace schema; current Codex recognizes that legacy layout, which names the marketplace `mrbekox`, and also supports `codex plugin marketplace add owner/repo` ([packaging guide](https://developers.openai.com/plugins/build/plugins), checked 2026-10-08), so `codex plugin marketplace add MrBekoX/agentic-sdlc` works against the public repository: on codex-cli 0.156.1 (Linux, 2026-10-12, isolated profile, no model call) it and `codex plugin add agentic-sdlc@mrbekox` installed 0.5.0 with 16 skills. Adding the same plugin from two sources can list it twice.

**Optional: personal catalog.** A personal catalog is an alternative to the package's own catalog, not an install requirement. The personal catalog root is the home directory, so the `./plugins/agentic-sdlc` source path below resolves to `~/plugins/agentic-sdlc`; place a copy or symlink/junction of the package directory there.

Example `~/.agents/plugins/marketplace.json` — if the file already exists, add only the `agentic-sdlc` entry to its `plugins` array; do not replace the file or other entries.

```json
{
  "name": "personal",
  "interface": {
    "displayName": "Personal"
  },
  "plugins": [
    {
      "name": "agentic-sdlc",
      "source": {
        "source": "local",
        "path": "./plugins/agentic-sdlc"
      },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Developer Tools"
    }
  ]
}
```

```bash
codex plugin add agentic-sdlc@personal
```

`@personal` names this example catalog; pass the marketplace ID you installed from to the trust check (`--plugin agentic-sdlc@personal` here).

The same skills run through the embedded author/critic adapter where Claude-only Workflow/Skill tooling is unavailable.

**Go condition.** Install through `codex plugin add agentic-sdlc@<marketplace-name>` from a catalog Codex recognizes (the package's own `mrbekox` catalog or a personal catalog); native discovery showing 16 skills (the app-server `skills/list` reports 17 entries, the `git-safety-check` command included) and `hooks/list` showing 8 hooks; and hook trust granted through the native `/hooks` trust protocol as a required step.

State: GAP. Native install, skill discovery, recopy and removal of a package built from main `1a9ac73` are recorded (E2, E6, E11 in the [compatibility matrix](docs/publication/compatibility-matrix.md); `hooks/list` was not part of those runs); final-package discovery of 16 skills and 8 hooks and real-profile hook trust are not yet recorded for the 0.5.0 package; the ledger carries the 26b0fe1 results.

### ZCode marketplace installs (experimental, not a release-gated path)

> **Experimental adapter.** ZCode was not a supported 0.4.3 release target; the next release includes it as an experimental adapter. These install paths carry no go/no-go verdict and no official submission exists. See [`docs/runtime-adapter.md`](docs/runtime-adapter.md).

**Prerequisites.** The ZCode desktop client (builds for Windows x64/ARM64, macOS Apple Silicon/Intel DMG and Linux x64 AppImage) and `node` on `PATH`; a file-source or directory marketplace add also needs a package directory (see [Get the package](#get-the-package)).

**Steps.** ZCode discovers `.zcode-plugin/plugin.json`, a flat `skills/<name>/SKILL.md` layout, and loads the separate [`hooks/hooks-zcode.json`](hooks/hooks-zcode.json) wire declared by the manifest (`hooks/hooks.json` is never created — ZCode auto-loads that standard location).

1. **Settings → Plugins → Discover**, click **+** (**Create → Add marketplace**), and add the package's root [`marketplace.json`](marketplace.json) **as a file source** — the ZCode marketplace schema (`name=mrbekox`, `source="./"`, `category=developer-tools`). A directory or GitHub source is read through `.claude-plugin/marketplace.json` first and shows the Claude entry instead. Without a package directory, the GitHub repository `MrBekoX/agentic-sdlc` can be added as that source: the vendor plugin page lists a GitHub repository as a marketplace source (checked 2026-10-08), and the plugin installs with the Claude entry. The repository is public since 2026-10-12; that route has not been natively verified.
2. Review the wired hooks first: ZCode enables newly installed plugins by default, which lets their hooks run. In the **Personal** segment, **Install** the `agentic-sdlc` card.
3. Start a new session, then check **Settings → Skills** (16 plugin skills), **Settings → Hooks** (plugin hook entries), and invoke `$using-agentic-sdlc` once.

**Go condition (adapter only).** Discovery evidence: the plugin card lists name/version/category, all 16 skills appear under plugin skills, the wired hooks appear read-only under Hooks, and one router invocation routes to a focused skill. Recorded evidence does not upgrade ZCode to a supported release target.

State: GAP for the desktop flow. The manifest, marketplace and hook wire pass `tests/test_zcode_packaging.py`. Through the ZCode 3.14.5 desktop bundle's agent CLI 0.16.9, validate, marketplace add of a catalog folder derived from the root `marketplace.json` (a directory source, not the GUI file-source step), install (16 skills, 5 hook declarations), version-bumped update and uninstall passed on Windows, Linux and macOS (E9, E15, E14 in the [compatibility matrix](docs/publication/compatibility-matrix.md)). The desktop GUI flow, hook delivery inside a live session and model behavior remain unverified. The official-marketplace gap list is in [`docs/publication/zcode-marketplace.md`](docs/publication/zcode-marketplace.md).

### Kimi Code plugin install (experimental, not a release-gated path)

> **Limited runtime coverage.** Kimi Code is included in current distribution preparation with PreToolUse command guards only; no submission has been performed. See [`.kimi-plugin/README.md`](.kimi-plugin/README.md).

**Prerequisites.** Kimi Code CLI 2.1+, `node` on the hook shell `PATH`, Python 3 and Git for helper workflows (on Windows, Kimi's Bash tool needs Git for Windows), and the extracted plugin directory (or a public/authorized repository URL).

**Steps.** Kimi reads `.kimi-plugin/plugin.json` (skills, command, agents, inline `^Bash$` hooks and the `sessionStart.skill` router). In the Kimi TUI:

```text
/plugins install <package-directory>
/plugins info agentic-sdlc
/reload
```

`/plugins install https://github.com/MrBekoX/agentic-sdlc` and the custom catalog [`marketplace-kimi.json`](marketplace-kimi.json) (`/plugins marketplace <path-or-url>`) use the public repository; neither route has been natively verified. Invoke skills by bare name (`/skill:using-agentic-sdlc`). Update: reinstall a changed local directory, or press Enter on an available update in the `/plugins` Installed tab; uninstall: `/plugins remove agentic-sdlc` (the managed copy stays on disk).

State: packaging and relocated hook replays pass. Native install (16 skills and 1 command; 3 hooks reported on Windows, E4), reinstall of a version-bumped copy and removal passed on Kimi Code 2.1.1 on Windows, Linux and macOS through the local `kimi web` API (E4, E7, E12 in the [compatibility matrix](docs/publication/compatibility-matrix.md)); the TUI `/plugins install` and Enter-update from a catalog were not driven, and hook delivery inside a live session is unverified.

### Grok CLI personal marketplace (experimental, not a release-gated path)

> **Limited runtime coverage.** Grok is included in current distribution preparation. No submission has been performed here; the historical 0.4.3 verdict does not certify its native lifecycle. See the [current publication checklist](docs/publication/grok-marketplace.md). Vendor manifest validation is separate from catalog acceptance and live behavior.

**Prerequisites.** Grok CLI, `node` on the selected shell `PATH`, and the extracted plugin directory. Install with `--trust` or hooks/skills stay inactive.

**Steps.** Grok discovers `.grok-plugin/plugin.json` and `.grok-plugin/marketplace.json`, a shared `skills/<name>/SKILL.md` layout, and loads the separate [`hooks/hooks-grok.json`](hooks/hooks-grok.json) wire declared by the manifest (`hooks/hooks.json` is never created — that is Grok's auto-discovered hook file).

```text
grok plugin install <package-directory> --trust
grok plugin details agentic-sdlc
grok inspect
```

The install also enables the plugin (`grok plugin enable agentic-sdlc` only re-enables after a disable). For a path containing `#`, `cd` into the package directory and run `grok plugin install . --trust`. After install, press `r` in the Plugins tab or start a new session. The router is `/using-agentic-sdlc` (qualified `/agentic-sdlc:using-agentic-sdlc` on collision). The shipped catalog `.grok-plugin/marketplace.json` names this repository as a remote `url` source (Grok skips a catalog entry that points at the catalog's own root), so `grok plugin marketplace add https://github.com/MrBekoX/agentic-sdlc` can use the public repository; that route has not been natively verified.

**Go condition (adapter only).** Discovery evidence: `grok plugin details` / `grok inspect` list 17 plugin skills — the 16 house skills including `using-agentic-sdlc`, plus command `git-safety-check` — and `agents/*`. Recorded evidence does not upgrade Grok to a supported release target.

State: native lifecycle passed on Grok CLI 1.0.50 on Windows, Linux and macOS (E3, E8, E13 in the [compatibility matrix](docs/publication/compatibility-matrix.md)): `grok plugin install <package-directory> --trust` in an isolated profile, `grok inspect --json` listing 17 plugin skills, uninstall and reinstall of a version-bumped copy, and uninstall. History (grok 1.0.34): a name install did not find the plugin because Grok did not index the catalog's former `source: "./"` entry (the shipped catalog now uses a remote `url` entry), and `grok plugin install . --trust` on a live worktree hit Windows I/O error 5 while copying `.git`; a git-less snapshot installed. None of this upgrades Grok to a supported release target. The personal-marketplace note is [`docs/publication/grok-marketplace.md`](docs/publication/grok-marketplace.md).

### OpenAI public directory

**Prerequisites.** Maintainer-verified identity and Apps Management Write (`api.apps.write`).

**Steps.** Build the deterministic skills-only projection (Codex manifest, skills and merged references, three required stdlib helpers, contracts, assets and `LICENSE`; lifecycle hooks are excluded) with `python3 scripts/build_release.py --output <zip> --skills-only`, check it with `python3 scripts/build_release.py --verify <zip>`, then upload it through the OpenAI portal. The prepared packet is [`docs/publication/openai-skills-only.md`](docs/publication/openai-skills-only.md).

**Go condition.** The skills-only archive verifies as `archive_kind=skills-only`, the maintainer identity and `api.apps.write` are verified, and submission, acceptance and publication are treated as three separate stages. After publication, the listing changes only through a newly reviewed version ([app review](https://developers.openai.com/plugins/deploy/app-review)).

State: BLOCKED. The path needs the verified identity, `api.apps.write` and a verified skills-only archive.

## What It Is

| It is | It is not |
|---|---|
| A local development plugin for Claude Code, Codex, Kimi Code, Grok CLI and ZCode | A hosted service or CI/CD platform |
| A library of reusable SDLC skills and guardrails | A general-purpose agent harness |
| A router plus an optional full-envelope pipeline | A rule that every prompt must run the full pipeline |
| Versioned, testable documentation-as-procedure | A replacement for human review and judgment |

AGENTIC-SDLC turns repeated engineering procedure into small, verifiable capabilities: read context first, specify before building, test before claiming, review before finishing.

## Architecture

The plugin is organized around one router, independent focused skills, and one full-envelope orchestrator.

```text
user prompt
  |
  v
using-agentic-sdlc
  |-- narrow intent ------------> focused skill
  |                                spec-authoring / plan-authoring / feature-build
  |                                root-cause-fix / safe-refactor / test-authoring
  |                                security-audit / code-quality-review / ...
  |
  `-- full SDLC or high risk ---> agentic-sdlc-pipeline
                                   owns outer envelope
                                   delegates implementation core
```

`using-agentic-sdlc` routes ordinary work to the smallest sufficient independent skill. Those skills are first-class entry points: users can invoke them directly, and they remain useful without the full pipeline.

`agentic-sdlc-pipeline` is the escalation path for end-to-end or high-risk work. It owns the outer envelope: git lifecycle, analysis, spec/plan phases, validation, scope lock, quality gates, security passes, final audit, and evidence-before-claim discipline. It then feeds the approved `docs/agentic-sdlc/specs/<work_id>.md` and `docs/agentic-sdlc/plans/<work_id>.md` into the matching core skill:

| Pipeline core need | Delegated skill |
|---|---|
| New feature, endpoint, or capability | `feature-build` |
| Bug, regression, or broken behavior | `root-cause-fix` |
| Behavior-preserving restructure | `safe-refactor` |
| Test-only coverage or repair | `test-authoring` |

Gate and review skills also feed the pipeline at control points: `dispatch-strategy`, `security-audit`, `implementation-control`, and `completion-claim-gate`.

Important boundary: `spec-authoring` and `plan-authoring` are standalone prompt-level skills. The pipeline does not call them for its internal spec/plan phases. Claude Code uses the `spec-plan-draft` workflow; Codex uses the embedded author/critic adapter documented in the runtime-specific README.

## Repository Layout

```text
.claude-plugin/        Claude Code manifest, Claude-schema marketplace (Codex reads it too), runtime README
.codex-plugin/         Codex manifest and runtime README
.kimi-plugin/          Kimi Code adapter manifest and runtime README (experimental)
.zcode-plugin/         ZCode adapter manifest and runtime READMEs (experimental)
.grok-plugin/          Grok CLI adapter manifest + catalog whose entry installs from the repository URL (experimental)
.grok/workflows/       Grok CLI project workflow catalog (Rhai; loaded from the repo, not shipped by a plugin install)
marketplace.json       ZCode-schema marketplace, added as a file source
marketplace-kimi.json  Kimi Code custom catalog (installs from the repository URL)
skills/                Shared skill source: one directory per skill
agents/                Bounded sub-agent role contracts (review roles are tool-level read-only)
workflows/             Claude Code dynamic workflow scripts; workflows/zcode/ holds an UNVERIFIED ZCode port
hooks/                 Deterministic guard scripts, flow evidence, and runtime hook wiring
contracts/skills/      Durable behavior contracts
commands/              Manual slash-command definitions
scripts/               25 Python helpers: probes, validators, eval runners, release archives, marketplace staging, portability, strict evidence, versioning, git-hook install, hook trust check, native lifecycle check, Cursor package check and install
tests/                 Unit tests, harness, fixtures, golden refs, eval seeds
docs/                  Component reference, boundaries, testing, release notes
```

Skills live in root [`skills/`](skills/), not in `.claude/skills/` or `.codex/skills/`. Claude Code, Codex, Kimi Code, ZCode, Grok CLI and Cursor load this shared source tree, through an explicit manifest path or the runtime's default `skills/` layout.

## Skill Inventory

### Router

| Skill | Purpose |
|---|---|
| `using-agentic-sdlc` | Session-local router. Chooses the smallest sufficient skill and escalates only when full-envelope work is needed. |

### Core Workflow Skills

| Skill | Purpose |
|---|---|
| `agentic-sdlc-pipeline` | Full-envelope SDLC orchestrator for end-to-end or high-risk implementation. |
| `spec-authoring` | Standalone WHAT flow: requirements, acceptance criteria, behavior contract. |
| `plan-authoring` | Standalone HOW flow: task breakdown, sequencing, verification strategy. |
| `feature-build` | Focused feature or endpoint implementation. |
| `root-cause-fix` | Root-cause bug fix with regression evidence. |
| `safe-refactor` | Behavior-preserving restructure guarded by characterization tests. |
| `test-authoring` | Test-only creation, repair, or strategy. |

### Gates And Review

| Skill | Purpose |
|---|---|
| `security-audit` | Security review with masked findings. |
| `code-quality-review` | Maintainability and implementation-quality review. |
| `feedback-triage` | Verify and apply reviewer, bot, PR, or CI feedback. |
| `implementation-control` | Pre-final audit that the required flow was actually followed. |
| `completion-claim-gate` | Same-turn evidence gate before any done/fixed/passing/ready claim. |

### Utilities

| Skill | Purpose |
|---|---|
| `mind-spark` | Pre-spec intent exploration for unsettled build/design requests. |
| `dispatch-strategy` | Choose main loop, sub-agent, dynamic workflow, or agent team. |
| `skill-authoring` | Create, evaluate, and package Claude Code / Codex skills. |

## Guardrails

Deterministic hook scripts live in [`hooks/`](hooks/). Runtime wiring differs:

| Runtime | Hook wiring |
|---|---|
| Claude Code | [`hooks/hooks-claude.json`](hooks/hooks-claude.json), declared by `.claude-plugin/plugin.json`: `PreToolUse`, `PostToolUse`, `SessionStart`, and `Stop` guards. The command guards match `Bash|PowerShell` and carry no `if` filter — a `Bash`-only matcher is inert on a Windows host without Git Bash, and a subcommand-level `if` never starts the hook for a git alias, so each guard self-gates internally instead. |
| Codex | [`hooks/hooks-codex.json`](hooks/hooks-codex.json), declared in `.codex-plugin/plugin.json`, after Codex hook review/trust: `SessionStart` bootstrap **plus** native blocking `PreToolUse` command guards, a pre-write secret guard, and two `Stop` backstops. See [`docs/runtime-adapter.md`](docs/runtime-adapter.md) for the exact set and its documented coverage gaps. |
| ZCode (experimental adapter) | [`hooks/hooks-zcode.json`](hooks/hooks-zcode.json), declared by `.zcode-plugin/plugin.json`: `PreToolUse` command guards on `Bash`, `PostToolUse` write scan on `Write\|Edit`, and the `SessionStart` bootstrap on `startup\|resume\|clear\|compact`, each a `process` executor (`node` on `PATH` required). Stop completion/flow guards and the flow-order guard stay unwired; see [`docs/runtime-adapter.md`](docs/runtime-adapter.md). |
| Grok CLI (experimental adapter) | [`hooks/hooks-grok.json`](hooks/hooks-grok.json), declared by `.grok-plugin/plugin.json`: `PreToolUse` command guards on `Bash\|run_terminal_command`; fixed Node code reads `process.env.GROK_PLUGIN_ROOT` as data. Write-scan, Stop, and SessionStart remain unwired; see [`docs/runtime-adapter.md`](docs/runtime-adapter.md). |
| Kimi Code (experimental adapter) | Inline `hooks` in `.kimi-plugin/plugin.json`: three `PreToolUse` command guards (`scan-commit.mjs`, `destructive-command-guard.mjs`, `branch-guard.mjs`) on `^Bash$`, run as `node "./hooks/<handler>.mjs"` with the plugin root as hook cwd; `sessionStart.skill` loads the `using-agentic-sdlc` router. Write-scan and Stop guards are not wired and warn-only guard output is not shown; see [`.kimi-plugin/README.md`](.kimi-plugin/README.md). |
| Cursor | [`hooks/hooks-cursor.json`](hooks/hooks-cursor.json), declared by `.cursor-plugin/plugin.json`: `beforeShellExecution` command guards, `preToolUse` write scan and flow-order, `sessionStart`, and a `stop` worktree scan. Launch code reads `process.env.CURSOR_PLUGIN_ROOT`. Claude transcript Stop readers stay unwired. See [`.cursor-plugin/README.md`](.cursor-plugin/README.md). |

Claude Code wires flow enforcement through `flow-order-guard.mjs` and `flow-step-guard.mjs`. Codex uses its own `flow-order-guard-codex.mjs` and `flow-step-guard-codex.mjs` adapters over the same [`hooks/flow-requirements.json`](hooks/flow-requirements.json); the Codex order gate is opt-in and its Stop gate can continue the turn but cannot undo effects.

Guarding happens at two layers, because one of them provably cannot be complete.

**Command layer (PreToolUse).** Fast, runs before anything executes, and is the only layer that can stop a
write *before* it lands. It reads the RAW command string. Git aliases are resolved deterministically through
[`hooks/git-invocation.mjs`](hooks/git-invocation.mjs), but shell aliases and functions from `~/.bashrc`,
`$PATH` shadowing, `eval` and variable indirection are applied by the shell *after* the hook has decided, and
the write surface (`tee`, `dd`, `base64`, any interpreter) is unbounded. Those are documented residuals, not
oversights - deciding what an arbitrary shell command does is undecidable.

**Effect layer.** Closes exactly that class by never reading a command string:

| Guard | Fires on | Why the command-layer residuals do not apply |
|---|---|---|
| repo git hooks ([`scripts/install_git_hooks.py`](scripts/install_git_hooks.py)) | the git operation | git has already resolved its alias table; the shell has already done quote removal and `$PATH` lookup; owned hashes are recorded under the repo's git directory and external/shared `core.hooksPath` writes require an explicit opt-in |
| [`hooks/worktree-scan.mjs`](hooks/worktree-scan.mjs) (Stop) | bytes on disk | how they were written is irrelevant |

Verified against the real techniques: a shell function wrapping `git commit`, an `eval`-assembled commit,
`git $C` indirection, a secret inside an alias-supplied message, and writes via `tee`, `base64 -d` and
`python -c` are all caught. The documented limit of the effect layer is stated too: `git commit --no-verify`
skips `pre-commit` and `commit-msg`, while the installed `prepare-commit-msg` backstop still runs by Git's
design; the Stop scan is detection because the bytes are already on disk.
Non-negotiable enforcement belongs server-side (`pre-receive`) or in CI.

Judgment-based checks, such as whether context was actually read or test output was understood, live in skills and contracts rather than hook scripts. See [`hooks/README.md`](hooks/README.md).

## Quality Gate

Run the local gate before claiming repository health:

```bash
python3 scripts/bump_version.py --check
python3 scripts/check_all.py
python3 tests/skills/harness.py
python3 -m unittest discover -s tests -v
```

On Windows, use `py -3` for the same commands when `python3` is not on `PATH`.

This proves metadata consistency, static skill wiring, fixture health, hook/workflow syntax, and unit behavior. It does not prove live model routing or live runtime obedience. Live Claude/Codex evals require the corresponding CLI and auth; do not claim a skill "works" or "triggers" without eval output or a transcript.

## Artifact Layouts And Per-Package Evidence

Work-package artifacts resolve in two layouts: the legacy flat `docs/agentic-sdlc/{specs,plans}/<id>.md` (back-compat, unchanged) and the per-package canonical `docs/agentic-sdlc/<slug>/{spec,plan,evidence}/<work_id>.md`, where `<slug>` is lowercase kebab-case `^[a-z0-9][a-z0-9-]{0,63}$` and never a reserved name (`specs`, `plans`, `evidence`, `notes`, `spec`, `plan`).

Per-package evidence persists to `docs/agentic-sdlc/<slug>/evidence/<work_id>.md` — per-package only (flat packages get no evidence), overwritten in place per run (single canonical file, last run wins), git-ignored, and with no validator (it never gates resolution). That evidence write is performed by the main pipeline finalize step, not the read-only `implementation-auditor` sub-agent.

Per-package plan change-detection runs as a filesystem scan, not a `git status` query: the whole `docs/` tree is git-ignored, so `git status` never reports new per-package plans and the resolver scans the filesystem instead.

## More Documentation

- [`docs/plugin-readme.md`](docs/plugin-readme.md) - component-by-component reference.
- [`docs/skill-boundaries.md`](docs/skill-boundaries.md) - skill ownership, anti-overlap rules, and pipeline boundaries.
- [`docs/testing.md`](docs/testing.md) - deterministic gate, live evals, transcript checks.
- [`docs/troubleshooting.md`](docs/troubleshooting.md) - runtime loading, hooks, evals, and common failures.
- [`docs/release-readiness.md`](docs/release-readiness.md) - release evidence checklist.
- [`docs/data-handling.md`](docs/data-handling.md) - what the hooks and eval helpers read, write and mask on the local machine.
- [`SECURITY.md`](SECURITY.md) - supported versions, private reporting, and hook/eval trust boundaries.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) - contribution gate and community expectations.

## Versioning

Current version: `0.5.0`.

```bash
python3 scripts/bump_version.py --check
python3 scripts/bump_version.py <next-version>
python3 scripts/bump_version.py --release-check
```

## Related Work And Acknowledgements

[obra/superpowers](https://github.com/obra/superpowers) influenced this project's RED/GREEN/REFACTOR
teaching loop, rationalization/red-flag review mechanics, and numbered completion-gate style. This
repository independently adds multi-runtime packaging, durable behavior contracts, artifact validators,
work-package evidence, and deterministic security/flow hooks. See
[`skills/skill-authoring/references/house-notes.md`](skills/skill-authoring/references/house-notes.md)
for the detailed derivation notes. Both projects are MIT licensed.

## License

MIT - see [LICENSE](LICENSE).
