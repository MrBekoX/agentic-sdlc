"""Foundation modules of the sdlc runner (plan Task 1; contract docs/agentic-sdlc/notes/2026-10-22-runner-contract.md).

textio, paths, lock, logs, frontmatter, schema and the scripts/sdlc.py entry. Every hostile case
has a clean twin, so a check that always passes (or always fails) is caught here.
"""
import errno
import hashlib
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from sdlc_runner import RUNNER_VERSION, frontmatter, lock, logs, paths, schema, textio  # noqa: E402
import validate_artifacts  # noqa: E402

GIT = shutil.which("git")
WIN = sys.platform == "win32"
# What the lock stores instead of the host name (design §4: "a hash of the host name, not the name").
HOST_ID = hashlib.sha256(socket.gethostname().encode("utf-8", "surrogateescape")).hexdigest()[:16]
# Repository-location variables a parent git (a hook, `git rebase -x`) exports; git's own list
# (`git rev-parse --local-env-vars`). Removed for every test so no git call reaches another repo.
LOCAL_GIT_ENV = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
    "GIT_OBJECT_DIRECTORY", "GIT_DIR", "GIT_WORK_TREE", "GIT_IMPLICIT_WORK_TREE", "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE", "GIT_NO_REPLACE_OBJECTS", "GIT_REPLACE_REF_BASE", "GIT_PREFIX",
    "GIT_SHALLOW_FILE", "GIT_COMMON_DIR",
)


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _dead_pid():
    """The pid of a child that has already exited."""
    proc = subprocess.run(
        [sys.executable, "-I", "-c", "import os; print(os.getpid())"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    return int(proc.stdout.strip())


def _child(code, timeout=60):
    """Run `code` in a fresh interpreter that imports this checkout's sdlc_runner.

    Used where the defect under test is a hang: a timeout raises here instead of hanging the suite.
    """
    prelude = "import sys\nsys.path.insert(0, %r)\n" % str(SCRIPTS)
    return subprocess.run([sys.executable, "-I", "-B", "-c", prelude + textwrap.dedent(code)],
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        # git configuration and discovery isolated from the machine and from a parent git's
        # exported repository variables, kept outside self.tmp so listings of it stay exact.
        env_dir = tempfile.TemporaryDirectory()
        self.addCleanup(env_dir.cleanup)
        global_cfg = Path(env_dir.name) / "global.gitconfig"
        global_cfg.write_bytes(b"")
        patcher = mock.patch.dict(os.environ, {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(global_cfg),
            "XDG_CONFIG_HOME": str(Path(env_dir.name) / "xdg"),
            "GIT_CEILING_DIRECTORIES": str(Path(self._td.name).resolve()),
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in LOCAL_GIT_ENV:
            os.environ.pop(name, None)

    def make_program(self, folder, name):
        """An empty program file named `name` (plus .exe on Windows) that PATH lookup accepts."""
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        program = folder / (name + (".exe" if WIN else ""))
        program.write_bytes(b"")
        program.chmod(0o755)
        if not WIN and not os.access(str(program), os.X_OK):
            self.skipTest("this temp folder does not allow programs (a noexec mount)")
        return program

    def make_readonly(self, directory):
        """Make `directory` refuse new files, or skip when this platform/user cannot."""
        directory = Path(directory)
        if os.name == "posix":
            os.chmod(str(directory), 0o555)
            self.addCleanup(os.chmod, str(directory), 0o755)
        elif WIN:
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

    def symlink(self, target, link, directory=False):
        try:
            os.symlink(str(target), str(link), target_is_directory=directory)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available here")


class TestTextio(TempDirCase):
    def test_write_text_atomic_lf_and_utf8(self):
        target = self.tmp / "sub" / "out.md"
        textio.write_text_atomic(target, "line ğ\nsecond → line\n")
        self.assertEqual(target.read_bytes(), "line ğ\nsecond → line\n".encode("utf-8"))
        self.assertEqual(target.read_bytes().count(b"\r\n"), 0)
        # Replacing an existing file leaves no temp file behind.
        textio.write_text_atomic(target, "new\n")
        self.assertEqual(target.read_bytes(), b"new\n")
        self.assertEqual(sorted(p.name for p in target.parent.iterdir()), ["out.md"])

    def test_write_text_atomic_failure_keeps_old_file_and_no_temp(self):
        target = self.tmp / "keep.md"
        target.write_bytes(b"old\n")
        with mock.patch.object(textio.os, "replace", side_effect=OSError("boom")):
            with self.assertRaises(textio.SdlcError) as ctx:
                textio.write_text_atomic(target, "new\n")
        self.assertEqual((ctx.exception.code, ctx.exception.message), (2, "unwritable:" + str(target)))
        self.assertEqual(target.read_bytes(), b"old\n")
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["keep.md"])

    def test_write_text_atomic_refused_create_is_a_prompt_named_error(self):
        # tempfile.mkstemp retries a refused create up to os.TMP_MAX (2**31 - 1) times on Windows
        # while the folder looks writable, so this runs in a child that a timeout can stop.
        target = self.tmp / "pkg" / "state.json"
        target.parent.mkdir()
        proc = _child('''
            import os
            from sdlc_runner import textio
            real_open, folder = os.open, os.path.dirname(%r)
            def refuse(path, *args, **kwargs):
                if os.path.dirname(os.path.abspath(path)) == folder:
                    raise PermissionError(13, "denied")
                return real_open(path, *args, **kwargs)
            os.open = refuse
            try:
                textio.write_text_atomic(%r, "x")
            except textio.SdlcError as exc:
                print("SdlcError", exc.code, exc.message)
            except BaseException as exc:
                print("raw", type(exc).__name__)
            else:
                print("written")
        ''' % (str(target), str(target)), timeout=30)
        self.assertEqual(proc.stdout.strip(), "SdlcError 2 unwritable:" + str(target), proc.stderr)
        self.assertEqual(os.listdir(str(target.parent)), [])

    def test_write_text_atomic_into_a_folder_that_refuses_files(self):
        folder = self.tmp / "denied"
        folder.mkdir()
        target = folder / "state.json"
        # Clean twin first: the same folder accepts the write before it is locked down.
        textio.write_text_atomic(folder / "before.json", "{}\n")
        (folder / "before.json").unlink()
        self.make_readonly(folder)
        proc = _child('''
            from sdlc_runner import textio
            try:
                textio.write_text_atomic(%r, "x")
            except textio.SdlcError as exc:
                print("SdlcError", exc.code, exc.message)
            except BaseException as exc:
                print("raw", type(exc).__name__)
        ''' % str(target), timeout=30)
        self.assertEqual(proc.stdout.strip(), "SdlcError 2 unwritable:" + str(target), proc.stderr)

    def test_write_text_atomic_unmakeable_parent_is_a_named_error(self):
        blocker = self.tmp / "afile"
        blocker.write_bytes(b"x")
        target = blocker / "sub" / "state.json"
        with self.assertRaises(textio.SdlcError) as ctx:
            textio.write_text_atomic(target, "x")
        self.assertEqual((ctx.exception.code, ctx.exception.message), (2, "unwritable:" + str(target)))

    def test_lone_surrogates_are_kept_in_json_and_refused_in_text(self):
        # POSIX argv turns undecodable bytes into lone surrogates (surrogateescape).
        target = self.tmp / "state.json"
        textio.write_json_atomic(target, {"q": "ok \udcff", "argv": ["tests/t\udcff.py"]})
        raw = target.read_bytes()
        raw.decode("utf-8")  # strict: the file stays valid UTF-8
        self.assertEqual(textio.read_json(target), {"q": "ok \udcff", "argv": ["tests/t\udcff.py"]})
        textio.write_json_atomic(target, {"q": "ğ"})  # clean twin: characters stay readable
        self.assertIn("ğ".encode("utf-8"), target.read_bytes())
        plain = self.tmp / "request.md"
        with self.assertRaises(textio.SdlcError) as ctx:
            textio.write_text_atomic(plain, "ok \udcff")
        self.assertEqual((ctx.exception.code, ctx.exception.message), (2, "unencodable_text:" + str(plain)))
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["state.json"])

    def test_write_text_atomic_within_refuses_a_linked_folder(self):
        pkg = self.tmp / "pkg"
        pkg.mkdir()
        outside = self.tmp / "outside"
        outside.mkdir()
        self.symlink(outside, pkg / "runs", directory=True)
        with self.assertRaises(textio.SdlcError) as ctx:
            textio.write_text_atomic(pkg / "runs" / "1.tail.txt", "x", within=pkg)
        self.assertEqual((ctx.exception.code, ctx.exception.message), (2, "linked_path:runs"))
        self.assertEqual(os.listdir(str(outside)), [])
        with self.assertRaises(textio.SdlcError) as ctx:
            textio.write_text_atomic(outside / "x.md", "x", within=pkg)
        self.assertEqual(ctx.exception.message, "outside_root:" + str(outside / "x.md"))
        # Clean twins: plain sub-folders (new or existing) are written.
        textio.write_text_atomic(pkg / "spec" / "deep" / "x.md", "x", within=pkg)
        textio.write_text_atomic(pkg / "state.json", "{}", within=pkg)
        self.assertEqual((pkg / "spec" / "deep" / "x.md").read_bytes(), b"x")

    @unittest.skipUnless(WIN, "Windows junctions")
    def test_write_text_atomic_within_refuses_a_junction(self):
        import _winapi
        pkg = self.tmp / "pkg"
        pkg.mkdir()
        outside = self.tmp / "outside"
        outside.mkdir()
        _winapi.CreateJunction(str(outside), str(pkg / "draft"))
        with self.assertRaises(textio.SdlcError) as ctx:
            textio.write_text_atomic(pkg / "draft" / "brief.md", "x", within=pkg)
        self.assertEqual(ctx.exception.message, "linked_path:draft")
        self.assertEqual(os.listdir(str(outside)), [])

    def test_read_text_refuses_bytes_that_are_not_utf8(self):
        target = self.tmp / "spec.md"
        target.write_bytes(b"---\nstatus: draft\n---\na\xf0\n")  # cp1254 'ğ' (PowerShell 5.1 Set-Content)
        with self.assertRaises(textio.SdlcError) as ctx:
            textio.read_text(target)
        self.assertEqual((ctx.exception.code, ctx.exception.message), (2, "not_utf8:" + str(target)))
        with self.assertRaises(textio.SdlcError):
            frontmatter.body_text(target)
        # The lossless reading keeps each undecodable byte apart (fingerprints use it).
        self.assertEqual(textio.read_text(target, errors="surrogateescape"), "---\nstatus: draft\n---\na\udcf0\n")
        target.write_bytes(b"\xef\xbb\xbfa\xc4\x9f\r\n")  # clean twin
        self.assertEqual(textio.read_text(target), "ağ\n")

    def test_read_text_strips_bom_and_crlf(self):
        hostile = self.tmp / "hostile.md"
        hostile.write_bytes(b"\xef\xbb\xbf---\r\nk: v\r\n---\r\nbody \xc4\x9f\r\n")
        clean = self.tmp / "clean.md"
        clean.write_bytes(b"---\nk: v\n---\nbody \xc4\x9f\n")
        self.assertEqual(textio.read_text(hostile), "---\nk: v\n---\nbody ğ\n")
        self.assertEqual(textio.read_text(hostile), textio.read_text(clean))

    def test_json_roundtrip_sorted_indent_trailing_newline(self):
        target = self.tmp / "s.json"
        textio.write_json_atomic(target, {"b": 1, "a": ["ğ", None]})
        raw = target.read_bytes()
        self.assertTrue(raw.endswith(b"}\n"))
        self.assertNotIn(b"\r\n", raw)
        self.assertLess(raw.index(b'"a"'), raw.index(b'"b"'))
        self.assertIn('  "a": [\n'.encode("utf-8"), raw)
        self.assertEqual(textio.read_json(target), {"a": ["ğ", None], "b": 1})

    def test_now_iso_is_utc_z_seconds(self):
        value = textio.now_iso()
        self.assertRegex(value, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_sdlc_error_carries_code_and_message(self):
        err = textio.SdlcError(4, "refused:x")
        self.assertEqual((err.code, err.message, str(err)), (4, "refused:x", "refused:x"))
        self.assertIsInstance(err, Exception)

    def test_textio_utf8_output_on_legacy_codepage(self):
        out_buf, err_buf = io.BytesIO(), io.BytesIO()
        out = io.TextIOWrapper(out_buf, encoding="cp1254", errors="strict")
        err = io.TextIOWrapper(err_buf, encoding="cp1254", errors="strict")
        # Clean twin: the legacy code page itself cannot print the arrow.
        with self.assertRaises(UnicodeEncodeError):
            out.write("→")
        with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err):
            textio.utf8_output()
            print("→ ğ")
            print("→ ğ", file=sys.stderr)
            sys.stdout.flush()
            sys.stderr.flush()
        self.assertEqual(out_buf.getvalue().decode("utf-8").strip(), "→ ğ")
        self.assertEqual(err_buf.getvalue().decode("utf-8").strip(), "→ ğ")

    def test_utf8_output_tolerates_streams_without_reconfigure(self):
        with mock.patch.object(sys, "stdout", io.StringIO()), mock.patch.object(sys, "stderr", None):
            textio.utf8_output()  # must not raise
            print("→ ğ")


class TestPaths(TempDirCase):
    def test_plugin_root_is_repo_root(self):
        self.assertEqual(paths.plugin_root(), REPO)
        self.assertTrue((paths.plugin_root() / "scripts" / "sdlc_runner" / "paths.py").is_file())

    def test_slug_rules(self):
        for good in ("add-export", "a", "0-fix", "x" * 64):
            with self.subTest(good=good):
                self.assertTrue(paths.valid_slug(good))
        for bad in ("Specs", "specs", "plans", "evidence", "notes", "spec", "plan", "a_b", "x" * 65,
                    "", "-lead", "a/b", "a b", "add-export\n", "con", "nul", "com1", "lpt9", None, 7):
            with self.subTest(bad=bad):
                self.assertFalse(paths.valid_slug(bad))

    def test_slug_rule_matches_the_resolver(self):
        import resolve_work_package as rwp
        corpus = ["add-export", "a", "Specs", "plans", "spec", "a_b", "x" * 64, "x" * 65, "-x", "a.b", "9z"]
        for s in corpus:
            with self.subTest(slug=s):
                self.assertEqual(paths.valid_slug(s), rwp.is_valid_slug(s))

    def test_work_id_rules(self):
        for good in ("add-export", "AB.1_x", "a", "Fix-42.v2", "x" * 64):
            with self.subTest(good=good):
                self.assertTrue(paths.valid_work_id(good))
        for bad in ("", ".hidden", "-x", "_x", "a..b", "x" * 65, "a/b", "a\\b", "a b", "ğ",
                    "abc\n", "con", "CON.md", "aux.v2", None):
            with self.subTest(bad=bad):
                self.assertFalse(paths.valid_work_id(bad))

    def test_slug_from_work_id(self):
        self.assertEqual(paths.slug_from_work_id("Add_Export.v2"), "add-export-v2")
        self.assertEqual(paths.slug_from_work_id("add-export"), "add-export")
        self.assertEqual(paths.slug_from_work_id("1.x_"), "1-x")
        self.assertTrue(paths.valid_slug(paths.slug_from_work_id("Fix-42.v2")))

    def test_package_dir(self):
        self.assertEqual(paths.AGENTIC_ROOT, "docs/agentic-sdlc")
        self.assertEqual(paths.package_dir(self.tmp, "add-export"),
                         self.tmp / "docs" / "agentic-sdlc" / "add-export")
        for bad in ("../x", "specs", "A"):
            with self.subTest(bad=bad):
                with self.assertRaises(textio.SdlcError) as ctx:
                    paths.package_dir(self.tmp, bad)
                self.assertEqual(ctx.exception.code, 2)

    def test_project_root_override_wins(self):
        other = self.tmp / "other"
        other.mkdir()
        self.assertEqual(paths.project_root(self.tmp, other), other.resolve())

    def test_project_root_without_git_repo_is_cwd(self):
        sub = self.tmp / "plain"
        sub.mkdir()
        with mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": str(self.tmp.resolve())}):
            self.assertEqual(paths.project_root(sub), sub.resolve())

    @unittest.skipUnless(GIT, "git not installed")
    def test_project_root_is_git_toplevel(self):
        repo = self.tmp / "repo"
        deep = repo / "a" / "b"
        deep.mkdir(parents=True)
        subprocess.run([GIT, "init", "-q", str(repo)], check=True, capture_output=True, timeout=60)
        self.assertEqual(paths.project_root(deep).resolve(), repo.resolve())

    @unittest.skipUnless(GIT, "git not installed")
    def test_project_root_ignores_repository_location_variables(self):
        mine = self.tmp / "mine"
        deep = mine / "a" / "b"
        deep.mkdir(parents=True)
        other = self.tmp / "other"
        other.mkdir()
        for repo in (mine, other):
            subprocess.run([GIT, "init", "-q", str(repo)], check=True, capture_output=True, timeout=60)
        self.assertEqual(paths.project_root(deep).resolve(), mine.resolve())  # clean twin
        for hostile in ({"GIT_DIR": str(other / ".git")},
                        {"GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other)}):
            with self.subTest(env=sorted(hostile)), mock.patch.dict(os.environ, hostile):
                self.assertEqual(paths.project_root(deep).resolve(), mine.resolve())
                self.assertEqual(paths.package_dir(paths.project_root(deep), "add-export").resolve(),
                                 (mine / "docs" / "agentic-sdlc" / "add-export").resolve())

    def test_resolve_program_refuses_a_name_with_a_path(self):
        bin_dir = self.tmp / "bin"
        project = self.tmp / "project"
        tool = self.make_program(bin_dir, "tool")
        self.make_program(bin_dir / "sub", "x")
        evil = self.make_program(project, "evil")
        self.make_program(project, "pytest")
        with mock.patch.dict(os.environ, {"PATH": str(bin_dir)}):
            self.assertEqual(paths.resolve_program("tool"), str(tool))  # clean twin
            for name in (str(evil), str(project / "pytest"), os.path.join("..", "project", "pytest"),
                         "sub/x", "sub" + os.sep + "x", "", ".", ".."):
                with self.subTest(name=name):
                    self.assertIsNone(paths.resolve_program(name))
            if WIN:
                for name in ("C:tool", "tool.exe:stream"):
                    with self.subTest(name=name):
                        self.assertIsNone(paths.resolve_program(name))

    def test_resolve_program_shims_only_on_request(self):
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        if not WIN:
            npm = self.make_program(bin_dir, "npm")
            with mock.patch.dict(os.environ, {"PATH": str(bin_dir)}):
                self.assertEqual(paths.resolve_program("npm"), str(npm))
                self.assertEqual(paths.resolve_program("npm", shims=True), str(npm))
            return
        shim = bin_dir / "npm.cmd"
        shim.write_bytes(b"@echo off\r\n")
        (bin_dir / "lint.bat").write_bytes(b"@echo off\r\n")
        with mock.patch.dict(os.environ, {"PATH": str(bin_dir)}):
            self.assertIsNone(paths.resolve_program("npm"))
            self.assertIsNone(paths.resolve_program("npm.cmd"))  # an explicit shim needs `shims` too
            self.assertIsNone(paths.resolve_program("lint.bat"))
            self.assertEqual(paths.resolve_program("npm", shims=True), str(shim))
            self.assertEqual(paths.resolve_program("NPM.CMD", shims=True), str(bin_dir / "NPM.CMD"))
            self.assertEqual(paths.resolve_program("lint", shims=True), str(bin_dir / "lint.bat"))
            exe = self.make_program(bin_dir, "npm")  # a real program beats a shim in the same folder
            self.assertEqual(paths.resolve_program("npm", shims=True), str(exe))
            self.assertEqual(paths.resolve_program("npm"), str(exe))

    def test_resolve_program_skips_path_entries_inside_the_excluded_folder(self):
        project = self.tmp / "project"
        planted = self.make_program(project / "bin", "tool")
        real = self.make_program(self.tmp / "system", "tool")
        both = str(project / "bin") + os.pathsep + str(self.tmp / "system")
        with mock.patch.dict(os.environ, {"PATH": both}):
            self.assertEqual(paths.resolve_program("tool"), str(planted))  # the hazard is real
            self.assertEqual(paths.resolve_program("tool", exclude=project), str(real))
            self.assertEqual(paths.resolve_program("tool", exclude=self.tmp / "elsewhere"), str(planted))
        with mock.patch.dict(os.environ, {"PATH": str(project / "bin")}):
            self.assertIsNone(paths.resolve_program("tool", exclude=project))

    def test_package_dir_refuses_linked_components(self):
        project = self.tmp / "proj"
        root = project / "docs" / "agentic-sdlc"
        root.mkdir(parents=True)
        outside = self.tmp / "outside"
        outside.mkdir()
        self.symlink(outside, root / "feat", directory=True)
        with self.assertRaises(textio.SdlcError) as ctx:
            paths.package_dir(project, "feat")
        self.assertEqual((ctx.exception.code, ctx.exception.message),
                         (2, "linked_package_path:docs/agentic-sdlc/feat"))
        self.assertEqual(paths.package_dir(project, "other"), root / "other")  # clean twin
        linked_docs = self.tmp / "proj2"
        linked_docs.mkdir()
        self.symlink(outside, linked_docs / "docs", directory=True)
        with self.assertRaises(textio.SdlcError) as ctx:
            paths.package_dir(linked_docs, "feat")
        self.assertEqual(ctx.exception.message, "linked_package_path:docs")

    @unittest.skipUnless(WIN, "Windows junctions")
    def test_package_dir_refuses_a_junction(self):
        import _winapi
        project = self.tmp / "proj"
        project.mkdir()
        outside = self.tmp / "outside"
        outside.mkdir()
        _winapi.CreateJunction(str(outside), str(project / "docs"))
        with self.assertRaises(textio.SdlcError) as ctx:
            paths.package_dir(project, "feat")
        self.assertEqual(ctx.exception.message, "linked_package_path:docs")

    def test_resolve_program_ignores_relative_path_entries(self):
        name = "fakeprog"
        exe = self.make_program(self.tmp, name)
        cwd = os.getcwd()
        try:
            os.chdir(str(self.tmp))
            with mock.patch.dict(os.environ, {"PATH": "." + os.pathsep + ""}):
                self.assertIsNone(paths.resolve_program(name))
            with mock.patch.dict(os.environ, {"PATH": str(self.tmp)}):
                found = paths.resolve_program(name)
        finally:
            os.chdir(cwd)
        self.assertIsNotNone(found)
        self.assertTrue(os.path.isabs(found))
        self.assertEqual(Path(found).resolve(), exe.resolve())


class TestLock(TempDirCase):
    def test_lock_exclusive(self):
        path = self.tmp / "pkg" / ".lock"
        first = lock.PackageLock(path)
        first.acquire(timeout=1)
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual((meta["pid"], meta["host"]), (os.getpid(), HOST_ID))
            with self.assertRaises(textio.SdlcError) as ctx:
                lock.PackageLock(path).acquire(timeout=0.2)
            self.assertEqual(ctx.exception.code, 2)
            self.assertEqual(ctx.exception.message, "locked:%d@%s" % (os.getpid(), HOST_ID))
        finally:
            first.release()
        self.assertFalse(path.exists())
        with lock.PackageLock(path) as again:  # free again once released
            self.assertTrue(path.exists())
            self.assertIsInstance(again, lock.PackageLock)
        self.assertFalse(path.exists())

    def _write_lock(self, path, pid, host, ts, **extra):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict({"pid": pid, "host": host, "ts": ts}, **extra)), encoding="utf-8")

    def test_lock_stores_a_host_hash_not_the_host_name(self):
        path = self.tmp / ".lock"
        with lock.PackageLock(path):
            meta = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(meta["host"], HOST_ID)
        self.assertRegex(meta["host"], r"^[0-9a-f]{16}$")
        self.assertNotEqual(meta["host"], socket.gethostname())
        self.assertEqual(sorted(meta), sorted(["host", "nonce", "pid", "ts"] + (["start"] if "start" in meta else [])))

    def test_lock_stale_is_broken_after_timeout(self):
        path = self.tmp / ".lock"
        self._write_lock(path, _dead_pid(), HOST_ID, "2000-01-01T00:00:00Z")
        holder = lock.PackageLock(path, stale_seconds=600)
        holder.acquire(timeout=1)
        try:
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["pid"], os.getpid())
        finally:
            holder.release()

    def test_lock_old_but_alive_on_this_host_is_kept(self):
        path = self.tmp / ".lock"
        self._write_lock(path, os.getpid(), HOST_ID, "2000-01-01T00:00:00Z")
        with self.assertRaises(textio.SdlcError):
            lock.PackageLock(path, stale_seconds=600).acquire(timeout=0.2)
        self.assertTrue(path.exists())

    def test_lock_old_held_by_another_live_process_is_kept(self):
        # Exercises the real liveness probe (OpenProcess on Windows, kill(pid, 0) on POSIX), which
        # the own-pid case above short-circuits. A lock without a process start (an older runner)
        # is judged by the pid alone.
        child = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(60)"])
        try:
            path = self.tmp / ".lock"
            self._write_lock(path, child.pid, HOST_ID, "2000-01-01T00:00:00Z")
            with self.assertRaises(textio.SdlcError) as ctx:
                lock.PackageLock(path, stale_seconds=600).acquire(timeout=0.2)
            self.assertEqual(ctx.exception.message, "locked:%d@%s" % (child.pid, HOST_ID))
        finally:
            child.kill()
            child.wait(timeout=30)

    def test_lock_whose_pid_now_names_another_process_is_broken(self):
        # A killed runner's pid reused by an unrelated live process: the start time tells them apart.
        child = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(60)"])
        try:
            started = lock._process_start(child.pid)
            if started is None:
                self.skipTest("this platform does not report a process start")
            path = self.tmp / ".lock"
            # Twin: the lock of the live process itself is kept.
            self._write_lock(path, child.pid, HOST_ID, "2000-01-01T00:00:00Z", start=started)
            with self.assertRaises(textio.SdlcError):
                lock.PackageLock(path, stale_seconds=600).acquire(timeout=0.2)
            self._write_lock(path, child.pid, HOST_ID, "2000-01-01T00:00:00Z", start="x" + started)
            with lock.PackageLock(path, stale_seconds=600):
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["pid"], os.getpid())
            # Our own pid, once held by an earlier process, is not this process either.
            self._write_lock(path, os.getpid(), HOST_ID, "2000-01-01T00:00:00Z", start="x" + started)
            with lock.PackageLock(path, stale_seconds=600):
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["start"],
                                 lock._process_start(os.getpid()))
            # A recent lock is kept whatever its start says.
            self._write_lock(path, child.pid, HOST_ID, textio.now_iso(), start="x" + started)
            with self.assertRaises(textio.SdlcError):
                lock.PackageLock(path, stale_seconds=600).acquire(timeout=0.2)
        finally:
            child.kill()
            child.wait(timeout=30)

    def test_lock_recent_with_dead_pid_is_kept(self):
        path = self.tmp / ".lock"
        self._write_lock(path, _dead_pid(), HOST_ID, textio.now_iso())
        with self.assertRaises(textio.SdlcError):
            lock.PackageLock(path, stale_seconds=600).acquire(timeout=0.2)

    def test_lock_old_from_another_host_is_broken(self):
        path = self.tmp / ".lock"
        self._write_lock(path, os.getpid(), "some-other-host.invalid", "2000-01-01T00:00:00Z")
        with lock.PackageLock(path, stale_seconds=600):
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["host"], HOST_ID)

    def test_lock_old_empty_or_corrupt_file_is_broken_and_a_fresh_one_kept(self):
        # A runner killed between the O_EXCL create and its write leaves an empty lock file.
        path = self.tmp / ".lock"
        for raw in (b"", b"{not json", b"[1, 2]"):
            with self.subTest(raw=raw):
                path.write_bytes(raw)
                old = time.time() - 3600
                os.utime(str(path), (old, old))
                with lock.PackageLock(path, stale_seconds=600):
                    self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["pid"], os.getpid())
                path.write_bytes(raw)  # twin: the same content, fresh
                with self.assertRaises(textio.SdlcError) as ctx:
                    lock.PackageLock(path, stale_seconds=600).acquire(timeout=0.2)
                self.assertEqual(ctx.exception.message, "locked:unknown@unknown")
                self.assertEqual(path.read_bytes(), raw)
                path.unlink()

    def test_lock_break_restores_a_fresh_lock_that_replaced_the_stale_one(self):
        # Runner B breaks the stale lock and takes its own between A's read and A's rename.
        path = self.tmp / ".lock"
        self._write_lock(path, _dead_pid(), HOST_ID, "2000-01-01T00:00:00Z")
        fresh = json.dumps({"host": HOST_ID, "nonce": "b", "pid": os.getpid(), "ts": textio.now_iso()}).encode("utf-8")
        real_rename = os.rename
        raced = []

        def racing_rename(src, dst):
            if not raced:
                raced.append(src)
                Path(src).write_bytes(fresh)
            return real_rename(src, dst)

        with mock.patch.object(lock.os, "rename", side_effect=racing_rename):
            with self.assertRaises(textio.SdlcError) as ctx:
                lock.PackageLock(path, stale_seconds=600).acquire(timeout=0.3)
        self.assertEqual(raced, [str(path)])
        self.assertEqual(ctx.exception.message, "locked:%d@%s" % (os.getpid(), HOST_ID))
        self.assertEqual(path.read_bytes(), fresh)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), [".lock"])  # nothing left aside

    def test_lock_in_a_folder_that_cannot_be_made_is_a_named_error(self):
        blocker = self.tmp / "afile"
        blocker.write_bytes(b"x")
        path = blocker / "newpkg" / ".lock"
        with self.assertRaises(textio.SdlcError) as ctx:
            lock.PackageLock(path).acquire(timeout=1)
        self.assertEqual((ctx.exception.code, ctx.exception.message), (2, "lock_unwritable:" + str(path)))

    def test_lock_create_errors_fail_fast_with_a_named_reason(self):
        path = self.tmp / "pkg" / ".lock"
        path.parent.mkdir()
        # A read-only file system (EROFS) is no "wait and retry" case.
        with mock.patch.object(lock.os, "open", side_effect=OSError(errno.EROFS, "Read-only file system")):
            started = time.monotonic()
            with self.assertRaises(textio.SdlcError) as ctx:
                lock.PackageLock(path).acquire(timeout=5)
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual((ctx.exception.code, ctx.exception.message), (2, "lock_unwritable:" + str(path)))
        # A refused create with no lock file in sight (a read-only folder, an ACL deny) is reported
        # within about a second, not after the whole timeout.
        with mock.patch.object(lock.os, "open", side_effect=PermissionError(errno.EACCES, "denied")):
            started = time.monotonic()
            with self.assertRaises(textio.SdlcError) as ctx:
                lock.PackageLock(path).acquire(timeout=10)
        self.assertLess(time.monotonic() - started, 5.0)
        self.assertEqual(ctx.exception.message, "lock_unwritable:" + str(path))
        self.assertFalse(path.exists())

    def test_lock_in_a_folder_that_refuses_files(self):
        folder = self.tmp / "denied"
        folder.mkdir()
        self.make_readonly(folder)
        for path in (folder / ".lock", folder / "newpkg" / ".lock"):
            with self.subTest(path=path.name if path.parent == folder else "missing package folder"):
                started = time.monotonic()
                with self.assertRaises(textio.SdlcError) as ctx:
                    lock.PackageLock(path).acquire(timeout=10)
                self.assertLess(time.monotonic() - started, 5.0)
                self.assertEqual((ctx.exception.code, ctx.exception.message), (2, "lock_unwritable:" + str(path)))

    def test_release_keeps_a_lock_that_is_no_longer_ours(self):
        path = self.tmp / ".lock"
        mine = lock.PackageLock(path)
        mine.acquire(timeout=1)
        self._write_lock(path, 1, "other-host.invalid", textio.now_iso())  # someone broke ours and took it
        mine.release()
        self.assertTrue(path.exists())

    def test_lock_serialises_threads(self):
        path = self.tmp / ".lock"
        counter = self.tmp / "counter"
        counter.write_text("0", encoding="utf-8")
        errors = []

        def bump():
            try:
                for _ in range(5):
                    with lock.PackageLock(path):
                        value = int(counter.read_text(encoding="utf-8"))
                        counter.write_text(str(value + 1), encoding="utf-8")
            except Exception as exc:  # pragma: no cover - reported below
                errors.append(exc)

        threads = [threading.Thread(target=bump) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.assertEqual(errors, [])
        self.assertEqual(counter.read_text(encoding="utf-8"), "20")


class TestLogs(TempDirCase):
    def _three(self, path):
        return [logs.append(path, {"kind": "start", "flow": "feature"}),
                logs.append(path, {"kind": "enter", "step": "strategy", "visit": 1, "note": "ğ"}),
                logs.append(path, {"kind": "done", "step": "strategy", "fp": "abc"})]

    def test_logs_chain_and_head12(self):
        path = self.tmp / "transitions.jsonl"
        self.assertEqual(logs.head12(path), "0" * 12)
        self.assertEqual(logs.verify(path), (True, "0" * 64, None))
        stored = self._three(path)
        raw_lines = path.read_bytes().split(b"\n")
        self.assertEqual(raw_lines[-1], b"")
        raw_lines = raw_lines[:-1]
        self.assertEqual([r["seq"] for r in stored], [1, 2, 3])
        self.assertEqual(stored[0]["prev"], "0" * 64)
        self.assertEqual(stored[1]["prev"], _sha(raw_lines[0]))
        self.assertEqual(stored[2]["prev"], _sha(raw_lines[1]))
        self.assertEqual(list(json.loads(raw_lines[1].decode("utf-8")).keys()),
                         ["seq", "ts", "kind", "step", "visit", "note", "prev"])
        self.assertRegex(stored[0]["ts"], r"Z$")
        self.assertEqual(logs.read(path), stored)
        self.assertEqual(logs.head12(path), _sha(raw_lines[2])[:12])
        self.assertEqual(logs.verify(path), (True, _sha(raw_lines[2]), None))

    def test_logs_append_requires_kind(self):
        with self.assertRaises(ValueError):
            logs.append(self.tmp / "x.jsonl", {"step": "a"})

    def test_logs_verify_detects_middle_edit(self):
        path = self.tmp / "transitions.jsonl"
        self._three(path)
        data = path.read_bytes()
        edited = data.replace('"ğ"'.encode("utf-8"), b'"g"', 1)  # only line 2 carries this value
        self.assertNotEqual(edited, data)
        self.assertTrue(logs.verify(path)[0])  # clean twin
        path.write_bytes(edited)
        ok, _head, bad = logs.verify(path)
        self.assertFalse(ok)
        self.assertEqual(bad, 3)  # line 2's own hash is only checked by its successor

    def test_logs_verify_detects_reordered_seq(self):
        path = self.tmp / "transitions.jsonl"
        self._three(path)
        lines = path.read_bytes().split(b"\n")
        path.write_bytes(b"\n".join([lines[0], lines[2], lines[1], b""]))
        ok, _head, bad = logs.verify(path)
        self.assertFalse(ok)
        self.assertEqual(bad, 2)

    def test_logs_verify_detects_an_edited_seq_on_the_last_line(self):
        # The last line has no successor whose `prev` covers it; only the seq check sees this edit.
        path = self.tmp / "transitions.jsonl"
        self._three(path)
        clean = path.read_bytes()
        for old, new, bad in ((b'{"seq": 3,', b'{"seq": 9,', 3), (b'{"seq": 1,', b'{"seq": 0,', 1)):
            with self.subTest(edit=new):
                edited = clean.replace(old, new, 1)
                self.assertNotEqual(edited, clean)
                path.write_bytes(edited)
                ok, _head, first_bad = logs.verify(path)
                self.assertEqual((ok, first_bad), (False, bad))
        path.write_bytes(clean)
        self.assertEqual(logs.verify(path)[0], True)  # clean twin

    def test_logs_keep_lone_surrogates(self):
        # A POSIX argv with undecodable bytes (surrogateescape) still lands in the log.
        path = self.tmp / "runs.jsonl"
        stored = logs.append(path, {"kind": "started", "argv": ["pytest", "tests/t\udcff.py"]})
        self.assertEqual(stored["argv"], ["pytest", "tests/t\udcff.py"])
        path.read_bytes().decode("utf-8")  # strict: the log stays valid UTF-8
        self.assertEqual(logs.read(path)[0]["argv"], ["pytest", "tests/t\udcff.py"])
        nxt = logs.append(path, {"kind": "finished", "exit": 1})
        self.assertEqual(nxt["seq"], 2)
        self.assertTrue(logs.verify(path)[0])

    def test_logs_refuse_a_linked_log_file(self):
        pkg = self.tmp / "pkg"
        pkg.mkdir()
        victim = self.tmp / "victim.npmrc"
        victim.write_bytes(b"registry=https://example.invalid/")  # one line, no newline: looks torn
        link = pkg / "transitions.jsonl"
        self.symlink(victim, link)
        for call in (lambda: logs.append(link, {"kind": "enter"}), lambda: logs.read(link),
                     lambda: logs.verify(link), lambda: logs.head12(link)):
            with self.assertRaises(textio.SdlcError) as ctx:
                call()
            self.assertEqual((ctx.exception.code, ctx.exception.message), (2, "log_not_regular:transitions.jsonl"))
        self.assertEqual(victim.read_bytes(), b"registry=https://example.invalid/")
        dangling = pkg / "runs.jsonl"
        self.symlink(self.tmp / "planted.pth", dangling)
        with self.assertRaises(textio.SdlcError):
            logs.append(dangling, {"kind": "started"})
        self.assertFalse((self.tmp / "planted.pth").exists())
        logs.append(pkg / "approvals.jsonl", {"kind": "approve"})  # clean twin: a plain file
        self.assertTrue(logs.verify(pkg / "approvals.jsonl")[0])

    def test_logs_reader_tolerates_truncated_tail(self):
        path = self.tmp / "transitions.jsonl"
        stored = self._three(path)[:2]
        lines = path.read_bytes().split(b"\n")
        path.write_bytes(b"\n".join(lines[:2]) + b"\n" + b'{"seq": 3, "kind": "trunc')  # a crashed write
        head_before = _sha(lines[1])
        self.assertEqual(logs.read(path), stored)
        self.assertEqual(logs.verify(path), (True, head_before, None))
        self.assertEqual(logs.head12(path), head_before[:12])
        nxt = logs.append(path, {"kind": "note"})
        self.assertEqual((nxt["seq"], nxt["prev"]), (3, head_before))
        self.assertNotIn(b'"trunc', path.read_bytes())
        self.assertTrue(logs.verify(path)[0])

    def test_logs_unterminated_complete_last_line_is_kept(self):
        path = self.tmp / "runs.jsonl"
        stored = self._three(path)
        path.write_bytes(path.read_bytes().rstrip(b"\n"))
        self.assertEqual(logs.read(path), stored)
        nxt = logs.append(path, {"kind": "note"})
        self.assertEqual(nxt["seq"], 4)
        self.assertEqual(len(logs.read(path)), 4)
        self.assertTrue(logs.verify(path)[0])

    def test_logs_chain_survives_crlf_and_bom_checkout(self):
        path = self.tmp / "transitions.jsonl"
        self._three(path)
        ok, head, _ = logs.verify(path)
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(logs.verify(path), (True, head, None))
        self.assertEqual(len(logs.read(path)), 3)
        self.assertEqual(logs.append(path, {"kind": "note"})["prev"], head)
        self.assertTrue(logs.verify(path)[0])

    def test_logs_corrupt_middle_line_raises(self):
        path = self.tmp / "transitions.jsonl"
        self._three(path)
        lines = path.read_bytes().split(b"\n")
        path.write_bytes(b"\n".join([lines[0], b"not json", lines[2], b""]))
        with self.assertRaises(textio.SdlcError) as ctx:
            logs.read(path)
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(logs.verify(path)[0:1], (False,))
        self.assertEqual(logs.verify(path)[2], 2)


class TestFrontmatter(TempDirCase):
    def test_frontmatter_roundtrip_keeps_body_bytes(self):
        body = "\n# Title ğ\n\nText with --- inside\n---\nnot frontmatter\n"
        text = "---\nwork_id: add-export\nstatus: draft\nspec: ../spec/add-export.md\n---\n" + body
        meta, got_body, had = frontmatter.split(text)
        self.assertTrue(had)
        self.assertEqual(meta, {"work_id": "add-export", "status": "draft", "spec": "../spec/add-export.md"})
        self.assertEqual(list(meta), ["work_id", "status", "spec"])
        self.assertEqual(got_body, body)
        self.assertEqual(frontmatter.render(meta, got_body), text)
        # render keeps key order and ends the body with exactly one newline
        rendered = frontmatter.render({"status": "approved", "work_id": "x"}, "body\n\n\n")
        self.assertEqual(rendered, "---\nstatus: approved\nwork_id: x\n---\nbody\n")
        self.assertEqual(frontmatter.render({"a": "b"}, "body"), "---\na: b\n---\nbody\n")

    def test_frontmatter_unterminated_block_is_body(self):
        text = "---\nwork_id: x\nstatus: draft\n\n# Body\n"
        self.assertEqual(frontmatter.split(text), ({}, text, False))
        plain = "# No frontmatter\n---\nk: v\n---\n"
        self.assertEqual(frontmatter.split(plain), ({}, plain, False))

    def test_frontmatter_crlf_bom_and_body_text(self):
        target = self.tmp / "spec.md"
        target.write_bytes(b"\xef\xbb\xbf---\r\nwork_id: x\r\n---\r\n# Body \xc4\x9f\r\n")
        self.assertEqual(frontmatter.body_text(target), "# Body ğ\n")
        meta, body, had = frontmatter.split("﻿---\r\nwork_id: x\r\n---\r\nB\r\n")
        self.assertEqual((meta, body, had), ({"work_id": "x"}, "B\n", True))

    def test_frontmatter_render_rejects_unsafe_values(self):
        for meta in ({"a": "x\ny"}, {"a:b": "x"}, {"": "x"}, {"a\n": "x"},
                     # values and keys the reader would see differently (contract §1 reading)
                     {"a": '"x"'}, {"a": "'x'"}, {"a": 'x"'}, {"a": " x"}, {"a": "x "},
                     {"a": "x\ry"}, {"a": "x y"}, {"a": "x\x85y"}, {"a": "x\x0by"}, {"a": "x\x1cy"},
                     {"#a": "x"}, {"a ": "x"}, {" a": "x"}):
            with self.subTest(meta=meta):
                with self.assertRaises(ValueError):
                    frontmatter.render(meta, "body\n")

    def test_frontmatter_render_reads_back_unchanged(self):
        meta = {"work_id": "add-export", "status": "approved", "spec": "../spec/add-export.md",
                "url": "http://a:b/c", "empty": "", "flag": True, "count": 3, "none": None, "note": "a # b ğ"}
        text = frontmatter.render(meta, "# Body\n")
        want = {k: frontmatter._value(v) for k, v in meta.items()}
        self.assertEqual(frontmatter.split(text), (want, "# Body\n", True))
        self.assertEqual(frontmatter.parse(text), (want, []))
        self.assertEqual(validate_artifacts._frontmatter_block(text), (want, []))

    # (name, file bytes, block terminated?). Read by the runner (textio.read_text, then split/parse)
    # and by the validator (Path.read_text(encoding="utf-8-sig"), then _frontmatter_block).
    PARITY_CORPUS = [
        ("plain", b"---\nwork_id: x\nstatus: draft\n---\n# Spec\n", True),
        ("double-quoted", b'---\nstatus: "approved"\n---\nB\n', True),
        ("single-quoted", b"---\nstatus: 'reviewed'\nflow: \"bugfix\"\n---\nB\n", True),
        ("comment-line", b"---\n# note: x\nstatus: draft\n  # indented: y\n---\nB\n", True),
        ("blank-lines", b"---\n\nstatus: draft\n   \n---\nB\n", True),
        ("colon-less-line", b"---\nwork_id: x\njunk line\n---\nB\n", True),
        ("empty-key", b"---\n: v\nstatus: draft\n---\nB\n", True),
        ("indented-closer", b"---\nwork_id: x\n  ---\nstatus: draft\n---\n# Spec\n", True),
        ("indented-opener", b"  ---\nstatus: draft\n---\nB\n", False),
        ("four-dash-opener", b"----\nstatus: draft\n---\nB\n", False),
        ("four-dash-closer", b"---\nstatus: draft\n----\nwork_id: y\n---\nB\n", True),
        ("trailing-space-delimiters", b"--- \nstatus: draft\n---  \nB\n", True),
        ("lone-cr", b"---\rstatus: draft\r---\rbody\r", True),
        ("u2028", "---\nnote: n --- ## Acceptance Criteria - AC-9\n---\nB\n".encode("utf-8"), True),
        ("u2028-opener", "--- status: approved --- B\n".encode("utf-8"), True),
        ("vertical-tab", b"---\nstatus: draft\x0bwork_id: y\n---\nB\n", True),
        ("next-line", "---\nstatus: draft\x85work_id: y\n---\nB\n".encode("utf-8"), True),
        ("crlf-bom", b"\xef\xbb\xbf---\r\nwork_id: x\r\nstatus: 'draft'\r\n---\r\nB\r\n", True),
        ("unterminated", b"---\nwork_id: x\nstatus: draft\njunk\n\n# Body\n", False),
        ("no-block", b"# Title\n---\nk: v\n---\n", False),
        ("opener-only", b"---", False),
        ("opener-newline", b"---\n", False),
        ("empty-block", b"---\n---\nB\n", True),
        ("empty-file", b"", False),
        ("value-with-colons", b"---\nspec: ../spec/x.md\nurl: http://a:b\n---\nB\n", True),
    ]

    def test_frontmatter_reads_exactly_like_the_validator(self):
        for name, data, terminated in self.PARITY_CORPUS:
            with self.subTest(case=name):
                target = self.tmp / (name + ".md")
                target.write_bytes(data)
                text = textio.read_text(target)
                want = validate_artifacts._frontmatter_block(target.read_text(encoding="utf-8-sig"))
                self.assertEqual(frontmatter.parse(text), want)
                meta, body, had = frontmatter.split(text)
                self.assertEqual((meta, had), (want[0], terminated))
                if not terminated:
                    self.assertEqual(body, text)

    def test_frontmatter_body_starts_after_the_validators_closer(self):
        meta, body, had = frontmatter.split("---\nwork_id: x\n  ---\nstatus: draft\n---\n# Spec\n")
        self.assertEqual((meta, body, had), ({"work_id": "x", "status": "draft"}, "# Spec\n", True))
        meta, body, had = frontmatter.split("---\nnote: n --- ## AC - AC-9\n---\nB\n")
        self.assertEqual((meta, body, had), ({"note": "n"}, "## AC - AC-9\n---\nB\n", True))
        # Stamping (split, set status, render) keeps no stray frontmatter line in the body.
        meta, body, _ = frontmatter.split("---\nwork_id: x\n  ---\nstatus: draft\n---\n# Spec\n")
        meta["status"] = "reviewed"
        self.assertEqual(frontmatter.render(meta, body), "---\nwork_id: x\nstatus: reviewed\n---\n# Spec\n")

    def test_frontmatter_parse_reports_invalid_lines(self):
        self.assertEqual(frontmatter.parse("---\nwork_id: x\njunk\n: v\n---\nB\n"),
                         ({"work_id": "x"}, ["invalid_frontmatter_line:3", "invalid_frontmatter_line:4"]))
        self.assertEqual(frontmatter.parse("---\nwork_id: x\n---\n"), ({"work_id": "x"}, []))  # clean twin
        self.assertEqual(frontmatter.parse("---\njunk\n"), ({}, []))  # unterminated: not frontmatter


class TestSchema(unittest.TestCase):
    def _pointers(self, errors):
        return [e.split(": ", 1)[0] for e in errors]

    def test_schema_subset(self):
        v = schema.validate
        # type, including a list of types; bool is not an integer
        self.assertEqual(v("x", {"type": "string"}), [])
        self.assertEqual(self._pointers(v(1, {"type": "string"})), [""])
        self.assertEqual(v(None, {"type": ["string", "null"]}), [])
        self.assertEqual(v(3, {"type": "integer"}), [])
        self.assertEqual(v(3.0, {"type": "integer"}), [])
        self.assertEqual(len(v(True, {"type": "integer"})), 1)
        self.assertEqual(len(v(1.5, {"type": "integer"})), 1)
        self.assertEqual(v(1.5, {"type": "number"}), [])
        self.assertEqual(len(v([], {"type": "object"})), 1)
        # required + properties, with a nested pointer
        s = {"type": "object", "required": ["a"],
             "properties": {"a": {"type": "object", "required": ["b"],
                                  "properties": {"b": {"type": "array", "items": {"type": "string"}}}}}}
        self.assertEqual(v({"a": {"b": ["x", "y"]}}, s), [])
        errs = v({"a": {"b": ["x", 2]}}, s)
        self.assertEqual(self._pointers(errs), ["/a/b/1"])
        self.assertIn("string", errs[0])
        errs = v({"a": {}}, s)
        self.assertEqual(self._pointers(errs), ["/a/b"])
        self.assertIn("required", errs[0])
        self.assertEqual(self._pointers(v({}, s)), ["/a"])
        # additionalProperties: false, with pointer escaping
        s = {"type": "object", "properties": {"a": {}}, "additionalProperties": False}
        self.assertEqual(v({"a": 1}, s), [])
        errs = v({"a": 1, "x/y~z": 2}, s)
        self.assertEqual(self._pointers(errs), ["/x~1y~0z"])
        self.assertIn("additional", errs[0])
        # enum and const use JSON equality (true is not 1)
        self.assertEqual(v("low", {"enum": ["low", "high"]}), [])
        self.assertEqual(self._pointers(v("mid", {"enum": ["low", "high"]})), [""])
        self.assertEqual(len(v(True, {"enum": [1]})), 1)
        self.assertEqual(v(1, {"const": 1}), [])
        self.assertEqual(len(v(True, {"const": 1})), 1)
        self.assertEqual(v({"a": [1]}, {"const": {"a": [1]}}), [])
        self.assertEqual(len(v({"a": [True]}, {"const": {"a": [1]}})), 1)
        # minLength, minimum, maximum, pattern
        self.assertEqual(v("ab", {"minLength": 2}), [])
        self.assertEqual(len(v("a", {"minLength": 2})), 1)
        self.assertEqual(v(3, {"minimum": 3, "maximum": 5}), [])
        self.assertEqual(len(v(2, {"minimum": 3})), 1)
        self.assertEqual(len(v(6, {"maximum": 5})), 1)
        self.assertEqual(v("ab12", {"pattern": "^[a-z]+[0-9]+$"}), [])
        self.assertEqual(len(v("12ab", {"pattern": "^[a-z]+[0-9]+$"})), 1)
        # keywords only apply to their own instance type
        self.assertEqual(v(5, {"minLength": 9, "pattern": "x", "required": ["a"], "items": {"type": "string"}}), [])
        # additionalProperties as a schema validates every extra property
        s = {"type": "object", "properties": {"a": {}}, "additionalProperties": {"type": "string"}}
        self.assertEqual(v({"a": 1, "k": "x"}, s), [])
        errs = v({"a": 1, "k": 5, "m": "y", "n": None}, s)
        self.assertEqual(self._pointers(errs), ["/k", "/n"])
        self.assertIn("expected string", errs[0])

    def test_schema_pattern_uses_ecma_262_semantics(self):
        # JSON Schema patterns are ECMA-262: `$` is the end of input (Python's `$` also matches
        # before a final newline), `\d`/`\w`/`\b` are ASCII, `\s` is Unicode whitespace, and `.`
        # stops at every line terminator.
        v = schema.validate
        fp16 = {"type": "string", "pattern": "^[0-9a-f]{16}$"}
        self.assertEqual(v("0123456789abcdef", fp16), [])
        self.assertEqual(len(v("0123456789abcdef\n", fp16)), 1)
        rows = [
            (r"^\d+$", "123", True), (r"^\d+$", "١٢٣", False),
            (r"^\w+$", "ab_9", True), (r"^\w+$", "é", False),
            (r"^a\sb$", "a b", True), (r"^a\sb$", "a b", True), (r"^a\sb$", "a b", True),
            (r"^a\Sb$", "a b", False), (r"^a\Sb$", "axb", True),
            (r"^a[\s,]b$", "a　b", True), (r"^a[\s,]b$", "a,b", True), (r"^a[\s,]b$", "axb", False),
            (r"^a.b$", "axb", True), (r"^a.b$", "a b", False), (r"^a.b$", "a\rb", False),
            (r"^a\$$", "a$", True), (r"^a[$]$", "a$", True), (r"^a[$]$", "ab", False),
            (r"\bcat\b", "a cat", True), (r"\bcat\b", "écat", True),
            (r"^x$", "x\n", False), (r"^(?:a|b)$", "b", True),
        ]
        for pattern, value, ok in rows:
            with self.subTest(pattern=pattern, value=value):
                self.assertEqual(v(value, {"pattern": pattern}) == [], ok)
        for bad in (r"[]", r"[^]", r"(?P<n>a)", r"a\Z", r"(?i)a", r"[\S]"):
            with self.subTest(unsupported=bad):
                with self.assertRaises(ValueError):
                    schema.validate("a", {"pattern": bad})

    def test_schema_errors_are_ordered_and_all_reported(self):
        s = {"type": "object", "required": ["a", "b"],
             "properties": {"a": {"type": "string"}, "b": {"type": "string"}}}
        self.assertEqual(self._pointers(schema.validate({}, s)), ["/a", "/b"])

    def test_schema_rejects_unsupported_keywords(self):
        for bad in ({"oneOf": []}, {"properties": {"a": {"$ref": "#/x"}}}, {"items": [{}]},
                    {"type": "strin"}, {"required": "a"}, {"pattern": "("}):
            with self.subTest(schema=bad):
                with self.assertRaises(ValueError):
                    schema.validate({}, bad)
        # annotations are allowed
        self.assertEqual(schema.validate("x", {"$schema": "x", "$id": "y", "title": "t",
                                               "description": "d", "type": "string"}), [])
        self.assertIn("pattern", schema.SUPPORTED_KEYWORDS)


class TestEntry(TempDirCase):
    def _copy_runner(self, with_cli=None):
        dest = self.tmp / "plug in ğ" / "scripts"
        (dest / "sdlc_runner").mkdir(parents=True)
        shutil.copy2(str(SCRIPTS / "sdlc.py"), str(dest / "sdlc.py"))
        shutil.copy2(str(SCRIPTS / "sdlc_runner" / "__init__.py"), str(dest / "sdlc_runner" / "__init__.py"))
        if with_cli is not None:
            (dest / "sdlc_runner" / "cli.py").write_bytes(with_cli.encode("utf-8"))
        return dest / "sdlc.py"

    def _run(self, script, *args):
        return subprocess.run([sys.executable, "-I", "-B", str(script), *args], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=60, cwd=str(self.tmp))

    def test_runner_version(self):
        self.assertEqual(RUNNER_VERSION, "1.0.0")

    def test_entry_without_cli_reports_cli_not_built(self):
        proc = self._run(self._copy_runner(), "next")
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertEqual(proc.stdout.strip().splitlines(), ["error=cli_not_built"])

    def test_entry_dispatches_to_cli_main(self):
        cli = "import sys\ndef main(argv=None):\n    print('argv=' + ','.join(sys.argv[1:]))\n    return 7\n"
        proc = self._run(self._copy_runner(cli), "card", "--slug", "x")
        self.assertEqual(proc.returncode, 7, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "argv=card,--slug,x")

    def test_entry_does_not_hide_a_broken_cli_import(self):
        proc = self._run(self._copy_runner("import sdlc_runner.no_such_module\n"), "next")
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("cli_not_built", proc.stdout)
        self.assertIn("no_such_module", proc.stderr)


if __name__ == "__main__":
    unittest.main()
