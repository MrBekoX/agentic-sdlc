# Quality review

Review the changed code for quality in fresh context and write one report. Change no code in this step.

## Scope
- The change: `git diff --no-ext-diff --no-textconv <base_commit>` plus the untracked files from `git status --porcelain=v1 --untracked-files=all`. `base_commit` is in `<package>/state.json`. When `<package>/request.md` names files, a folder or a pull request to review instead, review those.
- The criteria: `## Scope Lock` in `<package>/context.md`, and the package's `spec/<work_id>.md` and `plan/<work_id>.md` when they exist (a spec-less bugfix plan holds its own `## Acceptance Criteria`).
- Read every changed line. Small diffs hide sharp bugs too, and passing tests do not make a change correct or maintainable.

## How the role runs
Read `mechanism=` on the card. Take `<python>`, `<root>` and `<slug>` from its `then=` command.
- `subagent` or `workflow`: run the `code-reviewer` role in fresh context. Its role file is `<root>/agents/code-reviewer.md` (without that folder, the file of that name under `<root>/skills/`). Give the reviewer the role file, the diff and the criteria, never your reasoning about how the change was written.
- When the diff spans two or more independent layers or file groups, run one reviewer per layer at the same time; each gets only its slice and the criteria. For a structural change, add one `software-architect` role for the architecture lens.
- `inline-degraded`: play the role yourself. Read the role file, then only the diff, the files it names and the criteria. Mark the report degraded (see the Reviewer line below).
- A launch that fails or is refused: record it, then run the role inline. `<capability>` is the one that failed (`subagent` or `workflow`); `<reason>` is `missing`, `denied` or `unavailable`:
  `"<python>" -B "<root>/scripts/sdlc.py" note --slug <slug> --degraded <capability> --reason <reason>`
You merge the results: drop duplicates, split must-fix from optional, order by severity.

## Review areas
Readability, maintainability, simplicity, duplication, overengineering (speculative abstraction or configuration nobody asked for), naming, error handling (real paths handled, no swallowed errors), performance (N+1 calls, unbounded queries, needless allocation), architecture consistency (layers, boundaries, conventions), testability.

## What counts
- Each finding names the exact `file:line`, the concrete consequence (the bug it risks, the future change it blocks, the reader it misleads) and the specific change. A category such as "improve naming" or "add error handling" is not a finding.
- Naming: give the identifier, the name to use instead, and the wrong inference the current name invites.
- Maintainability: name the realistic future change and the line that would have to move for it.
- Performance: show the input that makes it bite (the N, the unbounded set) at `file:line`, or drop it.
- Must-fix is correctness, security or a requirement gap. Optional is style or preference.
- Flag only what touches correctness, the stated requirement or maintainability. Leave taste alone and do not manufacture findings to look thorough.
- "No must-fix" is evidence too: name the lines read and the properties checked (this path handles the empty case; that error is propagated, not swallowed).
- Reject a draft that reads like "overall clean, maybe tidy some names": no `file:line`, no consequence, no replacement.

## The report: `<package>/evidence/<work_id>.quality.md`
The work id is in the card's `outputs=` path. Write:

    # Quality review

    Reviewer: fresh sub-agent (<layers or "whole diff">)
    Scope: <base commit> to the working tree; <files and line ranges read>

    ## Must-fix
    - `<file:line>`: <issue>. Consequence: <what goes wrong>. Change: <the specific change>.

    ## Optional
    - `<file:line>`: <issue>. Change: <the specific change>.

    ## Coverage
    - AC1: met at `<file:line>` | not met: <what is missing>

    ## Checked clean
    - <lines read and the properties checked on them>

- `# Quality review` is the first line, exactly.
- A section with nothing in it says `none`. Without a spec or plan, `## Coverage` says so.
- For an inline run the line reads `Reviewer: inline (degraded: <the card's degraded= value>), not independent`.

## Finish
Write the report, then run the card's `then=` command. The must-fix list is the result: do not fix it in this step.
