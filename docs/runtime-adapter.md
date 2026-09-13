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
| Deterministic hook guardrails | `hooks/hooks-claude.json`: command/write guards, bootstrap, and Stop checks | `hooks/hooks-codex.json`: command/write guards, bootstrap, and Codex Stop adapters after review/trust | run the explicit checks; record missing native enforcement |
| Active-flow evidence enforcement | Skill/tool, artifact, and command evidence from Claude transcripts | In-session artifact writes, recognized source edits, and recorded test commands; see limits below | validators, real test output, and procedure review |
| Runtime plugin root | `${CLAUDE_PLUGIN_ROOT}` | `${PLUGIN_ROOT}` | current repo root |

> Other harnesses (OpenCode, Kimi, GLM-style) are future/unsupported work, not release targets.

## Hook wiring and runtime boundaries

| Purpose | Claude Code | Codex |
|---|---|---|
| Commit secrets, destructive commands, branch policy | `scan-commit.mjs`, `destructive-command-guard.mjs`, `branch-guard.mjs`; `Bash` / `PowerShell` | Same handlers; `Bash` also matches native shell/unified-exec commands |
| Write secret scan | `scan-write.mjs`: PostToolUse advisory for `Write` / `Edit` / `MultiEdit`; VERIFY before using this Claude field-shape handler on Codex | `scan-write-codex.mjs`: PreToolUse denial for recognized literal `Bash` / `apply_patch` writes |
| Source-edit ordering | `flow-order-guard.mjs`: warns by default; VERIFY before using this Claude field-shape handler on Codex | `flow-order-guard-codex.mjs`: default silent, opt-in denial; artifact or before-edit test evidence |
| Completion claim | `completion-claim-guard.mjs`: looks for a Skill invocation; VERIFY before using this Claude transcript reader on Codex | `completion-claim-guard-codex.mjs`: looks for the sentinel in the final assistant message through `codex-rollout.mjs` |
| Active-flow completion | `flow-step-guard.mjs`: Claude Skill/tool evidence; VERIFY before using this Claude transcript reader on Codex | `flow-step-guard-codex.mjs` and `codex-flow-evidence.mjs`: session-scoped artifact/command evidence |
| Working-tree secret detection | `worktree-scan.mjs`: Stop scan of changed/untracked bytes | Not wired; VERIFY this handler's installed-runtime behavior before porting |

The Claude command guards match both shells without a subcommand-level `if` filter; each handler resolves Git aliases and self-gates. Codex receives shell/patch content in `tool_input.command`, not Claude's `file_path` / `new_string` fields. Paths use the runtime root above; executable commands follow that runtime's shell contract.

The Codex flow-order switch `AGENTIC_FLOW_ORDER_BLOCK` and flow-step switch `AGENTIC_FLOW_GATE_BLOCK` are independent: the first enables pre-edit denial; the second escalates the Stop advisory. On Claude, `AGENTIC_FLOW_GATE_BLOCK` controls both flow guards. `AGENTIC_COMPLETION_GATE_BLOCK` controls completion-claim blocking on both runtimes. `AGENTIC_BRANCH_GUARD_BLOCK` and `AGENTIC_WORKTREE_SCAN_BLOCK` control their separate guards. A wired guard can still be advisory, disabled by default, or skipped while trust is pending.

## Codex flow evidence and limits

`flow-order-guard-codex.mjs` allows a recognized source edit after either a same-work-id spec/plan pair written in this rollout and validated strictly, or a recorded invocation of a recognized test runner. A RED run counts for ordering: the pre-edit check deliberately does not require a successful test result. On-disk-only artifacts do not satisfy the pair; a single patch that bundles artifacts and source is not prior evidence. An unreadable rollout or unavailable validator fails open; a readable rollout with missing/unresolvable required artifacts can deny.

`flow-step-guard-codex.mjs` activates only when this rollout records a spec/plan write. It attaches spec/plan/test obligations only when a non-test source edit is also observed. Artifact checks use strict validation and same-work-id pairing. Test evidence requires a recognized runner invocation; `echo pytest` does not qualify. A correlated exit code 0 satisfies the result check; a nonzero exit does not. A missing exit code fails open to invocation-only evidence. Correlation uses `call_id`, first taking the recorded `function_call_output` exit line and then the structured `exec_command_end` fallback.

Native Codex 0.154.0 WSL records successful patches as `custom_tool_call` / `custom_tool_call_output`, and shell exits as `Process exited with code N`. The reader retains historical carriers and accepts these current ones. It reads only leading native metadata before `Output:` or unknown text; tool-output or denial-echo headers are not exit evidence. A current custom patch needs its own correlated exit 0 and a success marker at the start of the actual output body. Missing, refused, failed, mismatched-type, or conflicting-call records do not count as successful patch writes. The captured fixture and mutations in `tests/test_codex_current_rollout.py` pin this boundary.

These checks do not establish test quality or freshness after the latest source edit: they scan the whole rollout, do not bind a test to one work id, and do not require a test-summary signature. A successful `pytest --version` can qualify. The parser also cannot guarantee that a runner-shaped segment in a compound shell command actually executed. Run and inspect the real final verification separately. The current allowlist includes `make test`, `npm test` / `npm run test`, yarn/pnpm test forms, `tox`, and `nox`, alongside direct Python/JS/Go/Rust/JVM runners; arbitrary shell scripts and unrecognized wrappers remain outside the invocation recognizer.

Flow evidence recognizes `apply_patch` targets, ordinary `>` / `>>` targets, and operands of `sed -i` and `tee`, including multi-file writes. The current-edit recognizer respects quotes, heredocs, expansion-dependent targets, and the actual tool name. The prior-write reader is broader and can over-approximate writes. Unrecognized copy/encoding commands without a recognized redirect, expansion-derived targets, source deletes, and extended/fd redirects (`&>`, `&>>`, `>|`, `N>`, `>&N`) remain bounded gaps. Recognizing a target for flow evidence does not mean its content is covered by the secret scanner: that scanner scans only literal added content from patch/printf/echo/heredoc forms. Arbitrary tee/base64/command-substitution output is not checkable by this layer and remains fail-open.

Other limits remain material:

- The rollout reader has an 8 MiB ceiling; literal write extraction has a 512 KiB bound. Missing, unreadable, or oversized inputs can suppress enforcement.
- Artifact-less refactors and implementation resumed with only prior-session artifacts do not activate the Codex flow-step backstop. `Skill` / `Workflow` / `Agent`-only security, control, dispatch, and core steps are not observed by this adapter.
- Completion-claim patterns are narrow and English-only. The sentinel must appear in the final assistant message; prior quoted/user messages do not count. A model can still repeat the marker without good evidence, so its presence is not proof of correctness.
- Stop adapters check `stop_hook_active` to avoid repeated continuation. They use payload `cwd`, falling back to the hook process directory; unresolved artifact locations can prevent useful evidence. Missing/unreadable inputs fail open, but malformed JSONL lines are skipped: a still-readable partial rollout can lack evidence and trigger a flow-order denial.

## Current binary and historical hook evidence

The current binary observed on 2026-09-12 is Codex CLI **0.154.0**; Claude Code is **2.1.269**. Historical Codex CLI **0.142.0** probes established blocking PreToolUse, Stop continuation, and the `patch_apply_end` carrier. Current native probes now establish startup/resume/manual-compact context, allowed and refused tool effects, production Stop blocking, continued execution, and delivered `stop_hook_active=true`. The Claude chain ran on Windows; the successful Codex read/write chain ran in WSL Ubuntu after the Windows isolated fixture's sandbox permissions prevented allowed execution. They use Sonnet 5/Low and GPT-5.3-Codex-Spark/Low respectively. Claude exposes the exact model in messages/modelUsage but does not echo response-side effective effort; Low is verified as CLI and child-environment configuration. Codex records both model and Low in native turn_context.

Native captures and snapshot identities live under `tests/artifacts/dual-runtime-remediation/claude-lifecycle/` and `codex-lifecycle-wsl/run-02/`. The WSL capture exposed the two current reader gaps above; the corrected reader is replayed against that unchanged capture and regression-tested separately. These bounded lifecycle results are not broad skill-trigger, procedure-compliance, or future-version guarantees. Model-access preflights and direct-handler replays remain distinct from native lifecycle evidence.

Current [Codex hook documentation](https://learn.chatgpt.com/docs/hooks) describes plugin hook discovery, hash-based review/trust, startup/resume/clear/compact context, pre-tool denial, and Stop continuation. `transcript_path` remains an unstable convenience, not a stable hook interface. The retired `plugin_hooks` feature flag alone does not establish delivery or removal of that support. Check the installed plugin, trust state, real events, and effects. [Claude's hook reference](https://code.claude.com/docs/en/hooks) describes the corresponding events; its SessionStart also supports `fork`. A direct script invocation or trust-bypass run cannot prove the ordinary installed trust lifecycle.

### Portable manifest discovery gap on 0.154.0

An isolated current-binary comparison installed the same plugin payload with and without root `plugin.json`. The portable path exposed all 16 skills but zero hooks in both `plugin/read` and `hooks/list`; the legacy-only path exposed the same 16 skills and eight hooks, all initially `untrusted`. Neither discovery response reported a plugin/hook load warning or error. This difference occurs before trust review. Local evidence is under `tests/artifacts/dual-runtime-remediation/hook-delivery-investigation/{portable,legacy}/results.json`.

The pinned [0.154.0 loader](https://github.com/openai/codex/blob/6b9826e3aa83b1a5947db50f4332cb9c65f1b340/codex-rs/core-plugins/src/loader.rs#L954-L964) returns no hooks for the portable `AgentPlugin` branch, despite the public packaging documentation describing portable lifecycle hooks. Retain the legacy `.codex-plugin/plugin.json` installation path for this binary; do not promote a portable root manifest merely because its schema and skill inventory pass. Successful hook discovery does not prove hook execution, trusted delivery, or model compliance; those require the separate lifecycle probes above. Re-evaluate this restriction against a newer binary before adopting the portable candidate.

## Coexistence and session restoration

Select one process owner before focused routing: explicit user selection wins; otherwise preserve the current phase's owner across resume/compact; a new house entry defaults to AGENTIC-SDLC. Bootstrap, router, and focused design guidance carry the same rule. Namespacing identifies a skill but does not select a process owner. Security hooks remain independent of that choice.

Before substantive phase content, load the selected owner's actual instructions. After resume, compaction, or a supplied summary, reload the selected procedure and continue from saved progress without repeating completed approvals; reuse an already-loaded body only in uninterrupted context. `mind-spark/SKILL.md` contains only the entry/loading gate. Its complete house design procedure is in `references/design-process.md` and is loaded only for an AGENTIC-SDLC-owned design phase; foreign-owned entry loads that owner's skill instead. This boundary was introduced after a live direct-entry failure, and its current behavior is measured separately from lifecycle delivery.

The reference snapshot [Superpowers b36e0829c6d0140e93cfef2ca599b1b07d4a7797](https://github.com/obra/superpowers/tree/b36e0829c6d0140e93cfef2ca599b1b07d4a7797) has a Claude SessionStart matcher `startup|clear|compact`, omitting `resume`; the house Claude hook has no matcher restriction. Its Codex manifest explicitly sets `"hooks": {}`, so that snapshot contributes no Codex SessionStart hook despite the physical default hook file. Thus the Claude bootstrap overlap and resume asymmetry differ from Codex's discoverable-skill overlap. Preserve the selected owner in conversation context; measure restoration with real resume/compact transcripts rather than assuming hook order resolves the conflict.

## Evidence Rule

Codex's native `config/batchWrite` trust operation was exercised in an isolated temporary profile using the exact `hooks.state` key/hash protocol used by its `/hooks` UI. The immutable WSL lifecycle records `hooks-before-trust.json`, `hooks-after-trust.json`, and `hooks-after-restart.json` under `tests/artifacts/dual-runtime-remediation/codex-lifecycle-wsl/run-02/` show all eight production hooks and three silent probe observers moving from untrusted to trusted, with trust retained after app-server restart. Its native event streams and filesystem receipts separately establish execution. Earlier top-level no-model inspection files are historical diagnostics: creating an idle thread alone produced no hook-completion notification and does not prove execution. No personal profile configuration or credential contents were copied into these artifacts.

If a native runtime tool exists, use it. If it does not exist, record `Delegation Degraded: <capability> unavailable`, perform the smallest safe fallback, and preserve deterministic gates such as `detect_context.py`, `validate_artifacts.py`, real test output, diff review, and secret scan.

Do not claim a deferred runtime is supported because this matrix names it. Support requires manifest/runtime wiring, docs, tests, and live evidence.

For Codex procedure transcripts, emit `Runtime: Codex` once and a `Codex Adapter Gate: <gate>` marker at each adapted Skill/Workflow gate. `Delegation Degraded: native Skill transcript events unavailable` means the transcript event is unavailable; the step still has to run through activated/read skill instructions plus deterministic command/artifact evidence. Do not run recursive cleanup deletes for generated caches such as `__pycache__` during Codex pipeline/eval runs; report them instead of adding permission-denial noise.

## Pipeline Spec/Plan Rule

`agentic-sdlc-pipeline` owns internal Spec and Plan phases. Claude Code uses `spec-plan-draft`; Codex uses the embedded author -> critic -> revise adapter. The pipeline must not call standalone `spec-authoring` or `plan-authoring` for its internal steps 4-5.

For deferred adapter targets, the only acceptable documented fallback is the same author -> critic -> revise discipline plus saved artifacts and `validate_artifacts.py` evidence.

## Artifact Layouts And Per-Package Evidence

Work-package artifacts resolve in two layouts on both runtimes: the legacy flat `docs/agentic-sdlc/{specs,plans}/<id>.md` (back-compat, unchanged) and the per-package canonical `docs/agentic-sdlc/<slug>/{spec,plan,evidence}/<work_id>.md`, where `<slug>` is lowercase kebab-case `^[a-z0-9][a-z0-9-]{0,63}$` and never a reserved name (`specs`, `plans`, `evidence`, `notes`, `spec`, `plan`).

Current Codex switch semantics (0.4.3): `AGENTIC_FLOW_GATE_BLOCK` controls only the flow-step Stop
backstop; `AGENTIC_FLOW_ORDER_BLOCK` controls only `flow-order-guard-codex.mjs`. They are independent.
The flow-order guard resolves both flat and canonical per-package spec/plan layouts through the same
artifact lookup used by the Codex Stop evidence engine. Any older “shared-env coupling” wording in
historical design material is superseded by this runtime contract.

Per-package evidence persists to `docs/agentic-sdlc/<slug>/evidence/<work_id>.md` — per-package only (flat packages get no evidence), overwritten in place per run (single canonical file, last run wins), git-ignored, and with no validator (it never gates resolution; the flow guards on neither runtime activate on an evidence write). That evidence write is performed by the main pipeline finalize step, not the read-only `implementation-auditor` sub-agent.

Per-package plan change-detection runs as a filesystem scan, not a `git status` query: new generated plans can be git-ignored, so the resolver scans the filesystem; published plugin documentation is tracked separately.
