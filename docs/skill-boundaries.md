# Skill Boundaries

> Source-of-truth map for **when each AGENTIC-SDLC skill owns a request**. Written for skill authors, plugin users, and reviewers who need to know exactly which skill owns which user intent.

This project is a disciplined SDLC skill library for Claude Code and Codex. A **skill** is a runnable procedure (`SKILL.md` plus optional `scripts/`, `references/`, `assets/`). The **contracts** in `contracts/skills/` are the durable behavior layer; the skills are the runnable procedure layer. This document is about the procedure layer's *boundaries*.

For the component reference see [`plugin-readme.md`](./plugin-readme.md); for runtime-specific usage see [Claude Code](../.claude-plugin/README.md) and [Codex](../.codex-plugin/README.md); for testing see [`testing.md`](./testing.md).

---

## Router-first principle

`using-agentic-sdlc` is the session-local router. Before acting, it asks which AGENTIC-SDLC skill owns the current prompt and chooses the **smallest sufficient skill**.

- A focused skill directly matches the intent → route to that skill.
- The intent spans the full SDLC envelope, **or** touches production-impacting areas (auth, payment, database migrations, API contracts, permissions, user data, tokens/sessions, RLS) → escalate to `agentic-sdlc-pipeline`.
- The user asks *which skill to use*, *how to route*, or *whether scope has shifted* → stay in `using-agentic-sdlc`.

`agentic-sdlc-pipeline` is the **escalation path, not the default**. Step-skills must not call it unless the user is intentionally escalating to the full flow.

## The onion rule

The skill architecture is a directed onion:

- `agentic-sdlc-pipeline` **knows the step-skills and calls them.**
- Step-skills must **not** call `agentic-sdlc-pipeline` and stay maximally unaware of each other.
- A step-skill calls another step-skill only when its own flow genuinely needs it.
- `agentic-sdlc-pipeline` **delegates the core** — it never duplicates spec/plan/TDD logic inline.

This keeps the dependency graph one-directional and prevents the pipeline from becoming a god-object.

---

## Master Owns / Does Not Own table

| Skill | Owns | Does Not Own |
|---|---|---|
| `using-agentic-sdlc` | Session-local routing, smallest-sufficient-skill selection, scope-shift tracking, evidence-before-claim discipline. | Performing implementation, review, or audit work itself. |
| `agentic-sdlc-pipeline` | Full-envelope end-to-end implementation: spec, plan, TDD, tests, security, review, final audit, release/PR readiness. | Focused feature/fix/test/spec/plan/review requests that don't need the full envelope. |
| `spec-authoring` | Spec-only WHAT work: requirements, acceptance criteria, behavior contract, edge cases, definition of done. | Planning HOW tasks or implementing the change. |
| `plan-authoring` | Plan-only HOW work: task breakdown, sequencing, affected surfaces, TDD points, verification plan. | Inventing missing WHAT or implementing the plan. |
| `feature-build` | New feature or endpoint implementation + its tests, ending with implementation-control. | Existing broken-behavior root cause, or the full pipeline envelope unless requested. |
| `root-cause-fix` | Bug fix or failing behavior requiring root cause, regression test, and final audit. | Net-new product capability. |
| `safe-refactor` | Behavior-preserving restructure guarded by characterization tests. | Behavior-changing feature/fix work. |
| `test-authoring` | Writing or fixing tests without production behavior change. | Owning feature/fix implementation. |
| `dispatch-strategy` | Deciding whether work runs in main loop, sub-agent, dynamic-workflow, or agent-team. | Performing the domain work itself. |
| `security-audit` | Security audit for code, diff, design, endpoint, or dependency changes. | General maintainability review or implementing fixes. |
| `code-quality-review` | Quality review of code/diff/file with fresh context. | Applying received reviewer feedback. |
| `feedback-triage` | Verifying, judging, and applying external review comments. | Producing a fresh review from scratch. |
| `implementasyon-control` | Mandatory pre-final audit that the required flow was followed. | Planning or implementing the work. |
| `completion-claim-gate` | Evidence check before saying done/fixed/passing/complete. | Replacing tests, security review, or implementation audit. |
| `mind-spark` | Ambiguous design/build intent before spec. | Clear bug fix, test-only, security review, or code review. |
| `skill-authoring` | Creating, changing, evaluating, or packaging Claude Code / Codex skills. | Ordinary application feature work. |

---

## Per-skill detail cards

Each card lists: **purpose · should trigger · should NOT trigger · produces · delegates · contracts**.

### `using-agentic-sdlc`

- **Purpose:** Session-local bootstrap router for the AGENTIC-SDLC skill system.
- **Should trigger:** explicit routing questions ("which skill owns this?", "route this request"); scope-shift decisions; choosing whether the pipeline is needed when no clearer focused skill applies.
- **Should NOT trigger:** when another focused skill directly matches (a clear bug fix → `root-cause-fix`); as a substitute for doing implementation/review/audit work.
- **Produces:** a routing decision + selected skill + evidence-before-claim discipline.
- **Delegates to:** the smallest sufficient focused skill, or `agentic-sdlc-pipeline`.
- **Contracts:** `00-global-behavior`, `10-ai-agent-collaboration`.

### `agentic-sdlc-pipeline`

- **Purpose:** full-envelope SDLC orchestrator for production-impacting, end-to-end work.
- **Should trigger:** user asks for end-to-end implementation with spec, plan, TDD, tests, security review, PR-ready diff; production-impacting areas (auth, payment, DB migration, API contract, permissions, user data, token/session, RLS).
- **Should NOT trigger:** narrow feature/fix/test/spec/plan/refactor/review/audit requests; as the default for every implementation question.
- **Produces:** approved `docs/agentic-sdlc/specs/<work_id>.md` + `docs/agentic-sdlc/plans/<work_id>.md`, implementation, tests, security findings, final implementation report.
- **Delegates to:** `dispatch-strategy`; `root-cause-fix`/`feature-build`/`safe-refactor`/`test-authoring` for the core; `security-audit`, `implementasyon-control`, `completion-claim-gate` for gates.
- **Contracts:** all of `00`–`10`.

### `spec-authoring`

- **Purpose:** produce the WHAT — requirements, acceptance criteria, edge cases, definition of done.
- **Should trigger:** "write a spec / acceptance criteria / requirements contract / WHAT document"; extract problem, business rules, edge cases, must-not-change behaviors, definition of done.
- **Should NOT trigger:** implementation task breakdown or sequencing (→ `plan-authoring`); ambiguous design exploration (→ `mind-spark`); end-to-end build/test/security (→ `agentic-sdlc-pipeline`).
- **Produces:** a spec summary, and when saved `docs/agentic-sdlc/specs/<work_id>.md` validated by `validate_artifacts.py`.
- **Delegates to:** `plan-authoring` if the user then asks for HOW; the pipeline if escalated; `mind-spark` if intent is still ambiguous.
- **Contracts:** `00`, `01`, `02`.

### `plan-authoring`

- **Purpose:** produce the HOW — task breakdown, sequencing, affected surfaces, verification plan.
- **Should trigger:** "write an implementation plan / task breakdown / HOW document / sequence plan"; turn acceptance criteria into ordered tasks with TDD points and risks.
- **Should NOT trigger:** spec-only requests (→ `spec-authoring`); test-only/code/ambiguous-design prompts; when there is no approved WHAT (inventing missing behavior is forbidden).
- **Produces:** a plan summary, AC→task mapping, and when saved `docs/agentic-sdlc/plans/<work_id>.md` validated by `validate_artifacts.py`.
- **Delegates to:** `feature-build`/`root-cause-fix`/`safe-refactor`/`test-authoring` for execution; the pipeline only for full-envelope work.
- **Contracts:** `00`, `01`, `03` (uses `02` for WHAT coverage).

### `feature-build`

- **Purpose:** build a new feature or endpoint in small, reversible, convention-respecting steps.
- **Should trigger:** "add/build a new feature, endpoint, screen, flow, or capability"; focused new functionality when the full pipeline envelope has **not** been requested.
- **Should NOT trigger:** bug/root-cause fixes (→ `root-cause-fix`); test-only work (→ `test-authoring`); behavior-preserving refactors (→ `safe-refactor`); full SDLC envelope requests (→ `agentic-sdlc-pipeline`).
- **Produces:** implemented feature, tests, security notes, final report.
- **Delegates to:** `dispatch-strategy` for exploration/verification fan-out; `implementasyon-control` for pre-final audit; `completion-claim-gate` before success claims.
- **Contracts:** `01`, `02`, `03`, `04`, `05`, `06`, `07`, `08`, `09`, `10`.

### `root-cause-fix`

- **Purpose:** find the root cause of a bug or failing behavior and fix it with a regression test.
- **Should trigger:** "fix a bug / error / broken behavior / failing test / production issue / incident / regression"; "find and fix / root cause / null reference / webhook / expired-token failures".
- **Should NOT trigger:** new features (→ `feature-build`); pure refactors (→ `safe-refactor`); received review feedback (→ `feedback-triage`).
- **Produces:** a minimal fix, regression test, test output, security pass, final report.
- **Delegates to:** `debugger`, `context-analyst`, `dispatch-strategy`, `security-audit`, `implementasyon-control`, `completion-claim-gate`.
- **Contracts:** `01`, `02`, `03`, `05`, `06`, `07`, `08`, `10`.

### `safe-refactor`

- **Purpose:** improve structure while preserving behavior, guarded by characterization tests.
- **Should trigger:** "refactor / restructure / clean up / simplify / improve readability / reduce duplication / change architecture without changing behavior"; requests requiring characterization tests and approval for broad scope.
- **Should NOT trigger:** bug fixes (→ `root-cause-fix`); new features (→ `feature-build`); test-only work (→ `test-authoring`).
- **Produces:** restructured code, proof behavior is unchanged (tests green before and after), remaining risks.
- **Delegates to:** `dispatch-strategy` for multi-file fan-out; `implementasyon-control` for pre-final audit.
- **Contracts:** `01`, `04`, `05`, `06`, `07`, `08`, `10`.

### `test-authoring`

- **Purpose:** design and write meaningful tests, or repair broken ones.
- **Should trigger:** "write / add / repair / design tests: unit, integration, regression, e2e, flaky tests, failing tests, meaningful assertions, coverage, test doubles, test strategy"; test-only work that must not change production behavior.
- **Should NOT trigger:** feature implementation (→ `feature-build`); bug fixes (→ `root-cause-fix`); refactors (→ `safe-refactor`).
- **Produces:** tests with RED→GREEN evidence, suite output, assertion-quality review.
- **Delegates to:** `root-cause-fix` if the failing test reveals a bug; `dispatch-strategy` for large multi-file passes.
- **Contracts:** `00`, `01`, `05`.

### `dispatch-strategy`

- **Purpose:** decide how work should run — main loop, sub-agent, dynamic-workflow, or agent-team.
- **Should trigger:** "should this run in the main loop, a sub-agent, a workflow, or an agent-team?"; work with 2+ independent parts, heavy exploration, verification/research fan-out, multi-file generation, or multi-angle review/audit.
- **Should NOT trigger:** as a substitute for doing the domain work; when the skill request already implies a specific focused skill (the focused skill consults `dispatch-strategy` internally).
- **Produces:** a mechanism recommendation with cost/caveat rationale.
- **Delegates to:** the chosen runtime mechanism; no domain work is performed here.
- **Contracts:** `00`, `10`.

### `security-audit`

- **Purpose:** systematically audit changes or designs for vulnerabilities.
- **Should trigger:** "audit / review code, diff, endpoint, login flow, or feature for security"; input validation, auth, authorization/IDOR, secrets, injection, dependencies, data exposure, logging, rate limiting, permission boundaries.
- **Should NOT trigger:** general code-quality review (→ `code-quality-review`); bug fixing or feature implementation.
- **Produces:** a findings table `Severity | Category | File:Line | Risk | Recommendation`, secrets masked as `***MASKED***`.
- **Delegates to:** `root-cause-fix` or `feature-build` to implement fixes; `security-reviewer` agent for deep single-lens analysis.
- **Contracts:** `00`, `06`, `10`.

### `code-quality-review`

- **Purpose:** review changes for readability, maintainability, simplicity, and architecture consistency.
- **Should trigger:** "review a diff / file / PR / change for code quality before merge"; readability, duplication, overengineering, naming, error handling, performance, testability.
- **Should NOT trigger:** received review feedback on the user's own change (→ `feedback-triage`); security audit (→ `security-audit`); build/fix work.
- **Produces:** findings grouped by area with `file:line`, issue, concrete suggestion; split into must-fix and optional.
- **Delegates to:** `code-reviewer` sub-agent for fresh-context review; implementation skills for any resulting fixes.
- **Contracts:** `00`, `04`, `10`.

### `feedback-triage`

- **Purpose:** verify, judge, and apply review feedback received on the user's own change.
- **Should trigger:** "apply / triage / judge CodeRabbit comments, reviewer comments, PR/MR feedback, bot/CI/linter review output"; "is this review feedback right?"
- **Should NOT trigger:** writing a fresh quality review of someone else's change (→ `code-quality-review`); feature or bug work not driven by external feedback.
- **Produces:** evaluated feedback items, planned/applied changes, reasoned pushback where appropriate.
- **Delegates to:** `code-quality-review` for cross-reference; `test-authoring` or `root-cause-fix` for behavior changes triggered by feedback.
- **Contracts:** `00`, `02`, `03` (scope lock), `04`.

### `implementasyon-control`

- **Purpose:** mandatory pre-final audit that the required implementation flow was actually followed.
- **Should trigger:** "pre-final audit", "verify the required flow was followed", "before the final answer check the flow"; any final implementation report in `feature-build`/`root-cause-fix`/`safe-refactor`/`agentic-sdlc-pipeline`.
- **Should NOT trigger:** starting new implementation; review feedback triage; listing only security findings.
- **Produces:** an **Implementation Control Report** with PASS / PARTIAL / FAIL per checked step.
- **Delegates to:** `implementation-auditor` agent for an independent fresh-context pass (degraded to main loop only if the agent is unavailable).
- **Contracts:** audits the full implementation-contract set (`00`–`10`); performs no code changes.

### `completion-claim-gate`

- **Purpose:** same-turn evidence gate before any "done / fixed / passing / ready" claim.
- **Should trigger:** immediately before writing done, fixed, passing, working, complete, ready, verified, "all green", "good to go"; before marking a task complete, committing, pushing, opening a PR, or relaying a subagent success claim.
- **Should NOT trigger:** ordinary implementation or planning; future-tense statements of intent; neutral reports of third-party claims.
- **Produces:** an evidence-backed claim with the exact command/output that proves it.
- **Delegates to:** none — it forces a fresh run/read/verify before claiming.
- **Contracts:** `00` (evidence before claim), `05` (RED→GREEN output), `08` (pre-commit verification).

### `mind-spark`

- **Purpose:** pre-spec intent gate for ambiguous build or design work.
- **Should trigger:** "we want a better dashboard but aren't sure what it should look like"; "design a new workflow / tool / experience before writing the spec"; any creative change where requirements, constraints, or success criteria are not agreed.
- **Should NOT trigger:** clear bug fixes (→ `root-cause-fix`); test-only work (→ `test-authoring`); security/code review; zero-design edits (typos, single-line renames).
- **One-decision test for a fix/refactor:** does the request already carry a testable definition of done (spec, ticket with AC, or clearly-described correct behavior)? **Yes** → don't fire, route to `root-cause-fix`/`safe-refactor`. **No** → the missing definition *is* the design question; stay here. "Too simple to design" is **not** a skip.
- **Produces:** an approved design intent (goal, approach, shape, edges, success criteria).
- **Delegates to:** `spec-plan-draft` workflow (Claude Code) or `agentic-sdlc-pipeline` Spec phase after approval; does not write the spec or code itself.
- **Contracts:** `00`, `01`, `02`.

### `skill-authoring`

- **Purpose:** create, edit, evaluate, optimize, and package Claude Code / Codex skills.
- **Should trigger:** "create / edit / test / evaluate / package a skill"; `SKILL.md` frontmatter tuning, trigger/description optimization, eval fixtures, baseline comparison, `.skill` packaging.
- **Should NOT trigger:** ordinary application feature work (→ `feature-build`/`agentic-sdlc-pipeline`); one-line typo fixes (just make the edit).
- **Produces:** a `SKILL.md`, eval fixtures, review viewer, packaged `.skill` artifact.
- **Delegates to:** external `skill-creator` scripts (`quick_validate.py`, `run_eval.py`, `run_loop.py`, `package_skill.py`, `aggregate_benchmark.py`, `generate_review.py`) for evals/viewer/packaging.
- **Method:** RED/GREEN/REFACTOR — capture a baseline failure first, write the minimal skill that fixes it, then close loopholes on a held-out phrasing.
- **Contracts:** `00`, `04` (lean, justified content), and the skill-creator packaging rules.

---

## Spec/Plan boundary

`spec-authoring` and `plan-authoring` are **standalone prompt-level routes**. They are **not** internal substeps of `agentic-sdlc-pipeline`.

| Situation | Owner | Mechanism |
|---|---|---|
| User asks for a spec only | `spec-authoring` | Standalone skill |
| User asks for a plan only | `plan-authoring` | Standalone skill |
| `agentic-sdlc-pipeline` needs spec/plan artifacts | `agentic-sdlc-pipeline` | Owns the phase directly |

When `agentic-sdlc-pipeline` needs spec and plan artifacts:

- **Claude Code:** use the named `Workflow` `spec-plan-draft` (author → critic → revise, ≤2 rounds + closing audit).
- **Codex:** use `agentic-sdlc-pipeline`'s **embedded author/critic adapter** as described in [`runtime-adapter.md`](./runtime-adapter.md). Do **not** call standalone `spec-authoring` or `plan-authoring` from inside the pipeline. Other non-Claude runtimes are deferred adapter targets, not supported release runtimes.

Standalone `spec-authoring` / `plan-authoring` may still use `spec-plan-draft` and the same validator (`validate_artifacts.py`), but they are entry points for single-artifact requests, not phases of a full pipeline run.

---

## Layer ownership

| Layer | Owns |
|---|---|
| `contracts/skills/` | Durable skill behavior contracts (`00`–`10`). |
| `hooks/` | Deterministic runtime enforcement and warnings (secret scan, branch guard, destructive-command guard, session start). |
| `skills/` | Procedure and agentic workflow surface; one directory per skill. |
| `agents/` | Fresh-context specialist roles (context-analyst, code-reviewer, security-reviewer, implementation-auditor, spec-plan-author, spec-plan-critic, …). |
| `workflows/` | Deterministic multi-agent author/critic loops (`spec-plan-draft.js`, `skill-draft.js`). |
| `commands/` | Explicit manual checks such as `/git-safety-check`. |
| `scripts/` | Machine-checkable helpers (`check_all.py`, `validate_artifacts.py`, `detect_context.py`, eval runners, packaging tools). |
| `tests/` | Deterministic test, fixture, golden, and procedure-eval infrastructure. |

---

## Decision flowcharts

### 1. Is this full-envelope work?

```text
End-to-end spec + plan + TDD + tests + security + final audit + PR readiness?
   OR production-impacting / auth / payment / DB migration / API contract / permissions / user data / tokens / RLS?
   YES -> agentic-sdlc-pipeline
   NO  -> go to focused-work ladder
```

### 2. What kind of focused work?

```text
Ambiguous idea / design / build intent?               -> mind-spark
Spec / acceptance criteria / WHAT only?               -> spec-authoring
Plan / task breakdown / HOW only?                     -> plan-authoring
New feature / endpoint / capability?                  -> feature-build
Bug / failing behavior / production issue?            -> root-cause-fix
Behavior-preserving restructure?                      -> safe-refactor
Test-only work (write / fix / strategy)?              -> test-authoring
Security audit of code / diff / endpoint / design?    -> security-audit
Code / diff / PR quality review?                      -> code-quality-review
Received review / bot / CI feedback to verify/apply?  -> feedback-triage
Choose execution mechanism?                           -> dispatch-strategy
Pre-final audit that required flow was followed?      -> implementasyon-control
About to claim done / fixed / passing / ready?        -> completion-claim-gate
Create / edit / evaluate / package a skill?           -> skill-authoring
```

### 3. How should it run? (from `dispatch-strategy`)

```text
Interdependent code, design/sequencing decisions, or small single-file work?
   YES -> main loop
Single independent piece whose intermediate work you don't need in main context
        (exploration, fixed-pattern generation, verification, reference analysis)?
   YES -> sub-agent
Large parallelizable work (≈3+ similar items), deterministic phases,
        adversarial cross-check, or worktree-isolated parallel writes?
   YES -> dynamic-workflow
Interactive, collaborative, continuous parallel work where peers talk and a live lead steers
        (multi-angle review, competing-hypothesis debugging)?
   YES -> agent-team
```

**Cost ladder:** `main loop` < `sub-agent` < `dynamic-workflow` < `agent-team`. Always use the smallest sufficient mechanism.

---

## Cross-references

- Project overview and install: [`README.md`](../README.md)
- Claude Code runtime README: [`../.claude-plugin/README.md`](../.claude-plugin/README.md)
- Codex runtime README: [`../.codex-plugin/README.md`](../.codex-plugin/README.md)
- Component-by-component plugin documentation: [`plugin-readme.md`](./plugin-readme.md)
- Skill behavior contracts: [`contracts/skills/`](../contracts/skills/)
  - `00-global-behavior.md` · `01-context-first.md` · `02-spec-driven-development.md` · `03-plan-mode.md` · `04-code-quality.md` · `05-testing.md` · `06-security.md` · `07-refactoring.md` · `08-git-safety.md` · `09-documentation.md` · `10-ai-agent-collaboration.md`
- Golden skill references and trigger keywords: [`tests/skills/golden/skills.json`](../tests/skills/golden/skills.json)
- Live trigger eval fixtures: [`tests/skills/evals/*.json`](../tests/skills/evals/)
- Quality gate commands:
  - `python3 scripts/check_all.py`
  - `python3 tests/skills/harness.py`
  - `python3 -m unittest discover -s tests -v`
