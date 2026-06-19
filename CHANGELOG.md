# Changelog

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
