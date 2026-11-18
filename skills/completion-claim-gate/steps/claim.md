# Completion claim

Write the completion claim for this package: what is true now, each part with its evidence, and what was not verified. This file is what you report to the user. Claim nothing beyond it.

## The rules
A completion claim is a statement of fact about the current state. Only evidence recorded in this package backs it: a run in `runs.jsonl`, a report in `evidence/`, an approval in `approvals.jsonl`, or an artifact the card's `inputs=` line names. Memory of a run, the shape of the diff, an edit that "obviously" works, or a sub-agent saying "done" is not evidence.

For each statement, in this order:
1. Identify the run or file whose content proves it. If none exists, you hold a hope, not a claim.
2. Check it is fresh. A run from before your last edit describes a state that no longer exists: record a new one.
3. Read all of it: the exit code, the summary line, the failed and skipped counts, every error.
4. Match it to your words. Exit 0 with "0 passed, 12 skipped" is not "tests pass". A green build is not "the feature works".
5. Then state the claim with its evidence beside it: the command or file and the line you read.

## What each claim needs
| Claim | Needs | Not enough |
|---|---|---|
| The bug is fixed | the failing run that reproduced it, then a GREEN run of that test after the fix | the edit applied; the code looks right |
| Tests pass | a GREEN run for the scope after the last edit: N passed, 0 failed, 0 skipped | an older run; a single test |
| The feature works | the feature path exercised and its result observed | a green build or a type check |
| Lint or types are clean | the tool run to completion, 0 errors | "I introduced nothing that fails" |
| A reviewer or sub-agent finished | its report or output in the package | its summary saying "done" |
| Reviewed for security | the security report's verdict line and the surfaces it traced | "security was considered" |
| Audited | the audit report's `## Overall Status` and `## Final Decision` | the audit having run |
| Approved | the approval record with the user's quote | "the user agreed" |
| Done, ready to commit | every row above that applies, and the diff reviewed | every file saved |

- A vague word in place of evidence ("works", "fine", "all set", "should", "probably", "looks right") is not a claim. Replace it with the evidence or drop it.
- A pass count that hides skips is not a clean run. Quote the skipped count.
- A review, a design, a spec or a plan with no code change claims only what its artifact says ("3 must-fix findings", "spec approved at fingerprint X"), never that the code is correct or safe.

To record a fresh run (take `<python>`, `<root>` and `<slug>` from the card's `then=` command):
`"<python>" -B "<root>/scripts/sdlc.py" run --slug <slug> --expect pass --label green -- <test command>`
The test command is an argument list for an allowlisted test runner: no shell, no pipes, no `;`. A lint or type tool runs the same way with `--label check`.

## Not verified and flags
Read `state.json`, the reports and the sidecars.
Under `## Not verified`, list every part of the work nothing checked: a step the runner skipped (with its `skip_reason`), a check whose tool was absent, any statement no run or report covers.
Under `## Flags`, list every item that holds:
- a role that ran inline (`degraded` in `state.json`, a report that says it ran inline or degraded, `critic: degraded` in an approval or sidecar): it was not independent;
- `red.order` other than `ok`, or `gate_order` set;
- tasks in `appended_tasks`: added to the plan after its approval;
- residual critic notes in the sidecars;
- open security findings, open must-fix quality findings, an audit `block-final`.

## Author's calls
The card's data part lists each decision nobody confirmed as one `author_call=` line: a decision of `design.md` marked `(author's call: ...)`, or a question of the spec check you settled yourself (`minor`, or `theirs` with no user to ask). Under `## Author's calls`, list every one of them, each with its id, where it came from and what was decided, and tell the user each one. Leave none out because it seems small, and never present one as the user's choice. With no `author_call=` line, write `- none`.

## Status
- `Status: done`: every statement has its evidence, nothing open contradicts it, and an audit, when there is one, says `allow-final`.
- `Status: done, partly verified`: the work is done, and `## Not verified` names the parts nothing checked.
- `Status: not done`: a required piece is missing or failing. Name it. Never soften it into done.

## The report: `<package>/evidence/<work_id>.claim.md`
The work id is in the card's `outputs=` path. Write:

    # Completion claim

    Status: done

    ## Claims
    | Claim | Evidence |
    |---|---|
    | Tests pass | run_seq 7, `pytest tests/auth`, exit 0: "14 passed, 0 failed, 0 skipped" |

    ## Not verified
    - none

    ## Flags
    - none

    ## Author's calls
    - D2 (design.md): rows are streamed, not built in memory

- `# Completion claim` is the first line, exactly.
- Show commands and output lines verbatim. Mask any secret value as `***MASKED***`.
- Keep the headings in English; tell the user the claim in their language.

## Finish
Write the report, then run the card's `then=` command.
