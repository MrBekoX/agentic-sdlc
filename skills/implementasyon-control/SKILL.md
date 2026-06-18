---
name: implementasyon-control
description: Use first for a pre-final audit that the implementation followed the required flow: spec, plan, TDD, tests run, security pass, scoped diff, and final evidence, including prompts asking to denetle/audit the spec-plan-TDD-security flow before the final response. Treat "Final cevaptan once ... denetle" as an active audit task, not a passive session preference; if evidence is missing, invoke this skill and report missing evidence instead of asking what task to do. Not for starting new implementation.
argument-hint: "<what was implemented — optional>"
---

# Skill: implementasyon-control

> **Argument:** `/implementasyon-control $ARGUMENTS`. Match the user's language; keep the report headings in English. This skill **audits**, it does not implement.

Runs before the final response of any implementation flow to confirm the work was done properly — not just that code exists. For a thorough audit it delegates to the **`implementation-auditor`** agent or runtime equivalent (fresh context, sees the diff and the spec/plan, not the reasoning that produced them).

## What it checks
- Was a **spec** produced? A **plan**? Was the plan broken into tasks?
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
1. Gather evidence: the spec, the plan, the `git diff`, the test output, the security-analysis notes.
2. **Delegate to the `implementation-auditor` agent** or runtime fresh-context equivalent for an independent pass (mandatory — self-attestation by the implementer is not an audit; F6). If the runtime supports a fresh-context specialist, use it. If it does not, record `Delegation Degraded: fresh-context specialist unavailable`, perform the pass in the main loop, and mark the result non-independent.
3. Map evidence to the checklist below; mark each step PASS / PARTIAL / FAIL with the evidence (or its absence).
4. Emit the **Implementation Control Report**.
5. If any **critical** step is missing → do not allow the final answer; complete the step (or escalate to the user), then re-run this skill (**Loop C** in root-cause-fix).

## Output — Implementation Control Report
```md
# Implementation Control Report

## Overall Status
PASS / PARTIAL / FAIL

## Checked Flow
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

## Missing Steps

## Risky Changes

## Required Fixes Before Final

## Final Decision
```

## Limits
- Audits only; performs no code changes.
- Evidence-based: a step without real evidence (e.g. test output) is **not** PASS.
- A FAIL or critical-PARTIAL blocks the final answer until resolved.
