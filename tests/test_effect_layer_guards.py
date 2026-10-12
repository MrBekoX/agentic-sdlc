"""Effect-layer enforcement: repo git hooks (prevention) + a Stop-time working-tree scan (detection).

WHY THIS LAYER EXISTS
Ten rounds of adversarial review over the PreToolUse command guards established a structural limit:
a gate that inspects the COMMAND STRING cannot be complete. Shell aliases and functions from
~/.bashrc, `$PATH` shadowing, `eval`, variable indirection and base64-decode-pipe-to-shell are all
resolved by the shell AFTER the hook has already decided, and the write surface (`tee`, `dd`,
`python -c`, any interpreter) is unbounded. Those are documented, accepted residuals of that layer.

This layer removes them by moving down:

  Layer 1 - PREVENTION. A real `pre-commit` / `commit-msg` hook inside the repository. Git runs
            these on the OPERATION, after it has already resolved aliases, quoting and $PATH, so
            `git ci` (alias), `g'i't commit`, `eval`, and a shell function named `git` all reach
            the same hook. Documented bypass: `--no-verify` (and history rewrites) - stated, not
            hidden.

  Layer 2 - DETECTION. A Stop-time scan of what actually landed in the working tree. It reads
            bytes on disk, so HOW they were written is irrelevant: `tee`, `python -c`, a base64
            pipe and an unrecognized redirect all show up identically.

Both layers reuse the already-hardened primitives (`secret-patterns.scanLines` with the HIGH set,
`scan-commit-names.isCredentialFilename`), so every fix from those ten rounds carries over.

No literal secret-shaped string appears in this file: every token is constructed at runtime.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
GIT = shutil.which("git")
# Reuse the interpreter that launched the suite. PATH aliases such as the Windows Store
# `python.exe` stub can exist yet fail CreateProcess, which made the cross-platform gate flaky.
PY = sys.executable

_A = "a1B2"
GH_CLEAN = "ghp_" + _A * 9
GH_OTHER = "ghp_" + "c3D4" * 9      # a second, different token of the same label (also synthetic)
GH_DOC = "ghp_" + "x" * 36          # a genuine documentation placeholder: must stay allowed

INSTALLER = REPO / "scripts" / "install_git_hooks.py"


def _git(args, cwd, **kw):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", **kw)


def _init_repo(path):
    _git(["init", "-b", "main"], path).check_returncode()
    _git(["config", "user.email", "t@e.st"], path).check_returncode()
    _git(["config", "user.name", "t"], path).check_returncode()
    _git(["config", "commit.gpgsign", "false"], path).check_returncode()


def _install(path):
    """Install the effect-layer git hooks into the repo at `path`."""
    return subprocess.run([PY, str(INSTALLER), "--install", "--repo", str(path)],
                          capture_output=True, text=True, encoding="utf-8")


@unittest.skipIf(NODE is None or GIT is None or PY is None, "node, git or python not available")
class TestGitHookInstaller(unittest.TestCase):
    """The installer must be safe to run in someone else's repository."""

    def test_installer_exists_and_reports_status(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            r = subprocess.run([PY, str(INSTALLER), "--check", "--repo", td],
                               capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("pre-commit", r.stdout)

    def test_install_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            first = _install(td)
            self.assertEqual(first.returncode, 0, first.stderr)
            body = Path(td, ".git", "hooks", "pre-commit").read_text(encoding="utf-8")
            second = _install(td)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(Path(td, ".git", "hooks", "pre-commit").read_text(encoding="utf-8"), body)

    def test_never_clobbers_a_foreign_hook(self):
        # Someone else's pre-commit must survive. Silently replacing it would break their repo and
        # is exactly the kind of side effect a security tool must not have.
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            foreign = Path(td, ".git", "hooks", "pre-commit")
            foreign.write_text("#!/bin/sh\necho FOREIGN\nexit 0\n", encoding="utf-8")
            r = _install(td)
            self.assertNotEqual(r.returncode, 0, "installer overwrote a foreign hook")
            self.assertIn("FOREIGN", foreign.read_text(encoding="utf-8"))

    def test_uninstall_removes_only_our_hook(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            _install(td)
            r = subprocess.run([PY, str(INSTALLER), "--uninstall", "--repo", td],
                               capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(Path(td, ".git", "hooks", "pre-commit").exists())


@unittest.skipIf(NODE is None or GIT is None or PY is None, "node, git or python not available")
class TestPreCommitHook(unittest.TestCase):
    """Layer 1: git runs this on the OPERATION, so command-string tricks are irrelevant."""

    def _repo(self, **files):
        td = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        _init_repo(td)
        _install(td)
        for name, content in files.items():
            p = Path(td, name)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            _git(["add", "--", name], td).check_returncode()
        return td

    def test_blocks_a_staged_secret(self):
        td = self._repo(**{"config.txt": "TOKEN = " + GH_CLEAN + "\n"})
        r = _git(["commit", "-m", "wip"], td)
        self.assertNotEqual(r.returncode, 0, "commit with a staged secret was not blocked")

    def test_blocks_a_credential_filename(self):
        td = self._repo(**{"id_rsa": "binary-key-body\n"})
        r = _git(["commit", "-m", "wip"], td)
        self.assertNotEqual(r.returncode, 0, "commit of a credential file was not blocked")

    def test_blocks_a_credential_filename_under_a_non_ascii_folder(self):
        # git C-quotes non-ASCII paths by default (core.quotePath): `"klas\303\266r/id_rsa"`. A
        # quoted name never matched the credential-filename rules, so a user whose folders are
        # named in Turkish, Chinese or any non-ASCII script could commit `id_rsa` unflagged.
        td = self._repo(**{"klasör/id_rsa": "binary-key-body\n"})
        r = _git(["commit", "-m", "wip"], td)
        self.assertNotEqual(r.returncode, 0, "credential file under a non-ASCII folder was not blocked")

    @unittest.skipIf(os.name == "nt", "a double quote is not a valid Windows file-name character")
    def test_blocks_a_credential_filename_whose_folder_needs_quoting(self):
        # core.quotePath=false stops octal-escaping non-ASCII, but git still C-quotes a name with a
        # `"`, `\` or control character. NUL-separated listings (-z) deliver every name verbatim.
        td = self._repo(**{'say "hi"/id_rsa': "binary-key-body\n"})
        r = _git(["commit", "-m", "wip"], td)
        self.assertNotEqual(r.returncode, 0, "credential file under a quoted folder name was not blocked")

    def test_allows_a_clean_commit(self):
        td = self._repo(**{"readme.md": "# hello\n"})
        r = _git(["commit", "-m", "docs: add readme"], td)
        self.assertEqual(r.returncode, 0, "clean commit was blocked: " + r.stderr)

    def test_allows_a_documentation_placeholder(self):
        # The hardened scanner's placeholder handling must carry over to this layer unchanged.
        td = self._repo(**{"README.md": "Set your token, e.g. " + GH_DOC + "\n"})
        r = _git(["commit", "-m", "docs: token example"], td)
        self.assertEqual(r.returncode, 0, "doc placeholder blocked a commit: " + r.stderr)

    def test_alias_cannot_bypass_this_layer(self):
        # THE point of layer 1. `git ci` defeated the command-string gate until it learned to
        # resolve aliases; here git has already resolved it before the hook runs, so no
        # command-string reasoning is involved at all.
        td = self._repo(**{"config.txt": "TOKEN = " + GH_CLEAN + "\n"})
        _git(["config", "alias.ci", "commit"], td).check_returncode()
        r = _git(["ci", "-m", "wip"], td)
        self.assertNotEqual(r.returncode, 0, "aliased commit bypassed the pre-commit hook")

    def test_no_verify_is_still_caught_by_prepare_commit_msg(self):
        # git documents --no-verify as skipping `pre-commit` and `commit-msg`. It does NOT skip
        # `prepare-commit-msg` - githooks: "it is not suppressed by the --no-verify option" - and
        # that hook can read `git diff --cached` and abort. So one flag no longer disarms the
        # whole commit-path guard.
        td = self._repo(**{"config.txt": "TOKEN = " + GH_CLEAN + "\n"})
        r = _git(["commit", "--no-verify", "-m", "wip"], td)
        self.assertNotEqual(r.returncode, 0, "--no-verify disarmed the entire commit-path guard")

    def test_hooks_path_dev_null_is_the_real_off_switch(self):
        # The honest limit, pinned so nobody claims this layer is unbypassable: git documents
        # core.hooksPath=/dev/null as disabling all hooks entirely.
        td = self._repo(**{"config.txt": "TOKEN = " + GH_CLEAN + "\n"})
        r = _git(["-c", "core.hooksPath=/dev/null", "commit", "-m", "wip"], td)
        self.assertEqual(r.returncode, 0, "expected core.hooksPath=/dev/null to disable hooks")

    def test_merge_commit_is_guarded(self):
        # A clean non-fast-forward merge runs `pre-merge-commit`, NOT `pre-commit`, so without a
        # merge hook that commit went in completely unscanned.
        # Build the branches with hooks fully OFF (core.hooksPath=/dev/null is git's documented
        # total disable), so the setup is not itself blocked. The merge below runs with hooks on -
        # that is the case under test.
        off = ["-c", "core.hooksPath=/dev/null"]
        td = self._repo(**{"base.txt": "base\n"})
        _git([*off, "commit", "-m", "base"], td).check_returncode()
        _git(["checkout", "-b", "side"], td).check_returncode()
        Path(td, "config.txt").write_text("TOKEN = " + GH_CLEAN + "\n", encoding="utf-8")
        _git(["add", "-A"], td).check_returncode()
        _git([*off, "commit", "-m", "side work"], td).check_returncode()
        _git(["checkout", "main"], td).check_returncode()
        Path(td, "other.txt").write_text("other\n", encoding="utf-8")
        _git(["add", "-A"], td).check_returncode()
        _git([*off, "commit", "-m", "main work"], td).check_returncode()
        r = _git(["merge", "--no-ff", "side", "-m", "merge side"], td)
        self.assertNotEqual(r.returncode, 0, "merge commit carrying a secret was not scanned")


@unittest.skipIf(NODE is None or GIT is None or PY is None, "node, git or python not available")
class TestCommitMsgHook(unittest.TestCase):
    """Layer 1b: `pre-commit` runs before a message exists, so the message needs its own hook."""

    def _repo(self):
        td = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        _init_repo(td)
        _install(td)
        Path(td, "readme.md").write_text("# hi\n", encoding="utf-8")
        _git(["add", "-A"], td).check_returncode()
        return td

    def test_blocks_a_secret_in_the_message(self):
        td = self._repo()
        r = _git(["commit", "-m", "rotate " + GH_CLEAN], td)
        self.assertNotEqual(r.returncode, 0, "secret in the commit message was not blocked")

    def test_allows_an_ordinary_message(self):
        td = self._repo()
        r = _git(["commit", "-m", "fix: handle the empty payload case"], td)
        self.assertEqual(r.returncode, 0, "ordinary message blocked: " + r.stderr)

    def test_alias_supplied_message_is_scanned(self):
        # The secret lives in the ALIAS definition, so it never appears on the command line.
        td = self._repo()
        _git(["config", "alias.ci", "commit -m 'rotate " + GH_CLEAN + "'"], td).check_returncode()
        r = _git(["ci"], td)
        self.assertNotEqual(r.returncode, 0, "alias-supplied message bypassed the commit-msg hook")


@unittest.skipIf(NODE is None or GIT is None, "node or git not available")
class TestWorktreeScan(unittest.TestCase):
    """Layer 2: reads what landed on disk, so the WRITE FORM is irrelevant."""

    HOOK = REPO / "hooks" / "worktree-scan.mjs"

    def _run(self, cwd, *, block=False, state=None):
        # The per-session dedup state is deliberately pinned to a per-test file. Letting it default
        # to the shared temp location made these tests pass alone and fail in the full suite, because
        # a previous run's state suppressed the finding - a test-isolation bug, not a guard bug.
        env = dict(os.environ)
        if block:
            env["AGENTIC_WORKTREE_SCAN_BLOCK"] = "true"
        env["AGENTIC_WORKTREE_SCAN_STATE"] = str(state or Path(cwd, ".scan-state.json"))
        proc = subprocess.run(
            [NODE, str(self.HOOK)], cwd=cwd, env=env,
            input=json.dumps({"hook_event_name": "Stop", "session_id": "t",
                              "cwd": str(cwd), "stop_hook_active": False}),
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def _repo(self):
        td = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        _init_repo(td)
        Path(td, "readme.md").write_text("# hi\n", encoding="utf-8")
        _git(["add", "-A"], td).check_returncode()
        _git(["commit", "-m", "base"], td).check_returncode()
        return td

    def test_detects_a_secret_written_by_an_unreadable_form(self):
        # `tee` is explicitly OUT of the command-string extractor's coverage. On disk it is
        # indistinguishable from any other write, which is the whole point of this layer.
        td = self._repo()
        Path(td, "out.txt").write_text("TOKEN = " + GH_CLEAN + "\n", encoding="utf-8")
        out = self._run(td)
        self.assertTrue(out, "a secret sitting in the working tree was not reported")
        self.assertNotIn(GH_CLEAN, json.dumps(out), "the report must mask the value")

    def test_detects_a_secret_in_a_tracked_modification(self):
        td = self._repo()
        Path(td, "readme.md").write_text("# hi\nTOKEN = " + GH_CLEAN + "\n", encoding="utf-8")
        self.assertTrue(self._run(td), "a modified tracked file with a secret was not reported")

    def test_detects_a_credential_file_on_disk(self):
        td = self._repo()
        Path(td, "id_rsa").write_text("binary-key-body\n", encoding="utf-8")
        self.assertTrue(self._run(td), "a credential file in the tree was not reported")

    def test_detects_secrets_under_non_ascii_paths(self):
        # With git's default core.quotePath, `git ls-files` prints `"\347\233\256\345\275\225/..."`;
        # reading that quoted string as a path failed silently, so nothing under a non-ASCII
        # folder was ever scanned - neither contents nor credential file names.
        for folder in ("klasör", "目录"):
            with self.subTest(folder=folder):
                td = self._repo()
                Path(td, folder).mkdir()
                Path(td, folder, "notes.txt").write_text("TOKEN = " + GH_CLEAN + "\n", encoding="utf-8")
                self.assertTrue(self._run(td), "a secret under %s/ was not reported" % folder)
                td = self._repo()
                Path(td, folder).mkdir()
                Path(td, folder, "id_rsa").write_text("binary-key-body\n", encoding="utf-8")
                self.assertTrue(self._run(td), "a credential file under %s/ was not reported" % folder)

    @unittest.skipIf(os.name == "nt", "a double quote is not a valid Windows file-name character")
    def test_detects_secrets_under_a_folder_name_git_must_quote(self):
        td = self._repo()
        Path(td, 'say "hi"').mkdir()
        Path(td, 'say "hi"', "notes.txt").write_text("TOKEN = " + GH_CLEAN + "\n", encoding="utf-8")
        self.assertTrue(self._run(td), "a secret under a quoted folder name was not reported")

    def test_detects_a_secret_in_a_gitignored_file(self):
        # `.env` is where secrets actually live, and it is almost always gitignored. Enumerating
        # only `git ls-files --others --exclude-standard` skipped exactly that file.
        td = self._repo()
        Path(td, ".gitignore").write_text(".env\nsecrets/\n", encoding="utf-8")
        Path(td, ".env").write_text("TOKEN=" + GH_CLEAN + "\n", encoding="utf-8")
        self.assertTrue(self._run(td), "a gitignored .env carrying a secret was not reported")

    def test_detects_a_secret_in_a_gitignored_directory(self):
        td = self._repo()
        Path(td, ".gitignore").write_text("secrets/\n", encoding="utf-8")
        Path(td, "secrets").mkdir()
        Path(td, "secrets", "key.txt").write_text("TOKEN=" + GH_CLEAN + "\n", encoding="utf-8")
        self.assertTrue(self._run(td), "a gitignored directory was not scanned")

    def test_dependency_directories_are_skipped(self):
        # CONTROL: scanning ignored paths must not mean walking node_modules on every turn.
        td = self._repo()
        Path(td, ".gitignore").write_text("node_modules/\n", encoding="utf-8")
        dep = Path(td, "node_modules", "pkg")
        dep.mkdir(parents=True)
        (dep / "fixture.js").write_text("const t = '" + GH_CLEAN + "';\n", encoding="utf-8")
        self.assertEqual(self._run(td), {}, "a vendored dependency fixture was reported as ours")

    def test_silent_on_a_clean_tree(self):
        td = self._repo()
        Path(td, "notes.md").write_text("just some notes\n", encoding="utf-8")
        self.assertEqual(self._run(td), {}, "false positive on a clean working tree")

    def test_advisory_by_default_and_blocks_only_under_the_env_flag(self):
        td = self._repo()
        Path(td, "out.txt").write_text("TOKEN = " + GH_CLEAN + "\n", encoding="utf-8")
        advisory = self._run(td, state=Path(td, "adv.json"))
        self.assertNotEqual(advisory.get("decision"), "block",
                            "Stop-time detection must not block by default")
        self.assertTrue(advisory.get("systemMessage"), "a detection must be visible to the user")
        blocking = self._run(td, block=True, state=Path(td, "blk.json"))
        self.assertEqual(blocking.get("decision"), "block",
                         "AGENTIC_WORKTREE_SCAN_BLOCK=true must escalate to a block")

    def test_does_not_repeat_the_same_finding_in_one_session(self):
        # A Stop hook fires every turn. Re-reporting an unchanged finding every time trains the
        # user to ignore it.
        td = self._repo()
        Path(td, "out.txt").write_text("TOKEN = " + GH_CLEAN + "\n", encoding="utf-8")
        shared = Path(td, "dedup.json")
        first = self._run(td, state=shared)
        self.assertTrue(first, "first sighting must be reported")
        second = self._run(td, state=shared)
        self.assertEqual(second, {}, "the same unchanged finding was reported twice")

    def test_outside_a_git_repo_it_stays_silent(self):
        td = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        Path(td, "x.txt").write_text("TOKEN = " + GH_CLEAN + "\n", encoding="utf-8")
        self.assertEqual(self._run(td), {}, "must fail open and stay quiet outside a repo")

    # --- before the first commit -------------------------------------------------------------
    # `git diff HEAD` has no HEAD to diff against, fails, and the single outer try/catch used to
    # take the untracked and ignored scans down with it: a brand-new project (where `.env` is
    # most likely to appear) was never scanned at all.

    def _unborn_repo(self):
        td = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        _init_repo(td)
        return td

    def test_detects_an_untracked_secret_before_the_first_commit(self):
        td = self._unborn_repo()
        Path(td, "out.txt").write_text("TOKEN = " + GH_CLEAN + "\n", encoding="utf-8")
        out = self._run(td)
        self.assertTrue(out, "a secret in a new file of a repository with no commit was not reported")
        self.assertNotIn(GH_CLEAN, json.dumps(out), "the report must mask the value")

    def test_detects_an_ignored_secret_before_the_first_commit(self):
        td = self._unborn_repo()
        Path(td, ".gitignore").write_text(".env\n", encoding="utf-8")
        Path(td, ".env").write_text("TOKEN=" + GH_CLEAN + "\n", encoding="utf-8")
        self.assertTrue(self._run(td), "a gitignored .env in a repository with no commit was not reported")

    def test_detects_a_staged_secret_before_the_first_commit(self):
        td = self._unborn_repo()
        Path(td, "out.txt").write_text("TOKEN = " + GH_CLEAN + "\n", encoding="utf-8")
        _git(["add", "out.txt"], td).check_returncode()
        self.assertTrue(self._run(td), "a staged secret in a repository with no commit was not reported")

    def test_detects_a_credential_file_before_the_first_commit(self):
        td = self._unborn_repo()
        Path(td, "id_rsa").write_text("binary-key-body\n", encoding="utf-8")
        self.assertTrue(self._run(td), "a credential file in a repository with no commit was not reported")

    def test_clean_tree_before_the_first_commit_stays_silent(self):
        td = self._unborn_repo()
        Path(td, "notes.md").write_text("just some notes\n", encoding="utf-8")
        self.assertEqual(self._run(td), {})

    # --- the suppression key must tell a new value from an old one ----------------------------

    def test_a_different_secret_in_the_same_file_is_reported_again(self):
        td = self._repo()
        shared = Path(td, "dedup.json")
        target = Path(td, "out.txt")
        target.write_text("TOKEN = " + GH_CLEAN + "\n", encoding="utf-8")
        self.assertTrue(self._run(td, state=shared), "first sighting must be reported")
        self.assertEqual(self._run(td, state=shared), {}, "the unchanged finding must not repeat")
        target.write_text("TOKEN = " + GH_OTHER + "\n", encoding="utf-8")
        out = self._run(td, state=shared)
        self.assertTrue(out, "a different secret at the same place was suppressed as an old finding")
        self.assertNotIn(GH_OTHER, json.dumps(out), "the report must mask the value")

    def test_a_different_secret_in_the_uncommitted_diff_is_reported_again(self):
        # Every uncommitted-diff finding shares one location label, so the label cannot tell two
        # secrets apart: only the matched line can.
        td = self._repo()
        shared = Path(td, "dedup.json")
        readme = Path(td, "readme.md")
        readme.write_text("# hi\nTOKEN = " + GH_CLEAN + "\n", encoding="utf-8")
        self.assertTrue(self._run(td, state=shared), "first sighting must be reported")
        self.assertEqual(self._run(td, state=shared), {}, "the unchanged finding must not repeat")
        readme.write_text("# hi\nTOKEN = " + GH_OTHER + "\n", encoding="utf-8")
        self.assertTrue(self._run(td, state=shared), "a different secret in the diff was suppressed as old")

    def test_the_same_secret_moving_to_another_line_is_not_a_new_finding(self):
        # CONTROL: a fingerprint of the matched line, not of its position, so editing around an
        # unchanged secret does not make the hook repeat itself every turn.
        td = self._repo()
        shared = Path(td, "dedup.json")
        target = Path(td, "out.txt")
        target.write_text("TOKEN = " + GH_CLEAN + "\n", encoding="utf-8")
        self.assertTrue(self._run(td, state=shared))
        target.write_text("# a new first line\nTOKEN = " + GH_CLEAN + "\n", encoding="utf-8")
        self.assertEqual(self._run(td, state=shared), {}, "moving an unchanged secret re-reported it")


if __name__ == "__main__":
    unittest.main()
