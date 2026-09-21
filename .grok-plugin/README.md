# AGENTIC-SDLC for Grok CLI (experimental adapter)

> Grok CLI is an **adapter target, not a supported 0.4.3 release target**. The
> supported release targets remain Claude Code and Codex (see the repository
> `README.md` and `docs/runtime-adapter.md`). This manifest and its hook wire are
> infrastructure for a local Grok personal marketplace; do not cite them as
> release support. `grok plugin validate .` going green against the Claude layout
> is not Grok-native publish.

AGENTIC-SDLC packages gated spec/plan/TDD/security/review procedure as 16 skills,
one manual command (`git-safety-check`), and deterministic guard hooks. This
directory is the Grok plugin manifest (`.grok-plugin/plugin.json`) plus the
marketplace index Grok reads (`.grok-plugin/marketplace.json`). The shared skill
source stays at the repository root `skills/` — do not copy skills into
`.grok/skills/`; that path is project-skill discovery, not a plugin.

The marketplace `name` is `mrbekox`, the same house catalog name used by the
Claude and ZCode indexes, so one owner is recognizable across adapters. Grok
reads this file independently of those other-runtime indexes.

## Local install

From this repository root (`node` must be on `PATH` — every hook command starts
`node ${GROK_PLUGIN_ROOT}/hooks/<script>.mjs`):

```text
grok plugin marketplace add .
grok plugin install agentic-sdlc --trust
grok plugin enable agentic-sdlc
grok plugin details agentic-sdlc
grok inspect
```

`--trust` is required. Without it, Grok leaves the plugin's hooks, MCP servers,
and skills inactive (`09-plugins.md`). This clone is a **marketplace source**,
not a copy under `.grok/plugins/`. Plugins placed in `~/.grok/plugins/` are
auto-trusted; project plugins in `.grok/plugins/` still require trust. Install
with `--trust` rather than copying the tree into those directories.

Plugins stay off until enabled (`09-plugins.md`). If `grok plugin list` shows
the plugin disabled after install, run `grok plugin enable agentic-sdlc`.

A newly installed plugin is picked up by pressing `r` in the Plugins tab
(`Ctrl+L` / `/plugins`) or by starting a new session.

## Using it

- `/using-agentic-sdlc` invokes the router. On a name collision the qualified
  form is `/agentic-sdlc:using-agentic-sdlc` (`08-skills.md`).
- The router picks the smallest sufficient skill; `agentic-sdlc-pipeline` only
  for the full SDLC envelope.
- Scripts resolve `${GROK_PLUGIN_ROOT}`. Grok also injects the
  `${CLAUDE_PLUGIN_ROOT}` alias (`09-plugins.md`), so house skill bodies that
  already use `${CLAUDE_PLUGIN_ROOT}` keep resolving.
- The manual command `git-safety-check` is discovered from `commands/`.
- Plugin agents under `agents/` must not declare `mcpServers`, hooks, or
  `permissionMode: bypassPermissions` (`16-subagents.md`).

## Trust and side effects

Enabling this plugin with `--trust` is a decision to let its hooks run code.
The wired hooks (`hooks/hooks-grok.json`) execute `node` scripts on:

| Event | Matcher | Handlers |
|---|---|---|
| `PreToolUse` | `Bash\|run_terminal_command` | `scan-commit.mjs`, `destructive-command-guard.mjs`, `branch-guard.mjs` |

Effects: the guards read hook stdin JSON (`toolInput.command`, with
`tool_input.command` as the Claude/Codex fallback) and local `git` state.
They can deny a `PreToolUse` call (`decision` / `permissionDecision`). There
is **no network access** (no MCP servers, no `.mcp.json`) and no data leaves
the machine. Long-lived writable data belongs under `GROK_PLUGIN_DATA`, not
the install directory.

Not wired on Grok (documented gaps, see `docs/runtime-adapter.md`): write-scan
(`search_replace` `toolInput` keys were not captured as hook stdin this
session), Stop completion/flow guards (they read Claude transcripts or Codex
rollouts; Grok Stop fields `lastAssistantMessage` / `stopHookActive` /
`reason == "end_turn"` were not captured), SessionStart, and the working-tree
Stop scan. The Claude, Codex, and ZCode hook files are not shared with Grok.

## Orchestration (project-catalog Rhai)

Grok discovers workflows from `.grok/workflows/*.rhai` (project) and
`~/.grok/workflows/*.rhai` (user), not from the plugin package. This clone
ships Rhai ports of the three Claude JS loops at
`.grok/workflows/spec-plan-draft.rhai`, `multi-lens-review.rhai`, and
`skill-draft.rhai`. Claude `workflows/*.js` stay the Claude runtime source;
Grok does not load them. `grok plugin details` still inventories
skills/commands/agents/hooks only — installing the plugin on another machine
does not deliver these project-catalog scripts.

When the named script is in the catalog and workflows are enabled, invoke
`/workflow spec-plan-draft` (or `multi-lens-review` / `skill-draft`) or the
`workflow` tool with that name. If Grok workflows are disabled or the named
script is missing, fall back to `spawn_subagent` plus **author → critic →
revise**, with saved artifacts and `scripts/validate_artifacts.py` evidence.
Do not call Claude JS `Workflow` on Grok.

## Versioning

`version` in `.grok-plugin/plugin.json` and in `.grok-plugin/marketplace.json`
is pinned to `VERSION` by `tests/test_grok_packaging.py`.
`scripts/bump_version.py` does not track these two Grok files yet — a version
bump must update them by hand or the local gate fails.

## Official directory submission

Not done and not claimed. There is no official xAI plugin directory
submission in this work. How someone else adds this repository as a personal
marketplace (including the private-repo 404 and `--trust`) is in
`docs/publication/grok-marketplace.md`. That note is not a publish.
