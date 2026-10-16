# agentic-sdlc-pipeline — Playbook (step detail)

Detailed reference for `agentic-sdlc-pipeline/SKILL.md`. The SKILL.md table is the spine; this file is the WHAT-each-step-means. agentic-sdlc-pipeline runs every step itself: Steps 8–13 follow the selected work-type core file, and the security and implementation-control gates dispatch read-only agents.

## Tool-call contract
Full Mode is not satisfied by inline summaries of other skills or roles. Use `<runtime-root>/docs/runtime-adapter.md` for portable capability names and runtime-specific equivalents. In Claude Code, agentic-sdlc-pipeline must call:
- `Skill` -> `agentic-sdlc:dispatch-strategy` before the first read, shell command or write. Within one pipeline run, call `dispatch-strategy` once at Step 1 and reuse that mechanism map for every later heavy, independent, or parallel step.
- Branch/HEAD receipts proving a work branch before the first write, as in step 2 (both runtimes).
- `Bash`/`PowerShell` -> `python3 "<runtime-root>/scripts/detect_context.py" --path <scope>` before replacing exploration decisions with file reads.
- `Workflow` -> `agentic-sdlc:spec-plan-draft` for step 4 (`mode:"spec"`) and step 5 (`mode:"plan"`).
- Grok CLI: `/workflow spec-plan-draft` or the `workflow` tool with name `spec-plan-draft` (same args) when `.grok/workflows/spec-plan-draft.rhai` is in the catalog; otherwise `spawn_subagent` author -> critic -> revise. Do not call Claude JS `Workflow` on Grok.
- `Bash`/`PowerShell` -> `python3 "<runtime-root>/scripts/validate_artifacts.py"` after saving the spec and plan artifacts.
- `Read` -> the selected work-type core file after the plan is approved and before the first test edit (see **Work-type core steps (8–13)** below).
- `Agent` -> `security-reviewer` for Steps 11 and 14 (one call for all four lenses, or one call per lens when the Step 1 map fans out); the returned findings table is the gate, not the dispatch.
- `Bash`/`PowerShell` -> `python3 "<runtime-root>/scripts/resolve_work_package.py"`, then `Agent` -> `implementation-auditor` with the dispatch prompt in **Implementation control** below, before finalizing.
- `Skill` -> `agentic-sdlc:completion-claim-gate` before any success/completion/ready claim.

In Codex, the other supported runtime, Claude Code `Workflow` calls are not available. Keep `spec-authoring` and `plan-authoring` as independent entry skills; agentic-sdlc-pipeline does not invoke them for steps 4-5. Instead, agentic-sdlc-pipeline runs the embedded adapter:
- Draft the spec/plan in the main loop using `spec-plan-author` role instructions and contracts 02/03.
- Run a fresh-context critic pass with the runtime's subagent/specialist mechanism using `spec-plan-critic` instructions wherever the runtime exposes a subagent mechanism (mandatory there).
- Revise up to two rounds, save the artifact, then run `validate_artifacts.py`.
- If fresh-context specialists are unavailable, record `Delegation Degraded: fresh-context specialist unavailable` and perform the critic pass inline.
- Read the selected work-type core file before Step 8, and run `security-reviewer` and `implementation-auditor` as fresh-context subagents with `<runtime-root>/agents/security-reviewer.md` and `<runtime-root>/agents/implementation-auditor.md` instructions; print each findings table and the auditor verdict as assistant text.
- Emit `Runtime: Codex` once and `Codex Adapter Gate: <gate>` for dispatch-strategy (once), spec-plan-draft author/critic, the work-type core read, security-reviewer, implementation-auditor, and completion-claim-gate, with the exact marker text of the SKILL.md Codex list. If Codex lacks a native transcript event, record `Delegation Degraded: native Skill transcript events unavailable`; this means the transcript event is unavailable, not that the step itself may be skipped.
- Do not run recursive cleanup deletes for generated caches such as `__pycache__` during Codex pipeline/eval runs. Leave or report them; cleanup is not a pipeline gate.

Resolve `<runtime-root>` exactly as the **Plugin root** rule in `agentic-sdlc-pipeline/SKILL.md` defines it (the installed folder two levels above that `SKILL.md`, never the working directory; stop with `plugin root unresolved` when it cannot be confirmed). This file is read as plain text, so a `${…}` token here is never substituted.

If a tool is missing in the runtime, record `Delegation Degraded: <tool/name>` and continue with the smallest safe fallback. If the tool exists, skipping the call is a failed gate. Manual Read/Glob/ls exploration does not replace `detect_context.py`; manual review text does not replace `validate_artifacts.py`; test and code edits made without the work-type core read, the bare RED/GREEN runs, or the TDD evidence file do not satisfy Steps 8–13.

For explicit automated smoke evals, add `depth:"smoke"` and `maxRevisionRounds:0` to the `spec-plan-draft` args. Do not use smoke depth for normal product work. Smoke depth shortens only the workflow's author/critic loop; it does not skip the branch checkpoint, context detection, artifact validation, the work-type core read, the bare RED/GREEN runs and the TDD evidence file, the completed `security-reviewer` and `implementation-auditor` results, or completion-claim-gate. Dependency-install approval boundaries still apply.

Call-order rule: `dispatch-strategy` is the first delegate call before Read/Bash/Edit/Write work. `completion-claim-gate` is the last delegate call immediately before the final report. These two are required even for smoke evals and small single-file changes.

## Work type → core file
| Symptom | Work type | Core file | agentic-sdlc-pipeline adds around it |
|---|---|---|---|
| Bug / error / broken behavior / prod issue | `bugfix` | `<runtime-root>/skills/root-cause-fix/references/core.md` | git envelope, Context7, scope-lock, 2nd security, quality gates |
| New feature / endpoint / capability | `feature` | `<runtime-root>/skills/feature-build/references/core.md` | same envelope |
| Behavior-preserving restructure | `refactor` | `<runtime-root>/skills/safe-refactor/references/core.md` | characterization-test guard + envelope |
| Test coverage only | `test-only` | `<runtime-root>/skills/test-authoring/references/core.md` | envelope (usually no migration/git-PR) |

agentic-sdlc-pipeline **owns the Spec and Plan phases directly** (steps 4–5). Claude Code uses the `spec-plan-draft` workflow with review gates; Grok CLI uses `/workflow spec-plan-draft` when the project-catalog Rhai script is present, otherwise `spawn_subagent` author/critic/revise; Codex uses the embedded author/critic adapter because the Claude Workflow runtime is not available there. agentic-sdlc-pipeline persists the artifacts to **`docs/agentic-sdlc/specs/`** and **`docs/agentic-sdlc/plans/`**, then runs Steps 8–13 from the core file — RED → GREEN → loop → security #1 → refactor → retest — **faithfully to those two files**, never re-drafting them. The core file holds only the work-type rules and steps; the envelope (mechanism map, spec/plan, scope lock, approval, final audit, final report) stays here.

---

## Outer steps agentic-sdlc-pipeline owns directly

### 1. Update main (git) — approval-gated, no-op if not a repo
`git status --short` + `git branch --show-current`. If tree clean and a repo: `git checkout <main>` → `git pull --ff-only origin <main>` (detect real default branch: main/master/develop). **Forbidden without explicit user approval:** `reset --hard`, `clean -fdx`, `stash drop`, `push --force`. Report: active branch, working-tree state, main up-to-date?, safe-to-proceed?

### 2. Confirm a work branch before writing (git)
Reuse an appropriate existing work branch; do not switch away from unrelated uncommitted work. On main/master or detached HEAD, create a scoped branch with `git checkout -b <name>`, then record `git branch --show-current` and `git rev-parse HEAD` before any artifact, test or source write. Name by work type: `fix/login-validation`, `feature/notification-settings`, `refactor/order-validation`, `security/rls-hardening`, `chore/update-deps`. Routine local branch creation is part of an implementation request unless the user restricts it; an instruction not to commit/push/merge still permits the work branch. Those publication operations remain separately approval-gated. Report branch + parent commit. Without Git, record the branch checkpoint as inapplicable; without a remote, record the remote update as inapplicable rather than claiming it ran. This checkpoint also applies to smoke evals.

### 2a. Optional worktree isolation — use for risky or parallel work
For large, risky, or parallelizable implementation, prefer an isolated git worktree after branch creation. Use native Claude Code worktree support if available; otherwise use `git worktree add <path> <branch>` with explicit user approval. Record the original repo path, worktree path, branch, and cleanup plan. Do not create a worktree for small single-session changes, non-git workspaces, or tasks where isolation adds no value.

### 3. Analyze code & problem — `detect_context.py` first, then branch
Classify the workspace **deterministically** before choosing how to explore — don't guess. Run **`python3 "<runtime-root>/scripts/detect_context.py" --path <scope>`** (repeat `--path` per root; stdlib, exits 0) and branch on `explore_mode`:
- **`parallel`** (brownfield, ≥2 layers listed in `layers=`): explore the project **layers concurrently**. Per the Step 1 mechanism map, use an agent-team or one `context-analyst` sub-agent **fanned out per layer** (e.g. data / api / ui / config at once). Findings merge into a single **Analysis Summary**; intermediate reads stay in the delegates so the main context stays clean.
- **`single`** (brownfield, one layer / flat source): a single **`context-analyst`** sub-agent.
- **`greenfield_inline`** (no existing code to explore): build the **Analysis Summary inline** — **do not spawn a `context-analyst` with nothing to read**. Call `context-analyst` only when there is a real, existing codebase. For a trivial greenfield there is nothing to parallelize; keep it light rather than opening a pointless sub-agent.

Produce the **Analysis Summary** (`templates.md`): problem · current vs expected behavior · affected files/modules · existing tests · risks · initial hypothesis. ⇉ can run alongside step 6.
Manual file reads, `ls`, `Glob`, or a direct `pytest` discovery run are useful after the detector, but they do not satisfy this step by themselves.

### 4. Spec phase (WHAT) — Claude Code workflow or runtime adapter
In Claude Code, invoke the **`Workflow` tool** for **`agentic-sdlc:spec-plan-draft`** with `args:{ mode:'spec', context:<analysis + scope>, pluginRoot:'<runtime-root>' }`. It is a **2-step conversational loop**: `spec-plan-author` drafts → `spec-plan-critic` adversarially audits (missing criteria/edge-cases, HOW-leak, contradictions) → author revises (≤2 rounds) → closing audit. Returns a spec draft + **decision points**.
On Grok CLI, invoke `/workflow spec-plan-draft` or the `workflow` tool with name `spec-plan-draft` and the same args when `.grok/workflows/spec-plan-draft.rhai` is in the catalog. Do not call Claude JS `Workflow`. If that catalog script is unavailable, `spawn_subagent` author -> critic -> revise.
In Codex, do not call standalone `spec-authoring`. Draft the spec inside agentic-sdlc-pipeline using `<runtime-root>/contracts/skills/02-spec-driven-development.md` and the `spec-plan-author` role instructions, then run a fresh-context critic pass with `spec-plan-critic` instructions when available. Revise up to two rounds; if fresh-context specialists are unavailable, mark the degraded path and perform the critic pass inline. Spec = the WHAT only (no files/layers/tasks/code), per the **Spec** template (`templates.md`).
Use the named Claude workflow only in Claude Code. Do not create an ad hoc Claude JS Workflow script for spec drafting.
**Spec Review gate:** write the spec to `docs/agentic-sdlc/specs/<work_id>.md` (create the folder if missing) with `work_id` and `status` frontmatter, then run `python3 "<runtime-root>/scripts/validate_artifacts.py" --mode spec --file docs/agentic-sdlc/specs/<work_id>.md`. The validator must pass before the review gate can be treated as approved, including automated smoke evals. Resolve the decision points WITH the user (AskUserQuestion); a spec with unresolved decisions or untestable criteria does not pass.
**Approval receipt.** Save the spec (and later the plan) with `status: reviewed` and validate it. Set `status: approved` only after the user approves that Review gate — in a later turn or as an `AskUserQuestion` answer — or when the original request explicitly pre-approves the Review gates. Under pre-approval, resolve each decision point by adopting its recommendation and list it in the gate message; a decision point with no recommendation, or whose options change scope or behaviour that the request does not settle, stays unresolved and stops at the gate. A critic contradiction — a `residualCriticNotes` item that names a contradiction or a hard blocker (on Codex: an issue from the critic's last round) — stops at the gate even under pre-approval. If no answer can be obtained, end the turn with a message that names the Spec Review (or Plan Review) gate, the artifact path and the open decision points. Never treat silence or a tool error as approval. Quote any pre-approval text in the gate message. While the spec or plan is `draft` or `reviewed`, make no source or test edit — stop at the gate and ask.
This file is the authoritative WHAT for the rest of the flow.

### 5. Plan phase (HOW) — Claude Code workflow or runtime adapter
After the spec file is approved, in Claude Code invoke the **`Workflow` tool** for **`agentic-sdlc:spec-plan-draft`** with `args:{ mode:'plan', context:<approved spec>, pluginRoot:'<runtime-root>' }` — same 2-step author⇄critic conversation. Returns the technical task list (Task 1..N), file-level change map, dependency order, and per-behavior RED-test points, covering **every** acceptance criterion of the spec.
On Grok CLI, invoke `/workflow spec-plan-draft` or the `workflow` tool with name `spec-plan-draft` and the same args when the catalog script is present; otherwise `spawn_subagent` author -> critic -> revise. Do not call Claude JS `Workflow`.
In Codex, do not call standalone `plan-authoring`. Draft the plan inside agentic-sdlc-pipeline using `<runtime-root>/contracts/skills/03-plan-mode.md`, the approved spec, and the `spec-plan-author` role instructions; then run the same fresh-context critic/revise adapter. Use the named Claude workflow only in Claude Code. Do not create an ad hoc Claude JS Workflow script for plan drafting.
**Plan Review gate:** user approval (contract 03); large/architectural plans need explicit approval. Write the plan to `docs/agentic-sdlc/plans/<work_id>.md` (same work_id as the spec) with `work_id`, `spec`, `branch`, and `status` frontmatter, then run `python3 "<runtime-root>/scripts/validate_artifacts.py" --mode plan --file docs/agentic-sdlc/plans/<work_id>.md --spec docs/agentic-sdlc/specs/<work_id>.md --strict`. The validator must pass before implementation starts, including automated smoke evals. The **Approval receipt** above applies to the plan unchanged: no test or source edit until the plan is `approved`. From here the implementation phase follows **`docs/agentic-sdlc/specs/<work_id>.md` + `docs/agentic-sdlc/plans/<work_id>.md` faithfully** — no scope drift, no undocumented change; a new finding becomes a new task appended to the plan file, not a silent diff.

### 6. Context7 doc verification — agentic-sdlc-pipeline, fan-out per library
**Mandatory** for: new package, working against an existing package API, framework upgrade, RN/Expo native change, Supabase Auth/RLS/Edge/Realtime/Storage, EF Core migration/query, Next/React/Node/TS config, JWT/OAuth/session/cookie, any security-sensitive dependency. List affected libraries → detect the version in use → verify against current docs via **Context7** (`resolve-library-id` → `query-docs`): method names, parameter order, async behavior, deprecations, security notes, breaking changes, env-var/config names, platform (Android/iOS) and server/client splits. **⇉ fan out across N libraries**: Claude Code may use a dynamic workflow; non-Claude runtimes should use subagent fan-out, parallel web/doc checks, or the best available runtime-native equivalent. **Fallback:** if Context7 is unavailable or its quota is exhausted (rate-limit / error), fall back to the runtime's web search/fetch tools against the library's **official** docs (version-matched site/repo — not random blogs/SO), and note in the report that the source was the web-search fallback. Output: **Documentation Verification** report. Never invent an API or trust an old blog/SO answer over verified docs.
**Context-fit escape (Step-1-symmetric):** first classify with **`python3 "<runtime-root>/scripts/detect_context.py" --path <scope> --probe deps`**. If `deps_probe=stdlib_only` (no third-party manifest), there is no external API to verify → **skip the Context7 fan-out and write "stdlib / zero-dep — Context7 n/a" in the report** instead of running it on nothing. This is the "unnecessary in this context" branch, distinct from the "Context7 quota out → WebSearch" fallback above.

### 7. Risk & scope lock — agentic-sdlc-pipeline
Produce **Risk & Scope Lock** (`templates.md`): In Scope · Out of Scope · Files-allowed-to-change · Files-read-only · Risk areas (migration, backward-compat, API contract, security, perf, test-break, mobile, deploy, secret-exposure) · Rollback plan · Verification plan. Then lock the end-state with the runtime goal tool when available; otherwise write the Goal Lock template inline and treat it as the scope lock.
**Active-goal escape (runtime check):** if the session already has an active runtime goal — e.g. agentic-sdlc-pipeline is nested inside another goal-managed flow — do **not** overwrite it. Lock this scope manually (or ask the user) and note that the existing goal was preserved. (Conflict is not the same as unavailable.)

### 14. Security analysis #2 (final diff) — agentic-sdlc-pipeline · `Agent(security-reviewer)`
After refactor + green tests, dispatch `Agent(security-reviewer)` on the **final diff** (not just the first implementation). **⇉ lenses** — injection / authz-IDOR / secrets / auth: one call for all four lenses, or one call per lens when the Step 1 map fans out. Each checklist item has a lens owner (the role's `## Lenses`): new endpoints have authZ?, new queries have tenant/owner filter (IDOR)?, new DTOs over-expose?, native permission change safe?, RLS affected? → `authz-IDOR`; new logs leak secrets/PII? → `secrets`; JWT/session handling correct? → `auth`; untrusted input reaching a query, command or path → `injection`; new env vars in `.env.example`?, new dependency safe?, migration destructive? → whichever lens sees the manifest or migration file. A lens reported incomplete is not a clean review. Print each findings table as assistant text. Output: **Final Security Analysis**. Loop: finding → fix → re-run the reviewer → retest.
**Change-conditioned (skip + document):** Security #2 re-audits the diff as it stands after Steps 12–13. Skip it only when nothing changed since the last Step 11 result — no refactor delta, no retest fix, no documentation edit: the final diff then equals the Security #1 surface → record "no change since Security #1; Security #2 == #1" and skip the duplicate pass. Any change since that result → run the full final-diff audit.

### 15. Lint / typecheck / build / secret-scan — agentic-sdlc-pipeline, ⇉ parallel
Run independent gates in parallel when the runtime supports it: Claude workflow for large fan-out; non-Claude runtimes use parallel local tool calls, subagent fan-out, or the best available native equivalent. Pick per stack: Node/TS `lint`+`typecheck`+`build`; .NET `dotnet build`+`dotnet format --verify-no-changes`; Python `ruff`+`mypy`. Secret-scan: `git diff --check` and, if present, `gitleaks` / `trufflehog` / `detect-secrets`. Looking for: API keys, JWT secret, Supabase service-role key, DB connection string, private key, OAuth secret, SMTP password, access/refresh token, committed `.env`, certs. Fixing lint: **formatting only, no behavior change**; fixing types: avoid gratuitous `any` / `!` / `as unknown as`. Output: **Quality Gates** report.
**Context-fit escape (Step-1-symmetric):** classify first with **`python3 "<runtime-root>/scripts/detect_context.py" --path <scope> --probe toolchain`**. If `toolchain_probe=absent` (no build/lint/typecheck tooling — e.g. a zero-dep vanilla script), mark the missing gates **N/A and say so in the report** rather than inventing a toolchain. Still run the secret-scan (it is tool-independent).

### 16. Git diff review — agentic-sdlc-pipeline · `git-safety-check`
`git status --short` → `git diff --no-ext-diff --no-textconv --stat` → `git diff --no-ext-diff --no-textconv` (no repository-configured diff program runs or rewrites what you review). Run the read-only **git-safety-check** command. Confirm: change matches spec, no out-of-plan files, no formatting noise, no secrets, no debug logs / commented-out code, tests meaningful, no unintended breaking change, `.env.example` updated, docs touched if needed. Output: **Diff Review** report.

### Implementation control (gate before commit) — `resolve_work_package.py` + `Agent(implementation-auditor)`
The master pre-final audit and the gate before any git commit. Run it after the last source edit, once the TDD evidence file is complete.
1. Run `python3 "<runtime-root>/scripts/resolve_work_package.py" --plan <plan path>` (or `--spec <spec path>`) and keep its stdout and exit code. A failed or ambiguous resolution blocks the gate; never guess the package.
2. Dispatch `Agent(implementation-auditor)` — fresh context, read-only — with a prompt carrying these labelled sections, in this order:
   - `Resolver output:` the verbatim resolver stdout and its exit code.
   - `Spec:` / `Plan:` the two artifact paths.
   - `TDD evidence:` the TDD evidence file path; the auditor opens it with `Read` (or the runtime's file-reading tool).
   - `Diff:` the output of `git diff --no-ext-diff --no-textconv`. Above about 400 lines, send `git diff --no-ext-diff --no-textconv --stat` plus the changed-file list instead, and tell the auditor to read those files.
   - `Security reviews:` the `security-reviewer` findings tables from Steps 11 and 14, or the documented Step 14 skip note.
   - `Branch receipts:` the `git branch --show-current` and `git rev-parse HEAD` output recorded before the first write.
   - `Envelope reports:` the Analysis Summary, the Goal Lock text, the Quality Gates report, the Diff Review report and the Loop Iteration records (or "none").
3. Print the auditor verdict (`## Overall Status`, `## Final Decision`) as assistant text. The audit must confirm adherence to `docs/agentic-sdlc/specs/<work_id>.md` + `docs/agentic-sdlc/plans/<work_id>.md`: every acceptance criterion implemented, no undocumented scope, every plan task done or consciously deferred.
4. `block-final` means do not finalize: close the gap, then re-run steps 1–3; a source edit while closing it re-opens Steps 13–14 first. Critical gap → **do not commit, do not finalize.**

### Finalize: persist per-package evidence — main flow, not the auditor
Work-package artifacts live in two layouts: the legacy flat `docs/agentic-sdlc/{specs,plans}/<id>.md` (back-compat, unchanged) and the per-package canonical `docs/agentic-sdlc/<slug>/{spec,plan,evidence}/<work_id>.md`, where `<slug>` is lowercase kebab-case `^[a-z0-9][a-z0-9-]{0,63}$` and never a reserved name (`specs`, `plans`, `evidence`, `notes`, `spec`, `plan`). Per-package plan change-detection is a filesystem scan, not a `git status` query: new generated plans can be git-ignored, so the resolver scans the filesystem; published plugin documentation is tracked separately.

On Finalize, persist the Final Implementation Report — Final Report + Security Analysis #1/#2 + Git Diff Review + test-run output — to `docs/agentic-sdlc/<slug>/evidence/<work_id>.md`, **per-package only** (flat packages get no Finalize evidence), using the slug emitted by `resolve_work_package.py` (BR14/AC23; never re-derived from the title). A re-run for the same `<slug>`/`<work_id>` **overwrites** this single canonical file in place (AC24; last run wins, no timestamp suffix, so stale per-run secrets do not accumulate). Evidence is git-ignored and has **no validator** — it never gates resolution (AC12). This write is performed by the **main pipeline finalize step** (the orchestrating context), not the read-only `implementation-auditor` sub-agent, which receives the resolver output, the diff and the TDD evidence path in its dispatch prompt and writes nothing.

### 17–21. Commit → Push → PR → Merge → Re-sync (git) — all approval-gated
- **17 Commit:** only after gates green + diff reviewed + user approval. Conventional Commits: `fix(auth): validate duplicate email on registration`. No Claude co-author trailer unless asked. No `git add -A` blanket staging — stage reviewed files. Report hash + message.
- **18 Push:** `git push -u origin <branch>`. Confirm correct branch, not main, no secret warnings.
- **19 PR/MR:** fill the **PR description** template (`templates.md`): summary, problem, solution, changes, tests, security, risk, rollback, checklist.
- **20 Merge:** only after review + local gates green, no conflicts, branch current with main, **explicit user approval** for production-impacting merges. Strategy per team standard (squash / merge / rebase).
- **21 Re-sync local main:** `git checkout <main>` → `git pull --ff-only`. Optional branch cleanup only if team standard allows. Output: **Final Sync** in the report.

### Branch finishing checkpoint
Before cleanup, present the actual state: branch name, commits, changed files, test/security evidence, open risks, and whether a worktree was used. Offer only valid next actions: keep branch, create PR, merge after approval, or discard. Destructive discard/cleanup requires explicit typed confirmation and must only target the owned branch/worktree path.

---

## Work-type core steps (8–13)
Read `<runtime-root>/skills/<skill>/references/core.md` for the selected work type before Step 8 and run its core steps as Steps 8–13. The core's security step is Step 11 and runs through `Agent(security-reviewer)`; its refactor step is Step 12; its retest is Step 13; a root-cause-fix core "Final Review" is satisfied by Step 16; a feature-build core "Documentation" step runs before Step 14.

The main loop runs these steps itself, **faithfully** to the approved `docs/agentic-sdlc/specs/<work_id>.md` + `docs/agentic-sdlc/plans/<work_id>.md`:
- **Core read first.** Read the core file (Claude Code: `Read`; Codex: the file-reading tool) before the first test or source edit, and reload it after resume or compaction. An edit before the read leaves Steps 8–13 red even if later tests pass.
- **RED → GREEN order (feature / bugfix).** First test edit → a bare test run that exits non-zero → first production edit → a bare run that exits 0. **Refactor:** a green characterization run before the first edit, and green after each step. **Test-only:** no lasting production change; show the failure under a temporary mutation — reverted before Step 11 and recorded as a MUTATION run, the one allowed exception — or capture a baseline.
- **Bare commands.** Run each test command on its own: no `| tail`, no `; echo`, no `|| true`. A piped or echoed run cannot be attributed, so it counts as neither RED nor GREEN.
- **11 Security #1** — `Agent(security-reviewer)` on the current diff, same lenses as Step 14 (contract 06). **12 Refactor / 13 Retest** — behavior unchanged, full suite green with output (contract 07).
- **Fidelity:** any divergence from the spec/plan files is a finding — append a new task to the plan file, never an undocumented diff.
- **Test-runner gotcha (Node):** `node --test <dir>` can treat the path as a single *module* and silently discover nothing — pass a glob instead, e.g. `node --test "**/*.test.js"` (quote it so the shell doesn't pre-expand). Confirm the runner actually collected tests (a "0 tests" run is a red flag, not a pass).

**TDD evidence file.** Only the main loop writes it: `docs/agentic-sdlc/<slug>/evidence/<work_id>.tdd.md` for a per-package work package, `docs/agentic-sdlc/evidence/<work_id>.tdd.md` for a flat one. The slug is the `<slug>` directory the spec and plan were saved in. Run the test bare. Then write its block with the file-edit tool (Claude Code `Write`/`Edit`; Codex `apply_patch`), never with a shell redirect, `tee` or `tail`. Copy the last ≤20 lines from the bare run's output. Append every test run from Step 8 until the auditor is dispatched, including retests. Only a new pipeline run for the same work_id starts the file fresh. The file is complete before `Agent(implementation-auditor)` is dispatched. Like the Finalize evidence it is git-ignored, has no validator and never gates resolution. Mask secrets as `***MASKED***`. Only RED blocks carry the `Production files edited before this run:` line. Format:

````md
# TDD evidence — <work_id>
Work type: feature | bugfix | refactor | test-only

## Run <n> — RED | GREEN | CHARACTERIZATION | RETEST | MUTATION
Command: `<exact command as run, bare: no pipe, no trailing echo, no || true>`
Exit: <integer>
Production files edited before this run: none | <list>
Output (last 20 lines or fewer):
```text
<output tail>
```
````

---

## Lite Mode
Only for low-risk work: typo, small README edit, simple UI-text change, comment fix, formatting, minor non-production config. **Forbidden** for auth, payment, security, DB migration, production bug, API contract, permission/role, user-data handling, native mobile permission, token/session, Supabase RLS — those are always Full.

Lite steps (own short track, not the Full 1–21): branch check · short analysis · scope note · change · relevant test/lint · diff review · commit (on approval) · push/PR (on approval).

## Parallel-execution rules (how the ⇉ steps run)
- Genuinely-independent steps run **concurrently**; gated/dependent steps stay ordered. Use the mechanism the Step 1 `dispatch-strategy` map assigned; do not call `dispatch-strategy` again mid-run.
- Keep one task-tracker item per active step. On Claude Code use `TaskCreate`, `TaskList` and `TaskUpdate` (`TodoWrite` only when `CLAUDE_CODE_ENABLE_TASKS=0`). On Codex use `update_plan` or the native tracker. A fanned-out step may spawn its own sub-items but the parent stays `in_progress` until all branches return and the gate passes.
- Fan-out examples: Context7 across libraries (6), security lenses (11/14), quality gates (15), multi-file generation in 9. Sequence 4→5→8→9→10 is **never** parallelized.
