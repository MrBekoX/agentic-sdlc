# Skill / agent / workflow / hook / contract test harness

Deterministic, stdlib-only validation for the *artifact wiring* layer (the part the
script tests under `tests/test_detect_context.py` / `tests/test_validate_artifacts.py` do
not cover). It checks structure and cross-references — **not** runtime model behavior.

## What it proves (and what it can't)

| Layer | Verified here (deterministic) | Verified only LIVE (model required) |
|---|---|---|
| Structure (A) | frontmatter valid, name == dir, allowed keys, description present | — |
| Trigger (B) | eval-set well-formedness, target skill exists, pos+neg present | whether a skill actually triggers → `run_trigger_eval.py` |
| Procedure (C) | core flow skills reference their steps/work-flows (via golden) | step *ordering at runtime* |
| Safety (D) | each scenario's guardrail text is **wired** in a contract/skill/hook | whether the model *obeys* the guardrail |
| Tool-use (E) | hook `.mjs` + workflow `.js` parse (`node --check`) | runtime tool decisions |
| Integration (F) | every cross-reference + `${CLAUDE_PLUGIN_ROOT}` path resolves | — |
| Regression (G) | golden baseline: name + description keywords + must_reference | — |

The harness reports **errors** (gating) and **warnings** (non-gating doc drift), mirroring
`scripts/check_all.py`.

## Layout

```
tests/skills/
  harness.py            # stdlib library + standalone runner (python tests/skills/harness.py)
  golden/skills.json    # per-skill regression baseline + must_reference cross-ref map (G/F)
  fixtures/safety.json  # 7 unsafe-instruction scenarios + wired-guardrail evidence (D)
  evals/<skill>.json    # live trigger eval-sets, run_trigger_eval.py format (B)
  README.md             # this file
```

The unittest **runners live at `tests/` top level** (`test_skill_structure.py`,
`test_skill_integration.py`, `test_skill_fixtures.py`, `test_static_node.py`), not under
`tests/skills/`. Reason: `scripts/check_all.py` runs `python -m unittest discover -s tests`,
which collects `test_*.py` at the top level exactly like the two existing script suites —
so the new tests join the gate automatically with no import/package gymnastics. `tests/skills/`
holds only the library, fixtures, and golden data (no `snapshots/` dir — `golden/` already
serves the regression-snapshot role; a second copy would just drift).

## Running

```bash
# Official gate (lints skill frontmatter + runs ALL discovered tests, incl. these):
python scripts/check_all.py

# Just the new suites:
python -m unittest discover -s tests -p "test_skill_*.py" -v
python -m unittest discover -s tests -p "test_static_node.py" -v

# Standalone harness summary (sorted key=value, exit 1 on error):
python tests/skills/harness.py
```

`test_static_node.py` **skips** (does not pass) if `node` is absent.

## Live trigger eval (B) — gated, model required, not run by the gate

```bash
python scripts/run_trigger_eval.py \
  --skill-path skills/root-cause-fix --eval-set tests/skills/evals/root-cause-fix.json --runs 3
```

Needs the `claude` CLI + auth. It is a real token/time cost (queries × runs), so run it
deliberately — never claim a skill "triggers" without its output. If `claude` is missing or
unauthenticated, treat the result as **skipped/blocked**, not passed.

## Extending

- New skill → add a `golden/skills.json` entry (`test_every_skill_has_a_golden_entry`
  fails until you do) and, if collision-prone, an `evals/<skill>.json`.
- New cross-reference contract → add it to that skill's `must_reference`.
- New safety guardrail → add a scenario to `fixtures/safety.json` with `guardrail_evidence`
  pointing at the real contract/skill/hook text that wires it.
