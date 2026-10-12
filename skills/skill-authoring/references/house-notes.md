# House notes — skill-authoring

Read this when you need the *why* behind a step in `SKILL.md`, the register decision for a
new skill, or the exact way to select and call an installed toolkit on either runtime.

## Table of contents
- [1. Don't relearn the canon — point to it](#1-dont-relearn-the-canon--point-to-it)
- [2. Register matrix (house style)](#2-register-matrix-house-style)
- [3. Capability selection and commands](#3-capability-selection-and-commands)
- [4. Runtime evaluation and Windows](#4-runtime-evaluation-and-windows)

## 1. Don't relearn the canon — point to it

The general skill-authoring theory already lives in skill-creator's reference. Keep local
agent operating files out of packaged skill behavior; they are workspace instructions, not
plugin sources. Read plugin behavior from tracked plugin docs, contracts, and skills so there
is one copy to keep correct:

- **Degrees of freedom, progressive disclosure (3 levels), context-sensitive optimization (CSO)
  of the description, token budgets, domain-by-reference organization:**
  Resolve `skill-creator` with `scripts/resolve_skill_creator.py --require schemas` before
  reading `references/schemas.md` (eval / grading / benchmark JSON shapes). Read its `SKILL.md`
  for the workflow; the Codex system edition does not necessarily include these eval schemas.
- **House doctrine** (lean beats long, explain-the-why over caps-MUST stacking, a skill is a
  prompt that runs a million times, the authoring workflow, approval gates):
  `<runtime-root>/docs/plugin-readme.md`, `<runtime-root>/docs/testing.md`, `<runtime-root>/docs/skill-boundaries.md`, and
  `<runtime-root>/contracts/skills/00-global-behavior.md` (`<runtime-root>` as defined in `SKILL.md`).

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

## 3. Capability selection and commands

Run the resolver from this skill's `scripts/` directory by absolute path. Resolve the plugin
root as described in `SKILL.md`; do not assume the current directory is the plugin checkout.
Discovery is read-only and checks explicit environment roots, the Codex system skill, and
versioned `claude-plugins-official/skill-creator` caches. It skips candidates missing requested
resources and reports the omitted file paths. It never searches arbitrary plugin caches.

| Work | Resolver arguments | Files required together |
|---|---|---|
| Complete behavioral authoring loop (default) | none | `validate benchmark viewer package schemas` below |
| Structural validation only | `--require validate` | `scripts/quick_validate.py` |
| Aggregate graded runs | `--require benchmark` | `scripts/aggregate_benchmark.py` |
| Render review | `--require viewer` | `eval-viewer/generate_review.py` and `viewer.html` |
| Package a skill | `--require package` | `scripts/package_skill.py` and `quick_validate.py` |
| Read eval data shapes | `--require schemas` | `references/schemas.md` |
| External Claude trigger/optimization tools | `--require trigger optimize` | `run_eval.py`, `run_loop.py`, their shared helpers; see runtime limits below |

Multiple capabilities may share one request, e.g. `--require benchmark viewer schemas`.
Exit 0 means the requested files exist, **not** that Python dependencies, CLI/auth, or runtime
behavior have passed. `skill_creator_capabilities` inventories the selected root's resources.
An incomplete installation returns exit 2 with `skill_creator_status=missing_capabilities`;
no installation returns `missing`. After an authorized `--install`, discovery runs again and
still fails if the required resources are absent. Use the printed source/trust and the
execution-authorization rule in `SKILL.md` before running external code.

Use the selected absolute `skill_creator_root` as `SC`, and absolute paths for `<skill-path>`,
`<iteration>`, `<out.html>`, and `<dist>`. Keep `<dist>` outside the skill being packaged so a
previous archive cannot be included in the next one. `-X utf8` makes both reads and output
portable on Windows; `-B` avoids writing bytecode into the installed toolkit.

| Task | Invocation |
|---|---|
| Validate | `python3 -X utf8 -B "<SC>/scripts/quick_validate.py" "<skill-path>"` |
| Aggregate | `python3 -X utf8 -B "<SC>/scripts/aggregate_benchmark.py" "<iteration>" --skill-name <name>` |
| Static viewer | `python3 -X utf8 -B "<SC>/eval-viewer/generate_review.py" "<iteration>" --benchmark "<iteration>/benchmark.json" --static "<out.html>"` |
| Package | From `SC`: `python3 -X utf8 -B -m scripts.package_skill "<skill-path>" "<dist>"` |

Module invocation from `SC` is necessary for `package_skill` and the external `run_eval` /
`run_loop`: they import `scripts.*`. Quote paths that may contain spaces. Inspect archive entries
and scan content for secrets before delivery; the inspected official packager excludes
`__pycache__`, `node_modules`, `*.pyc`, `.DS_Store`, and root-level `evals/`, but it is not a secret
scanner and does not make every file in a skill safe to distribute.

Validation scope differs by edition. The installed Codex system validator inspected on
2026-09-12 permits `name`, `description`, `license`, `allowed-tools`, and `metadata`; the full
Claude edition also permits `compatibility`. The [shared specification](https://agentskills.io/specification)
includes all six. Inspect the selected validator before using optional fields, keep meaningful
metadata intact, and report a validator-specific incompatibility instead of declaring the
skill format invalid or silently removing user data.

## 4. Runtime evaluation and Windows

The repo's runtime-specific runners already replace the external trigger harness where needed.
Run their `--help` before using optional flags; keep the user's selected model and effort, and
keep baseline/new/held-out fixture inputs comparable. From the resolved plugin root:

The repo runners are plugin companions, outside the standalone `.skill` archive. Verify the
selected runner exists under `<runtime-root>/scripts` before invoking it. With only the
standalone skill installed, capture native behavioral transcripts and use the external
benchmark/viewer tools; report unavailable trigger/classifier measurement explicitly instead
of calling absent files. Do not duplicate the companion runners into the skill.

| Runtime and measurement | Command shape | Evidence limit |
|---|---|---|
| Claude real Skill/Read activation | `python3 "<runtime-root>/scripts/run_trigger_eval.py" --skill-path "<skill-path>" --eval-set "<eval-set>" --plugin-dir "<runtime-root>" --no-command-shim --model <model> --transcript-dir "<transcripts>"` | CLI + auth required; Windows-safe runner; inspect tool events |
| Codex description routing | `python3 "<runtime-root>/scripts/run_codex_trigger_eval.py" --skill-path "<skill-path>" --eval-set "<eval-set>" --model <model> --reasoning-effort <effort> --transcript-dir "<transcripts>"` | Route-classifier proxy; does not prove installed-plugin discovery or procedure execution |
| Either runtime's actual procedure | Capture an isolated native session/subagent transcript, then `python3 "<runtime-root>/scripts/run_procedure_eval.py" --eval-set "<procedure-fixture>" --transcript "<transcript>"` | Replay checks only the supplied transcript and fixture assertions; `--live` invokes Claude only |

Trigger fixtures use the repository `{"queries": [...]}` schema; do not pass them unchanged to
the external toolkit, whose trigger schema is a JSON list. Repo trigger summary output is not
`grading.json`. For behavioral review, preserve raw transcripts/artifacts and write grades
against `references/schemas.md` from a root selected with `--require schemas`; use the benchmark
and viewer commands above. Inspect generated benchmark metadata before rendering: the inspected
aggregator leaves model/path placeholders and a default run count. Replace these with the actual
skill path, models (or "not applicable" for deterministic checks), and observed run counts.
Review the viewer before a verdict. A synthetic grading fixture can
smoke-test the toolchain but cannot establish that a skill triggers or improves behavior.

For optional automated description optimization on a supported Claude host, resolve
`--require trigger optimize`, inspect that installed version's `SKILL.md` and script `--help`,
then invoke `python3 -X utf8 -B -m scripts.run_loop ...` from `SC`. The inspected official
`run_eval.py` uses `select.select` on stdout pipes, which is unsupported on Windows; `run_loop`
wraps it. On Windows, iterate descriptions with the repo Claude runner and held-out prompts.
For Codex, use its classifier and native procedure transcripts. Neither external command runs
Codex, and resource presence alone does not remove these runtime limits.

Always use `--static` for portable review: it writes standalone HTML without opening a browser,
starting a server, or terminating a process using the viewer port. The external validator and
packager require PyYAML; check `python3 -c "import yaml"` with the selected interpreter and
report a missing dependency. Install only when the current task already authorizes it or the
user approves the concrete install. `-X utf8` also prevents packaging emoji from failing on
legacy Windows console encodings.

Source checks (2026-09-12): installed toolkit sources and the
[official skill-creator package](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/skill-creator),
[official packager](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/skill-creator/skills/skill-creator/scripts/package_skill.py),
and [marketplace install documentation](https://code.claude.com/docs/en/discover-plugins).
Recheck the selected version when its source or command contract changes.
