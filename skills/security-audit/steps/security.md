# Security review

Review the changed source for vulnerabilities and write one report. The reviewers only read. Never print a real secret.

## Scope
- The change: `git diff --no-ext-diff --no-textconv <base_commit>` plus the untracked files from `git status --porcelain=v1 --untracked-files=all`. `base_commit` is in `<package>/state.json`. When `<package>/request.md` names files or a folder to review instead, review those.
- What the change may touch: `## Scope Lock` in `<package>/context.md`, and the spec's security requirements when the package has a spec.
- A source change after this review re-opens this step. On that visit, review the whole current diff again, with extra care on the files changed since the last report.

## How the role runs
Read `mechanism=` on the card. Take `<python>`, `<root>` and `<slug>` from its `then=` command.
- `subagent` or `workflow`: run the `security-reviewer` role in fresh context. Its role file is `<root>/agents/security-reviewer.md` (without that folder, the file of that name under `<root>/skills/`). Give each reviewer the role file, its lens, the scope and the paths above, never your own reasoning about the change.
- `inline-degraded`: play the role yourself. Read the role file, then only the diff, the files it names and the criteria. Mark the report degraded (see the Reviewer line below).
- A launch that fails or is refused: record it, then run the role inline. `<capability>` is the one that failed (`subagent` or `workflow`); `<reason>` is `missing`, `denied` or `unavailable`:
  `"<python>" -B "<root>/scripts/sdlc.py" note --slug <slug> --degraded <capability> --reason <reason>`

## Lenses
For a diff that spans several surfaces, run one reviewer per lens at the same time. One reviewer may take all four lenses on a small diff.
- `injection`: input validation, output encoding (XSS), SQL, NoSQL, command and template injection, path traversal, unsafe upload or download.
- `authz-IDOR`: endpoint protection; object-level access (a user reaches only their own data, the route id matches the token subject); tenant or owner filters on new queries; over-exposed fields or PII; permission boundaries; row-level security.
- `secrets`: no hardcoded secret (load it from the environment or a secret store); no secret or PII in logs; error responses that leak no internals.
- `auth`: token and session validity, lifetime and signing source; rate limiting on auth-sensitive endpoints.
A new dependency, a destructive migration or a new environment variable missing from `.env.example` goes to whichever lens sees the file. You merge the results: drop duplicates across lenses and rank by severity.

## What counts
- A finding has a `file:line`, the untrusted input traced from its entry point through each transformation to the sink (both ends named), and one impact sentence: what the attacker gets. Without the trace it is a guess, not a finding.
- Trace the failure and bypass paths too: the empty token, the unexpected type, the request that skips the guard.
- "Validated upstream": name where, and show the validated value is the one that reaches the sink. "No user input here": name every parameter and where it comes from. "Internal only": it still ships.
- A clean result names each surface traced and, per untrusted input, why it cannot reach a sink (parameterized, encoded, allow-listed, never concatenated). "No issues" with nothing named is not a review.
- An unfinished lens or an unverified finding is not clean: list it under `## Not reviewed`.
- Mask secrets: keep the key name, write the value as `***MASKED***`.

## The report: `<package>/evidence/<work_id>.security.md`
The work id is in the card's `outputs=` path. Write:

    # Security review

    Reviewer: fresh sub-agents (injection, authz-IDOR, secrets, auth)
    Scope: <base commit> to the working tree; <the files reviewed>
    Verdict: pass

    | Severity | Category | File:Line | Risk | Recommendation |
    |---|---|---|---|---|
    | None | — | — | — | No finding |

    ## Surfaces traced
    - <entry point> -> <sink> at <file:line>: <why it is safe, or the finding>

    ## Not reviewed
    - none

- `# Security review` is the first line, exactly.
- Severity is Critical, High, Medium or Low. With no finding, keep the single `None` row.
- Write exactly one verdict line: `Verdict: pass` only when no finding is open and every lens finished; otherwise `Verdict: fail`.
- For an inline run the line reads `Reviewer: inline (degraded: <the card's degraded= value>), not independent`.

## When the verdict is fail
Read the card's `done_when=`.
- It asks for `Verdict: pass`: write the failing report and run `then=`; the runner records the failed review and prints this step again. Then fix each finding in the source with the smallest change inside the scope lock. Record a GREEN run:
  `"<python>" -B "<root>/scripts/sdlc.py" run --slug <slug> --expect pass --label green -- <test command>`
  The test command is an argument list for an allowlisted test runner: no shell, no pipes, no `;`. Run the review again on the current diff, as the card's mechanism says, and rewrite the report. The runner counts each re-review as a fix round and halts at its cap with the findings open.
- A fix that needs the user's decision: tell the user what is open and wait for the answer before you change code.
- It asks for no verdict: this is a review only. Change no code; the findings and their recommendations are the output.

## Finish
Write the report, then run the card's `then=` command.
