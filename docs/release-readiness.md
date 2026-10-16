# Release Readiness

This file is the publish gate for `agentic-sdlc` version `0.6.0`. It keeps the release decision evidence-based for the supported runtimes: Claude Code and Codex. The current release decision and sanitized observations are in [release evidence](release-evidence-0.6.0.md); preparation or a metadata-only pass cannot replace its required results. The 0.4.3 and 0.5.0 decisions stay unchanged in the [0.4.3 ledger](release-evidence-0.4.3.md) and the [0.5.0 ledger](release-evidence-0.5.0.md).

The 2026-10-06 preparation fixes public hook removal and packaged instruction/helper closure; native Codex 0.160.1 discovery from that date is recorded in [current readiness](publication/codex-0.160.1-readiness.md). The historical ledger below is preserved. New local preparation does not erase historical failed/not-run live evaluations or claim portal acceptance. No upload, publication, commit, push, PR or merge is part of this preparation.

## Current multi-platform preparation

The [2026-10-11 preparation record](publication/marketplace-readiness-2026-10-11.md)
separates committed source, producer projections, official-tool fixtures and
native lifecycle/event evidence from external publisher and review gates.
That record skipped macOS at the maintainer's request; macOS native lifecycle checks
passed on 2026-10-12 ([compatibility matrix](publication/compatibility-matrix.md) E10–E14).
No publication occurred.

Kimi, ZCode and Grok are now included in the installation/portability candidate alongside Claude and Codex. The candidate artifacts, supported channels, update methods, official references and the checks that remain unverified are in [multi-platform distribution](publication/multi-platform-distribution.md). Native install, discovery, update and uninstall results for all five runtimes on Windows, Linux and macOS, bound to main `1a9ac73`, are in the [compatibility matrix](publication/compatibility-matrix.md); they ran no model turn and do not prove hook trust/delivery or live skill behavior. This does not change the historical ledger below or approve publication.

## Supported Release Scope (historical 0.4.3 verdict)

| Runtime | Status | Evidence requirement |
|---|---|---|
| Claude Code | Supported | Local gate plus live routing/procedure transcript evidence before claiming live behavior. |
| Codex | Supported | Local gate plus route-classifier/procedure transcript evidence before claiming live behavior. |
| OpenCode, GLM-style harnesses | Experimental / deferred | Adapter guidance may exist, but these are not release-blocking supported runtimes for `0.4.3`. |
| ZCode (Z.ai) | Experimental adapter; was not a 0.4.3 release target | Adapter files (`.zcode-plugin/plugin.json`, root `marketplace.json`, `hooks/hooks-zcode.json`) support marketplace installs from the root `marketplace.json` as a file source; a directory or GitHub-repository source is read through `.claude-plugin/marketplace.json` first and shows the Claude entry, and a GitHub source uses the public repository and is not natively verified (experimental; no official submission). Native lifecycle passed on Windows, Linux and macOS with the desktop bundle's agent CLI, not the GUI ([compatibility matrix](publication/compatibility-matrix.md) E9, E15, E14). ZCode stays outside the supported scope above regardless of install evidence. |
| Grok CLI | Experimental adapter; was not a 0.4.3 release target | Adapter files (`.grok-plugin/plugin.json`, `.grok-plugin/marketplace.json`, `hooks/hooks-grok.json`) support local-directory installs and Git-catalog installs (the catalog names this public repository as a remote `url` source; not natively verified). Native lifecycle of a local install passed on Windows, Linux and macOS ([compatibility matrix](publication/compatibility-matrix.md) E3, E8, E13); the Git-catalog update was exercised only against an offline Git fixture in the 2026-10-11 preparation record. Grok stays outside the supported scope above regardless of install evidence. `grok plugin validate .` green on the Claude layout is not Grok-native publish. |
| Kimi Code | Experimental adapter; was not a 0.4.3 release target | Adapter files (`.kimi-plugin/plugin.json`, root `marketplace-kimi.json`) support local-directory installs, GitHub URL installs from the public repository (not natively verified) and the custom catalog. Native lifecycle of a local install passed on Windows, Linux and macOS through the `kimi web` API, not the TUI ([compatibility matrix](publication/compatibility-matrix.md) E4, E7, E12); the Enter-update path is not natively verified. Kimi Code stays outside the supported scope above regardless of install evidence. |

## Distribution paths and go/no-go

The four distribution paths below each get their own go/no-go decision; the same labels are used in [`README.md`](../README.md) and both runtime READMEs. Each verdict stays no-go, pending maintainer review, until a recorded maintainer review of that path is linked in the ledger's [path verdicts](release-evidence-0.6.0.md#path-verdicts). The old 45/45 routing results, synthetic replay and marketplace-only validation never close a path.

The experimental ZCode, Grok CLI, and Kimi Code installs (local directory, and repository or catalog sources from the public repository) are not among these four paths and carry no 0.4.3 verdict; their notes live in `docs/publication/zcode-marketplace.md`, `docs/publication/grok-marketplace.md`, and `docs/publication/kimi-marketplace.md`.

### Claude own marketplace

**Prerequisites.** Claude Code with plugin marketplace support, `node` on `PATH`, and read access to `MrBekoX/agentic-sdlc`.

**Steps.** `claude plugin marketplace add MrBekoX/agentic-sdlc`, then `claude plugin install agentic-sdlc@mrbekox`.

**Go condition.** Anonymous users need a public repository: a private repository installs only through a git credential helper or SSH, and a token supplied only in an environment variable does not authenticate the install ([private repositories](https://code.claude.com/docs/en/plugin-marketplaces.md#private-repositories), observed 2026-09-14). `claude plugin validate .claude-plugin/marketplace.json --strict` and `claude plugin validate .claude-plugin/plugin.json --strict` pass as two separate checks. Since Claude Code 2.1.289, `claude plugin validate .` also checks the plugin beside a marketplace manifest ([plugins/publish](https://code.claude.com/docs/en/plugins/publish) and the 2.1.289 changelog, fetched 2026-10-07). Hook-config validity comes from the repository tests. A worktree strict `plugin.json` exit 1 caused by the untracked `CLAUDE.md` is not the clean-package result. The clean install starts from an empty profile: `claude plugin marketplace add MrBekoX/agentic-sdlc`, `claude plugin install agentic-sdlc@mrbekox`, a new session or `/reload-plugins`, then skill, command and hook discovery plus one real invocation, with the clone transport (SSH or HTTPS) recorded.

State: GAP. The repository is public since 2026-10-12, published with a rewritten history ([history map](publication/history-map.md)); its unauthenticated URL returns 200 in `docs/publication/link-checks.json`. From the public repository, `claude plugin marketplace add MrBekoX/agentic-sdlc` and `claude plugin install agentic-sdlc@mrbekox` installed 0.5.0 with 16 skills in an isolated profile (Claude Code 2.1.282, Linux, 2026-10-12, no model call); the go condition's new-session discovery, real invocation and recorded clone transport are not recorded.

Verdict: maintainer review pending -> no-go ([path verdicts](release-evidence-0.6.0.md#path-verdicts)).

### Claude community marketplace submission

**Prerequisites.** A public repository, a recorded clean-package `claude plugin validate ./plugin --strict` result, and a paid claude.ai plan. On Pro and Max the maintainer submits from their own account; on Team and Enterprise an Owner submits, and on Enterprise an Owner can grant the Directory permission ([plugins/publish](https://code.claude.com/docs/en/plugins/publish), fetched 2026-10-07). Submission is at [claude.ai/directory/manage](https://claude.ai/directory/manage). `claude-plugins-official` does not take directory submissions.

**Steps.** Submit the plugin root through [claude.com/docs/plugins/submit](https://claude.com/docs/plugins/submit), using the packet [`publication/claude-community.md`](publication/claude-community.md).

**Go condition.** The repository must be public and `claude plugin validate` must pass on the submitted plugin root. Acceptance is not guaranteed. Observed 2026-09-14: [code.claude.com/docs/en/plugins](https://code.claude.com/docs/en/plugins.md) says approved plugins "are pinned to a specific commit SHA" and that CI bumps the pin automatically as new commits are pushed, and [claude.com/docs/plugins/submit](https://claude.com/docs/plugins/submit) says "updates pushed to your GitHub repo are picked up automatically", so every default-branch push after approval counts as publication. The pages name different target marketplaces, `claude-community` and `claude-plugins-official`; neither placement is promised.

State: BLOCKED. The path needs a public repository, the clean-package validation result and maintainer form access.

Verdict: maintainer review pending -> no-go ([path verdicts](release-evidence-0.6.0.md#path-verdicts)).

### Codex personal marketplace

**Prerequisites.** Codex CLI with plugin marketplace support (the 0.4.3 verdict was recorded on 0.154.0; the 2026-10-12 native lifecycle ran on codex-cli 0.162.1 and 0.156.1), `node` on `PATH`, and a package directory.

**Steps.** Run `codex plugin marketplace add <package-directory>` and `codex plugin add agentic-sdlc@mrbekox` (a personal catalog at `~/.agents/plugins/marketplace.json` with `codex plugin add agentic-sdlc@personal` is an optional alternative), open `/hooks` in Codex and trust each agentic-sdlc hook, then run `python3 scripts/check_codex_hook_trust.py --plugin agentic-sdlc@<marketplace-name>`, which prints `codex_hook_trust=trusted` for a fully trusted install ([Codex hook trust](troubleshooting.md#codex-hook-trust)).

**Go condition.** Install through `codex plugin add agentic-sdlc@<marketplace-name>` from a catalog Codex recognizes (the package's own `mrbekox` catalog or a personal catalog); native discovery showing 16 skills and `hooks/list` showing 8 hooks; and hook trust granted through the native `/hooks` trust protocol as a required step.

State: GAP. Final-package discovery of 16 skills and 8 hooks and real-profile hook trust are not yet recorded for the 0.6.0 package; the ledger carries the 26b0fe1 results.

Verdict: maintainer review pending -> no-go ([path verdicts](release-evidence-0.6.0.md#path-verdicts)).

### OpenAI public directory

**Prerequisites.** Maintainer-verified identity and Apps Management Write (`api.apps.write`).

**Steps.** Build the BR24 skills-only archive with `python3 scripts/build_release.py --output <zip> --skills-only`, verify it with `python3 scripts/build_release.py --verify <zip>`, then upload it through the OpenAI portal, using the packet [`publication/openai-skills-only.md`](publication/openai-skills-only.md).

**Go condition.** The skills-only archive verifies as `archive_kind=skills-only`, the maintainer identity and `api.apps.write` are verified, and submission, acceptance and publication are treated as three separate stages. After publication, the listing changes only through a newly reviewed version ([app review](https://developers.openai.com/plugins/deploy/app-review)).

State: BLOCKED. The path needs the verified identity, `api.apps.write` and a verified skills-only archive.

Verdict: maintainer review pending -> no-go ([path verdicts](release-evidence-0.6.0.md#path-verdicts)).

## Required Local Gate

Run these commands from the repository root before publishing or tagging:

```bash
python3 scripts/bump_version.py --check
python3 scripts/bump_version.py --release-check
python3 scripts/check_all.py
python3 tests/skills/harness.py
python3 -m unittest discover -s tests -v
```

Use the repository's `python3` entry point on both platforms and verify it resolves to the intended Python installation. CI uses `actions/setup-python`; its [Windows installer](https://github.com/actions/python-versions/blob/main/installers/win-setup-template.ps1) supplies the python3 executable link.

The local gate proves metadata consistency, Codex manifest shape, static skill wiring, fixture health, hook/workflow syntax, flow-evidence config wiring, and unit behavior. It does not prove live model routing or live tool-use obedience.

## Required Live Evidence

Do not claim that a skill "works", "triggers", or is "production-ready" in a runtime unless at least one current transcript or eval summary exists for that claim.

The model baseline for the 0.4.3 release batch is `gpt-5.5` / Low for Codex (a new baseline) and `claude-sonnet-5` / Low for Claude. Earlier `gpt-5.3-codex-spark` / Low results are historical and separate; they are not comparable to the new Codex baseline.

The live batch follows the BR11 settings: fifteen standalone routing scenarios with `--runs 3 --threshold 1.0` per runtime, where every case needs three correct observations, no hard error and no prohibited pipeline escalation; Claude `--max-budget-usd 1.50` per routing run; both procedure cases per runtime, at most $6 per Claude case; and no automatic retry. The first procedure case explicitly requests smoke depth, while the second requests the normal per-package layout.

| Claim | Command shape | Passing signal |
|---|---|---|
| `using-agentic-sdlc` routes standalone prompts in Claude Code | `python3 scripts/run_routing_eval.py --eval-set tests/skills/routing/using-agentic-sdlc.json --runtime claude --model claude-sonnet-5 --runs 3 --threshold 1.0 --max-budget-usd 1.50 ...` (non-persistent live Skill routing with `--plugin-dir`) | `routing_eval=passed`, 15/15 scenarios and 45/45 observations; inspect actual selected Skill/Read delivery. |
| `using-agentic-sdlc` routes standalone prompts in Codex | `python3 scripts/run_routing_eval.py --eval-set tests/skills/routing/using-agentic-sdlc.json --runtime codex --model gpt-5.5 --reasoning-effort low --runs 3 --threshold 1.0 ...` | `routing_eval=passed`, 15/15 scenarios and 45/45 observations; this is a description classifier, not native skill activation. |
| `agentic-sdlc-pipeline` procedure in Claude Code and Codex | A native installed-package `claude -p` or `codex exec` run whose command equals its approved entry, graded by `python3 scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --case-id <id> --transcript <capture> --fixture-root <fixture> --strict-evidence --evidence-dir <dir>` | Strict `procedure_eval=passed` for both procedure cases (2/2) on that runtime. Output of the eval's `--live` harness mode (which requires `--allow-fixture-commit`) is not scored as a procedure row. |
| `agentic-sdlc-pipeline` Codex adapter transcript replay | `python3 scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --transcript tests/fixtures/transcripts/agentic-sdlc-pipeline-procedure-codex-adapter-pass.jsonl` | `procedure_eval=passed`; labeled deterministic replay, and it never sets `codex_pipeline_procedure`. |

Procedure runs never use these BR12 forbidden flags. Codex: `--ephemeral`, `--dangerously-bypass-hook-trust`, `--dangerously-bypass-approvals-and-sandbox`, `--ignore-user-config` and `--ignore-rules`. Claude: `--no-session-persistence` and `--dangerously-skip-permissions`. Routing runs keep the runners' documented shapes, and neither routing type counts as trust, persistence or hook evidence.

These are runner command shapes, not automatic authorization to run a large batch. Review exact commands, snapshots and limits before execution. For Claude, set `CLAUDE_CODE_EFFORT_LEVEL=low` and pin `CLAUDE_CODE_SUBAGENT_MODEL` plus `ANTHROPIC_DEFAULT_HAIKU_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` and `ANTHROPIC_DEFAULT_OPUS_MODEL` to `claude-sonnet-5` in the isolated child environment. The routing runner's `--reasoning-effort` argument configures Codex; it does not itself configure Claude. Inspect every returned assistant model and modelUsage entry rather than assuming the requested main model constrains helpers. Claude response-side effective effort may be absent; record Low configuration without inventing telemetry.

Keep native auth in its existing store, use isolated fixtures and reviewed source, and preserve terminal process state. The standard procedure runner creates a scratch fixture baseline commit and cleans temporary outputs; a release capture must explicitly authorize that harness setup and preserve its artifacts before cleanup. No model or project commit/push/merge is permitted by these fixture cases. Generate the review viewer before grading, retain failures and do not retry a still-running process after an observation timeout.

If a live Claude Code run is denied a required branch/tool action, record the actual permission failure and missing procedure step. Correct an isolated fixture's permissions only within the reviewed scope; a trust bypass or swallowed denial cannot prove the normal installed behavior.

This release follows the maintainer's Low-effort constraint. Label every result with exact model, effort, date, runtime and payload identity; three observations improve the measured sample but do not establish high-effort or universal stability. The current CLI versions observed during remediation were Codex **0.154.0** and Claude Code **2.1.269**; record fresh versions for each release batch.

## Captured evidence — 2026-06-18/19 live sweep

These are historical observations, with detailed transcripts under `tests/artifacts/` (gitignored)
and a writeup in [`docs/testing.md`](testing.md#live-eval-findings-2026-06-18--haiku--sonnet-sweep).
The earlier Haiku/Sonnet/high-effort comparison is not a current release verdict. Follow the exact
models and three-observation requirement above for 0.4.3; do not relabel these old outcomes as new runs.

| Evidence | Result | Notes |
|---|---|---|
| `using-agentic-sdlc` routing — Claude | Sonnet 6/6 (router eval-set reworked); Haiku floor at `runs=3` (q13 0.60) | router trigger eval measures the router's own surface; child-routing is the routing eval |
| `using-agentic-sdlc` routing — Codex `high` | **15/15 passed** (`gpt-5.3-codex-spark`, `runs=3`) | satisfies the Codex routing evidence requirement |
| 16-skill trigger matrix — Codex | **16/16 passed** (`low`, after classifier-prompt fix) | `low` is fix-verification; re-confirm at `high` for publish. Pre-fix 12/16 was an eval-tool gap (trigger classifier prompt lacked the over-escalation/feeder guards the routing classifier has), now aligned |
| `agentic-sdlc-pipeline` procedure — Claude | Sonnet 2/2 at `--max-budget-usd 6`; Haiku 1/3 (floor) | `$2` default cut strong-model runs off mid-run → default raised to `5.00` |
| `agentic-sdlc-pipeline` procedure — Codex adapter | **`procedure_eval=passed`** (deterministic transcript) + historical `0.3.0` live low-effort strict smoke pass | adapter patterns present: `spec-plan-author/critic`, "Workflow unavailable/embedded adapter", `docs/agentic-sdlc/specs/`, `docs/agentic-sdlc/plans/`, all gates. The 2026-06-20 `gpt-5.3-codex-spark` run proves the `0.3.0` adapter path only; it is not live proof for `0.4.3` |

Eval-infra fixes made during the sweep (all on `main`): routing-eval early-stop + `runs=3` default;
implementation-control/router call-order guards; `safe-refactor`/`skill-authoring`/`completion-claim-gate`
activation guards; procedure-eval `--max-budget-usd` default `2.00 → 5.00`; Codex trigger classifier
prompt aligned with the routing classifier.

## Historical evidence — 2026-06-20 Codex 0.3.0 live low smoke

Sanitized summary: [`docs/agentic-sdlc/evidence/codex-live-low-strict-2026-06-20.md`](agentic-sdlc/evidence/codex-live-low-strict-2026-06-20.md).
Raw transcript/final report are local generated artifacts under `tests/artifacts/codex-procedure/` and are intentionally gitignored.
Fixture: `<temp-fixture-root>` (isolated copy of `tests/fixtures/agentic-sdlc-pipeline-basic`).

Run shape:

```powershell
codex -a never exec --json --ephemeral --dangerously-bypass-hook-trust -s workspace-write -m gpt-5.3-codex-spark -c 'model_reasoning_effort="low"' -c 'model_verbosity="low"' -C <fixture> -o <last-report> -
```

Passing signals observed in the transcript:

- plugin cache refreshed to `agentic-sdlc@personal` version `0.3.0` before the run;
- pipeline used the Codex embedded author -> critic -> revise adapter and wrote canonical artifacts under `docs/agentic-sdlc/specs/` and `docs/agentic-sdlc/plans/`;
- `validate_artifacts.py --mode spec` passed;
- `validate_artifacts.py --mode plan --strict` passed with `plan_ac_covered=4`, `plan_tasks=2`;
- `resolve_work_package.py` initially caught artifact metadata/path issues, the run fixed them, and the rerun passed with `work_package_resolution=passed`;
- RED phase was captured before implementation: `python -m pytest -q test_greeting.py` -> `2 failed, 1 passed`;
- GREEN phase passed after implementation: `python -m pytest -q test_greeting.py` -> `3 passed in 0.01s`;
- final focused recheck outside the Codex run also passed: `py -3 -m pytest -q test_greeting.py` -> `3 passed, 2 warnings`;
- final report included `Overall Status: PASS` for Implementation Control and the final todo list was complete.

Limit of this evidence: this is a historical Codex `0.3.0` low-effort smoke/procedure run, not a
publish-grade high-effort stability run and not live evidence for the current `0.6.0` worktree. It is
valid only as evidence that the earlier adapter completed the full pipeline in a small fixture,
including RED->GREEN, artifact validation, work-package resolution, and recovery from metadata errors.

## Secret and Local Path Check

Before any release commit or publish action:

```bash
git status --short --branch
git diff --stat
git diff
git diff --cached
```

Scan staged and unstaged diffs for tokens, private keys, connection strings, and machine-specific absolute paths. If a secret is found, mask it in reports as `***MASKED***` and do not publish until rotated and removed.

## Known Limitations

- Live routing is model-dependent and can vary by runtime, model, plugin list, and prompt shape. Treat live eval output as evidence for that exact run, not a permanent guarantee.
- Claude Code has native `Skill`, `Workflow`, and `Agent` transcript events. Codex uses activated skill instructions and equivalent transcript/procedure evidence; it does not emit the same Claude-native workflow events.
- Codex wires native blocking `PreToolUse` guards, `SessionStart`, and two `Stop` continuation backstops. Coverage is bounded: branch/flow hardening is env-gated, unrecognized write forms fail open, and Stop can request another turn but cannot undo prior effects.
- `agentic-sdlc-pipeline` owns internal spec/plan phases. It must not call standalone `spec-authoring` or `plan-authoring` for pipeline steps 4-5; Codex uses the embedded author/critic adapter.
- Hooks are local runtime guardrails. Some warn or fail open by design, so they complement but do not replace diff review, test output, and secret scanning.
- `0.6.0` is publishable for Claude Code and Codex only when the local gate and current release evidence are attached. Other runtimes should be described as experimental adapter targets, not supported release targets.
- Codex public-listing fields now use `interface.category: "Developer Tools"` and a `shortDescription` of at most 30 characters.
- Current bounded hook/lifecycle captures exist for Codex **0.154.0** and Claude Code **2.1.269**. They retain their own immutable source identities; current parser replay and later skill evaluations are separate evidence. `transcript_path` remains unstable. See [runtime boundaries](runtime-adapter.md#current-binary-and-historical-hook-evidence) and the [0.4.3 release ledger](release-evidence-0.4.3.md).

## Auxiliary .skill Archives

`.skill` archives are an auxiliary artifact. They are not a fifth distribution path and not a go/no-go gate (BR5); the release decision uses only the four paths in [Distribution paths and go/no-go](#distribution-paths-and-gono-go).

These skills depend on companion plugin resources, so they are not offered as universal standalone `.skill` packages. A skill counts when any `.md`, `.py` or `.json` file under `skills/<skill>/` references `<runtime-root>/scripts`, `/contracts` or `/hooks`, or the same paths under `${PLUGIN_ROOT}` or `${CLAUDE_PLUGIN_ROOT}`:

- `agentic-sdlc-pipeline`: `SKILL.md` and `playbook.md` run plugin scripts and read plugin contracts.
- `dispatch-strategy`: the **Plugin root** rule in `SKILL.md` confirms `<runtime-root>/scripts/validate_artifacts.py` before any helper command.
- `implementation-control`: `SKILL.md` runs a plugin script.
- `plan-authoring`: `SKILL.md` reads plugin contracts and runs the plan validator script.
- `skill-authoring`: `references/house-notes.md` points at `<runtime-root>/scripts`, and `SKILL.md` states that the runtime eval runners require companion plugin resources.
- `spec-authoring`: `SKILL.md` reads plugin contracts and runs the spec validator script.
- `using-agentic-sdlc`: the **Plugin root** rule in `SKILL.md` confirms `<runtime-root>/scripts/validate_artifacts.py` and resolves `contracts/skills/`, `scripts/` and `hooks/` through that root.

`mind-spark` is not in this list: its only plugin path, `skills/mind-spark/SKILL.md` under the installed folder (`${CLAUDE_PLUGIN_ROOT}/skills/mind-spark/SKILL.md` in Claude Code), is a catalog-fallback path, not a companion resource. The same holds for the `<runtime-root>/skills/<skill>/SKILL.md` fallback in `using-agentic-sdlc`, which counts only through its **Plugin root** rule.

The skill-creator toolkit is BLOCKED until reviewed. `skills/skill-authoring/scripts/resolve_skill_creator.py` reports `skill_creator_status=missing_capabilities` for the WSL toolkit and `explicit-unverified` for the Windows cache. No archive is produced from an unreviewed toolkit, and a reviewed toolkit commit is recorded only as a full 40-hex commit together with its ledger row.

The per-archive identity record is the `skill_archives` row in [release evidence](release-evidence-0.6.0.md) (AC127).

## Artifact Layouts And Per-Package Evidence

Work-package artifacts resolve in two layouts: the legacy flat `docs/agentic-sdlc/{specs,plans}/<id>.md` (back-compat, unchanged) and the per-package canonical `docs/agentic-sdlc/<slug>/{spec,plan,evidence}/<work_id>.md`, where `<slug>` is lowercase kebab-case `^[a-z0-9][a-z0-9-]{0,63}$` and never a reserved name (`specs`, `plans`, `evidence`, `notes`, `spec`, `plan`). This is distinct from the legacy `docs/agentic-sdlc/evidence/` directory (no slug segment) referenced above, which is outside the per-package evidence gate.

Per-package evidence persists to `docs/agentic-sdlc/<slug>/evidence/<work_id>.md` — per-package only (flat packages get no Finalize evidence), overwritten in place per run (single canonical file, last run wins), git-ignored, and with no validator (it never gates resolution). That evidence write is performed by the main pipeline finalize step, not the read-only `implementation-auditor` sub-agent.

Per-package plan change-detection runs as a filesystem scan, not a `git status` query: new generated plans can be git-ignored, so the resolver scans the filesystem; published plugin documentation is tracked separately.

## Release Verdict Template

Use this shape in a release note or final publish report. Its keys, allowed values and row bindings are governed by the decision block in the [release ledger](release-evidence-0.6.0.md#publication-decision) (AC116):

```text
version=0.6.0
scope=Claude Code, Codex
local_gate=<passed|failed|blocked|not-run>
claude_routing_eval=<passed|failed|blocked|not-run>
codex_routing_eval=<passed|failed|blocked|not-run>
claude_pipeline_procedure=<passed|failed|blocked|not-run>
codex_pipeline_procedure=<passed|failed|blocked|not-run>
secret_scan=<passed|failed|blocked|not-run>
known_limitations_acknowledged=<yes|no>
verdict=<publish|do-not-publish>
```

Evidence references, such as dates, transcripts, logs and scan methods, belong in the ledger's bound rows, not in this block.
