---
name: skill-authoring
description: This skill should be used first in any language to create, edit, test, evaluate, optimize, or package a Claude Agent Skill or Codex skill. It applies as the first action even when the target skill is unstated, before reading files or asking which skill to improve. Covers SKILL.md, frontmatter/description tuning, trigger optimization, eval fixtures/harnesses, and .skill packaging.
---

# Skill: skill-authoring

> Authoring a skill is not writing prose — it is debugging a prompt that will run a million
> times. This skill makes that loop disciplined: prove a real failure exists, fix exactly that
> failure with the least text, then close the loopholes the model used to wriggle out. Heavy
> machinery (evals, the review viewer, packaging) is reused from `skill-creator`; this skill owns
> the *method*, not a parallel toolset.

## Depth contract (proportional — scale rigor to the change)
Every claim that the skill helps rides on a captured RED baseline and a GREEN re-run of the *same* task, then a held-out phrasing proving it generalizes — not on how the prose reads. Each kept line earns its place against a failure you actually watched happen; a section for a problem you never observed is dead weight, cut it. "It triggers / passes / works" is incomplete until it carries the run output, the transcript, or the diff that shows it. A heavier edit earns more measurement (more held-out phrasings, the transcript read in full); a one-line tweak still names the symptom it removes.

## Excuse -> check
| Excuse | Check |
|---|---|
| "It looks right, ship it." | Show the baseline failure it fixes — no RED, no evidence it helps. |
| "Passes my three prompts." | Run a held-out phrasing; three prompts is overfitting. |
| "It triggers now." | Paste the run output or transcript line that shows it firing — asserting it isn't measuring it. |

## No placeholders
A skill section for a problem you never observed is speculation, not a fix — drop it until a baseline demonstrates the failure. "Works" with no transcript or diff is an assertion wearing the costume of evidence. Wording tuned to the exact test prompts passes the test and fails the million real ones; tune to the symptom, then prove it on phrasing you didn't write to.

## Why this exists

A skill that was never measured against a baseline is a guess. The common failure mode is
writing a long, confident SKILL.md, watching it "look right," and shipping — only for it to
either never trigger or fail on the next phrasing. The cure is a test-first loop borrowed from
TDD: don't write the skill until you have seen the failure it is supposed to fix, and don't keep
a line unless it earns its place. Lean beats long because every line competes for the model's
attention; explaining the *why* beats barking MUSTs because the model generalizes from reasons,
not from caps.

## When to use

Use this when the deliverable is a skill itself: a new `SKILL.md`, a substantial edit to one,
new evals, a triggering/description fix, or packaging. Skip it for a one-line typo fix (just make
the edit) and for ordinary code/SDLC work (that is `agentic-sdlc-pipeline`/`root-cause-fix` territory). If you are
unsure whether a skill even has a real problem, that uncertainty *is* the RED step below.

## The loop: RED, GREEN, REFACTOR

This is the spine. Each phase has one job and a reason it comes in this order. Delegate the
subagent runs (see [Delegation to skill-creator](#delegation-to-skill-creator)) so intermediate
transcripts stay out of the main context.

### RED

The reason this phase comes first is that a skill which doesn't fix a demonstrated baseline
failure is dead weight — so you must *see* the failure before you are allowed to write a fix.
Run the target task on a fresh subagent **without** the skill (or with the old version, when
improving) and capture the concrete failures — wrong output shape, missed steps, the skill not
triggering at all. Record the exact symptoms; they become your acceptance check.

### GREEN

The reason to keep this minimal is that lean beats long: every extra line dilutes the model's
attention, and a bloated skill makes Claude slower and more likely to wander, not smarter.
Write the **minimal** skill (or the minimal edit) that turns those specific failures into
successes — nothing speculative, no sections for problems you didn't observe. Re-run the same task
with the skill and confirm the RED symptoms are gone.

### REFACTOR

The reason this step is non-optional is that you must generalize rather than overfit: a fix that
only satisfies your two or three test prompts is worthless across the million real ones.
Read the *transcript*, not just the final output, and close the loopholes — the rationalizations
and shortcuts the model used to technically comply while missing the intent. Tighten wording, cut
dead weight you added in GREEN, and re-run on a *held-out* phrasing to prove the fix generalizes.

After ~2 failed attempts on the same stubborn issue, stop patching and re-frame — a different
metaphor or structure usually beats a third narrow patch.

## Delegation to skill-creator

Reuse the installed toolkit for validation, benchmark aggregation, the viewer, and packaging.
Resolve it by required capabilities: the Codex system `skill-creator` may provide validation
without any eval or packaging tools. A matching name or an `official` source is not enough.
**Plugin root (`<runtime-root>`):** the installed agentic-sdlc folder, two levels above this `SKILL.md` (`<runtime-root>/skills/<name>/SKILL.md`) — never the user's working directory. Claude Code substitutes `${CLAUDE_PLUGIN_ROOT}`; Claude Code and ZCode substitute `${CLAUDE_SKILL_DIR}/../..`; Kimi Code substitutes `${KIMI_SKILL_DIR}/../..`; a SessionStart line `Plugin root (resolved by this hook…)` names it on Claude Code, Codex, ZCode and Cursor; Codex and Grok CLI show this skill's absolute path in the skill listing. A `${…}` token still shown literally is unresolved: never pass it to a shell. Confirm `<runtime-root>/scripts/validate_artifacts.py` exists and write that absolute path, quoted for your shell, into commands; if it cannot be confirmed, stop the step and report `plugin root unresolved` — never run a same-named file from the user's project. Run helpers with `python3` (Python 3.8+), or `py -3` on Windows when `python3` is missing or is the Microsoft Store alias.
When developing this checkout, its absolute root is `<runtime-root>`.
For a standalone `.skill`, invoke the resolver by its extracted skill-local path instead;
the runtime eval runners below require companion plugin resources.

```bash
python3 "<runtime-root>/skills/skill-authoring/scripts/resolve_skill_creator.py"
```

The default requires validation, benchmark, viewer (including its template), packaging, and
eval schemas from one root. Narrow with `--require validate` for a validation-only change, or
`--require benchmark viewer schemas` for reviewing existing runs. Use `skill_creator_root` as
`SC` only after exit 0 and `skill_creator_status=found` (or `installed`). Read the source and
trust fields; `explicit-unverified` roots need source review and execution authorization already
present in the task, or explicit approval. Discovery never executes candidate scripts.

```bash
python3 "<runtime-root>/skills/skill-authoring/scripts/resolve_skill_creator.py" --require package
```

On `missing` / `missing_capabilities`, use the reported missing files to identify the absent
dependency. Continue independent authoring work; do not invoke absent scripts or label missing
evidence as passing. `--install` changes the Claude installation and is only for an already
authorized dependency install; otherwise present the exact install command for approval.

Before running tools, read `references/house-notes.md` for the capability-to-command matrix,
absolute path and UTF-8 setup, and runtime-specific eval semantics. Claude trigger checks use
the repo's Windows-safe `run_trigger_eval.py`; Codex uses `run_codex_trigger_eval.py`, a route
classifier that does not prove installed skill activation. The external `run_eval.py` and
`run_loop.py` are Claude tools and cannot substitute for Codex evaluation.

For behavioral comparison on either runtime, run old/no-skill and new-skill tasks in isolated
contexts, preserve transcripts and outputs, grade against the selected toolkit's schemas,
aggregate, and generate the static viewer before reviewing or judging. Record unavailable
runtime capabilities as explicit limits; file discovery itself is not a successful eval.

## Frontmatter that survives validation

The shared format permits `name`, `description`, `license`, `allowed-tools`, `metadata`, and
`compatibility`; keep just `name` + `description` unless another field is needed. External
validators differ by installation: the inspected Codex system validator rejects `compatibility`,
while the full Claude toolkit accepts it. Read and run the selected validator before packaging;
report tool-specific rejection separately from format validity. The local house rule also
rejects `<` or `>` in descriptions; `user-invocable` and `argument-hint` are outside the shared set.

The `description` is the trigger — it is the only body text Claude sees when deciding to invoke
the skill. Write it third-person and as *when to use*, not *what it does*, and seed it with the
real phrasings and contexts a user would type. Claude tends to under-trigger, so name the
situations explicitly; but don't go so broad it fires on adjacent work (that is the near-miss
failure the description-optimization step measures).

**Example — description framing**
Weak (what-it-does): `Creates and edits Claude skills.`
Strong (when-to-use): `Applies when creating, editing, evaluating, or packaging a Claude Code or Codex skill, including SKILL.md and trigger-description changes.`

## Rationalization table

The model (and the author) will reach for these excuses under time pressure. Each is a trap; the
reality column is why.

| Excuse | Reality |
|---|---|
| "It looks right, no need to run a baseline." | Looking right is not evidence. Without a RED baseline you cannot show the skill helps — it may even hurt. |
| "More instructions make it more reliable." | Length dilutes attention. Past a point, extra text makes the model wander and slows every run. |
| "Caps-MUST / ALWAYS / NEVER will force compliance." | Bare commands get rationalized away and don't transfer to new phrasings. A stated reason generalizes. |
| "It passes my three test prompts, ship it." | Three prompts is overfitting. The skill runs a million times; prove it on a held-out phrasing. |
| "I'll write the skill, then make up evals to match." | Evals reverse-engineered from the skill test nothing. The failure must exist before the fix. |
| "The viewer is optional, I'll just eyeball outputs." | Self-judging before review hides your own bias. Generate the viewer and look first. |
| "Add `argument-hint` / `user-invocable`, other skills have them." | `quick_validate` rejects those keys → AC1 fails → no package. Stay within the allowed set. |
| "Run scripts by direct path, `-m` is fussy." | `run_eval`/`run_loop`/`package_skill` need `-m` from `SC` or they `ModuleNotFoundError`. |

## Red flags — stop and re-check

If you catch yourself doing any of these, pause:

- Writing or expanding the skill **before** capturing a RED failure.
- A SKILL.md body drifting past ~500 lines with no `references/` split.
- Stacks of caps `MUST`/`ALWAYS`/`NEVER` instead of a one-line reason.
- A `description` written as what-it-does, or containing `<`/`>`, or with frontmatter keys
  outside the allowed set.
- Tuning wording to pass the exact test prompts (overfitting) instead of a held-out one.
- Forming a verdict on eval outputs before the viewer was generated for review.
- Claiming "triggers" / "passed" / "works" without run output, a transcript, or a diff.

## Checklist

- [ ] RED: baseline failure captured on a subagent (no skill / old version).
- [ ] GREEN: minimal skill makes those exact failures pass; re-run confirms it.
- [ ] REFACTOR: transcript read, loopholes closed, verified on a held-out phrasing.
- [ ] `description` is when-to-use, CSO-seeded, no `<`/`>`; frontmatter within allowed keys.
- [ ] Body lean and under ~500 lines; overflow pushed to `references/`.
- [ ] Viewer generated (`--static` on Windows) and reviewed **before** any verdict.
- [ ] Required toolkit capabilities resolved; selected validator exits 0; `.skill` packaged
      from `SC` with an absolute output directory outside the skill; archive contents reviewed.
- [ ] Every success claim backed by real evidence (output / transcript / diff).
