"""Consistency guard for hooks/flow-requirements.json (the shared flow-enforcement source).

The live hooks (flow-step-guard, flow-order-guard) read this file at runtime; this test is the
OFFLINE consumer in the gate. It proves every skill / workflow / agent / script the config names
resolves to a real component, so enforcement can never reference a renamed or removed target
(AC8: one shared source, read by both the hook and the gate).
"""
import importlib.util
import json
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CONFIG = REPO / "hooks" / "flow-requirements.json"
HARNESS = HERE / "skills" / "harness.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("skill_harness", HARNESS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


h = _load_harness()


class TestFlowRequirements(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.known = h.skill_names() | h.workflow_names() | h.agent_names()

    def test_parses_with_flows(self):
        self.assertGreaterEqual(self.cfg.get("version", 0), 1)
        self.assertTrue(self.cfg.get("flows"), "no flows defined")

    def test_active_when_skill_resolves(self):
        for name, flow in self.cfg["flows"].items():
            marker = flow.get("activeWhen", {}).get("skill", "")
            self.assertIn(marker, h.skill_names(), f"{name}: activeWhen.skill '{marker}' is not a real skill")

    def test_tooluse_markers_resolve(self):
        for name, flow in self.cfg["flows"].items():
            for step in flow.get("steps", []):
                for item in step.get("evidence", []):
                    if item.get("kind") != "toolUse":
                        continue
                    marker = item.get("contains", "")
                    self.assertIn(
                        marker, self.known,
                        f"{name}/{step['id']}: toolUse marker '{marker}' resolves to no skill/workflow/agent",
                    )

    def test_artifact_steps_reference_real_validator(self):
        uses_artifact = any(
            item.get("kind") == "artifact"
            for flow in self.cfg["flows"].values()
            for step in flow.get("steps", [])
            for item in step.get("evidence", [])
        )
        if uses_artifact:
            self.assertTrue((REPO / "scripts" / "validate_artifacts.py").exists())

    def test_command_regex_keys_compile(self):
        for key in ("testCommand", "completionClaim"):
            re.compile(self.cfg[key])

    def test_branch_step_warn_only_in_all_four_flows(self):  # AC32, AC33
        for name in ("root-cause-fix", "feature-build", "safe-refactor", "agentic-sdlc-pipeline"):
            with self.subTest(flow=name):
                steps = [s for s in self.cfg["flows"][name]["steps"] if s["id"] == "branch"]
                self.assertEqual(len(steps), 1)
                step = steps[0]
                self.assertEqual((step["stop"], step["beforeSourceEdit"], [e["kind"] for e in step["evidence"]]),
                                 ("warn", False, ["branch"]))

    def test_review_result_reviewers_match_flow_steps(self):  # AC37
        for name, flow in self.cfg["flows"].items():
            with self.subTest(flow=name):
                steps = {s["id"]: s for s in flow["steps"]}
                review = [s for s in flow["steps"] if s["id"] == "review-result"]
                self.assertEqual(len(review), 1)
                step = review[0]
                self.assertEqual((step["stop"], step["beforeSourceEdit"], len(step["evidence"])), ("warn", False, 1))
                evidence = step["evidence"][0]
                self.assertEqual(evidence["kind"], "reviewResult")
                expected = {group: [{"tool": e["tool"], "contains": e["contains"]}
                                    for e in steps[group]["evidence"] if e["kind"] == "toolUse"]
                            for group in ("control", "security") if group in steps}
                self.assertEqual(evidence["reviewers"], expected)
        safe_refactor = [s for s in self.cfg["flows"]["safe-refactor"]["steps"] if s["id"] == "review-result"]
        self.assertEqual(set(safe_refactor[0]["evidence"][0]["reviewers"]), {"control"})

    def test_review_result_markers_resolve(self):  # AC37
        markers = [member["contains"]
                   for flow in self.cfg["flows"].values() for step in flow["steps"]
                   for item in step["evidence"] if item.get("kind") == "reviewResult"
                   for group in item["reviewers"].values() for member in group]
        self.assertTrue(markers, "no reviewResult evidence declares reviewers")
        for marker in markers:
            self.assertIn(marker, self.known)


if __name__ == "__main__":
    unittest.main()
