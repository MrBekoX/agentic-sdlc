# Hooks - Deterministic Guards + Conceptual Checklists

Two kinds of guard live here:

1. **Real hooks** - executable `.mjs` scripts wired by a runtime hook config.
2. **Conceptual hooks** - judgment-based checkpoints enforced by skills and contracts, not scripts.

## Runtime Wiring

| Runtime | Config | Wired events in this release |
|---|---|---|
| Claude Code | `hooks/hooks-claude.json` via `.claude-plugin/plugin.json` | `PreToolUse`, `PostToolUse`, `SessionStart`, `Stop` |
| Codex | `hooks/hooks-codex.json` via `.codex-plugin/plugin.json`, after hook review/trust; portable root manifests are not hook-equivalent on CLI 0.154.0 | `PreToolUse`, `SessionStart`, `Stop` |

> **Command-guard matcher is `Bash\|PowerShell`, with no `if` filter.** Both details are security-load-bearing.
> On a Windows host without Git Bash, Claude Code does not register the Bash tool at all, so a `Bash`-only
> matcher leaves every command guard inert. And an `if` narrowed to a git SUBCOMMAND (`Bash(git commit*)`)
> never starts the hook for a git alias such as `git ci`, so the guard cannot decide at all — the docs call
> `if` best-effort and say to use the permission system, not a hook filter, for a hard allow/deny. The
> decision therefore lives inside each guard, which self-gates cheaply on `git`.


The hook scripts are shared in this directory, but being present as a script is not the same as being wired by every runtime.

Claude Code paths resolve through `${CLAUDE_PLUGIN_ROOT}`. Codex paths resolve through `${PLUGIN_ROOT}`.

## Real Hook Scripts

| Script | Claude Code event | Codex event | Behavior |
|---|---|---|---|
| `session-start.mjs` | `SessionStart` | Not wired | Injects git status summary and Claude Code Skill-tool bootstrap reminder. |
| `session-start-codex.mjs` | Not wired | `SessionStart` | Injects git status summary and Codex-specific AGENTIC-SDLC bootstrap reminder. |
| `scan-write.mjs` | `PostToolUse` (`Write`/`Edit`/`MultiEdit`) | Not wired | Scans newly written text for secrets; warns only. (Claude `Write`/`Edit` field shape; superseded on Codex by `scan-write-codex.mjs`.) |
| `scan-write-codex.mjs` | Not wired | `PreToolUse` (`Bash`/`apply_patch`) | Codex-native pre-write secret guard: extracts the literal added content of recognized write forms (apply_patch V4A; `printf`/`echo` `>`/`>>`; literal heredocs) and DENIES a high-confidence secret before the write. Bounded backstop — NOT covered (fail-open): pipe/`tee`/`base64`/command-substitution and `$VAR`/`${...}`/`$(...)` expansion. |
| `scan-commit.mjs` | `PreToolUse` (`Bash`/`PowerShell`) | `PreToolUse` (`Bash`) | Scans added diff lines **and the commit message** (`-m`/`--message`/`-F`) for high-confidence secrets; blocks the commit. Flags credential files by name, including derived copies (`id_rsa.bak`, `.npmrc.old`, `server.key.bak`). Self-gates internally by resolving the git subcommand through `git-invocation.mjs`, so a git alias (`alias.ci = commit -a`) is still scanned. |
| `branch-guard.mjs` | `PreToolUse` (`Bash`/`PowerShell`) | `PreToolUse` (`Bash`) | Warns on `main`/`master`; blocks when `AGENTIC_BRANCH_GUARD_BLOCK=true`; flags force-push. Self-gates internally through `git-invocation.mjs`, so an aliased commit/push is still seen. |
| `destructive-command-guard.mjs` | `PreToolUse` shell command | `PreToolUse` (`Bash`) | Blocks deterministic destructive commands such as `git reset --hard`, forceful `git clean`, recursive `rm` including wrapper/path forms, and `Remove-Item -Recurse` including common aliases/wrappers. |
| `flow-order-guard.mjs` | `PreToolUse` (`Write`/`Edit`/`MultiEdit`) | Not wired (Claude file; mechanism superseded on Codex by `flow-order-guard-codex.mjs`) | For active flows, checks current-turn pre-edit evidence before source edits; warns by default and denies when `AGENTIC_FLOW_GATE_BLOCK=true`. |
| `flow-order-guard-codex.mjs` | Not wired | `PreToolUse` (`Bash`/`apply_patch`) | Codex env-gated **opt-in** pre-edit ordering gate (AP2c): **default silent**, and only its own `AGENTIC_FLOW_ORDER_BLOCK` (independent of the flow-step `AGENTIC_FLOW_GATE_BLOCK`) enables denial. It accepts either a recorded recognized test-runner invocation before the edit (including a RED run), or a validated, same-work-id spec+plan pair authored in this session; it resolves both flat and canonical per-package layouts through the shared Codex artifact lookup, and separately derives the in-session spec/plan write sets so committed-only partners do not count. Current source edits are recognized across real `apply_patch`, `printf`/`echo` redirects and heredocs, in-place `sed -i`, `tee`, and plain `>`/`>>`; a literal `*** Begin Patch` inside Bash no longer selects the patch parser because `tool_name` is authoritative. Deferred fail-open forms remain `cat`/`dd` copy, `base64`, expansion-derived targets, and the `&>`/`&>>`/`>|`/`N>`/`>&N` redirect family. Deny output contains only a fixed preamble plus `{spec, plan}` roles; unreadable rollout, malformed input, or an unrecognized edit form fail open, while an unresolvable artifact root denies. |
| `completion-claim-guard.mjs` | `Stop` | Not wired (Claude file; mechanism superseded on Codex by `completion-claim-guard-codex.mjs`) | Warns when a final completion claim appears without `completion-claim-gate`; blocks when `AGENTIC_COMPLETION_GATE_BLOCK=true`. |
| `completion-claim-guard-codex.mjs` | Not wired | `Stop` | Codex completion-claim backstop: on a final completion claim without the `completion-claim-gate` **sentinel marker in the final assistant message**, emits a non-blocking advisory by default or blocks when `AGENTIC_COMPLETION_GATE_BLOCK=true`. Same env switch + copied claim/negation patterns as the Claude guard. |
| `flow-step-guard.mjs` | `Stop` | Not wired (Claude file; mechanism superseded on Codex by `flow-step-guard-codex.mjs`) | Re-derives required active-flow evidence from validated artifacts, real tool calls, and commands; warns by default and blocks missing `stop:block` steps when `AGENTIC_FLOW_GATE_BLOCK=true`. |
| `flow-step-guard-codex.mjs` | Not wired | `Stop` | Codex evidence-only flow-step backstop: re-derives active-flow evidence from THIS rollout's in-session spec/plan writes (session-scoped — committed prior-session artifacts never activate a flow), recorded commands, and recognized edit targets; tests require runner-invocation shape plus correlated exit code 0, failing open when the exit code is missing; warns by default and blocks missing `stop:block` steps when `AGENTIC_FLOW_GATE_BLOCK=true`. Fail-open; output names only step ids, never rollout bytes/work-id. |
| `flow-evidence.mjs` | Shared library | Shared library | Evidence engine used by `flow-order-guard.mjs` and `flow-step-guard.mjs`. |
| `codex-flow-evidence.mjs` | Not wired | Shared library | Pure session-scoped flow-evidence derivation for `flow-step-guard-codex.mjs`: active-flow by in-session artifact write, runner/exit evidence through `codex-rollout.mjs`, same-work-id spec/plan pairing (no fallback), `validate_artifacts.py --strict` subprocess, fail-open. Reuses the byte-locked `flow-evidence.mjs` read-only helpers (`loadRequirements`/`blockFlag`/`isSourceFile`). |
| `worktree-scan.mjs` | `Stop` | Not wired (VERIFY this handler on the installed Codex runtime before porting) | Effect-layer DETECTION: scans the bytes that actually landed in the working tree (uncommitted tracked changes plus untracked files) rather than any command string, so the write form is irrelevant - `tee`, `dd`, `base64`, `python -c` and unrecognized redirects all surface identically. That is precisely the class `scan-write-codex.mjs` documents as out of reach. Scans untracked files INCLUDING gitignored ones - `.env` is both the likeliest home for a secret and almost always gitignored, so `--exclude-standard` alone skipped exactly the file that matters; vendored trees (`node_modules`, `.venv`, `dist`, ...) are excluded instead. Advisory by default via `systemMessage` (stderr from a hook that exits 0 never reaches the transcript); `AGENTIC_WORKTREE_SCAN_BLOCK=true` escalates to a Stop block. Per-session dedup, bounded (200 untracked candidates / 256 KiB per untracked file / 4 MiB scan buffers), fail-open, values masked. |
| `git-hook-scan.mjs` | Repo git hook | Repo git hook | Effect-layer PREVENTION, invoked from a repository's own `pre-commit` and `pre-merge-commit` (staged content + credential filenames; `git merge` runs the latter, NOT `pre-commit`), `commit-msg` (the message), and `prepare-commit-msg` - the one commit-path hook Git does NOT suppress under `--no-verify`, and which can read both the staged index and the message. Runs on the git OPERATION, after Git has resolved its alias table and the shell has done quote removal and `$PATH` lookup, so `git ci`, `g'i't commit`, a shell function named `git` and `eval` all reach it identically. `--no-verify` skips pre-commit/commit-msg, but prepare-commit-msg remains a reduced backstop. Install with `scripts/install_git_hooks.py`. |
| `shell-quoting.mjs` | Shared library | Shared library | Pure ANSI-C quoting decoder (`$'...'`). The shell decodes those escapes BEFORE the command runs, so `git commit -m $'\x73\x6b...'` records `sk-...` in history and `echo $'...' > f` writes it to disk while the raw hook input carries no vendor-shaped text. Both the commit-message scan and the write extractor decode through this module first. |
| `git-invocation.mjs` | Shared library | Shared library | Resolves which git subcommands a command line will actually run, expanding git aliases (chains, `!shell` aliases, `-c alias.x=y`), global options, wrappers, quoted command names, and subshell/brace-group wrappers. `-C` is scoped PER STATEMENT and applied cumulatively the way git does (`git -C a -C b` == `cd a/b`); ask for the directories of the calls you care about with `targetCwdsFor` (a command line can carry more than one commit, and each is scanned in its own repository). Commit-message extraction covers `-m`, `--message`, bundled short options (`-am"msg"`), and `-F` files read from the repository of the statement that names them. Cannot see SHELL aliases/functions, `$PATH` shadowing or `eval` — those resolve after the hook has decided (documented in the file header). |
| `scan-commit-names.mjs` | Shared library | Shared library | Linear credential-filename matcher for `scan-commit.mjs`, including derived copies (`id_rsa.bak`, `.npmrc.old`, `server.key.bak`) while leaving ordinary files (`notes.bak`, `keys.md`, `api.keys.json`) clean. Deliberately NOT a regex: the pattern that first implemented derived suffixes backtracked catastrophically (20.6 s at 12 dotted suffixes) on an agent-influenced filename. |
| `secret-patterns.mjs` | Shared library | Shared library | Secret-pattern scanner used by the scan hooks. Vendor-prefix tokens are never keyword-filtered: they are suppressed only when structurally degenerate (a repeated/sequential run, e.g. `ghp_xxxx…`) or an exact published doc sample. The template heuristic applies only to captured (user-authored) values, as anchored whole-value predicates. |
| `codex-write-signal.mjs` | Not wired | Shared library | Pure write-content extractor (apply_patch V4A + bounded literal Bash write forms) used by `scan-write-codex.mjs`. No shell, no I/O. Scans the WHOLE `printf`/`echo` payload, not just its first quoted token. `parsed` means "accounted for the whole command" and defaults to false — an unread write form (`tee`/`dd`/`sed -i`/`cp`/`>|`/`&>`) clears it. |
| `codex-rollout.mjs` | Not wired | Shared library | Pure Codex rollout reader for final-message sentinel presence, recorded commands with correlated exit status, and recognized edit targets; used by the Codex completion/flow adapters. `node:fs` read only; no shell, no eval. |

`flow-requirements.json` is the shared source for active-flow step definitions and source-file extensions. The live flow hooks read it at runtime, and `tests/test_flow_requirements.py` validates that its skill, workflow, agent, and validator references resolve.

`flow-requirements.json` also defines two warn-level steps for the house flows. `branch` flags a source edit while the working directory is on `main` or `master`, observed at Stop on Claude. `review-result` flags a reviewer that was dispatched with no correlated non-error result: control = `implementation-control` / `implementation-auditor`, security = `security-audit` / `security-reviewer`. Both steps are observed on Claude only and never block or deny, under any flag; the live Codex Stop hook reports neither (see [strict evidence limits](../docs/runtime-adapter.md#limits-of-branch-review-result-and-strict-evidence)).

Strict Codex evaluation is opt-in. `AGENTIC_FLOW_STRICT_EVIDENCE` (`true`, `1` or `yes`) makes the live Codex `tests` evidence strict. The offline `python3 scripts/strict_flow_evidence.py --rollout <path> --cwd <dir>` evaluates one rollout and prints exactly three lines: `strict_evidence=green|partial|missing`, `strict_completion=satisfied|unsatisfied|n/a` and `strict_branch=protected|ok|unknown`. It exits 0 only for green evidence with a satisfied or n/a completion, 1 otherwise, and 2 on a preflight or evaluation error. The live hooks never call it.

`completion-claim-guard-codex.mjs` is owner-aware. In a Superpowers-owned or Ambiguous phase it emits a fixed owner-neutral message that asks for fresh verification evidence, and a successful `verification-before-completion` delivery recorded after the phase start silences it. The house message is unchanged in the no-owner, house-owned and unreadable owner-scan cases.

These are bounded backstops, not comprehensive shell or secret enforcement. Most unexpected input/reader failures are fail-open; a recognized flow-order violation can still deny. See [runtime evidence limits](../docs/runtime-adapter.md#codex-flow-evidence-and-limits) for parser bounds, missing-exit fallback, runner-shaped no-op commands, and the absence of freshness checks after the latest source edit.

## Effect Layer: What It Closes, And What It Does Not

The command guards read the raw command string and cannot be complete - shell aliases and
functions, `$PATH` shadowing, `eval` and variable indirection resolve after the hook has decided,
and the write surface is unbounded. The effect layer closes that class by never reading a command:
git runs `pre-commit`/`pre-merge-commit`/`commit-msg`/`prepare-commit-msg` on the OPERATION, and
`worktree-scan.mjs` reads bytes on disk.

The deterministic effect-layer tests (`tests/test_effect_layer_guards.py`) exercise a shell function wrapping `git commit`, an `eval`-assembled commit,
`git $C` indirection, a secret inside an alias-supplied message, `git commit --no-verify`, a
non-fast-forward merge commit, writes via `tee` / `base64 -d` / `python -c`, and a gitignored
`.env`. Their results establish handler behavior, not installed runtime delivery; retain fresh test output before citing a pass.

Stated limits, so nobody reads more into this than it delivers:

- `git -c core.hooksPath=/dev/null commit` disables all hooks - git documents this. A client-side
  hook is a fast local backstop; non-negotiable enforcement belongs server-side (`pre-receive`) or
  in CI.
- `Stop` does not fire on a user interrupt or an API error, so the working-tree scan can be skipped.
- The Stop scan is DETECTION: the bytes are already on disk when it runs. Prevention for the commit
  path is the git hook.
- A timed-out hook renders no decision at all, which is why the scan is bounded.

### Codex

`worktree-scan.mjs` is not wired on Codex (VERIFY). Its default `systemMessage` output and optional Stop `decision: "block"` use documented Codex envelopes, and the handler already checks `stop_hook_active`. A block asks the agent to continue; it does not undo a write. The shared envelope alone does not prove this handler's installed execution, cwd, dedup state, scan coverage, or continuation behavior. Verify those before adding it to the Codex manifest. The existing Codex completion/flow Stop adapters do not establish that separate proof.

Git hook installation is a separate operation from wiring a runtime Stop scan. A sandbox may protect `.git`; perform an authorized install through a runtime that permits those writes. The installer records owned hashes in `<git-dir>/agentic-sdlc-hooks.json` and refuses to replace a foreign hook. External `core.hooksPath` locations require its `--allow-external-hooks-path` opt-in. An existing attribution or other `prepare-commit-msg` hook is a possible collision, not a reason to assume every Codex installation has one.

### Bootstrap ownership and live evidence

Both house SessionStart handlers inject instructions to select the process owner before focused routing and preserve it in conversation context across resume/compact; they do not store or enforce owner state. A namespaced identity does not decide ownership; explicit user choice and the existing phase owner take precedence. The pinned reference's Claude matcher omits resume, while its Codex manifest has `"hooks": {}`; see the [runtime coexistence contract](../docs/runtime-adapter.md#coexistence-and-session-restoration).

Current binary versions and historical hook proof are recorded in [runtime-adapter.md](../docs/runtime-adapter.md#current-binary-and-historical-hook-evidence). Native manifest validation, direct handler tests, and model-access probes are distinct from installed/trusted lifecycle evidence. Capture the latter before claiming current runtime enforcement.

## Conceptual Hooks

These checkpoints require model judgment, so they live as flow gates in skills and contracts.

| Conceptual hook | Enforced by |
|---|---|
| `pre-edit-context-check` | contracts `01-context-first`, `03-plan-mode`; early steps in `root-cause-fix` and `feature-build`. |
| `post-edit-diff-check` | contracts `04-code-quality`, `08-git-safety`; `code-quality-review`; diff review steps. |
| `pre-test-command-check` | contract `05-testing`; `test-authoring`. |
| `post-test-result-check` | contract `05-testing`; TDD loops in implementation skills. |
| `security-sensitive-change-check` | contract `06-security`; `security-audit`. |
| `pre-git-operation-check` | contract `08-git-safety`; the runtime-neutral read-only `git-safety-check` command (Claude Code example: `/agentic-sdlc:git-safety-check`); `scan-commit.mjs`; `branch-guard.mjs`. |
| `flow-step-evidence-check` | `flow-order-guard.mjs`; `flow-step-guard.mjs`; `hooks/flow-requirements.json`; implementation skills and `implementation-control`. |
| `final-response-verification` | `implementation-control` plus `completion-claim-gate`; Claude `completion-claim-guard.mjs` is only a deterministic backstop. |

## Artifact Layouts And Per-Package Evidence

Work-package artifacts resolve in two layouts: the legacy flat `docs/agentic-sdlc/{specs,plans}/<id>.md` (back-compat, unchanged) and the per-package canonical `docs/agentic-sdlc/<slug>/{spec,plan,evidence}/<work_id>.md`, where `<slug>` is lowercase kebab-case `^[a-z0-9][a-z0-9-]{0,63}$` and never a reserved name (`specs`, `plans`, `evidence`, `notes`, `spec`, `plan`).

Per-package evidence persists to `docs/agentic-sdlc/<slug>/evidence/<work_id>.md` — per-package only (flat packages get no evidence), overwritten in place per run (single canonical file, last run wins), git-ignored, and with no validator (it never gates resolution, and no flow guard activates on an evidence write). That evidence write is performed by the main pipeline finalize step, not the read-only `implementation-auditor` sub-agent.

Per-package plan change-detection runs as a filesystem scan, not a `git status` query: new generated plans can be git-ignored, so the resolver scans the filesystem; published plugin documentation is tracked separately.

## Adding Or Disabling Hooks

- Add new scripts under the matching event in `hooks/hooks-claude.json` for Claude Code or `hooks/hooks-codex.json` for Codex when that runtime supports the event.
- Use runtime hook controls to browse or temporarily disable hooks.
- Keep scripts deterministic. Checks that need judgment belong in skills/contracts.
