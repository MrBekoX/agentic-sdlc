"""Fixture + golden + safety validation (test matrix B, D, G).

- G (regression): every skill has a golden entry; each entry's core description keywords
  still appear in the live SKILL.md description (description-drift guard).
- D (safety): every safety scenario's guardrail evidence text actually exists in the repo
  (proves the guardrail is WIRED; runtime obedience is a live eval, not asserted here).
- B (trigger): every evals/*.json is well-formed (run_trigger_eval.py shape), targets a real
  skill, and carries both positive and negative (near-miss) queries. This validates the
  fixtures; whether a skill actually triggers is verified only by the LIVE eval (claude
  required) — see tests/skills/README.md.
"""

import importlib.util
import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
HARNESS = HERE / "skills" / "harness.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("skill_harness", HARNESS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


h = _load_harness()


class TestGoldenRegression(unittest.TestCase):
    def test_every_skill_has_a_golden_entry(self):
        golden = h.load_golden()["skills"]
        missing = sorted(h.skill_names() - set(golden))
        self.assertEqual(missing, [], f"skills without a golden entry: {missing}")

    def test_no_orphan_golden_entries(self):
        golden = h.load_golden()["skills"]
        orphans = sorted(set(golden) - h.skill_names())
        self.assertEqual(orphans, [], f"golden entries for non-existent skills: {orphans}")

    def test_description_keywords_present(self):
        golden = h.load_golden()["skills"]
        failures = {}
        for name in sorted(h.skill_names()):
            if name not in golden:
                continue
            errors, _ = h.validate_golden(h.SKILLS_DIR / name, golden[name])
            if errors:
                failures[name] = errors
        self.assertEqual(failures, {}, f"description drift: {failures}")


class TestSafetyFixtures(unittest.TestCase):
    def test_safety_has_all_seven_scenarios(self):
        data = h.load_safety()
        ids = [s["id"] for s in data["scenarios"]]
        self.assertEqual(len(ids), 7, f"expected 7 safety scenarios, got {ids}")
        self.assertEqual(len(ids), len(set(ids)), "duplicate safety scenario ids")

    def test_every_scenario_well_formed(self):
        data = h.load_safety()
        for s in data["scenarios"]:
            for key in ("id", "prompt", "category", "expected_behavior", "guardrail_evidence"):
                self.assertIn(key, s, f"scenario {s.get('id')} missing '{key}'")
            self.assertTrue(s["guardrail_evidence"], f"scenario {s['id']} has no guardrail evidence")

    def test_guardrail_evidence_exists_in_repo(self):
        # Deterministic: each guardrail's text is actually present in the cited repo file.
        errors, warnings = h.validate_safety_guardrails()
        self.assertEqual(errors, [], f"safety guardrail evidence missing: {errors}")


class TestTriggerEvalSets(unittest.TestCase):
    def _evalsets(self):
        return sorted(h.EVALS_DIR.glob("*.json"))

    def test_eval_sets_exist(self):
        self.assertGreaterEqual(len(self._evalsets()), 1, "no trigger eval-sets found")

    def test_each_eval_set_well_formed_and_targets_real_skill(self):
        skills = h.skill_names()
        for p in self._evalsets():
            data = json.loads(p.read_text(encoding="utf-8"))
            self.assertIn(p.stem, skills, f"{p.name}: no skill named '{p.stem}'")
            self.assertIn("queries", data, f"{p.name}: missing 'queries'")
            self.assertTrue(data["queries"], f"{p.name}: empty queries")
            for q in data["queries"]:
                self.assertIn("query", q, f"{p.name}: a query missing 'query'")
                self.assertIsInstance(q.get("should_trigger"), bool,
                                      f"{p.name}: should_trigger must be bool")

    def test_every_skill_has_trigger_eval_set(self):
        eval_names = {p.stem for p in self._evalsets()}
        missing = sorted(h.skill_names() - eval_names)
        self.assertEqual(missing, [], f"skills without trigger eval-set: {missing}")

    def test_each_eval_set_has_positive_and_negative(self):
        for p in self._evalsets():
            data = json.loads(p.read_text(encoding="utf-8"))
            flags = {q["should_trigger"] for q in data["queries"]}
            self.assertIn(True, flags, f"{p.name}: no positive (should_trigger) query")
            self.assertIn(False, flags, f"{p.name}: no negative (near-miss) query")


if __name__ == "__main__":
    unittest.main()
