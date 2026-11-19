# Implementation audit

Check from artifacts only that the work followed its steps and meets its criteria. The auditor reads; you gather the evidence and write the report.

## Before the audit
Take `<python>`, `<root>` and `<slug>` from the card's `then=` command, the work id from its `outputs=` path.
1. After your last edit, record a GREEN run of the full suite for the scope:
   `"<python>" -B "<root>/scripts/sdlc.py" run --slug <slug> --expect pass --label green -- <test command>`
   The test command is argv for an allowlisted test runner: no shell, no pipes.
2. From the project root, run the resolver; keep its output and exit code verbatim:
   `"<python>" -B "<root>/scripts/resolve_work_package.py" --plan "<package>/plan/<work_id>.md"`
   Leave out `--plan` when the package has no plan. Where `done_when=` names the resolver, a failed or ambiguous result blocks this step: show the user its error lines and wait. Never guess the package.
3. For the auditor, collect the package paths (`request.md`, `context.md`, spec, plan, `runs.jsonl`, `state.json`, `approvals.jsonl`, every report in `evidence/`) and the diff: `git diff --no-ext-diff --no-textconv <base_commit>` (`base_commit` is in `state.json`) plus the untracked files from `git status --porcelain=v1 --untracked-files=all`. Above about 400 lines, send `--stat` and the file list, and tell the auditor to read every listed file.

## How the role runs
Read `mechanism=` on the card.
- `subagent` or `workflow`: run the `implementation-auditor` role in fresh context. Its role file is `<root>/agents/implementation-auditor.md` (without that folder, the file of that name under `<root>/skills/`). Give it the role file, the resolver output, the diff and the paths, never your account of the work.
- `inline-degraded`: play the role yourself from the same inputs only, and mark the report degraded.
- A launch that fails or is refused: record it, then run the role inline. `<capability>` is the one that failed (`subagent` or `workflow`); `<reason>` is `missing`, `denied` or `unavailable`:
  `"<python>" -B "<root>/scripts/sdlc.py" note --slug <slug> --degraded <capability> --reason <reason>`

## The rows
Give the auditor this section; its rows replace the role file's fixed checklist. One row per step of this package before this one, except the strategy step, in order (`steps` in `state.json`); a step the runner skipped is `N/A` with its `skip_reason`. Then four rows every audit has. A row is PASS only with its own artifact quoted:
- context: the `## Scope Lock` text. intent: `design.md` and its decisions with their owners. branch: the branch name, or `branch_policy=stay` with its quote.
- spec: the spec path and one acceptance criterion with its `(source: ...)` tag. spec-check: `spec/<work_id>.check.json`, its `reader` value (`fresh` or `degraded`) and the pile of each question; an open question is FAIL.
- plan: the plan path, its `spec:` line, and one task with the criteria it covers. spec-review: the approval record of the spec gate. plan-review: the approval record of the plan gate.
- draft: the spec and plan paths, one acceptance criterion read from them, the sidecar's `critic` value. review: the approval record.
- docs-check, quality-gates, diff-review, quality-review: the report and its result; an open must-fix or a failing gate is PARTIAL or FAIL.
- characterize: the `## Goal Lock` text and its GREEN run before the first edit.
- implement: the TDD evidence file and the runs in order. Feature or bugfix: a failing run after the first test edit and before the first production edit, then GREEN. Refactor: GREEN before the first edit and after each step. Test work: no lasting production change.
- security: the `Verdict:` line and one traced input to sink, or why no input reaches a sink.
- Work package: the resolver's `spec=` and `plan=` lines and exit 0. Test run: the GREEN run's `run_seq`, argv, exit code and summary line (N passed, 0 failed, 0 skipped).
- Diff scope: the files and line ranges read, and what put them in scope. Acceptance criteria: each one and the test or line that meets it.
PARTIAL or FAIL names the exact artifact that is absent ("no failing run before the first source edit"). The only statuses are PASS, PARTIAL, FAIL and N/A. Report `red.order` and `gate_order` from `state.json` when set.

Special paths:
- Refactor work with a Goal Lock and no spec or plan: grade scope and behavior against the Goal Lock; the Spec and Plan rows are `N/A (refactor: Goal Lock)`. With an approved spec and plan, grade them as for any work. A missing Goal Lock is FAIL.
- A plan with its own criteria (the resolver prints `spec=none`; the plan carries `spec: none` with `flow:` `bugfix`, `feature` or `plan`): grade against the plan's own `## Acceptance Criteria`, and a bugfix plan also against its `## Bug`; the Spec row is `N/A (criteria in the plan)`. Tell the auditor so. `spec: none` with any other flow is a missing spec: FAIL.
- A package with no implement step audits earlier work: grade the rows it needs (spec and plan or Goal Lock, tests run, security, diff scope) from what the resolver and the request point to. A row with no artifact is FAIL, not N/A. Change no code.

## The report: `<package>/evidence/<work_id>.audit.md`
Put `# Implementation audit` first, in place of the role's own title line, then the auditor's report:

    # Implementation audit

    Auditor: fresh sub-agent
    Resolver: exit 0; <its key=value lines>

    ## Overall Status
    PASS

    ## Checked Flow
    | Row | Status | Evidence |
    |---|---|---|

    ## Missing Steps
    ## Risky Changes
    ## Required Fixes Before Final
    ## Final Decision
    allow-final

- `# Implementation audit` is the first line, exactly.
- One value under `## Overall Status` (PASS, PARTIAL or FAIL) and one line under `## Final Decision`: `allow-final`, or `block-final` with its reason.
- For an inline run: `Auditor: inline (degraded: <the card's degraded= value>), not independent`.
- Never mark a step PASS from memory or from the implementer's notes. An empty `## Missing Steps` while an artifact is absent is a false report.

## When the decision is block-final
- With an implement step in this package, a gap in the work (a missing test, an out-of-scope edit, an unmet criterion): fix it, then run `then=` before you write the report. The runner re-opens the steps the change affects and brings you back here.
- Any other gap (it needs the user, or a past step's evidence is lost): write the report with `block-final` and the reason. Never write `allow-final` to move on. If `done_when=` asks for `allow-final`, tell the user what blocks and end your turn; on their word, run `then=` with `next` replaced by `halt --reason "<their words>"` (`resume` returns here).

## Finish
Write the report, then run the card's `then=` command.
