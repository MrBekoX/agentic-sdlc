# AGENTIC-SDLC Plugin Reference

> Version: `0.6.0`. This is the component-by-component reference. For runtime-specific behavior, start with [Claude Code](../.claude-plugin/README.md), [Codex](../.codex-plugin/README.md), [Kimi Code](../.kimi-plugin/README.md), [Grok CLI](../.grok-plugin/README.md), [ZCode](../.zcode-plugin/README.md) or [Cursor](../.cursor-plugin/README.md).

AGENTIC-SDLC is a local development plugin for **Claude Code** and **Codex**, with experimental adapters for **Kimi Code**, **Grok CLI** and **ZCode**. It routes each prompt to the smallest sufficient skill and reserves the full SDLC envelope for work that actually needs it.

## Supported Runtime Scope

| Runtime | Status | Runtime notes |
|---|---|---|
| Claude Code | Supported | Native `Skill`, `Workflow`, `Agent`/`Task`, commands, and full hook wiring. See [`../.claude-plugin/README.md`](../.claude-plugin/README.md). |
| Codex | Supported | Shared skills, Codex manifest metadata, install through `codex plugin marketplace add <package-directory>` then `codex plugin add agentic-sdlc@mrbekox` (a personal catalog is optional), and embedded pipeline adapter. See [`../.codex-plugin/README.md`](../.codex-plugin/README.md). |
| ZCode (Z.ai) | Adapter / experimental (not a 0.4.3 release target) | Marketplace install through the root ZCode-schema `marketplace.json` added as a file source; a directory or GitHub source (`MrBekoX/agentic-sdlc`) is read through `.claude-plugin/marketplace.json` first and shows the Claude entry, and the GitHub source (public since 2026-10-12) is not natively verified. A narrow verified-event hook wire. ZCode 3.14.0 added dynamic workflows, but Z.ai publishes no script API and `plugin.json` has no `workflows` key, so none ships here. See [`../.zcode-plugin/README.md`](../.zcode-plugin/README.md). |
| Grok CLI | Adapter / experimental (not a 0.4.3 release target) | Local install with `grok plugin install <package-directory> --trust`; the shipped catalog `.grok-plugin/marketplace.json` carries a remote `url` entry pointing at the public repository; a narrow verified-event hook wire (`hooks/hooks-grok.json`); project-catalog Rhai at `.grok/workflows/*.rhai` (not a plugin component). See [`../.grok-plugin/README.md`](../.grok-plugin/README.md). |
| Kimi Code | Adapter / experimental, limited runtime coverage (not a 0.4.3 release target) | `/plugins install <package-directory>` in the TUI; `.kimi-plugin/plugin.json`, `marketplace-kimi.json`, startup router and three inline command guards; see [Kimi](../.kimi-plugin/README.md). |
| Cursor | Adapter | Local copy into Cursor's user plugin directory via `scripts/install_cursor_plugin.py`, or a team marketplace import of `.cursor-plugin/marketplace.json`. Shared skills, agents, commands, one rule, and `hooks/hooks-cursor.json`. See [Cursor](../.cursor-plugin/README.md). |
| Google Antigravity | Adapter / experimental (not a supported release target) | Local staging into `<workspace>/.agents/plugins/agentic-sdlc/` or `~/.gemini/config/plugins/agentic-sdlc/` with `.antigravity-plugin/plugin.json` copied as `<plugin-dir>/plugin.json`. Shared skills, portable `<runtime-root>` resolution, `invoke_subagent` delegation, no `hooks.json` wire. See [Google Antigravity](../.antigravity-plugin/README.md). |
| OpenCode / GLM-style harnesses | Deferred adapter targets | Adapter concepts may be documented in [`runtime-adapter.md`](./runtime-adapter.md), but these are not supported release targets for `0.4.3`. |

Claude Code, Codex, Kimi Code, ZCode and Grok CLI are included in [distribution preparation](publication/multi-platform-distribution.md); packaging/replay evidence does not replace native/live validation. Native install, discovery, update and uninstall passed for those five on Windows, Linux and macOS in isolated profiles with no model turn ([compatibility matrix](publication/compatibility-matrix.md), E1–E15); hook trust and delivery inside a live session, live skill behavior and ZCode's desktop GUI flow are not proven there. The Cursor adapter is packaged separately and its IDE lifecycle cells are `not-run`.

## Installation Model

| File | Runtime | Purpose |
|---|---|---|
| `.claude-plugin/plugin.json` | Claude Code | Plugin metadata. |
| `.claude-plugin/marketplace.json` | Claude Code, Codex | Claude-schema marketplace `mrbekox`; its `source: "./"` makes the package root the plugin source. Codex reads this layout too. |
| `.kimi-plugin/plugin.json` | Kimi Code | Skills, commands, agents, startup router, tool mapping and inline hooks. |
| `marketplace-kimi.json` | Kimi Code | Custom catalog schema version 2; plugin version lives in its manifest. |
| `.codex-plugin/plugin.json` | Codex | Codex plugin metadata, `skills`, `hooks`, and `interface` block. |
| `hooks/hooks-claude.json` | Claude Code | `PreToolUse`, `PostToolUse`, `SessionStart`, and `Stop` wiring. |
| `hooks/hooks-codex.json` | Codex | Blocking `PreToolUse`, bootstrap `SessionStart`, and advisory/env-gated `Stop` wiring, subject to Codex hook review/trust. |
| `.zcode-plugin/plugin.json` | ZCode | Adapter plugin metadata; `skills`, `commands`, `agents`, and the ZCode hook wire. |
| `marketplace.json` (repository root) | ZCode | Local marketplace source in the ZCode schema, added as a file source; its `source: "./"` makes the package root the plugin source. A directory or GitHub source (`MrBekoX/agentic-sdlc`, public since 2026-10-12) is read through `.claude-plugin/marketplace.json` first. |
| `hooks/hooks-zcode.json` | ZCode | Verified-event wiring only: `PreToolUse` command guards on `Bash`, `PostToolUse` write scan on `Write\|Edit`, `SessionStart` bootstrap on `startup\|resume\|clear\|compact`. Each handler passes `--zcode-runtime`, so the scripts emit only ZCode-documented hook-output keys (`hooks/hook-output.mjs`). |
| `.grok-plugin/plugin.json` | Grok CLI | Adapter plugin metadata and the Grok hook wire. |
| `.grok-plugin/marketplace.json` | Grok CLI | Grok-schema catalog whose single entry is a remote `url` source (`https://github.com/MrBekoX/agentic-sdlc.git`), which is public since 2026-10-12; Grok skips an entry that points at the catalog's own root. A local install uses `grok plugin install <package-directory> --trust` instead. |
| `hooks/hooks-grok.json` | Grok CLI | Verified-event wiring only: `PreToolUse` command guards on `Bash\|run_terminal_command`. |
| `.cursor-plugin/plugin.json` | Cursor | Cursor plugin metadata and component paths. |
| `.cursor-plugin/marketplace.json` | Cursor | Single-plugin marketplace (`name=mrbekox`, `source: "."`). Prepared for import; not submitted. |
| `hooks/hooks-cursor.json` | Cursor | `beforeShellExecution`, `preToolUse`, `sessionStart` and `stop`, launched through `hooks/cursor-launch.mjs`. |
| `rules/agentic-sdlc.mdc` | Cursor | Always-on pointer at the shared skills and contracts. |
| `.antigravity-plugin/plugin.json` | Google Antigravity | Strict two-key (`name`, `description`) plugin manifest staged to `<plugin-dir>/plugin.json`. |

`.claude-plugin/marketplace.json` is Claude's marketplace schema; current Codex reads it as a legacy-compatible layout named `mrbekox`. The primary Codex install is `codex plugin marketplace add <package-directory>` (no `#` in the path; Codex reads `#` as a ref separator) followed by `codex plugin add agentic-sdlc@mrbekox`. That route installed, discovered, recopied and removed the package natively on codex-cli 0.162.1 on Windows (E2 in the [compatibility matrix](publication/compatibility-matrix.md)); the Linux and macOS runs (E6, E11) installed the same package through a personal catalog. Once the repository is public, `codex plugin marketplace add MrBekoX/agentic-sdlc` surfaces the same `mrbekox` marketplace. A personal catalog (`~/.agents/plugins/marketplace.json`, installed with `codex plugin add agentic-sdlc@personal`) is an optional alternative. Installing from both catalogs can list the plugin twice, once from `mrbekox` and once from `personal`.

Skills live in root `skills/`, not in `.claude/skills/` or `.codex/skills/`. Runtime root variables are:

| Runtime | Plugin root variable |
|---|---|
| Claude Code | `${CLAUDE_PLUGIN_ROOT}` |
| Codex | `${PLUGIN_ROOT}` |
| Kimi Code | `${KIMI_PLUGIN_ROOT}` |
| ZCode | `${ZCODE_PLUGIN_ROOT}` (ZCode also injects the `${CLAUDE_PLUGIN_ROOT}` alias, per the fetched hook documentation) |
| Grok CLI | `${GROK_PLUGIN_ROOT}` (Grok also injects the `${CLAUDE_PLUGIN_ROOT}` alias, per `09-plugins.md`) |

These variables are set only in hook processes. None reaches the model's Bash or PowerShell, where a reference such as `${PLUGIN_ROOT}` expands to an empty string. Skills find the root through their **Plugin root** rule: `<runtime-root>` is the installed folder two levels above the loaded `SKILL.md`. Claude Code substitutes `${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_SKILL_DIR}` in skill text, ZCode only `${CLAUDE_SKILL_DIR}` / `${ZCODE_SKILL_DIR}`, and Kimi Code `${KIMI_SKILL_DIR}`; Codex substitutes nothing but shows the skill's absolute path in the skill listing, and Grok CLI substitutes only when a slash command expands the skill. The `SessionStart` hooks on Claude Code, Codex and ZCode print `Plugin root (resolved by this hook; use this absolute path wherever a skill says <runtime-root>, quoted for your shell): <path>`. If the root cannot be confirmed, the skill stops and reports `plugin root unresolved`.

## Layered Components

| Layer | Responsibility |
|---|---|
| `skills/` | Runnable procedures: `SKILL.md` plus optional `scripts/`, `references/`, and `assets/`. |
| `contracts/skills/` | Durable behavior rules: context-first, spec, plan, testing, security, git safety, documentation, collaboration. |
| `agents/` | Bounded role contracts used for fresh-context analysis, review, audit, and author/critic passes; diagnostic roles may run tests, while reviewer/auditor roles omit shell tools. |
| `workflows/` | Claude Code dynamic workflow scripts. Codex does not run these directly. Grok CLI uses the separate project catalog `.grok/workflows/*.rhai` (not a plugin component). |
| `hooks/` | Deterministic guard scripts, active-flow evidence rules, and runtime hook wiring. |
| `commands/` | Manual slash-command definitions such as `/agentic-sdlc:git-safety-check`. |
| `scripts/` | Deterministic probes, validators, eval runners, version helpers, and review-package helpers. |
| `tests/` | Unit tests, harness, fixtures, golden references, and eval seeds. |
| `.claude-plugin/` / `.codex-plugin/` / `.kimi-plugin/` / `.zcode-plugin/` / `.grok-plugin/` | Runtime manifests and runtime README files. The root `marketplace.json` (ZCode) and `marketplace-kimi.json` (Kimi Code) are the other catalogs. |

## Entry Points

### `using-agentic-sdlc`

The session-local router. It chooses the smallest sufficient skill and escalates only when the prompt asks for full-envelope delivery or touches high-risk implementation areas such as auth, payment, database migration, API contracts, permissions, user data, tokens, sessions, or RLS.

### `agentic-sdlc-pipeline`

The full-envelope orchestrator. It owns git lifecycle, analysis, spec/plan gates, validation, scope lock, quality gates, security passes, final audit, and evidence-before-claim discipline.

The pipeline runs Steps 8–13 itself and never invokes a focused skill or reads its `SKILL.md`. Once the spec and plan are approved, it reads the work-type core file of the matching focused skill and runs that file's core steps:

| Work type | Core file read for Steps 8–13 |
|---|---|
| Feature or endpoint | `skills/feature-build/references/core.md` |
| Bug or broken behavior | `skills/root-cause-fix/references/core.md` |
| Behavior-preserving refactor | `skills/safe-refactor/references/core.md` |
| Test-only work | `skills/test-authoring/references/core.md` |

The standalone skill reads the same core file, so the work-type rules exist once. The pipeline calls `dispatch-strategy` once, at Step 1, and `completion-claim-gate` before any done or ready claim. Its security passes (Steps 11 and 14) dispatch the `security-reviewer` agent, and its implementation-control gate runs `resolve_work_package.py` and dispatches the `implementation-auditor` agent. The `security-audit` and `implementation-control` skills remain standalone entry points.

`spec-authoring` and `plan-authoring` are standalone prompt-level skills. They are not internal pipeline substeps.

## Runtime Split For Spec And Plan

| Runtime | Pipeline spec/plan mechanism |
|---|---|
| Claude Code | Uses the named Workflow `agentic-sdlc:spec-plan-draft` for both spec and plan phases. |
| Codex | Uses the embedded author -> critic -> revise adapter inside `agentic-sdlc-pipeline`; validates saved artifacts with `validate_artifacts.py`. |
| Grok CLI (experimental) | Uses `/workflow spec-plan-draft` (project catalog `.grok/workflows/spec-plan-draft.rhai`) when present; otherwise `spawn_subagent` author -> critic -> revise plus `validate_artifacts.py`. Not a plugin-shipped workflow. |
| Kimi Code (experimental) | No Claude Workflow runtime: `Agent` author -> critic -> revise with saved artifacts plus `validate_artifacts.py`, or an inline pass marked degraded. |
| ZCode (experimental) | A plugin cannot deliver a ZCode workflow (`workflows/zcode/spec-plan-draft.dwf.ts` is an unverified port); uses the embedded author -> critic -> revise adapter, as on Codex, plus `validate_artifacts.py`. |

The pipeline must not call standalone `spec-authoring` or `plan-authoring` for its internal steps 4-5.

Every runtime uses the same depth contract for spec/plan work. `spec-plan-author` carries the concrete bar for Given/When/Then criteria, input-to-sink security notes, RED test points, and runnable verification. `spec-plan-critic` is the adversarial pass and cannot return clean when a draft is shallow, leaks HOW into a spec, invents WHAT in a plan, omits verification, or hand-waves security.

## Focused Skills

| Skill | Owns |
|---|---|
| `spec-authoring` | Standalone WHAT document and acceptance criteria. |
| `plan-authoring` | Standalone HOW document and task sequencing. |
| `feature-build` | Focused new capability implementation. |
| `root-cause-fix` | Root-cause diagnosis and regression-backed fix. |
| `safe-refactor` | Behavior-preserving restructure. |
| `test-authoring` | Test-only creation, repair, or strategy. |
| `security-audit` | Security review and masked findings. |
| `code-quality-review` | Maintainability and implementation-quality review. |
| `feedback-triage` | Verification and application of received feedback. |
| `implementation-control` | Pre-final flow audit. |
| `completion-claim-gate` | Evidence gate before completion claims. |
| `mind-spark` | Pre-spec intent exploration. |
| `dispatch-strategy` | Mechanism choice: main loop, sub-agent, dynamic workflow, or agent team. |
| `skill-authoring` | Skill creation, evaluation, and packaging. |

See [`skill-boundaries.md`](./skill-boundaries.md) for detailed trigger and anti-trigger rules.

## Hooks

The scripts are shared, but runtime wiring differs.

| Script | Claude Code wiring | Codex wiring | Behavior |
|---|---|---|---|
| `session-start.mjs` | `SessionStart` | Not wired | Injects git status and Claude Code Skill-tool bootstrap reminder. |
| `session-start-codex.mjs` | Not wired | `SessionStart` | Injects git status and Codex-specific AGENTIC-SDLC bootstrap reminder. |
| `scan-write.mjs` | `PostToolUse` | Not wired | Warns on secret-shaped new content. |
| `scan-commit.mjs` | `PreToolUse` for shell commands; self-gates to commits | `PreToolUse` for `Bash`; self-gates to commits | Blocks high-confidence secrets in added diff lines. |
| `branch-guard.mjs` | `PreToolUse` for shell commands; self-gates to commit/push | `PreToolUse` for `Bash`; self-gates to commit/push | Warns on protected branches; can block with `AGENTIC_BRANCH_GUARD_BLOCK=true`. |
| `destructive-command-guard.mjs` | `PreToolUse` for shell commands | `PreToolUse` for `Bash` | Blocks the documented deterministic destructive-command subset, after walking off every shell `cmd_prefix` that can precede a command name and reaching into `-c`/`eval` payloads and command substitutions. The walk is depth- and budget-bounded and widens to a coarse linear scan past the bound. The prefix set is closed by the shell grammar; the wrapper list is an open-ended deny-list. |
| `scan-write-codex.mjs` | Not wired | `PreToolUse` for `Bash\|apply_patch` | Blocks high-confidence secrets in recognized literal writes. |
| `flow-order-guard-codex.mjs` | Not wired | `PreToolUse` for `Bash\|apply_patch` | With `AGENTIC_FLOW_ORDER_BLOCK=true`, requires this-session spec/plan or test-run ordering evidence. |
| `flow-order-guard.mjs` | `PreToolUse` for `Write`/`Edit`/`MultiEdit` | Not wired | Checks current-turn pre-edit evidence for active implementation flows before source edits; can deny with `AGENTIC_FLOW_GATE_BLOCK=true`. |
| `completion-claim-guard.mjs` | `Stop` | Not wired | Warns, or blocks with `AGENTIC_COMPLETION_GATE_BLOCK=true`, when final completion claims skip `completion-claim-gate`. |
| `flow-step-guard.mjs` | `Stop` | Not wired | Re-derives active-flow step evidence from validated artifacts, tool calls, and commands; can block missing required steps with `AGENTIC_FLOW_GATE_BLOCK=true`. Its warn-level `branch` and `review-result` steps never block. |
| `completion-claim-guard-codex.mjs` | Not wired | `Stop` | Warns, or continues the turn with `AGENTIC_COMPLETION_GATE_BLOCK=true`, when completion evidence is absent. In a Superpowers-owned or Ambiguous phase the message is owner-neutral (fresh verification evidence); otherwise it is the unchanged house message. |
| `flow-step-guard-codex.mjs` | Not wired | `Stop` | Re-derives Codex-observable evidence; can continue the turn with `AGENTIC_FLOW_GATE_BLOCK=true`. |
| `flow-evidence.mjs` | Shared library | Shared library | Evidence engine used by the flow guards. |
| `secret-patterns.mjs` | Shared library | Shared library | Secret-pattern scanner used by hook scripts. |

The experimental adapters wire a subset of the same scripts. Kimi Code (inline hooks in `.kimi-plugin/plugin.json`) and Grok CLI (`hooks/hooks-grok.json`) run `scan-commit.mjs`, `destructive-command-guard.mjs` and `branch-guard.mjs` as `PreToolUse` command guards; ZCode (`hooks/hooks-zcode.json`) runs the same three plus `scan-write.mjs` on `PostToolUse` and `session-start.mjs` on `SessionStart`. None of them wires a Stop or flow guard; see [`runtime-adapter.md`](./runtime-adapter.md).

`hooks/flow-requirements.json` is the shared source for which steps each active flow must evidence. It covers `root-cause-fix`, `feature-build`, `safe-refactor`, and `agentic-sdlc-pipeline`; the offline gate validates that every referenced skill, workflow, agent, and validator exists.

Judgment-based gates remain in skills and contracts. A script cannot decide whether a model understood test output, followed a spec, or completed a security review.

## Deterministic scripts (25)

| Script | Purpose |
|---|---|
| `check_all.py` | Skill frontmatter and validator tests. |
| `build_release.py` | Builds the release or skills-only (`--skills-only`) archive from the recorded HEAD commit (`--output`), verifies an archive against its recorded commit (`--verify`), and scans a local bare mirror's history (`--scan-history`). |
| `strict_flow_evidence.py` | Offline strict evaluation of one Codex rollout (`--rollout`, `--cwd`), printing `strict_evidence=`, `strict_completion=` and `strict_branch=`. |
| `check_codex_hook_trust.py` | Read-only post-install Codex hook trust check over `codex app-server --stdio` `hooks/list`, printing `codex_hook_trust=`. |
| `check_native_lifecycle.py` | No-model native install, discovery, refresh and uninstall of a package (`--package`) through each vendor's own plugin manager in a disposable profile (`--platform`, `--require`), printing one `native_<platform>=passed\|failed:<reason>\|not-run:<reason>` line per platform. |
| `eval_safety.py` | Shared eval slug and path-containment boundaries. |
| `sensitive_redaction.py` | Canonical high-confidence redaction adapter for persisted artifacts. |
| `validate_artifacts.py` | Spec/plan validation: structure, AC coverage, placeholders/secrets, task verification, deferral, and security hand-wave checks. |
| `resolve_work_package.py` | Deterministically resolves the canonical spec/plan pair for implementation audits without timestamp fallback. |
| `check_plugin_portability.py` | Checks declared hook paths and their transitive module/resource closure; shared by source harness and release build/verification. |
| `check_cursor_plugin.py` | Static Cursor manifest, component frontmatter and hook-path check. It does not start Cursor. |
| `install_cursor_plugin.py` | Copy, update or uninstall the package in Cursor's local plugin directory. Update and uninstall keep files the installer did not write. |
| `prepare_marketplace_release.py` | Export validated committed source and deterministic Grok/ZCode catalog packets to a new local destination, with separate producer/source provenance and byte verification; no publication or original Git mutation. |
| `detect_context.py` | Workspace/dependency/toolchain classification. |
| `run_trigger_eval.py` | Claude Code trigger eval runner. |
| `run_codex_trigger_eval.py` | Codex route-classifier trigger runner. |
| `run_all_trigger_evals.py` | Batch trigger eval runner. |
| `run_routing_eval.py` | Runtime routing eval for `using-agentic-sdlc`. |
| `run_behavior_eval.py` | Behavior fixture validator/eval runner. |
| `run_procedure_eval.py` | Transcript/procedure gate evaluator. |
| `run_glm_trigger_eval.py` | Experimental adapter research runner, not release-blocking. |
| `bump_version.py` | Sync version across manifests and `VERSION`. |
| `task_brief.py` | Extract a plan task into a handoff file. |
| `review_package.py` | Produce a git diff review package. |
| `install_git_hooks.py` | Install the effect-layer git guards into a repository. Git runs those on the OPERATION, after it has resolved aliases, quoting and `$PATH`, so they see what the command-string guards structurally cannot. Ownership is recorded in the repository's git directory; foreign/modified hooks are preserved, `--check` / `--uninstall` are supported, and an external/shared `core.hooksPath` requires `--allow-external-hooks-path`. |

## Testing And Evidence

Local deterministic gate:

```bash
python3 scripts/bump_version.py --check
python3 scripts/check_all.py
python3 tests/skills/harness.py
python3 -m unittest discover -s tests -v
```

The local gate proves static wiring and fixture health. It does not prove live model obedience. Runtime behavior claims need current eval output or transcript evidence:

| Claim | Evidence source |
|---|---|
| Claude skill trigger | `run_trigger_eval.py` stream-json transcript with real `Skill`/`Read` activation. |
| Codex route selection | `run_codex_trigger_eval.py` route-classifier output. |
| Pipeline procedure | `run_procedure_eval.py` transcript/tool/artifact evidence. |

See [`testing.md`](./testing.md) and [`release-readiness.md`](./release-readiness.md).

## Known Limitations

- The `0.4.3` release supported Claude Code and Codex only. The current tree also packages Kimi Code, Grok CLI and ZCode as experimental adapters with narrower hook wiring; their native install, discovery, update and uninstall pass on Windows, Linux and macOS ([compatibility matrix](publication/compatibility-matrix.md)), but hook delivery inside a live session and model behavior are not proven.
- Codex hook wiring is declared via `.codex-plugin/plugin.json` -> `hooks/hooks-codex.json`; non-managed plugin-bundled command hooks require Codex review/trust before they run. It is deliberately not named `hooks/hooks.json`, which Claude Code would auto-load with an undefined `${PLUGIN_ROOT}`.
- Codex trigger evals are classifier evidence, not Claude-style `Skill` event evidence.
- Hooks fail open where necessary so a hook fault does not break a session.
- `validate_artifacts.py` is structural; it cannot prove that a spec is semantically about the requested task.
- Live routing is model-dependent and must be evidenced per runtime, model, and run.
- Codex public-listing fields now use `interface.category: "Developer Tools"` and a `shortDescription` of at most 30 characters. Local CLI install does not require a public directory listing.
- Bounded native hook/lifecycle captures exist for Codex **0.154.0** and Claude Code **2.1.269**. Their source identities and the separate parser replay are recorded in [runtime evidence](runtime-adapter.md#current-binary-and-historical-hook-evidence); `transcript_path` remains unstable. The [release ledger](release-evidence-0.4.3.md) distinguishes this proof from the standalone routing and pipeline publication gates.

## Artifact Layouts And Per-Package Evidence

Work-package artifacts resolve in two layouts: the legacy flat `docs/agentic-sdlc/{specs,plans}/<id>.md` (back-compat, unchanged) and the per-package canonical `docs/agentic-sdlc/<slug>/{spec,plan,evidence}/<work_id>.md`, where `<slug>` is lowercase kebab-case `^[a-z0-9][a-z0-9-]{0,63}$` and never a reserved name (`specs`, `plans`, `evidence`, `notes`, `spec`, `plan`).

Per-package evidence persists to `docs/agentic-sdlc/<slug>/evidence/<work_id>.md` — per-package only (flat packages get no evidence), overwritten in place per run (single canonical file, last run wins), git-ignored, and with no validator (it never gates resolution). That evidence write is performed by the main pipeline finalize step, not the read-only `implementation-auditor` sub-agent.

Per-package plan change-detection runs as a filesystem scan, not a `git status` query: new generated plans can be git-ignored, so the resolver scans the filesystem; published plugin documentation is tracked separately.

## Cross-References

- Project overview: [`../README.md`](../README.md)
- Claude runtime README: [`../.claude-plugin/README.md`](../.claude-plugin/README.md)
- Codex runtime README: [`../.codex-plugin/README.md`](../.codex-plugin/README.md)
- Kimi Code, Grok CLI and ZCode adapter READMEs: [`../.kimi-plugin/README.md`](../.kimi-plugin/README.md), [`../.grok-plugin/README.md`](../.grok-plugin/README.md), [`../.zcode-plugin/README.md`](../.zcode-plugin/README.md)
- Compatibility matrix: [`publication/compatibility-matrix.md`](publication/compatibility-matrix.md)
- Skill boundaries: [`skill-boundaries.md`](./skill-boundaries.md)
- Testing: [`testing.md`](./testing.md)
- Troubleshooting: [`troubleshooting.md`](./troubleshooting.md)
- Release readiness: [`release-readiness.md`](./release-readiness.md)
