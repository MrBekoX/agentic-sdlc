# Hooks — Deterministic Guards + Conceptual Checklists

Two kinds of guard live here:

1. **Real hooks** — executable `.mjs` scripts wired in `hooks.json` (this directory). They run automatically and can warn or block. Use these for things that must happen every time (contracts 06, 08).
2. **Conceptual hooks** — judgment-based checkpoints that a hook script can't decide deterministically. These are enforced inside **skill contracts** and **skills** (the flow gates), not as scripts. The table below maps each requested conceptual hook to where it is actually enforced.

## Real hooks (scripts, wired in hooks.json / hooks-codex.json)

| Script | Event | Behavior |
|---|---|---|
| `session-start.mjs` | SessionStart | Injects a git status summary + AGENTIC-SDLC bootstrap reminder into context. |
| `scan-write.mjs` | PostToolUse (Write/Edit/MultiEdit) | Scans newly written text for secrets; **warns** (non-blocking). |
| `scan-commit.mjs` | PreToolUse (Bash · git commit) | Scans added diff lines for high-confidence secrets; **blocks** the commit. |
| `branch-guard.mjs` | PreToolUse (Bash · git commit/push) | Warns on commit/push to `main`/`master`; blocks when `AGENTIC_BRANCH_GUARD_BLOCK=true`; flags force-push. |
| `destructive-command-guard.mjs` | PreToolUse (Bash) | Blocks deterministic high-risk destructive commands such as `git reset --hard`, forceful `git clean`, `rm -rf`, and `Remove-Item -Recurse -Force`. |
| `secret-patterns.mjs` | — (shared lib) | Generic secret patterns + scanner used by the scan hooks. No real secrets embedded. |

All scripts are generic: no shell (git via argument array), path-normalized skip lists, fail-open on error.

Claude Code wires hooks through `hooks/hooks.json` using `${CLAUDE_PLUGIN_ROOT}`.
Codex wires the startup bootstrap through `hooks/hooks-codex.json` using `${PLUGIN_ROOT}`.

## Conceptual hooks → where enforced

These are the seven requested checkpoints. They require judgment, so they live as **flow gates** in skill contracts/skills rather than as deterministic scripts.

| Conceptual hook | Enforced by |
|---|---|
| `pre-edit-context-check` (file read? spec/plan exists? in scope?) | contracts 01 and 03; fix-flow/feature-flow steps 1–4 |
| `post-edit-diff-check` (which files changed? unnecessary changes? diff too big?) | contracts 04 and 08; `code-review` skill; fix-flow step 12 |
| `pre-test-command-check` (right test command? right scope?) | contract 05; `test-flow` skill |
| `post-test-result-check` (output actually read? fail root-caused? no false "passed"?) | contract 05 (show real output); fix-flow step 8 + Loop A |
| `security-sensitive-change-check` (auth/permission/config/secret/migration/data-loss?) | contract 06; `security-review` skill; fix-flow steps 9 & 11 |
| `pre-git-operation-check` (status/diff reviewed? branch? secrets? tests? approval?) | contract 08; `/git-safety-check` command; `scan-commit.mjs` + `branch-guard.mjs` |
| `final-response-verification` (work verified? test output? security done? control run? gaps stated?) | `implementasyon-control` skill (mandatory pre-final) + `implementation-auditor` agent |

> Why not all scripts? Per Claude Code docs, hooks are for **deterministic** actions. A check like "was the test output actually understood?" needs a model's judgment — so it is a prompt-level gate in a skill, backed where possible by a deterministic script (e.g. secret scanning, branch guarding).

## Adding / disabling hooks
- Wire a new script under the matching event in `hooks.json` (`PreToolUse`, `PostToolUse`, `SessionStart`, `Stop`, …).
- Use `/hooks` in a session to browse/temporarily disable.
- `${CLAUDE_PLUGIN_ROOT}` resolves to this plugin's install directory for portable paths (as used by every entry in `hooks.json`).
