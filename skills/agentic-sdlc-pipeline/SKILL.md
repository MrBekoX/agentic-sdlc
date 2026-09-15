---
name: agentic-sdlc-pipeline
description: This skill should be used first in any language for end-to-end implementation with the full gated SDLC envelope (spec, plan, TDD, tests, security review, final audit, PR readiness). Production-impacting, API contract, auth, payment, or database work overrides focused feature-build/root-cause-fix/safe-refactor/test-authoring routing.
---

# Skill: agentic-sdlc-pipeline (the full-envelope SDLC orchestrator)

> **Argument:** `/agentic-sdlc-pipeline $ARGUMENTS` — if given, that is the target work; otherwise ask. Match the user's language.

The full-envelope entry point for production-impacting work. agentic-sdlc-pipeline is not the default for every feature, fix, test, or refactor request; use the focused skill unless the user asks for end-to-end implementation or the work needs the whole SDLC envelope. agentic-sdlc-pipeline does **not** re-implement the inner work — it **owns the outer envelope** (git lifecycle, Spec & Plan phases, doc-verification, scope-lock, quality gates, task-tracking, parallel dispatch-strategy) and **delegates the implementation core** (TDD → security → refactor → control) to the matching work-flow skill, handing it the approved spec/plan files. It is a **gated, looped, task-tracked** flow: a red gate means go back, not forward.

## Depth contract (proportional — scale rigor to the change)
Every gate is satisfied by the **actual tool call or artifact** named in the runtime invocation contract — the `Skill` call, the validator's exit code, the `spec-plan-draft` `Workflow` (or, in Codex, the embedded author/critic adapter draft) — never by a sentence in the final report asserting it happened. "Security reviewed", "spec drafted", "control done" are prose, not gates. The Spec and Plan phases (steps 4–5) run their full author⇄critic depth with a fresh-context critic where the runtime exposes one; a shallow inline draft is the flagged degraded path, never the equal of the workflow. When a mandated mechanism has nothing to act on in this context, it carries its **one-line deterministic skip note** in its report (the Step-1-symmetric rule) — it is never silently dropped. Scale the envelope, not the evidence standard: Lite Mode still produces the real tool calls for the gates it keeps, and the high-risk surfaces (auth/payment/DB migration/API contract/permissions/user data/token-session/RLS) are always Full.

## Excuse -> check
| Excuse | Check |
|---|---|
| "Security was reviewed." | Show activation plus the completed dispatch/reviewer results required by `security-audit`, or its applicable documented fallback/skip. Loading the skill alone does not perform the review. |
| "The spec is fine, I drafted it inline." | The `spec-plan-draft` workflow (or the Codex author/critic adapter) ran with a fresh-context critic; an inline draft is the flagged degraded path, not the gate. |
| "Validation passed, I read the artifact." | Manual Read does not replace `validate_artifacts.py`; show the validator's zero exit, or the gate stays red. |
| "Context is clear, I explored manually." | Manual Read/Glob/ls does not replace `detect_context.py`; the transcript needs the detector run or its skip note. |
| "The step doesn't apply, I dropped it." | A skipped mechanism carries its one-line deterministic skip note in its report — dropping it silently is a failed gate, not a no-op. |

## No placeholders
No "reviewed / validated / audited / controlled" prose standing in for the tool call it claims. No gated step marked done while its check is red — a red gate means go back, not forward. No mechanism dropped without its deterministic skip note. No shallow inline spec/plan substituted for the author⇄critic phases, and no `Delegation Degraded` note used to quietly downgrade a gate the runtime actually supports — the note names a genuinely missing tool and the smallest safe fallback, nothing more.

## Onion rule (skill architecture)
- **agentic-sdlc-pipeline knows the step-skills and calls them.** Step-skills must **not** call agentic-sdlc-pipeline and stay maximally unaware of each other. A step-skill calls another step-skill only when its own flow genuinely needs it.
- agentic-sdlc-pipeline **delegates the core**, it does not duplicate it. Don't re-write spec/plan/TDD logic here — invoke the work-flow that owns it.

## Runtime invocation contract (eval-enforced)
See `docs/runtime-adapter.md` for the Portable capability matrix and runtime-specific equivalents. Use native runtime tools when they exist. If a capability is unavailable, record `Delegation Degraded: <capability> unavailable`, then perform the smallest safe fallback without weakening deterministic gates.

Claude Code keeps strict transcript gates: `Skill` for delegate skills, `Workflow` for `agentic-sdlc:spec-plan-draft`, and `Agent`/`Task` for fresh-context specialists. A final report saying "security reviewed" or "implementation control done" is not delegation.

Codex, the other supported runtime, satisfies the same behavior through the embedded adapter: draft inside `agentic-sdlc-pipeline`, run a fresh-context critic when the runtime supports it, revise up to two rounds, save the artifact, and run `validate_artifacts.py`. Do not replace pipeline steps 4-5 with standalone `spec-authoring` or `plan-authoring`.

**Runtime root rule:** resolve `<runtime-root>` from the active runtime: `${CLAUDE_PLUGIN_ROOT}` in Claude Code, `${PLUGIN_ROOT}` in Codex. Use runtime-local files under `<runtime-root>/contracts/skills/` and `<runtime-root>/scripts/`; do not require Codex to use Claude-only path examples.

**Call-order guard:** after loading `agentic-sdlc-pipeline`, do not read files, run shell commands, create branches, or write artifacts until you have called `Skill` -> `agentic-sdlc:dispatch-strategy` for the mechanism decision. This call is required even when the likely answer is "small single-file work; main loop is enough".

**Branch checkpoint (both runtimes):** after dispatch, before the first artifact/test/source write in a Git repository, record `git branch --show-current` and `git rev-parse HEAD`. Reuse a suitable work branch or create one when on main/master or detached HEAD, then verify the active branch before writing. Routine local branch creation is within an implementation request unless the user restricts it; no-commit does not mean no-branch. A non-Git workspace gets an explicit skip note. See playbook steps 1–2 for remote/update boundaries.

**No manual substitutes:** these gates are transcript gates, not prose gates. Manual Read/Glob/ls exploration does not replace detect_context.py. Manual review text does not replace validate_artifacts.py. Manual TDD/edit/test work does not replace the selected core work-flow Skill call. Missing one is a failed gate even if the final code and tests are otherwise correct.

**Named workflow only in Claude Code:** Spec and Plan drafts must call the named `Workflow` `agentic-sdlc:spec-plan-draft` when the Workflow tool exists. Do not create ad hoc Workflow scripts for spec or plan drafting; that bypasses the author/critic workflow contract and fails the gate. In Codex, the equivalent gate is the embedded author -> critic -> revise adapter described below, not a `Workflow` call and not a call to `spec-authoring` / `plan-authoring`.

Minimum Full-mode transcript in Claude Code:
1. `Skill` -> `agentic-sdlc:dispatch-strategy` before choosing mechanisms for heavy, independent, or parallel steps.
2. `Bash`/`PowerShell` -> `python3 "<runtime-root>/scripts/detect_context.py" --path <scope>` before replacing exploration decisions with file reads.
3. `Workflow` -> `agentic-sdlc:spec-plan-draft` with `args:{mode:"spec", context:<analysis + scope>}` for step 4.
4. `Bash`/`PowerShell` -> `python3 "<runtime-root>/scripts/validate_artifacts.py" --mode spec --file docs/agentic-sdlc/specs/<work_id>.md` after saving the spec and before the Spec Review gate.
5. `Workflow` -> `agentic-sdlc:spec-plan-draft` with `args:{mode:"plan", context:<approved spec>}` for step 5.
6. `Bash`/`PowerShell` -> `python3 "<runtime-root>/scripts/validate_artifacts.py" --mode plan --file docs/agentic-sdlc/plans/<work_id>.md --spec docs/agentic-sdlc/specs/<work_id>.md --strict` after saving the plan and before the Plan Review gate.
7. `Skill` -> the selected core work-flow (`agentic-sdlc:root-cause-fix`, `agentic-sdlc:feature-build`, `agentic-sdlc:safe-refactor`, or `agentic-sdlc:test-authoring`) with the approved spec and plan paths before writing implementation tests or code.
8. `Skill` -> `agentic-sdlc:security-audit` for each required security pass, followed by its dispatch decision and completed fresh reviewer result(s); retain input scope and findings. Use only the skill's applicable documented fallback or deterministic skip, with its evidence.
9. `Skill` -> `agentic-sdlc:implementation-control` before any final implementation report.
10. `Skill` -> `agentic-sdlc:completion-claim-gate` immediately before the final implementation report or any claim containing done, fixed, passing, verified, ready, complete, works, or commit/push/PR readiness.

Minimum Full-mode evidence in Codex (the other supported runtime):
Before the list, emit `Runtime: Codex`. For each gate below, emit a one-line `Codex Adapter Gate: <gate> ...` marker when the gate is reached. If Codex lacks a native transcript event, say `Delegation Degraded: native Skill transcript events unavailable` and then record the adapter evidence; do not say the step-skill itself was unavailable unless its `SKILL.md` could not be loaded. If skill descriptions are missing from context, discover `<runtime-root>/skills/*/SKILL.md`, read the exact needed skill file, and treat that as activation evidence. In automated smoke evals and normal Codex runs, do not run recursive cleanup deletes for generated caches such as `__pycache__`; leave them or report them in `git status` instead of issuing a delete command.
1. Activate `dispatch-strategy` instructions before heavy, independent, or parallel steps; record `Codex Adapter Gate: dispatch-strategy activated`.
2. Run `python3 "<runtime-root>/scripts/detect_context.py" --path <scope>` before replacing exploration decisions with file reads.
3. Draft the spec inside agentic-sdlc-pipeline using `contracts/skills/02-spec-driven-development.md` and the `spec-plan-author` role instructions; record `Codex Adapter Gate: spec-plan-draft spec author`.
4. Run a fresh-context critic pass using the runtime's subagent/specialist mechanism with `spec-plan-critic` instructions when available; otherwise mark the degraded path and perform the critic pass inline; record `Codex Adapter Gate: spec-plan-draft spec critic`.
5. Save `docs/agentic-sdlc/specs/<work_id>.md`, then run `python3 "<runtime-root>/scripts/validate_artifacts.py" --mode spec --file docs/agentic-sdlc/specs/<work_id>.md`.
6. Draft the plan inside agentic-sdlc-pipeline using `contracts/skills/03-plan-mode.md` and the approved spec; record `Codex Adapter Gate: spec-plan-draft plan author`.
7. Run the same critic/revise adapter for the plan, save `docs/agentic-sdlc/plans/<work_id>.md`, then validate with `--mode plan --spec docs/agentic-sdlc/specs/<work_id>.md --strict`; record `Codex Adapter Gate: spec-plan-draft plan critic`.
8. Activate the selected core work-flow skill instructions (`root-cause-fix`, `feature-build`, `safe-refactor`, or `test-authoring`) before implementation tests or code edits; record `Codex Adapter Gate: <selected-core-skill> activated`.
9. Activate `security-audit`, `implementation-control`, and `completion-claim-gate` at their gates, using runtime subagents where the skill calls for fresh context and the runtime supports them; retain completed reviewer results, not just activation. Record `Codex Adapter Gate: security-audit`, `Codex Adapter Gate: implementation-control`, and `Codex Adapter Gate: completion-claim-gate`.

Do not satisfy these by restating another skill's checklist inline. If a runtime tool is genuinely unavailable, write a `Delegation Degraded` note naming the missing tool and perform the smallest safe fallback; otherwise, missing the tool call is a failed gate.

For an explicit automated smoke eval only, pass `depth:"smoke"` and `maxRevisionRounds:0` to `spec-plan-draft`; normal product work stays full-depth. Smoke mode shortens only the `spec-plan-draft` internals. It does not skip the branch checkpoint, `detect_context.py`, artifact validation, the selected core work-flow Skill call, completed security review, implementation control, or completion-claim-gate. Dependency-install approval boundaries still apply.

## At kickoff (always)
1. **Mode select.** Full vs **Lite Mode** (see playbook). Lite is **forbidden** for auth / payment / security / DB migration / production bug / API contract / permission-role / user-data / token-session / RLS — those are always Full.
2. **Work-type → core work-flow:** bug/broken behavior → `root-cause-fix` · new feature/endpoint → `feature-build` · behavior-preserving restructure → `safe-refactor` · test coverage only → `test-authoring`.
3. **Create the task list.** Use the runtime task tracker (`TodoWrite`, `update_plan`, or equivalent) when available; otherwise write an explicit checklist. Mark a step `in_progress` on entry, `completed` only when its gate passes. **Never** complete a gated step while its gate is red. This is how the human follows progress.
4. **Invoke `dispatch-strategy` through the runtime skill mechanism** for every heavy/independent/parallel step — it picks the mechanism (main loop / sub-agent / dynamic-workflow / agent-team). Never run independent work serially in the main loop.

## Companion discipline skills (auto-trigger; cross-cutting)
These fire on their own triggers across the flow — invoke them with the `Skill` tool, don't inline their logic:
- **`mind-spark`** — before kickoff/Spec when the request's shape isn't settled: explore intent and get a design approved, then feed the agreed intent into the Spec phase (step 4). Skips already-specified work.
- **`completion-claim-gate`** — the per-claim, same-turn evidence gate in front of every "done / fixed / passing / works" claim (steps 10/13, Finalize) and before commit (step 17). Complements `implementation-control`, which audits the whole flow once.
- **`feedback-triage`** — when handling reviewer / PR / CI feedback (e.g. after step 19): verify each item against the code before applying, push back with reasons, no performative agreement.

## Step map (detail → `playbook.md`)

| # | Step | Owner | Gate | ⇉ parallel |
|--|--|--|--|--|
| 1 | Update main | agentic-sdlc-pipeline · git | clean tree | — |
| 2 | Create branch | agentic-sdlc-pipeline · git | off updated main | — |
| 3 | Analyze code & problem — `detect_context.py` selects `explore_mode` | agentic-sdlc-pipeline + `context-analyst` | problem + affected files stated | ⇉ per layer |
| 4 | Spec phase (WHAT) — Claude Code: `spec-plan-draft` workflow; non-Claude runtimes: embedded author/critic adapter | agentic-sdlc-pipeline | testable criteria, no HOW-leak | — |
| — | **Spec Review gate** | agentic-sdlc-pipeline + user | decision points resolved, spec approved | — |
| 5 | Plan phase (HOW) — Claude Code: `spec-plan-draft` workflow; non-Claude runtimes: embedded author/critic adapter | agentic-sdlc-pipeline | each criterion → a task | — |
| — | **Plan Review gate** | agentic-sdlc-pipeline + user | plan approved (contract 03) | — |
| 6 | Context7 doc verification (→ WebSearch fallback if quota out) | agentic-sdlc-pipeline | API/versions confirmed | ⇉ per library |
| 7 | Risk & scope lock | agentic-sdlc-pipeline | files in/out listed | — |
| — | **Goal lock** | runtime goal tool or manual Goal Lock artifact | end-state locked | — |
| 8 | Failing tests (RED) | core work-flow | test seen to fail | — |
| 9 | Implementation (GREEN) | core work-flow | only in-scope files | — |
| 10 | TDD loop test→fix→test | core work-flow · runtime loop tool or manual Loop Iteration artifact | targeted + suite green | — |
| 11 | Security analysis #1 | core work-flow / `security-audit` | no open finding | ⇉ lenses |
| 12 | Refactor | core work-flow / `safe-refactor` | behavior unchanged | — |
| 13 | Re-run all tests | core work-flow | full suite green | — |
| 14 | Security analysis #2 (final diff) | agentic-sdlc-pipeline · `security-audit` | final diff clean | ⇉ lenses |
| 15 | Lint / typecheck / build / secret-scan | agentic-sdlc-pipeline | all gates pass | ⇉ |
| 16 | Git diff review | agentic-sdlc-pipeline · read-only git-safety-check command | only intended files, no secrets | — |
| — | **Implementation control** | `implementation-control` | no critical gap | — |
| 17 | Commit | agentic-sdlc-pipeline · git | user approved | — |
| 18 | Push branch | agentic-sdlc-pipeline · git | user approved, not main | — |
| 19 | Open PR/MR | agentic-sdlc-pipeline · git | template filled | — |
| 20 | Merge after review | agentic-sdlc-pipeline · git | review + local gates green, user approved | — |
| 21 | Re-sync local main | agentic-sdlc-pipeline · git | tree clean | — |

**Parallel (⇉):** dispatch concurrently via `dispatch-strategy`. In Claude Code, large fan-out may use dynamic workflows or agent-teams. In Codex, use subagent fan-out, parallel local tool calls, or native agent mechanisms when available; if those are unavailable, run sequentially and record the degraded path. Examples: step 6 fans docs checks across N libraries, steps 11/14 fan security lenses, step 15 runs lint+typecheck+build+secret-scan in parallel. Gated sequence (4→5→8→9→10) stays strictly ordered.

**Context-fit (skip + document — Step-1-symmetric).** Step 1's "no-op when not a git repo" is the model: a mandated mechanism with nothing to act on in this context is **skipped with a one-line note in its report, never silently dropped** — and the skip decision is deterministic, not a guess. The detector is **`python3 "<runtime-root>/scripts/detect_context.py"`** (stdlib, exits 0):
- **Step 3** runs it first and branches on `explore_mode`: `parallel` (≥2 layers) → explore the layers concurrently; `single` → one `context-analyst`; `greenfield_inline` → no existing code, build the Analysis Summary inline (don't spawn a sub-agent with nothing to read).
- **Step 6** uses `--probe deps`: `stdlib_only` → no external API → Context7 fan-out **n/a** (note it; ≠ the quota-out fallback).
- **Step 15** uses `--probe toolchain`: `absent` → quality gates **N/A** (note it).
- **Step 7** goal lock is a **runtime** check: an active runtime goal already in the session → **don't overwrite it**, lock manually or ask.
- **Step 14** (Security #2): if Step 12 refactor was a no-op, the final diff == Security #1 surface → record that and skip the re-run.
Detail per step → `playbook.md`. The Spec/Plan author⇄critic phases (4–5) are **never** subject to a skip branch.

**Spec & Plan are explicit conversational phases (steps 4–5):** in Claude Code, each runs the `spec-plan-draft` workflow through the `Workflow` tool (`spec-plan-author` drafts ⇄ `spec-plan-critic` adversarially audits → author revises, ≤2 rounds + closing audit) — Spec with `mode:'spec'`, Plan with `mode:'plan'` (the approved spec as its context). In Codex, run the same author/critic discipline inside agentic-sdlc-pipeline with a fresh-context critic when available; do not call standalone `spec-authoring` or `plan-authoring`. A human **Review gate** follows each: resolve the returned decision points and approve before moving on. On approval the spec is saved to **`docs/agentic-sdlc/specs/<work_id>.md`** and the plan to **`docs/agentic-sdlc/plans/<work_id>.md`** (same work_id); the implementation core then follows **these two files faithfully** — drift becomes a new task appended to the plan file, never a silent diff. The approved spec+plan are **not drafted again** inside the delegated work-flow.

**Deterministic artifact gate (machine check under the human Review gate):** before each Review gate, run the validator on the saved file — `python3 "<runtime-root>/scripts/validate_artifacts.py" --mode spec --file docs/agentic-sdlc/specs/<work_id>.md` and, for the plan, `--mode plan --file docs/agentic-sdlc/plans/<work_id>.md --spec docs/agentic-sdlc/specs/<work_id>.md --strict`. A non-zero exit (missing section, untestable criterion, an acceptance criterion mapped to no task, a placeholder/secret) **blocks the gate** until fixed. The validator is **structural only** — it cannot tell whether the spec is *about the requested work*. So at the Spec Review gate **also confirm the spec's topic matches the requested task** (a quick human/semantic check): a mis-carried workflow context (see step 4) can yield a structurally-valid but **off-target** spec that the validator would still pass. (`<runtime-root>/scripts/check_all.py` is an optional manual helper that lints every skill's frontmatter the same `key=value`/exit-1 way; CI runs the deterministic gate on Windows and Linux.)

**Core handoff gate:** after the plan validator passes, invoke the selected core work-flow Skill before any implementation edit or test write. For a feature request, that is `Skill` -> `agentic-sdlc:feature-build`. The core work-flow may then guide RED/GREEN/security/refactor/retest, but loading it is mandatory evidence that agentic-sdlc-pipeline delegated instead of silently inlining the implementation.

## Git gating (steps 1–2, 17–21)
- **Approval-gated.** Commit / push / PR / merge happen **only on explicit user request** (contract 08). Propose, don't auto-run.
- **No-op when not a git repo.** If there is no repo, skip git steps, say so, and offer `git init`. Never operate destructively on `main`/`master`; work on a `fix/* | feature/* | refactor/* | security/* | chore/*` branch.
- Secrets: mask (`***MASKED***`), report only `file:line` + risk; never commit/log real values.

## Loop points
- **Test fail** → analyze → fix → retest (runtime loop tool or manual Loop Iteration artifact, step 10/13).
- **Security finding** → fix → re-check → retest (steps 11/14).
- **Implementation-control gap** → complete the step → re-run control. **If a critical step is missing, do NOT finalize.**

## Red flags — STOP
- Coding before the spec/plan files exist · diverging from `docs/agentic-sdlc/specs`/`docs/agentic-sdlc/plans` without updating them · marking a gated step done while red · "works/passed/fixed" without real output · scope creep (a new finding is a **new task** in the plan file, not a bigger diff) · committing/pushing without explicit approval · inventing an API without Context7 · running independent work serially instead of delegating.

## Finalize
Only when: code done · relevant + full tests run with output shown · both security passes done · lint/typecheck/build + secret-scan reported · diff reviewed · `implementation-control` clean. Then invoke `completion-claim-gate` with the exact evidence you will claim, and only after that produce the **Final Implementation Report** (`templates.md`). No evidence → no "done"; report the honest current state instead.

## Artifact layout & per-package evidence
Work-package artifacts resolve in two layouts: the legacy flat `docs/agentic-sdlc/{specs,plans}/<id>.md` (back-compat, unchanged) and the per-package canonical `docs/agentic-sdlc/<slug>/{spec,plan,evidence}/<work_id>.md`, where `<slug>` is lowercase kebab-case `^[a-z0-9][a-z0-9-]{0,63}$` and never a reserved name (`specs`, `plans`, `evidence`, `notes`, `spec`, `plan`). Per-package plan change-detection runs as a filesystem scan, not a `git status` query; new generated plans can be git-ignored, so the resolver scans the filesystem; published plugin documentation is tracked separately.

On **Finalize**, persist the Final Implementation Report to `docs/agentic-sdlc/<slug>/evidence/<work_id>.md` — **per-package only** (flat packages get no evidence), using the slug emitted by `resolve_work_package.py` (never re-derived). A re-run **overwrites** this single canonical file in place (last run wins; no per-run/timestamp suffix). Evidence is git-ignored and has **no validator** — it never gates resolution. This write is performed by the **main pipeline finalize step**, not the read-only `implementation-auditor` sub-agent.

**References:** step detail + Lite Mode → `playbook.md` · artifact/report templates → `templates.md`.
