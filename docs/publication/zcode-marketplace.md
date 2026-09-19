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
  `name`/`version`/`source`/`category=developer-tools`). This is the local-install
  marketplace file; an official PR would instead add an entry to the official repo's
  own root `marketplace.json`.
- `.zcode-plugin/README.md` + `.zcode-plugin/README_CN.md` documenting behavior and
  side effects (hooks, command execution, no network / no MCP).
- Version binding to `VERSION` via `tests/test_zcode_packaging.py`.
- Two keys sit outside the strict documented field lists and rely on official-example
  evidence: `description_i18n` in the plugin manifest (present in the official
  example-plugin manifest) and the extra `tools:` / `model:` keys in `agents/*.md`
  frontmatter (ZCode documents only required `name` + `description` there). The
  pending local discovery run must confirm the client emits no unknown-field
  diagnostics for either before any submission.

## Missing before an official PR

1. **Layout**: the official marketplace requires each plugin to live in a unique
   kebab-case directory under `plugins/` of that repository. This repo is a plugin
   root itself, so the PR would copy/package the plugin into that layout (or the
   entry's `source` would point at this repository, if accepted).
2. **Validation scripts**: `python3 scripts/validate.py` and
   `python3 scripts/build_dist.py` are maintainer scripts in the official repository;
   they have not been run against this plugin and no result is claimed.
3. **User-facing README pair at the plugin root**: the official requirements ask for
   equivalent `README.md` and `README_CN.md` user-facing files; the prepared pair
   lives under `.zcode-plugin/` and may need to move or duplicate per the PR review.
4. **Category check**: `developer-tools` is one of the supported categories
   (`developer-tools`, `productivity`, `utilities`, `finance`, `guides`, `template`,
   `other`); the official listing pipeline may still normalize or reject it.
5. **Immutability discipline**: published versions are immutable and never reused; a
   submission freeze means every later content change bumps the version in both the
   plugin manifest and the official marketplace entry.
6. **Live evidence**: the contribution guide asks contributors to exercise the
   plugin's main behavior in ZCode and document reproducible steps; no such official
   -marketplace run is recorded yet.
7. **Third-party assets/licenses**: the README must identify bundled third-party
   assets and their licenses; the acknowledgement of obra/superpowers in the
   repository `README.md` would need to be surfaced in the plugin README pair.

## Explicitly out of scope for this worktree state

No zip artifacts, `sha256`, or `_artifact` fields have been fabricated for the local
directory source — those belong to the official distribution's zip channel and are
produced by the maintainers' `build_dist.py`. No PR, fork, version bump, or
marketplace submission has been performed.
