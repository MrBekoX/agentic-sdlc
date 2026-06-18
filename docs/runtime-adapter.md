# Runtime Adapter

AGENTIC-SDLC currently supports **Claude Code** and **Codex** as release targets. This file defines the portable capability vocabulary used by the skills and records how Claude Code and Codex satisfy those capabilities.

OpenCode, Kimi Code, GLM-style harnesses, and similar runtimes are deferred adapter targets. Their names remain here only to make the portability boundary explicit and to keep historical/eval references understandable; they are not supported release targets for `0.2.7`.

## Portable Capability Matrix

| Portable capability | Claude Code | Codex | OpenCode | Kimi Code | Degraded fallback |
|---|---|---|---|---|---|
| Load skill instructions | `Skill` tool | activated skill instructions or explicit skill mention | Deferred adapter target | Deferred adapter target | read runtime-local `SKILL.md`; record `Delegation Degraded: skill tool unavailable` |
| Run spec-plan author/critic | `Workflow` -> `agentic-sdlc:spec-plan-draft` | embedded `agentic-sdlc-pipeline` adapter | Deferred adapter target | Deferred adapter target | main-loop author pass plus main-loop critic pass |
| Fresh-context specialist | `Agent` / `Task` | Codex subagent when available | Deferred adapter target | Deferred adapter target | main-loop pass marked `Delegation Degraded: fresh context unavailable` |
| Parallel fan-out | Workflow, agent-team, or multiple agents | subagent fan-out, parallel local tools, or best available native mechanism | Deferred adapter target | Deferred adapter target | sequential execution with explicit degraded note |
| Task tracking | `TodoWrite` | `update_plan` or native task tracker | Deferred adapter target | Deferred adapter target | explicit checklist in the response |
| Ask user | `AskUserQuestion` | direct user question or available input tool | Deferred adapter target | Deferred adapter target | stop at decision point |
| Goal lock | `/goal` | active goal tool if available; otherwise manual lock | Deferred adapter target | Deferred adapter target | `# Goal Lock` artifact |
| Loop fail-fix-retest | `/loop` | manual loop with command evidence | Deferred adapter target | Deferred adapter target | `# Loop Iteration` artifact |
| Runtime plugin root | `${CLAUDE_PLUGIN_ROOT}` | `${PLUGIN_ROOT}` | Deferred adapter target | Deferred adapter target | current repo root |

## Evidence Rule

If a native runtime tool exists, use it. If it does not exist, record `Delegation Degraded: <capability> unavailable`, perform the smallest safe fallback, and preserve deterministic gates such as `detect_context.py`, `validate_artifacts.py`, real test output, diff review, and secret scan.

Do not claim a deferred runtime is supported because this matrix names it. Support requires manifest/runtime wiring, docs, tests, and live evidence.

## Pipeline Spec/Plan Rule

`agentic-sdlc-pipeline` owns internal Spec and Plan phases. Claude Code uses `spec-plan-draft`; Codex uses the embedded author -> critic -> revise adapter. The pipeline must not call standalone `spec-authoring` or `plan-authoring` for its internal steps 4-5.

For deferred adapter targets, the only acceptable documented fallback is the same author -> critic -> revise discipline plus saved artifacts and `validate_artifacts.py` evidence.
