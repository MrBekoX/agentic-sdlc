# agentic-sdlc

A disciplined SDLC skill library for Claude Code and Codex. It routes each prompt to the smallest useful skill, and reserves the full **spec -> plan -> TDD -> security -> review** envelope for work that actually needs it.

Current scope: Claude Code and Codex plugin metadata share the root `skills/` source. Other harness integrations are intentionally deferred.

The entry point is **`using-agentic-sdlc`**, a session-local router. It tracks the current intent, selected skill, known artifacts, and scope shifts in the conversation. **`dev-flow`** is the escalation path for end-to-end implementation, not the default route for every feature, spec, plan, test, or review request.

## Install

This repo is now shaped as a **local/development Claude Code and Codex plugin**. The repository metadata is for local installation and validation. No CI workflow is configured for now; publishing or release work must stay manual and explicit.

```text
.claude-plugin/plugin.json
.claude-plugin/marketplace.json
.codex-plugin/plugin.json
hooks/hooks.json
hooks/hooks-codex.json
skills/
agents/
workflows/
commands/
contracts/skills/
scripts/
tests/
```

Add this repository as a local marketplace/plugin source in Claude Code, then invoke a focused skill or let the bootstrap router choose from a natural prompt:

```text
/spec-flow <what to specify>
/plan-flow <what to plan>
/feature-flow <what to add>
/dev-flow <end-to-end production-ready change>
```

Skills live in root `skills/`, not in `.claude/skills/`. The `.claude/` directory is only for local workspace settings.

Claude hook paths use `${CLAUDE_PLUGIN_ROOT}`. Codex hook paths use `${PLUGIN_ROOT}` through `.codex-plugin/plugin.json`, so plugin installation is the expected runtime model.

## Skills

| Skill | Purpose |
|---|---|
| `using-agentic-sdlc` | Session-local router; chooses the smallest sufficient skill, tracks scope shifts, and gates evidence-before-claim discipline. |
| `dev-flow` | Full-envelope SDLC orchestrator for end-to-end implementation; owns the gated envelope and delegates the core. Claude uses `spec-plan-draft`; Codex uses dev-flow's embedded author/critic adapter. |
| `spec-flow` | Spec-only WHAT flow for requirements, acceptance criteria, and behavior contracts. |
| `plan-flow` | Plan-only HOW flow for task breakdown, sequencing, and verification strategy. |
| `fix-flow` | Bug / broken-behavior fix via root cause, spec, plan, TDD, security, and verification. |
| `feature-flow` | New feature or endpoint end-to-end with a final implementation-control audit. |
| `refactor-flow` | Behavior-preserving restructure guarded by characterization tests. |
| `test-flow` | Write/fix unit, integration, regression, and e2e tests with meaningful assertions. |
| `orchestration` | Decide how to run work: main loop, sub-agent, dynamic workflow, or agent-team. |
| `security-review` | Input/auth/secrets/injection/dependency review with masked findings. |
| `code-review` | Technology-agnostic quality review of a diff or file. |
| `implementasyon-control` | Mandatory pre-final audit that the required flow was actually followed. |
| `completion-claim-gate` | Same-turn evidence gate before any "done / passing / fixed" claim. |
| `mind-spark` | Pre-spec intent gate for build/design requests whose shape is not settled. |
| `receiving-code-review` | Verify reviewer feedback against the code before applying it. |
| `writing-skills` | Author, eval, and package Claude Code skills with a test-first loop. |

Responsibility boundaries are enforced by the skill bodies, integration tests, and golden cross-reference fixtures under `tests/skills/`.

## Layout

```text
.claude-plugin/   Claude Code plugin metadata and local marketplace metadata
.codex-plugin/    Codex plugin metadata
skills/           one folder per skill (SKILL.md + bundled references/scripts)
agents/           sub-agent role contracts
commands/         slash commands such as git-safety-check
workflows/        Claude Code dynamic workflow scripts
hooks/            secret scan, branch guard, destructive command guard, session start
scripts/          deterministic helpers and subagent handoff utilities
tests/            stdlib unittest suites, skill fixtures, and static checks
contracts/skills/ skill behavior contracts (00..10)
docs/             plugin documentation, runtime notes, and example specs/plans
CLAUDE.md         operating model for this skill-development repo
```

## Detailed Plugin Documentation

For a component-by-component explanation of the Claude Code plugin, guardrails, skills, agents, workflows, tests, and pre-push checklist, see [docs/plugin-readme.md](docs/plugin-readme.md).

## Quality Gate

Run the local deterministic gate:

```bash
python scripts/check_all.py
python tests/skills/harness.py
python -m unittest discover -s tests -v
```

Trigger, behavior, and procedure eval fixtures live under `tests/skills/`.

## Guardrails

The plugin wires deterministic Claude Code hooks from [hooks/hooks.json](hooks/hooks.json):

- `scan-commit.mjs` blocks commits that add high-confidence secrets.
- `scan-write.mjs` warns on broad secret patterns in newly written content.
- `branch-guard.mjs` warns on protected branches and can block with `AGENTIC_BRANCH_GUARD_BLOCK=true`.
- `destructive-command-guard.mjs` blocks deterministic high-risk destructive commands.
- `session-start.mjs` injects workspace context and operating reminders.

## Runtime Note

`spec-flow` and `plan-flow` are standalone routes for spec-only and plan-only prompts. They are not internal `dev-flow` substeps. Codex does not use Claude Code's JavaScript Workflow runtime, so `dev-flow` maps its spec/plan author-critic loop to a Codex-friendly embedded adapter.

## Versioning

Current version: `0.2.6`.

Check version metadata:

```bash
python scripts/bump_version.py --check
```

Update Claude Code plugin version metadata:

```bash
python scripts/bump_version.py 0.2.0
```

## License

MIT - see [LICENSE](LICENSE).
