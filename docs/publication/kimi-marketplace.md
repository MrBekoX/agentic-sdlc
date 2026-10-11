# Kimi Code distribution checklist (experimental adapter)

Kimi is included in the current five-platform distribution preparation. The
historical certification was **not a 0.4.3 release target**; see
[multi-platform distribution](multi-platform-distribution.md) for current scope.
No external listing or publication has been performed.

## Prepared package

- `.kimi-plugin/plugin.json` declares shared `skills/`, `commands/` and
  `agents/`, the `sessionStart.skill` router, runtime `skillInstructions`
  and three inline `PreToolUse` Bash guards.
- Guard commands are `node "./hooks/<handler>.mjs"` with installed root cwd.
  They keep installed-path bytes outside shell command text.
- `marketplace-kimi.json` uses the documented custom catalog schema:
  `{"version":"2","plugins":[{"id","displayName","source"}]}`.
  The real `source` is this repository's GitHub URL; it selects remote content,
  not the local candidate. Verify that the selected release/ref includes the
  Kimi manifest before advertising that remote installation.
- `scripts/bump_version.py` tracks the Kimi plugin version. Catalog schema
  version `"2"` remains unchanged by a plugin version bump.
- The full directory includes shared hooks, scripts, contracts and role files.

## Supported distribution and update methods

Use the Kimi TUI's slash commands, with Node available in the same OS environment:

```text
/plugins install <package-directory>
/plugins info agentic-sdlc
/reload
```

The installer also supports ZIP URLs and four full GitHub URL forms:

```text
https://github.com/<owner>/<repo>
https://github.com/<owner>/<repo>/tree/<ref>
https://github.com/<owner>/<repo>/releases/tag/<tag>
https://github.com/<owner>/<repo>/commit/<sha>
```

The bare repository form selects its latest release, with default-branch
fallback. Do not assume a private GitHub source uses the same authentication as
another platform's git installer; that path has not been verified.

Browse the custom catalog with
`/plugins marketplace <marketplace-kimi.json-path-or-url>`. The installer copies
local sources into `$KIMI_CODE_HOME/plugins/managed/<id>/`; changing the source
directory afterward requires reinstallation. Installs currently apply per-user
across projects.

To update a local candidate, repeat its directory install. In `/plugins`,
Installed → Enter applies an available remote update. Then use `/reload` or
`/new` to activate changes. `/plugins reload` reloads installation records and
manifests; it does not copy changed local source files.

## Runtime scope and evidence

The manifest maps discovered custom agents first, with `coder`/`explore`/`plan`
fallback when a role is unavailable. Resolve helper paths from the loaded Skill
file's installed root. `KIMI_PLUGIN_ROOT` is documented for hook subprocesses;
a Bash alias or automatic `CLAUDE_PLUGIN_ROOT` substitution is not promised.

Current evidence adds an authenticated native Kimi 2.1.1 loopback management
install/recopy/remove check to packaging and relocated handler execution.
It does not certify router activation, native hook execution or
native skill/agent behavior. Earlier manual managed-copy probes are not proof
that `/plugins install` or GitHub download ran. Write scanning and transcript-based
Stop/flow guards remain unwired; Claude JS workflows use the documented author →
critic → revise fallback.

## Official/Curated listing still requires vendor guidance

The reviewed plugin reference describes Kimi-maintained Official entries and
partner Curated entries, but gives no self-service contribution contract for
this package. Obtain the vendor's actual submission, review and publication
requirements before claiming listing readiness. A custom catalog is a
supported distribution route; it is not acceptance into those curated tabs.

Before broader certification, record the real installer and update action,
source/ref, Kimi version, supported-host results, loaded components and hook
behavior. Keep test receipts separate from native lifecycle evidence and
report every unrun host or probe.

## Official sources (checked 2026-10-10)

- [Plugin formats, custom catalogs and installer](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/plugins.html)
- [Hooks](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/hooks.html)
- [Agents and delegation](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/agents.html)
