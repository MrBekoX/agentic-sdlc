# Release Readiness

This file is the publish gate for `agentic-sdlc` version `0.2.7`. It keeps the release decision evidence-based for the supported runtimes: Claude Code and Codex.

## Supported Release Scope

| Runtime | Status | Evidence requirement |
|---|---|---|
| Claude Code | Supported | Local gate plus live routing/procedure transcript evidence before claiming live behavior. |
| Codex | Supported | Local gate plus route-classifier/procedure transcript evidence before claiming live behavior. |
| OpenCode, Kimi Code, GLM-style harnesses | Experimental / deferred | Adapter guidance may exist, but these are not release-blocking supported runtimes for `0.2.7`. |

## Required Local Gate

Run these commands from the repository root before publishing or tagging:

```bash
python3 scripts/bump_version.py --check
python3 scripts/check_all.py
python3 tests/skills/harness.py
python3 -m unittest discover -s tests -v
```

On Windows, `py -3` is an acceptable local substitute for `python3` when `python3` is not on `PATH`.

The local gate proves metadata consistency, static skill wiring, fixture health, hook/workflow syntax, and unit behavior. It does not prove live model routing or live tool-use obedience.

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

For publish evidence, do not use Codex `--reasoning-effort low`. Low-effort runs are acceptable for smoke checks only; release evidence should use `high` unless a model/runtime does not expose that setting.

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
- `agentic-sdlc-pipeline` owns internal spec/plan phases. It must not call standalone `spec-authoring` or `plan-authoring` for pipeline steps 4-5; non-Claude runtimes use the embedded author/critic adapter.
- Hooks are local runtime guardrails. Some warn or fail open by design, so they complement but do not replace diff review, test output, and secret scanning.
- `0.2.7` is publishable for Claude Code and Codex when the local gate and current live evidence are attached. Other runtimes should be described as experimental adapter targets, not supported release targets.

## Release Verdict Template

Use this shape in a release note or final publish report:

```text
version=0.2.7
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
