# Changelog

## Unreleased

- Emit only documented hook-output keys under ZCode: a shared `hooks/hook-output.mjs` emitter driven by the `--zcode-runtime` wire marker and the injected `ZCODE_PLUGIN_ROOT` environment variable, so warn paths reach the model through `hookSpecificOutput.additionalContext` and deny paths carry no undeclared key on a marketplace install; other runtimes keep their channels byte-identically.
- Document the portable ZCode install path — adding the GitHub repository (`MrBekoX/agentic-sdlc`) as a marketplace source when there is no clone, beside the root `marketplace.json` file source — and align the distribution wording across the README, adapter readmes and release docs; adapter components (skills, agents, command frontmatter) verified against the current ZCode discovery rules.
- Add experimental Kimi Code, Grok CLI and ZCode adapters: `.kimi-plugin/plugin.json` with the `marketplace-kimi.json` catalog, `.grok-plugin/` with `hooks/hooks-grok.json`, and `.zcode-plugin/` with the root `marketplace.json` and `hooks/hooks-zcode.json`. Each wires a documented subset of the house hooks (PreToolUse command guards; ZCode adds the write scan and SessionStart bootstrap); Claude Code and Codex wiring is unchanged.
- Launch Codex marketplace hooks portably: fixed Node launch code reads the installed `PLUGIN_ROOT` from the environment, with Windows `commandWindows` overrides, instead of depending on a checkout path (#60).
- Resolve the plugin root at runtime on every runtime, so no install needs a machine-specific path: hooks read the runtime's root variable, skills locate the installed folder two levels above the loaded `SKILL.md`, and the SessionStart hooks on Claude Code, Codex and ZCode print the resolved root.
- Fix Windows interpreter and portability gaps: the flow hooks' validator search (`AGENTIC_SDLC_PYTHON`, `python3`, `python`, then `py -3`) fails open on a Microsoft Store alias, a launcher without Python or Python 2, and release archives reject Windows device names, invalid characters and trailing dots or spaces in member names.
- Harden the hooks against hostile projects: `git` and Python resolve only through absolute `PATH` entries, so a program planted in the project never runs, and git runs with settings a repository cannot use to blind the scanners (no colour, no external diff or textconv driver, no fsmonitor or repository hooks); ZCode output carries only documented keys (#59, above).
- Pre-approve only the exact `git-safety-check` commands (`git diff --no-ext-diff --no-textconv` forms; no prefix rules, no `git grep`); any other form asks first.
- Add `scripts/check_native_lifecycle.py`, a no-model native install, discovery, refresh and uninstall check through each vendor's plugin manager in disposable profiles, and `.github/scripts/zcode_agent_lifecycle.mjs` for ZCode's bundled agent CLI, with manual (`workflow_dispatch`) macOS and Linux workflows.
- Add `scripts/prepare_marketplace_release.py`, which exports validated committed source and deterministic Grok/ZCode catalog packets to a new local directory with byte verification; it publishes nothing.
- Ship the Grok catalog `.grok-plugin/marketplace.json` with a remote `url` entry (Grok skips an entry that points at the catalog's own root); it needs the public repository.
- Document install, update and uninstall for all five platforms from an extracted package directory, and add the compatibility matrix: all 15 platform × OS cells (Claude Code, Codex, Kimi Code, Grok CLI and ZCode on Windows, Linux and macOS) passed native install, discovery, update and uninstall with no model turn; hook delivery in a live session and model behavior are not proven there.

## 0.4.3 - 2026-09-13

- Select the authoring toolkit by required validation, evaluation, viewer and packaging capabilities, with explicit diagnostics for incomplete installations.
- Preserve explicit plugin choice and phase ownership across bootstrap, direct skill entry and restored context; load the selected procedure before phase content and keep the full house design process behind a conditional reference.
- Support Codex 0.154.0 native custom patch and command-exit records while rejecting success headers echoed inside denied output.
- Preserve JSON structure and credential-field context when redacting evaluation evidence.
- Enforce the six shared skill frontmatter fields, third-person description framing, portable runtime roots and RED-before-implementation guidance.
- Add Codex presentation assets while retaining the hook-capable compatibility manifest; document native lifecycle coverage and its snapshot, trust and effort limits.
- Refresh release documentation, public evidence visibility and clean distribution checks; use the repository's python3 entry point in CI.
- Clarify pipeline branch-before-write evidence, completed security reviewer results and dependency-install boundaries; require failing test commands to propagate failure to the implementation auditor.
- Close Codex exit-attribution forgery by default: a correlated exit code counts only when the runner is the last statement after splitting on unquoted `;`, newline and `||`, the trailing runner is not version-only or help-only, and a command with a separator stays inside the documented safe shell grammar.
- Add warn-level `branch` and `review-result` flow steps; neither ever blocks.
- Add opt-in strict Codex evidence through `AGENTIC_FLOW_STRICT_EVIDENCE` and the offline `scripts/strict_flow_evidence.py`, which prints `strict_evidence`, `strict_completion` and `strict_branch`.
- Emit an owner-neutral Codex completion message in Superpowers-owned or Ambiguous phases, and release that hook's byte lock with House-message byte pins.
- Add procedure-eval `--strict-evidence`, `--evidence-dir`, `--fixture-root` and `--allow-fixture-commit` (now required for `--live`).
- Add `scripts/build_release.py` for commit-tree release and skills-only archives, `--verify` and `--scan-history`, and make secret scanning examine every match on a line.
- Build, verify and gate the extracted release archive in CI on every push and pull request.
- Correct the Codex listing manifest fields and record unauthenticated link checks in `docs/publication/link-checks.json`.
- Check every visible version declaration in `bump_version.py --check`.
- Document the four distribution paths, the namespaced Claude command `/agentic-sdlc:git-safety-check` with runtime-neutral naming elsewhere, and the corrected Codex personal plugin path `~/plugins/agentic-sdlc`.
- Add `scripts/check_codex_hook_trust.py`, a read-only post-install Codex hook trust check, with per-environment trust steps in `docs/troubleshooting.md`.
- Clear the three real-tree scanner matches: a same-line allow marker on the git-safety-check grep pattern line, a reworded security-audit masking example, and a concatenated JWT-shaped validator test sample.
- Add the release ledger structure tests (`tests/test_release_ledger_docs.py`), the data-handling disclosure and the Claude community and OpenAI skills-only submission packets.

## 0.4.2 - 2026-09-08

- Codex public-listing metadata now uses the official `Developer Tools` category and a `shortDescription` within the final 30-character listing limit.
- Claude plugin manifest now declares `displayName: "Agentic SDLC"`.
- Documented that `codex plugin add agentic-sdlc@personal` remains the supported local install, and that this repo's `.claude-plugin/marketplace.json` is Claude's schema, not a Codex catalog for `codex plugin marketplace add`.
- Recorded Codex hook live-proof drift: last live proof 0.142.0, current documented CLI 0.153.4, Stop/rollout re-probe pending.

## 0.4.1 - 2026-09-01

- Renamed the mixed-language public skill ID `implementasyon-control` to `implementation-control` across discovery metadata, routing, hooks, docs, eval fixtures, and golden references.
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
