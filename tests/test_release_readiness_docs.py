import unittest
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


class TestReleaseReadinessDocs(unittest.TestCase):
    def test_current_release_evidence_is_visible_and_linked(self):
        version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
        evidence = REPO / "docs" / f"release-evidence-{version}.md"
        self.assertTrue(evidence.is_file(), "current release has no public evidence summary")
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", str(evidence)], cwd=REPO, capture_output=True
        )
        self.assertNotEqual(ignored.returncode, 0, "current release evidence is ignored")
        release = (REPO / "docs/release-readiness.md").read_text(encoding="utf-8")
        self.assertIn(evidence.name, release)

    def test_current_release_guidance_keeps_verified_runtime_and_eval_scope(self):
        text = (REPO / "docs/release-readiness.md").read_text(encoding="utf-8")
        current_limits = text.split("## Known Limitations", 1)[1].split("\n## ", 1)[0]
        self.assertNotIn("re-probe is pending", current_limits)
        self.assertNotIn("Current documented CLI is **0.153.4**", current_limits)
        for required in ("0.154.0", "2.1.269", "--runs 3", "--threshold 1.0", "claude-sonnet-5"):
            self.assertIn(required, text)
        self.assertIn("both procedure cases", text)

    def test_ci_uses_the_repository_python3_entrypoint(self):
        text = (REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertNotIn("run: python ", text)
        for command in (
            "python3 scripts/bump_version.py --release-check",
            "python3 scripts/check_all.py",
            "python3 tests/skills/harness.py",
            "python3 -m unittest discover -s tests -v",
        ):
            self.assertIn(command, text)

    def test_release_readiness_names_scope_gates_and_limitations(self):
        text = (REPO / "docs" / "release-readiness.md").read_text(encoding="utf-8")
        version = (REPO / "VERSION").read_text(encoding="utf-8").strip()

        for required in (
            "Claude Code",
            "Codex",
            "python3 scripts/bump_version.py --check",
            "python3 scripts/check_all.py",
            "python3 tests/skills/harness.py",
            "python3 -m unittest discover -s tests -v",
            "run_routing_eval.py",
            "--reasoning-effort low",
            "run_procedure_eval.py",
            "secret",
            "Known Limitations",
            "Codex wires native blocking `PreToolUse` guards",
            "Historical evidence — 2026-06-20 Codex 0.3.0 live low smoke",
            f"not live evidence for the current `{version}` worktree",
            "docs/agentic-sdlc/evidence/codex-live-low-strict-2026-06-20.md",
            "gpt-5.3-codex-spark",
            "model_reasoning_effort=\"low\"",
            "RED->GREEN",
            "`Overall Status: PASS` for Implementation Control",
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

    def test_linked_codex_live_evidence_is_release_visible(self):
        target = REPO / "docs/agentic-sdlc/evidence/codex-live-low-strict-2026-06-20.md"
        self.assertTrue(target.is_file())
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", str(target)], cwd=REPO, capture_output=True
        )
        self.assertNotEqual(ignored.returncode, 0, "release evidence is still git-ignored")
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(target.relative_to(REPO))],
            cwd=REPO,
            capture_output=True,
        )
        self.assertEqual(tracked.returncode, 0, "release evidence is not present in the Git index")


if __name__ == "__main__":
    unittest.main()
