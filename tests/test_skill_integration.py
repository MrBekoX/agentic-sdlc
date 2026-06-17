"""Integration validation: every cross-reference resolves (test matrix F).

Asserts the wiring between skills/agents/workflows/commands/hooks/scripts is intact:
- golden must_reference entries both APPEAR in the SKILL.md and RESOLVE to a real component
  (e.g. dev-flow -> fix-flow/feature-flow/refactor-flow/test-flow, implementasyon-control ->
  implementation-auditor, spec-plan-draft workflow -> spec-plan-author/critic agents).
- every ${CLAUDE_PLUGIN_ROOT}/<path> referenced in skills/hooks resolves to a real repo file.
- hooks.json is valid JSON and each referenced .mjs exists.
- README / hooks-README claims match the real tree (settings.json reference is gating;
  the .claude-plugin manifest claim is a non-gating warning, reported below).
"""

import importlib.util
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


class TestSkillCrossReferences(unittest.TestCase):
    def setUp(self):
        self.reg = h.registries()
        self.golden = h.load_golden()["skills"]

    def test_every_golden_reference_appears_and_resolves(self):
        failures = {}
        for name in sorted(h.skill_names()):
            if name not in self.golden:
                continue
            errors, _ = h.validate_skill_integration(
                h.SKILLS_DIR / name, self.golden[name], self.reg
            )
            if errors:
                failures[name] = errors
        self.assertEqual(failures, {}, f"cross-reference errors: {failures}")

    def test_dev_flow_delegates_to_four_work_flows(self):
        # The Onion-center contract: dev-flow must reference the four core work-flows it delegates to.
        text = (h.SKILLS_DIR / "dev-flow" / "SKILL.md").read_text(encoding="utf-8")
        for flow in ("fix-flow", "feature-flow", "refactor-flow", "test-flow"):
            self.assertIn(flow, text, f"dev-flow no longer references {flow}")

    def test_dev_flow_forbids_manual_substitutes_for_eval_gates(self):
        text = (h.SKILLS_DIR / "dev-flow" / "SKILL.md").read_text(encoding="utf-8")
        for phrase in (
            "Manual Read/Glob/ls exploration does not replace detect_context.py.",
            "Manual review text does not replace validate_artifacts.py.",
            "Manual TDD/edit/test work does not replace the selected core work-flow Skill call.",
        ):
            self.assertIn(phrase, text)

    def test_implementasyon_control_references_auditor_agent(self):
        text = (h.SKILLS_DIR / "implementasyon-control" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("implementation-auditor", text)
        self.assertIn("implementation-auditor", h.agent_names())


class TestRuntimePaths(unittest.TestCase):
    def test_all_plugin_root_refs_resolve(self):
        errors, _ = h.validate_plugin_root_refs()
        self.assertEqual(errors, [], f"dangling ${{CLAUDE_PLUGIN_ROOT}} refs: {errors}")

    def test_hooks_json_valid_and_scripts_exist(self):
        errors, _ = h.validate_hooks_json()
        self.assertEqual(errors, [], f"hooks.json errors: {errors}")

    def test_workflow_agent_types_resolve(self):
        errors, _ = h.validate_workflow_agent_types(h.registries())
        self.assertEqual(errors, [], f"workflow agentType errors: {errors}")

    def test_spec_plan_workflow_agent_types_are_plugin_qualified(self):
        text = (h.WORKFLOWS_DIR / "spec-plan-draft.js").read_text(encoding="utf-8")
        self.assertIn("agentType:'agentic-sdlc:spec-plan-author'", text)
        self.assertIn("agentType:'agentic-sdlc:spec-plan-critic'", text)
        self.assertNotIn("agentType:'spec-plan-author'", text)
        self.assertNotIn("agentType:'spec-plan-critic'", text)

    def test_spec_plan_workflow_supports_smoke_eval_mode(self):
        text = (h.WORKFLOWS_DIR / "spec-plan-draft.js").read_text(encoding="utf-8")
        self.assertIn("depth === 'smoke'", text)
        self.assertIn("maxRevisionRounds", text)


class TestDocConsistency(unittest.TestCase):
    def test_hooks_readme_does_not_reference_missing_settings_json(self):
        # The hooks are wired in hooks.json; a stale `settings.json` reference is a doc bug.
        errors, _ = h.check_doc_consistency()
        gating = [e for e in errors]
        self.assertEqual(
            gating, [],
            f"doc-consistency errors: {gating}",
        )


if __name__ == "__main__":
    unittest.main()
