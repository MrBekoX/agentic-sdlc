# Release Readiness

This file is the publish gate for `agentic-sdlc` version `0.4.3`. It keeps the release decision evidence-based for the supported runtimes: Claude Code and Codex. The current release decision and sanitized observations are in [release evidence](release-evidence-0.4.3.md); preparation or a metadata-only pass cannot replace its required results.

## Supported Release Scope

| Runtime | Status | Evidence requirement |
|---|---|---|
| Claude Code | Supported | Local gate plus live routing/procedure transcript evidence before claiming live behavior. |
| Codex | Supported | Local gate plus route-classifier/procedure transcript evidence before claiming live behavior. |
| OpenCode, Kimi Code, GLM-style harnesses | Experimental / deferred | Adapter guidance may exist, but these are not release-blocking supported runtimes for `0.4.3`. |

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

Minimum publish evidence for this release uses the requested `gpt-5.3-codex-spark` / Low and `claude-sonnet-5` / Low settings. Cover all fifteen standalone scenarios with `--runs 3 --threshold 1.0`: every case needs three correct observations, no hard error and no prohibited pipeline escalation. Preserve both procedure cases; the first explicitly requests smoke depth, while the second requests the normal per-package layout.

| Claim | Command shape | Passing signal |
|---|---|---|
| `using-agentic-sdlc` routes standalone prompts in Claude Code | `python3 scripts/run_routing_eval.py --eval-set tests/skills/routing/using-agentic-sdlc.json --runtime claude --model claude-sonnet-5 --runs 3 --threshold 1.0 --max-budget-usd 1.50 ...` | `routing_eval=passed`, 15/15 scenarios and 45/45 observations; inspect actual selected Skill/Read delivery. |
| `using-agentic-sdlc` routes standalone prompts in Codex | `python3 scripts/run_routing_eval.py --eval-set tests/skills/routing/using-agentic-sdlc.json --runtime codex --model gpt-5.3-codex-spark --reasoning-effort low --runs 3 --threshold 1.0 ...` | `routing_eval=passed`, 15/15 scenarios and 45/45 observations; this is a description classifier, not native skill activation. |
| `agentic-sdlc-pipeline` invokes the required phase skills/tools in Claude Code | `python3 scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --live --model claude-sonnet-5 --max-budget-usd 6 ...` | `procedure_eval=passed` for both procedure cases, with persisted fixture and transcript evidence. |
| `agentic-sdlc-pipeline` Codex adapter transcript satisfies procedure gates | `python3 scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --transcript tests/fixtures/transcripts/agentic-sdlc-pipeline-procedure-codex-adapter-pass.jsonl` | `procedure_eval=passed`. |

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
publish-grade high-effort stability run and not live evidence for the current `0.4.3` worktree. It is
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
- `0.4.3` is publishable for Claude Code and Codex only when the local gate and current release evidence are attached. Other runtimes should be described as experimental adapter targets, not supported release targets.
- Codex public-listing fields now use `interface.category: "Developer Tools"` and a `shortDescription` of at most 30 characters.
- Current bounded hook/lifecycle captures exist for Codex **0.154.0** and Claude Code **2.1.269**. They retain their own immutable source identities; current parser replay and later skill evaluations are separate evidence. `transcript_path` remains unstable. See [runtime boundaries](runtime-adapter.md#current-binary-and-historical-hook-evidence) and the [public release ledger](release-evidence-0.4.3.md).

## Artifact Layouts And Per-Package Evidence

Work-package artifacts resolve in two layouts: the legacy flat `docs/agentic-sdlc/{specs,plans}/<id>.md` (back-compat, unchanged) and the per-package canonical `docs/agentic-sdlc/<slug>/{spec,plan,evidence}/<work_id>.md`, where `<slug>` is lowercase kebab-case `^[a-z0-9][a-z0-9-]{0,63}$` and never a reserved name (`specs`, `plans`, `evidence`, `notes`, `spec`, `plan`). This is distinct from the legacy `docs/agentic-sdlc/evidence/` directory (no slug segment) referenced above, which is outside the per-package evidence gate.

Per-package evidence persists to `docs/agentic-sdlc/<slug>/evidence/<work_id>.md` — per-package only (flat packages get no evidence), overwritten in place per run (single canonical file, last run wins), git-ignored, and with no validator (it never gates resolution). That evidence write is performed by the main pipeline finalize step, not the read-only `implementation-auditor` sub-agent.

Per-package plan change-detection runs as a filesystem scan, not a `git status` query: new generated plans can be git-ignored, so the resolver scans the filesystem; published plugin documentation is tracked separately.

## Release Verdict Template

Use this shape in a release note or final publish report:

```text
version=0.4.3
scope=Claude Code, Codex
local_gate=<passed|failed> <date>
claude_routing_eval=<passed|failed|not-run> <transcript-or-log>
codex_routing_eval=<passed|failed|not-run> <transcript-or-log>
claude_pipeline_procedure=<passed|failed|not-run> <transcript-or-log>
codex_pipeline_procedure=<passed|failed|not-run> <transcript-or-log>
secret_scan=<clean|blocked> <method>
known_limitations_acknowledged=<yes|no>
verdict=<publish|do-not-publish>
```
