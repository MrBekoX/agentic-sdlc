# Quality gates

Run the project's own lint, typecheck and build checks on the current source, record them through the runner, and report.

In the commands below, `<python>` is the interpreter that starts the card's `then=` line and `<root>` is the card's `root=` value. Run them with `-B`, as the `then=` line does: it keeps `__pycache__` out of the plugin folder. `<slug>` is the last part of the card's `package=` value.

## 1. Pick the gates
The start probe found a toolchain: read `probes.details.toolchain.toolchains` in `<package>/state.json` (`node`, `python`, `dotnet`, `go`, `rust`, `make`). Use the commands the project already configures, for example:
- Node or TypeScript: `npm run lint`, `npm run typecheck`, `npm run build`, `npx tsc --noEmit`, `npx eslint .`;
- Python: `ruff check .`, `ruff format --check .`, `mypy <source dir>`;
- Go: `go vet ./...`; Rust: `cargo test`; .NET: `dotnet test`;
- make: `make check`; Gradle: `./gradlew check`; Maven: `mvn verify`.

Never install a tool or add a config just to make a gate run. A gate the project does not have is `N/A` in the report, with the reason.

## 2. Record each gate
Run each gate through the runner, which records it against the current source:

`"<python>" -B "<root>/scripts/sdlc.py" run --slug <slug> --expect pass --label check -- <command and its arguments>`

- The runner runs the argv without a shell: no pipes, no `&&`, no redirects, no `|| true`. It prints the output tail and a `run_seq=... exit=... valid=yes|no reason=...` line.
- The step needs at least one valid passing `--label check` run at the current source. When the stack offers no lint, typecheck or build command the runner accepts, record the project's test command with `--label check` and say so in the report.
- A command the runner refuses (exit 4: not on its list) may be run directly. Put its command, exit code and a short output tail in the report; it does not count for the check.
- As the card's mechanism line says: `parallel-runs` starts the independent gates side by side (several commands at once); `main` runs them one after another.

## 3. Secret scan
When the project already uses a secret scanner (gitleaks, trufflehog, detect-secrets), run it directly. Never print a found value: report `file:line` and the risk type, with the value as `***MASKED***`.

## 4. When a gate fails
- Lint: fix the formatting only, with no behaviour change.
- Types: fix the type. No gratuitous `any`, `!` or `as unknown as`.
- Run the gate again through the runner after each fix. The runs that count are the ones at the final source.
- A source fix here reopens the earlier checks that depend on the source; the runner handles that.
- A failure you cannot fix without changing behaviour or scope: stop and tell the user. Never weaken, skip or silence a gate.

## 5. Write the report
Write the file the card's `outputs=` line names:

```md
# Quality gates
Toolchain: <toolchains>

| Gate | Command | run_seq | Exit | Result |
|---|---|---|---|---|
| lint | `ruff check .` | 12 | 0 | pass |

N/A: <gate>: <reason>
Run directly (not recorded): <command>: exit <n>
Secret scan: <tool> clean | <file:line> <risk type> ***MASKED*** | no scanner configured
Fixes applied: <what changed and why>
```

The line `# Quality gates` must appear exactly like that, on its own line. Write the report in this visit: a file left from an earlier visit, or rewritten byte for byte, does not count.

## Finish
Write the report, then run the card's `then=` command.
