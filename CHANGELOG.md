# Changelog

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
