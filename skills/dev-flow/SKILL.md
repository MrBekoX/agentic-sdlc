---
name: dev-flow
description: Use when implementing any production-impacting code change end-to-end: bug fix, new feature, refactor, security fix, migration, API contract, auth, payment, permission, user-data, token/session, or database work that needs the full gated SDLC rather than a small local edit.
user-invocable: true
argument-hint: "<what to build or fix>"
---

# Skill: dev-flow (the Onion-center SDLC orchestrator)

> **Argument:** `/dev-flow $ARGUMENTS` — if given, that is the target work; otherwise ask. **Reply in Turkish.**

The single entry point for a production-impacting code change. dev-flow does **not** re-implement the inner work — it **owns the outer envelope** (git lifecycle, Spec & Plan phases, doc-verification, scope-lock, quality gates, task-tracking, parallel orchestration) and **delegates the implementation core** (TDD → security → refactor → control) to the matching work-flow skill, handing it the approved spec/plan files. It is a **gated, looped, task-tracked** flow: a red gate means go back, not forward.

## Onion rule (skill architecture)
- **dev-flow knows the step-skills and calls them.** Step-skills must **not** call dev-flow and stay maximally unaware of each other. A step-skill calls another step-skill only when its own flow genuinely needs it.
- dev-flow **delegates the core**, it does not duplicate it. Don't re-write spec/plan/TDD logic here — invoke the work-flow that owns it.

## Runtime invocation contract (eval-enforced)
When Claude Code exposes `Skill` and `Workflow` tools, dev-flow must produce explicit tool calls for its delegates. A final report saying "security reviewed" or "implementation control done" is not delegation.

**Call-order guard:** after loading `dev-flow`, do not read files, run shell commands, create branches, or write artifacts until you have called `Skill` -> `agentic-sdlc:orchestration` for the mechanism decision. This call is required even when the likely answer is "small single-file work; main loop is enough".

**No manual substitutes:** these gates are transcript gates, not prose gates. Manual Read/Glob/ls exploration does not replace detect_context.py. Manual review text does not replace validate_artifacts.py. Manual TDD/edit/test work does not replace the selected core work-flow Skill call. Missing one is a failed gate even if the final code and tests are otherwise correct.

**Named workflow only:** Spec and Plan drafts must call the named `Workflow` `agentic-sdlc:spec-plan-draft`. Do not create ad hoc Workflow scripts for spec or plan drafting; that bypasses the author/critic workflow contract and fails the gate.

Minimum Full-mode transcript:
1. `Skill` -> `agentic-sdlc:orchestration` before choosing mechanisms for heavy, independent, or parallel steps.
2. `Bash`/`PowerShell` -> `python "${CLAUDE_PLUGIN_ROOT}/scripts/detect_context.py" --path <scope>` before replacing exploration decisions with file reads.
3. `Workflow` -> `agentic-sdlc:spec-plan-draft` with `args:{mode:"spec", context:<analysis + scope>}` for step 4.
4. `Bash`/`PowerShell` -> `python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_artifacts.py" --mode spec --file docs/specs/<name>.md` after saving the spec and before the Spec Review gate.
5. `Workflow` -> `agentic-sdlc:spec-plan-draft` with `args:{mode:"plan", context:<approved spec>}` for step 5.
6. `Bash`/`PowerShell` -> `python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_artifacts.py" --mode plan --file docs/plans/<name>.md --spec docs/specs/<name>.md --strict` after saving the plan and before the Plan Review gate.
7. `Skill` -> the selected core work-flow (`agentic-sdlc:fix-flow`, `agentic-sdlc:feature-flow`, `agentic-sdlc:refactor-flow`, or `agentic-sdlc:test-flow`) with the approved spec and plan paths before writing implementation tests or code.
8. `Skill` -> `agentic-sdlc:security-review` for each required security pass, unless a deterministic skip rule applies and is recorded.
9. `Skill` -> `agentic-sdlc:implementasyon-control` before any final implementation report.
10. `Skill` -> `agentic-sdlc:completion-claim-gate` immediately before the final implementation report or any claim containing done, fixed, passing, verified, ready, complete, works, or commit/push/PR readiness.

Do not satisfy these by restating another skill's checklist inline. If a runtime tool is genuinely unavailable, write a `Delegation Degraded` note naming the missing tool and perform the smallest safe fallback; otherwise, missing the tool call is a failed gate.

For an explicit automated smoke eval only, pass `depth:"smoke"` and `maxRevisionRounds:0` to `spec-plan-draft`; normal product work stays full-depth. Smoke mode shortens only the `spec-plan-draft` internals. It does not skip `detect_context.py`, artifact validation, the selected core work-flow Skill call, security review, implementation control, or completion-claim-gate.

## At kickoff (always)
1. **Mode select.** Full vs **Lite Mode** (see playbook). Lite is **forbidden** for auth / payment / security / DB migration / production bug / API contract / permission-role / user-data / token-session / RLS — those are always Full.
2. **Work-type → core work-flow:** bug/broken behavior → `fix-flow` · new feature/endpoint → `feature-flow` · behavior-preserving restructure → `refactor-flow` · test coverage only → `test-flow`.
3. **Create the task list.** One **TodoWrite** item per active step of the selected mode. Mark a step `in_progress` on entry, `completed` only when its gate passes. **Never** complete a gated step while its gate is red. This is how the human follows progress.
4. **Invoke `orchestration` with the `Skill` tool** for every heavy/independent/parallel step — it picks the mechanism (main loop / sub-agent / dynamic-workflow / agent-team). Never run independent work serially in the main loop.

## Companion discipline skills (auto-trigger; cross-cutting)
These fire on their own triggers across the flow — invoke them with the `Skill` tool, don't inline their logic:
- **`mind-spark`** — before kickoff/Spec when the request's shape isn't settled: explore intent and get a design approved, then feed the agreed intent into the Spec phase (step 4). Skips already-specified work.
- **`completion-claim-gate`** — the per-claim, same-turn evidence gate in front of every "done / fixed / passing / works" claim (steps 10/13, Finalize) and before commit (step 17). Complements `implementasyon-control`, which audits the whole flow once.
- **`receiving-code-review`** — when handling reviewer / PR / CI feedback (e.g. after step 19): verify each item against the code before applying, push back with reasons, no performative agreement.

## Step map (detail → `playbook.md`)

| # | Step | Owner | Gate | ⇉ parallel |
|--|--|--|--|--|
| 1 | Update main | dev-flow · git | clean tree | — |
| 2 | Create branch | dev-flow · git | off updated main | — |
| 3 | Analyze code & problem — `detect_context.py` selects `explore_mode` | dev-flow + `context-analyst` | problem + affected files stated | ⇉ per layer |
| 4 | Spec phase (WHAT) — `spec-plan-draft` workflow `mode=spec` (author⇄critic, 2 steps) | dev-flow · workflow | testable criteria, no HOW-leak | — |
| — | **Spec Review gate** | dev-flow + user | decision points resolved, spec approved | — |
| 5 | Plan phase (HOW) — `spec-plan-draft` workflow `mode=plan` (author⇄critic, 2 steps) | dev-flow · workflow | each criterion → a task | — |
| — | **Plan Review gate** | dev-flow + user | plan approved (rule 03) | — |
| 6 | Context7 doc verification (→ WebSearch fallback if quota out) | dev-flow | API/versions confirmed | ⇉ per library |
| 7 | Risk & scope lock | dev-flow | files in/out listed | — |
| — | **Goal lock** | built-in **`/goal`** | end-state locked | — |
| 8 | Failing tests (RED) | core work-flow | test seen to fail | — |
| 9 | Implementation (GREEN) | core work-flow | only in-scope files | — |
| 10 | TDD loop test→fix→test | core work-flow · **`/loop`** | targeted + suite green | — |
| 11 | Security analysis #1 | core work-flow / `security-review` | no open finding | ⇉ lenses |
| 12 | Refactor | core work-flow / `refactor-flow` | behavior unchanged | — |
| 13 | Re-run all tests | core work-flow | full suite green | — |
| 14 | Security analysis #2 (final diff) | dev-flow · `security-review` | final diff clean | ⇉ lenses |
| 15 | Lint / typecheck / build / secret-scan | dev-flow | all gates pass | ⇉ |
| 16 | Git diff review | dev-flow · `/git-safety-check` | only intended files, no secrets | — |
| — | **Implementation control** | `implementasyon-control` | no critical gap | — |
| 17 | Commit | dev-flow · git | user approved | — |
| 18 | Push branch | dev-flow · git | user approved, not main | — |
| 19 | Open PR/MR | dev-flow · git | template filled | — |
| 20 | Merge after review | dev-flow · git | CI + review green, user approved | — |
| 21 | Re-sync local main | dev-flow · git | tree clean | — |

**Parallel (⇉):** dispatch concurrently via `orchestration` — e.g. step 6 fans Context7 checks across N libraries (workflow), steps 11/14 fan security lenses (workflow/agent-team), step 15 runs lint+typecheck+build+secret-scan in parallel (workflow). Gated sequence (4→5→8→9→10) stays strictly ordered.

**Context-fit (skip + document — Step-1-symmetric).** Step 1's "no-op when not a git repo" is the model: a mandated mechanism with nothing to act on in this context is **skipped with a one-line note in its report, never silently dropped** — and the skip decision is deterministic, not a guess. The detector is **`python "${CLAUDE_PLUGIN_ROOT}/scripts/detect_context.py"`** (stdlib, exits 0):
- **Step 3** runs it first and branches on `explore_mode`: `parallel` (≥2 layers) → explore the layers concurrently; `single` → one `context-analyst`; `greenfield_inline` → no existing code, build the Analysis Summary inline (don't spawn a sub-agent with nothing to read).
- **Step 6** uses `--probe deps`: `stdlib_only` → no external API → Context7 fan-out **n/a** (note it; ≠ the quota-out fallback).
- **Step 15** uses `--probe toolchain`: `absent` → quality gates **N/A** (note it).
- **Step 7** (`/goal`) is a **runtime** check: an active `/goal` already in the session → **don't overwrite it**, lock manually or ask.
- **Step 14** (Security #2): if Step 12 refactor was a no-op, the final diff == Security #1 surface → record that and skip the re-run.
Detail per step → `playbook.md`. The Spec/Plan author⇄critic phases (4–5) are **never** subject to a skip branch.

**Spec & Plan are explicit conversational phases (steps 4–5):** each runs the `spec-plan-draft` workflow through the `Workflow` tool (`spec-plan-author` drafts ⇄ `spec-plan-critic` adversarially audits → author revises, ≤2 rounds + closing audit) — Spec with `mode:'spec'`, Plan with `mode:'plan'` (the approved spec as its context). A human **Review gate** follows each: resolve the returned decision points (AskUserQuestion) and approve before moving on. On approval the spec is saved to **`docs/specs/<name>.md`** and the plan to **`docs/plans/<name>.md`** (same base name); the implementation core then follows **these two files faithfully** — drift becomes a new task appended to the plan file, never a silent diff. The approved spec+plan are **not drafted again** inside the delegated work-flow.

**Deterministic artifact gate (machine check under the human Review gate):** before each Review gate, run the validator on the saved file — `python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_artifacts.py" --mode spec --file docs/specs/<name>.md` and, for the plan, `--mode plan --file docs/plans/<name>.md --spec docs/specs/<name>.md --strict`. A non-zero exit (missing section, untestable criterion, an acceptance criterion mapped to no task, a placeholder/secret) **blocks the gate** until fixed. The validator is **structural only** — it cannot tell whether the spec is *about the requested work*. So at the Spec Review gate **also confirm the spec's topic matches the requested task** (a quick human/semantic check): a mis-carried workflow context (see step 4) can yield a structurally-valid but **off-target** spec that the validator would still pass. (`${CLAUDE_PLUGIN_ROOT}/scripts/check_all.py` is an optional manual helper that lints every skill's frontmatter the same `key=value`/exit-1 way; run it by hand — no CI is wired.)

**Core handoff gate:** after the plan validator passes, invoke the selected core work-flow Skill before any implementation edit or test write. For a feature request, that is `Skill` -> `agentic-sdlc:feature-flow`. The core work-flow may then guide RED/GREEN/security/refactor/retest, but loading it is mandatory evidence that dev-flow delegated instead of silently inlining the implementation.

## Git gating (steps 1–2, 17–21)
- **Approval-gated.** Commit / push / PR / merge happen **only on explicit user request** (rule 08). Propose, don't auto-run.
- **No-op when not a git repo.** If there is no repo, skip git steps, say so, and offer `git init`. Never operate destructively on `main`/`master`; work on a `fix/* | feature/* | refactor/* | security/* | chore/*` branch.
- Secrets: mask (`***MASKED***`), report only `file:line` + risk; never commit/log real values.

## Loop points
- **Test fail** → analyze → fix → retest (`/loop`, step 10/13).
- **Security finding** → fix → re-check → retest (steps 11/14).
- **Implementation-control gap** → complete the step → re-run control. **If a critical step is missing, do NOT finalize.**

## Red flags — STOP
- Coding before the spec/plan files exist · diverging from `docs/specs`/`docs/plans` without updating them · marking a gated step done while red · "works/passed/fixed" without real output · scope creep (a new finding is a **new task** in the plan file, not a bigger diff) · committing/pushing without explicit approval · inventing an API without Context7 · running independent work serially instead of delegating.

## Finalize
Only when: code done · relevant + full tests run with output shown · both security passes done · lint/typecheck/build + secret-scan reported · diff reviewed · `implementasyon-control` clean. Then invoke `completion-claim-gate` with the exact evidence you will claim, and only after that produce the **Final Implementation Report** (`templates.md`). No evidence → no "done"; report the honest current state instead.

**References:** step detail + Lite Mode → `playbook.md` · artifact/report templates → `templates.md`.
