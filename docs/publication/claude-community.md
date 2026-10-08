# Claude community submission packet

This packet prepares an `agentic-sdlc` submission to the Anthropic plugin directory. It is a ready-to-submit preparation record only: nothing has been submitted, and submission never implies acceptance. State values are GAP, BLOCKED, not-run, "not needed" or "facts listed, Anthropic decision"; no clause is labeled compliant or violating.

## Listing

| Field | Value |
|---|---|
| Plugin name | `agentic-sdlc` |
| Display name | `Agentic SDLC` (copied from `.claude-plugin/plugin.json`) |
| Description | "Claude Code skill library for gated spec, plan, TDD, security, and review workflows" (copied from `.claude-plugin/plugin.json`) |
| Product description | A local development plugin for Claude Code and Codex that packages repeatable software-delivery procedure as skills, hooks, contracts, scripts, agents and workflows: a router picks the smallest sufficient skill, and a gated pipeline covers end-to-end or high-risk work. |
| Support channel | Repository issues on `MrBekoX/agentic-sdlc`, plus the reporting path in `SECURITY.md`. Both are GAP while the repository is private: its unauthenticated URL returns 404 in `docs/publication/link-checks.json`. |
| Source and package identity | Plugin `agentic-sdlc`, marketplace `mrbekox`, install id `agentic-sdlc@mrbekox`. The release commit and archive hash are bound to the ledger rows `archive_verify` and `clean_package_native_validation` in [`../release-evidence-0.4.3.md`](../release-evidence-0.4.3.md); both are not-run. |
| Evidence links | Ledger rows `clean_package_native_validation`, `archive_verify`, `archive_reproducibility`, `claude_routing_eval`, `claude_pipeline_procedure`, `security_report_mechanism`, `submission_cases_group` and `path_verdicts`. |

## Policy checklist

Sources: the [Anthropic Software Directory Policy](https://support.claude.com/en/articles/13145358-anthropic-software-directory-policy) and the [Anthropic Software Directory Terms](https://support.claude.com/en/articles/13145338-anthropic-software-directory-terms), both observed 2026-09-14. The requirement column names each clause; the linked pages hold the authoritative text.

| Clause | Requirement | State | Evidence |
|---|---|---|---|
| 1.D | Directory Policy clause 1.D | facts listed, Anthropic decision | The plugin runs locally inside Claude Code; hooks read session transcripts, Git state and working-tree bytes on the user's machine (see Hook data access facts below). |
| 1.F | Directory Policy clause 1.F | facts listed, Anthropic decision | Hook behavior, trust needs and bounded coverage are documented in `docs/runtime-adapter.md` and `hooks/README.md`. |
| 3.A | Directory Policy clause 3.A (privacy and data handling disclosure) | GAP | Decision DP10: link `docs/data-handling.md` once it is reachable. It is linked only through a URL whose `docs/publication/link-checks.json` entry records `http_status` 200 with `auth` `none`; no such entry exists today. |
| 3.B | Directory Policy clause 3.B (verified contact) | GAP | No verified public contact yet; the repository URL returns 404 unauthenticated. |
| 3.D | Directory Policy clause 3.D (test account) | not needed | No test account is needed: the plugin operates locally and calls no hosted service of its own. |
| 3.E | Directory Policy clause 3.E (usage examples) | GAP | The 5 positive cases are in `tests/skills/submission/cases.json`; their live runs are not-run (AC84). |
| Directory Terms security-report mechanism | A mechanism for reporting security vulnerabilities | GAP | The GitHub private vulnerability reporting API returns 404 while the repository is private. `LICENSE` (MIT) and `SECURITY.md` are unchanged since 5801cb9. |

## Hook data access facts

- The Stop hooks read the session transcript named by `transcript_path` (exercised by `tests/test_flow_guards.py` `TestFlowStepGuard` and `tests/test_codex_completion_claim_guard.py` `TestGuardBehavior`).
- The SessionStart hooks add the plugin bootstrap context through `additionalContext` (asserted by `tests/test_hooks_policy.py` `TestSessionStartHook` and `TestCodexSessionStartHook`). The Git status summary they include is read by running `git` in `hooks/session-start.mjs` and `hooks/session-start-codex.mjs` (code-cited).
- `worktree-scan` keeps a per-session deduplication state file holding finding keys only (`tests/test_effect_layer_guards.py` `TestWorktreeScan.test_does_not_repeat_the_same_finding_in_one_session`, which points the state at a temporary path). Its default location, `<os tmpdir>/agentic-sdlc/worktree-scan-<session>.json`, is code-cited from `hooks/worktree-scan.mjs:126`, not asserted by a test.
- The full inventory of what hooks and eval helpers read, write and mask is in `docs/data-handling.md` (by repository path).

## How to disable hooks

Run `/plugin`, open the Installed tab, and disable or uninstall `agentic-sdlc`, or run `/plugin disable` ([discover plugins](https://code.claude.com/docs/en/discover-plugins), observed 2026-09-14).

## Top-level URLs (DP24)

`.claude-plugin/plugin.json` keeps its top-level `homepage`, `repository` and `author.url` fields. `homepage` and `repository` point at the repository URL, whose `docs/publication/link-checks.json` entry records 404, so both are GAP until that entry shows 200. `author.url` has a recorded 200 entry.

## Current submission route

Fetched 2026-10-07 from [plugins/publish](https://code.claude.com/docs/en/plugins/publish): Anthropic's directory is browsed at claude.ai/directory. Submitting needs a paid claude.ai plan. On Pro and Max the maintainer submits from their own account; on Team and Enterprise an Owner submits, and on Enterprise an Owner can grant the Directory permission. Validate with `claude plugin validate ./plugin --strict`, then submit at [claude.ai/directory/manage](https://claude.ai/directory/manage). `claude-plugins-official` does not take directory submissions. This is not a live test on 2.1.293.

## Form access

Recorded 2026-09-14, before the developer-portal route above:

- The claude.ai submission form needs a Team/Enterprise plan with directory management; the unauthenticated page returned 403.
- The Console submission form needs a Developer/Admin/Owner role. Only its login page was seen, so its fields are unverified.

## Naming rules

- The `anthropics/claude-plugins-official` README describes the `name` slug as immutable, with a `renames` map for moved entries.
- A `renames` map is observed in `claude-community`, with no explicit immutability statement.
- The fixed identity of this plugin is `agentic-sdlc`.

## Target marketplace discrepancy

Recorded 2026-09-14: the code.claude.com community-marketplace documentation names `claude-community` as the target, while the claude.com submit page names `claude-plugins-official`. Neither placement is promised.

## Maintainer-evening items (D24)

These maintainer-evening items happen outside agent execution:

- The public repository is a new, clean repository created together with the maintainer (option C); this private repository does not change visibility.
- The form submission is done together with the maintainer. The agent submits nothing.
- The listing URLs and the top-level `homepage`, `repository` and `author.url` values are re-checked against that new repository at that time.

## Submission state

Ready to submit is not the same as submitted, accepted or published. The Claude community marketplace path stays BLOCKED, and its verdict stays maintainer review pending -> no-go in the ledger's path verdicts.
