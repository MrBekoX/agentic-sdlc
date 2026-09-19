# AGENTIC-SDLC for ZCode (experimental adapter)

> ZCode is an **adapter target, not a supported 0.4.3 release target**. The supported
> release targets remain Claude Code and Codex (see the repository `README.md` and
> `docs/runtime-adapter.md`). This manifest and its hook wire are infrastructure for
> local ZCode installs; do not cite them as release support.

AGENTIC-SDLC packages gated spec/plan/TDD/security/review procedure as 16 skills, one
manual command, and deterministic guard hooks. This directory is the ZCode plugin
manifest (`.zcode-plugin/plugin.json`); the shared skill source stays at the repository
root `skills/` (flat `skills/<name>/SKILL.md` layout — no grouping folders).

## Local install

1. Open ZCode **Settings → Plugins**, **Discover** tab, and click **+**
   (**Create → Add marketplace**).
2. Add this repository root (the folder that contains `marketplace.json`, the ZCode
   marketplace schema) as a local directory or file source. ZCode validates before adding.
3. In the **Personal** segment, find the `agentic-sdlc` card (name, version, category
   `developer-tools`) and click **Install**, then **Enable**.
4. Start a new session (or reload) so skills, commands, and hooks are discovered.

Prerequisite: `node` must be on `PATH` — every hook executor is `node <script>` via argv.

## Using it

- Type `$using-agentic-sdlc` in the chat box (or open `/` → Skills) to invoke the router.
  The router picks the smallest sufficient skill; `agentic-sdlc-pipeline` only for the
  full SDLC envelope.
- Scripts resolve `${ZCODE_PLUGIN_ROOT}`; ZCode also injects the `${CLAUDE_PLUGIN_ROOT}`
  alias (per the fetched hook documentation), so house skill bodies that reference
  `${CLAUDE_PLUGIN_ROOT}` keep resolving on ZCode.
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
| `SessionStart` | `startup\|clear\|compact` | `session-start.mjs` |

Effects: the guards read the hook stdin JSON (`tool_input.command`, `tool_input` write
fields, `cwd`) and local `git` state. Denial uses the documented
`hookSpecificOutput.permissionDecision` field and the SessionStart bootstrap uses the
documented `additionalContext` field; the advisory `systemMessage` channel is a Claude
Code convention and whether ZCode displays it is unverified. There is **no network
access** (no MCP servers are declared) and no data leaves the machine. Long-lived
writable data would belong under `ZCODE_PLUGIN_DATA`, not the install directory.

Not wired on ZCode (documented gaps, see `docs/runtime-adapter.md`): the Stop
completion/flow guards (they read Claude transcripts / Codex rollouts), the flow-order
guard, the working-tree Stop scan, and the advisory-message channel above. The Claude
and Codex hook files (`hooks-claude.json`, `hooks-codex.json`) are not shared with ZCode.

## Orchestration fallback

ZCode has no Workflow runtime. Where Claude Code would run the `spec-plan-draft`
workflow and Codex its embedded adapter, a ZCode session runs the same
**author → critic → revise** discipline in the main loop with saved artifacts and
`scripts/validate_artifacts.py` evidence.

## Versioning

`version` in `.zcode-plugin/plugin.json` and in the root `marketplace.json` entry is
pinned to `VERSION` by `tests/test_zcode_packaging.py`. `scripts/bump_version.py` does
not track these two ZCode files yet — a version bump must update them by hand or the
local gate fails.

## Official marketplace submission

Not done and not claimed. What a future `zai-org/zcode-plugins` PR would still need is
listed in `docs/publication/zcode-marketplace.md`.
