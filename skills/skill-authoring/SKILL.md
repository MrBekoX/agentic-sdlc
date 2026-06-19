---
name: skill-authoring
description: Use first in any language to create, edit, test, evaluate, optimize, or package a Claude Agent Skill or Codex skill. Activate this skill as the first action even when the target skill is unstated, before reading files or asking which skill to improve. Covers SKILL.md, frontmatter/description tuning, trigger optimization, eval fixtures/harnesses, and .skill packaging.
---

# Skill: skill-authoring

> Authoring a skill is not writing prose — it is debugging a prompt that will run a million
> times. This skill makes that loop disciplined: prove a real failure exists, fix exactly that
> failure with the least text, then close the loopholes the model used to wriggle out. Heavy
> machinery (evals, the review viewer, packaging) is reused from `skill-creator`; this skill owns
> the *method*, not a parallel toolset.

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

This skill does not re-implement evals, the viewer, or packaging — it calls `skill-creator`.
The call style differs per script, and getting it wrong is the most common time-sink.
Resolve `SC` first; do not assume a fixed Claude or Codex home path:

```bash
python skills/skill-authoring/scripts/resolve_skill_creator.py
```

If the output is `skill_creator_status=found`, use `skill_creator_root` as `SC`. If it is
`missing`, run the same helper with `--install` so it fetches `skill-creator` from the official
Claude marketplace and resolves again:

```bash
python skills/skill-authoring/scripts/resolve_skill_creator.py --install
```

Then use this matrix exactly.

| Task | Script | How to call |
|---|---|---|
| Validate skill structure / frontmatter | `quick_validate.py` | direct: `python <SC>/scripts/quick_validate.py <skill-path>` |
| Aggregate eval results into a benchmark | `aggregate_benchmark.py` | direct: `python <SC>/scripts/aggregate_benchmark.py <ws>/iteration-N --skill-name <name>` |
| Build the review viewer (review before judging) | `generate_review.py` | direct: `python <SC>/eval-viewer/generate_review.py <ws>/iteration-N --static <out.html>` |
| Run the triggering eval | `run_eval.py` | package: `python -m scripts.run_eval ...` **from `SC`** |
| Optimize the description (loop) | `run_loop.py` | package: `python -m scripts.run_loop ...` **from `SC`** |
| Package the final `.skill` | `package_skill.py` | package: `python -m scripts.package_skill <skill-path>` **from `SC`** |

Why two styles: `run_eval`, `run_loop`, and `package_skill` do package-relative imports
(`from scripts....`), so they need `python -m scripts.<name>` run from `SC` (the package root);
calling them by direct path fails with `ModuleNotFoundError: No module named 'scripts.utils'`.
The other three import nothing from their own package, so a direct path is fine.

**On Windows (this host):**
- Always generate the viewer with `--static <out.html>` — the server path leans on `lsof` /
  `webbrowser`, which are unreliable here; `--static` writes a standalone file you just open.
- `run_eval.py` (and `run_loop.py`, which wraps it) is **broken on Windows**: it calls
  `select.select` on a pipe at `run_eval.py:108`, and Windows `select` accepts only sockets, so it
  dies with `WinError 10038`. The triggering eval is therefore not run on Windows. For behavioral
  evals use the sequential-subagent path instead (with-skill + baseline subagents → grader writes
  `grading.json` → `aggregate_benchmark.py` → `generate_review.py --static`), and review the
  viewer **before** forming any verdict.

For the deeper canon (degrees of freedom, progressive-disclosure levels, CSO of the description,
token budgets, the register matrix) read `references/house-notes.md`; it points to skill-creator's
own reference rather than duplicating it.

## Frontmatter that survives validation

`quick_validate.py` allows only these keys: `name`, `description`, `license`, `allowed-tools`,
`metadata`, `compatibility`. It rejects anything else (e.g. `user-invocable`, `argument-hint`) and
rejects `<` or `>` anywhere in the description. Keep frontmatter to `name` + `description` unless
you have a real need for the others, because an invalid key fails AC1 and blocks packaging.

The `description` is the trigger — it is the only body text Claude sees when deciding to invoke
the skill. Write it third-person and as *when to use*, not *what it does*, and seed it with the
real phrasings and contexts a user would type. Claude tends to under-trigger, so name the
situations explicitly; but don't go so broad it fires on adjacent work (that is the near-miss
failure the description-optimization step measures).

**Example — description framing**
Weak (what-it-does): `Creates and edits Claude skills.`
Strong (when-to-use): `Use when creating, editing, or testing a Claude skill — authoring a SKILL.md, writing evals, fixing why a skill never triggers, or packaging a .skill.`

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
- [ ] `quick_validate.py` exits 0; `.skill` packaged via `python -m scripts.package_skill` from `SC`.
- [ ] Every success claim backed by real evidence (output / transcript / diff).
