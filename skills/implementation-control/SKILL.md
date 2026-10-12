---
name: implementation-control
description: This skill should be used first for a pre-final audit in any language that the implementation followed the required flow across spec, plan, TDD, tests run, security pass, scoped diff, and final evidence. Requests to audit the spec-plan-TDD-security flow before the final response are active audit tasks, not passive session preferences. It applies as the first action, before running git diff/status/log or reading files and even when evidence is missing, because its auditor inspects the diff itself; missing evidence is an audit outcome, not a reason to defer activation. Not for starting new implementation.
---

# Skill: implementation-control

> **Argument:** `/implementation-control $ARGUMENTS`. Match the user's language; keep the report headings in English. This skill **audits**, it does not implement.

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

## Depth contract (proportional — scale rigor to the change)
A step earns **PASS only with its own artifact quoted in the report**: Spec → the spec path plus one acceptance criterion read from it; Plan → the plan path plus the task it maps to; TDD → the RED→GREEN line (the failing assertion, then the passing one); Test Run → the runner's summary line (N passed, 0 failed, 0 skipped); Security Analysis → the note and the input→sink it cleared or the reason none reaches a sink; Git Diff Review → the file/line range you actually read. **PARTIAL/FAIL names the exact artifact that is absent** ("no security note for the new request handler"), never a vague shortfall. "Looks complete" is not a status — the only statuses are PASS / PARTIAL / FAIL, each tied to evidence or its named absence. Proportional: a one-line fix has fewer steps to evidence, but every step you mark PASS still cites the one artifact that backs it.

## Excuse -> check
| Excuse | Check |
|---|---|
| "The spec was obviously produced." | Quote its path and one acceptance criterion read from it. If you can't, it's FAIL, not PASS. |
| "Tests obviously ran." | Quote the summary line (N passed, 0 failed, 0 skipped) from the actual output. A remembered run is not evidence. |
| "The diff is in scope, I can tell." | Then name the file/line range you read and what put it in scope. An unread diff is not a reviewed diff. |
| "Security wasn't relevant here." | Then name the input that does NOT reach a sink and why. A blank Security step is PARTIAL, not PASS. |

## No placeholders
Do not mark any step PASS without quoting the artifact that backs it. Do not emit a report whose "Missing Steps" is empty while an artifact is in fact absent — an absent artifact is a missing step. Do not substitute "flow followed" for per-step evidence: the audit grades artifacts, not the implementer's narrative.

## Shallow example (reject this)
A report that marks every step PASS with the same justification ("flow was followed") and not one quoted spec path, RED→GREEN line, or test-summary line is a rubber-stamp, not an audit. Reject it and re-run with the artifacts in hand.

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

**Plugin root (`<runtime-root>`):** the installed agentic-sdlc folder, two levels above this `SKILL.md` (`<runtime-root>/skills/<name>/SKILL.md`) — never the user's working directory. Claude Code substitutes `${CLAUDE_PLUGIN_ROOT}`; Claude Code and ZCode substitute `${CLAUDE_SKILL_DIR}/../..`; Kimi Code substitutes `${KIMI_SKILL_DIR}/../..`; a SessionStart line `Plugin root (resolved by this hook…)` names it on Claude Code, Codex and ZCode; Codex and Grok CLI show this skill's absolute path in the skill listing. A `${…}` token still shown literally is unresolved: never pass it to a shell. Confirm `<runtime-root>/scripts/validate_artifacts.py` exists and write that absolute path, quoted for your shell, into commands; if it cannot be confirmed, stop the step and report `plugin root unresolved` — never run a same-named file from the user's project. Run helpers with `python3` (Python 3.8+), or `py -3` on Windows when `python3` is missing or is the Microsoft Store alias.

## Procedure
1. Resolve the work package before reading the spec/plan. If the user supplied `plan:` or `spec:` paths, pass them explicitly: `python3 "<runtime-root>/scripts/resolve_work_package.py" --plan <path>` or `--spec <path>`. Otherwise run `python3 "<runtime-root>/scripts/resolve_work_package.py"` and let it match current branch, then changed canonical plans.
2. If resolution fails or returns multiple candidates, do **not** guess. Emit PARTIAL/FAIL with `spec/plan artifact ambiguous or missing`, list the candidates/error lines, and block the final answer until the intended plan path is supplied or the artifacts are fixed.
3. Gather evidence from the resolved spec, resolved plan, the `git diff`, test output with exit status, and security-analysis notes. Supply the auditor with branch/HEAD receipts before the first write (when the enclosing flow requires a work branch), dependency-install attempts and their authorization, and the required security dispatch/reviewer completion results or the applicable documented fallback. A Skill load or self-authored PASS note is not completed independent review.
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

## Evidence persistence
For **per-package** work the Final Implementation Report is persisted to `docs/agentic-sdlc/<slug>/evidence/<work_id>.md` — per-package only (flat packages get none), using the slug `resolve_work_package.py` reports; a re-run **overwrites** it in place (single canonical file, last run wins). This persisting write is done by the **main control/finalize step** this skill runs in (the main pipeline finalize step), not the read-only `implementation-auditor` sub-agent it dispatches — the auditor only consumes the report and resolver output as input. Evidence has **no validator** and never gates resolution (AC12).

## Limits
- Audits only; performs no code changes.
- Evidence-based: a step without real evidence (e.g. test output) is **not** PASS.
- Work-package selection never uses newest timestamp or a guessed filename. Use explicit path, unique branch match, or unique changed canonical plan only.
- A FAIL or critical-PARTIAL blocks the final answer until resolved.
