# AGENTIC-SDLC Plugin Reference

> Version: `0.4.3`. This is the component-by-component reference. For runtime-specific behavior, start with [Claude Code](../.claude-plugin/README.md) or [Codex](../.codex-plugin/README.md).

AGENTIC-SDLC is a local development plugin for **Claude Code** and **Codex**. It routes each prompt to the smallest sufficient skill and reserves the full SDLC envelope for work that actually needs it.

## Supported Runtime Scope

| Runtime | Status | Runtime notes |
|---|---|---|
| Claude Code | Supported | Native `Skill`, `Workflow`, `Agent`/`Task`, commands, and full hook wiring. See [`../.claude-plugin/README.md`](../.claude-plugin/README.md). |
| Codex | Supported | Shared skills, Codex manifest metadata, personal-marketplace install flow, and embedded pipeline adapter. See [`../.codex-plugin/README.md`](../.codex-plugin/README.md). |
| ZCode (Z.ai) | Adapter / experimental (not a 0.4.3 release target) | Local personal-marketplace install through the root ZCode-schema `marketplace.json`; a narrow verified-event hook wire and no Workflow runtime. See [`../.zcode-plugin/README.md`](../.zcode-plugin/README.md). |
| OpenCode / Kimi Code / GLM-style harnesses | Deferred adapter targets | Adapter concepts may be documented in [`runtime-adapter.md`](./runtime-adapter.md), but these are not supported release targets for `0.4.3`. |

## Installation Model

| File | Runtime | Purpose |
|---|---|---|
| `.claude-plugin/plugin.json` | Claude Code | Plugin metadata. |
| `.claude-plugin/marketplace.json` | Claude Code | Local marketplace source; the repo root is the source. |
| `.codex-plugin/plugin.json` | Codex | Codex plugin metadata, `skills`, `hooks`, and `interface` block. |
| `hooks/hooks-claude.json` | Claude Code | `PreToolUse`, `PostToolUse`, `SessionStart`, and `Stop` wiring. |
| `hooks/hooks-codex.json` | Codex | Blocking `PreToolUse`, bootstrap `SessionStart`, and advisory/env-gated `Stop` wiring, subject to Codex hook review/trust. |
| `.zcode-plugin/plugin.json` | ZCode | Adapter plugin metadata; `skills`, `commands`, `agents`, and the ZCode hook wire. |
| `marketplace.json` (repository root) | ZCode | Local marketplace source in the ZCode schema; the repo root is the source. |
| `hooks/hooks-zcode.json` | ZCode | Verified-event wiring only: `PreToolUse` command guards on `Bash`, `PostToolUse` write scan on `Write\|Edit`, `SessionStart` bootstrap on `startup\|clear\|compact`. |

`.claude-plugin/marketplace.json` is Claude's marketplace schema and not the supported Codex install path. Codex 0.154.0 can read it as a legacy-compatible layout, and `codex plugin marketplace add MrBekoX/agentic-sdlc` surfacing the `mrbekox` marketplace has been observed, but that route is unsupported. Installing both routes can list the plugin twice, once from `mrbekox` and once from `personal`. The supported Codex install remains `codex plugin add agentic-sdlc@personal`.

Skills live in root `skills/`, not in `.claude/skills/` or `.codex/skills/`. Runtime root variables are:

| Runtime | Plugin root variable |
|---|---|
| Claude Code | `${CLAUDE_PLUGIN_ROOT}` |
| Codex | `${PLUGIN_ROOT}` |
| ZCode | `${ZCODE_PLUGIN_ROOT}` (ZCode also injects the `${CLAUDE_PLUGIN_ROOT}` alias, per the fetched hook documentation) |

## Layered Components

| Layer | Responsibility |
|---|---|
| `skills/` | Runnable procedures: `SKILL.md` plus optional `scripts/`, `references/`, and `assets/`. |
| `contracts/skills/` | Durable behavior rules: context-first, spec, plan, testing, security, git safety, documentation, collaboration. |
| `agents/` | Bounded role contracts used for fresh-context analysis, review, audit, and author/critic passes; diagnostic roles may run tests, while reviewer/auditor roles omit shell tools. |
| `workflows/` | Claude Code dynamic workflow scripts. Codex does not run these directly. |
| `hooks/` | Deterministic guard scripts, active-flow evidence rules, and runtime hook wiring. |
| `commands/` | Manual slash-command definitions such as `/agentic-sdlc:git-safety-check`. |
| `scripts/` | Deterministic probes, validators, eval runners, version helpers, and review-package helpers. |
| `tests/` | Unit tests, harness, fixtures, golden references, and eval seeds. |
| `.claude-plugin/` / `.codex-plugin/` | Runtime manifests and runtime README files. |

## Entry Points

### `using-agentic-sdlc`

The session-local router. It chooses the smallest sufficient skill and escalates only when the prompt asks for full-envelope delivery or touches high-risk implementation areas such as auth, payment, database migration, API contracts, permissions, user data, tokens, sessions, or RLS.

### `agentic-sdlc-pipeline`

The full-envelope orchestrator. It owns git lifecycle, analysis, spec/plan gates, validation, scope lock, quality gates, security passes, final audit, and evidence-before-claim discipline.

The pipeline does not duplicate the implementation core. It delegates to focused skills after it has approved spec/plan artifacts:

| Work type | Delegated core skill |
|---|---|
| Feature or endpoint | `feature-build` |
| Bug or broken behavior | `root-cause-fix` |
| Behavior-preserving refactor | `safe-refactor` |
| Test-only work | `test-authoring` |

Gate skills feed the pipeline at control points: `dispatch-strategy`, `security-audit`, `implementation-control`, and `completion-claim-gate`.

`spec-authoring` and `plan-authoring` are standalone prompt-level skills. They are not internal pipeline substeps.

## Runtime Split For Spec And Plan

| Runtime | Pipeline spec/plan mechanism |
|---|---|
| Claude Code | Uses the named Workflow `agentic-sdlc:spec-plan-draft` for both spec and plan phases. |
| Codex | Uses the embedded author -> critic -> revise adapter inside `agentic-sdlc-pipeline`; validates saved artifacts with `validate_artifacts.py`. |

The pipeline must not call standalone `spec-authoring` or `plan-authoring` for its internal steps 4-5.

Both runtimes use the same depth contract for spec/plan work. `spec-plan-author` carries the concrete bar for Given/When/Then criteria, input-to-sink security notes, RED test points, and runnable verification. `spec-plan-critic` is the adversarial pass and cannot return clean when a draft is shallow, leaks HOW into a spec, invents WHAT in a plan, omits verification, or hand-waves security.

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
| `destructive-command-guard.mjs` | `PreToolUse` for shell commands | `PreToolUse` for `Bash` | Blocks the documented deterministic destructive-command subset. |
| `scan-write-codex.mjs` | Not wired | `PreToolUse` for `Bash\|apply_patch` | Blocks high-confidence secrets in recognized literal writes. |
| `flow-order-guard-codex.mjs` | Not wired | `PreToolUse` for `Bash\|apply_patch` | With `AGENTIC_FLOW_ORDER_BLOCK=true`, requires this-session spec/plan or test-run ordering evidence. |
| `flow-order-guard.mjs` | `PreToolUse` for `Write`/`Edit`/`MultiEdit` | Not wired | Checks current-turn pre-edit evidence for active implementation flows before source edits; can deny with `AGENTIC_FLOW_GATE_BLOCK=true`. |
| `completion-claim-guard.mjs` | `Stop` | Not wired | Warns, or blocks with `AGENTIC_COMPLETION_GATE_BLOCK=true`, when final completion claims skip `completion-claim-gate`. |
| `flow-step-guard.mjs` | `Stop` | Not wired | Re-derives active-flow step evidence from validated artifacts, tool calls, and commands; can block missing required steps with `AGENTIC_FLOW_GATE_BLOCK=true`. Its warn-level `branch` and `review-result` steps never block. |
| `completion-claim-guard-codex.mjs` | Not wired | `Stop` | Warns, or continues the turn with `AGENTIC_COMPLETION_GATE_BLOCK=true`, when completion evidence is absent. In a Superpowers-owned or Ambiguous phase the message is owner-neutral (fresh verification evidence); otherwise it is the unchanged house message. |
| `flow-step-guard-codex.mjs` | Not wired | `Stop` | Re-derives Codex-observable evidence; can continue the turn with `AGENTIC_FLOW_GATE_BLOCK=true`. |
| `flow-evidence.mjs` | Shared library | Shared library | Evidence engine used by the flow guards. |
| `secret-patterns.mjs` | Shared library | Shared library | Secret-pattern scanner used by hook scripts. |

`hooks/flow-requirements.json` is the shared source for which steps each active flow must evidence. It covers `root-cause-fix`, `feature-build`, `safe-refactor`, and `agentic-sdlc-pipeline`; the offline gate validates that every referenced skill, workflow, agent, and validator exists.

Judgment-based gates remain in skills and contracts. A script cannot decide whether a model understood test output, followed a spec, or completed a security review.

## 11. Deterministic scripts (20)

| Script | Purpose |
|---|---|
| `check_all.py` | Skill frontmatter and validator tests. |
| `build_release.py` | Builds the release or skills-only (`--skills-only`) archive from the recorded HEAD commit (`--output`), verifies an archive against its recorded commit (`--verify`), and scans a local bare mirror's history (`--scan-history`). |
| `strict_flow_evidence.py` | Offline strict evaluation of one Codex rollout (`--rollout`, `--cwd`), printing `strict_evidence=`, `strict_completion=` and `strict_branch=`. |
| `check_codex_hook_trust.py` | Read-only post-install Codex hook trust check over `codex app-server --stdio` `hooks/list`, printing `codex_hook_trust=`. |
| `eval_safety.py` | Shared eval slug and path-containment boundaries. |
| `sensitive_redaction.py` | Canonical high-confidence redaction adapter for persisted artifacts. |
| `validate_artifacts.py` | Spec/plan validation: structure, AC coverage, placeholders/secrets, task verification, deferral, and security hand-wave checks. |
| `resolve_work_package.py` | Deterministically resolves the canonical spec/plan pair for implementation audits without timestamp fallback. |
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

- `0.4.3` supports Claude Code and Codex only.
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
- Skill boundaries: [`skill-boundaries.md`](./skill-boundaries.md)
- Testing: [`testing.md`](./testing.md)
- Troubleshooting: [`troubleshooting.md`](./troubleshooting.md)
- Release readiness: [`release-readiness.md`](./release-readiness.md)
