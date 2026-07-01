# Hooks - Deterministic Guards + Conceptual Checklists

Two kinds of guard live here:

1. **Real hooks** - executable `.mjs` scripts wired by a runtime hook config.
2. **Conceptual hooks** - judgment-based checkpoints enforced by skills and contracts, not scripts.

## Runtime Wiring

| Runtime | Config | Wired events in this release |
|---|---|---|
| Claude Code | `hooks/hooks-claude.json` via `.claude-plugin/plugin.json` | `PreToolUse`, `PostToolUse`, `SessionStart`, `Stop` |
| Codex | `hooks/hooks-codex.json` declared in `.codex-plugin/plugin.json`, after Codex hook review/trust | `SessionStart` + `PreToolUse` (`Bash` command guards: `scan-commit.mjs`, `destructive-command-guard.mjs`, `branch-guard.mjs`; `Bash`+`apply_patch` pre-write secret guard: `scan-write-codex.mjs`, then env-gated flow-order pre-gate: `flow-order-guard-codex.mjs`) + `Stop` (completion-claim marker backstop: `completion-claim-guard-codex.mjs`; evidence-only flow-step backstop: `flow-step-guard-codex.mjs`) |

The hook scripts are shared in this directory, but being present as a script is not the same as being wired by every runtime.

Claude Code paths resolve through `${CLAUDE_PLUGIN_ROOT}`. Codex paths resolve through `${PLUGIN_ROOT}`.

## Real Hook Scripts

| Script | Claude Code event | Codex event | Behavior |
|---|---|---|---|
| `session-start.mjs` | `SessionStart` | Not wired | Injects git status summary and Claude Code Skill-tool bootstrap reminder. |
| `session-start-codex.mjs` | Not wired | `SessionStart` | Injects git status summary and Codex-specific AGENTIC-SDLC bootstrap reminder. |
| `scan-write.mjs` | `PostToolUse` (`Write`/`Edit`/`MultiEdit`) | Not wired | Scans newly written text for secrets; warns only. (Claude `Write`/`Edit` field shape; superseded on Codex by `scan-write-codex.mjs`.) |
| `scan-write-codex.mjs` | Not wired | `PreToolUse` (`Bash`/`apply_patch`) | Codex-native pre-write secret guard: extracts the literal added content of recognized write forms (apply_patch V4A; `printf`/`echo` `>`/`>>`; literal heredocs) and DENIES a high-confidence secret before the write. Bounded backstop — NOT covered (fail-open): pipe/`tee`/`base64`/command-substitution and `$VAR`/`${...}`/`$(...)` expansion. |
| `scan-commit.mjs` | `PreToolUse` (`git commit*`) | `PreToolUse` (`Bash`) | Scans added diff lines for high-confidence secrets; blocks commit. Self-gates to `git commit` internally, so Codex wires it without an `if` clause. |
| `branch-guard.mjs` | `PreToolUse` (`git commit*` / `git push*`) | `PreToolUse` (`Bash`) | Warns on `main`/`master`; blocks when `AGENTIC_BRANCH_GUARD_BLOCK=true`; flags force-push. Self-gates to `git commit`/`push` internally. |
| `destructive-command-guard.mjs` | `PreToolUse` shell command | `PreToolUse` (`Bash`) | Blocks deterministic destructive commands such as `git reset --hard`, forceful `git clean`, recursive `rm` including wrapper/path forms, and `Remove-Item -Recurse` including common aliases/wrappers. |
| `flow-order-guard.mjs` | `PreToolUse` (`Write`/`Edit`/`MultiEdit`) | Not wired (Claude file; mechanism superseded on Codex by `flow-order-guard-codex.mjs`) | For active flows, checks current-turn pre-edit evidence before source edits; warns by default and denies when `AGENTIC_FLOW_GATE_BLOCK=true`. |
| `flow-order-guard-codex.mjs` | Not wired | `PreToolUse` (`Bash`/`apply_patch`) | Codex env-gated **opt-in** pre-edit ordering gate (AP2c): **default silent**, and only under its own `AGENTIC_FLOW_ORDER_BLOCK` (independent of the flow-step `AGENTIC_FLOW_GATE_BLOCK`) does it DENY a production-source edit attempted before THIS session produced a validated spec AND matching plan (same work id, both written this session via apply_patch, each re-validated strict). Deliberately does NOT reuse `deriveFlowEvidence` (which would accept a committed-only partner — DP-EVID): it derives the in-session spec-write and plan-write sets separately. **(B5 write-form symmetry)** the pending source edit it gates is recognized across apply_patch, `printf`/`echo` `>`/`>>` and heredocs, AND in-place `sed -i`, `tee`, and any command's plain `>`/`>>` redirect — matched precisely (quote/heredoc/`$`-expansion-aware, Bash-only, never over patch text), so choosing `sed`/`tee`/a non-`printf` redirect instead of a patch no longer bypasses the gate, and a multi-file `sed -i`/`tee` now surfaces every operand (not just the last/first). Deferred residuals (fail-open): `cat`/`dd` copy, `base64`, `$`-expansion targets, the `&>`/`&>>`/`>|`/`N>`/`>&N` redirect family, and a Bash command whose text literally contains `*** Begin Patch`. Fixed-preamble + bracketed `{spec, plan}` deny reason, no rollout/command/path/work-id bytes. Fail-open on unreadable rollout / malformed input / unrecognized edit form; an unresolvable artifact root denies (BR4b). |
| `completion-claim-guard.mjs` | `Stop` | Not wired (Claude file; mechanism superseded on Codex by `completion-claim-guard-codex.mjs`) | Warns when a final completion claim appears without `completion-claim-gate`; blocks when `AGENTIC_COMPLETION_GATE_BLOCK=true`. |
| `completion-claim-guard-codex.mjs` | Not wired | `Stop` | Codex completion-claim backstop: on a final completion claim without the `completion-claim-gate` **sentinel marker** in the rollout, emits a non-blocking advisory by default or blocks when `AGENTIC_COMPLETION_GATE_BLOCK=true`. Same env switch + copied claim/negation patterns as the Claude guard. |
| `flow-step-guard.mjs` | `Stop` | Not wired (Claude file; mechanism superseded on Codex by `flow-step-guard-codex.mjs`) | Re-derives required active-flow evidence from validated artifacts, real tool calls, and commands; warns by default and blocks missing `stop:block` steps when `AGENTIC_FLOW_GATE_BLOCK=true`. |
| `flow-step-guard-codex.mjs` | Not wired | `Stop` | Codex evidence-only flow-step backstop: re-derives active-flow evidence from THIS rollout's in-session spec/plan writes (session-scoped — committed prior-session artifacts never activate a flow), recorded commands, and patch edit targets; warns by default and blocks missing `stop:block` steps when `AGENTIC_FLOW_GATE_BLOCK=true`. Fail-open; output names only step ids, never rollout bytes/work-id. |
| `flow-evidence.mjs` | Shared library | Shared library | Evidence engine used by `flow-order-guard.mjs` and `flow-step-guard.mjs`. |
| `codex-flow-evidence.mjs` | Not wired | Shared library | Pure session-scoped flow-evidence derivation for `flow-step-guard-codex.mjs`: active-flow by in-session artifact write, same-work-id spec/plan pairing (no fallback), `validate_artifacts.py --strict` subprocess, fail-open. Reuses the byte-locked `flow-evidence.mjs` read-only helpers (`loadRequirements`/`blockFlag`/`isSourceFile`). |
| `secret-patterns.mjs` | Shared library | Shared library | Secret-pattern scanner used by the scan hooks. |
| `codex-write-signal.mjs` | Not wired | Shared library | Pure write-content extractor (apply_patch V4A + bounded literal Bash write forms) used by `scan-write-codex.mjs`. No shell, no I/O. |
| `codex-rollout.mjs` | Not wired | Shared library | Pure Codex rollout reader (final assistant message + completion-claim-gate sentinel-marker presence) used by `completion-claim-guard-codex.mjs`. `node:fs` read only; no shell, no eval. |

`flow-requirements.json` is the shared source for active-flow step definitions and source-file extensions. The live flow hooks read it at runtime, and `tests/test_flow_requirements.py` validates that its skill, workflow, agent, and validator references resolve.

All scripts are generic: no shell for git operations, path-normalized skip lists, no embedded real secrets, and fail-open behavior on hook errors.

## Conceptual Hooks

These checkpoints require model judgment, so they live as flow gates in skills and contracts.

| Conceptual hook | Enforced by |
|---|---|
| `pre-edit-context-check` | contracts `01-context-first`, `03-plan-mode`; early steps in `root-cause-fix` and `feature-build`. |
| `post-edit-diff-check` | contracts `04-code-quality`, `08-git-safety`; `code-quality-review`; diff review steps. |
| `pre-test-command-check` | contract `05-testing`; `test-authoring`. |
| `post-test-result-check` | contract `05-testing`; TDD loops in implementation skills. |
| `security-sensitive-change-check` | contract `06-security`; `security-audit`. |
| `pre-git-operation-check` | contract `08-git-safety`; `/git-safety-check`; `scan-commit.mjs`; `branch-guard.mjs`. |
| `flow-step-evidence-check` | `flow-order-guard.mjs`; `flow-step-guard.mjs`; `hooks/flow-requirements.json`; implementation skills and `implementasyon-control`. |
| `final-response-verification` | `implementasyon-control` plus `completion-claim-gate`; Claude `completion-claim-guard.mjs` is only a deterministic backstop. |

## Artifact Layouts And Per-Package Evidence

Work-package artifacts resolve in two layouts: the legacy flat `docs/agentic-sdlc/{specs,plans}/<id>.md` (back-compat, unchanged) and the per-package canonical `docs/agentic-sdlc/<slug>/{spec,plan,evidence}/<work_id>.md`, where `<slug>` is lowercase kebab-case `^[a-z0-9][a-z0-9-]{0,63}$` and never a reserved name (`specs`, `plans`, `evidence`, `notes`, `spec`, `plan`).

Per-package evidence persists to `docs/agentic-sdlc/<slug>/evidence/<work_id>.md` — per-package only (flat packages get no evidence), overwritten in place per run (single canonical file, last run wins), git-ignored, and with no validator (it never gates resolution, and no flow guard activates on an evidence write). That evidence write is performed by the main pipeline finalize step, not the read-only `implementation-auditor` sub-agent.

Per-package plan change-detection runs as a filesystem scan, not a `git status` query: the whole `docs/` tree is git-ignored, so `git status` never reports new per-package plans and the resolver scans the filesystem instead.

## Adding Or Disabling Hooks

- Add new scripts under the matching event in `hooks/hooks-claude.json` for Claude Code or `hooks/hooks-codex.json` for Codex when that runtime supports the event.
- Use runtime hook controls to browse or temporarily disable hooks.
- Keep scripts deterministic. Checks that need judgment belong in skills/contracts.
