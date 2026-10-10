# Grok CLI distribution and official catalog checklist

All five platforms are included in this distribution preparation; Grok runtime
coverage remains experimental. The historical certification was **not a 0.4.3 release target**.
See [multi-platform distribution](multi-platform-distribution.md) for the current
scope. No catalog PR, release tag or external publication has been performed.

The current manifest and catalog use `.grok-plugin/plugin.json` and
`.grok-plugin/marketplace.json`. The catalog's `source: "./"` points at the
package root. Hook commands read the installed root from `GROK_PLUGIN_ROOT`
inside Node; no maintainer drive path is required. Both Grok versions are tracked
by `scripts/bump_version.py`.

## Install and update a prepared directory

Extract the complete full package and use Grok and Node in the same OS environment.
Ensure `node` is on the selected hook shell PATH:

```text
grok plugin install <package-directory> --trust
grok plugin enable agentic-sdlc
grok plugin details agentic-sdlc
grok inspect --json
```

Registering a marketplace is optional for this directory install:

```text
grok plugin marketplace add <package-directory>
grok plugin marketplace list
grok plugin list --json --available
```

Install by name only after the available list shows `agentic-sdlc`. Historical
Grok 1.0.34 name lookup did not expose this catalog's local `source: "./"` entry;
directory installation was the recorded fallback. Copying the live checkout
also hit a Windows `.git` access error. These are historical observations,
not a native installer result for the current candidate or Grok 1.0.50.

For a reachable repository, the documented GitHub shorthand can register its
marketplace:

```text
grok plugin marketplace add MrBekoX/agentic-sdlc
```

Grok documents GitHub shorthand, git URLs and local directories as sources;
private repositories depend on each installer's git credentials. An official
catalog remote source must instead be public and pinned as described below.
Source visibility and policy restrictions are separate installation gates.

For an added marketplace and installed plugin:

```text
grok plugin marketplace update mrbekox
grok plugin update agentic-sdlc
```

Reinstall a refreshed local directory when there is no remote update to fetch.
Press `r` in Plugins or start a new session. Review trust before enabling;
do not silently change organization policy or experimental settings.

## Official xAI catalog submission

The [official contribution guide](https://github.com/xai-org/plugin-marketplace/blob/main/CONTRIBUTING.md)
accepts reviewed catalog PRs. The following are manual publication steps:

1. Freeze and review the actual release commit and package evidence. Confirm the
   source is public and the selected commit is reachable; resolve any separate
   privacy/history release blocker before changing repository visibility.
2. In a fork of `xai-org/plugin-marketplace`, add one unique kebab-case entry to
   `.grok-plugin/marketplace.json`. A remote third-party entry uses
   `source: {"source":"url","url":"https://github.com/MrBekoX/agentic-sdlc.git","sha":"<actual-full-commit-sha>"}`.
   Replace the placeholder with the real 40-character lowercase commit SHA;
   do not submit a branch, tag, abbreviated SHA or fabricated value.
3. Alternatively vendor a local third-party plugin under
   `external_plugins/agentic-sdlc/` and point a local `source.path` there.
   Include a README, manifest, license, homepage and explicit hook side effects.
4. Run the marketplace repository's own tools:

   ```text
   python3 scripts/generate-plugin-index.py
   python3 scripts/validate-catalog.py
   python3 scripts/generate-plugin-index.py --check
   ```

5. Open the PR with its template and wait for CI and code-owner review.
   For later updates, change the existing entry's remote SHA (or vendored files)
   and regenerate the index.

This repository's optional `.grok-plugin/plugin-index.json` is not shipped;
personal directory installs do not require it. Official catalog generation is
a different repository's publication requirement. Local `grok plugin validate`
or an inventory showing skills is not proof of catalog acceptance or live behavior.
Rhai workflows remain separate project/user catalogs, not a delivered plugin
component.

## Evidence still required

The current scope covers static wiring/dependency checks and relocated handler
replays. Native clean install, trust, update, skill invocation and supported-host
behavior need separate runtime evidence before broader certification. Unverified
write/startup/Stop readers remain unwired; no such execution is claimed.

## Official sources (checked 2026-10-10)

- [Runtime plugin reference](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/09-plugins.md)
- [Runtime hook reference](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/10-hooks.md)
- [Official catalog format](https://github.com/xai-org/plugin-marketplace)
- [Contribution and validation steps](https://github.com/xai-org/plugin-marketplace/blob/main/CONTRIBUTING.md)
