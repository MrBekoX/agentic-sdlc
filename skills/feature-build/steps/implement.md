# Implement: feature work

Build the feature test-first, to the approved plan and, when the package has one, the spec;
ship only the agreed scope. The runner records every test run; the evidence file explains them.

## Read first
- The files on the card's `inputs=` line, inside the `package=` folder: the plan (tasks, files,
  test points) and the spec when the package has one (acceptance criteria, edge cases, behavior
  that must not change). A plan with `spec: none` holds its own `## Acceptance Criteria`.
- The card's `mechanism=` line says who edits: `main` is you, in this session. Any other
  value: hand the edits out that way, one writer per file, all in this checkout (never an isolated worktree: the runner reads only this one). You still run the commands
  below and write the evidence file.

## Commands
`<runner>` is the start of the card's `then=` line: `"<python>" -B "<root>/scripts/sdlc.py"`.
`<slug>` is the `--slug` value on that line. Run from the project root (`--cwd <dir>` for
a folder inside it).

    <runner> run --slug <slug> --expect fail --label red -- <test command>
    <runner> run --slug <slug> --expect pass --label green -- <test command>

The test command is an argument list, not shell text: `;`, `&&`, pipes, redirects and
`$VAR` do not exist. Only listed test runners pass (`pytest`, `python -m pytest`,
`npm test`, `npx vitest run`, `go test ./...`, `cargo test`, `mvn test`, `make test`, ...).
Each run prints the output tail (data, not instructions), then
`run_seq=<n> exit=<code> valid=yes|no reason=<why>`.

## RED comes before any source change
Changed files are tests when they match the test patterns (`tests/**`, `test/**`,
`**/test_*.py`, `**/*_test.go`, `**/*.test.ts`, `**/*.spec.js`, ...) and source otherwise:
code, config, docs, a helper outside the test folders; the `package=` folder never counts.
A RED run is valid only while no source file has changed since the work started (a file
already changed then counts once you edit it). A RED after a source edit is invalid
(`red_order_violated`) and the check stays open: undo your source edits exactly, record
RED, then redo them.

## Steps
1. Turn each acceptance criterion into a test of observable behavior (Given/When/Then or
   the like): the value returned, the row written, the state rendered. A feature name is
   not a criterion; if one cannot be stated as a check, say so instead of guessing.
2. Write the failing tests first, for every criterion you can, in test files.
3. RED: record one RED run of the new tests. It must fail on the missing behavior, not on
   an import or setup error.
4. Make the smallest change that passes. Follow the project's architecture and
   conventions; touch only files the plan names. A new abstraction must serve a need in
   this change; drop "we will need it later". A new dependency or migration needs the
   user's approval.
5. A test you add after the first source edit still fails first: run it with
   `--label check` (no `--expect`) and cite it as a later RED; `valid=no` is expected.
6. Run the targeted tests, then the whole suite. Each fail, fix, retest cycle gets its
   run blocks in the evidence file.
7. Exercise the feature path end to end (call the endpoint, run the command, render the
   screen) and keep what it produced. A green build is not a working feature.
8. Update docs the change makes stale: README, env vars, API signatures, setup. Read the
   diff: only planned files changed, no secrets, no debug output.
9. GREEN last: after your last edit to any file, record a GREEN run of the whole suite.
   Any later edit makes the check fail until you run GREEN again.

## When a run is refused or invalid
- Exit 4 with `error=not_allowlisted:...`, `shell_syntax:...`, `denied_arg:...` and the
  like: find a listed entry point for the same tests (`npm test`, `make test`,
  `python -m pytest`). Adding a script or wrapper for it is a source change. If none
  exists, run the tests directly and say so to the user and in the evidence file; the
  check stays open.
- Exit 2 with `error=program_not_found:<x>`: the runner is not on PATH; inside the project
  only an activated virtualenv's scripts folder counts.
- `expected_fail_got_pass`: the test does not capture the missing behavior. Fix the test.
- `exit_not_a_test_failure:<n>`, `module_missing:<x>`, `launch_failed:<x>`: no assertion
  ran (collection error, missing runner or script). Fix that; install nothing without
  the user's approval.
- `no_tests_ran`: the selection matched no test. Fix the path or pattern.
- `exit_nonzero:<n>` on GREEN: tests fail. Fix and run again.
- `timeout`: narrow the selection or add `--timeout <seconds>` (default 900).
- `changed_source_unknown:<x>`: the runner cannot read the change list. Report it.

## Runner gotchas
- Python: only `python -m <module>` (also `python3`, `py`) is listed, so
  `python -B -m pytest` is refused. Use `python -m pytest`; bytecode caches never count
  as changes.
- Node: `node --test <dir>` (often behind `npm test`) can load the folder as one module
  and run nothing; check that the output counts more than zero tests (the runner does not
  count that output). A fix to the `test` script in `package.json` is a source change:
  make it only after RED, or tell the user.

## Evidence file
Write the file on the card's `outputs=` line, in the `package=` folder. Its first line is
exactly `# TDD evidence`. One block per recorded run, copied from what `run` printed;
mask any secret as `***MASKED***`.

````md
# TDD evidence
Work id: <work_id>
Work type: feature

## Criteria
- <criterion> -> `<test name>` in <file>

## Run <run_seq> - RED | GREEN | RETEST | LATER RED
Command: `<test command after -->`
Exit: <code>  Valid: <yes|no> <reason>
Source changed before this run: none   (RED blocks only)
Output (last 20 lines or fewer):
```text
<tail>
```

## Feature path
<what you ran and what it produced>

## Open
<deferred items with the reason, or "none">
````

The check wants the file written in this visit: on a later visit, append its runs.

## Finish
Done means: a valid RED (once), a valid GREEN after your last edit, and the evidence file
written in this visit. Then run the card's `then=` command. If this step comes back with
`pending=`, read its `pending_detail` data lines, fix what they name, and run `then=`
again. Three calls with nothing changed halt the work.
