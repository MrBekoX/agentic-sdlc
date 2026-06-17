# agentic-sdlc

> A disciplined SDLC skill library for **Claude Code** and **Codex**. It routes every prompt to the **smallest sufficient** capability and escalates to a full gated envelope only when the work actually needs it.
>
> `Version 0.2.7` · `MIT` · `Author: Beko` · <https://github.com/MrBekoX/agentic-sdlc>

---

## Why this exists

Agentic coding tools write code fast. Speed without discipline produces untested diffs, undocumented assumptions, security blind spots, and claims that "it works" without evidence. **agentic-sdlc** turns repeatable software-engineering procedure into versioned, testable **skills** so the agent does the right work the right way:

> **Read context first · spec before building · test before claiming · review before finishing.**

The library is opinionated about *ceremony*: a one-line typo should not trigger a 21-step pipeline, but a production auth change should. A session-local router picks the right amount of process for each prompt and tracks scope shifts across the conversation.

## What it is / what it is not

| It **is** | It **is not** |
|---|---|
| A local development plugin for Claude Code and Codex | A CI/CD pipeline or hosted service |
| A library of reusable skills, contracts, hooks, scripts, agents, and workflows | A general-purpose agent harness |
| A router-plus-pipeline that chooses the right level of ceremony | A rule that every prompt must run the full SDLC envelope |
| Versioned, testable documentation-as-procedure | A replacement for human judgment |

Current scope is **Claude Code and Codex only**. Other harness integrations (Cursor, Gemini, OpenCode, etc.) are intentionally deferred.

## How it works

The system is a thin **onion**. `using-agentic-sdlc` sits at the edge and classifies intent into the smallest sufficient skill. Focused skills own their own domains (spec, plan, feature, fix, refactor, test, review). When the user asks for end-to-end implementation — or the work touches auth, payment, database migration, API contract, permissions, user data, tokens, or RLS — `agentic-sdlc-pipeline` takes over the outer envelope while delegating the inner TDD/security/refactor work to the matching core skill.

```text
                         ┌──────────────────────────────────────┐
                         │   using-agentic-sdlc  (edge router)  │  ← classifies intent
                         │   smallest sufficient skill          │
                         └─────────────────┬────────────────────┘
                                           │ escalate only when full envelope is needed
                         ┌─────────────────▼────────────────────┐
                         │   agentic-sdlc-pipeline (orchestrator)│  ← owns spec/plan/gates/git
                         │   delegates the implementation core   │
                         └─────────────────┬────────────────────┘
              ┌──────────────┬─────────────┼──────────────┬──────────────┐
              ▼              ▼             ▼              ▼              ▼
        root-cause-fix  feature-build  safe-refactor  test-authoring  (review skills)
```

Contracts in `contracts/skills/` are the durable behavior layer; hooks in `hooks/` enforce deterministic guardrails; `tests/` verifies that skills route and execute as documented.

## Core concepts

| Concept | What it means here |
|---|---|
| **Skill** | A `SKILL.md` with YAML frontmatter plus optional `scripts/`, `references/`, and `assets/`. The runnable unit of procedure. |
| **Contract** | A durable behavior rule in `contracts/skills/` (`00`–`10`). Cross-cutting requirements such as context-first, spec-driven development, testing, security, git safety. |
| **Agent** | A read-only role contract in `agents/` used by subagents or workflows (e.g. `spec-plan-author`, `security-reviewer`, `implementation-auditor`). |
| **Workflow** | A Claude Code dynamic workflow script in `workflows/` (`spec-plan-draft`, `skill-draft`). Codex runs equivalent logic through an embedded adapter. |
| **Hook** | A deterministic guard script (`.mjs`) wired by `hooks/hooks.json` (Claude) and `hooks/hooks-codex.json` (Codex). |
| **Command** | A manual slash command such as `/git-safety-check`. |
| **Script** | A deterministic Python helper in `scripts/` (e.g. `detect_context.py`, `validate_artifacts.py`, eval runners). |
| **Eval** | A prompt/fixture pair under `tests/skills/` that verifies routing, behavior, or procedure gates. |

## Repository layout

```text
.claude-plugin/    Claude Code plugin manifest + local marketplace metadata
.codex-plugin/     Codex plugin manifest (skills + hooks + interface block)
skills/            16 skills; each is a dir with SKILL.md + optional bundled files
agents/            9 read-only sub-agent role contracts
workflows/         2 Claude Code dynamic workflow scripts (author⇄critic loops)
hooks/             Deterministic guard scripts + hook-wiring JSON (Claude + Codex)
scripts/           11 Python helpers: context detection, artifact validation, evals, versioning
tests/             unittest suites + skill harness + fixtures + golden references + eval seeds
contracts/skills/  11 numbered behavior contracts (00 global .. 10 AI-agent collaboration)
commands/          Slash-command definitions (/git-safety-check)
docs/              Plugin guide, skill boundaries, testing guide, runtime notes, audit reports
AGENTS.md          Operating model for agents working in this skill-development repo
```

## Skill inventory (16 skills)

### Router

| Skill | Purpose |
|---|---|
| `using-agentic-sdlc` | Session-local router. Picks the smallest sufficient skill, tracks scope shifts, enforces evidence-before-claim discipline. |

### Core work-flow skills

| Skill | Purpose |
|---|---|
| `agentic-sdlc-pipeline` | Full-envelope SDLC orchestrator for end-to-end implementation. Owns the outer envelope (spec/plan/git/gates) and delegates the core. |
| `spec-authoring` | Standalone WHAT flow: requirements, acceptance criteria, behavior contract. |
| `plan-authoring` | Standalone HOW flow: task breakdown, sequencing, verification strategy. |
| `feature-build` | New feature or endpoint end-to-end, ending with implementation-control. |
| `root-cause-fix` | Bug/broken-behavior fix via root cause → spec → plan → TDD → security → verify. |
| `safe-refactor` | Behavior-preserving restructure guarded by characterization tests. |
| `test-authoring` | Write or fix unit/integration/regression/e2e tests with meaningful assertions. |

### Gates and review skills

| Skill | Purpose |
|---|---|
| `security-audit` | Input/auth/secrets/injection/dependency review with masked findings. |
| `code-quality-review` | Technology-agnostic quality review of a diff or file. |
| `feedback-triage` | Verify reviewer/PR/bot feedback against the code before applying it. |
| `implementasyon-control` | Mandatory pre-final audit that the required flow was actually followed. |
| `completion-claim-gate` | Same-turn evidence gate before any "done / passing / fixed" claim. |

### Utility skills

| Skill | Purpose |
|---|---|
| `mind-spark` | Pre-spec intent gate for build/design requests whose shape is not settled. |
| `dispatch-strategy` | Decide how to run work: main loop, sub-agent, dynamic-workflow, or agent-team. |
| `skill-authoring` | Author, evaluate, and package Claude Code / Codex skills (RED/GREEN/REFACTOR loop). |

## Quick start

### Requirements

- **Claude Code** or **Codex** (the supported agent runtimes)
- **Node.js** — hook scripts are `.mjs` and run via `node`
- **Python 3** — deterministic scripts, validators, eval helpers, and the local gate
- **Git** — branch guard, diff review, commit/PR flow

### Claude Code

Add this repository as a local marketplace/plugin source. The plugin reads:

- `.claude-plugin/plugin.json` — manifest
- `.claude-plugin/marketplace.json` — local marketplace source (`"source": "./"`)
- `hooks/hooks.json` — PreToolUse / PostToolUse / SessionStart wiring (paths via `${CLAUDE_PLUGIN_ROOT}`)

> Skills live in root `skills/`, **not** in `.claude/skills/`. The `.claude/` directory is for local workspace settings only.

### Codex

Point Codex at `.codex-plugin/plugin.json`. It loads skills from `./skills/` and hooks from `./hooks/hooks-codex.json` (SessionStart bootstrap only in this release). Codex resolves plugin-root paths via `${PLUGIN_ROOT}`.

Codex has no Claude Workflow runtime; `agentic-sdlc-pipeline` uses an **embedded author/critic adapter** for the spec/plan phases instead of the `spec-plan-draft` workflow.

## Typical usage

Invoke a focused skill directly, or let `using-agentic-sdlc` route from a natural-language prompt:

```text
/spec-authoring <what to specify>
/plan-authoring <what to plan>
/feature-build <what to add>
/root-cause-fix <broken behavior>
/agentic-sdlc-pipeline <end-to-end production-ready change>
```

`agentic-sdlc-pipeline` is the **escalation path** for full-envelope work — not the default for every request.

## Guardrails

Deterministic hooks are wired from `hooks/hooks.json` (Claude) and `hooks/hooks-codex.json` (Codex):

| Hook | Event | Behavior |
|---|---|---|
| `scan-commit.mjs` | PreToolUse (`git commit`) | **Blocks** commits that add high-confidence secrets. |
| `scan-write.mjs` | PostToolUse (Write/Edit/MultiEdit) | **Warns** on secret-shaped patterns in new content. |
| `branch-guard.mjs` | PreToolUse (`git commit`/`push`) | Warns on `main`/`master`; blocks when `AGENTIC_BRANCH_GUARD_BLOCK=true`; flags force-push. |
| `destructive-command-guard.mjs` | PreToolUse (`Bash`) | **Blocks** deterministic destructive commands (`git reset --hard`, `rm -rf`, …). |
| `session-start.mjs` | SessionStart | Injects git status summary + AGENTIC-SDLC bootstrap reminder. |

Judgment-based checkpoints (was context read? was test output understood? was security done?) live as **flow gates** in skill contracts, not as scripts — see `hooks/README.md`.

## Quality gate

Run the three fast local commands before considering a change complete:

```bash
python3 scripts/check_all.py
python3 tests/skills/harness.py
python3 -m unittest discover -s tests -v
```

Trigger, behavior, and procedure eval fixtures live under `tests/skills/`. Live evals (Claude/Codex) require the CLI + auth and are **not** part of the normal local gate.

## Versioning

Current version: `0.2.7`.

```bash
python3 scripts/bump_version.py --check      # verify VERSION + manifests agree
python3 scripts/bump_version.py 0.2.8        # bump VERSION + both plugin manifests
```

## License

MIT — see [LICENSE](LICENSE).

## Where to read more

- [docs/plugin-readme.md](docs/plugin-readme.md) — component-by-component plugin reference
- [docs/skill-boundaries.md](docs/skill-boundaries.md) — skill responsibilities, anti-overlap rules, decision flowcharts
- [docs/testing.md](docs/testing.md) — evaluation strategy, fixtures, harness, and local validation
- [AGENTS.md](AGENTS.md) — operating model for agents authoring skills in this repo
