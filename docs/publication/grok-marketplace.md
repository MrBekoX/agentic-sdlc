# Grok CLI distribution and official catalog checklist

All five platforms are included in this distribution preparation; Grok runtime
coverage remains experimental. The historical certification was **not a 0.4.3 release target**.
See [multi-platform distribution](multi-platform-distribution.md) for the current
scope. No catalog PR, release tag or external publication has been performed.

The current manifest and catalog use `.grok-plugin/plugin.json` and
`.grok-plugin/marketplace.json`. The catalog entry names this repository as a remote
`{"source": "url", "url": "https://github.com/MrBekoX/agentic-sdlc.git"}` source:
Grok cannot point an entry at the catalog's own root (`MarketplaceRelativePath`
strips `./`, the remainder is empty and the scanner skips the entry; on Grok 1.0.50
an isolated `plugin list --available` returned `[]` for the former `"./"` entry and
listed the plugin for a sub-directory or `url` entry). Hook commands read the
installed root from `GROK_PLUGIN_ROOT` inside Node; no maintainer drive path is
required. Both Grok versions are tracked by `scripts/bump_version.py`.

## Install and update a prepared directory

Extract the complete full package and use Grok and Node in the same OS environment.
Ensure `node` is on the selected hook shell PATH:

```text
grok plugin install <package-directory> --trust
grok plugin details agentic-sdlc
grok inspect --json
```

The install enables the plugin; `grok plugin enable agentic-sdlc` is needed only after
a `grok plugin disable`. Use an absolute or `./`-relative directory. A local install
is refreshed by `grok plugin uninstall agentic-sdlc` and a new directory install:
`grok plugin update` reports it as already live, and installing over it reports
AlreadyInstalled.

For a reachable (public or credential-backed) repository, register the catalog:

```text
grok plugin marketplace add MrBekoX/agentic-sdlc
grok plugin marketplace list
grok plugin list --json --available
grok plugin install agentic-sdlc --trust
```

Grok names a marketplace after its source's last path segment, not the catalog's
`name` field; use the name `grok plugin marketplace list` prints. Grok documents
GitHub shorthand, git URLs and local directories as sources; private repositories
depend on each installer's git credentials. An official catalog remote source must
be public and pinned as described below. Source visibility and policy restrictions
are separate installation gates.

For an added Git marketplace and installed plugin:

```text
grok plugin marketplace update <source-name>
grok plugin update agentic-sdlc
```

A copied live checkout once hit a Windows `.git` access error on Grok 1.0.34; install
from an extracted package directory instead.
On native Grok 1.0.50, local `plugin update` does not recopy the installed
directory, and reinstalling the same source reports "already installed". Refresh a
local install by uninstalling and installing the new directory after reviewing
retained data (verified natively on 1.0.50, see the
[compatibility matrix](compatibility-matrix.md)); then press `r` in Plugins or start a
new session. A moving Git branch supports a genuine fetch/update, verified with a
disposable offline Git fixture. For a path containing `#`, change into that directory
and run `grok plugin install . --trust`: 1.0.50 treats `#` in an absolute source
operand as a subdirectory suffix. Review trust before enabling;
do not silently change organization policy or experimental settings.

## Official xAI catalog submission

The [official contribution guide](https://github.com/xai-org/plugin-marketplace/blob/main/CONTRIBUTING.md)
accepts reviewed catalog PRs. The following are manual publication steps:

1. Freeze and review the actual release commit and package evidence. Confirm the
   source is public and the selected commit is reachable; resolve any separate
   privacy/history release blocker before changing repository visibility.
2. In a fork of `xai-org/plugin-marketplace`, add one unique kebab-case entry to
   `.grok-plugin/marketplace.json`. A remote third-party entry uses
   `source: {"type":"url","url":"<public-repository-git-url>","sha":"<actual-full-commit-sha>"}`.
   Replace the placeholder with the real 40-character lowercase commit SHA;
   do not submit a branch, tag, abbreviated SHA or fabricated value.
3. Alternatively vendor a local third-party plugin under
   `external_plugins/agentic-sdlc/` and use
   `source: {"type":"local","path":"./external_plugins/agentic-sdlc"}`.
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

Current Windows 1.0.50 evidence includes isolated native install/remove,
authorized temporary trust and an offline moving-branch Git update with changed
installed bytes and HEAD. Local-copy update/reinstall limitations above were
observed directly. Pinned official catalog tools are exercised on a single-plugin
fixture; see [current preparation](marketplace-readiness-2026-10-11.md).
Native hook delivery, live skill invocation and supported-host
behavior need separate runtime evidence before broader certification. Unverified
write/startup/Stop readers remain unwired; no such execution is claimed.

## Official sources (checked 2026-10-10)

- [Runtime plugin reference](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/09-plugins.md)
- [Runtime hook reference](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/10-hooks.md)
- [Official catalog format](https://github.com/xai-org/plugin-marketplace)
- [Contribution and validation steps](https://github.com/xai-org/plugin-marketplace/blob/main/CONTRIBUTING.md)
