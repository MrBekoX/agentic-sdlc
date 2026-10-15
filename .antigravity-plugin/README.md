# agentic-sdlc — Google Antigravity Experimental Adapter

> Status: **Experimental adapter** for local workspace and user-level plugin/skill installs. **Not a supported release target** (supported release targets remain Claude Code and Codex; see [`docs/runtime-adapter.md`](../docs/runtime-adapter.md) and [`docs/publication/multi-platform-distribution.md`](../docs/publication/multi-platform-distribution.md)).

## 1. Verified Antigravity Manifest Schema (`plugin.json`)

The official Antigravity plugin schema (`https://antigravity.google/schemas/v1/plugin.json`, published at `https://antigravity.google/docs/plugins`) specifies:

- `required`: `["name"]` (`pattern: "^[a-zA-Z0-9-_]+$"`)
- `properties`: `name` (`string`) and `description` (`string`)
- `additionalProperties`: `false`

Accordingly, `.antigravity-plugin/plugin.json` contains **only** the verified `name` and `description` fields and does not copy Claude Code or Codex manifest keys (`version`, `author`, `license`, `skills`, `hooks`, `interface`). Version tracking for this schema-constrained manifest is handled in `scripts/bump_version.py` (`VERSIONLESS_PLUGIN_MANIFESTS`), which verifies that `.antigravity-plugin/plugin.json` stays registered and free of unsupported keys across version bumps.

### Why `plugin.json` and `hooks/hooks.json` are not at the repository root

1. **Codex 0.154.0 hook compatibility:** Codex `loader.rs` treats any repository containing a root `plugin.json` as a portable `AgentPlugin` and suppresses all 8 legacy hooks in `hooks/hooks-codex.json`.
2. **Cross-runtime hook auto-discovery:** Claude Code, ZCode, and Grok CLI auto-discover `hooks/hooks.json` when present.

To preserve Claude Code and Codex behavior while supporting Antigravity's `<plugin-root>/plugin.json` layout, keep `.antigravity-plugin/plugin.json` in this adapter directory inside the source repository and copy it to `<installed-plugin-root>/plugin.json` when staging an Antigravity plugin install.

## 2. Local Installation & Staging (Antigravity IDE & Antigravity 2.0 App)

Antigravity discovers plugins from:
- **Workspace plugin root:** `<workspace>/.agents/plugins/agentic-sdlc/` (or paths listed in `<workspace>/.agents/plugins.json`)
- **Global user plugin root:** `~/.gemini/config/plugins/agentic-sdlc/`
- **Antigravity CLI (`agy`) root:** `~/.gemini/antigravity-cli/plugins/agentic-sdlc/` (via `agy plugin install <staged-dir>`)

### Stage an isolated Antigravity plugin directory

From the repository root, stage the single-source skills, contracts, runtime helpers, assets, and commands alongside `.antigravity-plugin/plugin.json` as `<plugin-root>/plugin.json`:

```bash
# Example target: <workspace>/.agents/plugins/agentic-sdlc
# (or ~/.gemini/config/plugins/agentic-sdlc for a user-wide install)
TARGET="<workspace>/.agents/plugins/agentic-sdlc"
mkdir -p "$TARGET"
cp .antigravity-plugin/plugin.json "$TARGET/plugin.json"
cp -R skills contracts scripts assets commands LICENSE "$TARGET/"
```

```powershell
# PowerShell equivalent
$Target = "<workspace>\.agents\plugins\agentic-sdlc"
New-Item -ItemType Directory -Force -Path $Target | Out-Null
Copy-Item ".antigravity-plugin\plugin.json" (Join-Path $Target "plugin.json") -Force
foreach ($item in @("skills", "contracts", "scripts", "assets", "commands", "LICENSE")) {
    Copy-Item $item $Target -Recurse -Force
}
```

> **Important — Do not copy `agents/*.md` as custom Antigravity subagent definitions without tool-name mapping:**
> The official Antigravity Subagents documentation (`https://antigravity.google/docs/subagents`) warns:
> *"Known issue (tool validation): Specifying an unmapped or misspelled tool name in the `tools` list may cause the subagent process to hang during execution. Double-check exact tool names (such as `view_file` or `run_command`) when configuring custom subagents."*
> Because `agents/*.md` declare Claude Code tool names (`Glob, Grep, Read, WebFetch, WebSearch`), copy `agents/` into `<plugin-root>/agents/` **only** when read as role instruction files by built-in subagents (`research` / `self`), or keep `agents/*.md` as role reference files and invoke Antigravity's built-in `research` (read-only) or `self` subagent via `invoke_subagent`.

### Workspace skill-only discovery (no plugin wrapper)

In a repository checkout or workspace skill setup, Antigravity also discovers skills directly from `<workspace>/.agents/skills/<skill-name>/SKILL.md` or `~/.gemini/config/skills/<skill-name>/SKILL.md`.

## 3. Runtime Capabilities & Fallbacks on Antigravity

| Capability | Antigravity Mechanism | Adapter Behavior & Notes |
|---|---|---|
| **Session router (`using-agentic-sdlc`)** | `AGENTS.md` (`always_on` rule in repo checkouts) + `<skills>` catalog / `/using-agentic-sdlc` slash command | In repo checkouts, `AGENTS.md` loads automatically as an `always_on` rule and routes through `using-agentic-sdlc`. In plugin installs, invoke `/using-agentic-sdlc` or rely on autonomous `<skills>` description matching. |
| **Skill discovery & invocation** | `<plugin-root>/skills/<name>/SKILL.md` or `.agents/skills/<name>/SKILL.md`; `/<skill-name>` slash command or `view_file` | Antigravity injects each discovered skill's description and exact absolute `SKILL.md` path into `<skills>`. Read the selected `SKILL.md` with `view_file` before acting. |
| **Plugin root (`<runtime-root>`)** | Portable two-levels-up resolution from `<runtime-root>/skills/<name>/SKILL.md` | Antigravity does not export an undocumented plugin-root environment variable into shell commands. Resolve `<runtime-root>` as the directory two levels above the loaded `SKILL.md` path shown in `<skills>`, verify `<runtime-root>/scripts/validate_artifacts.py` exists, and pass that quoted absolute path to `python3` (or `py -3` on Windows). |
| **Rules & contracts** | Workspace `AGENTS.md` / `GEMINI.md` (`always_on`); on-demand `<runtime-root>/contracts/skills/*.md` | `contracts/skills/00`–`10` stay single-source on-demand skill contracts rather than always-on `.agents/rules/*.md` files (`trigger: always_on`), preserving session context budget. |
| **Specialist subagents** | `invoke_subagent` tool (`TypeName: "research"` for read-only roles; `TypeName: "self"` with `Workspace: "branch"` for isolated writes) | Read the specialist instructions from `<runtime-root>/agents/<role>.md` (stripping YAML frontmatter) and pass them in `Prompt` to `invoke_subagent` with `TypeName: "research"` (read-only) or `"self"`. Do not register custom `agents/*.md` with unmapped Claude tool names (`Glob`, `Grep`, `Read`), which can hang subagent validation. If `invoke_subagent` is unavailable, run inline and record `Delegation Degraded: subagents unavailable (single-session inline fallback)`. |
| **Workflows (`spec-plan-draft`, `multi-lens-review`, `skill-draft`)** | Embedded author -> critic -> revise adapter via `invoke_subagent` + `validate_artifacts.py` | Legacy Antigravity `.agents/workflows/*.md` prompt macros are deprecated on **October 19, 2026** (`https://antigravity.google/docs/migration/workflows-to-skills`) and are not equivalent to Claude Code's JS `Workflow` runtime. No `.agents/workflows/` files are used. Draft artifacts, dispatch a fresh-context critic via `invoke_subagent(TypeName="research")`, revise up to 2 rounds, and run `validate_artifacts.py` (or record `Delegation Degraded: no-workflow-runtime (single-session inline fallback)` when subagents are unavailable). |
| **Hooks (`PreToolUse`, `PostToolUse`, `SessionStart`, `Stop`)** | `<plugin-root>/hooks.json` or `.agents/hooks.json` (**unwired by default**) | Antigravity hooks use a named-group top-level schema (`{"<group>": {"enabled": true, "PreToolUse": [...]}}`), `toolCall.name` / `toolCall.args` (`run_command` with `CommandLine`/`Cwd`, `write_to_file`/`replace_file_content` with `TargetFile`), `workspacePaths[]`, and require `{"decision": "allow"\|"deny"\|...}` on `PreToolUse` stdout. Existing `hooks/*.mjs` target Claude/Codex/Grok/ZCode payloads and are **not wired by default** on Antigravity. Prompt/skill gates are procedural only and do not provide deterministic pre-tool blocking unless an approved Antigravity hook adapter is wired. |
| **Artifact & evidence paths** | Dual layout (`docs/agentic-sdlc/specs/<work_id>.md` + `docs/agentic-sdlc/<slug>/spec/<work_id>.md`, `docs/agentic-sdlc/<slug>/evidence/<work_id>.md`) | Per-package evidence at `docs/agentic-sdlc/<slug>/evidence/<work_id>.md` is per-package-only, overwritten per run, git-ignored, has no validator mode, and is written by the main finalize step — not the read-only auditor. Change detection uses a filesystem scan via `resolve_work_package.py`. |
