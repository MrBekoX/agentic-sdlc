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
| Deterministic hook guardrails | Full `hooks/hooks-claude.json`: command guards, write scan, flow guards, session bootstrap, Stop guards | `hooks/hooks-codex.json` SessionStart bootstrap + native blocking PreToolUse guards (shell-string command form, verified live codex-cli 0.142.0): command guards `scan-commit.mjs`, `destructive-command-guard.mjs`, `branch-guard.mjs` (matcher `Bash`), PLUS a native pre-write secret guard `scan-write-codex.mjs` (matcher `Bash|apply_patch`) backed by the pure extractor `codex-write-signal.mjs`. The write guard is a **bounded deterministic backstop**: it scans only the literal added content of recognized write forms — apply_patch V4A patches, and `printf`/`echo` `>`/`>>` redirects and literal heredocs — and denies a high-confidence secret before the write lands. NOT covered (fail-open, documented): pipe/`tee`/`base64`/command-substitution writes and `$VAR`/`${...}`/`$(...)` expansion-dependent payloads. PLUS a native `Stop` guard `completion-claim-guard-codex.mjs` (backed by the pure reader `codex-rollout.mjs`): on an unverified completion claim made without the `completion-claim-gate` **sentinel marker** in the rollout, it emits a non-blocking advisory by default or blocks under `AGENTIC_COMPLETION_GATE_BLOCK` (live-verified loop-safe on codex-cli 0.142.0). The Claude `scan-write.mjs` PostToolUse guard (Claude `Write`/`Edit` field shape) and the flow Stop guard `flow-step-guard.mjs` stay unwired on Codex — VERIFY (see the Active-flow row) | skills, contracts, explicit script runs, and transcript/procedure evidence |
| Active-flow evidence enforcement | `flow-order-guard.mjs` and `flow-step-guard.mjs` read `hooks/flow-requirements.json` | VERIFY — PROBED, not wireable as-is (needs an adapter, not a wire). The write SECRET-scan is now covered by the new `scan-write-codex.mjs` adapter (see the guardrails row); the **completion-claim Stop backstop is now WIRED on Codex** via the marker adapter `completion-claim-guard-codex.mjs` (+ `codex-rollout.mjs`): Phase-0d showed a `completion-claim-gate` activation leaves no reliable rollout signal, so the gate now emits a deterministic sentinel marker (its `SKILL.md` contract) and the adapter detects that marker — the Claude `completion-claim-guard.mjs` file itself is NOT ported as-is (its `Skill` tool_use / `type:"assistant"` detection finds nothing in the rollout — VERIFY) and stays Claude-only, superseded on Codex by the marker adapter. What stays deferred HERE is `flow-order-guard.mjs`'s path-gating (write) and `flow-step-guard.mjs` (Stop), plus the Claude `scan-write.mjs` field shape. These are NOT wired on Codex: Codex has no Claude-style `Write`/`Edit`/`MultiEdit` field shape — edits surface as the `Bash` tool (this probe's model) or the native `apply_patch` tool (first-party models), and BOTH carry the payload in `tool_input.command`, never `tool_input.file_path`/`new_string`, so the current guards' field reads never match; and the Codex Stop transcript is the rollout format (`session_meta`/`response_item`/`event_msg`), NOT Claude-JSONL, so `flow-evidence.mjs`'s `Skill`/`Workflow`/`Agent` `tool_use` parsing and `completion-claim-guard.mjs`'s `type:"assistant"` parsing find nothing. Wiring requires a Codex adapter (match `Bash`+`apply_patch`, parse `tool_input.command`; parse the rollout transcript / `last_assistant_message` for Stop) — a separate redesign phase. The skill-activation detection that the Claude `completion-claim-guard.mjs` relies on was PROBED (Phase 0d) and found to have NO reliable Codex signal — which is exactly why the Codex backstop uses the deterministic sentinel marker (above) instead of porting that file's mechanism. Run validators + degraded evidence meanwhile | run validators and record missing native enforcement as degraded evidence |
| Runtime plugin root | `${CLAUDE_PLUGIN_ROOT}` | `${PLUGIN_ROOT}` | current repo root |

> Other harnesses (OpenCode, Kimi, GLM-style) are future/unsupported work, not release targets.

## Evidence Rule

If a native runtime tool exists, use it. If it does not exist, record `Delegation Degraded: <capability> unavailable`, perform the smallest safe fallback, and preserve deterministic gates such as `detect_context.py`, `validate_artifacts.py`, real test output, diff review, and secret scan.

Do not claim a deferred runtime is supported because this matrix names it. Support requires manifest/runtime wiring, docs, tests, and live evidence.

For Codex procedure transcripts, emit `Runtime: Codex` once and a `Codex Adapter Gate: <gate>` marker at each adapted Skill/Workflow gate. `Delegation Degraded: native Skill transcript events unavailable` means the transcript event is unavailable; the step still has to run through activated/read skill instructions plus deterministic command/artifact evidence. Do not run recursive cleanup deletes for generated caches such as `__pycache__` during Codex pipeline/eval runs; report them instead of adding permission-denial noise.

## Pipeline Spec/Plan Rule

`agentic-sdlc-pipeline` owns internal Spec and Plan phases. Claude Code uses `spec-plan-draft`; Codex uses the embedded author -> critic -> revise adapter. The pipeline must not call standalone `spec-authoring` or `plan-authoring` for its internal steps 4-5.

For deferred adapter targets, the only acceptable documented fallback is the same author -> critic -> revise discipline plus saved artifacts and `validate_artifacts.py` evidence.
