# agentic-sdlc-pipeline — Playbook (step detail)

Detailed reference for `agentic-sdlc-pipeline/SKILL.md`. The SKILL.md table is the spine; this file is the WHAT-each-step-means. agentic-sdlc-pipeline **owns** the outer steps and **delegates** the core to the matching work-flow.

## Tool-call contract
Full Mode is not satisfied by inline summaries of other skills. Use `docs/runtime-adapter.md` for portable capability names and runtime-specific equivalents. In Claude Code, agentic-sdlc-pipeline must call:
- `Skill` -> `agentic-sdlc:dispatch-strategy` before non-trivial mechanism decisions.
- `Bash`/`PowerShell` -> `python "${CLAUDE_PLUGIN_ROOT}/scripts/detect_context.py" --path <scope>` before replacing exploration decisions with file reads.
- `Workflow` -> `agentic-sdlc:spec-plan-draft` for step 4 (`mode:"spec"`) and step 5 (`mode:"plan"`).
- `Bash`/`PowerShell` -> `python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_artifacts.py"` after saving the spec and plan artifacts.
- `Skill` -> the selected core work-flow with the approved `docs/agentic-sdlc/specs/<work_id>.md` and `docs/agentic-sdlc/plans/<work_id>.md` paths.
- `Skill` -> `agentic-sdlc:security-audit` for required security passes.
- `Skill` -> `agentic-sdlc:implementasyon-control` before finalizing.
- `Skill` -> `agentic-sdlc:completion-claim-gate` before any success/completion/ready claim.

In Codex, the other supported runtime, Claude Code `Workflow` calls are not available. Keep `spec-authoring` and `plan-authoring` as independent entry skills; agentic-sdlc-pipeline does not invoke them for steps 4-5. Instead, agentic-sdlc-pipeline runs the embedded adapter:
- Draft the spec/plan in the main loop using `spec-plan-author` role instructions and contracts 02/03.
- Run a fresh-context critic pass with the runtime's subagent/specialist mechanism using `spec-plan-critic` instructions wherever the runtime exposes a subagent mechanism (mandatory there).
- Revise up to two rounds, save the artifact, then run `validate_artifacts.py`.
- If fresh-context specialists are unavailable, record `Delegation Degraded: fresh-context specialist unavailable` and perform the critic pass inline.

Resolve `<runtime-root>` as `${CLAUDE_PLUGIN_ROOT}` in Claude Code, `${PLUGIN_ROOT}` in Codex for contract and script paths.

If a tool is missing in the runtime, record `Delegation Degraded: <tool/name>` and continue with the smallest safe fallback. If the tool exists, skipping the call is a failed gate. Manual Read/Glob/ls exploration does not replace `detect_context.py`; manual review text does not replace `validate_artifacts.py`; manual TDD/edit/test work does not replace the selected core work-flow Skill call.

For explicit automated smoke evals, add `depth:"smoke"` and `maxRevisionRounds:0` to the `spec-plan-draft` args. Do not use smoke depth for normal product work. Smoke depth shortens only the workflow's author/critic loop; it does not skip context detection, artifact validation, core work-flow delegation, security review, implementation control, or completion-claim-gate.

Call-order rule: `dispatch-strategy` is the first delegate call before Read/Bash/Edit/Write work. `completion-claim-gate` is the last delegate call immediately before the final report. These two are required even for smoke evals and small single-file changes.

## Work-type → core work-flow
| Symptom | Core work-flow | agentic-sdlc-pipeline adds around it |
|---|---|---|
| Bug / error / broken behavior / prod issue | `root-cause-fix` | git envelope, Context7, scope-lock, 2nd security, quality gates |
| New feature / endpoint / capability | `feature-build` | same envelope |
| Behavior-preserving restructure | `safe-refactor` | characterization-test guard + envelope |
| Test coverage only | `test-authoring` | envelope (usually no migration/git-PR) |

agentic-sdlc-pipeline **owns the Spec and Plan phases directly** (steps 4–5). Claude Code uses the `spec-plan-draft` workflow with review gates; Codex uses the embedded author/critic adapter because the Claude Workflow runtime is not available there. agentic-sdlc-pipeline persists the artifacts to **`docs/agentic-sdlc/specs/`** and **`docs/agentic-sdlc/plans/`**, then hands the **approved spec + plan files** to the core work-flow, which executes the implementation core — RED → GREEN → security#1 → refactor → retest → `implementasyon-control` (steps 8–13) — **faithfully to those two files**. The work-flow consumes the provided spec/plan and does not re-draft them.

---

## Outer steps agentic-sdlc-pipeline owns directly

### 1. Update main (git) — approval-gated, no-op if not a repo
`git status --short` + `git branch --show-current`. If tree clean and a repo: `git checkout <main>` → `git pull --ff-only origin <main>` (detect real default branch: main/master/develop). **Forbidden without explicit user approval:** `reset --hard`, `clean -fdx`, `stash drop`, `push --force`. Report: active branch, working-tree state, main up-to-date?, safe-to-proceed?

### 2. Create branch (git) — approval-gated
Name by work type: `fix/login-validation`, `feature/notification-settings`, `refactor/order-validation`, `security/rls-hardening`, `chore/update-deps`. Bad names (`fix`, `new`, `test`, `claude-work`, `final`) are rejected. `git checkout -b <name>`. Report branch + parent commit.

### 2a. Optional worktree isolation — use for risky or parallel work
For large, risky, or parallelizable implementation, prefer an isolated git worktree after branch creation. Use native Claude Code worktree support if available; otherwise use `git worktree add <path> <branch>` with explicit user approval. Record the original repo path, worktree path, branch, and cleanup plan. Do not create a worktree for small single-session changes, non-git workspaces, or tasks where isolation adds no value.

### 3. Analyze code & problem — `detect_context.py` first, then branch
Classify the workspace **deterministically** before choosing how to explore — don't guess. Run **`python "<runtime-root>/scripts/detect_context.py" --path <scope>`** (repeat `--path` per root; stdlib, exits 0) and branch on `explore_mode`:
- **`parallel`** (brownfield, ≥2 layers listed in `layers=`): explore the project **layers concurrently**. Per `dispatch-strategy`, use an agent-team or one `context-analyst` sub-agent **fanned out per layer** (e.g. data / api / ui / config at once). Findings merge into a single **Analysis Summary**; intermediate reads stay in the delegates so the main context stays clean.
- **`single`** (brownfield, one layer / flat source): a single **`context-analyst`** sub-agent.
- **`greenfield_inline`** (no existing code to explore): build the **Analysis Summary inline** — **do not spawn a `context-analyst` with nothing to read**. Call `context-analyst` only when there is a real, existing codebase. For a trivial greenfield there is nothing to parallelize; keep it light rather than opening a pointless sub-agent.

Produce the **Analysis Summary** (`templates.md`): problem · current vs expected behavior · affected files/modules · existing tests · risks · initial hypothesis. ⇉ can run alongside step 6.
Manual file reads, `ls`, `Glob`, or a direct `pytest` discovery run are useful after the detector, but they do not satisfy this step by themselves.

### 4. Spec phase (WHAT) — Claude Code workflow or runtime adapter
In Claude Code, invoke the **`Workflow` tool** for **`agentic-sdlc:spec-plan-draft`** with `args:{ mode:'spec', context:<analysis + scope> }`. It is a **2-step conversational loop**: `spec-plan-author` drafts → `spec-plan-critic` adversarially audits (missing criteria/edge-cases, HOW-leak, contradictions) → author revises (≤2 rounds) → closing audit. Returns a spec draft + **decision points**.
In Codex, do not call standalone `spec-authoring`. Draft the spec inside agentic-sdlc-pipeline using `contracts/skills/02-spec-driven-development.md` and the `spec-plan-author` role instructions, then run a fresh-context critic pass with `spec-plan-critic` instructions when available. Revise up to two rounds; if fresh-context specialists are unavailable, mark the degraded path and perform the critic pass inline. Spec = the WHAT only (no files/layers/tasks/code), per the **Spec** template (`templates.md`).
Use the named workflow only in Claude Code. Do not create an ad hoc Workflow script for spec drafting.
**Spec Review gate:** resolve the decision points WITH the user (AskUserQuestion); a spec with unresolved decisions or untestable criteria does not pass. On approval, **write the spec to `docs/agentic-sdlc/specs/<work_id>.md`** (create the folder if missing) with `work_id` and `status` frontmatter, then run `python "<runtime-root>/scripts/validate_artifacts.py" --mode spec --file docs/agentic-sdlc/specs/<work_id>.md`. The validator must pass before the review gate can be treated as approved, including automated smoke evals. This file is the authoritative WHAT for the rest of the flow.

### 5. Plan phase (HOW) — Claude Code workflow or runtime adapter
After the spec file is approved, in Claude Code invoke the **`Workflow` tool** for **`agentic-sdlc:spec-plan-draft`** with `args:{ mode:'plan', context:<approved spec> }` — same 2-step author⇄critic conversation. Returns the technical task list (Task 1..N), file-level change map, dependency order, and per-behavior RED-test points, covering **every** acceptance criterion of the spec.
In Codex, do not call standalone `plan-authoring`. Draft the plan inside agentic-sdlc-pipeline using `contracts/skills/03-plan-mode.md`, the approved spec, and the `spec-plan-author` role instructions; then run the same fresh-context critic/revise adapter. Use the named workflow only in Claude Code. Do not create an ad hoc Workflow script for plan drafting.
**Plan Review gate:** user approval (contract 03); large/architectural plans need explicit approval. On approval, **write the plan to `docs/agentic-sdlc/plans/<work_id>.md`** (same work_id as the spec) with `work_id`, `spec`, `branch`, and `status` frontmatter, then run `python "<runtime-root>/scripts/validate_artifacts.py" --mode plan --file docs/agentic-sdlc/plans/<work_id>.md --spec docs/agentic-sdlc/specs/<work_id>.md --strict`. The validator must pass before implementation starts, including automated smoke evals. From here the implementation phase follows **`docs/agentic-sdlc/specs/<work_id>.md` + `docs/agentic-sdlc/plans/<work_id>.md` faithfully** — no scope drift, no undocumented change; a new finding becomes a new task appended to the plan file, not a silent diff.

### 6. Context7 doc verification — agentic-sdlc-pipeline, fan-out per library
**Mandatory** for: new package, working against an existing package API, framework upgrade, RN/Expo native change, Supabase Auth/RLS/Edge/Realtime/Storage, EF Core migration/query, Next/React/Node/TS config, JWT/OAuth/session/cookie, any security-sensitive dependency. List affected libraries → detect the version in use → verify against current docs via **Context7** (`resolve-library-id` → `query-docs`): method names, parameter order, async behavior, deprecations, security notes, breaking changes, env-var/config names, platform (Android/iOS) and server/client splits. **⇉ fan out across N libraries**: Claude Code may use a dynamic workflow; non-Claude runtimes should use subagent fan-out, parallel web/doc checks, or the best available runtime-native equivalent. **Fallback:** if Context7 is unavailable or its quota is exhausted (rate-limit / error), fall back to the runtime's web search/fetch tools against the library's **official** docs (version-matched site/repo — not random blogs/SO), and note in the report that the source was the web-search fallback. Output: **Documentation Verification** report. Never invent an API or trust an old blog/SO answer over verified docs.
**Context-fit escape (Step-1-symmetric):** first classify with **`python "<runtime-root>/scripts/detect_context.py" --path <scope> --probe deps`**. If `deps_probe=stdlib_only` (no third-party manifest), there is no external API to verify → **skip the Context7 fan-out and write "stdlib / zero-dep — Context7 n/a" in the report** instead of running it on nothing. This is the "unnecessary in this context" branch, distinct from the "Context7 quota out → WebSearch" fallback above.

### 7. Risk & scope lock — agentic-sdlc-pipeline
Produce **Risk & Scope Lock** (`templates.md`): In Scope · Out of Scope · Files-allowed-to-change · Files-read-only · Risk areas (migration, backward-compat, API contract, security, perf, test-break, mobile, deploy, secret-exposure) · Rollback plan · Verification plan. Then lock the end-state with the runtime goal tool when available; otherwise write the Goal Lock template inline and treat it as the scope lock.
**Active-goal escape (runtime check):** if the session already has an active runtime goal — e.g. agentic-sdlc-pipeline is nested inside another goal-managed flow — do **not** overwrite it. Lock this scope manually (or ask the user) and note that the existing goal was preserved. (Conflict is not the same as unavailable.)

### 14. Security analysis #2 (final diff) — agentic-sdlc-pipeline · `security-audit`
After refactor + green tests, re-audit the **final diff** (not just the first implementation): new endpoints have authZ?, new queries have tenant/owner filter (IDOR)?, new DTOs over-expose?, new logs leak secrets/PII?, new env vars in `.env.example`?, new dependency safe?, migration destructive?, native permission change safe?, RLS affected?, JWT/session handling correct? **⇉ fan lenses** (injection / authz-IDOR / secrets / data-exposure) via Claude workflow/agent-team or the runtime's subagent/parallel equivalent. Output: **Final Security Analysis**. Loop: finding → fix → re-check → retest.
**Refactor-conditioned (skip + document):** Security #2's value is re-auditing the diff **as changed by the refactor** (step 12). If the refactor was a **no-op** (it changed nothing), the final diff equals the Security #1 surface → record "no refactor delta; Security #2 == #1" and skip the duplicate pass. Any refactor that actually touched the diff → run the full final-diff audit.

### 15. Lint / typecheck / build / secret-scan — agentic-sdlc-pipeline, ⇉ parallel
Run independent gates in parallel when the runtime supports it: Claude workflow for large fan-out; non-Claude runtimes use parallel local tool calls, subagent fan-out, or the best available native equivalent. Pick per stack: Node/TS `lint`+`typecheck`+`build`; .NET `dotnet build`+`dotnet format --verify-no-changes`; Python `ruff`+`mypy`. Secret-scan: `git diff --check` and, if present, `gitleaks` / `trufflehog` / `detect-secrets`. Looking for: API keys, JWT secret, Supabase service-role key, DB connection string, private key, OAuth secret, SMTP password, access/refresh token, committed `.env`, certs. Fixing lint: **formatting only, no behavior change**; fixing types: avoid gratuitous `any` / `!` / `as unknown as`. Output: **Quality Gates** report.
**Context-fit escape (Step-1-symmetric):** classify first with **`python "<runtime-root>/scripts/detect_context.py" --path <scope> --probe toolchain`**. If `toolchain_probe=absent` (no build/lint/typecheck tooling — e.g. a zero-dep vanilla script), mark the missing gates **N/A and say so in the report** rather than inventing a toolchain. Still run the secret-scan (it is tool-independent).

### 16. Git diff review — agentic-sdlc-pipeline · `git-safety-check`
`git status --short` → `git diff --stat` → `git diff`. Run the read-only **`/git-safety-check`** command. Confirm: change matches spec, no out-of-plan files, no formatting noise, no secrets, no debug logs / commented-out code, tests meaningful, no unintended breaking change, `.env.example` updated, docs touched if needed. Output: **Diff Review** report.

### Implementation control (gate before commit) — `implementasyon-control`
Run the **`implementasyon-control`** skill as the master pre-final audit (the core work-flow also runs it internally; here it is the gate before any git commit). The audit must include a passing `resolve_work_package.py` result and adherence to `docs/agentic-sdlc/specs/<work_id>.md` + `docs/agentic-sdlc/plans/<work_id>.md`: every acceptance criterion implemented, no undocumented scope, every plan task done or consciously deferred. Gap → complete the step → re-run. Critical gap → **do not commit, do not finalize.**

### 17–21. Commit → Push → PR → Merge → Re-sync (git) — all approval-gated
- **17 Commit:** only after gates green + diff reviewed + user approval. Conventional Commits: `fix(auth): validate duplicate email on registration`. No Claude co-author trailer unless asked. No `git add -A` blanket staging — stage reviewed files. Report hash + message.
- **18 Push:** `git push -u origin <branch>`. Confirm correct branch, not main, no secret warnings.
- **19 PR/MR:** fill the **PR description** template (`templates.md`): summary, problem, solution, changes, tests, security, risk, rollback, checklist.
- **20 Merge:** only after review + local gates green, no conflicts, branch current with main, **explicit user approval** for production-impacting merges. Strategy per team standard (squash / merge / rebase).
- **21 Re-sync local main:** `git checkout <main>` → `git pull --ff-only`. Optional branch cleanup only if team standard allows. Output: **Final Sync** in the report.

### Branch finishing checkpoint
Before cleanup, present the actual state: branch name, commits, changed files, test/security evidence, open risks, and whether a worktree was used. Offer only valid next actions: keep branch, create PR, merge after approval, or discard. Destructive discard/cleanup requires explicit typed confirmation and must only target the owned branch/worktree path.

---

## Delegated core steps (8,9,10,11,12,13)
These belong to the chosen work-flow skill, which agentic-sdlc-pipeline invokes through the `Skill` tool with the approved `docs/agentic-sdlc/specs/<work_id>.md` + `docs/agentic-sdlc/plans/<work_id>.md` paths. The core work-flow implements **faithfully** to them; agentic-sdlc-pipeline only ensures they happen and their gates pass:
- **8 RED / 9 GREEN / 10 loop** — TDD: failing test first (show RED) → minimal code (GREEN) → runtime loop tool or manual Loop Iteration artifact until green (contract 05).
- **11 Security #1** — diff-level security pass (contract 06).
- **12 Refactor / 13 Retest** — behavior unchanged, full suite green with output (contract 07).
- **Fidelity:** any divergence from the spec/plan files is a finding — append a new task to the plan file, never an undocumented diff.
- **Test-runner gotcha (Node):** `node --test <dir>` can treat the path as a single *module* and silently discover nothing — pass a glob instead, e.g. `node --test "**/*.test.js"` (quote it so the shell doesn't pre-expand). Confirm the runner actually collected tests (a "0 tests" run is a red flag, not a pass).

The selected core work-flow Skill call is the handoff gate. For feature work, call `Skill` -> `agentic-sdlc:feature-build` before adding tests or editing production code. If implementation starts without that tool call, the flow is red even if later tests pass.

---

## Lite Mode
Only for low-risk work: typo, small README edit, simple UI-text change, comment fix, formatting, minor non-production config. **Forbidden** for auth, payment, security, DB migration, production bug, API contract, permission/role, user-data handling, native mobile permission, token/session, Supabase RLS — those are always Full.

Lite steps (own short track, not the Full 1–21): branch check · short analysis · scope note · change · relevant test/lint · diff review · commit (on approval) · push/PR (on approval).

## Parallel-execution rules (how the ⇉ steps run)
- Genuinely-independent steps run **concurrently**; gated/dependent steps stay ordered. `dispatch-strategy` chooses the mechanism each time.
- Keep one TodoWrite item per active step; a fanned-out step may spawn its own sub-items but the parent stays `in_progress` until all branches return and the gate passes.
- Fan-out examples: Context7 across libraries (6), security lenses (11/14), quality gates (15), multi-file generation in 9. Sequence 4→5→8→9→10 is **never** parallelized.
