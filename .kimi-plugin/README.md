# AGENTIC-SDLC for Kimi Code (experimental adapter)

Kimi Code is an experimental adapter. It was **not a 0.4.3 release target**; the
next release includes it as an experimental adapter. Native install, update and
remove passed on Kimi Code 2.1.1 on Windows, Linux and macOS, and hook registration
and delivery of the three guards passed on Kimi Code 2.7.2 on Linux, for a local and a
GitHub-URL install (see [Native evidence](#native-evidence)); live skill and model
behavior are not proven. See the [current distribution guide](../docs/publication/multi-platform-distribution.md)
for scope, evidence and publication limits.

The Kimi manifest is `.kimi-plugin/plugin.json`; the custom catalog is root
`marketplace-kimi.json`. Skills, commands and agents use the shared root
directories. Keep the complete plugin, including `hooks/`, `scripts/` and
`contracts/`; a copied `SKILL.md` alone omits its dependencies.

## Install and update

Get the package: a package directory is an extracted copy of this repository's
files. Clone the repository, or download and extract its source ZIP or a release
archive (maintainers build one with `python3 scripts/build_release.py --output agentic-sdlc.zip`;
GitHub Releases are not published yet). Keep `#` out of the path (Codex and Grok
read `#` specially). Nothing inside the folder needs editing.

Use Kimi and Node in the same OS environment, with `node` on the hook shell PATH.
Helper workflows require Python 3 (3.12 is tested; the helpers skills run are kept
import-compatible with 3.8 by a static check, not a runtime test) and Git. On
Windows, Kimi's Bash tool needs Git for Windows. In the Kimi TUI, run:

```text
/plugins install <package-directory>
/plugins info agentic-sdlc
/reload
```

The installed plugin reports 16 skills, 1 command and 3 hooks. The hooks run as
soon as the plugin is installed; review [Hooks and side effects](#hooks-and-side-effects)
first. `/new` is an alternative to `/reload`. Plugin commands are TUI slash commands;
Kimi Code CLI 2.1.1 does not expose a `kimi plugin` shell subcommand.

The official installer also accepts a ZIP URL and these full GitHub URL forms:
repository, `/tree/<ref>`, `/releases/tag/<tag>` and `/commit/<sha>`. A bare
repository URL selects its latest release, falling back to the default branch.
Choose a ref that actually contains this candidate's Kimi manifest; an older
release is not assumed to include it. Remote installation requires source access:
the repository is public since 2026-10-12. On Kimi Code 2.7.2 an install from
`https://github.com/MrBekoX/agentic-sdlc` recorded `source: github`, ref `HEAD` (the
default branch, as no release exists) and the installed commit, with 16 skills,
1 command and 3 hooks, and its hooks ran (compatibility matrix E30, E31).

To browse the prepared custom catalog:

```text
/plugins marketplace <marketplace-kimi.json-path-or-url>
```

Its `source` points at the repository URL. This downloads from that source rather
than the local checkout; use the directory install for a local candidate.
The installer copies local sources into `$KIMI_CODE_HOME/plugins/managed/<id>/`.
Editing the original directory does not update the managed copy.

For a changed local package, repeat `/plugins install <package-directory>`.
For an available remote update, open `/plugins`, select the Installed tab and
press Enter; then `/reload` or `/new` (this remote update path has not been
natively verified). Repeating installation with the intended source is also
documented. There is no `/plugins update` command promised here.

## Skills, agents and helper paths

`sessionStart.skill` selects the `using-agentic-sdlc` router. Kimi names a plugin
skill `<plugin-id>:<skill-name>`, so use `/skill:agentic-sdlc:<name>` for a skill
(Kimi's plugin documentation says a bare skill name never resolves to a plugin
skill) and `/agentic-sdlc:git-safety-check` for the command.
The manifest's `skillInstructions` supplies runtime mappings:

- Map `TaskCreate`/`TaskUpdate`/`TodoWrite` to `TodoList` when exposed.
- Dispatch a discovered custom plugin agent role when available. Otherwise use
  `coder`, `explore` or `plan` with the bundled role instructions; report the
  fallback. Do not invent `general-purpose` or assume nested agents.
- Kimi does not execute the Claude JS `Workflow` facade. Use Agent author →
  critic → revise with saved artifacts and `scripts/validate_artifacts.py`,
  or record the degraded inline pass.
- The flow runner has no Kimi engine: its own loop (`start --option loop`) is the
  only loop, and a spec is checked by one fresh reader the same way. When a flow
  runner card prints a role card (`role=`, `prompt=`, `write=`),
  give the prompt file to a new `Agent(subagent_type=<role>)`; never resume or
  fork an earlier agent for a card. Save its final message to the card's write
  path and an author's decision points to its `decisions=` path, then run the
  card's `then=` command.
- Kimi substitutes `${KIMI_SKILL_DIR}` in skill text, so the shared **Plugin root**
  rule resolves the root as `${KIMI_SKILL_DIR}/../..`. Otherwise resolve helper roots from the loaded installed
  `skills/<name>/SKILL.md` path. Root notation from another runtime means that
  installed root; it is not a promised shell environment alias.
- `KIMI_PLUGIN_ROOT` is documented for hook processes. Do not assume Bash has
  it or the `CLAUDE_PLUGIN_ROOT`/`PLUGIN_ROOT` aliases.
- Use actual tool names. Kimi uses `FetchURL`; a shared role's `WebFetch`
  allowlist entry does not grant it. If needed, choose an available profile
  with the required tools and pass the read-only role instructions.

## Hooks and side effects

The manifest declares inline `PreToolUse` rules for `Bash`. They run as soon as
the plugin is installed:

| Handler | Timeout (seconds) |
|---|---|
| `scan-commit.mjs` | 20 |
| `destructive-command-guard.mjs` | 15 |
| `branch-guard.mjs` | 15 |

Each command is `node "./hooks/<handler>.mjs"` with process cwd equal to the
installed plugin root. The Bash tool's own `tool_input.cwd` (or else the stdin `cwd`)
identifies the repository the command runs in for Git
checks. Guards read `tool_input.command` and local Git state, and can return
`hookSpecificOutput.permissionDecision: "deny"`. Branch warning/block behavior
follows the configured house policy; Kimi shows only blocking decisions, so warn-mode
messages are not visible there (Kimi reads a top-level `message`, and the warning is in
`systemMessage`; in a live 2.7.2 turn with a repo-local Git identity the warned commit
succeeded on `main` and no warning text reached the next model request, E31). Hook errors fail open, so Node availability
is required. No MCP server or network integration is declared.

Write scanning and Claude/Codex transcript-based Stop/flow readers remain
unwired because this candidate has no verified Kimi input/reader contract.
Startup uses `sessionStart.skill` rather than the Claude `session-start.mjs`
hook (see below). Static packaging and relocated handler replays do not prove installer,
router invocation, frontmatter tolerance, update or native lifecycle behavior;
the native lifecycle evidence is listed below. A manually copied managed
directory is not an installer transcript.

### Why Stop and SessionStart stay unwired

The Kimi hooks reference (checked 2026-11-21) defines an output contract the
shared handlers do not follow:

- A `Stop` hook blocks only with exit 2 and the reason on stderr, or with stdout
  `hookSpecificOutput.permissionDecision: "deny"`; a blocked Stop starts a
  continuation turn. The Stop matcher is an empty string.
- `SessionStart` is observation-only: it cannot block, and its exit-0 stdout
  "may be appended to context".
- The payload is snake_case with no transcript field and no `stop_hook_active`.

The shared Stop handlers (`worktree-scan.mjs` and the completion and flow guards)
print Claude-style `decision`/`systemMessage` JSON and exit 0, which is not a
documented Kimi block. The guards read a transcript Kimi does not provide, and
their `stop_hook_active` loop guard would never fire. `session-start.mjs` prints
`hookSpecificOutput.additionalContext` JSON and runs Git in the process cwd,
which the Kimi plugins page sets to the plugin root (the hooks page says the session's
project directory; the docs do not reconcile them, checked 2026-11-21). Routing is already done by
`sessionStart.skill`, so a SessionStart hook would add nothing.

A future Kimi mode would need Stop results as exit 2 with a stderr reason (or the
deny JSON), SessionStart context as plain stdout text, loop protection that does
not rely on `stop_hook_active` (for example a per-turn counter keyed by
`session_id` and `turn_id`), no transcript dependency, and the project taken from
the payload `cwd` rather than the process cwd.

Verified natively on Kimi Code 2.7.2 (2026-11-22, compatibility matrix E30, E31):

- K4, GitHub-installed hooks: after an install from the GitHub URL, the plugin reports
  3 hooks and they fired in a live turn, as they do for a local-directory install.
- K5, the extra `hookEventName` key: the installed binary's hook parser
  (`runHook.ts` `structuredOutput()`) reads stdout with a zod `looseObject`, which keeps
  unknown keys and ignores them; only `hookSpecificOutput.permissionDecision: "deny"` on
  exit 0, or exit 2, blocks. In live turns the deny payload with `hookEventName` blocked
  `git reset --hard`, a commit on `main` in block mode and a commit of a staged secret, and
  each `permissionDecisionReason` reached the model as the tool error. No Kimi output mode
  is needed for the PreToolUse guards.

The live turns ran `kimi -p` against a local OpenAI-compatible endpoint that scripts one
`Bash` call, so no Kimi account was used; they prove hook delivery, not model behavior. A
turn with a Kimi model needs `kimi login`.

## Native evidence

Kimi Code 2.1.1 passed the native lifecycle on Windows, Linux and macOS on
2026-10-12 in isolated profiles: install reporting 16 skills and 1 command (3 hooks
reported on Windows, E4), reinstall of a changed (version-bumped) copy observed in the managed copy,
and removal, with unrelated state preserved (E4, E7, E12 in the
[compatibility matrix](../docs/publication/compatibility-matrix.md)). The runs
drove Kimi's own plugin manager through the local authenticated `kimi web` API,
not the TUI `/plugins install` command, and did not exercise the Enter-update
path. Earlier preparation evidence is in
[marketplace readiness](../docs/publication/marketplace-readiness-2026-10-11.md).

Hook evidence, Kimi Code 2.7.2 on Linux, 2026-11-22 (E30, E31): the CLI from the
official `code.kimi.com/kimi-code/install.sh` installer, isolated profile, plugin
installed through the same `kimi web` API from the package directory and from the
GitHub URL; headless `kimi -p` turns against a local OpenAI-compatible endpoint (no
Kimi account) showed all three guards blocking and a removed plugin letting the same
command run. Skill triggering and vendor-model behavior were not measured.

## Versioning and publication

`scripts/bump_version.py` tracks `.kimi-plugin/plugin.json` and `VERSION`;
`tests/test_kimi_packaging.py` checks their agreement. The catalog's
`"version": "2"` is its schema version, not the plugin version.

Directory, ZIP URL, GitHub URL and custom catalog distribution are documented.
No Official/Curated submission has been made, and no self-service submission
contract is documented in the reviewed sources. Follow the
[publication note](../docs/publication/kimi-marketplace.md) before making a
listing or broader runtime-support claim.

## Uninstall

In the TUI, run `/plugins remove agentic-sdlc`, confirm the native prompt, then
`/reload` or `/new`. Removal deletes the installed record but retains the managed
copy on disk. Use Kimi's manager; preserve unrelated plugin records and files.
See the [lifecycle guide](../docs/publication/multi-platform-distribution.md).

## Official sources (checked 2026-10-10)

- [Plugins, installer and updates](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/plugins.html)
- [Hook payload and failure behavior](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/hooks.html)
- [Custom agents and tool allowlists](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/agents.html)
