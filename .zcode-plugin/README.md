# AGENTIC-SDLC for ZCode (experimental adapter)

> ZCode is an **adapter target, not a supported 0.4.3 release target**. The supported
> release targets remain Claude Code and Codex (see the repository `README.md` and
> `docs/runtime-adapter.md`). This manifest and its hook wire are infrastructure for
> ZCode marketplace installs — the root `marketplace.json` as a file source, or this
> repository from a local directory or GitHub — and are not release support.

AGENTIC-SDLC packages gated spec/plan/TDD/security/review procedure as 16 skills, one
manual command, and deterministic guard hooks. This directory is the ZCode plugin
manifest (`.zcode-plugin/plugin.json`); the shared skill source stays at the repository
root `skills/` (flat `skills/<name>/SKILL.md` layout — no grouping folders).

## Install

Get the package: the file source is the root `marketplace.json` inside a package
directory, an extracted copy of this repository's files. Clone the repository, or
download and extract its source ZIP or a release archive (maintainers build one with
`python3 scripts/build_release.py --output agentic-sdlc.zip`; GitHub Releases are not
published yet). Nothing inside the folder needs editing. ZCode desktop builds exist for
Windows (x64/ARM64), macOS (Apple Silicon/Intel DMG) and Linux (x64 AppImage).

1. Open ZCode **Settings → Plugins**, **Discover** tab, and click **+**
   (**Create → Add marketplace**).
2. Add the root `marketplace.json` (the ZCode marketplace schema) **as a file source**.
   A directory or GitHub source is read through `.claude-plugin/marketplace.json` first,
   which still installs the plugin but shows the Claude entry without the ZCode category,
   tags and translations. ZCode validates before adding.
3. Review the hook table under **Trust and side effects** first: newly installed plugins
   are **enabled by default**, which lets their hooks run. In the **Personal** segment,
   find the `agentic-sdlc` card (name, version, category `developer-tools`) and click
   **Install**. It is enabled at once; use **Enable** in Manage installed only after a disable.
4. Start a new session (or reload) so skills, commands, and hooks are discovered.

Without a local package directory, add the GitHub repository `MrBekoX/agentic-sdlc` (or
its URL) as the marketplace source in step 2. The repository is public since
2026-10-12; this route has not been natively verified. The vendor plugin page lists a GitHub
repository as a marketplace source (checked 2026-10-08). ZCode reads that source through
`.claude-plugin/marketplace.json` first, as step 2 describes: the plugin installs with the
Claude entry, without the ZCode category, tags and translations.

Prerequisites: `node` must be on `PATH` — every hook executor is `node <script>` via argv.
Helper workflows also need Python 3 (3.12 is tested; the helpers skills run are kept
import-compatible with 3.8 by a static check) and Git; on Windows, use `py -3` when
`python3` is missing or is the Microsoft Store alias. On macOS, a GUI app started from
Finder or the Dock may not inherit your shell `PATH`; if ZCode cannot find `node`, the
hooks fail open and the guards silently do nothing. Check that `node` is visible to the
ZCode app, not only to your terminal (not verified here).

## Using it

- Type `$using-agentic-sdlc` in the chat box (or open `/` → Skills) to invoke the router.
  The router picks the smallest sufficient skill; `agentic-sdlc-pipeline` only for the
  full SDLC envelope.
- Hook processes receive `${ZCODE_PLUGIN_ROOT}` and a `${CLAUDE_PLUGIN_ROOT}` alias. Skill
  text gets only `${CLAUDE_SKILL_DIR}` / `${ZCODE_SKILL_DIR}` substituted, so skills locate
  bundled helpers with their **Plugin root** rule (`${CLAUDE_SKILL_DIR}/../..`) or the
  root line the SessionStart hook prints.
- The manual command `git-safety-check` is discovered from `commands/` (the command name
  comes from the file name).
- Sub-agents under `agents/` carry `name` + `description` frontmatter as ZCode requires.

## Trust and side effects

Enabling this plugin is a decision to let its hooks run code. The wired hooks
(`hooks/hooks-zcode.json`) execute `node` scripts on these verified events and tools:

| Event | Matcher | Handlers |
|---|---|---|
| `PreToolUse` | `Bash` | `scan-commit.mjs`, `destructive-command-guard.mjs`, `branch-guard.mjs` |
| `PostToolUse` | `Write\|Edit` | `scan-write.mjs` |
| `SessionStart` | `startup\|resume\|clear\|compact` | `session-start.mjs` |

Effects: the guards read the hook stdin JSON (`tool_input.command`, `tool_input` write
fields, `cwd`) and local `git` state. Denial uses the documented
`hookSpecificOutput.permissionDecision` field and the SessionStart bootstrap uses the
documented `additionalContext` field. The write scanner's advisory reaches the model as
`hookSpecificOutput.additionalContext`. The scripts detect ZCode through two documented
mechanisms — the wire passes a literal `--zcode-runtime` argv element and ZCode injects
`ZCODE_PLUGIN_ROOT` as an environment variable — and in that mode emit only documented
keys (`hooks/hook-output.mjs`): warns move into `hookSpecificOutput.additionalContext`,
and the advisory top-level `systemMessage` channel (a Claude Code convention) is never
written. The live hook doc says ZCode ignores unknown fields, while the bundled
`diagnosing-hooks` skill says any extra key fails the run and discards its effect; the
output is safe under either reading. Native display and invocation remain unverified.
There is **no network
access** (no MCP servers are declared) and no data leaves the machine. Long-lived
writable data would belong under `ZCODE_PLUGIN_DATA`, not the install directory.

Not wired on ZCode (documented gaps, see `docs/runtime-adapter.md`): the Stop
completion/flow guards (they read Claude transcripts / Codex rollouts), the flow-order
guard and the working-tree Stop scan. The Claude
and Codex hook files (`hooks-claude.json`, `hooks-codex.json`) are not shared with ZCode.

## Orchestration fallback

ZCode added dynamic workflows in client 3.14.0 (official changelog, 2026-09-19),
started from the input-box plus menu or `/workflow`. The open-source client stores
saved workflows in the project's `.zcode/workflows/` or the user's `~/.zcode/workflows/`
folder, but `plugin.json` has no `workflows` component key — so **this plugin cannot
ship you one**. Where Claude Code would run
the `spec-plan-draft` workflow and Codex its embedded adapter, a ZCode session runs
the same **author → critic → revise** discipline in the main loop with saved
artifacts and `scripts/validate_artifacts.py` evidence. The unverified port kept at
`workflows/zcode/spec-plan-draft.dwf.ts` is a starting point for a live run, not a
supported path.

## Versioning

`version` in `.zcode-plugin/plugin.json` and in the root `marketplace.json` entry is
tracked by `scripts/bump_version.py` and pinned to `VERSION` by
`tests/test_zcode_packaging.py`. ZCode offers an update only when the version changes:
refresh the marketplace, then use Manage installed → Check for updates, apply the
update and start a new session. See [distribution preparation](../docs/publication/multi-platform-distribution.md)
for current scope and publishing requirements.

## Uninstall

Open Settings → Plugins → Manage installed → the plugin details, then Uninstall; ZCode
asks for confirmation before it removes the plugin. Persistent-data retention is not
specified in the reviewed vendor documentation, so do not assume uninstall deletes it.
Use the native UI and preserve unrelated plugins/settings. See the
[lifecycle guide](../docs/publication/multi-platform-distribution.md).

## Native evidence

The signed ZCode desktop 3.14.5 distribution's bundled agent CLI 0.16.9 passed isolated
native validate, marketplace add of a catalog folder derived from the root
`marketplace.json` (a directory source, not the GUI file-source step), install (enabled,
16 skills, five hook declarations), version-bumped update and confirmed uninstall on
2026-10-12: Windows (E9), Linux x64 AppImage (E15) and macOS Apple Silicon DMG (E14) in
the [compatibility matrix](../docs/publication/compatibility-matrix.md). That CLI manages
plugins only in Electron's Node mode, which is not a documented user path, so this
verifies the bundled plugin manager only; the desktop GUI flow, a GitHub source, actual
hook delivery and model behavior remain unverified. Earlier preparation evidence is in
[marketplace readiness](../docs/publication/marketplace-readiness-2026-10-11.md).

## Official marketplace submission

Not done and not claimed. What a future `zai-org/zcode-plugins` PR would still need is
listed in `docs/publication/zcode-marketplace.md`.

## License and attribution

MIT; see [LICENSE](../LICENSE). [obra/superpowers](https://github.com/obra/superpowers)
(also MIT licensed) influenced parts of the skill procedure; see the
[repository README](../README.md#related-work-and-acknowledgements).
