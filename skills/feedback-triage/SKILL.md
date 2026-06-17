---
name: feedback-triage
description: This skill should be used first before answering or asking for PR details when review feedback has been received on the user's own change and must be verified, answered, judged, or implemented. Covers CodeRabbit comments, reviewer comments, PR/MR feedback, bot/linter/CI review output, "make this more robust" suggestions, and questionable feedback; not for writing a fresh code-quality-review of someone else's change.
---

# Skill: feedback-triage

> Review feedback is input to evaluate, not a command to obey. A reviewer (human or bot)
> sees a slice of the change and the codebase; you can see the whole thing. The job is to
> close the gap between their suggestion and what the code actually needs — with technical
> reasoning, not agreement theater. This is the receiving counterpart to `code-quality-review`
> (the giving side); it owns *how you take* feedback, not how you write it.

## Why this exists

The cheap failure mode is fast agreement: "You're absolutely right, great catch, let me
implement that now" — followed by editing code you never re-read to satisfy a suggestion you
never verified. It feels collaborative and produces regressions, dead abstractions, and YAGNI
bloat. The reviewer was sometimes wrong, sometimes right about a different file, sometimes
right that a problem exists but wrong about the fix. Agreeing on sight skips the one step that
catches all of these: checking the claim against the real code before touching it.

The fix is a short loop borrowed from how you'd treat any unverified claim — restate it,
verify it, judge it, then act — applied one item at a time so each change is tested in
isolation. Reasoned pushback is a valid, frequent outcome; a review you fully agreed with on
sight probably wasn't read carefully.

## The loop — one pass per feedback item

Run these in order. The order is the point: every step exists to stop you from editing on an
unverified claim. The last two steps assume the user actually wants the change applied — if
the ask is only "is this feedback right?", stop after EVALUATE and report the verdict with its
reasoning (see "Evaluate-only" below).

1. **READ** — Take in the *entire* feedback before reacting. Don't start composing a reply or
   an edit while still reading; partial reading is how you "fix" item 1 in a way item 4
   forbids. Group the comments into distinct items.
2. **UNDERSTAND** — Restate each item in your own words. If you can't, you don't understand it
   yet — ask a specific question rather than guessing. "Make this more robust" is not
   actionable until you've pinned down *robust against what*. (When there's no one to ask — a
   bot, CI, an absent reviewer — see "When you can't ask" below.)
3. **VERIFY** — Check the claim against the actual codebase. Open the file, read the function,
   grep for the real usage. Reviewers misremember signatures, miss a guard three lines up, or
   comment on a pattern the codebase already handles elsewhere. The claim must survive contact
   with the code.
4. **EVALUATE** — Decide if it's technically sound *for this codebase* — not in the abstract,
   and not only on its own merits. Two gates:
   - **Conventions:** weigh it against existing conventions (the same ones `code-quality-review`
     checks: simplicity, duplication, overengineering, architecture consistency). A suggestion
     idiomatic in another stack, or right for a library but wrong for this app, fails here.
   - **Spec/scope:** a suggestion can be correct yet land outside the agreed spec or
     contradict a must-not-change behavior (contracts 02/03 scope-lock). Sound-but-out-of-scope
     feedback becomes a new-task / raise-with-author item, not a silent diff expansion. The
     same applies when two accepted items conflict — surface the conflict rather than guessing.
5. **RESPOND** — Acknowledge technically, or push back with a reason. State *what* you plan to
   change and *why*, or why you won't — phrased as intent, since IMPLEMENT may revise it if the
   test disagrees. No praise, no thanks — the fix is the thanks. (See the response patterns
   below.)
6. **IMPLEMENT** — One item at a time, testing each before the next. Batching edits hides
   which suggestion broke what. For behavior changes this is ordinary TDD territory — defer to
   `test-authoring` / `root-cause-fix`. If a test contradicts what you said in RESPOND, say so and adjust.

## Evaluate-only — when the ask is "is this right?"

Sometimes the user wants a judgment, not an implementation: "is this review feedback sound?",
"is the reviewer right here?". Run READ → EVALUATE, then stop and report the verdict and the
reasoning. Don't roll into RESPOND-as-commitment or IMPLEMENT — applying an edit the user
didn't request is scope creep (contract 04). If the verdict is "sound and worth doing", say so and
let them decide whether to apply it.

## When you can't ask

UNDERSTAND tells you to ask when a suggestion is ambiguous — but a bot, a CI linter, or an
offline reviewer can't answer. Don't let that become "can't ask, so I'll guess and implement".
If the code itself makes the intent unambiguous after VERIFY, resolve it from the code. If it
stays ambiguous, it doesn't get implemented on a guess — leave it and flag the ambiguity to the
human author, the same way a real conflict surfaces rather than gets papered over.

## Response register

Acknowledgment is technical and specific, not affective. The reviewer needs to know you
understood and what you'll do — not that you're grateful or impressed. Acknowledgments state
*planned* change (contingent on the test in IMPLEMENT), so you never commit to a fix you
haven't confirmed.

**Example — accepting a valid point**
- Avoid: "You're absolutely right, great catch! Let me fix that right away."
- Use: "Confirmed — `parseConfig` returns `null` on an empty file and the caller derefs it
  unguarded (config.ts:42). Will add the null check and an empty-file test to confirm."

**Example — right problem, wrong fix**
- The reviewer correctly spots a real issue but proposes a remedy that's unsound here. Separate
  the diagnosis from the prescription: confirm the issue, justify a different fix.
- Avoid: implementing their proposed fix because the diagnosis was correct.
- Use: "Confirmed the unguarded null deref (config.ts:42). Fixing it at the parse boundary
  (return an empty config object) rather than guarding each caller, so all three call sites
  are covered without repeating the check."

**Example — feedback that's wrong for this codebase**
- Avoid: "Good point, I'll make it more flexible." *(then adds an unused options object)*
- Use: "Checked — this helper has one caller (grep shows only `importUsers`), so a generic
  options bag would be speculative. Leaving it concrete; happy to revisit if a second caller
  appears."

**Example — unclear feedback**
- Avoid: silently guessing what "handle this better" meant and refactoring.
- Use: "To make sure I address the right thing — do you mean the error path (currently
  swallowed) or the retry count? They need different fixes."

## YAGNI gate for "make it professional"

Vague quality suggestions — "make it robust", "more flexible", "production-grade", "handle
all cases", "add proper error handling everywhere" — are the highest-risk class, because
agreeing feels responsible while the result is overengineering the codebase didn't ask for.
Before implementing one, find the *concrete present need*: grep for the actual callers, the
real inputs, the failure that's actually reachable. No reachable failure, no second caller,
no real requirement → say so and skip it. This is contract 04 (code quality) and the
overengineering lens of `code-quality-review` applied to *incoming* suggestions.

**Example**
- Suggestion: "This function should validate all its inputs for production."
- Before: add type checks, range checks, null guards on every parameter.
- After: "Both callers (grep: `loadPage`, `prefetch`) pass a validated `PageId` from the
  router, so the inputs can't be arbitrary here. Adding guards would duplicate validation
  that already happens upstream. Skipping unless there's an untrusted entry point I missed."

## External reviewers are advisory

Feedback from a bot, an automated linter, or a CI review (CodeRabbit, Copilot, Sonar, lint
output) is a *suggestion to evaluate*, not an order. The same loop applies — verify and judge
before acting. Tools flag patterns, not context; they don't know this codebase's constraints.
A bot's "consider using X" gets the VERIFY/EVALUATE treatment like any other claim, and
"won't fix, because…" is a legitimate resolution. (When such a suggestion stays ambiguous and
there's no one to ask, apply "When you can't ask" above.)

**Example — bot suggestion**
- Avoid: silently applying CodeRabbit's "consider extracting this duplicated block".
- Use: "CodeRabbit flagged the two blocks as duplication, but they diverge in the error
  branch (grep: only here and retry.ts). Extracting would couple unrelated paths under one
  helper — won't fix; leaving them separate."

## Rationalization table

The pull toward fast agreement shows up as these excuses. Each is a trap; the reality column
is why.

| Excuse | Reality |
|---|---|
| "The reviewer is senior / it's a bot with rules — just do it." | Authority isn't verification. Seniors misremember the file; bots miss context. VERIFY still applies. |
| "Agreeing keeps things friendly and fast." | Agreeing before verifying ships regressions. The technical answer is the friendly one. |
| "The diagnosis is right, so their fix is right." | A correct problem can have a wrong remedy. Confirm the issue, then choose the fix the codebase needs. |
| "It's a small change, I'll skip the test." | Small unverified changes are exactly where silent regressions live. One item, one test. |
| "'Make it robust' sounds responsible, I'll add guards." | Without a reachable failure that's YAGNI bloat. Find the concrete need first or skip it. |
| "It's a good idea, so I'll just add it." | Good-in-isolation can still be out of scope or contradict the spec. Out-of-scope becomes a new task, not a silent diff. |
| "I'll apply all the comments in one pass, faster." | Batching hides which suggestion broke what. Isolate so each is testable. |
| "Pushing back looks defensive." | Reasoned pushback grounded in the code is the job. Reflexive agreement is the failure. |
| "It's a bot, I can't ask it, so I'll guess what it meant." | Can't-ask plus ambiguous isn't a license to guess. Resolve from the code or flag it to the author. |
| "I'll say 'you're right' now and figure out the fix after." | Agreement before verification commits you to a claim you haven't checked. Verify, then respond. |

## Red flags — stop and re-check

- About to type "you're absolutely right" / "great catch" / "let me implement that now"
  before opening the file.
- Editing code to satisfy a comment you haven't re-read in this session.
- Implementing a reviewer's proposed fix because their diagnosis was correct, without checking
  the fix itself.
- Implementing a "make it more X" suggestion without having grepped for the real usage.
- Expanding the diff for a sound-but-out-of-scope suggestion instead of raising it as a new task.
- Treating a bot's or linter's output as mandatory rather than advisory.
- Guessing what an unaskable (bot/CI/absent) reviewer meant instead of resolving from the code
  or flagging the ambiguity.
- Editing when the user only asked whether the feedback was sound.
- Applying several comments in one batch with no test between them.
- Restating a suggestion and realizing you can't — yet proceeding to edit anyway instead of
  asking.

## Note on scale

This skill stays in the main loop: items are verified and tested one at a time, in isolation,
so they can't be fanned out to parallel workers (a later item's fix may depend on an earlier
one's outcome). If a review is genuinely huge, the unit of delegation is the *change*, not the
items — IMPLEMENT defers behavior work to `test-authoring` / `root-cause-fix`, which make their own
dispatch-strategy calls.

## Checklist

- [ ] Read the full feedback; split into distinct items before reacting.
- [ ] Restated each item; asked when one was unclear — or, when unaskable, resolved from code or flagged the ambiguity.
- [ ] Verified each claim against the actual code (file read / grep), not memory.
- [ ] Evaluated for *this* codebase's conventions **and** the agreed spec/scope.
- [ ] Separated diagnosis from prescription where the problem was real but the fix wasn't.
- [ ] Confirmed whether the user wanted the change applied; stopped at the verdict if they only asked "is this right?".
- [ ] Responded technically as planned intent — no praise or thanks.
- [ ] "Make it professional" suggestions passed a YAGNI/usage check before implementing.
- [ ] Implemented one item at a time, each tested before the next.
