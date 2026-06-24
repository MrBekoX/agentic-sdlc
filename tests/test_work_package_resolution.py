"""Tests for resolve_work_package.py.

The resolver picks the spec/plan pair for implementasyon-control. It is separate
from validate_artifacts.py: this module tests identity and selection, not content
quality.
"""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SCRIPT = REPO / "scripts" / "resolve_work_package.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("resolve_work_package", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_cli(*args):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True, encoding="utf-8",
    )
    return proc.returncode, proc.stdout, proc.stderr


def write_artifacts(root, work_id="sample-work", branch="feature/sample", status="in_progress"):
    specs = root / "docs" / "agentic-sdlc" / "specs"
    plans = root / "docs" / "agentic-sdlc" / "plans"
    specs.mkdir(parents=True, exist_ok=True)
    plans.mkdir(parents=True, exist_ok=True)
    spec = specs / f"{work_id}.md"
    plan = plans / f"{work_id}.md"
    spec.write_text(
        f"""---
work_id: {work_id}
status: reviewed
---

# {work_id} Spec
""",
        encoding="utf-8",
    )
    plan.write_text(
        f"""---
work_id: {work_id}
spec: ../specs/{work_id}.md
branch: {branch}
status: {status}
---

# {work_id} Plan
""",
        encoding="utf-8",
    )
    return spec, plan


class TestWorkPackageResolution(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.resolver = _load_module()

    def tearDown(self):
        self.tmp.cleanup()

    def test_explicit_plan_resolves_relative_spec(self):
        spec, plan = write_artifacts(self.root)
        result = self.resolver.resolve(self.root, plan_path=plan)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.source, "explicit-plan")
        self.assertEqual(result.spec, spec.resolve())
        self.assertEqual(result.plan, plan.resolve())
        self.assertEqual(result.work_id, "sample-work")

    def test_explicit_spec_finds_single_referencing_plan(self):
        spec, plan = write_artifacts(self.root)
        result = self.resolver.resolve(self.root, spec_path=spec)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.source, "explicit-spec")
        self.assertEqual(result.plan, plan.resolve())

    def test_explicit_spec_fails_when_multiple_plans_reference_it(self):
        spec, _plan = write_artifacts(self.root, work_id="shared", branch="feature/a")
        other = self.root / "docs" / "agentic-sdlc" / "plans" / "shared-copy.md"
        other.write_text(
            """---
work_id: shared
spec: ../specs/shared.md
branch: feature/b
status: in_progress
---

# Shared copy
""",
            encoding="utf-8",
        )
        result = self.resolver.resolve(self.root, spec_path=spec)
        self.assertFalse(result.ok)
        self.assertIn("ambiguous_plan", result.errors)
        self.assertEqual(len(result.candidates), 2)

    def test_branch_match_resolves_single_plan(self):
        _spec, plan = write_artifacts(self.root, branch="feature/current")
        result = self.resolver.resolve(self.root, branch="feature/current")
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.source, "branch")
        self.assertEqual(result.plan, plan.resolve())

    def test_branch_match_fails_when_ambiguous(self):
        write_artifacts(self.root, work_id="a", branch="feature/current")
        write_artifacts(self.root, work_id="b", branch="feature/current")
        result = self.resolver.resolve(self.root, branch="feature/current")
        self.assertFalse(result.ok)
        self.assertIn("ambiguous_plan", result.errors)
        self.assertEqual(len(result.candidates), 2)

    def test_changed_plan_fallback_resolves_single_plan(self):
        _spec, plan = write_artifacts(self.root, branch="feature/other")
        result = self.resolver.resolve(
            self.root,
            branch="feature/current",
            changed_plans=[plan],
        )
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.source, "changed-plan")
        self.assertEqual(result.plan, plan.resolve())

    def test_missing_referenced_spec_fails(self):
        _spec, plan = write_artifacts(self.root)
        (self.root / "docs" / "agentic-sdlc" / "specs" / "sample-work.md").unlink()
        result = self.resolver.resolve(self.root, plan_path=plan)
        self.assertFalse(result.ok)
        self.assertIn("spec_not_found", result.errors)

    def test_work_id_mismatch_fails(self):
        _spec, plan = write_artifacts(self.root)
        spec = self.root / "docs" / "agentic-sdlc" / "specs" / "sample-work.md"
        spec.write_text(
            """---
work_id: different-work
status: reviewed
---

# Mismatch Spec
""",
            encoding="utf-8",
        )
        result = self.resolver.resolve(self.root, plan_path=plan)
        self.assertFalse(result.ok)
        self.assertIn("work_id_mismatch", result.errors)

    def test_invalid_status_fails(self):
        _spec, plan = write_artifacts(self.root, status="almost_done")
        result = self.resolver.resolve(self.root, plan_path=plan)
        self.assertFalse(result.ok)
        self.assertIn("plan_invalid_status", result.errors)

    def test_invalid_spec_status_fails(self):
        _spec, plan = write_artifacts(self.root)
        spec = self.root / "docs" / "agentic-sdlc" / "specs" / "sample-work.md"
        spec.write_text(
            """---
work_id: sample-work
status: maybe
---

# Bad Status Spec
""",
            encoding="utf-8",
        )
        result = self.resolver.resolve(self.root, plan_path=plan)
        self.assertFalse(result.ok)
        self.assertIn("spec_invalid_status", result.errors)

    def test_plan_spec_path_traversal_fails(self):
        _spec, plan = write_artifacts(self.root)
        plan.write_text(
            """---
work_id: sample-work
spec: ../../outside.md
branch: feature/sample
status: in_progress
---

# Bad Plan
""",
            encoding="utf-8",
        )
        result = self.resolver.resolve(self.root, plan_path=plan)
        self.assertFalse(result.ok)
        self.assertIn("spec_outside_root", result.errors)

    def test_no_timestamp_fallback(self):
        _spec_a, plan_a = write_artifacts(self.root, work_id="old", branch="feature/old")
        _spec_b, _plan_b = write_artifacts(self.root, work_id="new", branch="feature/new")
        plan_a.touch()
        result = self.resolver.resolve(self.root, branch="feature/current")
        self.assertFalse(result.ok)
        self.assertIn("no_plan", result.errors)
        self.assertEqual(result.plan, None)

    def test_git_status_changed_plan_fallback_resolves_untracked_plan(self):
        git_init = subprocess.run(["git", "init", "-q"], cwd=self.root, capture_output=True)
        if git_init.returncode != 0:
            raise unittest.SkipTest("git unavailable")
        subprocess.run(
            ["git", "checkout", "-b", "feature/current"],
            cwd=self.root,
            capture_output=True,
            text=True, encoding="utf-8",
            check=True,
        )
        _spec, plan = write_artifacts(self.root, work_id="changed", branch="feature/other")
        result = self.resolver.resolve(self.root, branch="feature/current")
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.source, "changed-plan")
        self.assertEqual(result.plan, plan.resolve())

    def test_cli_emits_stable_key_value_output(self):
        _spec, plan = write_artifacts(self.root)
        rc, out, err = run_cli("--repo", str(self.root), "--plan", str(plan))
        self.assertEqual(rc, 0, out + err)
        self.assertIn("work_package_resolution=passed", out)
        self.assertIn("resolution_source=explicit-plan", out)
        lines = [line for line in out.splitlines() if line]
        self.assertEqual(lines, sorted(lines))


class TestRepoWorkPackageArtifacts(unittest.TestCase):
    def test_canonical_work_package_artifacts_are_well_formed(self):
        resolver = _load_module()
        plan_root = REPO / "docs" / "agentic-sdlc" / "plans"
        plans = sorted(plan_root.glob("*.md")) if plan_root.exists() else []
        self.assertGreaterEqual(len(plans), 1, "expected at least one canonical dogfooding plan")
        for plan in plans:
            result = resolver.resolve(REPO, plan_path=plan)
            self.assertTrue(result.ok, f"{plan.relative_to(REPO)}: {result.errors}")


if __name__ == "__main__":
    unittest.main()
