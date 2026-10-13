"""Message scan cannot discard commentary that Git may retain in history."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
GIT = shutil.which("git")
SCANNER = REPO / "hooks" / "git-hook-scan.mjs"
INSTALLER = REPO / "scripts" / "install_git_hooks.py"
# Header only, no key material; constructed to keep a doc-shaped value out of source scans.
CANARY = "-----BEGIN " + "PRIVATE KEY-----"


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestCommitMessageRetention(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="message-retention-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        self.repo = self.make_repo(self.root / "fixture")

    def git(self, args, *, cwd=None, env=None):
        return subprocess.run([GIT, *args], cwd=str(cwd or self.repo), env=env or self.env,
                              capture_output=True, text=True, encoding="utf-8", timeout=20)

    def make_repo(self, path):
        path.mkdir(parents=True)
        for args in (("init", "-b", "feature/test"), ("config", "user.name", "Fixture"),
                     ("config", "user.email", "fixture@example.invalid"),
                     ("config", "commit.gpgsign", "false")):
            result = self.git(args, cwd=path)
            self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([sys.executable, str(INSTALLER), "--install", "--repo", str(path)],
                                capture_output=True, text=True, encoding="utf-8", env=self.env, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("pre-commit", "commit-msg", "prepare-commit-msg", "pre-merge-commit"):
            self.assertIn(name + "=installed", result.stdout)
        return path

    def scan(self, mode, file):
        return subprocess.run([NODE, str(SCANNER), mode, str(file)], cwd=self.repo, env=self.env,
                              capture_output=True, text=True, encoding="utf-8", timeout=15)

    def test_hash_line_is_scanned_in_both_message_modes(self):
        for newline in ("\n", "\r\n"):
            for mode in ("commit-msg", "prepare-commit-msg"):
                with self.subTest(newline=repr(newline), mode=mode):
                    message = self.root / "message.txt"
                    message.write_bytes(("fixture" + newline + "# " + CANARY + newline).encode("utf-8"))
                    result = self.scan(mode, message)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn("private-key (commit message)", result.stderr)
                    self.assertNotIn(CANARY, result.stderr)

    def test_installed_hooks_reject_retained_hash_message(self):
        cases = (
            ([], "-m"), ([], "-F"), (["--cleanup=whitespace"], "-m"),
            (["--cleanup=verbatim"], "-F"), (["--no-verify"], "-m"),
        )
        for extra, message_option in cases:
            with self.subTest(extra=extra, option=message_option):
                body = "fixture\n# " + CANARY + "\n"
                message = self.root / "message.txt"
                message.write_text(body, encoding="utf-8")
                value = str(message) if message_option == "-F" else body
                result = self.git(["commit", "--allow-empty", *extra, message_option, value])
                self.assertNotEqual(result.returncode, 0, "retained hash canary committed")
                self.assertIn("private-key (commit message)", result.stderr)
                self.assertNotIn(CANARY, result.stderr)
                self.assertNotEqual(self.git(["rev-parse", "--verify", "HEAD"]).returncode, 0)
        result = self.git(["-c", "core.commentChar=;", "commit", "--allow-empty", "--cleanup=strip",
                           "-m", "fixture\n# " + CANARY])
        self.assertNotEqual(result.returncode, 0, "custom comment marker retained hash canary")
        self.assertIn("private-key (commit message)", result.stderr)

    @unittest.skipIf(os.name == "nt", "POSIX editor fixture; native Windows direct modes are covered")
    def test_editor_inserted_hash_is_rejected_by_commit_msg(self):
        editor = self.root / "editor"
        editor.write_text("#!/bin/sh\nprintf '\\n# " + CANARY + "\\n' >> \"$1\"\n", encoding="utf-8")
        editor.chmod(0o700)
        for cleanup in ("whitespace", "verbatim"):
            with self.subTest(cleanup=cleanup):
                result = self.git(["commit", "--allow-empty", "--edit", "--cleanup=" + cleanup,
                                   "-m", "fixture before editor"], env=dict(self.env, GIT_EDITOR=str(editor)))
                self.assertNotEqual(result.returncode, 0, "late message edit bypassed commit-msg")
                self.assertIn("private-key (commit message)", result.stderr)
                self.assertNotEqual(self.git(["rev-parse", "--verify", "HEAD"]).returncode, 0)

    def test_harmless_templates_samples_and_same_line_suppression_remain_allowed(self):
        controls = (
            "fixture\n# Changes to be committed:\n# ordinary template note\n",
            "fixture\n# placeholder only\n",
            "fixture\n# " + "AKIAIOSFODNN7" + "EXAMPLE\n",
            "fixture\n# " + CANARY + " agentic-sdlc:allow-secret\n",
        )
        for text in controls:
            for mode in ("commit-msg", "prepare-commit-msg"):
                with self.subTest(text=text[:20], mode=mode):
                    message = self.root / "safe.txt"
                    message.write_text(text, encoding="utf-8")
                    result = self.scan(mode, message)
                    self.assertEqual(result.returncode, 0, result.stderr)
        result = self.git(["commit", "--allow-empty", "-m", controls[0]])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_other_line_suppression_cannot_hide_hash_finding(self):
        message = self.root / "message.txt"
        message.write_text("fixture agentic-sdlc:allow-secret\n# " + CANARY + "\n", encoding="utf-8")
        for mode in ("commit-msg", "prepare-commit-msg"):
            with self.subTest(mode=mode):
                self.assertEqual(self.scan(mode, message).returncode, 1)

    def test_missing_message_preserves_explicit_unscanned_warning(self):
        for mode in ("commit-msg", "prepare-commit-msg"):
            with self.subTest(mode=mode):
                result = self.scan(mode, self.root / "absent")
                self.assertEqual(result.returncode, 0)
                self.assertIn("NOT scanned", result.stderr)


if __name__ == "__main__":
    unittest.main()
