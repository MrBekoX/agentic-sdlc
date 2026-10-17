# AGENTIC-SDLC for Cursor

Cursor loads this package from [`.cursor-plugin/plugin.json`](plugin.json). Skills, agents and the `git-safety-check` command are the shared files at the repository root. Cursor-only pieces are `rules/agentic-sdlc.mdc` and `hooks/hooks-cursor.json`. `hooks/hooks.json` is intentionally absent so Claude Code, ZCode and Grok do not auto-load a Cursor wire.

The manifest and component layout follow the Cursor plugin reference fetched on 2026-10-14 from [cursor.com/docs/reference/plugins](https://cursor.com/docs/reference/plugins). Hook fields follow [cursor.com/docs/hooks](https://cursor.com/docs/hooks) from the same day. This environment had no `cursor` or `cursor-agent` binary, so the steps below were checked as a file copy plus hook replay, not as a live IDE session.

## Requirements

| Tool | Where it is needed | If it is missing |
|---|---|---|
| Cursor | Desktop or CLI that can load `~/.cursor/plugins/local` | The package cannot be discovered |
| Node.js 22 or newer | `node` on `PATH` for every hook | `scripts/install_cursor_plugin.py` exits with `error=node_missing`. A crash of the commit and destructive hooks is fail-closed |
| Python 3.8+ | `python3`, `python`, or `py -3` for `scripts/validate_artifacts.py` and `scripts/detect_context.py` | Install exits with `error=python_missing` |
| Git | Branch, commit and worktree guards | Install exits with `error=git_missing` |

On Windows, macOS and Linux the installer uses the current user's home directory. It does not embed a username, drive letter or checkout path. Windows uses `%USERPROFILE%\.cursor\plugins\local\agentic-sdlc`. macOS and Linux use `~/.cursor/plugins/local/agentic-sdlc`.

Enterprise administrators control local plugin imports under Dashboard → Settings → Security & Identity → Marketplace and Plugins. That control is off by default on Enterprise. A marketplace plugin of the same name takes precedence over the local copy.

## Install

Get a package directory: clone this repository, or extract a source archive. From that directory:

```bash
python3 scripts/install_cursor_plugin.py install
```

On Windows, use `py -3` when `python3` is missing or is the Microsoft Store alias. Then run **Developer: Reload Window** and open **Customize**. The plugin name is `agentic-sdlc`.

The installer copies the package. Cursor does not load a symlink in `~/.cursor/plugins/local` whose target sits outside that folder. Pass `--dest` only when you need a different directory; the default is the documented local plugin folder.

## Update

```bash
python3 scripts/install_cursor_plugin.py update
```

Reload the window afterwards. The update replaces files this installer wrote. A file you added inside the destination, and every Cursor setting outside it (`~/.cursor/hooks.json`, other plugins, user settings), stays. Edits you made to installed plugin files are replaced, because those files belong to the package.

## Uninstall

```bash
python3 scripts/install_cursor_plugin.py uninstall
```

This deletes only the paths recorded in `.cursor-plugin/install-receipt.json` inside the destination. If that receipt is missing, the command refuses and deletes nothing. Files you added, and the rest of `~/.cursor`, stay. Remove a team-marketplace install from Customize or the dashboard; this script does not call the dashboard.

## Use

In a project chat:

```text
/using-agentic-sdlc
```

Ask for the smallest procedure, for example a plan-only change, and the router selects `plan-authoring`. A full spec, plan, implementation, test, security and completion request uses:

```text
/agentic-sdlc-pipeline
```

The read-only review command is:

```text
/git-safety-check
```

Cursor has no Claude Workflow tool. Spec and plan drafting uses the author, then a fresh-context critic from `agents/`, then a revision. The sessionStart hook adds the installed plugin root to the conversation so helper commands can quote that path.

## What is wired

| Cursor component | Source | Behavior |
|---|---|---|
| Skills | `skills/*/SKILL.md` | The shared 16 skills, invoked as `/<skill-name>` or by reading `SKILL.md` |
| Agents | `agents/*.md` | Shared review and drafting roles |
| Commands | `commands/git-safety-check.md` | Read-only git safety check |
| Rules | `rules/agentic-sdlc.mdc` | Always-on pointer at the skills and contracts |
| Hooks | `hooks/hooks-cursor.json` | Command guards, write scan, flow-order, startup context, opt-in worktree scan |

Hook commands read `CURSOR_PLUGIN_ROOT` inside Node. They do not splice the install path into shell code, so a path with spaces or non-ASCII characters stays data. `hooks/cursor-launch.mjs` maps Cursor's hook JSON onto the shared handlers and maps their decisions back to `permission`, `additional_context` or `followup_message`.

## Limits

- Claude `completion-claim-guard.mjs` and `flow-step-guard.mjs` are not wired. They read Claude transcripts. Completion evidence stays the `completion-claim-gate` skill.
- The default worktree-scan advisory is not shown. Cursor's documented `stop` output is `followup_message`, and sending the advisory there would start another turn. Set `AGENTIC_WORKTREE_SCAN_BLOCK=true` to forward a finding as that follow-up.
- Flow-order warns by default. Cursor `preToolUse` has no documented allow-time context field, so the warning is not converted into a deny. `AGENTIC_FLOW_GATE_BLOCK=true` denies the edit.
- Flow-order activates on a `Skill` tool call to a flow skill, or on a Claude Code slash-command record (`<command-name>/<skill></command-name>`). Cursor's documented invocations, `/<skill-name>` and reading `SKILL.md`, are not known to record either, so flow-order is not known to gate `agentic-sdlc-pipeline` or any other flow; no test covers activation from a real Cursor transcript.
- A write-scan finding is a `preToolUse` deny. `afterFileEdit` documents no model-visible output.
- `beforeShellExecution` warnings, including the default protected-branch warning, use `permission: ask`.
- There is no MCP server in this plugin.
- Public marketplace submission has not been sent. See [cursor-marketplace.md](../docs/publication/cursor-marketplace.md).

## Team marketplace

Dashboard → Plugins & MCPs → Add Marketplace → Import from Repo, and paste:

```text
https://github.com/MrBekoX/agentic-sdlc
```

Cursor reads [`.cursor-plugin/marketplace.json`](marketplace.json). The single entry's `source` is `.`, the repository root, which contains `.cursor-plugin/plugin.json`. This import is a Teams or Enterprise feature. It is separate from the local installer.
