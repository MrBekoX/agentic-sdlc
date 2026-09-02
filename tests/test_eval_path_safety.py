import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.eval_safety import require_link_free_tree, require_slug, resolve_under
from scripts import run_codex_trigger_eval, run_glm_trigger_eval, run_trigger_eval
from scripts import run_procedure_eval


class TestEvalPathSafety(unittest.TestCase):
    def test_slug_rejects_parent_and_separator_forms(self):
        for value in ("../outside", "a/b", r"a\b", "C:escape", "_hidden"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                require_slug(value, "case id")

    def test_resolve_under_rejects_absolute_and_parent_paths(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            for value in ("../outside", Path(td).anchor + "outside"):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    resolve_under(base, value, "fixture")

    def test_procedure_eval_rejects_traversing_case_and_fixture(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for case in (
                {"id": "../outside", "prompt": "x"},
                {"id": "safe-case", "prompt": "x", "fixture_dir": "../outside"},
                {"id": "safe-case", "prompt": "x", "required_artifacts": ["../outside"]},
            ):
                path = root / "eval.json"
                path.write_text(json.dumps({"cases": [case]}), encoding="utf-8")
                with self.subTest(case=case), self.assertRaises(ValueError):
                    run_procedure_eval.load_eval(path)

    def test_all_trigger_readers_reject_unsafe_frontmatter_name(self):
        with tempfile.TemporaryDirectory() as td:
            skill = Path(td)
            (skill / "SKILL.md").write_text(
                "---\nname: ../outside\ndescription: unsafe\n---\n", encoding="utf-8"
            )
            for reader in (
                run_trigger_eval.read_skill,
                run_codex_trigger_eval.read_skill,
                run_glm_trigger_eval.read_skill,
            ):
                with self.subTest(reader=reader.__module__), self.assertRaises(ValueError):
                    reader(skill)

    def test_fixture_tree_rejects_nested_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = root / "fixture"
            outside = root / "outside.txt"
            fixture.mkdir()
            outside.write_text("private local data", encoding="utf-8")
            link = fixture / "nested-link"
            try:
                link.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            with self.assertRaisesRegex(ValueError, "link/reparse point"):
                require_link_free_tree(fixture, "fixture_dir")

    def test_procedure_copy_rejects_nested_fixture_symlink(self):
        with tempfile.TemporaryDirectory() as repo_td, tempfile.TemporaryDirectory() as work_td:
            repo = Path(repo_td)
            fixture = repo / "tests" / "fixture"
            outside = repo / "outside.txt"
            fixture.mkdir(parents=True)
            outside.write_text("private local data", encoding="utf-8")
            try:
                (fixture / "nested-link").symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            case = {"id": "safe-case", "fixture_dir": "tests/fixture"}
            with mock.patch.object(run_procedure_eval, "REPO", repo):
                with self.assertRaisesRegex(ValueError, "link/reparse point"):
                    run_procedure_eval.copy_fixture(case, Path(work_td))


if __name__ == "__main__":
    unittest.main()
