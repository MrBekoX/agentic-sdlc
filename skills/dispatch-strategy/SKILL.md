---
name: dispatch-strategy
description: This skill should be used first in any language to decide whether work runs in the main loop, a sub-agent, a dynamic-workflow, or an agent-team, especially when the user asks which orchestration mode to choose. It applies before answering when work has 2+ independent parts, heavy exploration, verification/research fan-out, multi-file generation, or multi-angle review/audit.
---

# Skill: dispatch-strategy (the mechanism-decision authority)

> Before any non-trivial work, this skill answers "how should I run this?" Other work-skills reference it at fan-out gates. **Goal:** run parallelizable work in parallel; delegate independent work so the main context stays clean; never do heavy independent work serially in the main loop.

## Scope — mechanism only, never a skill's internal flow
At the start of a work-skill, produce a **mechanism map over the skill's named parts**: for each heavy/independent/fan-out part the skill exposes, pick which mechanism runs it (main loop / sub-agent / dynamic-workflow / agent-team). That map IS the dispatch decision.

This scope is fenced:
- **Never wholesale-delegate a multi-step skill.** The skill always coordinates from the main loop; only its *parts* receive a mechanism — a multi-step skill run inside one sub-agent would nest its own delegations and degrade its fresh-context gates.
- **Never touch the skill's internal mechanism.** Its steps, their order, whether a step runs, the mandated integrity gates (a `spec-plan-critic` for a drafted spec/plan, an `implementation-auditor` for self-graded code/findings), and the content/correctness verdicts belong to the skill and its contracts — not to this decision.

In one line: dispatch sets the **working strategy**; the skill owns **what the work is and how it is sequenced**.

## Depth contract (proportional — scale rigor to the change)
A dispatch decision names the **property of the work** that selects the mechanism, not just the verdict. State the relevant property: independence (does this part need the main context, or run alone?), similar-item count (≈3+ alike → fan-out), whether the intermediate context is needed later (disposable → delegate), interactivity (peers + live lead → team). One short clause of "why" per decision is enough — this is a routing call, not an essay. If you land on "main loop" for heavy *independent* work, say why it isn't delegable; absent a reason, that default is the bug.

## Excuse -> check
| Excuse | Check |
|---|---|
| "Just run it in the main loop." | Name whether it's independent and whether its intermediate steps are needed later — independent + disposable is a sub-agent, not the main loop. |
| "Make it a workflow to be safe." | Count the similar items — under ≈3, a workflow is needless weight; pick the smallest sufficient mechanism. |
| "Delegate it." | To which mechanism, and why — sub-agent, workflow, or team is selected by the work's shape, not by a vague "delegate". |

## No placeholders
Do not state a mechanism with no work-shape behind it. Do not say "delegate it" without naming which mechanism and the property that picks it. Do not default to the main loop for heavy independent work — that is the failure this skill exists to catch.

## Shallow example (reject this)
"Verdict: use a sub-agent." with no reason is not a decision — name the property that picks it ("one independent codebase sweep whose intermediate reads I won't need later → sub-agent").

## The four options

| Option | Use for | How to invoke | Cost / caveat |
|---|---|---|---|
| **Main loop** (no delegation) | Interdependent code, sequencing/design decisions, small single-file work, user dialogue | — (you do it directly) | Cheapest; but doing heavy/independent work here **bloats context** |
| **Sub-agent** | One well-defined **independent** piece: codebase exploration/research, "build from this spec and report", fixed-pattern multi-file generation, multi-file verification | `Agent` tool (use `isolation:"worktree"` / `run_in_background` when useful) | Medium; intermediate work **stays in the sub-agent's context**, only the result returns |
| **Dynamic-workflow** | Large parallelizable work: **verification, research, OR code** (≈3+ similar items; deterministic phases, adversarial cross-check, loop-until-done, pipeline). Parallel code writing via worktree isolation | `Workflow` tool (JS: `agent()`/`parallel()`/`pipeline()`; `isolation:"worktree"` for parallel writes) | High but amortized; runs in background, returns structured results |
| **Agent-team** | Continuous, **interactive**, collaborative parallel work: multi-angle review (security/perf/test), competing-hypothesis debugging, independent module ownership; peers talk, a live lead steers | Natural language: "set up an agent team with roles … " | **Most expensive**; needs interaction, **not for headless/CI**; requires the experimental teams flag + a recent Claude Code |

## Runtime adapter

Use the portable capability matrix in `<runtime-root>/docs/runtime-adapter.md`.

**Plugin root (`<runtime-root>`):** the installed agentic-sdlc folder, two levels above this `SKILL.md` (`<runtime-root>/skills/<name>/SKILL.md`) — never the user's working directory. Claude Code substitutes `${CLAUDE_PLUGIN_ROOT}`; Claude Code and ZCode substitute `${CLAUDE_SKILL_DIR}/../..`; Kimi Code substitutes `${KIMI_SKILL_DIR}/../..`; a SessionStart line `Plugin root (resolved by this hook…)` names it on Claude Code, Codex, ZCode and Cursor; Codex and Grok CLI show this skill's absolute path in the skill listing. A `${…}` token still shown literally is unresolved: never pass it to a shell. Confirm `<runtime-root>/scripts/validate_artifacts.py` exists and write that absolute path, quoted for your shell, into commands; if it cannot be confirmed, stop the step and report `plugin root unresolved` — never run a same-named file from the user's project. Run helpers with `python3` (Python 3.8+), or `py -3` on Windows when `python3` is missing or is the Microsoft Store alias.

- **Claude Code:** `Dynamic-workflow` means the native JavaScript Workflow runtime. Use it only when its scale/repeatability properties matter.
- **Codex:** map `Dynamic-workflow` to subagent fan-out, parallel local tools, cloud delegation, or a sequential degraded path with an explicit note. Do not invent a workflow script requirement when the runtime lacks a Workflow tool.
- **ZCode (experimental adapter):** subagents run through the `Agent` tool with the plugin `agents/*.md` roles; ZCode 3.14.0 added a dynamic-workflow tier whose saved workflows live in the project or user `.zcode/workflows/` folders, but no plugin component can install one, so treat `Dynamic-workflow` as **unavailable** and use the documented degraded path; agent-team is unavailable too. Details in `<runtime-root>/docs/zcode-runtime-adapter.md`.
- **Grok CLI (experimental adapter):** `Dynamic-workflow` means Grok's Rhai `workflow` tool (`/workflow <name>` or the `workflow` tool with a catalog name). Named loops live in the project catalog `.grok/workflows/*.rhai` (`spec-plan-draft`, `multi-lens-review`, `skill-draft`), not as a plugin component. Plugin install does not deliver those scripts. If Grok workflows are disabled or the named script is not in the catalog, map to `spawn_subagent` fan-out. Do not call Claude JS `Workflow` on Grok.
- **Agent-team:** runtime-specific. If unavailable, use subagents or a documented degraded path.
- **Spec/plan inside agentic-sdlc-pipeline:** Claude Code uses `spec-plan-draft`; Grok CLI uses `/workflow spec-plan-draft` when that catalog script is present; Codex uses the embedded author/critic adapter. Standalone `spec-authoring` and `plan-authoring` remain prompt-level entry skills, not agentic-sdlc-pipeline substeps.

## Decision tree
1. Is it **interdependent code** or a design/sequencing decision? → **Main loop**. (But hand independent sub-parts — exploration, fixed-pattern generation — to a **sub-agent**.)
2. Is it **large-scale and parallelizable** (≈3+ similar items — verification, research, **or code**; deterministic phases / adversarial cross-check; worktree isolation for parallel writes)? → **Dynamic-workflow**.
3. Is it a **single independent piece** whose intermediate steps you don't need in the main context? → **Sub-agent**.
4. Is it **interactive, collaborative, continuous** parallel work where peers talking + a live lead add value? → **Agent-team**.

> **Context-bloat heuristic (always apply):** if a task will produce many intermediate tool-calls/reads/builds you won't need later → **delegate** (sub-agent or workflow). Don't do it serially in the main loop.

## Per-slice fan-out — parallel specialists, you coordinate
The common in-skill shape: the work splits into 2+ **independent read-only slices** (layers, lenses, file-groups, hypotheses). Dispatch **one specialist per slice in a single message** — parallel `Agent` calls, or a `Workflow` when the slices are a fixed ≈3+ and you want them deterministic/repeatable — so they run concurrently. You (main loop) stay the **coordinator**: the fresh-context specialists return unbiased findings; merging, dedup, conflict resolution, and the final call are yours.
- **Reads fan out; writes stay serial.** Review/analysis/audit slices parallelize; file edits stay in one loop or worktree-isolated — never two agents on one file.
- **Independent verdict, not self-attestation.** When accepting the merged findings would mean judging your own code, route them through `implementation-auditor` (via `implementation-control`). You coordinate; the auditor arbitrates.
- **No coordinator agent.** The main loop already receives every specialist's result — a separate coordinator sub-agent would see less than you and cannot apply fixes. Don't add one.
- **Degrade:** inside a delegated sub-agent (no nesting) or a runtime without parallel agents → run the slices serially and flag `Delegation Degraded: parallel specialists unavailable`, marked non-independent.

## Mandatory gates (contracts)
- **Delegation required:** an **independent** piece whose intermediate work you don't need to keep (exploration, reference analysis, N-file fixed-pattern generation, multi-file verification) → **sub-agent**. Doing it serially in the main loop is forbidden.
- **Fan-out required:** ≈3+ similar **verification/research** items → **dynamic-workflow** (don't do them one-by-one inline).
- **All three can write code:** sub-agent, workflow (worktree-isolated parallel), and agent-team all write code. Choose by the **shape of the work**, not by authority. Use worktree isolation to avoid collisions in parallel writes.
- **Smallest sufficient mechanism (YAGNI):** cost ladder **Main loop < Sub-agent < Dynamic-workflow < Agent-team**. Don't build a workflow for one task; don't open an agent-team for a simple handoff.
- **Agent-team only when interactive:** in headless/automated/cron runs use a workflow instead.

## Anti-patterns (avoid)
- Doing everything serially in the main loop → context bloats, quality degrades.
- A workflow for a single dependency/check (needless weight).
- Not delegating an independent exploration/generation and pumping dozens of intermediate steps into the main context.
- Agent-team in headless mode.

## Relationship to work-skills
- **root-cause-fix:** heavy context-gathering → `context-analyst` sub-agent(s); competing root-cause hypotheses → one `debugger` per hypothesis (parallel, read-only); verification (tests/lint/security) → fan-out. The fix itself stays in the main loop.
- **feature-build:** scope map → one `context-analyst` per affected layer; verification → test/lint/security lenses in parallel (`security-reviewer` for the security lens). Interdependent code stays in the main loop.
- **security-audit:** the lenses (injection / authz-IDOR / secrets / auth) → one `security-reviewer` per lens in parallel (or **agent-team** for interactive review); you merge.
- **code-quality-review:** one `code-reviewer` per changed layer/file-group (fresh-context, so the reviewer isn't the author); add a `software-architect` lens for a structural change. You synthesize.
- **safe-refactor:** characterize per module via `software-architect` / `context-analyst`; large parallel *edits* run worktree-isolated. **test-authoring:** coverage-gap analysis per behavior-area via `test-engineer`; test-writing stays serial.
- Spec/plan drafting in Claude Code flows → `spec-plan-draft` workflow (author → critic), not shallow main-loop writing.
- Spec/plan drafting on Grok CLI → `/workflow spec-plan-draft` (or the `workflow` tool with name `spec-plan-draft`) when `.grok/workflows/spec-plan-draft.rhai` is in the catalog; otherwise `spawn_subagent` author → critic → revise.
- Spec/plan drafting inside `agentic-sdlc-pipeline` on Codex runs the embedded author/critic adapter with a fresh-context critic when available. Standalone `spec-authoring` and `plan-authoring` remain independent prompt routes.

## Quick mapping (example → mechanism)
| Work | Mechanism |
|---|---|
| Verify N library versions / docs | Dynamic-workflow (fan-out) |
| "Where/how is X done" in the codebase | Sub-agent |
| Analyze a reference repo / external source | Sub-agent |
| Generate N similar files from one clear spec | Sub-agent |
| 100+ file bulk migration (parallel, worktree) | Dynamic-workflow |
| Review a diff from 4 security lenses in parallel | Dynamic-workflow |
| test + lint + typecheck + secret-scan in parallel | Dynamic-workflow |
| Interactively review a PR for security/perf/test | Agent-team |
| Debug with competing hypotheses in parallel | Agent-team |
| Small single-file fix / design decision | Main loop |
