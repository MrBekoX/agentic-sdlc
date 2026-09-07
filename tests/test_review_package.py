import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "review_package.py"


@unittest.skipIf(shutil.which("git") is None, "git not available")
class TestReviewPackageRefValidation(unittest.TestCase):
    """review_package.py builds `git diff/log` argv from positional base/head. A ref starting
    with '-' is parsed by git as an OPTION, not a revision -> git option injection (e.g.
    `--output=<file>` makes git write an attacker-chosen file). git itself forbids ref/branch
    names starting with '-', so the script must refuse such refs before invoking git."""

    def _make_repo(self, td):
        subprocess.run(["git", "init", "-b", "main"], cwd=td, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=td, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=td, check=True, capture_output=True)
        (Path(td) / "a.txt").write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=td, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=td, check=True, capture_output=True)

    def _run(self, td, *refs):
        # `--` forces argparse to treat the following tokens as the positional base/head,
        # which is exactly how an injected leading-dash ref reaches the git argv.
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--out-dir", str(Path(td) / "out"), "--", *refs],
            cwd=td,
            capture_output=True,
            text=True, encoding="utf-8",
        )

    def test_refuses_base_starting_with_dash_and_writes_no_injected_file(self):
        with tempfile.TemporaryDirectory() as td:
            self._make_repo(td)
            proc = self._run(td, "--output=pwned", "HEAD")
            combined = (proc.stdout + proc.stderr).lower()
            self.assertEqual(proc.returncode, 1, combined)
            self.assertIn("invalid ref", combined)
            # The injected `--output=` option must NOT have produced any file in the repo.
            self.assertEqual(list(Path(td).rglob("pwned*")), [])

    def test_refuses_head_starting_with_dash(self):
        with tempfile.TemporaryDirectory() as td:
            self._make_repo(td)
            proc = self._run(td, "HEAD", "-O/tmp/x")
            combined = (proc.stdout + proc.stderr).lower()
            self.assertEqual(proc.returncode, 1, combined)
            self.assertIn("invalid ref", combined)

    def test_ref_with_slash_does_not_create_subdir(self):
        # A legit ref like a `feat/x` branch contains '/'. The old `args.head[:12]` put that '/'
        # straight into the output filename, creating an out/feat/ subdir (path drift). The slug
        # must collapse separators so the file is written directly under out_dir.
        with tempfile.TemporaryDirectory() as td:
            self._make_repo(td)
            subprocess.run(["git", "branch", "feat/x"], cwd=td, check=True, capture_output=True)
            proc = self._run(td, "HEAD", "feat/x")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            out = Path(td) / "out"
            self.assertEqual(len(list(out.glob("*.md"))), 1, list(out.rglob("*")))
            self.assertTrue(all(p.is_file() for p in out.iterdir()))  # no subdirectory created

    def test_normal_refs_still_work(self):
        with tempfile.TemporaryDirectory() as td:
            self._make_repo(td)
            (Path(td) / "b.txt").write_text("world\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=td, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "second"], cwd=td, check=True, capture_output=True)
            proc = self._run(td, "HEAD~1", "HEAD")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertTrue(any(Path(td).glob("out/review-package-*.md")))

    def test_persisted_diff_redacts_high_confidence_secret(self):
        with tempfile.TemporaryDirectory() as td:
            self._make_repo(td)
            secret = "ghp_" + "A1b2" * 9
            (Path(td) / "secret.txt").write_text(secret + "\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=td, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "second"], cwd=td, check=True, capture_output=True)
            proc = self._run(td, "HEAD~1", "HEAD")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            text = next(Path(td).glob("out/review-package-*.md")).read_text(encoding="utf-8")
            self.assertNotIn(secret, text)
            self.assertIn("***MASKED:github-token***", text)


if __name__ == "__main__":
    unittest.main()
