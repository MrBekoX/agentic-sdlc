# Data Handling

This page lists what the runtime hooks wired in `hooks/hooks-claude.json` and `hooks/hooks-codex.json`, the hook modules they import, and the eval and review helpers named below read and write on the machine where they run. It does not cover the Git hooks that `scripts/install_git_hooks.py` installs. Each statement cites the source that implements it.

`tests/test_release_readiness_docs.py` re-derives part of the hook inventory on every run: a hook source under `hooks/` that contains `transcript_path`, `writeFileSync`, `readdirSync` or `spawnSync` fails the local gate until this page names it. The same test checks the hook read, work-package and eval persistence statements below against the source text that implements them.

## What hooks read

Hook wiring comes from `hooks/hooks-claude.json` (Claude Code) and `hooks/hooks-codex.json` (Codex).

### Session transcripts

These hooks open the transcript or rollout file named by the `transcript_path` field of their hook input:

| Hook | Runtime | Event |
|---|---|---|
| `hooks/completion-claim-guard.mjs` | Claude Code | `Stop` |
| `hooks/flow-step-guard.mjs` | Claude Code | `Stop` |
| `hooks/flow-order-guard.mjs` | Claude Code | `PreToolUse` for `Write`, `Edit`, `MultiEdit` |
| `hooks/completion-claim-guard-codex.mjs` | Codex | `Stop` |
| `hooks/flow-step-guard-codex.mjs` | Codex | `Stop` |
| `hooks/flow-order-guard-codex.mjs` | Codex | `PreToolUse` for `Bash`, `apply_patch` |

### Work-package artifacts

The flow hooks check whether a flow's spec and plan steps produced valid artifacts. `hooks/flow-step-guard.mjs` and `hooks/flow-order-guard.mjs` do this through `hooks/flow-evidence.mjs`. `hooks/flow-step-guard-codex.mjs` and `hooks/flow-order-guard-codex.mjs` do it through `hooks/codex-flow-evidence.mjs`.

`hooks/flow-evidence.mjs` and `hooks/codex-flow-evidence.mjs` list the directory entries of the artifact locations that `hooks/flow-requirements.json` configures, relative to the session working directory, to find Markdown artifact files: `docs/agentic-sdlc/specs`, `docs/agentic-sdlc/plans`, and the `spec` and `plan` folders of each work package under `docs/agentic-sdlc`.

To validate a matched file, `hooks/flow-evidence.mjs`, `hooks/codex-flow-evidence.mjs` and `hooks/flow-order-guard-codex.mjs` start a Python interpreter and run `scripts/validate_artifacts.py` on it. They try the interpreter named by the `AGENTIC_SDLC_PYTHON` environment variable first when it is set, then `python3`, `python` and, on Windows, `py -3` from `PATH`. Each attempt has a 10-second timeout.

### Session context

The `SessionStart` hooks `hooks/session-start.mjs` (Claude Code) and `hooks/session-start-codex.mjs` (Codex) run `git` to read the current branch and working-tree status. They add a one-line status summary and the plugin bootstrap text to the session context through `additionalContext`.

### Commands and Git state

The command guards `hooks/branch-guard.mjs`, `hooks/scan-commit.mjs` and `hooks/destructive-command-guard.mjs` read the shell command from the tool input (`tool_input.command`). `hooks/branch-guard.mjs` and `hooks/scan-commit.mjs` read Git alias definitions through `hooks/git-invocation.mjs`, which runs `git config --get alias.<name>`, so an aliased commit or push is recognized. `hooks/branch-guard.mjs` runs `git` to read the current branch. `hooks/scan-commit.mjs` runs `git diff` to read the added diff lines of a commit, takes the commit message from the `-m` text in the command, and reads the contents of any file named by `-F` or `--file`, resolved against the working directory of the statement that names it.

### Written content

`hooks/scan-write.mjs` (Claude Code, `PostToolUse` for `Write`, `Edit`, `MultiEdit`) reads the new text from the tool input (`new_string`, `edits[].new_string` or `content`). When none of those fields is present, it reads the file named by `tool_input.file_path`. `hooks/scan-write-codex.mjs` (Codex, `PreToolUse`) reads the content of a recognized literal write before it runs.

### Working tree

`hooks/worktree-scan.mjs` (Claude Code, `Stop`) runs `git` to read the added lines of `git diff HEAD` for tracked changes, and to list untracked files, gitignored files included. It reads the bytes of those untracked files to scan them for secret-shaped content. It skips vendor and tool-state directories, such as `node_modules` and `.claude`, and caps the scan at 200 files, 256 KiB per file and 4 MiB in total; binary files and files over the per-file cap are skipped. It also flags changed or untracked files whose names mark them as credential files.

## What hooks write

`hooks/worktree-scan.mjs:125-141` writes one per-session deduplication state file under the operating system's temporary directory, at `agentic-sdlc/worktree-scan-<session>.json`, or at the path set in the `AGENTIC_WORKTREE_SCAN_STATE` environment variable. The file holds finding keys only: the first 16 hexadecimal characters of a SHA-256 digest over a finding's pattern label and its location, which is a file path or, for a finding in the tracked diff, the literal `uncommitted change`.

Hooks report their results to the runtime as JSON on standard output.

## Masking

Hook findings show a pattern label and a location, such as a file path, an added-line number or the commit message (`hooks/scan-commit.mjs`, `hooks/scan-write.mjs`, `hooks/worktree-scan.mjs:144-145`). The matched value is left out of the message.

Eval and review artifacts that the helper scripts persist pass through `scripts/sensitive_redaction.py`. It is a fail-closed adapter to `hooks/redact-sensitive.mjs`: it raises an error when `node` is missing or the redactor fails, so unredacted output is not written. Its behavior is covered by `tests/test_sensitive_redaction.py`. The callers are `scripts/run_trigger_eval.py`, `scripts/run_codex_trigger_eval.py`, `scripts/run_routing_eval.py`, `scripts/run_procedure_eval.py`, `scripts/run_glm_trigger_eval.py`, `scripts/review_package.py` and `scripts/task_brief.py`.

## Eval artifact persistence

The helpers below write transcripts, review packages and task briefs, redacted as described under Masking, to these locations:

- `scripts/run_trigger_eval.py`, `scripts/run_codex_trigger_eval.py`, `scripts/run_routing_eval.py` and `scripts/run_glm_trigger_eval.py` write a transcript file only when `--transcript-dir` is given, and write it into that directory.
- `scripts/run_all_trigger_evals.py:22` sets the default `--transcript-dir` that it passes to the Claude and Codex trigger runners to `tests/artifacts/trigger-matrix`, inside the gitignored `tests/artifacts/` directory.
- `scripts/run_procedure_eval.py` writes live-run transcripts into `--transcript-dir` when it is given, and otherwise into a `transcripts` folder inside the temporary directory it creates for the run. Python removes that temporary directory when the run ends; because cleanup errors are ignored, a file it cannot delete is left in place.
- `scripts/review_package.py` writes a review package into `--out-dir` when it is given, and otherwise into the Git `sdd` path (`git rev-parse --git-path sdd`), or `.sdd` when that Git command fails or prints nothing.
- `scripts/task_brief.py` writes a task brief into `--out-dir` when it is given, and otherwise into a `.handoffs` folder beside the plan file.

## Model providers

The skills run inside Claude Code or Codex. Content that the runtime sends to a model, including files the agent reads and tool output, is processed by the model provider the user configured in that runtime, under that provider's terms.

## Directory Policy 3.A

Listing metadata links this page only through a URL whose `docs/publication/link-checks.json` entry records `http_status` 200 with `auth` `none` (decision DP10). `.codex-plugin/plugin.json` currently carries no `privacyPolicyURL`.
