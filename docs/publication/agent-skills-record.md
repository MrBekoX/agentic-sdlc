# Agent Skills alignment record

| Field | Value |
|---|---|
| Date | 2026-09-15 |
| Git commit | `882180859c6306cdc1bef1382a965a466554b1ae` plus the uncommitted slice F documentation edits (skill routing frontmatter unchanged) |
| Reviewer | Agent under the maintainer's delegated authority |

Commands run on that tree, with exit codes:

| Command | Exit | Result |
|---|---|---|
| `python3 scripts/check_all.py` | 1 | `skills_checked=16`; the frontmatter checks passed. The only unittest failure is `test_release_distribution.TestRealTreeVerify.test_real_head_release_archive_verifies_and_lists_suppressions`, a declared known-RED test that builds from HEAD and turns green after the slice commit (`Ran 1105 tests`, `FAILED (failures=1, skipped=2)`). |
| `python3 tests/skills/harness.py` | 0 | `skills_checked=16`, `skills_eval=passed` |
| `PYTHONPATH=tests python3 -m unittest test_skill_structure test_shared_skill_contract -v` | 0 | `Ran 15 tests`, `OK` |

## Official fields vs house rules

The [Agent Skills specification](https://agentskills.io/specification) (observed 2026-09-14) defines six frontmatter fields: `name`, `description`, `license`, `allowed-tools`, `metadata` and `compatibility`. The official length limits are 64 characters for `name` and 1024 characters for `description`.

House-only rules, which are not part of the specification:

- the description is written in the third person, as when to use the skill; the gate enforces this only by rejecting a leading `Use` imperative;
- the description contains no angle brackets;
- the directory name is kebab-case and equals `name`.

`scripts/check_all.py` is a regex-based frontmatter checker, not a full YAML parser or specification validator. This package adds no frontmatter key, no frontmatter parser and no dependency.

## Per-skill record

Lengths come from the parsed frontmatter values, with quotes stripped. Support files come from `git ls-files skills/<name>`, excluding `SKILL.md`. Each description-meaning review is one sentence by the reviewer above on 2026-09-15; it is a recorded reading of the text, not a live trigger measurement.

| Skill | Name equals directory | Name length / 64 | Description length / 1024 | Frontmatter keys used | Support files | Description meaning (reviewed 2026-09-15) |
|---|---|---|---|---|---|---|
| `agentic-sdlc-pipeline` | yes | 21 / 64 | 334 / 1024 | `name`, `description` | `playbook.md`, `templates.md` | Triggers on end-to-end implementation that needs the full gated envelope, and on production, API contract, auth, payment or database work. |
| `code-quality-review` | yes | 19 / 64 | 419 / 1024 | `name`, `description` | none | Triggers on a fresh code-quality review of a diff, file or PR, not on security review or feedback on the user's own change. |
| `completion-claim-gate` | yes | 21 / 64 | 391 / 1024 | `name`, `description` | none | Triggers immediately before the agent claims work is done, fixed, passing, ready or verified. |
| `dispatch-strategy` | yes | 17 / 64 | 376 / 1024 | `name`, `description` | none | Triggers when choosing between the main loop, a sub-agent, a dynamic workflow or an agent team for multi-part work. |
| `feature-build` | yes | 13 / 64 | 258 / 1024 | `name`, `description` | none | Triggers on adding a feature, endpoint, screen or capability without the full pipeline envelope. |
| `feedback-triage` | yes | 15 / 64 | 316 / 1024 | `name`, `description` | none | Triggers when review, bot or CI feedback on the user's own change must be verified, judged or applied. |
| `implementation-control` | yes | 22 / 64 | 610 / 1024 | `name`, `description` | none | Triggers on a pre-final audit that the implementation followed spec, plan, TDD, tests, security and scoped-diff steps. |
| `mind-spark` | yes | 10 / 64 | 449 / 1024 | `name`, `description` | `references/design-process.md` | Triggers on exploring ambiguous build or design intent before requirements are agreed, in an AGENTIC-SDLC-owned phase. |
| `plan-authoring` | yes | 14 / 64 | 426 / 1024 | `name`, `description` | none | Triggers on a request for only an implementation plan, task breakdown or verification points without code. |
| `root-cause-fix` | yes | 14 / 64 | 244 / 1024 | `name`, `description` | none | Triggers on fixing a bug, failing test, regression or incident at its root cause. |
| `safe-refactor` | yes | 13 / 64 | 434 / 1024 | `name`, `description` | none | Triggers on restructuring, cleanup or duplication removal that must not change behavior. |
| `security-audit` | yes | 14 / 64 | 299 / 1024 | `name`, `description` | none | Triggers on a security audit of code, a diff, an endpoint or a login flow. |
| `skill-authoring` | yes | 15 / 64 | 382 / 1024 | `name`, `description` | `references/house-notes.md`, `references/house-voice.md`, `scripts/resolve_skill_creator.py` | Triggers on creating, editing, evaluating, optimizing or packaging a Claude or Codex skill. |
| `spec-authoring` | yes | 14 / 64 | 279 / 1024 | `name`, `description` | none | Triggers on a request for only a spec, acceptance criteria or a WHAT document. |
| `test-authoring` | yes | 14 / 64 | 358 / 1024 | `name`, `description` | none | Triggers on test-only work: writing, repairing or designing tests without changing production behavior. |
| `using-agentic-sdlc` | yes | 18 / 64 | 375 / 1024 | `name`, `description` | none | Triggers on explicit routing questions about which AGENTIC-SDLC skill owns the work, and escalates only full SDLC work to the pipeline. |
