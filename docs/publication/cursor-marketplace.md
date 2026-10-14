# Cursor marketplace packet

Prepared for a later submission. Nothing in this packet has been sent to [cursor.com/marketplace/publish](https://cursor.com/marketplace/publish).

The shape follows the Cursor plugin reference fetched on 2026-10-14:

- [Plugins](https://cursor.com/docs/plugins)
- [Plugins reference](https://cursor.com/docs/reference/plugins)
- [Hooks](https://cursor.com/docs/hooks)

## Files

| File | Role |
|---|---|
| `.cursor-plugin/plugin.json` | Cursor plugin manifest. `name` is `agentic-sdlc`. Component paths are relative and stay inside the repository. |
| `.cursor-plugin/marketplace.json` | Marketplace index `mrbekox` with one plugin. `source` is `.`, the repository root. |
| `.cursor-plugin/README.md` | Install, update, uninstall, usage and limits. |
| `rules/agentic-sdlc.mdc` | Rule frontmatter has `description` and `alwaysApply`. |
| `hooks/hooks-cursor.json` | Hook events. Commands read `CURSOR_PLUGIN_ROOT` in Node. |
| `skills/`, `agents/`, `commands/` | Shared with the other adapters. |

`hooks/hooks.json` and a root `plugin.json` are not part of this packet. Those filenames are auto-loaded by other adapters.

## Local check

```bash
python3 scripts/check_cursor_plugin.py
python3 scripts/check_plugin_portability.py
python3 scripts/install_cursor_plugin.py install --dest <scratch-directory> --skip-dependency-check
```

`--skip-dependency-check` is for a scratch directory in a test. A user install omits it, so a missing Node, Python or Git command stops the copy with an `error=` line.

## Submission checklist

- [x] `.cursor-plugin/plugin.json` exists and `name` is lowercase kebab-case
- [x] Description, version, author, license, repository and keywords are present
- [x] Logo path `assets/logo.png` is inside the repository
- [x] Skills, agents, commands, rules and hooks use relative paths that exist
- [x] Skill, agent, command and rule files carry the documented frontmatter
- [x] `.cursor-plugin/marketplace.json` lists one plugin whose source resolves to `.cursor-plugin/plugin.json`
- [x] README documents install, update, uninstall and configuration
- [ ] Plugin tested inside the Cursor IDE. Not done here: `cursor` and `cursor-agent` were not installed. Hook replay and a clean copy are not an IDE load
- [ ] Submitted at cursor.com/marketplace/publish. Do not submit from this packet until a maintainer chooses to

## Not in this submission

No MCP server is declared. No plugin variable schema is declared, and no `${VAR}` secret placeholder is used. Do not add a token to the repository.
