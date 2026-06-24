# Runtime Adapter

AGENTIC-SDLC currently supports **Claude Code** and **Codex** as release targets. This file defines the portable capability vocabulary used by the skills and records how Claude Code and Codex satisfy those capabilities.

## Portable Capability Matrix

| Portable capability | Claude Code | Codex | Degraded fallback |
|---|---|---|---|
| Load skill instructions | `Skill` tool | activated skill instructions or explicit skill mention | read runtime-local `SKILL.md`; record `Delegation Degraded: skill tool unavailable` |
| Run spec-plan author/critic | `Workflow` -> `agentic-sdlc:spec-plan-draft` | embedded `agentic-sdlc-pipeline` adapter | main-loop author pass plus main-loop critic pass |
| Fresh-context specialist | `Agent` / `Task` | Codex subagent when available | main-loop pass marked `Delegation Degraded: fresh context unavailable` |
| Parallel fan-out | Workflow, agent-team, or multiple agents | subagent fan-out, parallel local tools, or best available native mechanism | sequential execution with explicit degraded note |
| Task tracking | `TodoWrite` | `update_plan` or native task tracker | explicit checklist in the response |
| Ask user | `AskUserQuestion` | direct user question or available input tool | stop at decision point |
| Goal lock | `/goal` | active goal tool if available; otherwise manual lock | `# Goal Lock` artifact |
| Loop fail-fix-retest | `/loop` | manual loop with command evidence | `# Loop Iteration` artifact |
| Deterministic hook guardrails | Full `hooks/hooks-claude.json`: command guards, write scan, flow guards, session bootstrap, Stop guards | `hooks/hooks-codex.json` SessionStart bootstrap after hook review/trust | skills, contracts, explicit script runs, and transcript/procedure evidence |
| Active-flow evidence enforcement | `flow-order-guard.mjs` and `flow-step-guard.mjs` read `hooks/flow-requirements.json` | no command-blocking flow hooks in this release | run validators and record missing native enforcement as degraded evidence |
| Runtime plugin root | `${CLAUDE_PLUGIN_ROOT}` | `${PLUGIN_ROOT}` | current repo root |

> Other harnesses (OpenCode, Kimi, GLM-style) are future/unsupported work, not release targets.

## Evidence Rule

If a native runtime tool exists, use it. If it does not exist, record `Delegation Degraded: <capability> unavailable`, perform the smallest safe fallback, and preserve deterministic gates such as `detect_context.py`, `validate_artifacts.py`, real test output, diff review, and secret scan.

Do not claim a deferred runtime is supported because this matrix names it. Support requires manifest/runtime wiring, docs, tests, and live evidence.

For Codex procedure transcripts, emit `Runtime: Codex` once and a `Codex Adapter Gate: <gate>` marker at each adapted Skill/Workflow gate. `Delegation Degraded: native Skill transcript events unavailable` means the transcript event is unavailable; the step still has to run through activated/read skill instructions plus deterministic command/artifact evidence. Do not run recursive cleanup deletes for generated caches such as `__pycache__` during Codex pipeline/eval runs; report them instead of adding permission-denial noise.

## Pipeline Spec/Plan Rule

`agentic-sdlc-pipeline` owns internal Spec and Plan phases. Claude Code uses `spec-plan-draft`; Codex uses the embedded author -> critic -> revise adapter. The pipeline must not call standalone `spec-authoring` or `plan-authoring` for its internal steps 4-5.

For deferred adapter targets, the only acceptable documented fallback is the same author -> critic -> revise discipline plus saved artifacts and `validate_artifacts.py` evidence.
