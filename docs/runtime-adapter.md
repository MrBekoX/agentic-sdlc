# Runtime Adapter

AGENTIC-SDLC skills use portable capability names first and runtime-native tool names second. Claude Code remains the reference implementation for `Skill`, `Workflow`, and `Agent` transcript gates, but non-Claude runtimes satisfy the same behavior through equivalent evidence.

## Portable Capability Matrix

| Portable capability | Claude Code | Codex | OpenCode | Kimi Code | Degraded fallback |
|---|---|---|---|---|---|
| Load skill instructions | `Skill` tool | activated skill instructions or explicit skill mention | native `skill({ name })` tool | `/skill:<name>` or automatic skill read | read runtime-local `SKILL.md`; record `Delegation Degraded: skill tool unavailable` |
| Run spec-plan author/critic | `Workflow` -> `agentic-sdlc:spec-plan-draft` | embedded `agentic-sdlc-pipeline` adapter | subagent pair or main-loop adapter | `Agent` subagent pair; `/flow` only if packaged as a flow skill | main-loop author pass plus main-loop critic pass |
| Fresh-context specialist | `Agent` / `Task` | Codex subagent when available | configured subagent or `@` mention | `Agent` tool with built-in/custom subagent | main-loop pass marked `Delegation Degraded: fresh context unavailable` |
| Parallel fan-out | Workflow, agent-team, or multiple agents | subagent fan-out, parallel local tools, cloud delegation | subagents, plugins, or parallel sessions | background/parallel `Agent` subagents | sequential execution with explicit degraded note |
| Task tracking | `TodoWrite` | `update_plan` or native task tracker | todo tool/events when enabled | `SetTodoList` | explicit checklist in the response |
| Ask user | `AskUserQuestion` | direct user question or available input tool | direct user question | `AskUserQuestion` | stop at decision point |
| Goal lock | `/goal` | active goal tool if available; otherwise manual lock | plan agent/manual scope lock | manual or tool-backed lock | `# Goal Lock` artifact |
| Loop fail-fix-retest | `/loop` | manual loop with command evidence | manual loop or configured command | manual loop | `# Loop Iteration` artifact |
| Runtime plugin root | `${CLAUDE_PLUGIN_ROOT}` | `${PLUGIN_ROOT}` | configured plugin or repo root | skill root / `--skills-dir` root | current repo root |

## Evidence Rule

If a native runtime tool exists, use it. If it does not exist, record `Delegation Degraded: <capability> unavailable`, perform the smallest safe fallback, and preserve deterministic gates such as `detect_context.py`, `validate_artifacts.py`, real test output, diff review, and secret scan.

## Pipeline Spec/Plan Rule

`agentic-sdlc-pipeline` owns internal Spec and Plan phases. Claude Code uses `spec-plan-draft`; Codex, OpenCode, Kimi Code, and other non-Claude runtimes use the embedded author -> critic -> revise adapter. The pipeline must not call standalone `spec-authoring` or `plan-authoring` for its internal steps 4-5.
