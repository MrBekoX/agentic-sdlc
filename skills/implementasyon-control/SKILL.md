---
name: implementasyon-control
description: Use first for a pre-final audit in any language that the implementation followed the required flow across spec, plan, TDD, tests run, security pass, scoped diff, and final evidence. Treat requests to audit the spec-plan-TDD-security flow before the final response as active audit tasks, not passive session preferences. Invoke this skill as the first action, before running git diff/status/log or reading files and even when evidence is missing, because its auditor inspects the diff itself; then report missing evidence and do not gather the diff or ask what to do first. Not for starting new implementation.
---

# Skill: implementasyon-control

> **Argument:** `/implementasyon-control $ARGUMENTS`. Match the user's language; keep the report headings in English. This skill **audits**, it does not implement.

Runs before the final response of any implementation flow to confirm the work was done properly — not just that code exists. For a thorough audit it delegates to the **`implementation-auditor`** agent or runtime equivalent (fresh context, sees the diff and the resolved work package, not the reasoning that produced them).

## Invariant
The audit reports what the evidence shows — a step is "done" only when its artifact/output exists, and missing steps are named, not glossed.

## Tripwires
- marking a step done from memory, not from an artifact
- "looks complete" without inspecting the diff
- skipping the report because "the flow was obviously followed"

## Proof
Per step, the artifact/output that proves it: spec path, plan path, RED→GREEN, security pass, reviewed diff. Gaps listed explicitly.

## Excuse → check
| Excuse | Check |
|---|---|
| "The flow was clearly followed." | Then point to each artifact. If you can't, it wasn't. |
| "No time to audit." | An unaudited "done" is exactly the failure this skill exists to catch. |

## What it checks
- Was a **spec** produced? A **plan**? Was the plan broken into tasks?
- Did `resolve_work_package.py` resolve exactly one spec/plan pair?
- Is every task complete?
- Did code change **only within scope**?
- Were tests written? Run? **Was real output seen?**
- Was a **security analysis** performed?
- If refactored, were tests re-run afterward?
- Any unnecessary file changes? Was the architecture broken?
- Any secret or sensitive data added?
- Was the `git diff` reviewed?
- Are the acceptance criteria met? Edge cases checked?
- Any missing step?

## Procedure
1. Resolve the work package before reading the spec/plan. If the user supplied `plan:` or `spec:` paths, pass them explicitly: `python "<runtime-root>/scripts/resolve_work_package.py" --plan <path>` or `--spec <path>`. Otherwise run `python "<runtime-root>/scripts/resolve_work_package.py"` and let it match current branch, then changed canonical plans.
2. If resolution fails or returns multiple candidates, do **not** guess. Emit PARTIAL/FAIL with `spec/plan artifact ambiguous or missing`, list the candidates/error lines, and block the final answer until the intended plan path is supplied or the artifacts are fixed.
3. Gather evidence from the resolved spec, resolved plan, the `git diff`, the test output, and the security-analysis notes.
4. **Delegate to the `implementation-auditor` agent** or runtime fresh-context equivalent for an independent pass (mandatory — self-attestation by the implementer is not an audit; F6). If the runtime supports a fresh-context specialist, use it. If it does not, record `Delegation Degraded: fresh-context specialist unavailable`, perform the pass in the main loop, and mark the result non-independent.
5. Map evidence to the checklist below; mark each step PASS / PARTIAL / FAIL with the evidence (or its absence).
6. Emit the **Implementation Control Report**.
7. If any **critical** step is missing → do not allow the final answer; complete the step (or escalate to the user), then re-run this skill (**Loop C** in root-cause-fix).

## Output — Implementation Control Report
```md
# Implementation Control Report

## Overall Status
PASS / PARTIAL / FAIL

## Checked Flow
- [ ] Work Package Resolution
- [ ] Context Analysis
- [ ] Spec
- [ ] Plan
- [ ] Runtime goal tool or manual Goal Lock artifact
- [ ] TDD / Regression Test
- [ ] Implementation
- [ ] Test Run
- [ ] Security Analysis
- [ ] Refactor
- [ ] Retest
- [ ] Runtime loop tool or manual Loop Iteration artifact
- [ ] Final Review
- [ ] Git Diff Review

## Work Package
- Resolution: PASS / PARTIAL / FAIL
- Work ID:
- Spec:
- Plan:
- Resolution source:
- Status:

## Missing Steps

## Risky Changes

## Required Fixes Before Final

## Final Decision
```

## Limits
- Audits only; performs no code changes.
- Evidence-based: a step without real evidence (e.g. test output) is **not** PASS.
- Work-package selection never uses newest timestamp or a guessed filename. Use explicit path, unique branch match, or unique changed canonical plan only.
- A FAIL or critical-PARTIAL blocks the final answer until resolved.
