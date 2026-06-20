# Release Readiness

This file is the publish gate for `agentic-sdlc` version `0.3.0`. It keeps the release decision evidence-based for the supported runtimes: Claude Code and Codex.

## Supported Release Scope

| Runtime | Status | Evidence requirement |
|---|---|---|
| Claude Code | Supported | Local gate plus live routing/procedure transcript evidence before claiming live behavior. |
| Codex | Supported | Local gate plus route-classifier/procedure transcript evidence before claiming live behavior. |
| OpenCode, Kimi Code, GLM-style harnesses | Experimental / deferred | Adapter guidance may exist, but these are not release-blocking supported runtimes for `0.3.0`. |

## Required Local Gate

Run these commands from the repository root before publishing or tagging:

```bash
python3 scripts/bump_version.py --check
python3 scripts/check_all.py
python3 tests/skills/harness.py
python3 -m unittest discover -s tests -v
```

On Windows, `py -3` is an acceptable local substitute for `python3` when `python3` is not on `PATH`.

The local gate proves metadata consistency, Codex manifest shape, static skill wiring, fixture health, hook/workflow syntax, and unit behavior. It does not prove live model routing or live tool-use obedience.

## Required Live Evidence

Do not claim that a skill "works", "triggers", or is "production-ready" in a runtime unless at least one current transcript or eval summary exists for that claim.

Minimum publish evidence for this release:

| Claim | Command shape | Passing signal |
|---|---|---|
| `using-agentic-sdlc` routes standalone prompts in Claude Code | `python3 scripts/run_routing_eval.py --eval-set tests/skills/routing/using-agentic-sdlc.json --runtime claude --model haiku ...` | `routing_eval=passed`, all scenarios passed. |
| `using-agentic-sdlc` routes standalone prompts in Codex | `python3 scripts/run_routing_eval.py --eval-set tests/skills/routing/using-agentic-sdlc.json --runtime codex --reasoning-effort high ...` | `routing_eval=passed`, all scenarios passed. |
| `agentic-sdlc-pipeline` invokes the required phase skills/tools in Claude Code | `python3 scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --live --model haiku ...` | `procedure_eval=passed`. |
| `agentic-sdlc-pipeline` Codex adapter transcript satisfies procedure gates | `python3 scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --transcript tests/fixtures/transcripts/agentic-sdlc-pipeline-procedure-codex-adapter-pass.jsonl` | `procedure_eval=passed`. |

If a live Claude Code run uses a restrictive permission mode and the model is denied a required branch/tool action, record it as a permission-mode failure, not as pipeline behavior evidence. Re-run in an isolated fixture with an explicit permissive mode if branch/tool creation is part of the procedure being evaluated.

For publish evidence, prefer Codex `--reasoning-effort high`. Low-effort runs are acceptable as smoke/procedure checks only; if a release decision cites a low-effort run, label it with the exact model, effort, date, and transcript instead of presenting it as a high-effort stability guarantee.

## Captured evidence — 2026-06-18/19 live sweep

Detailed transcripts under `tests/artifacts/` (gitignored); full writeup in
[`docs/testing.md`](testing.md#live-eval-findings-2026-06-18--haiku--sonnet-sweep). Model-capacity note:
**Haiku is a floor** for abstract/meta/gate skills and the pipeline — the same descriptions score
0.80–1.00 on Sonnet and Codex routes them at high effort. Take publish evidence on Sonnet/Opus (Claude)
and `gpt-5.3-codex-spark` at `high` (Codex); do not block release on Haiku floor numbers, but do record
them. Use routing/trigger `--runs ≥3`.

| Evidence | Result | Notes |
|---|---|---|
| `using-agentic-sdlc` routing — Claude | Sonnet 6/6 (router eval-set reworked); Haiku floor at `runs=3` (q13 0.60) | router trigger eval measures the router's own surface; child-routing is the routing eval |
| `using-agentic-sdlc` routing — Codex `high` | **15/15 passed** (`gpt-5.3-codex-spark`, `runs=3`) | satisfies the Codex routing evidence requirement |
| 16-skill trigger matrix — Codex | **16/16 passed** (`low`, after classifier-prompt fix) | `low` is fix-verification; re-confirm at `high` for publish. Pre-fix 12/16 was an eval-tool gap (trigger classifier prompt lacked the over-escalation/feeder guards the routing classifier has), now aligned |
| `agentic-sdlc-pipeline` procedure — Claude | Sonnet 2/2 at `--max-budget-usd 6`; Haiku 1/3 (floor) | `$2` default cut strong-model runs off mid-run → default raised to `5.00` |
| `agentic-sdlc-pipeline` procedure — Codex adapter | **`procedure_eval=passed`** (deterministic transcript) + live low-effort strict smoke pass | adapter patterns present: `spec-plan-author/critic`, "Workflow unavailable/embedded adapter", `docs/agentic-sdlc/specs/`, `docs/agentic-sdlc/plans/`, all gates. Live `codex exec` smoke evidence captured on 2026-06-20 with `gpt-5.3-codex-spark`, `model_reasoning_effort="low"`, RED->GREEN, work-package resolution, and Implementation Control PASS |

Eval-infra fixes made during the sweep (all on `main`): routing-eval early-stop + `runs=3` default;
implementasyon-control/router call-order guards; `safe-refactor`/`skill-authoring`/`completion-claim-gate`
activation guards; procedure-eval `--max-budget-usd` default `2.00 → 5.00`; Codex trigger classifier
prompt aligned with the routing classifier.

## Captured evidence — 2026-06-20 Codex live low smoke

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

Limit of this evidence: this is a Codex low-effort smoke/procedure run, not the publish-grade high-effort stability run. It is valid evidence that the Codex adapter can complete the full pipeline in a small fixture, including RED->GREEN, artifact validation, work-package resolution, and recovery from metadata errors.

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
- Codex command-blocking guardrails are advisory/manual in this release: Codex wires the plugin-default `SessionStart` hook only, while destructive-command, commit-secret, branch, and completion-claim hook enforcement remain Claude Code-only.
- `agentic-sdlc-pipeline` owns internal spec/plan phases. It must not call standalone `spec-authoring` or `plan-authoring` for pipeline steps 4-5; Codex uses the embedded author/critic adapter.
- Hooks are local runtime guardrails. Some warn or fail open by design, so they complement but do not replace diff review, test output, and secret scanning.
- `0.3.0` is publishable for Claude Code and Codex only when the local gate and current live evidence are attached. Other runtimes should be described as experimental adapter targets, not supported release targets.

## Release Verdict Template

Use this shape in a release note or final publish report:

```text
version=0.3.0
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
