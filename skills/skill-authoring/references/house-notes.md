# House notes — skill-authoring

Read this when you need the *why* behind a step in `SKILL.md`, the register decision for a
new skill, or the exact way to call a skill-creator script on this Windows host.

## Table of contents
- [1. Don't relearn the canon — point to it](#1-dont-relearn-the-canon--point-to-it)
- [2. Register matrix (house style)](#2-register-matrix-house-style)
- [3. skill-creator invocation matrix (corrected for this host)](#3-skill-creator-invocation-matrix-corrected-for-this-host)
- [4. Windows specifics](#4-windows-specifics)

## 1. Don't relearn the canon — point to it

The general skill-authoring theory already lives in skill-creator's reference. Keep local
agent operating files out of packaged skill behavior; they are workspace instructions, not
plugin sources. Read plugin behavior from tracked plugin docs, contracts, and skills so there
is one copy to keep correct:

- **Degrees of freedom, progressive disclosure (3 levels), context-sensitive optimization (CSO)
  of the description, token budgets, domain-by-reference organization:**
  Resolve `skill-creator` with `scripts/resolve_skill_creator.py` and read its `SKILL.md`
  and `references/schemas.md` at the discovered root (eval / grading / benchmark JSON shapes).
- **House doctrine** (lean beats long, explain-the-why over caps-MUST stacking, a skill is a
  prompt that runs a million times, the authoring workflow, approval gates):
  `docs/plugin-readme.md`, `docs/testing.md`, `docs/skill-boundaries.md`, and
  `contracts/skills/00-global-behavior.md`.

This file holds only what those two do *not* cover: our register policy and the portable way to
discover and run the reused scripts.

## 2. Register matrix (house style)

We borrow superpowers' *mechanics* (RED/GREEN/REFACTOR, rationalization table, red-flags,
a numbered gate) but not its commanding *register*. Match tone to what the skill is for, because
an over-authoritative reference skill wastes the reader's trust and an under-authoritative
discipline skill gets ignored at the moment it matters.

| Skill type | Persuasion goal | Register to use | Why |
|---|---|---|---|
| **Reference / lookup** (schemas, API maps, "how is X shaped") | clarity only | neutral, descriptive, zero exhortation | the reader already decided to act; they need facts, not pressure. Authority here just adds noise. |
| **Discipline / gate** (the narrow core that must hold under pressure, e.g. RED/GREEN/REFACTOR, completion-claim-gate) | get a step done that the model is tempted to skip | moderate, *reasoned* authority — explain the failure it prevents, then ask for the step | a step the model skips needs a reason to stop it; a bare command without the why doesn't generalize and gets rationalized away. Keep authority reserved and explained, never caps-MUST barked. |

Default to the reference register. Spend authority only on the one or two steps that actually
fail without it, and always pair the ask with the reason it exists.

## 3. skill-creator invocation matrix (corrected for this host)

Resolve the skill-creator root before running any external script:

```bash
python skills/skill-authoring/scripts/resolve_skill_creator.py
```

If it prints `skill_creator_status=missing`, run:

```bash
python skills/skill-authoring/scripts/resolve_skill_creator.py --install
```

The helper checks `SKILL_CREATOR_ROOT`, `AGENTIC_SDLC_SKILL_CREATOR_ROOT`, Codex skill homes,
Claude plugin caches, and the legacy Claude marketplace layout. With `--install`, it runs
`claude plugin install skill-creator@claude-plugins-official` and then resolves again.
Use the printed `skill_creator_root` as `SC`.

skill-creator scripts split into two call styles, decided by whether the script does a
package-relative import (`from scripts.*`). Calling a package-relative script by direct path
fails with `ModuleNotFoundError: No module named 'scripts.utils'`. Verified against the real
source.

| Script | Has `from scripts.*`? | How to call | Note |
|---|---|---|---|
| `run_eval.py` | yes (`scripts.utils`) | `python -m scripts.run_eval ...` **from `SC`** | broken on Windows — see §4 |
| `run_loop.py` | yes (`scripts.*`) | `python -m scripts.run_loop ...` **from `SC`** | wraps run_eval → also blocked on Windows |
| `improve_description.py` | yes (`scripts.utils`) | `python -m scripts.improve_description ...` **from `SC`** | |
| `package_skill.py` | yes (`scripts.quick_validate`) | `python -m scripts.package_skill <skill-path>` **from `SC`** | validates first; excludes `evals/` |
| `quick_validate.py` | no | `python <SC>/scripts/quick_validate.py <skill-path>` (direct) | exit 0 = valid |
| `aggregate_benchmark.py` | no | `python <SC>/scripts/aggregate_benchmark.py <ws>/iteration-N --skill-name <name>` (direct) | stdlib only |
| `generate_review.py` | no (`SC/eval-viewer/`) | `python <SC>/eval-viewer/generate_review.py <ws>/iteration-N --static <out.html>` (direct) | use `--static` on Windows — see §4 |

`-m` runs from the package root so Python resolves `scripts` as a package; direct path runs the
file standalone, which only works when it imports nothing from its own package.

## 4. Windows specifics

- **`run_eval.py` (and therefore `run_loop.py`) does not run on Windows.** It imports `select`
  and at `run_eval.py:108` calls `select.select([process.stdout], [], [], 1.0)` on a pipe handle;
  on Windows `select` accepts only sockets, so the run dies with
  `OSError: [WinError 10038] An operation was attempted on something that is not a socket`.
  This is the *triggering* harness (non-gating), so triggering-eval / description-optimization is
  not run on this host. For behavioral evals use the sequential-subagent path instead:
  spawn with-skill + baseline subagents → grader writes `grading.json` →
  `aggregate_benchmark.py` (direct) → `generate_review.py --static`.
- **Viewer: always pass `--static <out.html>`.** The server path relies on `lsof` / `webbrowser`,
  which are unreliable here; `--static` writes a standalone HTML file with no server and no
  display dependency. Open the file directly to review outputs before forming a verdict.
- **PyYAML is a host prerequisite** for `quick_validate.py` / `package_skill.py` (third-party,
  not stdlib). It is present on this host; note it if you move to a clean machine.
- **Set `PYTHONUTF8=1` before `package_skill.py`.** It prints emoji (`📦`, `✅`) to stdout; the
  default Windows console here is code page cp1254 (Turkish), which raises
  `UnicodeEncodeError: 'charmap' codec can't encode character '\U0001f4e6'` and aborts packaging
  with exit 1 — even though the skill is valid. `$env:PYTHONUTF8="1"` (or `PYTHONIOENCODING=utf-8`)
  makes stdout UTF-8 and packaging succeeds. Verified: with the flag, `skill-authoring.skill` packs
  cleanly (exit 0).
