"""Git facts, fingerprints and start probes of the sdlc runner (plan Task 2).

Contract: docs/agentic-sdlc/notes/2026-10-22-runner-contract.md §1, §2, §5. Covers
scripts/sdlc_runner/gitinfo.py, fingerprint.py and probes.py. Every repository is made with
`git init` inside a temp dir under an isolated git configuration; nothing here touches the
checkout the suite runs from. Every hostile case has a clean twin, so a check that always passes
(or always fails) is caught.
"""
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from sdlc_runner import fingerprint, frontmatter, gitinfo, paths, probes, textio  # noqa: E402

HAVE_GIT = gitinfo.git_available()
GIT = paths.resolve_program("git")
POSIX = os.name == "posix"

# Repository-location variables a parent git (a hook, `git rebase -x`) exports; git's own list
# (`git rev-parse --local-env-vars`). Removed for every test so the suite cannot act on the wrong repo.
LOCAL_GIT_ENV = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
    "GIT_OBJECT_DIRECTORY", "GIT_DIR", "GIT_WORK_TREE", "GIT_IMPLICIT_WORK_TREE", "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE", "GIT_NO_REPLACE_OBJECTS", "GIT_REPLACE_REF_BASE", "GIT_PREFIX",
    "GIT_SHALLOW_FILE", "GIT_COMMON_DIR",
)

# The test globs of the fixture `_shared.json` (plan Task 2 Step 1); Task 3 owns flows/_shared.json.
SHARED_FIXTURE = {
    "test_globs": [
        "tests/**", "**/test_*.py", "**/*.test.{js,ts}", "**/*_test.go", "**/__tests__/**",
        "**/*Tests.cs", "spec/**",
    ],
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _crlf_bom_variants(text: str):
    lf = text.encode("utf-8")
    crlf = lf.replace(b"\n", b"\r\n")
    return [lf, crlf, b"\xef\xbb\xbf" + lf, b"\xef\xbb\xbf" + crlf]


class GitCase(unittest.TestCase):
    """A temp dir, an isolated git configuration, and helpers that build throwaway repositories."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name).resolve()
        self.nohooks = self.tmp / "no-hooks"  # never created
        global_cfg = self.tmp / "global.gitconfig"
        global_cfg.write_bytes(b"")
        self.global_cfg = global_cfg
        env = {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(global_cfg),
            # git's default global ignore and attributes files ($XDG_CONFIG_HOME/git/ignore, else
            # ~/.config/git/ignore) are read even with an empty global config; this one is empty.
            "XDG_CONFIG_HOME": str(self.tmp / "xdg"),
            "GIT_AUTHOR_NAME": "sdlc test",
            "GIT_AUTHOR_EMAIL": "sdlc-test@example.invalid",
            "GIT_COMMITTER_NAME": "sdlc test",
            "GIT_COMMITTER_EMAIL": "sdlc-test@example.invalid",
            # Discovery stops at the temp root, so a temp dir inside some checkout is not a repo.
            "GIT_CEILING_DIRECTORIES": str(self.tmp),
        }
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in LOCAL_GIT_ENV:
            os.environ.pop(name, None)

    def git(self, cwd, *args, check=True, env=None):
        proc = subprocess.run(
            [GIT, "-c", "core.hooksPath=" + str(self.nohooks), "-c", "commit.gpgsign=false",
             "-c", "init.defaultBranch=main", "-c", "core.autocrlf=false", *args],
            cwd=str(cwd), stdin=subprocess.DEVNULL, capture_output=True, shell=False,
            encoding="utf-8", errors="replace", timeout=60, env=env,
        )
        if check and proc.returncode != 0:
            self.fail("git %s failed: %s" % (" ".join(args), proc.stderr))
        return proc

    def make_repo(self, name="repo", files=None, commit=True):
        root = self.tmp / name
        root.mkdir(parents=True)
        self.git(root, "init", "-q")
        for rel, data in (files or {"a.txt": b"a\n"}).items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        if commit:
            self.commit(root, "initial")
        return root

    def commit(self, root, message):
        self.git(root, "add", "-A")
        self.git(root, "commit", "-q", "--allow-empty", "-m", message)
        return self.git(root, "rev-parse", "HEAD").stdout.strip()

    def write(self, root, rel, data: bytes):
        target = Path(root) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target


# ---------------------------------------------------------------------------------------------
# gitinfo
# ---------------------------------------------------------------------------------------------

class TestGitFacts(GitCase):
    def test_git_available_follows_program_resolution(self):
        with mock.patch.object(gitinfo.paths, "resolve_program", return_value=None):
            self.assertFalse(gitinfo.git_available())
            facts = gitinfo.facts(self.tmp)
            self.assertEqual((facts["repo"], facts["reason"]), (False, "git_missing"))
            with self.assertRaises(textio.SdlcError) as ctx:
                gitinfo.changed_paths(self.tmp, None)
            self.assertEqual((ctx.exception.code, ctx.exception.message), (2, "git_missing"))
            with self.assertRaises(textio.SdlcError):
                gitinfo.run_git(self.tmp, "status")
        if GIT:  # clean twin
            self.assertTrue(gitinfo.git_available())

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_gitinfo_not_a_repo(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        facts = gitinfo.facts(plain)
        self.assertEqual(facts, {"repo": False, "unborn": False, "head": None, "branch": None,
                                 "detached": False, "writable": False, "reason": "not_a_repo"})
        self.assertIsNone(gitinfo.head_sha(plain))
        with self.assertRaises(textio.SdlcError) as ctx:
            gitinfo.changed_paths(plain, None)
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(ctx.exception.message, "not_a_git_repo")
        # A folder that does not exist is a fact too, never a crash.
        missing = gitinfo.facts(self.tmp / "missing")
        self.assertEqual((missing["repo"], missing["reason"]), (False, "project_missing"))
        # Clean twin: the same folder after `git init` is a repository.
        self.git(plain, "init", "-q")
        self.assertTrue(gitinfo.facts(plain)["repo"])

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_gitinfo_unborn_head(self):
        repo = self.make_repo(files={"staged.py": b"x\n"}, commit=False)
        self.git(repo, "add", "staged.py")
        self.write(repo, "untracked.txt", b"u\n")
        facts = gitinfo.facts(repo)
        self.assertEqual(facts, {"repo": True, "unborn": True, "head": None, "branch": "main",
                                 "detached": False, "writable": True, "reason": None})
        self.assertIsNone(gitinfo.head_sha(repo))
        self.assertEqual(gitinfo.changed_paths(repo, None), ["staged.py", "untracked.txt"])
        # Clean twin: after the first commit HEAD is born.
        sha = self.commit(repo, "first")
        born = gitinfo.facts(repo)
        self.assertEqual((born["unborn"], born["head"], born["branch"]), (False, sha, "main"))
        self.assertEqual(gitinfo.head_sha(repo), sha)

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_gitinfo_detached(self):
        repo = self.make_repo()
        first = self.git(repo, "rev-parse", "HEAD").stdout.strip()
        self.write(repo, "b.txt", b"b\n")
        second = self.commit(repo, "second")
        on_branch = gitinfo.facts(repo)
        self.assertEqual((on_branch["detached"], on_branch["branch"], on_branch["head"]),
                         (False, "main", second))
        self.git(repo, "checkout", "-q", "--detach", first)
        facts = gitinfo.facts(repo)
        self.assertEqual(facts, {"repo": True, "unborn": False, "head": first, "branch": None,
                                 "detached": True, "writable": True, "reason": None})

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_gitinfo_branch_with_slash_is_kept_whole(self):
        repo = self.make_repo()
        self.git(repo, "checkout", "-q", "-b", "feat/x-y")
        self.assertEqual(gitinfo.facts(repo)["branch"], "feat/x-y")

    def _make_readonly(self, directory: Path):
        """Make `directory` refuse new files, or skip when this platform/user cannot."""
        if POSIX:
            os.chmod(directory, 0o555)
            self.addCleanup(os.chmod, directory, 0o755)
        elif sys.platform == "win32":
            # The read-only attribute does not stop file creation in a Windows folder; an ACL does.
            icacls = paths.resolve_program("icacls")
            if icacls is None:
                self.skipTest("icacls not found")
            deny = subprocess.run([icacls, str(directory), "/deny", "*S-1-1-0:(WD,AD)"],
                                  stdin=subprocess.DEVNULL, capture_output=True, shell=False,
                                  encoding="utf-8", errors="replace", timeout=60)
            if deny.returncode != 0:
                self.skipTest("icacls could not deny writes: " + deny.stdout + deny.stderr)
            self.addCleanup(subprocess.run, [icacls, str(directory), "/remove:d", "*S-1-1-0"],
                            stdin=subprocess.DEVNULL, capture_output=True, shell=False,
                            encoding="utf-8", errors="replace", timeout=60)
        else:
            self.skipTest("no way to make a folder read-only here")
        probe = directory / ".readonly-check"
        try:
            fd = os.open(str(probe), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError:
            return
        os.close(fd)
        os.unlink(str(probe))
        self.skipTest("the folder still accepts new files (running as root?)")

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_gitinfo_readonly_git_dir(self):
        repo = self.make_repo()
        head = self.git(repo, "rev-parse", "HEAD").stdout.strip()
        git_dir = repo / ".git"
        # Clean twin: a normal .git accepts the probe, and the probe leaves nothing behind.
        listing = sorted(os.listdir(git_dir))
        self.assertTrue(gitinfo.facts(repo)["writable"])
        self.assertEqual(sorted(os.listdir(git_dir)), listing)
        self._make_readonly(git_dir)
        facts = gitinfo.facts(repo)
        self.assertEqual(facts, {"repo": True, "unborn": False, "head": head, "branch": "main",
                                 "detached": False, "writable": False, "reason": None})
        # The read-only .git (a Codex sandbox) still answers the change queries.
        self.write(repo, "new.txt", b"n\n")
        self.assertEqual(gitinfo.changed_paths(repo, head), ["new.txt"])
        self.assertEqual(sorted(os.listdir(git_dir)), listing)

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_gitinfo_writable_false_when_the_probe_create_is_refused(self):
        repo = self.make_repo()
        with mock.patch.object(gitinfo, "_open_exclusive", side_effect=PermissionError(13, "denied")):
            facts = gitinfo.facts(repo)
        self.assertEqual((facts["repo"], facts["writable"], facts["reason"]), (True, False, None))
        self.assertTrue(gitinfo.facts(repo)["writable"])  # clean twin

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_gitinfo_ignores_repository_location_variables(self):
        other = self.make_repo("other")
        other_head = self.git(other, "rev-parse", "HEAD").stdout.strip()
        mine = self.make_repo("mine", commit=False)
        hostile = dict(os.environ, GIT_DIR=str(other / ".git"))
        # The hazard is real: a plain git call in `mine` follows GIT_DIR to the other repo.
        leaked = self.git(mine, "rev-parse", "HEAD", env=hostile)
        self.assertEqual(leaked.stdout.strip(), other_head)
        with mock.patch.dict(os.environ, {"GIT_DIR": str(other / ".git")}):
            facts = gitinfo.facts(mine)
            changed = gitinfo.changed_paths(mine, None)
        self.assertEqual((facts["unborn"], facts["head"]), (True, None))
        self.assertEqual(changed, ["a.txt"])

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_run_git_never_uses_a_git_planted_in_the_project(self):
        # An absolute PATH entry inside the project (an activated .venv/bin, direnv's PATH_add bin).
        repo = self.make_repo()
        planted = self.write(repo, "bin/" + ("git.exe" if sys.platform == "win32" else "git"), b"")
        os.chmod(str(planted), 0o755)
        if POSIX and not os.access(str(planted), os.X_OK):
            self.skipTest("this temp folder does not allow programs (a noexec mount)")
        hostile_path = str(repo / "bin") + os.pathsep + os.environ.get("PATH", "")
        with mock.patch.dict(os.environ, {"PATH": hostile_path}):
            self.assertEqual(paths.resolve_program("git"), str(planted))  # the hazard is real
            proc = gitinfo.run_git(repo, "rev-parse", "--is-inside-work-tree")
            facts = gitinfo.facts(repo)
            top = paths.project_root(repo / "bin")
        self.assertEqual(proc.stdout.strip(), "true")
        self.assertEqual((facts["repo"], facts["reason"]), (True, None))
        self.assertEqual(top.resolve(), repo.resolve())


class TestRunGit(GitCase):
    FAKE_GIT = os.path.abspath(os.path.join(os.sep, "fake-bin", "git"))

    def _fake_run(self, calls):
        def fake(argv, **kwargs):
            # Fail closed: anything but the resolved git running a known subcommand is a test bug.
            if not argv or argv[0] != self.FAKE_GIT or not ({"rev-parse", "diff"} & set(argv)):
                raise AssertionError("unexpected subprocess argv: %r" % (argv,))
            calls.append((list(argv), kwargs))
            return subprocess.CompletedProcess(argv, 0, "true\n", "")
        return fake

    def test_run_git_argv_and_environment_are_hardened(self):
        calls = []
        hostile = {"GIT_DIR": "/elsewhere/.git", "GIT_INDEX_FILE": "/elsewhere/index",
                   "GIT_CONFIG_PARAMETERS": "'core.fsmonitor'='evil'", "LC_ALL": "tr_TR.UTF-8"}
        with mock.patch.dict(os.environ, hostile), \
                mock.patch.object(gitinfo.paths, "resolve_program", return_value=self.FAKE_GIT), \
                mock.patch.object(gitinfo.subprocess, "run", side_effect=self._fake_run(calls)):
            result = gitinfo.run_git(self.tmp, "rev-parse", "--is-inside-work-tree")
            gitinfo.run_git(self.tmp, "diff", "--name-only", "-z")
        self.assertEqual(result.returncode, 0)
        argv, kwargs = calls[0]
        self.assertEqual(argv[0], self.FAKE_GIT)
        self.assertTrue(os.path.isabs(argv[0]))
        self.assertEqual(argv[-2:], ["rev-parse", "--is-inside-work-tree"])
        pairs = list(zip(argv, argv[1:]))
        self.assertIn(("-c", "core.fsmonitor="), pairs)
        self.assertIn("--no-optional-locks", argv)
        hooks = [b for a, b in pairs if a == "-c" and b.startswith("core.hooksPath=")]
        self.assertEqual(len(hooks), 1)
        hooks_dir = hooks[0][len("core.hooksPath="):]
        self.assertTrue(os.path.isabs(hooks_dir))
        self.assertTrue(os.path.isdir(hooks_dir))
        self.assertEqual(os.listdir(hooks_dir), [])
        self.assertIs(kwargs.get("shell"), False)
        self.assertEqual((kwargs.get("encoding"), kwargs.get("errors")), ("utf-8", "replace"))
        self.assertGreater(kwargs.get("timeout") or 0, 0)
        self.assertEqual(kwargs.get("cwd"), str(self.tmp))
        env = kwargs.get("env")
        self.assertIsNotNone(env)
        for name in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_CONFIG_PARAMETERS"):
            self.assertNotIn(name, env)
        self.assertEqual(env.get("LC_ALL"), "C")  # English messages, so failure reasons parse
        diff_argv = calls[1][0]
        start = diff_argv.index("diff")
        self.assertEqual(diff_argv[start:start + 3], ["diff", "--no-ext-diff", "--no-textconv"])

    def test_run_git_turns_spawn_failures_into_sdlc_errors(self):
        with mock.patch.object(gitinfo.paths, "resolve_program", return_value=self.FAKE_GIT), \
                mock.patch.object(gitinfo.subprocess, "run",
                                  side_effect=subprocess.TimeoutExpired([self.FAKE_GIT], 1)):
            with self.assertRaises(textio.SdlcError) as ctx:
                gitinfo.run_git(self.tmp, "status")
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(ctx.exception.message, "git_timeout:status")
        with mock.patch.object(gitinfo.paths, "resolve_program", return_value=self.FAKE_GIT), \
                mock.patch.object(gitinfo.subprocess, "run", side_effect=OSError("boom")):
            with self.assertRaises(textio.SdlcError) as ctx:
                gitinfo.run_git(self.tmp, "status")
        self.assertEqual(ctx.exception.message, "git_failed:status:OSError")

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_run_git_disables_a_repository_fsmonitor_hook(self):
        repo = self.make_repo()
        marker = self.tmp / "fsmonitor-ran"
        hook = self.tmp / "fsmonitor-hook.sh"
        hook.write_bytes(("#!/bin/sh\necho ran > '%s'\nexit 1\n" % marker.as_posix()).encode("utf-8"))
        os.chmod(hook, 0o755)
        self.git(repo, "config", "core.fsmonitor", hook.as_posix())
        self.write(repo, "a.txt", b"changed\n")
        # Twin: the configured hook really runs on a plain `git status`.
        self.git(repo, "status", "--porcelain", check=False)
        if not marker.exists():
            self.skipTest("this git does not run a configured fsmonitor hook")
        marker.unlink()
        self.assertEqual(gitinfo.changed_paths(repo, None), ["a.txt"])
        gitinfo.facts(repo)
        self.assertFalse(marker.exists())


class TestChangedPaths(GitCase):
    def test_status_parser_handles_renames_copies_and_untracked(self):
        raw = "R  new.py\0old.py\0C  copy.py\0src.py\0?? dir/u.txt\0 M m.txt\0D  gone.txt\0?? nested/\0"
        self.assertEqual(sorted(gitinfo._parse_status_z(raw)),
                         ["copy.py", "dir/u.txt", "gone.txt", "m.txt", "nested", "new.py", "old.py"])
        self.assertEqual(gitinfo._parse_status_z(""), [])

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_changed_paths_includes_untracked_and_renames(self):
        repo = self.make_repo(files={"a.py": b"print(1)\n", "keep.txt": b"k\n", "mod.txt": b"m\n",
                                     "gone.txt": b"g\n"})
        base = self.git(repo, "rev-parse", "HEAD").stdout.strip()
        self.write(repo, "c.txt", b"committed after base\n")
        self.commit(repo, "after base")
        self.git(repo, "mv", "a.py", "moved.py")
        self.write(repo, "mod.txt", b"m2\n")
        (repo / "gone.txt").unlink()
        self.write(repo, "new/deep/u.py", b"u\n")
        self.write(repo, "space name ğ.txt", b"s\n")
        working = ["a.py", "gone.txt", "mod.txt", "moved.py", "new/deep/u.py", "space name ğ.txt"]
        self.assertEqual(gitinfo.changed_paths(repo, None), working)
        # With a base, files committed since the base are changed too; keep.txt never is.
        self.assertEqual(gitinfo.changed_paths(repo, base), sorted(working + ["c.txt"]))

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_changed_paths_lists_both_paths_of_a_committed_rename(self):
        # A source file moved under tests/ must not hide the source change from the RED-order check,
        # whatever the user's rename settings say.
        self.global_cfg.write_bytes(b"[diff]\n\trenames = copies\n[status]\n\trenames = true\n")
        repo = self.make_repo(files={"src/x.py": b"".join(b"line %d\n" % i for i in range(40)),
                                     "keep.py": b"k\n"})
        base = self.git(repo, "rev-parse", "HEAD").stdout.strip()
        (repo / "tests").mkdir()
        self.git(repo, "mv", "src/x.py", "tests/x_test.py")
        self.commit(repo, "move a source file under tests")
        self.assertEqual(gitinfo.changed_paths(repo, base), ["src/x.py", "tests/x_test.py"])
        self.assertEqual(gitinfo.changed_paths(repo, None), [])  # clean twin: nothing uncommitted
        # The hazard is real: git itself reports only the new path with the user's settings.
        plain = self.git(repo, "diff", "--name-only", base, "HEAD").stdout.split()
        self.assertEqual(plain, ["tests/x_test.py"])

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_changed_paths_excludes_package_dir(self):
        repo = self.make_repo(files={"docs/agentic-sdlc/pkg/state.json": b"{}\n",
                                     "docs/readme.md": b"r\n", "src/x.py": b"x\n"})
        base = self.git(repo, "rev-parse", "HEAD").stdout.strip()
        self.write(repo, "docs/agentic-sdlc/pkg/state.json", b'{"a": 1}\n')
        self.write(repo, "docs/agentic-sdlc/pkg/runs.jsonl", b"{}\n")
        self.write(repo, "docs/agentic-sdlc/other/spec/x.md", b"s\n")
        self.write(repo, "docs/agentic-sdlc-notes/n.md", b"n\n")  # boundary twin: not the package root
        self.write(repo, "docs/readme.md", b"r2\n")
        expected = ["docs/agentic-sdlc-notes/n.md", "docs/readme.md"]
        self.assertEqual(gitinfo.changed_paths(repo, None), expected)
        self.assertEqual(gitinfo.changed_paths(repo, base), expected)

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_package_written_into_an_existing_docs_folder_of_another_case(self):
        # .NET and Unity repositories often have `Docs/`; on a case-insensitive file system
        # (Windows, default macOS) the package lands inside it and git reports `Docs/agentic-sdlc/...`.
        repo = self.make_repo(files={"Docs/index.md": b"i\n", "app.py": b"a\n"})
        if not (repo / "docs").is_dir():
            self.skipTest("case-sensitive file system: docs/ and Docs/ are different folders")
        head = self.git(repo, "rev-parse", "HEAD").stdout.strip()
        pkg = paths.package_dir(repo, "add-export")
        textio.write_json_atomic(pkg / "state.json", {"status": "active"})
        self.write(pkg, "transitions.jsonl", b"{}\n")
        self.assertIn("Docs/agentic-sdlc/add-export/state.json",
                      self.git(repo, "status", "--porcelain", "-uall").stdout)  # the hazard is real
        self.assertEqual(gitinfo.changed_paths(repo, None), [])
        self.assertEqual(gitinfo.changed_paths(repo, head), [])
        self.write(repo, "app.py", b"a2\n")  # clean twin: a real source change still shows
        self.assertEqual(gitinfo.changed_paths(repo, head), ["app.py"])

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_changed_paths_of_a_subfolder_project_are_relative_to_it(self):
        repo = self.make_repo(files={"sub/in.py": b"i\n", "out.py": b"o\n"})
        base = self.git(repo, "rev-parse", "HEAD").stdout.strip()
        self.write(repo, "sub/in.py", b"i2\n")
        self.write(repo, "sub/docs/agentic-sdlc/p/state.json", b"{}\n")
        self.write(repo, "out.py", b"o2\n")
        self.assertEqual(gitinfo.changed_paths(repo / "sub", base), ["in.py"])
        self.assertEqual(gitinfo.changed_paths(repo, base),
                         ["out.py", "sub/docs/agentic-sdlc/p/state.json", "sub/in.py"])

    @unittest.skipUnless(HAVE_GIT, "git not installed")
    def test_changed_paths_refuses_a_base_that_is_not_a_commit_id(self):
        repo = self.make_repo()
        for bad in ("--output=evil.txt", "HEAD", "main", "abc", "g" * 40, "a" * 40 + "\n"):
            with self.subTest(base=bad):
                with self.assertRaises(textio.SdlcError) as ctx:
                    gitinfo.changed_paths(repo, bad)
                self.assertEqual(ctx.exception.code, 2)
                self.assertTrue(ctx.exception.message.startswith("bad_base_commit"))
        self.assertFalse((repo / "evil.txt").exists())
        # Twin: the real id is accepted, a commit id that is not in the repo is a named git failure.
        sha = self.git(repo, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(gitinfo.changed_paths(repo, sha), [])
        with self.assertRaises(textio.SdlcError) as ctx:
            gitinfo.changed_paths(repo, "0" * 40)
        self.assertTrue(ctx.exception.message.startswith("git_failed:diff"))


# ---------------------------------------------------------------------------------------------
# fingerprint
# ---------------------------------------------------------------------------------------------

class TestFingerprint(GitCase):
    def test_norm_bytes(self):
        cases = {
            b"\xef\xbb\xbfa\r\nb\r\n": b"a\nb\n",
            b"a\nb\n": b"a\nb\n",
            b"a\rb": b"a\rb",                      # a lone CR is content
            b"a\r\r\n": b"a\r\n",
            b"x\xef\xbb\xbf": b"x\xef\xbb\xbf",    # a BOM that does not lead is content
            b"\xef\xbb\xbf\xef\xbb\xbfz": b"\xef\xbb\xbfz",  # only one leading BOM goes
            b"": b"",
        }
        for raw, want in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(fingerprint.norm_bytes(raw), want)

    def test_fingerprint_crlf_bom_equal(self):
        text = "---\nstatus: draft\n---\n# Title ğ\n\nbody line\n"
        fps = set()
        for i, data in enumerate(_crlf_bom_variants(text)):
            target = self.write(self.tmp, "v%d.md" % i, data)
            fp = fingerprint.file_fp(target)
            self.assertEqual(fp, _sha(fingerprint.norm_bytes(data)))
            fps.add(fp)
        self.assertEqual(len(fps), 1)
        self.assertRegex(fps.pop(), r"^[0-9a-f]{64}$")
        # Twins: a content change is a change; a missing file is the literal "absent".
        other = self.write(self.tmp, "other.md", text.replace("body", "Body").encode("utf-8"))
        self.assertNotEqual(fingerprint.file_fp(other), fingerprint.file_fp(self.tmp / "v0.md"))
        self.assertEqual(fingerprint.file_fp(self.tmp / "missing.md"), "absent")
        self.assertEqual(fingerprint.file_fp(self.tmp / "no-dir" / "missing.md"), "absent")

    def test_file_fp_streams_across_chunk_boundaries(self):
        raw = b"\xef\xbb\xbf" + b"ab\r\ncd\r\r\n\r\ne\rf\r\n" * 7 + b"\r"
        target = self.write(self.tmp, "stream.bin", raw)
        want = _sha(fingerprint.norm_bytes(raw))
        for size in range(1, 12):
            with self.subTest(chunk=size), mock.patch.object(fingerprint, "_CHUNK", size):
                self.assertEqual(fingerprint.file_fp(target), want)

    def test_file_fp_of_non_files(self):
        folder = self.tmp / "folder"
        folder.mkdir()
        self.assertEqual(fingerprint.file_fp(folder), "dir")
        if hasattr(os, "mkfifo"):
            fifo = self.tmp / "pipe"
            os.mkfifo(str(fifo))
            self.assertEqual(fingerprint.file_fp(fifo), "special")  # never opened, never blocks

    def test_file_fp_hashes_a_symlink_never_its_target(self):
        target = self.write(self.tmp, "outside.txt", b"one\n")
        link = self.tmp / "link"
        try:
            os.symlink(str(target), str(link))
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available here")
        before = fingerprint.file_fp(link)
        self.assertRegex(before, r"^[0-9a-f]{64}$")
        self.assertNotEqual(before, fingerprint.file_fp(target))
        target.write_bytes(b"two\n")
        self.assertEqual(fingerprint.file_fp(link), before)  # the target's bytes are not read
        link.unlink()
        os.symlink(str(self.tmp / "elsewhere.txt"), str(link))
        self.assertNotEqual(fingerprint.file_fp(link), before)  # re-pointing the link is a change

    def test_body_fp_ignores_frontmatter(self):
        body = "# Spec\n\nThe body ğ.\n"
        a = self.write(self.tmp, "a.md", ("---\nstatus: draft\nwork_id: x\n---\n" + body).encode("utf-8"))
        b = self.write(self.tmp, "b.md", ("---\nstatus: approved\n---\n" + body).encode("utf-8"))
        bare = self.write(self.tmp, "bare.md", body.encode("utf-8"))
        hostile = self.write(self.tmp, "hostile.md",
                             b"\xef\xbb\xbf" + ("---\r\nstatus: x\r\n---\r\n" + body.replace("\n", "\r\n")).encode("utf-8"))
        fp = fingerprint.body_fp(a)
        self.assertRegex(fp, r"^[0-9a-f]{64}$")
        for other in (b, bare, hostile):
            with self.subTest(file=other.name):
                self.assertEqual(fingerprint.body_fp(other), fp)
        # The runner's own stamping (frontmatter.render) never moves the body fingerprint.
        loose = self.write(self.tmp, "loose.md", (body + "\n\n").encode("utf-8"))
        self.assertEqual(fingerprint.body_fp(loose), fp)
        stamped = self.write(self.tmp, "stamped.md",
                             frontmatter.render({"status": "reviewed"}, body + "\n\n").encode("utf-8"))
        self.assertEqual(fingerprint.body_fp(stamped), fp)
        # Twins: a body edit is a change, a missing file is "absent", an unterminated block is body.
        edited = self.write(self.tmp, "edited.md", ("---\nstatus: draft\n---\n" + body + "more\n").encode("utf-8"))
        self.assertNotEqual(fingerprint.body_fp(edited), fp)
        self.assertEqual(fingerprint.body_fp(self.tmp / "missing.md"), "absent")
        open_block = self.write(self.tmp, "open.md", ("---\nstatus: draft\n" + body).encode("utf-8"))
        self.assertNotEqual(fingerprint.body_fp(open_block), fp)
        self.assertEqual(fingerprint.body_fp(open_block),
                         _sha(("---\nstatus: draft\n" + body).encode("utf-8")))

    def test_set_fp(self):
        # The set fingerprint is its members and their content only. It once also hashed the HEAD
        # commit, so committing the work (or an empty commit) made every @source/@tests step stale
        # and used up a security fix round (audit RN-6); set_fp takes no HEAD since.
        self.write(self.tmp, "src/a.py", b"a\n")
        self.write(self.tmp, "src/b.py", b"b\n")
        fp = fingerprint.set_fp(self.tmp, ["src/a.py", "src/b.py"])
        self.assertRegex(fp, r"^[0-9a-f]{64}$")
        self.assertEqual(fingerprint.set_fp(self.tmp, ["src/b.py", "src/a.py", "src/a.py"]), fp)
        self.assertNotEqual(fingerprint.set_fp(self.tmp, ["src/a.py"]), fp)
        self.assertNotEqual(fingerprint.set_fp(self.tmp, ["src/a.py", "src/b.py", "gone.py"]), fp)
        self.write(self.tmp, "src/a.py", b"a\r\n")  # a CRLF checkout is not a change
        self.assertEqual(fingerprint.set_fp(self.tmp, ["src/a.py", "src/b.py"]), fp)
        self.write(self.tmp, "src/a.py", b"A\n")
        self.assertNotEqual(fingerprint.set_fp(self.tmp, ["src/a.py", "src/b.py"]), fp)
        self.assertEqual(fingerprint.set_fp(self.tmp, []), fingerprint.set_fp(self.tmp, []))

    def test_set_fp_never_reads_a_name_outside_the_project(self):
        project = self.tmp / "proj"
        self.write(project, "src/a.py", b"a\n")
        secret = self.write(self.tmp, "secret.txt", b"one\n")
        outside = ["../secret.txt", "/etc/passwd", "src/../../secret.txt"]
        if sys.platform == "win32":
            outside += [str(secret).replace("\\", "/"), "C:/x", "src\\..\\..\\secret.txt", "a:b"]
        before = fingerprint.set_fp(project, ["src/a.py"] + outside)
        secret.write_bytes(b"two\n")
        self.assertEqual(fingerprint.set_fp(project, ["src/a.py"] + outside), before)
        # Twins: the names still count as members, and an inside change is still seen.
        self.assertNotEqual(fingerprint.set_fp(project, ["src/a.py"]), before)
        self.write(project, "src/a.py", b"A\n")
        self.assertNotEqual(fingerprint.set_fp(project, ["src/a.py"] + outside), before)

    def test_body_fp_tells_undecodable_bytes_apart(self):
        # Two cp1254 specs (PowerShell 5.1 Set-Content) that differ only in a Turkish letter.
        a = self.write(self.tmp, "a.md", b"---\nstatus: approved\n---\nGoal: a\xf0\n")   # 'ağ'
        b = self.write(self.tmp, "b.md", b"---\nstatus: approved\n---\nGoal: a\xfe\n")   # 'aş'
        self.assertNotEqual(fingerprint.file_fp(a), fingerprint.file_fp(b))
        self.assertNotEqual(fingerprint.body_fp(a), fingerprint.body_fp(b))
        self.assertEqual(fingerprint.body_fp(a), _sha(b"Goal: a\xf0\n"))
        # Twins: only the frontmatter differs -> same body; valid UTF-8 keeps its old fingerprint.
        c = self.write(self.tmp, "c.md", b"---\nstatus: draft\n---\r\nGoal: a\xf0\r\n")
        self.assertEqual(fingerprint.body_fp(c), fingerprint.body_fp(a))
        utf8 = self.write(self.tmp, "u.md", "---\nstatus: x\n---\nGoal: aş\n".encode("utf-8"))
        self.assertEqual(fingerprint.body_fp(utf8), _sha("Goal: aş\n".encode("utf-8")))

    def test_body_fp_follows_the_validators_block(self):
        # An indented `---` is not a closer (validator reading), so it stays in the frontmatter.
        a = self.write(self.tmp, "a.md", b"---\nwork_id: x\n  ---\nstatus: draft\n---\n# Spec\n")
        self.assertEqual(fingerprint.body_fp(a), _sha(b"# Spec\n"))


class TestGlobsAndClassify(GitCase):
    def setUp(self):
        super().setUp()
        shared = self.tmp / "_shared.json"
        shared.write_bytes(json.dumps(SHARED_FIXTURE, indent=2).encode("utf-8") + b"\n")
        self.globs = textio.read_json(shared)["test_globs"]

    def test_classify_test_globs(self):
        cases = {
            "tests/x.py": "test", "tests/deep/fixture.json": "test",
            "a/b/test_x.py": "test", "test_root.py": "test",
            "src/x.test.js": "test", "src/x.test.ts": "test", "x.test.ts": "test",
            "pkg/foo_test.go": "test", "foo_test.go": "test",
            "src/__tests__/a.js": "test", "__tests__/a.js": "test", "a/__tests__/b/c.js": "test",
            "Proj/FooTests.cs": "test", "FooTests.cs": "test",
            "spec/a_spec.rb": "test",
            # Clean twins: near misses stay source.
            "src/main.py": "source", "testsuite/x.py": "source", "tests": "source",
            "Tests/x.py": "source", "src/x.test.jsx": "source", "src/x.spec.js": "source",
            "a/b/test_x.pyc": "source", "a/btest_x.py": "source", "src/spec/a.rb": "source",
            "pkg/foo_test.go.orig": "source", "src/__tests__": "source", "FooTests.csx": "source",
            "README.md": "source",
            # Excluded entirely: the package tree and git's own folder.
            "docs/agentic-sdlc/pkg/state.json": None, "docs/agentic-sdlc": None,
            ".git/config": None, ".git": None,
        }
        source, tests = fingerprint.classify(list(cases), self.globs)
        self.assertEqual(sorted(source), sorted(p for p, k in cases.items() if k == "source"))
        self.assertEqual(sorted(tests), sorted(p for p, k in cases.items() if k == "test"))
        self.assertEqual(source, sorted(source))
        self.assertEqual(tests, sorted(tests))
        # No globs: everything that is not excluded is source.
        self.assertEqual(fingerprint.classify(["a.py", "tests/b.py", ".git/x"], []), (["a.py", "tests/b.py"], []))
        self.assertEqual(fingerprint.classify(["a.py", "a.py"], self.globs), (["a.py"], []))

    def test_glob_translator(self):
        table = [
            ("*.py", "a.py", True), ("*.py", "d/a.py", False), ("*", ".hidden", True),
            ("?.py", "a.py", True), ("?.py", "ab.py", False), ("?", "/", False),
            ("a/**/b", "a/b", True), ("a/**/b", "a/x/b", True), ("a/**/b", "a/x/y/b", True),
            ("a/**/b", "ab", False), ("a/**/b", "a/xb", False),
            ("**", "anything/at/all", True), ("**/x", "x", True), ("**/x", "d/e/x", True),
            ("**/x", "dx", False), ("d/**", "d", False), ("d/**", "d/e", True),
            ("a**b", "aXYb", True), ("a**b", "a/b", False),
            ("*.{js,ts}", "a.ts", True), ("*.{js,ts}", "a.jsx", False),
            ("{a,b{c,d}}.txt", "bd.txt", True), ("{a,b{c,d}}.txt", "b.txt", False),
            ("{{a,b}}", "{a}", True), ("{a}", "{a}", True), ("{a}", "a", False),
            ("{a,b", "{a,b", True), ("a.b", "axb", False), ("a+(b)", "a+(b)", True),
            ("[ab].py", "[ab].py", True), ("[ab].py", "a.py", False),
            ("**/n", "line\nbreak/n", True),
        ]
        for pattern, path, want in table:
            with self.subTest(pattern=pattern, path=path):
                self.assertIs(fingerprint.glob_match(path, pattern), want)

    def test_brace_expansion_is_bounded(self):
        with self.assertRaises(ValueError):
            fingerprint.glob_match("x", "{a,b}" * 12)

    def test_excluded_paths(self):
        for path, want in (("docs/agentic-sdlc", True), ("docs/agentic-sdlc/a/b", True),
                           (".git", True), (".git/HEAD", True), ("docs/agentic-sdlc-x", False),
                           ("docs/agentic", False), (".github/workflows/ci.yml", False),
                           ("src/.git/x", False)):
            with self.subTest(path=path):
                self.assertIs(fingerprint.is_excluded(path), want)

    def test_excluded_roots_ignore_ascii_case(self):
        # On a case-insensitive file system the package lands in an existing `Docs/` folder.
        for path, want in (("Docs/agentic-sdlc/p/state.json", True), ("DOCS/AGENTIC-SDLC", True),
                           ("docs/Agentic-Sdlc/p/.lock", True), (".GIT/config", True),
                           ("Docs/agentic-sdlc-notes/x", False), ("Docs/agentic/x", False),
                           ("src/Docs/agentic-sdlc/x", False), ("Docs/readme.md", False),
                           ("docſ/agentic-sdlc/x", False)):  # only ASCII letters fold
            with self.subTest(path=path):
                self.assertIs(fingerprint.is_excluded(path), want)
        self.assertEqual(fingerprint.classify(["Docs/agentic-sdlc/p/state.json", "Docs/x.md", "tests/t.py"],
                                              self.globs), (["Docs/x.md"], ["tests/t.py"]))

    def test_walk_skips_the_package_tree_in_any_ascii_case(self):
        root = self.tmp / "proj"
        self.write(root, "Docs/index.md", b"i\n")
        self.write(root, "src/a.py", b"a\n")
        self.write(root, "Docs/agentic-sdlc/add-export/state.json", b"{}\n")
        snap = fingerprint.walk_snapshot(root)
        self.assertEqual(sorted(snap), ["Docs/index.md", "src/a.py"])
        self.write(root, "Docs/agentic-sdlc/add-export/runs.jsonl", b"{}\n")
        self.assertEqual(fingerprint.snapshot_changed(root, snap), [])
        self.write(root, "Docs/index.md", b"i2\n")  # clean twin
        self.assertEqual(fingerprint.snapshot_changed(root, snap), ["Docs/index.md"])


class TestWalkSnapshot(GitCase):
    def _tree(self, root, count):
        for i in range(count):
            self.write(root, "src/f%02d.py" % i, b"x%d\n" % i)
        for skipped in (".git/objects/x", "node_modules/m/i.js", ".venv/lib/a.py", "venv/b.py",
                        "dist/out.js", "build/out.o", "src/__pycache__/f.pyc",
                        "docs/agentic-sdlc/pkg/state.json", "sub/node_modules/n.js"):
            self.write(root, skipped, b"skip\n")

    def test_walk_snapshot_limit(self):
        root = self.tmp / "proj"
        self._tree(root, 5)
        snap = fingerprint.walk_snapshot(root, limit=5)  # exactly the limit is allowed
        self.assertEqual(sorted(snap), ["src/f%02d.py" % i for i in range(5)])
        self.assertEqual(list(snap), sorted(snap))
        self.assertEqual(snap["src/f00.py"], fingerprint.file_fp(root / "src" / "f00.py"))
        with self.assertRaises(textio.SdlcError) as ctx:
            fingerprint.walk_snapshot(root, limit=4)
        self.assertEqual((ctx.exception.code, ctx.exception.message), (2, "not_a_git_repo_and_too_large"))
        self.write(root, "docs/agentic-sdlc-notes/kept.md", b"k\n")  # boundary twin is walked
        self.assertIn("docs/agentic-sdlc-notes/kept.md", fingerprint.walk_snapshot(root))

    def test_snapshot_changed(self):
        root = self.tmp / "proj"
        self._tree(root, 3)
        baseline = fingerprint.walk_snapshot(root)
        self.assertEqual(fingerprint.snapshot_changed(root, baseline), [])
        self.write(root, "src/f00.py", b"x0\r\n")  # CRLF only: not a change
        self.write(root, "src/f01.py", b"edited\n")
        (root / "src" / "f02.py").unlink()
        self.write(root, "src/new.py", b"n\n")
        self.write(root, "node_modules/m/i.js", b"ignored edit\n")
        self.write(root, "docs/agentic-sdlc/pkg/state.json", b"ignored edit\n")
        self.assertEqual(fingerprint.snapshot_changed(root, baseline),
                         ["src/f01.py", "src/f02.py", "src/new.py"])

    def test_walk_snapshot_records_symlinked_folders_without_entering_them(self):
        root = self.tmp / "proj"
        self._tree(root, 1)
        outside = self.tmp / "outside"
        self.write(outside, "big.txt", b"never walked\n")
        try:
            os.symlink(str(outside), str(root / "linked"), target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available here")
        snap = fingerprint.walk_snapshot(root)
        self.assertIn("linked", snap)
        self.assertNotIn("linked/big.txt", snap)

    @unittest.skipUnless(sys.platform == "win32", "Windows junctions")
    def test_walk_snapshot_does_not_enter_a_junction(self):
        import _winapi
        root = self.tmp / "proj"
        self._tree(root, 1)
        self.write(root, "real/inside.txt", b"walked once\n")
        outside = self.tmp / "outside"
        self.write(outside, "big.txt", b"never walked\n")
        _winapi.CreateJunction(str(outside), str(root / "junction"))
        _winapi.CreateJunction(str(root), str(root / "loop"))  # a junction to its own root
        snap = fingerprint.walk_snapshot(root)
        self.assertIn("junction", snap)
        self.assertIn("loop", snap)
        self.assertIn("real/inside.txt", snap)  # clean twin: a plain folder is walked
        self.assertFalse([key for key in snap if key.startswith(("junction/", "loop/"))])


# ---------------------------------------------------------------------------------------------
# probes
# ---------------------------------------------------------------------------------------------

class TestProbes(GitCase):
    def setUp(self):
        super().setUp()
        probes._reset_cache()
        self.addCleanup(probes._reset_cache)
        self.project = self.tmp / "proj"
        self.write(self.project, "package.json",
                   json.dumps({"dependencies": {"left-pad": "1"}, "scripts": {"test": "x"}}).encode("utf-8"))
        self.write(self.project, "api/a.py", b"a\n")
        self.write(self.project, "ui/b.ts", b"b\n")

    def test_probes_report_the_detector_values(self):
        result = probes.start_probes(self.project)
        self.assertEqual((result["explore_mode"], result["deps"], result["toolchain"]),
                         ("parallel", "external", "present"))
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["details"]["explore_mode"]["layers"], ["api", "ui"])
        self.assertEqual(result["details"]["deps"]["manifests"], ["package.json"])
        self.assertEqual(result["details"]["toolchain"]["toolchains"], ["node"])
        self.assertIn("repo", result["git"])
        json.dumps(result)  # the probes land in state.json

    def test_probes_survive_detector_exception(self):
        module = probes.detector()
        with mock.patch.object(module, "probe_deps", side_effect=RuntimeError("boom ğ")):
            result = probes.start_probes(self.project)
        self.assertEqual(result["deps"], "error")
        self.assertEqual((result["explore_mode"], result["toolchain"]), ("parallel", "present"))
        self.assertEqual(len(result["errors"]), 1)
        self.assertTrue(result["errors"][0].startswith("deps: RuntimeError: boom"))
        self.assertNotIn("deps", result["details"])
        # Clean twin: unpatched, no errors.
        self.assertEqual(probes.start_probes(self.project)["errors"], [])

    def test_probes_survive_a_malformed_detector_result(self):
        module = probes.detector()
        malformed = [{"toolchains": []}, {"toolchain_probe": ""}, {"toolchain_probe": None},
                     {"toolchain_probe": ["present"]}, "present",
                     {"toolchain_probe": "present", "toolchains": [object()]}]
        for bad in malformed:
            with self.subTest(result=repr(bad)):
                with mock.patch.object(module, "probe_toolchain", return_value=bad):
                    result = probes.start_probes(self.project)
                self.assertEqual(result["toolchain"], "error")
                self.assertEqual(len(result["errors"]), 1)
                self.assertTrue(result["errors"][0].startswith("toolchain: "))
                self.assertNotIn("toolchain", result["details"])
                self.assertEqual(result["deps"], "external")

    def test_probe_error_text_is_masked_and_one_bounded_line(self):
        samples = json.loads((REPO / "tests" / "fixtures" / "mask-samples.json").read_text(encoding="utf-8"))
        token = next("".join(s["masked"]) for s in samples["secrets"] if s["name"] == "github-classic")
        module = probes.detector()
        message = "bad\nline " + token + " " + "x" * 1000
        with mock.patch.object(module, "detect", side_effect=OSError(message)):
            entry = probes.start_probes(self.project)["errors"][0]
        self.assertTrue(entry.startswith("explore_mode: OSError: bad line "))
        self.assertNotIn(token, entry)
        self.assertIn("***MASKED***", entry)
        self.assertNotIn("\n", entry)
        self.assertLessEqual(len(entry), 300)

    def test_probes_survive_a_missing_detector(self):
        empty_root = self.tmp / "plugin"
        (empty_root / "scripts").mkdir(parents=True)
        probes._reset_cache()
        with mock.patch.object(probes.paths, "plugin_root", return_value=empty_root):
            result = probes.start_probes(self.project)
        self.assertEqual((result["explore_mode"], result["deps"], result["toolchain"]),
                         ("error", "error", "error"))
        self.assertEqual([e.split(":", 1)[0] for e in result["errors"]],
                         ["explore_mode", "deps", "toolchain"])

    def test_probes_load_the_detector_from_the_plugin_root_only(self):
        marker = self.tmp / "planted-ran"
        planted = ("import pathlib\npathlib.Path(%r).write_text('x')\n"
                   "def detect(p): raise SystemExit(9)\n" % str(marker))
        self.write(self.project, "detect_context.py", planted.encode("utf-8"))
        self.write(self.project, "scripts/detect_context.py", planted.encode("utf-8"))
        with mock.patch.object(sys, "path", [str(self.project)] + list(sys.path)):
            module = probes.detector()
            result = probes.start_probes(self.project)
        self.assertEqual(Path(module.__file__).resolve(),
                         (paths.plugin_root() / "scripts" / "detect_context.py").resolve())
        self.assertFalse(marker.exists())
        self.assertEqual(result["explore_mode"], "parallel")


if __name__ == "__main__":
    unittest.main()
