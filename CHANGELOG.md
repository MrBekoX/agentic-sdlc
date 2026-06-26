# Changelog

## Unreleased — skill-depth contract (PoC)

- Refreshed plugin documentation for the current Claude/Codex layer split: active flow guards, flow evidence config, deeper spec/plan validation, work-package resolution, router/procedure evals, and current test-suite coverage.
- Procedure eval now validates written artifact **content** (a literal `"spec"`/`"plan"` stub is rejected as `shallow_artifact`), closing the gap where surface-trace transcripts passed.
- Validator gained quality checks (`task_no_verification`, `deferred_work`, `security_handwave`) — quality + proportionality, **no numeric count floors**.
- `spec-plan-critic` carries a hard-blocker list + external-signal grounding; the inline-critic loophole is removed from all skills — a fresh-context critic is mandatory wherever the runtime supports it.
- `spec-authoring` / `plan-authoring` carry proportional depth-forcing (Depth contract + Excuse→Check + no-placeholder + shallow example).
- Regression fixtures lock the bar: shallow artifacts FAIL, a deep reference PASSES. Live before/after proof is pending a CLI run.

## 0.4.0 - 2026-06-26

- **Codex v0.142.0 native deterministic hooks.** The plugin's guard logic now runs on Codex's native hook system (each guard's logic preserved, driven by Codex-native mechanisms; Claude Code behavior stays byte-identical). All Codex behavior was established by live `codex exec` probes, not assumed.
  - Command guards (`scan-commit`, `destructive-command-guard`, `branch-guard`) + a bounded pre-write **secret guard** `scan-write-codex.mjs` (matcher `Bash|apply_patch`, backed by the pure `codex-write-signal.mjs`).
  - **completion-claim** Stop backstop `completion-claim-guard-codex.mjs`: since a skill activation leaves no reliable rollout signal on Codex, the `completion-claim-gate` now emits a deterministic sentinel marker and the guard detects it (live-verified block/silent).
  - **flow-step** Stop backstop `flow-step-guard-codex.mjs` (+ `codex-flow-evidence.mjs`, `codex-rollout.mjs`): evidence-only, session-scoped — an artifact-bearing flow that finished with a missing step (stub/missing spec or plan, or no test run after a source edit) warns or, under `AGENTIC_FLOW_GATE_BLOCK`, blocks. Committed prior-session artifacts never false-activate it.
  - **flow-order** PreToolUse pre-edit gate `flow-order-guard-codex.mjs`: env-gated opt-in (its own `AGENTIC_FLOW_ORDER_BLOCK`, independent of flow-step) that denies a source edit attempted before a validated spec + matching plan exist this session.
- The Codex rollout reader was hardened against live findings: it reads the real `patch_apply_end` apply_patch carrier, and surfaces every `>`/`>>` shell-redirect target (including newline-bundled multi-writes) as an in-session edit.
- Two Stop guards (completion-claim + flow-step) confirmed live to fire independently on one Stop event.

## 0.3.0 - 2026-06-19

- Introduced the original "Assertion contract" skill voice (`Invariant` / `Tripwires` / `Proof` / `Excuse → check`) and applied it to the discipline-bearing skills; removed borrowed `Red Flags`/`Rationalizations` headings from the product surface.
- Deduplicated both SessionStart bootstraps (`session-start.mjs`, `session-start-codex.mjs`) against the `using-agentic-sdlc` router skill.
- Narrowed the product surface to Claude Code + Codex; other harnesses are now framed only as future/unsupported work.
- Renamed the marketplace to `mrbekox` for a public channel (`/plugin install agentic-sdlc@mrbekox`).
- Added `.github` issue/PR templates and `CONTRIBUTING.md`; started tracking the dogfooding spec/plan under `docs/specs/` and `docs/plans/`.
- Added `tests/test_house_voice.py` guards locking the house-voice, runtime-scope, and maintenance-file acceptance criteria.

## 0.2.7 - 2026-06-17

- Added full-project trigger eval batch coverage for Claude and Codex skill routing, including no-command-shim Claude live activation and Codex route-classifier updates.
- Tuned all 16 skill trigger descriptions and eval fixtures around smallest-sufficient-skill routing, focused feature/spec/plan boundaries, and explicit claim-gate prompts.
- Added all-skill trigger fixture enforcement so every `skills/*/SKILL.md` has a matching eval set.

## 0.2.6 - 2026-06-17

- Stabilized Claude `spec-flow` live trigger evaluation by narrowing router/workflow trigger metadata and allowing harmless prelude reads in the trigger detector without counting command files as skill activation.
- Added trigger detector unit coverage for AGENTS/memory prelude reads, generated command-file reads, real skill-file reads, and replay behavior.

## 0.2.5 - 2026-06-17

- Split live trigger evaluation by runtime: Claude keeps tool-event trigger checks, while Codex gets a separate route-classifier harness over shared skill eval fixtures.
- Added Claude `--bare` trigger smoke support to isolate project context from plugin trigger behavior.

## 0.2.4 - 2026-06-17

- Added a safe live trigger smoke mode with single-query execution, process-tree cleanup, plugin-dir loading, transcript capture, and budget controls.

## 0.2.3 - 2026-06-17

- Standardized `SKILL.md` runtime-root path guidance so Claude Code uses `${CLAUDE_PLUGIN_ROOT}` and Codex uses `${PLUGIN_ROOT}` for contracts and scripts.

## 0.2.2 - 2026-06-17

- Adapted `dev-flow` spec/plan phases for Codex by defining an embedded author/critic adapter instead of requiring Claude Code dynamic workflows.
- Clarified that `spec-flow` and `plan-flow` are standalone prompt-level routes, not internal `dev-flow` substeps.
- Documented Claude Code versus Codex runtime mapping for workflows, subagents, hooks, and spec/plan artifact generation.

## 0.2.1 - 2026-06-17

- Defined explicit runtime bindings for `spec-flow` and `plan-flow`: router hook, skill contracts, author/critic agents, workflow, and validator.
- Updated spec/plan agents to enforce `contracts/skills/02-spec-driven-development.md` and `contracts/skills/03-plan-mode.md`.
- Extended the skill harness golden references with resolvable `contract` and `hook` kinds.

## 0.2.0 - 2026-06-17

- Added Codex plugin manifest and Codex session-start hook wiring.
- Added `using-agentic-sdlc` as the session-local smallest-sufficient-skill router.
- Added standalone `spec-flow` and `plan-flow` skills with trigger eval coverage.
- Moved shared rule material into skill contracts and removed the Turkish-only response requirement from skill contracts.
- Removed GitHub Actions CI workflow; validation now remains a local manual gate.
- Updated skill harness, metadata, and trigger eval fixtures for 16 skills.

## 0.1.0 - 2026-06-17

- Added Claude Code plugin manifest and development marketplace metadata.
- Documented Claude Code runtime expectations, testing, and troubleshooting.
- Added strict-mode branch guard configuration and destructive command guard.
- Added trigger eval fixtures for all existing skills.
- Added local validation scaffolding and version bump helper.
