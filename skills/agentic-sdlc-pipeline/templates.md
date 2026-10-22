# agentic-sdlc-pipeline — Templates (artifacts & reports)

Fill these as you pass the matching step. Keep them short and concrete; vague "should work" criteria are banned.

## Analysis Summary (step 3)
```md
## Analysis Summary
Problem:
Current behavior:
Expected behavior:
Affected files:
Affected modules:
Existing tests:
Risks:
Initial hypothesis:
```

## Spec (step 4 — the WHAT, code-independent) — save to `docs/agentic-sdlc/specs/<work_id>.md` with `status: reviewed`; set `approved` only per the Approval receipt
```md
# Spec: <name>
## Problem / Goal / Non-goals
## Current vs Expected Behavior
## Business Rules & Validation
## Acceptance Criteria   # each labelled and testable: "- AC1: given X → returns Y"
## Edge Cases            # empty/null, boundaries, authz, error paths
## Security Requirements
## Must-not-change behaviors (regression surface)
## Definition of Done
```
Do **not** leak the HOW (files/methods) into the spec.

## Plan (step 5 — the HOW) — save to `docs/agentic-sdlc/plans/<work_id>.md` with `status: reviewed`; set `approved` only per the Approval receipt
```md
# Implementation Plan
## Task N: <title>
Purpose · Files to inspect · Files likely to change · TDD point (which failing test first) · Validation · Risks
```
Every acceptance criterion maps to ≥1 task, and that task names its id (`AC1`); the plan validator checks coverage by id.

## Documentation Verification (step 6 — Context7)
```md
## Documentation Verification
Library / Version in project:
Source:                 # Context7 | WebSearch fallback (Context7 quota out / unavailable)
Verified topics:        # method names, params, async, deprecations, config/env names
Findings:
Impact on implementation:
```

## Risk & Scope Lock (step 7)
```md
# Risk & Scope Lock
In Scope / Out of Scope:
Files allowed to change / Files read-only:
Risk areas:             # migration, backward-compat, API contract, security, perf, test-break, mobile, deploy, secret-exposure
Rollback plan:
Verification plan:
```

## Goal Lock (built-in /goal — or manual)
```md
# Goal Lock
Main Goal · Non-Goals · Acceptance Criteria · Constraints · Risk Areas · Next Step
```

## Loop Iteration (scheduled `/loop`, or a manual fail-fix-retest)
```md
# Loop Iteration
Trigger · Failed Check · Root Cause · Fix Plan · Applied Fix · Verification · Continue or Exit
```

## Security Analysis (steps 11 & 14)
```md
## Security Analysis (#1 diff / #2 final)
Checked areas:          # input-validation, authN, authZ/IDOR, data-exposure, injection, secrets, logging, deps, DB/RLS, mobile
Findings:               # mask secrets as ***MASKED***, report file:line + risk type
Severity:               # Critical / High / Medium / Low
Required fixes / Accepted risks:
```

## Quality Gates (step 15)
```md
## Quality Gates
Lint / Typecheck / Build / Secret-scan: Passed | Failed
Details:
```

## Diff Review (step 16)
```md
## Diff Review
Changed files:
Expected changes / Unexpected changes:
Potential issues / Cleanups applied:
```

## PR / MR description (step 19)
```md
# Summary / Problem / Solution / Changes
# Tests / Security / Risk / Rollback Plan
# Screenshots / Logs
# Checklist
- [ ] Spec done  - [ ] Plan followed  - [ ] Failing test added  - [ ] Tests passing
- [ ] Security #1 + #2 done  - [ ] Lint/typecheck/build passing  - [ ] Secret scan done  - [ ] Diff reviewed
```

## Final Implementation Report (finalize)
```md
# Final Implementation Report
## Summary / Problem Solved
## Branch / Commit / Files Changed
## Tests Run (with result)
## Security Checks (#1 + #2)
## Lint / Typecheck / Build / Secret Scan
## Risk Assessment / Diff Review Summary
## PR/MR Notes
## Final Sync (main updated? / working tree)
## Follow-up Recommendations   # out-of-scope findings go here, never silently fixed
```

### Where the Final Implementation Report is persisted (per-package evidence)
For **per-package** work, the Final Implementation Report above — together with Security Analysis #1/#2, the Git Diff Review, and the test-run output — is persisted as the package's evidence artifact at the canonical path `docs/agentic-sdlc/<slug>/evidence/<work_id>.md` (the per-package canonical layout `docs/agentic-sdlc/<slug>/{spec,plan,evidence}/<work_id>.md`; the legacy flat layout `docs/agentic-sdlc/{specs,plans}/<id>.md` keeps no Finalize evidence). The `<slug>` is the one emitted by `resolve_work_package.py` (never re-derived). A re-run **overwrites** this single canonical file in place (last run wins; no timestamp suffix). Evidence is git-ignored and has **no validator**; it is **per-package only** (flat packages get no Finalize evidence). The write is performed by the **main pipeline finalize step**, not the read-only `implementation-auditor` sub-agent. Per-package plan change-detection is a filesystem scan, not a `git status` query (`docs/` is git-ignored).
