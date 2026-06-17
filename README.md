# agentic-sdlc

A disciplined SDLC skill library for [Claude Code](https://claude.com/claude-code). It turns production-impacting work into a gated **spec -> plan -> TDD -> security -> review** flow instead of an unstructured edit.

Current scope: **Claude Code only**. Codex and other harness integrations are intentionally deferred.

The centerpiece is **`dev-flow`**, an Onion orchestrator that owns the outer envelope: git lifecycle, Spec and Plan phases, documentation verification, scope lock, quality gates, and final audit. It delegates implementation to the matching work-flow skill.

## Install

This repo is now shaped as a **local/development Claude Code plugin**. The repository metadata is for local installation and validation; CI does not publish the plugin or create releases.

```text
.claude-plugin/plugin.json
.claude-plugin/marketplace.json
hooks/hooks.json
skills/
agents/
workflows/
commands/
rules/
scripts/
tests/
```

Add this repository as a local marketplace/plugin source in Claude Code, then invoke a skill such as:

```text
/dev-flow <what to build or fix>
```

Skills live in root `skills/`, not in `.claude/skills/`. The `.claude/` directory is only for local workspace settings.

Hook paths use `${CLAUDE_PLUGIN_ROOT}`, so plugin installation is the expected runtime model.

## Skills

| Skill | Purpose |
|---|---|
| `dev-flow` | Onion-center SDLC orchestrator; owns the gated envelope and delegates the core. |
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
skills/           one folder per skill (SKILL.md + bundled references/scripts)
agents/           sub-agent role contracts
commands/         slash commands such as git-safety-check
workflows/        dynamic workflow scripts
hooks/            secret scan, branch guard, destructive command guard, session start
scripts/          deterministic helpers and subagent handoff utilities
tests/            stdlib unittest suites, skill fixtures, and static checks
rules/            generic engineering rules (00..10)
docs/             local-only ignored runtime notes, specs, plans, and audit reports
CLAUDE.md         operating model for this skill-development repo
```

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

## Versioning

Current version: `0.1.0`.

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
