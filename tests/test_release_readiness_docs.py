import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


class TestReleaseReadinessDocs(unittest.TestCase):
    def test_release_readiness_names_scope_gates_and_limitations(self):
        text = (REPO / "docs" / "release-readiness.md").read_text(encoding="utf-8")

        for required in (
            "Claude Code",
            "Codex",
            "python3 scripts/bump_version.py --check",
            "python3 scripts/check_all.py",
            "python3 tests/skills/harness.py",
            "python3 -m unittest discover -s tests -v",
            "run_routing_eval.py",
            "--reasoning-effort high",
            "run_procedure_eval.py",
            "secret",
            "Known Limitations",
            "Release Verdict Template",
        ):
            self.assertIn(required, text)

    def test_documented_script_count_matches_repo(self):
        scripts = sorted((REPO / "scripts").glob("*.py"))
        expected = f"scripts/           {len(scripts)} Python helpers"
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn(expected, readme)

        plugin_readme = (REPO / "docs" / "plugin-readme.md").read_text(encoding="utf-8")
        self.assertIn(f"## 11. Deterministic scripts ({len(scripts)})", plugin_readme)


if __name__ == "__main__":
    unittest.main()
