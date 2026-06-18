# Hooks - Deterministic Guards + Conceptual Checklists

Two kinds of guard live here:

1. **Real hooks** - executable `.mjs` scripts wired by a runtime hook config.
2. **Conceptual hooks** - judgment-based checkpoints enforced by skills and contracts, not scripts.

## Runtime Wiring

| Runtime | Config | Wired events in this release |
|---|---|---|
| Claude Code | `hooks/hooks.json` | `PreToolUse`, `PostToolUse`, `SessionStart`, `Stop` |
| Codex | `hooks/hooks-codex.json` | `SessionStart` only |

The hook scripts are shared in this directory, but being present as a script is not the same as being wired by every runtime.

Claude Code paths resolve through `${CLAUDE_PLUGIN_ROOT}`. Codex paths resolve through `${PLUGIN_ROOT}`.

## Real Hook Scripts

| Script | Claude Code event | Codex event | Behavior |
|---|---|---|---|
| `session-start.mjs` | `SessionStart` | `SessionStart` | Injects git status summary and AGENTIC-SDLC bootstrap reminder. |
| `scan-write.mjs` | `PostToolUse` (`Write`/`Edit`/`MultiEdit`) | Not wired | Scans newly written text for secrets; warns only. |
| `scan-commit.mjs` | `PreToolUse` (`git commit*`) | Not wired | Scans added diff lines for high-confidence secrets; blocks commit. |
| `branch-guard.mjs` | `PreToolUse` (`git commit*` / `git push*`) | Not wired | Warns on `main`/`master`; blocks when `AGENTIC_BRANCH_GUARD_BLOCK=true`; flags force-push. |
| `destructive-command-guard.mjs` | `PreToolUse` shell command | Not wired | Blocks deterministic destructive commands such as `git reset --hard`, forceful `git clean`, `rm -rf`, and `Remove-Item -Recurse -Force`. |
| `completion-claim-guard.mjs` | `Stop` | Not wired | Warns when a final completion claim appears without `completion-claim-gate`; blocks when `AGENTIC_COMPLETION_GATE_BLOCK=true`. |
| `secret-patterns.mjs` | Shared library | Shared library | Secret-pattern scanner used by the scan hooks. |

All scripts are generic: no shell for git operations, path-normalized skip lists, no embedded real secrets, and fail-open behavior on hook errors.

## Conceptual Hooks

These checkpoints require model judgment, so they live as flow gates in skills and contracts.

| Conceptual hook | Enforced by |
|---|---|
| `pre-edit-context-check` | contracts `01-context-first`, `03-plan-mode`; early steps in `root-cause-fix` and `feature-build`. |
| `post-edit-diff-check` | contracts `04-code-quality`, `08-git-safety`; `code-quality-review`; diff review steps. |
| `pre-test-command-check` | contract `05-testing`; `test-authoring`. |
| `post-test-result-check` | contract `05-testing`; TDD loops in implementation skills. |
| `security-sensitive-change-check` | contract `06-security`; `security-audit`. |
| `pre-git-operation-check` | contract `08-git-safety`; `/git-safety-check`; `scan-commit.mjs`; `branch-guard.mjs`. |
| `final-response-verification` | `implementasyon-control` plus `completion-claim-gate`; Claude `completion-claim-guard.mjs` is only a deterministic backstop. |

## Adding Or Disabling Hooks

- Add new scripts under the matching event in `hooks/hooks.json` for Claude Code or `hooks/hooks-codex.json` for Codex when that runtime supports the event.
- Use runtime hook controls to browse or temporarily disable hooks.
- Keep scripts deterministic. Checks that need judgment belong in skills/contracts.
