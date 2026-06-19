---
name: completion-claim-gate
description: Use first in any language as the evidence gate before saying work is done, fixed, passing, complete, ready, verified, or safe to claim. Invoke this skill as the first action and run the gate; listing or describing the evidence inline is not a substitute for invoking it. Use for the agent's own success claims and relayed subagent claims; skip future plans or third-party claims you are not endorsing.
---

# Skill: completion-claim-gate

> A completion claim is a factual assertion about the current state of the code. The only thing
> that backs a factual assertion is fresh output you just read — not memory of an earlier run, not
> the shape of the diff, not the fact that the change "obviously" works. This skill makes the
> claim wait until that evidence exists.

## Invariant
A completion claim is only as true as the fresh output you just read — not memory, not the shape of the diff.

## Why this exists

The expensive failures are confident wrong claims: "fixed" when the bug still reproduces, "tests
pass" when one was skipped, "done" when an edit never saved. Each costs a round-trip of trust and
usually a second bug on top of the first. The cause is almost never laziness — it is the gap
between *finishing the edit* and *finishing the work*. The edit feels like the end, so the claim
fires before anything confirms it. The fix is a small reflex: when you are about to assert
success, treat that impulse as the trigger to run the proof first.

This complements the lab's evidence contracts rather than restating them. Contract 00 ("show real
evidence before claiming success") and contract 05 (TDD: see RED, then GREEN, show the output) define
*what counts as evidence* for code and tests. `implementasyon-control` audits the *whole flow*
once, at the very end. This skill is the per-claim, same-turn micro-gate in front of every
individual "done/passing/works" — including mid-flow claims, claims about a subagent's report,
and the line right before a commit.

## When to use

The trigger is linguistic, not procedural: any time you are about to write a sentence asserting
the work reached a good state. Concretely —

- About to write done, fixed, passing, working, complete, ready, verified, "good to go", "all
  green", "no errors", "CI green", "works on my machine", "task finished", "LGTM".
- About to commit, push, open a PR, ship/deploy, or mark a task or checklist item complete.
- About to forward a subagent's "I finished / it passes" up to the user as fact.
- You reach for a hedge (*should*, *probably*, *seems*, *looks right*) or a satisfaction word
  (*Done!*, *Perfect!*) about finished work — both are tells that you want to claim before you
  checked.

**Where it does not fire** (share a keyword but are not your own success assertion):

- A hedge about an *approach*, not a result — "this should be cleaner". No finished-state claim.
- Future-tense plans — "I'll make the tests pass next". You are describing intent, not state.
- Quoting a spec or acceptance criterion — "the spec says tests should pass for X".
- Relaying a third party's claim without endorsing it — "the user says it's fixed" (neutral
  report). The moment you assert it *is* fixed, the gate is back on.

Also skip genuinely unverifiable statements ("I'll start by reading the config").

**Gate already satisfied this turn:** if the gate's Run/Read/Verify already happened *this turn*
and the shown summary line matches the claim's exact words, the gate is met — re-pasting that
output is not a second run, so just make the claim. This is not an escape hatch: stale output
(run before your latest edit) or output whose summary doesn't match the specific claim has *not*
satisfied the gate — that is exactly what step 4 catches.

## The gate — five steps, in order

Run these before you write the claim. The order matters: each step is worthless if the one before
it was skipped.

1. **Identify** — Name the single command (or observation) whose output would prove this exact
   claim. "Fixed" → the command that reproduced the bug. "Tests pass" → the test runner for the
   relevant scope. If you cannot name one, you do not have a claim yet — you have a hope.
2. **Run** — Execute it now, fresh, to completion. Not a remembered result from three edits ago;
   state may have changed since. Don't truncate it to "the part you care about".
3. **Read** — Read the whole result: exit code, the pass/fail summary line, the failure count, any
   error or warning. The summary line is where skips and partial runs hide.
4. **Verify** — Check the output actually says what your claim says. Exit 0 with "0 passed, 12
   skipped" is not "tests pass". A build that succeeded is not "the feature works". Match the
   evidence to the specific words you are about to use.
5. **Then claim** — Only now state it, and state it *with* the evidence (the command and the
   relevant output line), so the reader sees the proof, not just the verdict.

**Example — a completion claim**
Before (bare verdict): `Fixed the auth bug, tests pass, ready to merge.`
After (evidence-backed): ``Ran `pytest tests/auth` after the fix: 14 passed, 0 failed, 0 skipped (exit 0). The original repro (`pytest tests/auth/test_login.py::test_expired_token`) now passes. Ready to merge.``

**Example — relaying a subagent**
Before (relaying a claim): `The subagent finished the migration and says it works.`
After (relaying evidence): ``The subagent ran `alembic upgrade head` (exit 0) and `pytest tests/db` (31 passed, 0 failed); output attached. Migration applied and verified.``

## What each claim actually requires

A claim is only as strong as the thing you ran. Common mismatches — this table is the canonical
home for the per-claim evidence bar, including the subagent-relay rule:

| Claim | Requires | Not sufficient |
|---|---|---|
| "The bug is fixed" | The original repro run now shows correct behavior | The code looks right / the edit applied |
| "Tests pass" | Full run for the scope, summary read: N passed, **0 failed, 0 skipped** | A run from before the last edit; a single test |
| "The feature works" | Exercising the actual feature path and observing the result | A green build / type-check |
| "Lint/types are clean" | The linter/type-checker run to completion, 0 errors | "I didn't introduce anything that would fail" |
| "The subagent finished it" | You saw its evidence (its command output/diff), or you re-ran the check yourself | Its summary saying "done" |
| "Done / ready to commit" | The above for every claim in the change, plus `git diff` reviewed | Everything is saved |

## Regression-fix proof

A fix without a test that fails *because* of the bug proves nothing — the test might pass with or
without your change. To show the fix is real:

1. Write the test that captures the bug; run it and see it fail (RED) — that is what ties the test
   to the bug.
2. Apply the fix; run it and see it pass (GREEN).
3. For certainty the test guards the fix: revert the fix, confirm the test fails again, restore
   the fix, confirm it passes. Then the test is a genuine regression guard, not a passenger.

(This is contract 05's RED→GREEN applied to *proving a fix*; lean on that contract for the general TDD
loop.)

## Excuse → check

These excuses fire under time pressure (the ones the requirements table doesn't already cover).
Each is the moment to run the gate, not skip it.

| Excuse | Reality |
|---|---|
| "It's a trivial change, no need to run it." | Trivial changes break trivially — a typo, an unsaved file. The run is cheap; the wrong claim is not. |
| "I ran it earlier, it was fine." | You edited since. The earlier run describes a state that no longer exists. |
| "The build passed, so it works." | A build proves it compiles, not that it behaves. Different claim, different proof. |
| "I'll just say 'should work' to be safe." | A hedge in place of a check still leaves the reader to find the breakage. Run it and say what's true. |
| "Re-running takes too long." | Slower than running is shipping a false "done" and the round-trip to undo it. |

## Reply-language note

Match the user's language unless they request otherwise. Keep formal artifact headings (e.g.
"Implementation Control Report") in English. The evidence itself — commands and output — is shown
verbatim regardless of language.

## Checklist

- [ ] Identify: named the exact command/observation that proves the claim.
- [ ] Run: executed it fresh and complete after the latest edit.
- [ ] Read: exit code, summary line, and failure/skip count all read.
- [ ] Verify: output matches the specific words of the claim (no skipped/partial passing as full).
- [ ] Then claim: stated with the evidence attached, not as a bare verdict.
- [ ] No commit / push / PR / "ready" without a just-run verification in the same message.
