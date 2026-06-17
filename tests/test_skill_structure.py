"""Structure validation for every skill + agent (test matrix A).

Drives tests/skills/harness.py (loaded by path, cwd-independent — same convention as
test_detect_context.py / test_validate_artifacts.py). Stdlib unittest only.

What this asserts: each SKILL.md has valid frontmatter, name == directory (kebab-case),
a present non-trivial description with no angle brackets, only allowed frontmatter keys;
each agent contract has name == filename and a description. Body-length and thin-description
issues are surfaced as harness warnings (non-gating), printed here for visibility.
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


class TestSkillStructure(unittest.TestCase):
    def test_skills_dir_exists_and_nonempty(self):
        self.assertTrue(h.SKILLS_DIR.is_dir(), "skills/ directory missing")
        self.assertGreaterEqual(len(h.skill_names()), 1)

    def test_every_skill_structure_has_no_errors(self):
        failures = {}
        for name in sorted(h.skill_names()):
            errors, _warnings = h.validate_skill_structure(h.SKILLS_DIR / name)
            if errors:
                failures[name] = errors
        self.assertEqual(failures, {}, f"skill structure errors: {failures}")

    def test_every_skill_name_matches_directory(self):
        for name in sorted(h.skill_names()):
            sk = h.SKILLS_DIR / name / "SKILL.md"
            fm, _ = h.split_frontmatter(sk.read_text(encoding="utf-8"))
            self.assertEqual(h.frontmatter_value(fm, "name"), name)

    def test_every_skill_frontmatter_key_is_allowed(self):
        for name in sorted(h.skill_names()):
            sk = h.SKILLS_DIR / name / "SKILL.md"
            fm, _ = h.split_frontmatter(sk.read_text(encoding="utf-8"))
            for key in h.frontmatter_keys(fm):
                self.assertIn(
                    key, h.ALLOWED_SKILL_KEYS,
                    f"{name}: disallowed frontmatter key '{key}'",
                )

    def test_every_skill_description_present_no_angle_brackets(self):
        for name in sorted(h.skill_names()):
            sk = h.SKILLS_DIR / name / "SKILL.md"
            fm, _ = h.split_frontmatter(sk.read_text(encoding="utf-8"))
            desc = h.frontmatter_value(fm, "description")
            self.assertTrue(desc, f"{name}: empty description")
            self.assertNotIn("<", desc, f"{name}: angle bracket in description")
            self.assertNotIn(">", desc, f"{name}: angle bracket in description")


class TestAgentStructure(unittest.TestCase):
    def test_every_agent_structure_has_no_errors(self):
        failures = {}
        for ap in sorted(h.AGENTS_DIR.glob("*.md")):
            errors, _warnings = h.validate_agent_structure(ap)
            if errors:
                failures[ap.stem] = errors
        self.assertEqual(failures, {}, f"agent structure errors: {failures}")

    def test_expected_agents_present(self):
        expected = {
            "code-reviewer", "context-analyst", "debugger", "implementation-auditor",
            "security-reviewer", "software-architect", "spec-plan-author",
            "spec-plan-critic", "test-engineer",
        }
        self.assertEqual(expected, h.agent_names())


if __name__ == "__main__":
    unittest.main()
