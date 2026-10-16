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


def marker_violations(cfg):
    """(flow, step id, evidence index, markers present) for every toolUse evidence item that does not
    carry exactly one of `contains` / `exactName` (C6)."""
    out = []
    for name, flow in cfg.get("flows", {}).items():
        for step in flow.get("steps", []):
            for index, item in enumerate(step.get("evidence", [])):
                if item.get("kind") != "toolUse":
                    continue
                present = [k for k in ("contains", "exactName") if k in item]
                if len(present) != 1:
                    out.append((name, step["id"], index, present))
    return out


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

    def _names_for(self, tool):
        """The component names a toolUse marker for `tool` must resolve against (C6): a Skill marker
        names a skill, an Agent marker names an agent, a Workflow marker names a workflow."""
        return {"Skill": h.skill_names(), "Agent": h.agent_names(), "Workflow": h.workflow_names()}.get(tool, self.known)

    def test_tooluse_markers_resolve(self):  # C6: marker = exactName or contains, resolved per tool
        for name, flow in self.cfg["flows"].items():
            for step in flow.get("steps", []):
                for item in step.get("evidence", []):
                    if item.get("kind") != "toolUse":
                        continue
                    marker = item.get("exactName") or item.get("contains", "")
                    self.assertIn(
                        marker, self._names_for(item.get("tool")),
                        f"{name}/{step['id']}: {item.get('tool')} toolUse marker '{marker}' resolves to no "
                        f"known {item.get('tool')} name",
                    )

    def test_tooluse_items_carry_exactly_one_marker(self):  # C6
        self.assertEqual(marker_violations(self.cfg), [],
                         "a toolUse item needs exactly one of contains/exactName")

    def test_marker_check_rejects_both_and_neither(self):  # negative controls for the check above
        synthetic = {"flows": {"x": {"steps": [{"id": "s", "evidence": [
            {"kind": "toolUse", "tool": "Agent", "contains": "security-reviewer", "exactName": "security-reviewer"},
            {"kind": "toolUse", "tool": "Agent"},
            {"kind": "toolUse", "tool": "Agent", "exactName": "security-reviewer"},
            {"kind": "toolUse", "tool": "Skill", "contains": "security-audit"},
            {"kind": "command", "matches": "testCommand"},
        ]}]}}}
        self.assertEqual(marker_violations(synthetic), [("x", "s", 0, ["contains", "exactName"]), ("x", "s", 1, [])])

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
                # C6: compare the keys present among tool / contains / exactName, so an exact-name
                # step is mirrored by an exact-name reviewer and a substring step by a substring one.
                expected = {group: [{k: e[k] for k in ("tool", "contains", "exactName") if k in e}
                                    for e in steps[group]["evidence"] if e["kind"] == "toolUse"]
                            for group in ("control", "security") if group in steps}
                self.assertEqual(evidence["reviewers"], expected)
        safe_refactor = [s for s in self.cfg["flows"]["safe-refactor"]["steps"] if s["id"] == "review-result"]
        self.assertEqual(set(safe_refactor[0]["evidence"][0]["reviewers"]), {"control"})

    def test_review_result_markers_resolve(self):  # AC37, C6
        members = [member
                   for flow in self.cfg["flows"].values() for step in flow["steps"]
                   for item in step["evidence"] if item.get("kind") == "reviewResult"
                   for group in item["reviewers"].values() for member in group]
        self.assertTrue(members, "no reviewResult evidence declares reviewers")
        for member in members:
            marker = member.get("exactName") or member.get("contains", "")
            self.assertIn(marker, self._names_for(member.get("tool")),
                          f"reviewer {member} resolves to no known {member.get('tool')} name")


# ---- C6 / D7: the agentic-sdlc-pipeline flow (exact literals from the binding contract) ----
# Every step is pinned as a literal decided by C6, not read back from the file under test. The
# unchanged steps are pinned too, so "unchanged steps keep their current JSON" is checked rather
# than assumed.
PIPE_SPEC = {"id": "spec", "label": "Spec (WHAT)", "evidence": [
    {"kind": "artifact", "role": "spec", "validate": {"mode": "spec", "strict": True}},
    {"kind": "toolUse", "tool": "Workflow", "contains": "spec-plan-draft"},
    {"kind": "toolUse", "tool": "Agent", "contains": "spec-plan-author"}], "stop": "block", "beforeSourceEdit": True}
PIPE_PLAN = {"id": "plan", "label": "Plan (HOW)", "evidence": [
    {"kind": "artifact", "role": "plan", "validate": {"mode": "plan", "strict": True}},
    {"kind": "toolUse", "tool": "Workflow", "contains": "spec-plan-draft"}], "stop": "block", "beforeSourceEdit": True}
PIPE_TESTS = {"id": "tests", "label": "RED to GREEN tests run",
              "evidence": [{"kind": "command", "matches": "testCommand"}], "stop": "block", "beforeSourceEdit": False}
PIPE_BRANCH = {"id": "branch", "label": "Source edits off protected branch", "evidence": [{"kind": "branch"}],
               "stop": "warn", "beforeSourceEdit": False}
PIPE_DISPATCH = {"id": "dispatch", "label": "Mechanism decision (dispatch-strategy)",
                 "evidence": [{"kind": "toolUse", "tool": "Skill", "exactName": "dispatch-strategy"}],
                 "stop": "block", "beforeSourceEdit": True}
PIPE_RED_FIRST = {"id": "red-first", "label": "Test command run before the first production edit",
                  "evidence": [{"kind": "command", "matches": "testCommand"}], "beforeSourceEdit": True}
PIPE_SECURITY = {"id": "security", "label": "Security analysis",
                 "evidence": [{"kind": "toolUse", "tool": "Agent", "exactName": "security-reviewer"}],
                 "stop": "block", "beforeSourceEdit": False}
PIPE_CONTROL = {"id": "control", "label": "Implementation control",
                "evidence": [{"kind": "toolUse", "tool": "Agent", "exactName": "implementation-auditor"}],
                "stop": "block", "beforeSourceEdit": False}
PIPE_REVIEW_RESULT = {"id": "review-result", "label": "Reviewer results returned without error", "evidence": [
    {"kind": "reviewResult", "reviewers": {
        "control": [{"tool": "Agent", "exactName": "implementation-auditor"}],
        "security": [{"tool": "Agent", "exactName": "security-reviewer"}]}}], "stop": "warn", "beforeSourceEdit": False}
PIPE_STEPS = [PIPE_DISPATCH, PIPE_SPEC, PIPE_PLAN, PIPE_RED_FIRST, PIPE_TESTS, PIPE_SECURITY, PIPE_CONTROL,
              PIPE_BRANCH, PIPE_REVIEW_RESULT]

# The three other flows, pinned as literals: C6 says they do not change.
_SKILL_OR_AGENT_SECURITY = [{"kind": "toolUse", "tool": "Skill", "contains": "security-audit"},
                            {"kind": "toolUse", "tool": "Agent", "contains": "security-reviewer"}]
_SKILL_OR_AGENT_CONTROL = [{"kind": "toolUse", "tool": "Skill", "contains": "implementation-control"},
                           {"kind": "toolUse", "tool": "Agent", "contains": "implementation-auditor"}]
_RESULT_CONTROL = [{"tool": "Skill", "contains": "implementation-control"},
                   {"tool": "Agent", "contains": "implementation-auditor"}]
_RESULT_SECURITY = [{"tool": "Skill", "contains": "security-audit"},
                    {"tool": "Agent", "contains": "security-reviewer"}]
_FOCUSED_IMPLEMENT_STEPS = [
    PIPE_SPEC, PIPE_PLAN, PIPE_TESTS,
    {"id": "security", "label": "Security analysis", "evidence": _SKILL_OR_AGENT_SECURITY,
     "stop": "warn", "beforeSourceEdit": False},
    {"id": "control", "label": "Implementation control", "evidence": _SKILL_OR_AGENT_CONTROL,
     "stop": "block", "beforeSourceEdit": False},
    PIPE_BRANCH,
    {"id": "review-result", "label": "Reviewer results returned without error", "evidence": [
        {"kind": "reviewResult", "reviewers": {"control": _RESULT_CONTROL, "security": _RESULT_SECURITY}}],
     "stop": "warn", "beforeSourceEdit": False},
]
OTHER_FLOWS = {
    "root-cause-fix": {"activeWhen": {"skill": "root-cause-fix"}, "steps": _FOCUSED_IMPLEMENT_STEPS},
    "feature-build": {"activeWhen": {"skill": "feature-build"}, "steps": _FOCUSED_IMPLEMENT_STEPS},
    "safe-refactor": {"activeWhen": {"skill": "safe-refactor"}, "steps": [
        {"id": "characterization", "label": "Characterization tests (safety net) run",
         "evidence": [{"kind": "command", "matches": "testCommand"}], "stop": "block", "beforeSourceEdit": True},
        {"id": "control", "label": "Implementation control", "evidence": _SKILL_OR_AGENT_CONTROL,
         "stop": "block", "beforeSourceEdit": False},
        PIPE_BRANCH,
        {"id": "review-result", "label": "Reviewer results returned without error", "evidence": [
            {"kind": "reviewResult", "reviewers": {"control": _RESULT_CONTROL}}],
         "stop": "warn", "beforeSourceEdit": False},
    ]},
}


class TestPipelineFlowContract(unittest.TestCase):  # C6 / D7
    def setUp(self):
        self.flows = json.loads(CONFIG.read_text(encoding="utf-8"))["flows"]
        self.assertIn("agentic-sdlc-pipeline", list(self.flows), "the pipeline flow is missing from the config")
        self.pipe = self.flows["agentic-sdlc-pipeline"]
        self.steps = {s["id"]: s for s in self.pipe["steps"]}

    def _step(self, step_id):
        # Presence first, so a missing step fails by name instead of raising KeyError.
        self.assertIn(step_id, list(self.steps), f"pipeline step '{step_id}' is missing")
        return self.steps[step_id]

    def test_core_step_removed(self):
        self.assertNotIn("core", list(self.steps),
                         "the pipeline never invokes focused skills (D1), so the core-delegation step must go")

    def test_step_order(self):
        self.assertEqual([s["id"] for s in self.pipe["steps"]], [s["id"] for s in PIPE_STEPS])

    def test_activation_unchanged(self):
        self.assertEqual(self.pipe["activeWhen"].get("skill"), "agentic-sdlc-pipeline")

    def test_red_first_step_exact(self):
        step = self._step("red-first")
        self.assertNotIn("stop", step,
                         "red-first must carry no stop key: codex-flow-evidence.mjs would fold it into the "
                         "Codex Stop gate as an exit-0 requirement")
        self.assertEqual(step, PIPE_RED_FIRST)

    def test_dispatch_step_exact_name(self):
        self.assertEqual(self._step("dispatch"), PIPE_DISPATCH)

    def test_security_step_agent_only_exact_name(self):
        self.assertEqual(self._step("security"), PIPE_SECURITY)

    def test_control_step_agent_only_exact_name(self):
        self.assertEqual(self._step("control"), PIPE_CONTROL)

    def test_review_result_mirrors_agent_only_reviewers(self):
        self.assertEqual(self._step("review-result"), PIPE_REVIEW_RESULT)

    def test_unchanged_steps_keep_their_json(self):
        for want in (PIPE_SPEC, PIPE_PLAN, PIPE_TESTS, PIPE_BRANCH):
            with self.subTest(step=want["id"]):
                self.assertEqual(self._step(want["id"]), want)

    def test_whole_pipeline_step_list(self):
        self.assertEqual(self.pipe["steps"], PIPE_STEPS)

    def test_other_flows_unchanged(self):
        for name, want in OTHER_FLOWS.items():
            with self.subTest(flow=name):
                self.assertIn(name, list(self.flows))
                got ={k: v for k, v in self.flows[name].items() if k != "$comment"}
                self.assertEqual(got, want)

    def test_flow_set_unchanged(self):
        self.assertEqual(set(self.flows), {"root-cause-fix", "feature-build", "safe-refactor", "agentic-sdlc-pipeline"})


if __name__ == "__main__":
    unittest.main()
