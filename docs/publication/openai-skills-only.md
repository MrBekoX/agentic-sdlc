# OpenAI skills-only submission packet

This packet prepares an `agentic-sdlc` upload to the OpenAI public plugin directory. Submission, acceptance and publication are three separate stages, and none of them has happened.

## Archive definition

- The skills-only archive holds exactly the committed files under `.codex-plugin/`, `skills/`, `hooks/`, `contracts/skills/`, `scripts/` and `assets/`, plus `LICENSE` (BR24).
- It is built with `python3 scripts/build_release.py --output <zip> --skills-only` and checked with `python3 scripts/build_release.py --verify <zip>`, which reports `archive_kind=skills-only`. It is a separate archive from the general release ZIP.
- The governing manifest is `.codex-plugin/plugin.json` (DP11).
- It has no `.claude-plugin/`, `commands/`, `agents/`, `workflows/`, `docs/` or `tests/` member and no MCP configuration.
- The OpenAI guide requires that no skill relies on commands or agents ([submit a Claude plugin](https://developers.openai.com/plugins/guides/submit-claude-plugin), observed 2026-09-14).
- GAP: `agentic-sdlc-pipeline` step 16 (`SKILL.md` and `playbook.md`) tells the agent to run the read-only `git-safety-check` command, which lives in `commands/` and is not in this archive.
- GAP: skills name `agents/` roles (`code-reviewer`, `context-analyst`, `debugger`, `implementation-auditor`, `security-reviewer`, `software-architect`, `spec-plan-author`, `spec-plan-critic`, `test-engineer`) that are not in this archive; there those roles run only through each skill's degraded inline fallback.
- The OpenAI path stays GAP until pipeline step 16 has a skills-only fallback.

## Listing fields

The `interface` block of `.codex-plugin/plugin.json`, as pinned by `tests/test_packaging_metadata.py`:

| Field | Value |
|---|---|
| `brandColor` | `#20806E` (at least 2.0 contrast against white) |
| `category` | `Developer Tools` |
| `screenshots` | no key |
| `termsOfServiceURL`, `privacyPolicyURL`, `websiteURL` | no key |
| `displayName`, `shortDescription` | at most 30 characters each |
| `longDescription` | at most 4000 characters |
| `defaultPrompt` | 2 entries, each at most 128 characters |
| `logo`, `composerIcon` | square PNG files inside the package, 48 to 4096 px per side |

## Guard statement

Installs through ChatGPT get no guard enforcement from this package. The guards are local Codex and Claude Code hook behavior, and they run only after the user reviews and trusts the hooks in that runtime.

## Prerequisites

Maintainer-verified identity and Apps Management Write (`api.apps.write`): BLOCKED until the maintainer verifies both.

## Listing risk

The portal resets `author.name` and `interface.developerName` to defaults when they do not match the verified publisher identity. This is recorded for maintainer review (DP14); no identity data is copied into this packet.

## Naming

- An update whose package name differs from the published plugin fails with `plugin_name_mismatch` ([submission errors](https://developers.openai.com/plugins/deploy/submission-errors)).
- Submitted information and reviewed metadata are locked after publication, and the listing changes only through a newly reviewed version ([app review](https://developers.openai.com/plugins/deploy/app-review)).
- The fixed identity of this plugin is `agentic-sdlc`.

## Other items

- Privacy link: the DP10 record. `docs/data-handling.md` is linked only through a URL whose `docs/publication/link-checks.json` entry records 200; GAP today.
- Security-report mechanism: GAP, because the GitHub private vulnerability reporting API returns 404 while the repository is private.
- DP24 top-level URLs: `homepage` and `repository` point at the repository URL, recorded as 404, so both are GAP until 200; `author.url` has a recorded 200 entry.
- Ledger rows: `skills_only_archive` and `portal_normalized_manifest` in `## Required release rows` of [`../release-evidence-0.4.3.md`](../release-evidence-0.4.3.md). They stay not-run or BLOCKED until a maintainer-approved upload.

## Maintainer-evening items (D24)

These maintainer-evening items happen outside agent execution:

- The public repository is a new, clean repository created together with the maintainer (option C).
- The portal upload is done together with the maintainer. The agent submits nothing.
- The listing and top-level URLs are re-checked against that new repository at that time.
