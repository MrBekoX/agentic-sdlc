"""AC22 evidence-tracking gate + AC21 change-detectability (T12).

Two acceptance criteria are pinned here:

- AC22 — no *tracked* file may be a per-package evidence path
  (``docs/agentic-sdlc/<slug>/evidence/...`` for a valid, non-reserved ``<slug>``).
  The legacy ``docs/agentic-sdlc/evidence/...`` directory (no slug segment) is
  explicitly *outside* the gate and must never trip it.
- AC21 — a brand-new per-package plan is detectable by the resolver's
  filesystem-scan change-detector, while the package's ``<slug>/evidence/`` never
  appears in git's tracked-file set.

The gate code under test is the module-level ``matcher(path) -> bool`` below. It is
self-contained: the slug rule is borrowed from the resolver (``is_valid_slug``) so the
reserved-slug exclusion stays in lock-step with the rest of the feature.
"""
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path, PurePosixPath


HERE = Path(__file__).resolve().parent
REPO = HERE.parent
RESOLVER = REPO / "scripts" / "resolve_work_package.py"


def _load_resolver():
    spec = importlib.util.spec_from_file_location("resolve_work_package", RESOLVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_RESOLVER = _load_resolver()

# docs/agentic-sdlc/<slug>/evidence/<...> — anchored at the repo root, because the
# gate runs over `git ls-files` paths (repo-relative, forward-slash separated).
AGENTIC_PREFIX = ("docs", "agentic-sdlc")


def matcher(path):
    """True iff ``path`` is a per-package evidence path (AC22).

    Flags ``docs/agentic-sdlc/<slug>/evidence/<...>`` with EXACTLY ONE directory
    level between ``agentic-sdlc`` and ``evidence`` — that level must be a valid,
    non-reserved ``<slug>`` per the resolver's slug rule. The legacy
    ``docs/agentic-sdlc/evidence/...`` (no slug segment) is excluded by construction:
    its first post-prefix segment is the reserved name ``evidence``, which
    ``is_valid_slug`` rejects. A reserved-name slug (e.g. ``spec``) is likewise not a
    valid slug, and two-or-more directory levels before ``evidence`` are not flagged.
    """
    parts = PurePosixPath(str(path)).parts
    if parts[:2] != AGENTIC_PREFIX:
        return False
    rest = parts[2:]
    if len(rest) < 3:  # need <slug>/evidence/<at least one tracked file>
        return False
    slug, subdir = rest[0], rest[1]
    return subdir == "evidence" and _RESOLVER.is_valid_slug(slug)


def _write_per_package(root, slug="x", work_id="x", branch="feature/other"):
    """Write a valid per-package spec+plan under docs/agentic-sdlc/<slug>/."""
    base = root / "docs" / "agentic-sdlc" / slug
    (base / "spec").mkdir(parents=True, exist_ok=True)
    (base / "plan").mkdir(parents=True, exist_ok=True)
    (base / "spec" / f"{work_id}.md").write_text(
        f"---\nwork_id: {work_id}\nstatus: reviewed\n---\n\n# {work_id} Spec\n",
        encoding="utf-8",
    )
    plan = base / "plan" / f"{work_id}.md"
    plan.write_text(
        f"---\nwork_id: {work_id}\nspec: ../spec/{work_id}.md\n"
        f"branch: {branch}\nstatus: in_progress\n---\n\n# {work_id} Plan\n",
        encoding="utf-8",
    )
    return plan


class TestEvidenceTrackingGate(unittest.TestCase):
    """AC22 matcher unit + real-repo integration + legacy exclusion."""

    def test_matcher_flags_per_package_evidence_only(self):
        # A synthetic tracked-file list: only the per-package evidence path is flagged.
        tracked = [
            "docs/agentic-sdlc/myslug/evidence/x.md",      # per-package → flagged
            "docs/agentic-sdlc/evidence/legacy.md",        # legacy (no slug) → NOT flagged
            "docs/agentic-sdlc/spec/evidence/x.md",        # reserved slug → NOT flagged
            "docs/agentic-sdlc/specs/foo.md",              # flat spec → NOT flagged
            "docs/agentic-sdlc/work-x/plan/work-x.md",     # per-package plan → NOT flagged
            "docs/agentic-sdlc/a/b/evidence/x.md",         # two levels deep → NOT flagged
            "scripts/resolve_work_package.py",             # unrelated → NOT flagged
        ]
        flagged = [p for p in tracked if matcher(p)]
        self.assertEqual(flagged, ["docs/agentic-sdlc/myslug/evidence/x.md"])

    def test_real_repo_has_no_tracked_per_package_evidence(self):
        # AC22 integration: the real repo must never track a per-package evidence file.
        proc = subprocess.run(
            ["git", "ls-files"],
            cwd=REPO, capture_output=True, text=True, encoding="utf-8",
        )
        if proc.returncode != 0:
            raise unittest.SkipTest("git unavailable or REPO is not a git repo")
        offenders = [p for p in proc.stdout.splitlines() if p.strip() and matcher(p)]
        self.assertEqual(offenders, [], f"tracked per-package evidence found: {offenders}")

    def test_legacy_evidence_dir_not_flagged(self):
        # AC22 exclusion: the legacy docs/agentic-sdlc/evidence/ file (no slug segment,
        # referenced from docs/release-readiness.md) is outside the gate by construction.
        self.assertFalse(
            matcher("docs/agentic-sdlc/evidence/codex-live-low-strict-2026-06-20.md")
        )
        self.assertFalse(matcher("docs/agentic-sdlc/evidence/legacy.md"))


class TestPerPackageChangeDetectability(unittest.TestCase):
    """AC21 — new per-package plan is fs-detectable while evidence stays untracked."""

    def test_new_per_package_plan_is_fs_detectable(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            git_init = subprocess.run(
                ["git", "init", "-q"], cwd=root, capture_output=True
            )
            if git_init.returncode != 0:
                raise unittest.SkipTest("git unavailable")
            # NOTE: deliberately NO docs/* ignore — same stance as the resolver's
            # untracked-flat test. A per-package plan is invisible to git-status purely
            # via the `-- PLAN_ROOT` pathspec + _is_inside(PLAN_ROOT) filter, so the
            # fs-scan is what makes it detectable (AC21 detect half).
            plan = _write_per_package(root, slug="x", work_id="x", branch="feature/other")

            scanned = {p.resolve() for p in _RESOLVER._changed_plans_from_fs(root)}
            self.assertIn(plan.resolve(), scanned)

            # A non-branch-matching resolve falls through to the changed-plan step and
            # returns the per-package plan (AC5/AC7 rest on this detectability).
            result = _RESOLVER.resolve(root, branch="feature/none")
            self.assertTrue(result.ok, result.errors)
            self.assertEqual(result.source, "changed-plan")
            self.assertEqual(result.plan, plan.resolve())

            # AC21 untracked half: evidence is absent, so no <slug>/evidence/ path is in
            # git's tracked-file set (nothing was added; the spec/plan stay untracked too).
            ls = subprocess.run(
                ["git", "ls-files"],
                cwd=root, capture_output=True, text=True, encoding="utf-8",
            )
            offenders = [p for p in ls.stdout.splitlines() if p.strip() and matcher(p)]
            self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
