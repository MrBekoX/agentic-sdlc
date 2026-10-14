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
| `hooks/cursor-launch.mjs` | Cursor | Forwards `transcript_path` to `hooks/flow-order-guard.mjs` on `preToolUse`. The launcher does not open that file. |

### Work-package artifacts

The flow hooks check whether a flow's spec and plan steps produced valid artifacts. `hooks/flow-step-guard.mjs` and `hooks/flow-order-guard.mjs` do this through `hooks/flow-evidence.mjs`. `hooks/flow-step-guard-codex.mjs` and `hooks/flow-order-guard-codex.mjs` do it through `hooks/codex-flow-evidence.mjs`.

`hooks/flow-evidence.mjs` and `hooks/codex-flow-evidence.mjs` list the directory entries of the artifact locations that `hooks/flow-requirements.json` configures, relative to the session working directory, to find Markdown artifact files: `docs/agentic-sdlc/specs`, `docs/agentic-sdlc/plans`, and the `spec` and `plan` folders of each work package under `docs/agentic-sdlc`.

To validate a matched file, `hooks/flow-evidence.mjs`, `hooks/codex-flow-evidence.mjs` and `hooks/flow-order-guard-codex.mjs` start a Python interpreter and run `scripts/validate_artifacts.py` on it, through the shared `runValidator` in `hooks/flow-evidence.mjs`. It tries the interpreter named by the `AGENTIC_SDLC_PYTHON` environment variable first when it is set, then `python3`, `python` and, on Windows, `py -3`, resolving each name only through absolute `PATH` entries, so an executable in the project directory is never run. A candidate is used only when a `-c` probe reports Python 3.8 or newer (3-second timeout); the Microsoft Store alias, a launcher without an installed Python and Python 2 are skipped. The validator run itself has a 10-second timeout. When no candidate qualifies, the hooks treat the validator as unavailable and fail open.

### Session context

The `SessionStart` hooks `hooks/session-start.mjs` (Claude Code and ZCode) and `hooks/session-start-codex.mjs` (Codex) run `git` to read the current branch and working-tree status. They add a one-line status summary and the plugin bootstrap text to the session context through `additionalContext`. The bootstrap names the plugin's absolute install path, resolved from the hook's own file location, so the model can run bundled helpers without a shell variable; that path can contain the operating-system user name and therefore reaches the session transcript.

### Commands and Git state

The command guards `hooks/branch-guard.mjs`, `hooks/scan-commit.mjs` and `hooks/destructive-command-guard.mjs` read the shell command from the tool input (`tool_input.command`). `hooks/branch-guard.mjs` and `hooks/scan-commit.mjs` read Git alias definitions through `hooks/git-invocation.mjs`, which runs `git config --get alias.<name>`, so an aliased commit or push is recognized. `hooks/branch-guard.mjs` runs `git` to read the current branch and bounded local push state as described below. `hooks/scan-commit.mjs` runs `git diff` to read the added diff lines of a commit, takes the commit message from the `-m` text in the command, and reads the contents of any file named by `-F` or `--file`, resolved against the working directory of the statement that names it. Under Kimi Code (detected by the `KIMI_PLUGIN_ROOT` variable Kimi exports to its hooks), both guards take the repository from the Bash tool's own `tool_input.cwd` (resolved against the session `cwd`, which is the fallback when it is absent), because Kimi runs the command there. Every hook starts `git` through `hooks/git-exec.mjs`, which resolves it only through absolute `PATH` entries, so a `git` in the project directory is never run, and disables colour (`color.ui`, `color.diff`), relative diffs, fsmonitor and repository hooks (`core.hooksPath` pointed at a never-created folder inside the plugin; the flow guard's branch probe, which runs no hook-triggering command, keeps its own fixed argv); diffs use `--text --no-ext-diff --no-textconv` so repository settings cannot hide added lines.

For a resolved push context, the branch guard queries only local ref names (`for-each-ref`, including custom namespaces for canonical-source matching), remote names (`remote`, without URLs), and relevant configuration (`config --null --get-regexp`: push defaults, remote push/mirror mappings and branch remote/pushRemote/merge entries). Fixed argv arrays reach the hardened Git launcher; command text is never executed. Ordered inline configuration is parsed in memory, not forwarded to a subprocess. Payload-derived repository/config paths and command-supplied Git environment/include/path overrides remain unresolved and do not widen these reads. Results are cached per repository, with a one-second/1 MiB query limit and four-second aggregate budget. Failed reads remain unknown rather than successful empty state. The pure `hooks/push-targets.mjs` helper consumes these values without I/O, never queries remote refs and emits only fixed protected-branch labels in hook decisions. Mirror/prune deletion potential is handled conservatively; tag-derived unqualified remote namespaces remain unknown offline.

The optional installed Git hooks' message modes read and scan the raw message file, including hash-prefixed commentary that Git may retain. No comment-cleanup guess discards bytes before secret detection. Existing sample/placeholder and same-line suppression rules still apply, and findings omit matched values. This change adds no message path or reader beyond the existing hook argument.

Configured mapping computation also has a deterministic per-invocation budget of 8 Mi UTF-16 character units, accounting comparison and inverse-candidate string lengths. Repeated inverse candidates are deduplicated and literal negatives indexed. Exhaustion is an unresolved query, distinct from successful no-match; it introduces no fallback destination or output of configuration text. Other independently known explicit protected targets remain eligible for the existing warn/deny decision.

### Written content

`hooks/scan-write.mjs` (Claude Code and ZCode, `PostToolUse` for `Write`, `Edit`, `MultiEdit`) reads the new text from the tool input (`new_string`, `edits[].new_string` or `content`). When none of those fields is present, it reads the file named by `tool_input.file_path`. `hooks/scan-write-codex.mjs` (Codex, `PreToolUse`) reads the content of a recognized literal write before it runs.

When `hooks/scan-write.mjs` finds something, it emits its advisory on two channels: `systemMessage`, which the user sees, and `hookSpecificOutput.additionalContext`, which Claude Code documents as visible to the MODEL in the transcript for `PostToolUse`. The model therefore also sees the file path and the pattern label. This is the same content the user-visible message already carried — the matched value is masked on both channels — but it is a new audience, added because the advisory-only `systemMessage` field is outside ZCode's documented hook-output key set, where a warn carrying only it would reach nobody; under ZCode the `hooks/hook-output.mjs` emitter writes only the documented `hookSpecificOutput` key. The command guards `hooks/branch-guard.mjs` and `hooks/scan-commit.mjs` are wired to `PreToolUse`. On that event Claude Code adds `additionalContext` to the model's context beside the tool result ([hooks](https://code.claude.com/docs/en/hooks), fetched 2026-10-07). Those two guards do not emit the field; their deny text is `permissionDecisionReason`, which the model also sees, so that text names no way to silence the scanner.

### Working tree

`hooks/worktree-scan.mjs` (Claude Code, `Stop`) runs `git` to read the added lines of the tracked changes against `HEAD` (before the first commit, of the staged and unstaged diffs), and to list untracked files, gitignored files included. It reads the bytes of those untracked files to scan them for secret-shaped content. It skips vendor and tool-state directories, such as `node_modules` and `.claude`, and caps the scan at 200 files, 256 KiB per file and 4 MiB in total; binary files and files over the per-file cap are skipped. It also flags changed or untracked files whose names mark them as credential files.

## What hooks write

`hooks/worktree-scan.mjs:183-208` writes one per-session deduplication state file under the operating system's temporary directory, at `agentic-sdlc/worktree-scan-<session>.json`, or at the path set in the `AGENTIC_WORKTREE_SCAN_STATE` environment variable. The file holds finding keys only: the first 16 hexadecimal characters of a SHA-256 digest over a finding's pattern label, its location and the matched line of text. The location is a file path or, for a finding in the tracked diff, the literal `uncommitted change`. The matched line is hashed so that a different secret at the same place counts as new; it is never written to the file itself. The digest is unsalted and truncated, so it is not reversible, but someone who can read the file could confirm a guess of the line; for that reason the folder is created owner-only (mode 0700) and the file mode 0600 on POSIX systems (Windows ignores the mode and keeps the temporary directory per user).

The Claude Stop hooks `hooks/completion-claim-guard.mjs` and `hooks/flow-step-guard.mjs` also read `last_assistant_message` and `background_tasks` from the Stop payload. Shell entries in `background_tasks` can carry command lines. `scripts/run_trigger_eval.py` writes a command shim into the selected project's `.claude/commands/` for the duration of a query when `--plugin-dir` is absent, then removes the file and any directory that run created.

Hooks report their results to the runtime as JSON on standard output.

## Masking

Hook findings show a pattern label and a location, such as a file path, an added-line number or the commit message (`hooks/scan-commit.mjs`, `hooks/scan-write.mjs`, `hooks/worktree-scan.mjs:211`). The matched value is left out of the message.

Eval and review artifacts that the helper scripts persist pass through `scripts/sensitive_redaction.py`. It is a fail-closed adapter to `hooks/redact-sensitive.mjs`: it raises an error when `node` is missing or the redactor fails, so unredacted output is not written. Its behavior is covered by `tests/test_sensitive_redaction.py`. The callers are `scripts/run_trigger_eval.py`, `scripts/run_codex_trigger_eval.py`, `scripts/run_routing_eval.py`, `scripts/run_procedure_eval.py`, `scripts/run_glm_trigger_eval.py`, `scripts/review_package.py` and `scripts/task_brief.py`.

## Eval artifact persistence

The helpers below write transcripts, review packages and task briefs, redacted as described under Masking, to these locations:

- `scripts/run_trigger_eval.py`, `scripts/run_codex_trigger_eval.py`, `scripts/run_routing_eval.py` and `scripts/run_glm_trigger_eval.py` write a transcript file only when `--transcript-dir` is given, and write it into that directory.
- `scripts/run_all_trigger_evals.py:22` sets the default `--transcript-dir` that it passes to the Claude and Codex trigger runners to `tests/artifacts/trigger-matrix`, inside the gitignored `tests/artifacts/` directory.
- `scripts/run_procedure_eval.py` writes live-run transcripts into `--transcript-dir` when it is given, and otherwise into a `transcripts` folder inside the temporary directory it creates for the run. Python removes that temporary directory when the run ends; because cleanup errors are ignored, a file it cannot delete is left in place.
- With `--strict-evidence --evidence-dir <dir>`, `scripts/run_procedure_eval.py` also writes one redacted `<case-id>.transcript.jsonl` and one `<case-id>.json` evidence packet per case into that directory. It refuses a directory inside the fixture root or a fixture copy (`evidence_dir_inside_fixture`) and never overwrites an existing packet (`evidence_packet_exists`). The transcript copy is redacted line by line, and the user segment of a home-directory path is masked in the copy and in the packet.
- `scripts/review_package.py` writes a review package into `--out-dir` when it is given, and otherwise into the Git `sdd` path (`git rev-parse --git-path sdd`), or `.sdd` when that Git command fails or prints nothing.
- `scripts/task_brief.py` writes a task brief into `--out-dir` when it is given, and otherwise into a `.handoffs` folder beside the plan file.

## Model providers

The skills run inside Claude Code, Codex, Kimi Code, Grok CLI, ZCode or Cursor. Content that the runtime sends to a model, including files the agent reads and tool output, is processed by the model provider the user configured in that runtime, under that provider's terms.

## Directory Policy 3.A

Listing metadata links this page only through a URL whose `docs/publication/link-checks.json` entry records `http_status` 200 with `auth` `none` (decision DP10). `.codex-plugin/plugin.json` currently carries no `privacyPolicyURL`.
