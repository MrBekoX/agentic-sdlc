"""Tests for resolve_work_package.py.

The resolver picks the spec/plan pair for implementation-control. It is separate
from validate_artifacts.py: this module tests identity and selection, not content
quality.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from unittest import mock


HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SCRIPT = REPO / "scripts" / "resolve_work_package.py"
FLAT_PLAN_ROOT = "docs/agentic-sdlc/plans"
# `git rev-parse --local-env-vars`: variables that would point a git child at another repository,
# index or config. Dropped so a git call here only reads the repository it is given.
GIT_LOCATION_VARS = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
    "GIT_OBJECT_DIRECTORY", "GIT_DIR", "GIT_WORK_TREE", "GIT_IMPLICIT_WORK_TREE", "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE", "GIT_NO_REPLACE_OBJECTS", "GIT_REPLACE_REF_BASE", "GIT_PREFIX",
    "GIT_SHALLOW_FILE", "GIT_COMMON_DIR",
)


def _git_env():
    env = {name: value for name, value in os.environ.items() if name not in GIT_LOCATION_VARS}
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"})
    return env


def tracked_flat_plans(repo):
    """The flat plans (`docs/agentic-sdlc/plans/*.md`) git tracks in `repo` and the working tree holds.

    Sorted paths, or None when git cannot say (no git on PATH, not a repository, git failed); the
    caller then reads the folder. Read-only: `git --no-optional-locks ls-files` takes no index lock.
    """
    git = shutil.which("git")
    if git is None:
        return None
    try:
        proc = subprocess.run(
            [git, "--no-optional-locks", "-C", str(repo), "ls-files", "-z", "--", FLAT_PLAN_ROOT],
            capture_output=True, env=_git_env(), stdin=subprocess.DEVNULL, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    plans = []
    for name in proc.stdout.decode("utf-8", "surrogateescape").split("\0"):
        rel = PurePosixPath(name)
        if name and rel.parent == PurePosixPath(FLAT_PLAN_ROOT) and rel.suffix == ".md":
            path = Path(repo, *rel.parts)
            if path.is_file():
                plans.append(path)
    return sorted(plans)


def canonical_flat_plans(repo):
    """The plans the canonical-artifact check reads: the tracked ones, or the folder without git."""
    tracked = tracked_flat_plans(repo)
    if tracked is not None:
        return tracked
    plan_root = Path(repo) / FLAT_PLAN_ROOT
    return sorted(plan_root.glob("*.md")) if plan_root.exists() else []


def unresolved_plans(resolver, repo, plans):
    """[(repo-relative path, resolver errors)] for each of `plans` that does not resolve."""
    failures = []
    for plan in plans:
        result = resolver.resolve(repo, plan_path=plan)
        if not result.ok:
            failures.append((plan.relative_to(repo).as_posix(), result.errors))
    return failures


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


def write_per_package_artifacts(
    root,
    work_id="work-x",
    branch="feature/work-x",
    status="in_progress",
    slug=None,
    basename=None,
    spec_link=None,
    spec_work_id=None,
    write_spec=True,
):
    """Write a per-package package at docs/agentic-sdlc/<slug>/{spec,plan}/<basename>.md.

    slug defaults to work_id (BR2 1:1) and basename defaults to work_id (BR16). The
    plan's frontmatter ``spec:`` link defaults to ``../spec/<basename>.md`` (BR5). The
    optional knobs let integrity tests craft mismatches (bad link, cross-package,
    basename!=work_id) without a second helper.
    """
    slug = slug if slug is not None else work_id
    basename = basename if basename is not None else work_id
    spec_work_id = spec_work_id if spec_work_id is not None else work_id
    base = root / "docs" / "agentic-sdlc" / slug
    plan_dir = base / "plan"
    plan_dir.mkdir(parents=True, exist_ok=True)
    spec = base / "spec" / f"{basename}.md"
    if write_spec:
        spec.parent.mkdir(parents=True, exist_ok=True)
        spec.write_text(
            f"""---
work_id: {spec_work_id}
status: reviewed
---

# {basename} Spec
""",
            encoding="utf-8",
        )
    link = spec_link if spec_link is not None else f"../spec/{basename}.md"
    plan = plan_dir / f"{basename}.md"
    plan.write_text(
        f"""---
work_id: {work_id}
spec: {link}
branch: {branch}
status: {status}
---

# {basename} Plan
""",
        encoding="utf-8",
    )
    return spec, plan


def _symlinks_supported():
    try:
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "t"
            target.write_text("x", encoding="utf-8")
            link = Path(d) / "l"
            import os
            os.symlink(target, link)
        return True
    except (OSError, NotImplementedError, AttributeError):
        return False


SYMLINKS_SUPPORTED = _symlinks_supported()


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

    def test_approved_status_resolves(self):
        # `approved` is the approval receipt (see validate_artifacts FRONTMATTER_STATUSES);
        # the resolver accepts the same status set as the validator.
        self.assertIn("approved", self.resolver.STATUSES)
        spec, plan = write_artifacts(self.root, status="approved")
        result = self.resolver.resolve(self.root, plan_path=plan)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.status, "approved")
        self.assertEqual(result.plan, plan.resolve())

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


class TestSlugModel(unittest.TestCase):
    """T1 — slug model + path classification helpers (AC2/AC14/BR2/BR11)."""

    def setUp(self):
        self.resolver = _load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_slug_rejects_reserved_and_unsafe(self):
        bad = [
            "specs", "plans", "evidence", "notes", "spec", "plan",  # reserved (BR11)
            "Work-X",          # uppercase
            "a b",             # space
            "a/b",             # path separator
            "..",              # traversal segment
            'a"b',             # quote
            "a" * 65,          # over length (max 64)
            "-lead",           # must start alphanumeric
            "",                # empty
        ]
        for seg in bad:
            self.assertFalse(self.resolver.is_valid_slug(seg), f"{seg!r} should be invalid")
        for good in ("work-x", "feature-1", "a", "a" * 64):
            self.assertTrue(self.resolver.is_valid_slug(good), f"{good!r} should be valid")

    def test_slug_rejects_a_trailing_newline(self):
        # `$` also matches before a final "\n", so `SLUG_RE.match` let `work-x\n` through. The
        # pattern text is shared with hooks/flow-requirements.json and run_procedure_eval.py
        # (tests/test_procedure_eval.py pins it), so the whole string is matched instead.
        for seg in ("work-x\n", "a\n", "a" * 64 + "\n"):
            with self.subTest(seg=seg):
                self.assertFalse(self.resolver.is_valid_slug(seg), f"{seg!r} should be invalid")
                with self.assertRaises(ValueError):
                    self.resolver.evidence_path(self.root, seg, "work-x")
        self.assertEqual(
            self.resolver.evidence_path(self.root, "work-x", "work-x"),
            self.root.resolve() / "docs" / "agentic-sdlc" / "work-x" / "evidence" / "work-x.md")

    def test_classify_flat_and_per_package(self):
        agentic = self.root / "docs" / "agentic-sdlc"
        flat_plan = agentic / "plans" / "sample-work.md"
        pp_spec = agentic / "work-x" / "spec" / "work-x.md"
        reserved = agentic / "spec" / "spec" / "x.md"

        c_flat = self.resolver.classify_artifact(self.root, flat_plan)
        self.assertEqual(c_flat["layout"], "flat")
        self.assertIsNone(c_flat["slug"])
        self.assertEqual(c_flat["role"], "plan")

        c_pp = self.resolver.classify_artifact(self.root, pp_spec)
        self.assertEqual(c_pp["layout"], "per-package")
        self.assertEqual(c_pp["slug"], "work-x")
        self.assertEqual(c_pp["role"], "spec")
        self.assertEqual(c_pp["basename"], "work-x")

        c_reserved = self.resolver.classify_artifact(self.root, reserved)
        self.assertIsNone(c_reserved["layout"])


class TestDualLayoutDiscovery(unittest.TestCase):
    """T2 — dual-layout discovery, explicit paths, layout/slug fields (AC1/AC2/AC7/AC9/AC23)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.resolver = _load_module()

    def tearDown(self):
        self.tmp.cleanup()

    def test_explicit_per_package_plan_resolves(self):
        spec, plan = write_per_package_artifacts(self.root)
        result = self.resolver.resolve(self.root, plan_path=plan)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.source, "explicit-plan")
        self.assertEqual(result.spec, spec.resolve())
        self.assertEqual(result.plan, plan.resolve())
        self.assertEqual(result.work_id, "work-x")

    def test_explicit_per_package_spec_finds_single_plan(self):
        spec, plan = write_per_package_artifacts(self.root)
        result = self.resolver.resolve(self.root, spec_path=spec)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.source, "explicit-spec")
        self.assertEqual(result.plan, plan.resolve())

    def test_per_package_branch_match(self):
        _spec, plan = write_per_package_artifacts(self.root, branch="feature/active")
        result = self.resolver.resolve(self.root, branch="feature/active")
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.source, "branch")
        self.assertEqual(result.plan, plan.resolve())

    def test_per_package_emits_layout_and_slug(self):
        _spec, plan = write_per_package_artifacts(self.root, work_id="work-x")
        rc, out, err = run_cli("--repo", str(self.root), "--plan", str(plan))
        self.assertEqual(rc, 0, out + err)
        self.assertIn("layout=per-package", out)
        self.assertIn("slug=work-x", out)
        lines = [line for line in out.splitlines() if line]
        self.assertEqual(lines, sorted(lines))

    def test_flat_emits_layout_flat(self):
        _spec, plan = write_artifacts(self.root)
        rc, out, err = run_cli("--repo", str(self.root), "--plan", str(plan))
        self.assertEqual(rc, 0, out + err)
        self.assertIn("layout=flat", out)
        self.assertNotIn("slug=", out)
        # Every other flat field is byte-identical to the pre-change output.
        for expected in (
            "work_package_resolution=passed",
            "resolution_source=explicit-plan",
            "work_id=sample-work",
            "status=in_progress",
        ):
            self.assertIn(expected, out)


class TestPerPackageIntegrity(unittest.TestCase):
    """T3 — per-package integrity + security (AC6/AC8/AC13/AC14/AC18/AC19/AC20/AC25)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.resolver = _load_module()

    def tearDown(self):
        self.tmp.cleanup()

    def test_per_package_spec_traversal_rejected(self):
        # Absolute, out-of-repo spec target → rejected by the traversal guard (AC13).
        _spec, plan = write_per_package_artifacts(self.root, spec_link="/etc/passwd")
        result = self.resolver.resolve(self.root, plan_path=plan)
        self.assertFalse(result.ok)
        self.assertIn("spec_outside_root", result.errors)

    @unittest.skipUnless(SYMLINKS_SUPPORTED, "symlink creation unsupported on this platform")
    def test_per_package_spec_symlink_escape_rejected(self):
        # A <slug>/spec/link.md symlink whose target resolves outside every recognized
        # root must be rejected (AC13 symlink vector), proving _is_inside's symlink
        # resolution — not just literal `..` normalization.
        _spec, plan = write_per_package_artifacts(
            self.root, work_id="link", slug="x", write_spec=False, spec_link="../spec/link.md"
        )
        spec_dir = self.root / "docs" / "agentic-sdlc" / "x" / "spec"
        spec_dir.mkdir(parents=True, exist_ok=True)
        outside = Path(tempfile.mkdtemp())
        try:
            target = outside / "secret.md"
            target.write_text("---\nwork_id: link\nstatus: reviewed\n---\n", encoding="utf-8")
            os.symlink(target, spec_dir / "link.md")
            result = self.resolver.resolve(self.root, plan_path=plan)
            self.assertFalse(result.ok)
            self.assertIn("spec_outside_root", result.errors)
        finally:
            import shutil
            shutil.rmtree(outside, ignore_errors=True)

    def test_flat_plan_into_per_package_rejected(self):
        plans = self.root / "docs" / "agentic-sdlc" / "plans"
        plans.mkdir(parents=True, exist_ok=True)
        plan = plans / "x.md"
        plan.write_text(
            """---
work_id: x
spec: ../work-y/spec/x.md
branch: feature/x
status: in_progress
---

# Flat plan into per-package
""",
            encoding="utf-8",
        )
        result = self.resolver.resolve(self.root, plan_path=plan)
        self.assertFalse(result.ok)
        self.assertIn("layout_class_mismatch", result.errors)

    def test_per_package_plan_into_flat_specs_rejected(self):
        _spec, plan = write_per_package_artifacts(
            self.root, work_id="x", slug="x", write_spec=False, spec_link="../../specs/x.md"
        )
        result = self.resolver.resolve(self.root, plan_path=plan)
        self.assertFalse(result.ok)
        self.assertIn("layout_class_mismatch", result.errors)

    def test_cross_package_spec_link_rejected(self):
        _spec, plan = write_per_package_artifacts(
            self.root, work_id="x", slug="a-pkg", write_spec=False,
            spec_link="../../other-slug/spec/x.md",
        )
        result = self.resolver.resolve(self.root, plan_path=plan)
        self.assertFalse(result.ok)
        self.assertIn("colocation_violation", result.errors)

    def test_per_package_basename_work_id_mismatch_fails(self):
        # x/spec/foo.md + x/plan/foo.md with frontmatter work_id: bar (AC25/BR16).
        _spec, plan = write_per_package_artifacts(
            self.root, work_id="bar", basename="foo", slug="x"
        )
        result = self.resolver.resolve(self.root, plan_path=plan)
        self.assertFalse(result.ok)
        self.assertIn("basename_work_id_mismatch", result.errors)

    def test_flat_basename_mismatch_tolerated(self):
        # Flat specs/foo.md + plans/foo.md with work_id: bar — never failed on basename (AC9).
        specs = self.root / "docs" / "agentic-sdlc" / "specs"
        plans = self.root / "docs" / "agentic-sdlc" / "plans"
        specs.mkdir(parents=True, exist_ok=True)
        plans.mkdir(parents=True, exist_ok=True)
        (specs / "foo.md").write_text(
            "---\nwork_id: bar\nstatus: reviewed\n---\n\n# Spec\n", encoding="utf-8"
        )
        plan = plans / "foo.md"
        plan.write_text(
            """---
work_id: bar
spec: ../specs/foo.md
branch: feature/bar
status: in_progress
---

# Plan
""",
            encoding="utf-8",
        )
        result = self.resolver.resolve(self.root, plan_path=plan)
        self.assertTrue(result.ok, result.errors)
        self.assertNotIn("basename_work_id_mismatch", result.errors)

    def test_explicit_reserved_slug_path_fails(self):
        bad = self.root / "docs" / "agentic-sdlc" / "spec" / "plan" / "x.md"
        result = self.resolver.resolve(self.root, plan_path=bad)
        self.assertFalse(result.ok)
        self.assertIn("bad_slug", result.errors)

    def test_scanned_bad_slug_yields_no_package(self):
        bad_dir = self.root / "docs" / "agentic-sdlc" / "Work-X" / "plan"
        bad_dir.mkdir(parents=True, exist_ok=True)
        (bad_dir / "Work-X.md").write_text(
            "---\nwork_id: Work-X\nspec: ../spec/Work-X.md\nbranch: b\nstatus: draft\n---\n",
            encoding="utf-8",
        )
        self.assertEqual(self.resolver._plan_files(self.root), [])
        result = self.resolver.resolve(self.root, branch="feature/none")
        self.assertFalse(result.ok)
        self.assertIn("no_plan", result.errors)

    def test_malformed_package_lists_both(self):
        write_per_package_artifacts(self.root, work_id="a", slug="x")
        (self.root / "docs" / "agentic-sdlc" / "x" / "spec" / "b.md").write_text(
            "---\nwork_id: b\nstatus: reviewed\n---\n\n# Second spec\n", encoding="utf-8"
        )
        plan = self.root / "docs" / "agentic-sdlc" / "x" / "plan" / "a.md"
        result = self.resolver.resolve(self.root, plan_path=plan)
        self.assertFalse(result.ok)
        self.assertIn("malformed_package", result.errors)
        names = sorted(p.name for p in result.candidates)
        self.assertEqual(names, ["a.md", "b.md"])

    def test_per_package_spec_without_plan(self):
        spec_dir = self.root / "docs" / "agentic-sdlc" / "x" / "spec"
        spec_dir.mkdir(parents=True, exist_ok=True)
        spec = spec_dir / "x.md"
        spec.write_text("---\nwork_id: x\nstatus: reviewed\n---\n\n# Spec only\n", encoding="utf-8")
        result = self.resolver.resolve(self.root, spec_path=spec)
        self.assertFalse(result.ok)
        self.assertIn("no_plan", result.errors)

    def test_empty_per_package_spec_dir_role_absent(self):
        _spec, plan = write_per_package_artifacts(self.root, work_id="x", slug="x", branch="feature/x")
        # An empty <slug>/spec/ contributes no role and must not error or block (AC19).
        (self.root / "docs" / "agentic-sdlc" / "y" / "spec").mkdir(parents=True, exist_ok=True)
        result = self.resolver.resolve(self.root, branch="feature/x")
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.plan, plan.resolve())


class TestPerPackageAmbiguity(unittest.TestCase):
    """T4 — per-selection-step ambiguity + branch/changed disambiguation (AC3/AC4/AC10/BR15)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.resolver = _load_module()

    def tearDown(self):
        self.tmp.cleanup()

    def _two_packages(self):
        _sa, pa = write_per_package_artifacts(self.root, work_id="x", slug="slug-a", branch="feature/a")
        _sb, pb = write_per_package_artifacts(self.root, work_id="x", slug="slug-b", branch="feature/b")
        return pa, pb

    def test_duplicate_work_id_two_per_package_ambiguous(self):
        pa, pb = self._two_packages()
        result = self.resolver.resolve(self.root, branch="feature/none")
        self.assertFalse(result.ok)
        self.assertIn("ambiguous_plan", result.errors)
        candidates = {p.resolve() for p in result.candidates}
        self.assertEqual(candidates, {pa.resolve(), pb.resolve()})

    def test_branch_disambiguates_two_per_package(self):
        pa, _pb = self._two_packages()
        result = self.resolver.resolve(self.root, branch="feature/a")
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.source, "branch")
        self.assertEqual(result.plan, pa.resolve())

    def test_no_timestamp_tiebreak_per_package(self):
        pa, pb = self._two_packages()
        pa.touch()  # newer mtime must NOT win (BR7)
        result = self.resolver.resolve(self.root, branch="feature/none")
        self.assertFalse(result.ok)
        self.assertIn("ambiguous_plan", result.errors)
        self.assertIsNone(result.plan)


class TestChangedPlanFsScan(unittest.TestCase):
    """T5 — filesystem-scan change-detector for per-package plans (DP-1, AC5/AC7/AC10/AC21)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.resolver = _load_module()

    def tearDown(self):
        self.tmp.cleanup()

    def _git_init(self, branch):
        git_init = subprocess.run(["git", "init", "-q"], cwd=self.root, capture_output=True)
        if git_init.returncode != 0:
            raise unittest.SkipTest("git unavailable")
        subprocess.run(
            ["git", "checkout", "-b", branch],
            cwd=self.root, capture_output=True, text=True, encoding="utf-8", check=True,
        )

    def test_changed_plan_detects_new_per_package_via_fs_scan(self):
        # Temp repo deliberately has NO docs/* ignore (same stance as the existing
        # untracked-flat test); a per-package plan is invisible to git-status purely
        # via the `-- PLAN_ROOT` pathspec + _is_inside(PLAN_ROOT) filter.
        self._git_init("feature/none")
        _spec, plan = write_per_package_artifacts(
            self.root, work_id="x", slug="x", branch="feature/other"
        )
        self.assertEqual(self.resolver._changed_plans_from_git(self.root), [])
        result = self.resolver.resolve(self.root, branch="feature/none")
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.source, "changed-plan")
        self.assertEqual(result.plan, plan.resolve())

    def test_fs_scan_ignores_bad_slug_dirs(self):
        bad = self.root / "docs" / "agentic-sdlc" / "Bad Slug" / "plan"
        bad.mkdir(parents=True, exist_ok=True)
        (bad / "x.md").write_text("---\nwork_id: x\n---\n", encoding="utf-8")
        self.assertEqual(self.resolver._changed_plans_from_fs(self.root), [])

    def test_mixed_flat_changed_and_per_package_is_ambiguous(self):
        # Flat plan left UNTRACKED (not committed) so it appears in _changed_plans_from_git;
        # the per-package plan is added by the fs-scan. Union → two co-equal candidates.
        self._git_init("feature/current")
        _fs, flat_plan = write_artifacts(self.root, work_id="flat-x", branch="feature/flat")
        _ps, pp_plan = write_per_package_artifacts(self.root, work_id="pp-x", slug="pp-x", branch="feature/pp")
        result = self.resolver.resolve(self.root, branch="feature/current")
        self.assertFalse(result.ok)
        self.assertIn("ambiguous_plan", result.errors)
        candidates = {p.resolve() for p in result.candidates}
        self.assertEqual(candidates, {flat_plan.resolve(), pp_plan.resolve()})

    def test_two_per_package_no_branch_is_ambiguous(self):
        _sa, pa = write_per_package_artifacts(self.root, work_id="x", slug="slug-a", branch="feature/a")
        _sb, pb = write_per_package_artifacts(self.root, work_id="x", slug="slug-b", branch="feature/b")
        result = self.resolver.resolve(self.root, branch="feature/none")
        self.assertFalse(result.ok)
        self.assertIn("ambiguous_plan", result.errors)
        candidates = {p.resolve() for p in result.candidates}
        self.assertEqual(candidates, {pa.resolve(), pb.resolve()})


class TestEvidence(unittest.TestCase):
    """T6 — evidence ignored by resolution + read-only evidence_path() (AC11/AC12)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.resolver = _load_module()

    def tearDown(self):
        self.tmp.cleanup()

    def test_orphan_evidence_does_not_affect_resolution(self):
        _spec, plan = write_per_package_artifacts(self.root, work_id="x", slug="x", branch="feature/x")
        evidence = self.root / "docs" / "agentic-sdlc" / "x" / "evidence"
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / "x.md").write_text("orphan junk, not an input\n", encoding="utf-8")
        result = self.resolver.resolve(self.root, branch="feature/x")
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.plan, plan.resolve())
        self.assertEqual(result.source, "branch")

    def test_evidence_path_per_package_only(self):
        ep = self.resolver.evidence_path(self.root, "work-x", "work-x")
        expected = self.root / "docs" / "agentic-sdlc" / "work-x" / "evidence" / "work-x.md"
        self.assertEqual(Path(ep).resolve(), expected.resolve())
        for bad_slug in (None, "", "spec", "plans", "evidence", "Work-X", "a/b"):
            with self.assertRaises(ValueError):
                self.resolver.evidence_path(self.root, bad_slug, "work-x")

    def test_evidence_path_is_read_only(self):
        ep = self.resolver.evidence_path(self.root, "work-x", "work-x")
        self.assertFalse(Path(ep).exists())
        self.assertFalse(Path(ep).parent.exists())


def write_bugfix_plan(root, work_id="fix-x", slug=None, branch="fix/x", status="approved",
                      spec="none", flow="bugfix", layout="per-package"):
    """Write a spec-less bugfix plan (design §5.19); `flow=None` leaves the key out."""
    if layout == "flat":
        plan = root / "docs" / "agentic-sdlc" / "plans" / f"{work_id}.md"
    else:
        slug = slug if slug is not None else work_id
        plan = root / "docs" / "agentic-sdlc" / slug / "plan" / f"{work_id}.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---", f"work_id: {work_id}", f"spec: {spec}"]
    if flow is not None:
        lines.append(f"flow: {flow}")
    lines += [f"branch: {branch}", f"status: {status}", "---", "", f"# {work_id} bugfix plan", ""]
    plan.write_bytes("\n".join(lines).encode("utf-8"))
    return plan


class TestBugfixPlans(unittest.TestCase):
    """Spec-less bugfix plans: `spec: none` resolves only together with `flow: bugfix`."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.resolver = _load_module()

    def tearDown(self):
        self.tmp.cleanup()

    def test_resolver_emits_spec_none(self):
        plan = write_bugfix_plan(self.root)
        result = self.resolver.resolve(self.root, plan_path=plan)
        self.assertTrue(result.ok, result.errors)
        self.assertIsNone(result.spec)
        self.assertEqual(result.plan, plan.resolve())
        self.assertEqual((result.work_id, result.branch, result.status), ("fix-x", "fix/x", "approved"))
        rc, out, err = run_cli("--repo", str(self.root), "--plan", str(plan))
        self.assertEqual(rc, 0, out + err)
        for expected in ("spec=none", "work_package_resolution=passed", "layout=per-package",
                         "slug=fix-x", "work_id=fix-x", "resolution_source=explicit-plan"):
            self.assertIn(expected, out.splitlines())
        lines = [line for line in out.splitlines() if line]
        self.assertEqual(lines, sorted(lines))

    def test_flat_bugfix_plan_resolves(self):
        plan = write_bugfix_plan(self.root, layout="flat")
        rc, out, err = run_cli("--repo", str(self.root), "--plan", str(plan))
        self.assertEqual(rc, 0, out + err)
        self.assertIn("spec=none", out.splitlines())
        self.assertIn("layout=flat", out.splitlines())

    def test_bugfix_plan_resolves_by_branch(self):
        plan = write_bugfix_plan(self.root, branch="fix/current")
        result = self.resolver.resolve(self.root, branch="fix/current")
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.source, "branch")
        self.assertEqual(result.plan, plan.resolve())
        self.assertIsNone(result.spec)

    def test_spec_none_requires_flow_bugfix(self):
        for name, flow in (("no flow key", None), ("another flow", "feature"), ("empty flow", "")):
            with self.subTest(case=name):
                plan = write_bugfix_plan(self.root, work_id="w-" + name.replace(" ", "-"), flow=flow)
                result = self.resolver.resolve(self.root, plan_path=plan)
                self.assertFalse(result.ok)
                self.assertIn("spec_none_requires_flow_bugfix", result.errors)
                rc, out, err = run_cli("--repo", str(self.root), "--plan", str(plan))
                self.assertEqual(rc, 1, out + err)
                self.assertIn("error=spec_none_requires_flow_bugfix", out.splitlines())
                self.assertIn("work_package_resolution=failed", out.splitlines())
                self.assertEqual(err, "")

    def test_flow_bugfix_with_a_spec_resolves_like_any_plan(self):
        spec, plan = write_per_package_artifacts(self.root, work_id="fix-y")
        text = plan.read_text(encoding="utf-8").replace("status: in_progress\n", "status: in_progress\nflow: bugfix\n")
        plan.write_bytes(text.encode("utf-8"))
        result = self.resolver.resolve(self.root, plan_path=plan)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.spec, spec.resolve())

    def test_explicit_spec_never_pairs_with_a_bugfix_plan(self):
        # `spec: none` is a keyword, not a relative path: `_plan_spec_path` returns None rather
        # than `<plan dir>/none`. The pairing result below holds either way (no spec path can equal
        # `<plan dir>/none`), so the None is what pins the keyword; the pairing guards against
        # `none` ever becoming a wildcard that matches any spec.
        spec, plan = write_per_package_artifacts(self.root, work_id="feat-z")
        bugfix = write_bugfix_plan(self.root, work_id="fix-z")
        meta, errors = self.resolver._parse_frontmatter(bugfix)
        self.assertEqual(errors, [])
        self.assertIsNone(self.resolver._plan_spec_path(self.root, bugfix.resolve(), meta))
        result = self.resolver.resolve(self.root, spec_path=spec)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.plan, plan.resolve())

    def test_spec_none_plan_in_a_package_with_a_spec_fails(self):
        # A plan cannot opt out of the spec its own package holds by declaring `spec: none`; the
        # validator refuses a spec given for such a plan with the same code.
        spec, plan = write_per_package_artifacts(self.root, work_id="feat-x", branch="feat/x")
        self.assertEqual(write_bugfix_plan(self.root, work_id="feat-x", branch="feat/x"), plan)
        for name, kwargs in (("explicit plan", {"plan_path": plan}), ("branch", {"branch": "feat/x"})):
            with self.subTest(source=name):
                result = self.resolver.resolve(self.root, **kwargs)
                self.assertFalse(result.ok)
                self.assertIn("spec_none_with_spec", result.errors)
        rc, out, err = run_cli("--repo", str(self.root), "--plan", str(plan))
        self.assertEqual(rc, 1, out + err)
        self.assertIn("error=spec_none_with_spec", out.splitlines())
        self.assertIn("work_package_resolution=failed", out.splitlines())
        # Any spec file in the package counts, not only one named like the plan.
        other = write_bugfix_plan(self.root, work_id="fix-y", slug="pkg-y")
        old_spec = self.root / "docs" / "agentic-sdlc" / "pkg-y" / "spec" / "old.md"
        old_spec.parent.mkdir(parents=True)
        old_spec.write_bytes(b"---\nwork_id: old\nstatus: approved\n---\n")
        result = self.resolver.resolve(self.root, plan_path=other)
        self.assertIn("spec_none_with_spec", result.errors)
        # A flat plan is never paired by name, so flat specs leave a flat bugfix plan alone.
        write_artifacts(self.root, work_id="fix-flat")
        flat = write_bugfix_plan(self.root, work_id="fix-flat", layout="flat")
        result = self.resolver.resolve(self.root, plan_path=flat)
        self.assertTrue(result.ok, result.errors)
        self.assertIsNone(result.spec)

    def test_frontmatter_delimiters_are_whole_lines(self):
        # The block ends only at a line that is `---` (trailing spaces aside), as the validator
        # reads it. A `----` line ended the block here while the validator read on, so the two
        # tools judged different keys; it is now an invalid line in both.
        spec, plan = write_per_package_artifacts(self.root, work_id="feat-x", branch="feat/x")
        text = plan.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nwork_id: feat-x\nspec: ../spec/feat-x.md\nbranch: feat/x\n"
                                        "status: in_progress\n---\n"), text)
        cases = (
            ("---- line, then keys", text.replace("status: in_progress\n---\n",
                                                  "status: in_progress\n----\nspec: none\nflow: bugfix\n---\n"),
             "plan_invalid_frontmatter_line:6"),
            # The line number is the file's own (it was one too high).
            ("colon-less line", text.replace("branch: feat/x\n", "branch: feat/x\nnotes\n"),
             "plan_invalid_frontmatter_line:5"),
            ("indented closer", text.replace("in_progress\n---\n", "in_progress\n  ---\n"),
             "plan_missing_frontmatter_end"),
            ("indented opener", "  " + text, "plan_missing_frontmatter"),
        )
        for name, body, error in cases:
            with self.subTest(case=name):
                plan.write_bytes(body.encode("utf-8"))
                result = self.resolver.resolve(self.root, plan_path=plan)
                self.assertFalse(result.ok, name)
                self.assertIn(error, result.errors)
        plan.write_bytes(text.replace("---\n", "--- \n").encode("utf-8"))
        result = self.resolver.resolve(self.root, plan_path=plan)
        self.assertTrue(result.ok, result.errors)


class TestRepoWorkPackageArtifacts(unittest.TestCase):
    def test_canonical_work_package_artifacts_are_well_formed(self):
        # The canonical plans are the ones git tracks, the set CI checks out. Dogfooding specs/plans
        # live under the gitignored docs/agentic-sdlc/, so a local untracked draft is not part of the
        # shipped gate and a clean clone has none (skip there). Without git the folder is read.
        resolver = _load_module()
        plans = canonical_flat_plans(REPO)
        if not plans:
            self.skipTest("no tracked flat plans (docs/agentic-sdlc/ is gitignored; a clean clone has none)")
        self.assertEqual(unresolved_plans(resolver, REPO, plans), [])


def _write_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class TestCanonicalPlanSelection(unittest.TestCase):
    """The canonical-artifact check reads the plans git tracks, as CI sees them, not every local file."""

    MALFORMED = b"# A plan without frontmatter\n"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.resolver = _load_module()
        self.plans = self.root / "docs" / "agentic-sdlc" / "plans"

    def tearDown(self):
        self.tmp.cleanup()

    def _git(self, *args):
        proc = subprocess.run(
            [shutil.which("git"), "-C", str(self.root), *args], capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=_git_env(), stdin=subprocess.DEVNULL, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_untracked_plan_is_ignored_and_tracked_malformed_plan_fails(self):
        self._git("init", "-q")
        spec, good = write_artifacts(self.root, work_id="good-work")
        tracked_bad = _write_bytes(self.plans / "tracked-bad.md", self.MALFORMED)
        untracked = _write_bytes(self.plans / "untracked-draft.md", self.MALFORMED)
        nested = _write_bytes(self.plans / "archive" / "old.md", self.MALFORMED)
        # -f: a global excludes file must not decide what this fixture tracks.
        self._git("add", "-f", "--", *(p.relative_to(self.root).as_posix()
                                         for p in (spec, good, tracked_bad, nested)))
        # The folder glob (the check's old input) sees the untracked draft; git does not.
        self.assertIn(untracked, sorted(self.plans.glob("*.md")))
        plans = canonical_flat_plans(self.root)
        self.assertEqual(plans, [good, tracked_bad])
        failures = unresolved_plans(self.resolver, self.root, plans)
        self.assertEqual([name for name, _errors in failures], ["docs/agentic-sdlc/plans/tracked-bad.md"])
        self.assertIn("plan_missing_frontmatter", failures[0][1])

    def test_without_git_the_folder_is_read(self):
        _spec, good = write_artifacts(self.root, work_id="good-work")
        draft = _write_bytes(self.plans / "untracked-draft.md", self.MALFORMED)
        expected = sorted([good, draft])
        with self.subTest(case="no git on PATH"), mock.patch.object(shutil, "which", return_value=None):
            self.assertIsNone(tracked_flat_plans(self.root))
            self.assertEqual(canonical_flat_plans(self.root), expected)

        def failing_git(argv, **kwargs):
            # Fail closed: anything but the expected ls-files call is a test bug, never a real spawn.
            if argv[0] != "/fake/git" or "ls-files" not in argv:
                raise AssertionError("unexpected subprocess: %r" % (argv,))
            return subprocess.CompletedProcess(argv, 128, b"", b"fatal: not a git repository")

        with self.subTest(case="git cannot list"), \
                mock.patch.object(shutil, "which", return_value="/fake/git"), \
                mock.patch.object(subprocess, "run", failing_git):
            self.assertIsNone(tracked_flat_plans(self.root))
            self.assertEqual(canonical_flat_plans(self.root), expected)
        self.assertEqual([name for name, _errors in unresolved_plans(self.resolver, self.root, expected)],
                         ["docs/agentic-sdlc/plans/untracked-draft.md"])


if __name__ == "__main__":
    unittest.main()
