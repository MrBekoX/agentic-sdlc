# AGENTIC-SDLC Plugin Reference

> Version: `0.2.7` (see `VERSION`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.codex-plugin/plugin.json`)

AGENTIC-SDLC is a local/development plugin that brings a disciplined, gated SDLC to **Claude Code** and **Codex**. It routes each prompt to the smallest sufficient skill and reserves the full **spec → plan → TDD → security → review → final audit** envelope for work that actually needs it.

This document is the **component-by-component reference** for a developer who has installed (or is about to install) the plugin. For skill responsibilities and anti-overlap rules see [`skill-boundaries.md`](./skill-boundaries.md); for testing see [`testing.md`](./testing.md).

---

## 1. Supported runtimes

| Runtime | What the plugin uses | Key differences |
|---|---|---|
| **Claude Code** | Native `Skill`, `Workflow`, `Agent` tools; `hooks/hooks.json` | Full JavaScript Workflow runtime (`spec-plan-draft`, `skill-draft`). Hook paths resolve via `${CLAUDE_PLUGIN_ROOT}`. |
| **Codex** | Activated skill instructions + available tools; `hooks/hooks-codex.json` | No Claude Workflow runtime. `agentic-sdlc-pipeline` uses an **embedded author/critic adapter** for spec/plan phases. Hook paths resolve via `${PLUGIN_ROOT}`. |
| **OpenCode / Kimi Code / similar Agent Skills runtimes** | Standard `SKILL.md` directories plus runtime-native skill/agent/task mechanisms | Supported through the portable adapter when the runtime can provide equivalent tool evidence or a documented degraded path. Hook wiring is runtime-specific and not native-packaged in this repo. |

See [`runtime-adapter.md`](./runtime-adapter.md) for portable capability names and runtime-specific equivalents.

---

## 2. Installation model

Plugin metadata lives at the repo root:

| File | Purpose |
|---|---|
| `.claude-plugin/plugin.json` | Claude Code plugin manifest: name, version, description, keywords, author, license, homepage. |
| `.claude-plugin/marketplace.json` | Local marketplace source definition. The plugin entry uses `"source": "./"`, so the repo root **is** the source. |
| `.codex-plugin/plugin.json` | Codex plugin manifest: points to `./skills/` and `./hooks/hooks-codex.json`, plus the `interface` block (displayName, capabilities, defaultPrompt, …). |
| `hooks/hooks.json` | Claude Code hook wiring: PreToolUse / PostToolUse / SessionStart. |
| `hooks/hooks-codex.json` | Codex hook wiring: SessionStart bootstrap only in this release. |

**Layout rules (important):**

- Skills live in root `skills/`, **not** in `.claude/skills/` or `.codex/skills/`.
- Runtime paths resolve through environment-style variables:
  - Claude Code → `${CLAUDE_PLUGIN_ROOT}`
  - Codex → `${PLUGIN_ROOT}`
- Because hooks and skill-internal commands rely on these variables, the expected model is **installing the repo as a plugin**, not running it as a bare project.

---

## 3. Runtime requirements

| Requirement | Why it is needed |
|---|---|
| Claude Code or Codex | Native packaged agent runtimes. OpenCode/Kimi Code-style Agent Skills runtimes use `runtime-adapter.md`. |
| Node.js | Hook scripts are `.mjs` and run via `node`. |
| Python 3 | Deterministic scripts, validators, eval helpers, and the local gate. |
| Git | Branch guard, diff review, review packages, commit/PR flow. |
| `pre-commit` *(optional)* | Extra static checks wired in `.pre-commit-config.yaml`. |

In a non-git workspace most flows still work, but branch, commit, PR, worktree, and release steps are explicitly **skipped with a note** rather than silently dropped.

---

## 4. Layered control system

| Layer | Responsibility |
|---|---|
| `skills/` | Procedural instructions and the trigger surface. One dir per skill: `SKILL.md` + optional `scripts/`, `references/`, `assets/`. |
| `agents/` | Read-only expert sub-agent role contracts (analysis, review, audit). |
| `workflows/` | Repeatable author⇄critic multi-agent loops for Claude Code's Workflow runtime. |
| `hooks/` | Deterministic security and runtime guardrails. |
| `contracts/skills/` | Durable behavior contracts (`00`–`10`) that skills reference. |
| `commands/` | Manual slash commands such as `/git-safety-check`. |
| `scripts/` | Machine-verifiable Python helpers and eval runners. |
| `tests/` | Deterministic test suites, fixtures, golden references, and eval harnesses. |
| `.claude-plugin/` / `.codex-plugin/` | Plugin manifests and local marketplace metadata. |

---

## 5. Entry points

### 5.1 `using-agentic-sdlc` — the session-local router

`skills/using-agentic-sdlc/SKILL.md` is the bootstrap router. Before acting it asks *which AGENTIC-SDLC skill owns this prompt* and chooses the smallest sufficient one. It tracks the current intent, active skill, known artifacts, and scope shifts in conversation memory (no persistent file).

**Router decision table:**

| User intent | Routes to |
|---|---|
| Ambiguous idea, design, or build intent | `mind-spark` |
| Spec / acceptance criteria / WHAT only | `spec-authoring` |
| Plan / task breakdown / HOW only | `plan-authoring` |
| New feature or endpoint | `feature-build` |
| Bug, broken behavior, production issue | `root-cause-fix` |
| Behavior-preserving restructure | `safe-refactor` |
| Test-only work | `test-authoring` |
| Security audit | `security-audit` |
| Code/diff quality review | `code-quality-review` |
| Received review feedback | `feedback-triage` |
| Parallelism / delegation decision | `dispatch-strategy` |
| Final implementation audit | `implementasyon-control` |
| Any done/fixed/passing/ready claim | `completion-claim-gate` **first** |
| End-to-end production-ready SDLC | `agentic-sdlc-pipeline` |

Escalate to `agentic-sdlc-pipeline` only for end-to-end implementation or high-risk areas (auth, payment, DB migration, API contract, permissions, user data, token/session, RLS).

### 5.2 `agentic-sdlc-pipeline` — the full-envelope orchestrator

`skills/agentic-sdlc-pipeline/SKILL.md` owns the **outer envelope** for production-impacting work. It does **not** implement the core itself — it delegates the implementation core to the matching work-flow skill, handing it the approved `docs/specs/<name>.md` + `docs/plans/<name>.md`.

**Work-type → core work-flow:**

| Symptom | Delegated skill |
|---|---|
| Bug / broken behavior / prod issue | `root-cause-fix` |
| New feature / endpoint / capability | `feature-build` |
| Behavior-preserving restructure | `safe-refactor` |
| Test coverage only | `test-authoring` |

**Full-mode step map** (21 steps + gates; detail in `skills/agentic-sdlc-pipeline/playbook.md`):

| # | Step | Owner | Gate |
|---|---|---|---|
| 1 | Update main (git) | pipeline · git | clean tree |
| 2 | Create branch | pipeline · git | off updated main |
| 3 | Analyze code & problem (`detect_context.py` picks `explore_mode`) | pipeline + `context-analyst` | problem + affected files stated |
| 4 | **Spec phase** (WHAT) — Claude Code: `spec-plan-draft` workflow; non-Claude runtimes: embedded adapter | pipeline | testable criteria, no HOW-leak |
| — | *Spec Review gate* | pipeline + user | decision points resolved, spec approved |
| 5 | **Plan phase** (HOW) — Claude Code: `spec-plan-draft` workflow; non-Claude runtimes: embedded adapter | pipeline | each criterion → a task |
| — | *Plan Review gate* | pipeline + user | plan approved |
| 6 | Context7 doc verification (WebSearch fallback if quota out) | pipeline | API/versions confirmed |
| 7 | Risk & scope lock (`/goal`) | pipeline | files in/out listed |
| 8 | Failing tests (RED) | core work-flow | test seen to fail |
| 9 | Implementation (GREEN) | core work-flow | only in-scope files |
| 10 | TDD loop test→fix→test (`/loop`) | core work-flow | targeted + suite green |
| 11 | Security analysis #1 | core work-flow / `security-audit` | no open finding |
| 12 | Refactor | core work-flow / `safe-refactor` | behavior unchanged |
| 13 | Re-run all tests | core work-flow | full suite green |
| 14 | Security analysis #2 (final diff) | pipeline · `security-audit` | final diff clean |
| 15 | Lint / typecheck / build / secret-scan | pipeline | all gates pass |
| 16 | Git diff review (`/git-safety-check`) | pipeline | only intended files, no secrets |
| — | *Implementation control* | `implementasyon-control` | no critical gap |
| 17 | Commit | pipeline · git | user approved |
| 18 | Push branch | pipeline · git | user approved, not main |
| 19 | Open PR/MR | pipeline · git | template filled |
| 20 | Merge after review | pipeline · git | review + gates green, user approved |
| 21 | Re-sync local main | pipeline · git | tree clean |

**Parallel (⇉):** genuinely-independent steps run concurrently via `dispatch-strategy` (Context7 across libraries, security lenses, quality gates). The gated sequence **4 → 5 → 8 → 9 → 10** is never parallelized.

**Minimum Full-mode transcript evidence** (Claude Code — these are *tool calls*, not prose):

1. `Skill` → `agentic-sdlc:dispatch-strategy` before mechanism decisions.
2. `Bash` → `python "${CLAUDE_PLUGIN_ROOT}/scripts/detect_context.py" --path <scope>`.
3. `Workflow` → `agentic-sdlc:spec-plan-draft` with `mode:"spec"`.
4. `Bash` → `python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_artifacts.py" --mode spec --file docs/specs/<name>.md`.
5. `Workflow` → `agentic-sdlc:spec-plan-draft` with `mode:"plan"`.
6. `Bash` → `…validate_artifacts.py --mode plan --file docs/plans/<name>.md --spec docs/specs/<name>.md --strict`.
7. `Skill` → selected core work-flow with the approved spec+plan paths.
8. `Skill` → `agentic-sdlc:security-audit` for each required pass.
9. `Skill` → `agentic-sdlc:implementasyon-control` before any final report.
10. `Skill` → `agentic-sdlc:completion-claim-gate` immediately before any success claim.

**Lite Mode:** a short track (branch check · short analysis · scope note · change · relevant test/lint · diff review · commit) for low-risk work only (typo, README edit, comment). **Forbidden** for auth, payment, security, DB migration, production bug, API contract, permission/role, user-data, token/session, or RLS — those are always Full.

**Context-fit skips (Step-1-symmetric):** a mandated mechanism with nothing to act on is **skipped with a one-line note, never silently dropped**:

- Step 6: `detect_context.py --probe deps` → `stdlib_only` → Context7 fan-out **n/a**.
- Step 15: `detect_context.py --probe toolchain` → `absent` → quality gates **N/A** (secret-scan still runs).
- Step 14: if step 12 refactor was a no-op → Security #2 == Security #1 surface → record and skip.

The Spec/Plan author⇄critic phases (4–5) are **never** subject to a skip branch.

---

## 6. Focused skills

| Skill | When to use | What it owns | What it delegates |
|---|---|---|---|
| `using-agentic-sdlc` | Meta-routing; choosing/selecting/routing the right skill. | Session-local routing + scope-shift tracking + evidence discipline. | The focused skill, or pipeline for full-envelope work. |
| `agentic-sdlc-pipeline` | End-to-end full SDLC envelope. | Outer envelope: git lifecycle, spec/plan phases, doc verification, scope-lock, quality gates, final audit. | Core work-flows + `security-audit`, `implementasyon-control`, `completion-claim-gate`. |
| `spec-authoring` | Spec/WHAT/ac/requirements contract only. | Standalone spec artifact in `docs/specs/`. | `spec-plan-draft` workflow (Claude) or manual draft + critic; `validate_artifacts.py`. |
| `plan-authoring` | Plan/HOW/task breakdown/sequencing only. | Standalone plan artifact in `docs/plans/`. | `spec-plan-draft` workflow (Claude) or manual draft + critic; `validate_artifacts.py`. |
| `root-cause-fix` | Bug, error, broken behavior, failing test, prod issue. | Root-cause diagnosis → spec → plan → RED test → minimal fix → security → refactor → retest. | `debugger`, `context-analyst`, `dispatch-strategy`, `security-audit`, `implementasyon-control`, `completion-claim-gate`. |
| `feature-build` | New feature/endpoint/capability without the full pipeline. | Requirement analysis → spec → plan → TDD → security → refactor → docs. | `context-analyst`, `dispatch-strategy`, `security-audit`, `implementasyon-control`. |
| `safe-refactor` | Refactor/restructure/cleanup without behavior change. | Characterization tests → scope → small steps → no-behavior-change proof. | `dispatch-strategy`, `test-authoring`, `security-audit`, `implementasyon-control`. |
| `test-authoring` | Write/add/repair/design tests only. | Meaningful unit/integration/regression/e2e tests, RED→GREEN. | `test-engineer`, `dispatch-strategy`. |
| `security-audit` | Audit/review code or diff for security. | Systematic vulnerability review + masked findings report. | `security-reviewer`, `dispatch-strategy` for parallel lenses. |
| `code-quality-review` | Fresh-context quality review before merge. | Readability/maintainability/simplicity/duplication findings. | `code-reviewer` sub-agent. |
| `feedback-triage` | Received PR/MR/bot review feedback to verify/apply. | READ → UNDERSTAND → VERIFY → EVALUATE → RESPOND → IMPLEMENT. | Behavior changes to `root-cause-fix` / `test-authoring`. |
| `mind-spark` | Ambiguous build/design request whose shape isn't settled. | Intent/design clarification + user approval before spec. | Hands off to `spec-plan-draft` or pipeline Spec phase. |
| `skill-authoring` | Create/edit/test/evaluate/package a skill. | SKILL.md, frontmatter, eval fixtures, baseline comparison, packaging. | External `skill-creator` scripts (`quick_validate.py`, `run_eval.py`, `package_skill.py`, …). |
| `implementasyon-control` | Pre-final audit: required flow was actually followed. | Implementation Control Report — PASS/PARTIAL/FAIL per step. | `implementation-auditor` agent. |
| `completion-claim-gate` | Same-turn evidence gate before any done/fixed/passing claim. | Identify → Run → Read → Verify → Then claim. | None. |
| `dispatch-strategy` | Decide execution mechanism for non-trivial work. | main loop / sub-agent / dynamic-workflow / agent-team. | None. |

---

## 7. Agents (9)

All agents are **read-only contracts** under `agents/*.md`, used to keep the main context clean. They are spawned by subagents/workflows.

| Agent | Purpose | Constraints | Used by |
|---|---|---|---|
| `context-analyst` | Explore codebase structure and locate relevant files before a change. | Read-only; no edits. | `agentic-sdlc-pipeline`, `dispatch-strategy`, `feature-build`, `root-cause-fix`. |
| `debugger` | Find root cause of a bug; separate symptom from cause. | Diagnose only; no code changes. | `root-cause-fix`. |
| `code-reviewer` | Fresh-context quality review of a diff or file. | Read-only; recommends, does not edit. | `code-quality-review`. |
| `security-reviewer` | Audit changes for vulnerabilities. | Read-only; never prints real secrets; masks values. | `security-audit`. |
| `implementation-auditor` | Verify a completed change followed the required flow. | Read-only; structured verdict; blocks final if critical gaps exist. | `implementasyon-control`. |
| `software-architect` | Validate structural decisions; flag unnecessary abstractions. | Read-only; recommends simpler alternatives. | Large changes, `agentic-sdlc-pipeline`. |
| `test-engineer` | Design test strategy and audit existing test meaning. | Analysis only; does not write tests. | `test-authoring`. |
| `spec-plan-author` | Produce a deep spec or plan draft. | Returns draft + decision points; does not write files directly. | `spec-plan-draft` workflow, non-Claude embedded adapter. |
| `spec-plan-critic` | Adversarially audit a spec/plan draft for completeness/contradictions. | Returns structured critique. | `spec-plan-draft` workflow, non-Claude embedded adapter. |

---

## 8. Workflows (2)

`workflows/` contains JavaScript Workflow scripts for Claude Code's native Workflow runtime.

### `workflows/spec-plan-draft.js` — name `spec-plan-draft`

- **Args:** `{ mode: 'spec' | 'plan', context: <object|string>, depth?: 'full' | 'smoke', maxRevisionRounds?: number }`
- **Sequence:**
  1. Defensively parse `args` (JSON string or object); **fail loud** if `context` is empty.
  2. Optional smoke draft when `depth === 'smoke'`.
  3. `agent()` call with `agentType: 'agentic-sdlc:spec-plan-author'` to produce the draft.
  4. Up to `maxRevisionRounds` critic rounds with `agentType: 'agentic-sdlc:spec-plan-critic'`.
  5. Closing audit; returns draft markdown + decision points + residual critic notes.
- **Claude Code vs non-Claude runtimes:** Claude Code only. In Codex, OpenCode, Kimi Code, and similar runtimes the same author/critic discipline runs **inside** `agentic-sdlc-pipeline` through the embedded adapter.

### `workflows/skill-draft.js` — name `skill-draft`

- **Args:** `{ mode: 'create' | 'improve', context: <object|string>, currentDraft?: string }`
- **Sequence:**
  1. Defensively parse `args` as JSON string.
  2. Apply the house style prompt (lean, imperative, no caps-MUST stacking, frontmatter constraints).
  3. Author draft.
  4. Up to 2 critic rounds checking description framing, trigger boundaries, length, examples, frontmatter validity.
  5. Closing audit; returns full `SKILL.md` draft + description + decision points.
- **Claude Code vs non-Claude runtimes:** intended for Claude Code's Workflow runtime; non-Claude skill authoring follows the same method with available tools directly.

---

## 9. Commands

### `/git-safety-check`

- **File:** `commands/git-safety-check.md`
- **Type:** read-only pre-commit safety check. **Never commits or pushes.**
- **Governing contract:** `contracts/skills/08-git-safety.md`

It runs `git status`, `git diff --stat`, `git diff`, `git log --oneline -n 10`, and a read-only staged-secret scan (`git diff --cached | grep …`). On a suspicious match it masks the value and reports `file:line` + risk type.

**Pre-commit checklist:** only intended files changed · no secret/token leak · build/test commands run and shown · change focused on one problem · branch is not `main`/`master` · commit message clear (propose only — never commit without explicit approval).

---

## 10. Hooks and guardrails

### Real hooks (wired in `hooks/hooks.json` and `hooks/hooks-codex.json`)

| Script | Trigger event | Behavior | Block / Warn |
|---|---|---|---|
| `session-start.mjs` | `SessionStart` | Injects git status summary + AGENTIC-SDLC bootstrap reminder. | None (informational) |
| `scan-write.mjs` | `PostToolUse` (Write/Edit/MultiEdit) | Scans newly written text for secret-shaped content. | Warn |
| `scan-commit.mjs` | `PreToolUse` (`Bash git commit*`) | Scans added diff lines for high-confidence secrets. | **Block** |
| `branch-guard.mjs` | `PreToolUse` (`git commit*` / `git push*`) | Warns on `main`/`master`; blocks if `AGENTIC_BRANCH_GUARD_BLOCK=true`; flags force-push. | Warn / Block |
| `destructive-command-guard.mjs` | `PreToolUse` (`Bash`) | Blocks deterministic destructive commands (`git reset --hard`, forceful `git clean`, `rm -rf`, `Remove-Item -Recurse -Force`). | **Block** |
| `secret-patterns.mjs` | shared library | Generic secret patterns + scanner used by the scan hooks. No standalone event. | n/a |

All hook scripts are generic (no shell for git — argument arrays), path-normalized, skip-listed, and **fail-open on error** so a hook fault does not break the agent session. Claude Code wires via `${CLAUDE_PLUGIN_ROOT}`; Codex via `${PLUGIN_ROOT}`; other runtimes need their own hook wiring or a documented degraded path.

### Conceptual hooks (judgment-based, enforced by skills/contracts)

Some checkpoints require judgment and are therefore enforced inside skills/contracts rather than as deterministic scripts (per `hooks/README.md`):

| Conceptual hook | Enforced by |
|---|---|
| Pre-edit context check (file read? spec/plan exists? in scope?) | contracts `01-context-first`, `03-plan-mode`; `root-cause-fix`/`feature-build` early steps |
| Post-edit diff check (which files changed? diff too big?) | contracts `04-code-quality`, `08-git-safety`; `code-quality-review` |
| Pre-test command check (right command? right scope?) | contract `05-testing`; `test-authoring` |
| Post-test result check (output read? fail root-caused?) | contract `05-testing`; `root-cause-fix` test loops |
| Security-sensitive change check | contract `06-security`; `security-audit` |
| Pre-git operation check | contract `08-git-safety`; `/git-safety-check`; `scan-commit.mjs`; `branch-guard.mjs` |
| Final response verification | `implementasyon-control` skill + `implementation-auditor` agent |

---

## 11. Deterministic scripts (11)

All scripts are in `scripts/*.py`, pure stdlib unless noted, and emit sorted flat `key=value` lines for easy log parsing.

| Script | Purpose | Example invocation |
|---|---|---|
| `check_all.py` | Local repo gate: skill frontmatter + unittest discovery. | `python3 scripts/check_all.py` |
| `validate_artifacts.py` | Spec/plan structural validation, placeholder/secret scan, AC coverage. | `python3 scripts/validate_artifacts.py --mode spec --file docs/specs/login.md` |
| `detect_context.py` | Workspace classification, dependency/toolchain probe. Always exits 0. | `python3 scripts/detect_context.py --path .` |
| `run_trigger_eval.py` | Windows-safe live Claude Code trigger eval. | `python3 scripts/run_trigger_eval.py --skill-path skills/agentic-sdlc-pipeline --eval-set tests/skills/evals/agentic-sdlc-pipeline.json --runs 3` |
| `run_codex_trigger_eval.py` | Codex route-classifier trigger eval. | `python3 scripts/run_codex_trigger_eval.py --skill-path skills/spec-authoring --eval-set tests/skills/evals/spec-authoring.json --smoke --model gpt-5.4-mini --reasoning-effort low` |
| `run_all_trigger_evals.py` | Batch wrapper over Claude and/or Codex trigger evals for every fixture. | `python3 scripts/run_all_trigger_evals.py --runtime both --smoke` |
| `run_behavior_eval.py` | Behavior fixture dry-run/live validator. | `python3 scripts/run_behavior_eval.py --eval-set tests/skills/behavior/completion-claim-gate.json --dry-run` |
| `run_procedure_eval.py` | Transcript/live procedure evaluator. | `python3 scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --dry-run` |
| `bump_version.py` | Sync `VERSION`, plugin manifest, and marketplace version. | `python3 scripts/bump_version.py --check` |
| `task_brief.py` | Extract one task from a plan into a handoff file. | `python3 scripts/task_brief.py docs/plans/login.md 1` |
| `review_package.py` | Produce a git diff review package. | `python3 scripts/review_package.py main HEAD` |

> `skill-authoring` additionally delegates to the **external** Anthropic `skill-creator` plugin scripts (`quick_validate.py`, `run_eval.py`, `run_loop.py`, `package_skill.py`, `aggregate_benchmark.py`, `generate_review.py`) located under `~/.claude/plugins/marketplaces/anthropic-agent-skills/skills/skill-creator`. These are **not** part of this repo.

---

## 12. Test and eval layers

### Local deterministic gate

The local gate proves **static wiring and fixture health**, not live model obedience:

```bash
python3 scripts/check_all.py
python3 tests/skills/harness.py
python3 -m unittest discover -s tests -v
```

What it covers: skill frontmatter shape + allowed keys · skill/agent/workflow/hook/script/contract cross-references resolve · golden description drift · safety-fixture evidence wired · hook/workflow JavaScript syntax (`node --check`) · plugin metadata + version consistency · `validate_artifacts.py` test cases · procedure-evaluator fixture cases.

### Eval categories

| Eval type | Script | What it measures |
|---|---|---|
| **Trigger eval** | `run_trigger_eval.py` (Claude), `run_codex_trigger_eval.py` (Codex), `run_all_trigger_evals.py` | Whether the right skill is selected for a prompt. |
| **Behavior eval** | `run_behavior_eval.py` | Whether a skill's output matches required/forbidden patterns. |
| **Procedure eval** | `run_procedure_eval.py` | Whether a full run used required skills, workflows, commands, artifacts, and avoided forbidden commands. |

Live evals require Claude/Codex CLI and auth and are **not** part of the normal local gate. See [`testing.md`](./testing.md) for the full strategy.

---

## 13. Automation policy

- **No CI workflow** is configured for this repo (GitHub Actions CI was intentionally removed — see CHANGELOG `0.2.0`).
- Releases, publishing, automatic commit/push, and marketplace publication are **not automated**.
- Health checks are run manually with the local gate commands.
- Any release work happens only on explicit user request as a separate manual process.

### Pre-push checklist

```bash
git status --short --branch
python3 scripts/bump_version.py --check
python3 scripts/check_all.py
python3 tests/skills/harness.py
python3 -m unittest discover -s tests -v
python3 scripts/run_behavior_eval.py --eval-set tests/skills/behavior/completion-claim-gate.json --dry-run
python3 scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --dry-run
python3 scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --transcript tests/fixtures/transcripts/agentic-sdlc-pipeline-procedure-pass.jsonl
```

Optional: `pre-commit run --all-files`.

---

## 14. Known limitations and scope notes

- Version `0.2.7` is unreleased; no CI pipeline exists.
- Publishing/release work must be a separate, explicit manual process.
- Hook operation depends on Node.js on `PATH` and the runtime resolving `${CLAUDE_PLUGIN_ROOT}` / `${PLUGIN_ROOT}`.
- Some hooks fail-open on error so they do not break the agent session.
- `scan-write.mjs` warns but does **not** block.
- `branch-guard.mjs` blocks only when `AGENTIC_BRANCH_GUARD_BLOCK=true`.
- `validate_artifacts.py` performs **structural** checks; it cannot prove a spec is semantically correct for the requested work (a quick human/semantic topic-match check is recommended at the Spec Review gate).
- Deterministic tests verify wiring and fixture health, **not** live model obedience.
- The repo gate accepts additional Claude Code frontmatter keys (`user-invocable`, `argument-hint`) that a stricter external `skill-creator` validator may reject.
- Non-Claude runtimes have no Claude Workflow runtime; `agentic-sdlc-pipeline` uses an embedded adapter for spec/plan phases and must leave equivalent transcript evidence or a documented degraded path.
- `spec-authoring` and `plan-authoring` are standalone prompt routes; the pipeline does **not** invoke them internally.

---

## 15. Cross-references

- Project overview and install notes: [`README.md`](../README.md)
- Operating model for agents in this repo: [`AGENTS.md`](../AGENTS.md)
- Skill responsibilities and anti-overlap rules: [`skill-boundaries.md`](./skill-boundaries.md)
- Testing strategy, fixtures, and harness: [`testing.md`](./testing.md)
- Skill instructions: `skills/*/SKILL.md`
- Agent contracts: `agents/*.md`
- Workflow scripts: `workflows/spec-plan-draft.js`, `workflows/skill-draft.js`
- Hook scripts and conceptual mapping: `hooks/*.mjs`, `hooks/README.md`
- Behavior contracts: `contracts/skills/*.md` (`00`–`10`)
- Deterministic helpers: `scripts/*.py`
- Static integration harness: `tests/skills/harness.py`
- Local test suites: `tests/test_*.py`
