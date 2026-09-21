"""Meta-tests for the byte locks themselves.

A lock whose expected value is re-read from the moving baseline is not a lock. Seven
assertions in this suite used to compare a working-tree file against `git show HEAD:<path>`.
On a clean checkout the working tree IS HEAD, so the content half reduced to
`content == content`; the assertion could only fire in the window between an uncommitted edit
and its commit, and it re-baselined silently once the change landed.

That is not hypothetical. Commit c173b99 changed `hooks/flow-step-guard.mjs` and
`hooks/completion-claim-guard.mjs` - both locked - and in the SAME commit added a
string-replacement hatch to neutralise the lock it had just tripped. Since then the replaced
string occurs nowhere, so the hatch is a permanent no-op and the lock points at whatever the
files now contain.

`.github/workflows/ci.yml` checks out and runs nothing that writes into the tree before
`unittest discover`, so in CI those assertions were in the always-passing state.

The tests here pin three properties rather than any particular file:

  1. No live test resolves an expected value from `git show HEAD:`.
  2. Every locked path's expected value is a 64-hex literal that appears verbatim in the test
     source, so it cannot be recomputed at runtime - which is how the tautology gets back in.
  3. A demonstration, in a scratch repository, of exactly what the old shape failed to catch.
"""

import hashlib
import importlib.util
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "tests"
GIT = shutil.which("git")
SELF = Path(__file__).name

HEX64 = re.compile(r"\b[0-9a-f]{64}\b")

# The suites that carry lock maps. Named rather than discovered: a lock that moves to a new
# file should be a conscious edit here, not something this meta-test silently stops covering.
LOCK_SUITES = (
    "test_codex_flow_order_guard.py",
    "test_codex_flow_step_guard.py",
    "test_codex_completion_claim_guard.py",
    "test_codex_write_guard.py",
)


def _load(name):
    path = TESTS / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _lock_digests(mod):
    """Every {relative path: sha256} map a lock suite exposes, merged."""
    merged = {}
    for attr in dir(mod):
        if not attr.isupper():
            continue
        value = getattr(mod, attr)
        if isinstance(value, dict) and value and all(
            isinstance(k, str) and isinstance(v, str) and HEX64.fullmatch(v)
            for k, v in value.items()
        ):
            merged.update(value)
    return merged


def _normalized_digest(rel):
    payload = (REPO / rel).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(payload).hexdigest()


class TestNoLockReadsItsExpectedValueFromHead(unittest.TestCase):
    def test_no_live_test_resolves_content_from_git_show(self):
        # `git show HEAD:<path>` as the EXPECTED side of a comparison is the defect. Within
        # the helper, the check is broad - ANY use of `_git_show` is reported, not just one in
        # an assertion - because the helper existed for exactly one purpose.
        #
        # What it does NOT catch, stated rather than implied: a HEAD-relative comparison
        # written inline, under a different helper name, or via GitPython. This pins the shape
        # that was actually here; it is not a proof that no such comparison can return.
        offenders = []
        for path in sorted(TESTS.glob("test_*.py")):
            if path.name == SELF:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "_git_show" in line and not line.lstrip().startswith("#"):
                    offenders.append("%s:%d" % (path.name, number))
        self.assertEqual(
            offenders, [],
            "these lines resolve an expected value from the moving HEAD, so they cannot fail "
            "on a committed change: " + ", ".join(offenders),
        )


class TestEveryLockedPathIsPinnedByALiteral(unittest.TestCase):
    def test_lock_suites_expose_digest_maps(self):
        missing = [name for name in LOCK_SUITES if not _lock_digests(_load(name))]
        self.assertEqual(
            missing, [],
            "these suites claim to lock files but expose no {path: sha256} map, so whatever "
            "they compare against is derived rather than pinned: " + ", ".join(missing),
        )

    def test_each_digest_is_a_literal_in_the_source_and_matches_today(self):
        # A digest COMPUTED at runtime is the tautology wearing a hash. Requiring the literal
        # in the source is what forces a change to a locked file to show up in review.
        for name in LOCK_SUITES:
            source = (TESTS / name).read_text(encoding="utf-8")
            for rel, want in sorted(_lock_digests(_load(name)).items()):
                with self.subTest(suite=name, path=rel):
                    self.assertIn(want, source,
                                  "%s: the expected digest for %s is not a literal in the "
                                  "test source" % (name, rel))
                    self.assertTrue((REPO / rel).exists(), "%s: locked file is missing" % rel)
                    self.assertEqual(_normalized_digest(rel), want,
                                     "%s: locked file changed without a digest bump" % rel)


@unittest.skipIf(GIT is None, "git not available - the demonstration needs a scratch repo")
class TestTheHeadRelativeShapeCannotDetectACommittedChange(unittest.TestCase):
    def test_a_head_relative_comparison_rebaselines_on_commit(self):
        # Kept as executable documentation of WHY the suites no longer use that shape. If this
        # ever stops holding, the rewrite above was unnecessary and should be revisited.
        with tempfile.TemporaryDirectory() as tmp:
            def git(*args):
                subprocess.run([GIT, *args], cwd=tmp, check=True, capture_output=True)

            guard = Path(tmp, "guard.mjs")
            git("init", "-q", "-b", "main", ".")
            git("config", "user.email", "t@example.invalid")
            git("config", "user.name", "T")
            guard.write_bytes(b"guard v1\n")
            git("add", "guard.mjs")
            git("-c", "core.hooksPath=/dev/null", "commit", "-qm", "initial")

            def head_relative_lock_holds():
                head = subprocess.run([GIT, "show", "HEAD:guard.mjs"], cwd=tmp,
                                      capture_output=True, text=True, encoding="utf-8")
                return guard.read_text(encoding="utf-8") == head.stdout

            self.assertTrue(head_relative_lock_holds(), "clean checkout: the lock passes")

            guard.write_bytes(b"guard v1\nBACKDOOR\n")
            self.assertFalse(head_relative_lock_holds(),
                             "uncommitted edit: the only window the old shape fired")

            git("add", "guard.mjs")
            git("-c", "core.hooksPath=/dev/null", "commit", "-qm", "backdoor")
            self.assertTrue(head_relative_lock_holds(),
                            "committed edit: the old shape re-baselines and passes again")

            # And the digest form, on the same tree, does not.
            pinned = hashlib.sha256(b"guard v1\n").hexdigest()
            self.assertNotEqual(hashlib.sha256(guard.read_bytes()).hexdigest(), pinned,
                                "a literal digest still fails after the commit")


if __name__ == "__main__":
    unittest.main()
