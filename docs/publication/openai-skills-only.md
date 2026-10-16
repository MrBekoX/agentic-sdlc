# OpenAI skills-only submission packet

This packet prepares an `agentic-sdlc` upload to the OpenAI public plugin directory. Submission, acceptance and publication are three separate stages, and none of them has happened.

## Archive definition

- The skills-only archive is a deterministic public projection of committed source (BR24), separate from the unchanged manual Claude/Codex distribution. It contains `.codex-plugin/plugin.json`, source `skills/` (with each skill's `references/`, including the four work-type `references/core.md` files that `agentic-sdlc-pipeline` Steps 8–13 read), `contracts/skills/`, `assets/`, `LICENSE`, and three stdlib Python helpers: `scripts/detect_context.py`, `scripts/validate_artifacts.py`, `scripts/resolve_work_package.py`.
- It is built with `python3 scripts/build_release.py --output <zip> --skills-only` and checked with `python3 scripts/build_release.py --verify <zip>`, which reports `archive_kind=skills-only`. It is a separate archive from the general release ZIP.
- The governing manifest is `.codex-plugin/plugin.json` (DP11).
- It has no lifecycle hook files, `.claude-plugin/`, `commands/`, `agents/`, `workflows/`, root `docs/` or `tests/` member and no MCP configuration. The public manifest has no `hooks` field. General release and manual install hooks remain unchanged.
- The OpenAI guide requires reusable command/agent procedures to become skills and lifecycle hooks to be removed for public submission ([submit a Claude plugin](https://developers.openai.com/plugins/guides/submit-claude-plugin), checked 2026-10-06). This projection merges the procedures into skill references without adding routing descriptions or altering source Claude behavior.
- `skills/using-agentic-sdlc/references/public-runtime.md` maps all nine bundled role instructions to native subagent dispatch. Each public skill requires loading this guide; the actual role body must be supplied to a specialist before delegation. Inline review is allowed only when native delegation is unavailable and must be labelled degraded.
- `skills/using-agentic-sdlc/references/git-safety-check.md` supplies pipeline step 16's read-only review procedure. It preserves status/diff/history/test review and requires redaction before printing values; it does not commit or push.
- Required source runtime/plugin/testing/boundary/troubleshooting documents are relocated under that same skill's `references/docs/`. Exact package references are mapped, while target-project outputs under `docs/agentic-sdlc/` remain unchanged. Optional source-only test/eval runners are explicitly unavailable unless a separate source checkout supplies them.
- Owner: the maintainer reviews local preparation evidence and controls external publication. Preparing or verifying an archive does not upload it.

## Listing fields

The public `interface` retains the source listing fields/assets validated by `tests/test_packaging_metadata.py`, while its `longDescription` states procedural guidance and no automatic hook enforcement. Optional `homepage` and `repository` URLs for the private source checkout are omitted from the public manifest; `author` and stable package identity remain unchanged.

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

This public package provides procedural guidance and no lifecycle hook enforcement on any surface. Manual Codex and Claude Code distributions retain their runtime hooks. Codex skips non-managed plugin hooks until the user reviews and trusts their current definitions; installation does not grant trust ([package hooks](https://developers.openai.com/plugins/build/plugins#hooks), checked 2026-10-06).

## Prerequisites

Maintainer-verified identity and Apps Management Write (`api.apps.write`): account
status is unknown in this workspace. The maintainer must verify both in the portal
before submission; local package checks cannot establish them.

## Listing risk

The portal resets `author.name` and `interface.developerName` to defaults when they do not match the verified publisher identity. This is recorded for maintainer review (DP14); no identity data is copied into this packet.

## Naming

- An update whose package name differs from the published plugin fails with `plugin_name_mismatch` ([submission errors](https://developers.openai.com/plugins/deploy/submission-errors)).
- Submitted information and reviewed metadata are locked after publication, and the listing changes only through a newly reviewed version ([app review](https://developers.openai.com/plugins/deploy/app-review)).
- The fixed identity of this plugin is `agentic-sdlc`.

## Other items

- The current submission field reference requires website/support/privacy/terms URLs for MCP review; skills-only metadata validation does not require all four. This plugin has no MCP server; do not invent account or link prerequisites for its skills-only format ([submission reference](https://developers.openai.com/plugins/deploy/submission#listing-metadata), checked 2026-10-06).
- Public source links and a GitHub security-report mechanism remain maintainer distribution decisions for a future public repository. The public ZIP does not advertise the currently private repository URLs.
- Historical ledger row `skills_only_archive` reads PASS at `2a3d6ac` (static gate: `archive_kind=skills-only`, byte-identical rebuild, `verify=passed`); it binds that commit only, so the skills-only archive must be rebuilt and verified at the release commit. Row `portal_normalized_manifest` is BLOCKED because no upload was performed. New local build/verify/native evidence is recorded separately in [current readiness](codex-0.160.1-readiness.md); local verification is not portal acceptance.

## Maintainer-evening items (D24)

These maintainer-evening items happen outside agent execution:

- The public repository is a new, clean repository created together with the maintainer (option C).
- The portal upload is done together with the maintainer. The agent submits nothing.
- The listing and top-level URLs are re-checked against that new repository at that time.

## Validation and provenance

`--verify` reconstructs the same public projection from the archive's recorded source commit, then checks member set, bytes, modes, deterministic rebuild and secrets. A missing role/reference/helper stops preparation; tampering or restored lifecycle files fails verification. Never submit an archive whose verification failed.

An uncommitted preparation run may use an explicitly labelled isolated Git source snapshot, preserving that snapshot for reconstruction. It is not a commit in the development repository. Build both distributions and run native discovery against that same immutable snapshot. A final maintainer release must rebuild from the intended committed revision.

Current native discovery, direct script checks, transcript replay and authenticated installed-hook execution are separate evidence levels. Missing current execution evidence remains an explicit limitation; successful discovery alone does not prove hook effects or skill routing.

The 2026-10-07 public critic component check supplied four packaged instruction bodies through a trusted harness and observed real native delegation on GPT-5.6 Luna/Low. This supports that bounded instruction/delegation path only. The original shell-read case was infrastructure-inconclusive, so no equal-harness improvement or model-side file-read claim is made. A `read-only`/`never` host policy can deny shell-based inspection before execution; phase helpers require approved command execution or a host-supported read/input mechanism. Do not weaken user permissions or hook trust to make a preparation check pass.
