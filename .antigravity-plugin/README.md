# agentic-sdlc — Google Antigravity Experimental Adapter

> Status: **Experimental adapter**. **Not a supported release target** (supported release targets remain Claude Code and Codex; see [`docs/runtime-adapter.md`](../docs/runtime-adapter.md) and [`docs/publication/multi-platform-distribution.md`](../docs/publication/multi-platform-distribution.md)). The native install, reinstall and uninstall of the built package and one headless turn were recorded with agy 1.5.14 on 2026-11-21 ([compatibility matrix](../docs/publication/compatibility-matrix.md#google-antigravity)); nothing else is claimed.

Sources, all read on 2026-11-21: the references bundled with the Antigravity CLI `agy` 1.5.14 (`build-plugins.md`, `subagents.md`, and the `agy-customizations` skill's `hooks.md`), the [workflows-to-skills migration page](https://antigravity.google/docs/migration/workflows-to-skills), and `agy` 1.5.14 runs in isolated profiles. A claim below without one of these sources is marked unverified.

## 1. Manifest (`.antigravity-plugin/plugin.json`)

agy reads the manifest in place at `<plugin-root>/.antigravity-plugin/plugin.json`; it takes precedence over a root `plugin.json`, so no root `plugin.json` is created (a root one would also reach Codex's portable-manifest loader). The schema `https://antigravity.google/schemas/v1/plugin.json` requires only `name` (kebab-case) and sets `additionalProperties`: `false`; its other properties include `displayName`, `description`, `version`, `logo`, `author`, `homepage`, `repository`, `license` and `keywords`.

This manifest carries `name`, `displayName`, `version`, `description`, `author`, `homepage`, `repository`, `license`, `keywords` and `logo` (`assets/logo.png`). `version` is one of the versioned manifests in `scripts/bump_version.py`, so `--check` fails when it differs from `VERSION` and a bump rewrites it. agy reads the version from this file; without one it fell back to `.claude-plugin/plugin.json` (probe, 2026-11-21).

## 2. Build, install, upgrade and uninstall

Build the package from the committed tree, extract it, and install the folder:

```bash
python3 scripts/build_release.py --output <zip> --antigravity
python3 scripts/build_release.py --verify <zip>
python3 -m zipfile -e <zip> <package-dir>
agy plugin validate --json <package-dir>
agy plugin install <package-dir>
```

`agy plugin install` takes a folder, not a `.zip`, and copies it into `~/.gemini/config/plugins/agentic-sdlc/`. The package holds `.antigravity-plugin/plugin.json`, a root `hooks.json` (a copy of [`.antigravity-plugin/hooks.json`](hooks.json)), the hook launcher and the handlers it starts, the 16 skills, `contracts/`, `scripts/`, `flows/`, `assets/`, the roles as agy agents in `agents/`, the docs and workflow file the skills name as `<runtime-root>/...`, this README and `LICENSE`. It holds no `commands/`, `rules/`, `cursor/` or other runtime's manifest or hook wire.

- Upgrade: build the new version and run `agy plugin install <package-dir>` again; it replaces the installed folder. There is no `agy plugin update` in agy 1.5.14 (`agy update` updates the CLI).
- Uninstall: `agy plugin uninstall agentic-sdlc`. Unrelated files in the profile stay.
- A workspace-only install is the same folder at `<workspace>/.agents/plugins/agentic-sdlc/`.
- `agy plugin validate --strict` reports one warning, a known limitation: agy loads only the first 24000 bytes of a `SKILL.md` body, and `skills/agentic-sdlc-pipeline/SKILL.md` is larger. The skill is not split; the rest of that file is not in the model's context on agy.

## 3. Roles as agy agents

`scripts/project_roles.py --target antigravity` generates `agents/<role>.md` from the shared `agents/*.md` at build time. agy skips an agent whose `tools` is a comma string, so each generated agent has a YAML-list `tools` of agy runtime names (`Read`/`Glob`/`Grep` -> `read_file`, `WebFetch`/`WebSearch` -> `search_web`, `Write` -> `write_file`, `Edit`/`MultiEdit` -> `edit_file`, `Bash`/`PowerShell` -> `run_command`), `model: inherit`, `subagent: true` and `mainAgent: false`. A read-only role (no write or shell tool) also gets `inheritMcp: false`. The body is the shared role body, byte for byte. `agy plugin validate` reports 11 agents.

agy has no grep, glob or directory-list tool, so a read-only role can only read the files it is told about: the orchestrating skill passes it an explicit file list (for example from the diff). The tool allowlist was enforced in a live probe; the runtime still added `manage_task` and the MCP tools (`inheritMcp` defaults to `true`). What `manage_task` can do there is unverified.

## 4. Hooks

The root `hooks.json` is one named group, `agentic-sdlc`. agy runs each command with `sh -c` (`cmd /c` on Windows, unverified here) in the folder that holds `hooks.json` and exports `PLUGIN_ROOT`, so the commands are relative: `node ./hooks/agy-launch.mjs --event <event> --handler <file>`.

| Event | Matcher | Shared handler |
|---|---|---|
| `PreToolUse` | `run_command` | `scan-commit.mjs`, `destructive-command-guard.mjs`, `branch-guard.mjs` |
| `PreToolUse` | `write_file\|edit_file` | `scan-write.mjs` |
| `SessionStart` | — | `session-start.mjs` |
| `Stop` | — | `worktree-scan.mjs` |

`hooks/agy-launch.mjs` reads the payload's `toolCall.name` and `toolCall.args` (`CommandLine`; `Path` with `Content` for `write_file`; `Path` with `Replacement` for `edit_file`), hands the shared handler the Claude-shaped input it already reads, and prints one JSON object: a deny becomes `{"decision":"deny","reason":...}`, a warning becomes an allow with a `reason`, and anything else `{"decision":"allow"}`. A PreToolUse guard that crashes, times out or prints something other than a JSON object denies the call; agy itself also fails closed on a non-zero exit or invalid JSON from a PreToolUse hook (probe, 2026-11-21). SessionStart injects the bootstrap as `injectSteps` `systemMessage`; Stop continues the agent only when `AGENTIC_WORKTREE_SCAN_BLOCK` is set, the scan finds a secret and `continuationActive` is not `true`. Payload text never reaches a shell.

Not wired: the flow-order guard and the completion-claim and flow-step Stop readers, which read a Claude transcript and Claude `Skill`/`Agent` tool events that agy does not produce. `PostToolUse`, `PreInvocation` and `PostInvocation` are not used.

## 5. Runtime capabilities on Antigravity

| Capability | Antigravity mechanism | Adapter behavior |
|---|---|---|
| Session router (`using-agentic-sdlc`) | SessionStart bootstrap, the skill catalog, `/using-agentic-sdlc` | The bootstrap names the router; read the selected `SKILL.md` with `read_file` before acting. |
| Plugin root (`<runtime-root>`) | Two levels above the loaded `SKILL.md` | Verify `<runtime-root>/scripts/validate_artifacts.py` exists and pass that quoted absolute path to `python3` (`py -3` on Windows). `PLUGIN_ROOT` is exported to hook commands only. |
| Specialist subagents | `invoke_subagent` | Use the bundled agent of the role, or pass the body of `<runtime-root>/agents/<role>.md` (frontmatter stripped) to a built-in subagent. Give read-only roles explicit file lists. If `invoke_subagent` is unavailable, run inline and record `Delegation Degraded: subagents unavailable (single-session inline fallback)`. |
| Workflows (`spec-plan-draft`, `multi-lens-review`, `skill-draft`) | Embedded author -> critic -> revise via `invoke_subagent` + `validate_artifacts.py` | Antigravity `.agents/workflows/*.md` prompt macros are deprecated (no removal date announced) and are not Claude Code's JS `Workflow` runtime; no `.agents/workflows/` file is used. |
| Commands | — | `commands/` is not shipped: agy reported converting `git-safety-check` to a skill on install, but no such skill folder appeared and its use in a session is unverified. Known gap: the pipeline's read-only `git-safety-check` step has no installed command on agy. |
| Artifact and evidence paths | Dual layout under `docs/agentic-sdlc/` | Unchanged; change detection uses `resolve_work_package.py`. |
