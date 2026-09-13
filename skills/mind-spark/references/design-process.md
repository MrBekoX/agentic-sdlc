# AGENTIC-SDLC design procedure

Read this file only after the process-owner check in [mind-spark](../SKILL.md) selects AGENTIC-SDLC. It is the house procedure, not routing context for a phase owned by another plugin. References below to the process-owner check mean the entrypoint's check.

> The cheapest bug to fix is the one in an assumption you never wrote down. Before a line is built,
> this turns a vague "build X" into an agreed intent and a design the user has actually said yes to.
> The gate: don't write code, scaffold, or invoke a build skill until you've **presented a design and
> the user has approved it** — a wrong assumption caught in a sentence costs a sentence; caught in code
> it costs the code, the rework, and the user's trust. It owns *intent + design only*. The moment the
> design is approved it hands off to the spec-driven flow and stops — it does not write the spec or plan.

## Depth contract (proportional — scale rigor to the change)
The design you present and get approved must carry real shape, scaled to the task but never a bare echo of the request. Name the actual units/components involved and how they talk to each other — not "a dashboard" but which piece reads what and renders where. Surface the notable error/edge paths the questions exposed (empty state, failure of the upstream call, the limit that bites), each as a concrete scenario, not a category. State a concrete "success looks like" signal the user can recognize — an observable behavior or output, never "it works". For each of the 2-3 approaches, state the one trade-off that actually distinguishes it from the others (what it buys, what it costs); three phrasings of the same idea is one approach, not three. A trivial change earns a two-sentence design — short and concrete, never short and hollow.

## Excuse -> check
| Excuse | Check |
|---|---|
| "It's too simple to design." | State the two-sentence design — purpose, shape, success signal — and still get the explicit yes. Simple is cheap to confirm, which is exactly why you confirm it. |
| "They said just build it." | An explicit build instruction names the *what*, not the *how* — confirm the design before any code. Sounding ready to build is the case this gate exists for, not an exception to it. |
| "The approaches all kind of work." | Then name the trade-off that separates them; if you can't, you have one approach reworded, and the choice is fake. |
| "Success is obvious — it just works." | Then state the observable signal that proves it: what the user sees, what the output is, what stops happening. "It works" is not a success criterion. |

## No placeholders
Do not present a design that only restates the request in new words. Do not offer approaches with no distinguishing trade-off, or a "success looks like" of "it works" / "it's done". Do not refine details of a request that is really several independent subsystems before you've decomposed it and picked the first sub-project. If the design names no units, no edges, and no concrete success signal, it is not a design — it is a restated prompt.

## Shallow example (reject this)
"I'll add a dashboard that shows the data — sound good?" presented as a design is a restatement: it names no units (what reads the data, what renders it), no edge paths (empty data, slow query, permission gap), and no concrete success signal (what does the user see when it's right?). It would get a reflexive yes and hide every assumption that matters. Reject it; present the shape and the success signal, then get the yes.

## Why this exists

Most wasted implementation work traces back to a design no one confirmed. The model reads "add a
dashboard", pictures one thing, builds it, and the user meant something else. Skipping this step feels
faster and is almost always slower, because rework costs more than a few questions.

Two failure modes it guards against. **Premature building:** jumping to code before intent is settled —
the approval gate is the cure. **Premature detail:** lavishing questions on one corner of a request
that is actually three independent systems — you refine the bikeshed while the architecture goes
unexamined; the cure is to decompose before you refine.

## When to use

Reach for this at the *start* of any creative change where the design isn't settled: a new feature,
component, endpoint, screen, job, or a "change how X behaves" request. It runs before the spec — it
produces the agreed intent the spec then makes testable. It composes with `agentic-sdlc-pipeline` rather than
competing: when agentic-sdlc-pipeline kicks off a production change, this runs first and feeds the approved intent
into agentic-sdlc-pipeline's Spec phase.

**The one decision test for a fix/refactor request:** does the request already carry a testable
definition of done — a spec, a ticket with acceptance criteria, or a bug whose correct behavior is
clearly described? **Yes** → this skill does not fire; route to `root-cause-fix` / `safe-refactor`, which own
already-specified work. **No** → the missing definition *is* the design question; stay here. This single
test resolves the boundary both ways: don't grab a clearly-specified fix, and don't wave an
underspecified one through as "just a fix".

**When to skip — only zero-design edits:**

- A typo, rename, comment, or formatting-only change.
- A single-line edit whose intent the user already stated explicitly *this turn*.
- A fix/refactor that passes the decision test above (testable definition of done already exists).

"Too simple to design" is **not** a skip — see the next section. The answer to simple is a two-sentence
design you still confirm, never silence.

For an AGENTIC-SDLC-owned design, use the house register and hand off to the runtime's spec-plan adapter / `agentic-sdlc-pipeline`. The process-owner check above preserves an explicit Superpowers choice and its own handoff.

## "This is too simple to need a design"

This thought is the most reliable signal that an assumption is about to go unchecked — simple-looking
tasks are exactly where unexamined assumptions hide, because nobody slows down for them. A todo widget,
a single config flag, a one-endpoint helper: each still has a purpose, a constraint, and a success
criterion the user holds in their head and you don't.

The answer isn't heavy process — scale the design to the task. For a truly small change the "design" is
two sentences — "I'll add X that does Y, surfaced as Z; that match what you want?" — but you still say
it and still wait for the yes. Cheap to do, and it catches the mismatch before it becomes code. This is
why the skip list above is zero-design edits only, not "simple-looking" ones.

An **explicit build instruction is a starting point, not design approval.** "Just add a login page",
"scaffold the API" tells you *what* the user wants built, not that they've agreed *how* — you still
state the two-sentence design and get the yes before you build. The user sounding ready to build is the
case this gate exists for, not an exception to it.

## The flow

Work these in order. Treat each as a checkpoint, not a form to rush.

### 1. Read the context first

Before any question, look at what already exists — relevant files, docs, recent commits, existing
patterns. Half of "clarifying" questions answer themselves once you've seen the codebase, and asking
about something already decided in the repo wastes the user's turn and signals you didn't look.

### 2. Check scope before you refine

If the request is several independent subsystems wearing one sentence ("a platform with chat, file
storage, billing, and analytics"), name that *first*. Don't polish the chat UI when the real first
decision is how the pieces split and in what order they're built.

When it's too big for one design, help decompose: what are the independent pieces, how do they relate,
what order makes sense? Then run mind-spark on only the *first* sub-project through the normal flow. Each
sub-project later gets its own intent → spec → plan → build cycle. Decomposing first is what keeps
every later step a manageable size.

### 3. Ask one question at a time

Once scope is right-sized, refine by asking **one question per message** — purpose, constraints,
success criteria, edge cases. One at a time because a wall of five questions gets a shallow answer to
each; a single focused question gets a real one, and each answer shapes the next.

Prefer multiple-choice — far easier to answer well than an open prompt, and it surfaces options the
user hadn't considered. Open-ended is fine when the space is genuinely open.

**Example — weak vs. strong question**
Weak (open, overwhelming): "How should auth work — what provider, what session model, what about roles,
password reset, MFA?"
Strong (one thing, multiple choice): "For sign-in, which fits best?
(a) email + password we manage, (b) OAuth via Google/GitHub, (c) magic-link email. I'd lean (b) if you
want minimal credential handling — does that match your plan?"

### 4. Propose 2-3 approaches with a recommendation

Before settling, lay out two or three real approaches with their trade-offs, lead with the one you
recommend, and say why. The recommendation matters: options without a steer push the decision back on
the user with no signal. Offering alternatives keeps you from quietly committing to the first idea that
came to mind.

**Example — weak vs. strong approach offer**
Weak (no options, no why): "I'll store sessions in Redis."
Strong (options, lead with recommendation, give the why):
"Three ways to hold sessions:
- **A) Signed JWT, no server store** — stateless, scales free; revocation is awkward.
- **B) Server session in Redis** *(I'd pick this)* — easy revoke + short TTLs, one extra dependency.
- **C) DB-backed sessions** — no new infra, but a read on every request.
I lean B: you mentioned needing instant logout, which A can't do cleanly. Sound right?"

### 5. Present the design in scaled sections, approve each

When you understand it, present the design broken into sections, each scaled to its complexity (a
sentence if straightforward, up to a couple hundred words if nuanced). Cover what's relevant:
architecture, components, data flow, error handling, how it'll be tested.

**Example — scaling sections:** a trivial part stays one line — "**Storage:** one `todos` table, columns
id/text/done." A nuanced part earns room — "**Sync:** offline edits queue locally and replay on
reconnect; conflicts resolve last-write-wins by server timestamp, except deletes always win because…".

Ask after each section whether it looks right before moving on, so a wrong assumption is caught at that
section instead of after the whole design is built on top of it. Be ready to go back.

Favor designs that break the system into small units with one clear purpose and well-defined interfaces
— each understandable and testable on its own. The test: can someone tell what a unit does without
reading its internals, and can you change those internals without breaking its consumers? If not, the
boundaries need work. (Focused units also make the later implementation easier to reason about and edit.)

In an existing codebase, follow the patterns already there. If code you must touch has real problems
that affect the work, fold targeted improvements into the design the way a careful developer would — but
don't bolt on unrelated refactoring; stay on the current goal.

### 6. Hand off to the spec-driven flow

The terminal step is the handoff, not the build. Once the design is approved, pass the agreed intent
into the spec-driven flow and stop here — do not start implementing and do not invoke a build skill
(frontend, API scaffolding, etc.) yourself.

- Inside **`agentic-sdlc-pipeline`**: the approved intent feeds its Spec phase directly — return control.
- Standalone: use **`spec-plan-draft`** only when the runtime exposes the named Claude Code Workflow. In Codex or a degraded runtime, run the author (`spec-plan-author`) -> critic (`spec-plan-critic`) -> revise adapter; the critic pass is mandatory and must run in a fresh context wherever the runtime exposes one, with a same-context inline critic flagged `Delegation Degraded: fresh-context critic unavailable`. State the adapter path used. Record the spec when the work is substantial.

This skill produces intent + an approved design. The spec (the testable WHAT) and the plan (the HOW)
are owned downstream — don't duplicate them here.

## Output shape

By the end of a mind-spark pass the user should have seen, and approved:

```markdown
## Design — [topic]
**Goal:** one sentence on what this is for.
**Approach:** the chosen option (of the 2-3) and the one-line why.
**Shape:** the main units / components and how they talk to each other.
**Edges:** the notable error paths, limits, and edge cases surfaced in questions.
**Success looks like:** the concrete signal the user agreed this is done.
```

Keep it as short as the task allows — this is the agreed intent, not the spec.

## Red flags — stop and re-check

- Writing code, scaffolding, or invoking a build skill **before** the design was approved.
- Treating an explicit build instruction ("just build it") as design approval — it isn't; still confirm.
- Deciding something is "too simple" to confirm — that's the trap, not an exception.
- Routing an underspecified bug fix to root-cause-fix as "already specified" when "fixed" isn't defined yet.
- Re-opening design on a fix that already carries acceptance criteria — that's root-cause-fix's, not yours.
- Refining details of a request that is really several subsystems — decompose first.
- Firing multiple questions in one message, or open-ended ones where a multiple-choice would do.
- Presenting one approach with no alternatives and no recommendation.
- Continuing to a build skill after approval instead of handing off to the spec flow.
- Re-writing the spec or plan here instead of passing intent downstream.

## Checklist

- [ ] Existing context (files, docs, commits, patterns) read before questioning.
- [ ] Fix/refactor decision test applied — already-specified work routed to root-cause-fix/safe-refactor, not grabbed.
- [ ] Scope checked; oversized requests decomposed, first sub-project chosen.
- [ ] Questions asked one at a time, multiple-choice preferred.
- [ ] 2-3 approaches offered with trade-offs and a recommendation.
- [ ] Design presented in scaled sections, approved section by section.
- [ ] No code / scaffold / build skill before the design was approved (explicit build instruction is not approval).
- [ ] Handed off to the spec-driven flow (agentic-sdlc-pipeline Spec phase / runtime spec-plan adapter); spec & plan left downstream.
