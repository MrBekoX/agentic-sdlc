# ZCode official marketplace — future PR package draft (NOT submitted)

Status: adapter infrastructure only. Nothing here has been submitted to
`zai-org/zcode-plugins`, and no fork or pull request exists. This note records what a
future official-marketplace PR would still need, from the official contribution
requirements fetched on 2026-09-19
([CONTRIBUTING.md](https://raw.githubusercontent.com/zai-org/zcode-plugins/main/CONTRIBUTING.md),
[distribution.md](https://raw.githubusercontent.com/zai-org/zcode-plugins/main/docs/distribution.md)).

## Already prepared locally

- `.zcode-plugin/plugin.json` with `name`, `description`, `description_i18n` (`en` +
  `zh-CN`), `version`, and `author`.
- Root `marketplace.json` in the ZCode schema (`name=mrbekox`, `plugins[]` entry with
  `name`/`version`/`source`/`category=developer-tools`). This is the marketplace file
  a user adds as a file source; an official PR would instead add an entry to the
  official repo's own root `marketplace.json`.
- `.zcode-plugin/README.md` + `.zcode-plugin/README_CN.md` documenting behavior and
  side effects (hooks, command execution, no network / no MCP).
- Version binding to `VERSION` via `tests/test_zcode_packaging.py`.
- Two keys sit outside the strict documented field lists and rely on official-example
  evidence: `description_i18n` in the plugin manifest (present in the official
  example-plugin manifest) and the extra `tools:` / `model:` keys in `agents/*.md`
  frontmatter (ZCode documents only required `name` + `description` there).
  `plugins validate` from the ZCode desktop 3.14.5 bundle's agent CLI 0.16.9 exited 0
  for this package on Windows, Linux and macOS
  ([compatibility matrix](compatibility-matrix.md) E9, E15, E14), so neither key fails
  that validator. The runs checked the exit status only, not the output, so a
  non-fatal diagnostic was not assessed; the desktop GUI was not exercised.

## Missing before an official PR

1. **Layout**: the official marketplace requires each plugin to live in a unique
   kebab-case directory under `plugins/` of that repository. This repo is a plugin
   root itself, so the PR copies the prepared plugin into that layout. The current
   official validator requires the exact local source `./plugins/agentic-sdlc`;
   it does not accept a remote repository source as an alternative.
2. **Validation scripts**: `python3 scripts/validate.py` and
   `python3 scripts/build_dist.py` are maintainer scripts in the official repository;
   they are pinned and run in a separate local single-plugin fixture. Their
   actual outputs and identities are in [current preparation](marketplace-readiness-2026-10-11.md).
   Fixture validation does not publish their generated CDN URLs.
3. **User-facing README pair at the plugin root**: the official requirements ask for
   equivalent `README.md` and `README_CN.md` user-facing files; the prepared pair
   lives under `.zcode-plugin/`. The staging helper produces an equivalent root
   English/Chinese pair with rebased links, prerequisites, hook side effects and
   third-party attribution; original source READMEs remain separate.
4. **Category check**: `developer-tools` is one of the supported categories
   (`developer-tools`, `productivity`, `utilities`, `finance`, `guides`, `template`,
   `other`); the official listing pipeline may still normalize or reject it.
5. **Immutability discipline**: published versions are immutable and never reused; a
   submission freeze means every later content change bumps the version in both the
   plugin manifest and the official marketplace entry.
6. **Live evidence**: the contribution guide asks contributors to exercise the
   plugin's main behavior in ZCode and document reproducible steps; no such official
   -marketplace run is recorded yet. The signed desktop 3.14.5 bundle's agent CLI
   0.16.9 now has isolated native validate/install/versioned-update/uninstall and
   component discovery evidence on Windows, Linux and macOS
   ([compatibility matrix](compatibility-matrix.md) E9, E15, E14). Desktop GUI, hook
   execution and live model behavior remain separate boundaries.
7. **Third-party assets/licenses**: the README must identify bundled third-party
   assets and their licenses. The root README pair that
   `scripts/prepare_marketplace_release.py` projects already carries a license and
   provenance section (MIT license, the obra/superpowers (MIT) influence, no
   third-party prebuilt binaries); review it against the final submitted bundle.

## Explicitly out of scope for this worktree state

No zip artifacts, `sha256`, or `_artifact` fields have been fabricated for the local
directory source — those belong to the official distribution's zip channel and are
produced by the maintainers' `build_dist.py`. No PR, fork, version bump, or
marketplace submission has been performed.
