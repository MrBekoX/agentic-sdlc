"""House portability rules, separate from runtime-specific agent metadata."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

from scripts import check_all

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("skill_harness", REPO / "tests/skills/harness.py")
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


class SharedSkillContractTests(unittest.TestCase):
    def validate(self, description, extra="", name="example-skill"):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / name
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: {description}\n{extra}---\n# Example\n",
                encoding="utf-8",
            )
            errors, warnings = [], []
            check_all.check_skill(skill, errors, warnings)
            other, _ = harness.validate_skill_structure(skill)
            return errors, other

    def test_runtime_only_keys_rejected_by_both_shared_gates(self):
        for key in ("user-invocable", "argument-hint", "model", "disable-model-invocation"):
            with self.subTest(key=key):
                for errors in self.validate("This skill is used when a focused test is requested.", f"{key}: value\n"):
                    self.assertIn(f"bad_frontmatter_key:example-skill:{key}", errors)

    def test_compatibility_remains_a_shared_spec_key(self):
        for errors in self.validate("This skill is used when a focused test is requested.", "compatibility: Requires Python 3\n"):
            self.assertEqual(errors, [])

    def test_imperative_description_is_a_house_error(self):
        for errors in self.validate("Use first when the user asks for a focused test."):
            self.assertIn("imperative_description:example-skill", errors)

    def test_spec_length_limits_are_enforced(self):
        for errors in self.validate("This skill is used when " + "a" * 1024):
            self.assertIn("description_too_long:example-skill", errors)
        for errors in self.validate("This skill is used when a focused test is requested.", name="a" * 65):
            self.assertIn("name_too_long:" + "a" * 65, errors)

    def test_feature_flow_observes_red_before_implementation(self):
        text = (REPO / "skills/feature-build/SKILL.md").read_text(encoding="utf-8").split("## Flow", 1)[1]
        self.assertLess(text.index("**Failing test"), text.index("**Implementation"))

    def test_pipeline_commands_use_python3_and_resolved_runtime_root(self):
        for name in ("SKILL.md", "playbook.md"):
            text = (REPO / "skills/agentic-sdlc-pipeline" / name).read_text(encoding="utf-8")
            self.assertNotRegex(text, r"\bpython\s")
            self.assertNotIn('python3 "${CLAUDE_PLUGIN_ROOT}/scripts/', text)


if __name__ == "__main__":
    unittest.main()
