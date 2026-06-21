# AGENTIC-SDLC Plugin Reference

> Version: `0.3.0`. This is the component-by-component reference. For runtime-specific behavior, start with [Claude Code](../.claude-plugin/README.md) or [Codex](../.codex-plugin/README.md).

AGENTIC-SDLC is a local development plugin for **Claude Code** and **Codex**. It routes each prompt to the smallest sufficient skill and reserves the full SDLC envelope for work that actually needs it.

## Supported Runtime Scope

| Runtime | Status | Runtime notes |
|---|---|---|
| Claude Code | Supported | Native `Skill`, `Workflow`, `Agent`/`Task`, commands, and full hook wiring. See [`../.claude-plugin/README.md`](../.claude-plugin/README.md). |
| Codex | Supported | Shared skills, Codex manifest metadata, personal-marketplace install flow, and embedded pipeline adapter. See [`../.codex-plugin/README.md`](../.codex-plugin/README.md). |
| OpenCode / Kimi Code / GLM-style harnesses | Deferred adapter targets | Adapter concepts may be documented in [`runtime-adapter.md`](./runtime-adapter.md), but these are not supported release targets for `0.3.0`. |

## Installation Model

| File | Runtime | Purpose |
|---|---|---|
| `.claude-plugin/plugin.json` | Claude Code | Plugin metadata. |
| `.claude-plugin/marketplace.json` | Claude Code | Local marketplace source; the repo root is the source. |
| `.codex-plugin/plugin.json` | Codex | Codex plugin metadata, `skills`, and `interface` block. |
| `hooks/hooks-claude.json` | Claude Code | `PreToolUse`, `PostToolUse`, `SessionStart`, and `Stop` wiring. |
| `hooks/hooks-codex.json` | Codex | `SessionStart` bootstrap wiring (declared in `.codex-plugin/plugin.json`), subject to Codex hook review/trust. |

Skills live in root `skills/`, not in `.claude/skills/` or `.codex/skills/`. Runtime root variables are:

| Runtime | Plugin root variable |
|---|---|
| Claude Code | `${CLAUDE_PLUGIN_ROOT}` |
| Codex | `${PLUGIN_ROOT}` |

## Layered Components

| Layer | Responsibility |
|---|---|
| `skills/` | Runnable procedures: `SKILL.md` plus optional `scripts/`, `references/`, and `assets/`. |
| `contracts/skills/` | Durable behavior rules: context-first, spec, plan, testing, security, git safety, documentation, collaboration. |
| `agents/` | Read-only role contracts used for fresh-context analysis, review, audit, and author/critic passes. |
| `workflows/` | Claude Code dynamic workflow scripts. Codex does not run these directly. |
| `hooks/` | Deterministic guard scripts and runtime hook wiring. |
| `commands/` | Manual slash-command definitions such as `/git-safety-check`. |
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

Gate skills feed the pipeline at control points: `dispatch-strategy`, `security-audit`, `implementasyon-control`, and `completion-claim-gate`.

`spec-authoring` and `plan-authoring` are standalone prompt-level skills. They are not internal pipeline substeps.

## Runtime Split For Spec And Plan

| Runtime | Pipeline spec/plan mechanism |
|---|---|
| Claude Code | Uses the named Workflow `agentic-sdlc:spec-plan-draft` for both spec and plan phases. |
| Codex | Uses the embedded author -> critic -> revise adapter inside `agentic-sdlc-pipeline`; validates saved artifacts with `validate_artifacts.py`. |

The pipeline must not call standalone `spec-authoring` or `plan-authoring` for its internal steps 4-5.

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
| `implementasyon-control` | Pre-final flow audit. |
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
| `scan-commit.mjs` | `PreToolUse` for `git commit*` | Not wired | Blocks high-confidence secrets in added diff lines. |
| `branch-guard.mjs` | `PreToolUse` for `git commit*` and `git push*` | Not wired | Warns on protected branches; can block with `AGENTIC_BRANCH_GUARD_BLOCK=true`. |
| `destructive-command-guard.mjs` | `PreToolUse` for shell commands | Not wired | Blocks deterministic destructive commands. |
| `completion-claim-guard.mjs` | `Stop` | Not wired | Warns, or blocks with `AGENTIC_COMPLETION_GATE_BLOCK=true`, when final completion claims skip `completion-claim-gate`. |
| `secret-patterns.mjs` | Shared library | Shared library | Secret-pattern scanner used by hook scripts. |

Judgment-based gates remain in skills and contracts. A script cannot decide whether a model understood test output, followed a spec, or completed a security review.

## 11. Deterministic scripts (14)

| Script | Purpose |
|---|---|
| `check_all.py` | Skill frontmatter and validator tests. |
| `validate_artifacts.py` | Spec/plan structural validation and secret/placeholder scan. |
| `resolve_work_package.py` | Deterministically resolves the spec/plan pair for implementation audits. |
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

- `0.3.0` supports Claude Code and Codex only.
- Codex hook wiring is declared via `.codex-plugin/plugin.json` -> `hooks/hooks-codex.json`; non-managed plugin-bundled command hooks require Codex review/trust before they run. It is deliberately not named `hooks/hooks.json`, which Claude Code would auto-load with an undefined `${PLUGIN_ROOT}`.
- Codex trigger evals are classifier evidence, not Claude-style `Skill` event evidence.
- Hooks fail open where necessary so a hook fault does not break a session.
- `validate_artifacts.py` is structural; it cannot prove that a spec is semantically about the requested task.
- Live routing is model-dependent and must be evidenced per runtime, model, and run.

## Cross-References

- Project overview: [`../README.md`](../README.md)
- Claude runtime README: [`../.claude-plugin/README.md`](../.claude-plugin/README.md)
- Codex runtime README: [`../.codex-plugin/README.md`](../.codex-plugin/README.md)
- Skill boundaries: [`skill-boundaries.md`](./skill-boundaries.md)
- Testing: [`testing.md`](./testing.md)
- Troubleshooting: [`troubleshooting.md`](./troubleshooting.md)
- Release readiness: [`release-readiness.md`](./release-readiness.md)
