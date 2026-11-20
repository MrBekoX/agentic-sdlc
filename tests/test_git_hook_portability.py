"""Portable git hooks (R1-e of docs/agentic-sdlc/plans/audit-residuals.md).

The installer wrote each hook with an absolute path to the scanner, so a checkout reached under
another spelling (WSL `/mnt/d/...` for a Windows `D:/...` install, a moved or renamed folder) ran a
hook that could not find it and committed unscanned. These tests pin the portable install: what
the installer writes, and that a commit is still scanned after the paths change.
"""
import ast
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INSTALLER = REPO / "scripts" / "install_git_hooks.py"
GIT = shutil.which("git")
NODE = shutil.which("node")
SH = shutil.which("sh")
WRITE_MODES = set("wax+")
POSIX = os.name != "nt"
VENDOR = "agentic-sdlc-scanner"
MANIFEST = "agentic-sdlc-hooks.json"
HOOK_NAMES = ("pre-commit", "pre-merge-commit", "commit-msg", "prepare-commit-msg")

# Synthetic GitHub-shaped token: prefix + 36 mixed characters, built at runtime.
SECRET = "gh" + "p_" + "Zq8Lm4Tx9" * 4
GIT_ENV = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)


def _mode_of(call):
    """The mode argument of an open call: builtin `open(path, mode)` or `Path.open(mode)`."""
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            return kw.value.value
    index = 1 if isinstance(call.func, ast.Name) else 0
    if len(call.args) > index and isinstance(call.args[index], ast.Constant):
        return call.args[index].value
    return "r"


def _newline_is_lf(call):
    return any(kw.arg == "newline" and isinstance(kw.value, ast.Constant) and kw.value.value == "\n"
               for kw in call.keywords)


def _write_violations(tree):
    """Lines that write a file without forcing LF: any write_text, any write-mode open without newline."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
        if name == "write_text":
            found.append(node.lineno)
        elif name == "open" and WRITE_MODES & set(str(_mode_of(node))) and not _newline_is_lf(node):
            found.append(node.lineno)
    return sorted(found)


class TestInstallerWritesLf(unittest.TestCase):

    def test_installer_writes_only_through_the_lf_helper(self):
        tree = ast.parse(INSTALLER.read_text(encoding="utf-8"), filename=str(INSTALLER))
        self.assertEqual(_write_violations(tree), [],
                         "the installer writes a file that is not forced to LF (or uses write_text)")

    def test_the_write_rule_fires(self):
        # Negative control: each forbidden form is seen, the LF forms are not.
        tree = ast.parse("p.write_text(s)\n"
                         "open(f, 'w')\n"
                         "p.open('a', encoding='utf-8')\n"
                         "open(f, 'w', newline='\\n')\n"
                         "p.open(mode='w', newline='\\n')\n"
                         "open(f)\n")
        self.assertEqual(_write_violations(tree), [1, 2, 3])

    @unittest.skipIf(GIT is None, "git required")
    def test_generated_hooks_and_manifest_hold_no_cr(self):
        with tempfile.TemporaryDirectory(prefix="hook-lf-") as tmp:
            repo = Path(tmp, "repo")
            repo.mkdir()
            subprocess.run([GIT, "init", "-q", str(repo)], check=True, capture_output=True)
            proc = subprocess.run([sys.executable, str(INSTALLER), "--install", "--repo", str(repo)],
                                  capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            hooks = repo / ".git" / "hooks"
            written = [p for p in hooks.rglob("*") if p.is_file() and not p.name.endswith(".sample")]
            written.append(repo / ".git" / "agentic-sdlc-hooks.json")
            for path in written:
                with self.subTest(path=path.name):
                    self.assertNotIn(b"\r", path.read_bytes())



# ---------------------------------------------------------------------------------------------
# Fixtures: a copy of the plugin (installer + hooks) and a repository, both in a temp folder, so a
# test can move or rename either one. Built once per class and copied per test.
# ---------------------------------------------------------------------------------------------
def _copy_plugin(dest):
    (dest / "scripts").mkdir(parents=True)
    shutil.copy2(str(INSTALLER), str(dest / "scripts" / INSTALLER.name))
    (dest / "hooks").mkdir()
    for src in (REPO / "hooks").glob("*.mjs"):
        shutil.copy2(str(src), str(dest / "hooks" / src.name))


def _git(cwd, *args, check=True):
    return subprocess.run([GIT, *args], cwd=str(cwd), env=GIT_ENV, capture_output=True,
                          text=True, encoding="utf-8", check=check)


def _make_repo(path):
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "feature/x")
    _git(path, "config", "user.name", "Fixture")
    _git(path, "config", "user.email", "fixture@example.invalid")
    _git(path, "config", "commit.gpgsign", "false")
    (path / "readme.md").write_text("# fixture\n", encoding="utf-8")
    _git(path, "add", "readme.md")
    _git(path, "-c", "core.hooksPath=" + os.devnull, "commit", "-qm", "base")


def _installer_run(plugin, repo, *args):
    return subprocess.run([sys.executable, str(plugin / "scripts" / INSTALLER.name), *args, "--repo", str(repo)],
                          env=GIT_ENV, capture_output=True, text=True, encoding="utf-8")


def _load_installer(plugin, tag):
    spec = importlib.util.spec_from_file_location("_portable_installer_" + tag,
                                                  str(plugin / "scripts" / INSTALLER.name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _hooks(repo):
    return repo / ".git" / "hooks"


def _check(plugin, repo):
    proc = _installer_run(plugin, repo, "--check")
    assert proc.returncode == 0, proc.stderr
    return dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)


@unittest.skipIf(GIT is None, "git required")
class _Fixture(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="hook-portable-")
        base = Path(cls._tmp.name)
        cls.template_plugin = base / "template-plugin"
        _copy_plugin(cls.template_plugin)
        cls.template_repo = base / "template-repo"
        _make_repo(cls.template_repo)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self._case = tempfile.TemporaryDirectory(prefix="hook-case-")
        self.addCleanup(self._case.cleanup)
        self.base = Path(self._case.name)
        self.plugin = self.base / "plugin"
        shutil.copytree(str(self.template_plugin), str(self.plugin), symlinks=True)
        self.repo = self.base / "repo"
        shutil.copytree(str(self.template_repo), str(self.repo), symlinks=True)

    def install(self, *args, plugin=None, repo=None):
        return _installer_run(plugin or self.plugin, repo or self.repo, "--install", *args)

    def uninstall(self, plugin=None, repo=None):
        return _installer_run(plugin or self.plugin, repo or self.repo, "--uninstall")

    def manifest(self, repo=None):
        return (repo or self.repo) / ".git" / MANIFEST

    def stage_token(self, repo, name="config.py"):
        (repo / name).write_text("key = '" + SECRET + "'\n", encoding="utf-8")
        _git(repo, "add", name)

    def commit(self, cwd, message="fix: change"):
        return _git(cwd, "commit", "-m", message, check=False)


# ---------------------------------------------------------------------------------------------
# Task 6 (AC12-AC14): the hooks find a vendored scanner from $0, so no plugin path is recorded.
# ---------------------------------------------------------------------------------------------
@unittest.skipIf(GIT is None or NODE is None, "git and node required")
class TestPortableHookInstall(_Fixture):

    def _assert_blocked(self, proc):
        self.assertNotEqual(proc.returncode, 0, "a staged token was committed: " + proc.stderr[-300:])
        self.assertNotIn("scanner missing", proc.stderr)

    def test_commit_is_scanned_after_the_plugin_and_repo_move(self):
        self.assertEqual(self.install().returncode, 0)
        moved_plugin = self.plugin.rename(self.base / "plugin-renamed")
        moved_repo = self.repo.rename(self.base / "repo renamed")
        self.stage_token(moved_repo)
        self._assert_blocked(self.commit(moved_repo))
        sub = moved_repo / "src"
        sub.mkdir()
        self._assert_blocked(self.commit(sub))
        _git(moved_repo, "reset", "-q", "config.py")
        (moved_repo / "notes.md").write_text("clean\n", encoding="utf-8")
        _git(moved_repo, "add", "notes.md")
        clean = self.commit(moved_repo, "docs: notes")
        self.assertEqual(clean.returncode, 0, clean.stderr[-300:])
        self.assertTrue(moved_plugin.is_dir())

    @unittest.skipUnless(POSIX, "symlinks need a privilege on Windows")
    def test_commit_through_a_symlinked_repo_path(self):
        self.assertEqual(self.install().returncode, 0)
        self.plugin.rename(self.base / "plugin-renamed")
        link = self.base / "link"
        link.symlink_to(self.repo)
        self.stage_token(link)
        self._assert_blocked(self.commit(link))

    def test_vendored_set_is_the_import_closure(self):
        seen, todo = set(), ["git-hook-scan.mjs"]
        while todo:
            name = todo.pop()
            if name in seen:
                continue
            seen.add(name)
            text = (REPO / "hooks" / name).read_text(encoding="utf-8")
            todo.extend(re.findall(r"""from\s+['"]\./([\w.-]+\.mjs)['"]""", text))
        installer = _load_installer(self.plugin, "closure")
        self.assertEqual(set(installer.VENDORED), seen)

    def test_generated_files_are_lf_and_executable(self):
        self.assertEqual(self.install().returncode, 0)
        files = [_hooks(self.repo) / n for n in HOOK_NAMES]
        files += sorted((_hooks(self.repo) / VENDOR).iterdir())
        files.append(self.manifest())
        for path in files:
            with self.subTest(path=path.name):
                self.assertNotIn(b"\r", path.read_bytes())
        if POSIX:
            for name in HOOK_NAMES:
                self.assertTrue(os.stat(str(_hooks(self.repo) / name)).st_mode & 0o100, name)

    def _run_hook(self, env):
        hook = _hooks(self.repo) / "pre-commit"
        return subprocess.run([SH, str(hook)], cwd=str(self.repo), env=env, capture_output=True,
                              text=True, encoding="utf-8")

    @unittest.skipIf(SH is None, "sh required")
    def test_missing_node_fails_open_loudly(self):
        self.assertEqual(self.install().returncode, 0)
        empty = self.base / "empty-path"
        empty.mkdir()
        path = str(empty) if POSIX else os.path.dirname(SH)
        proc = self._run_hook(dict(GIT_ENV, PATH=path))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("node not found", proc.stderr)
        self.assertIn("NOT scanned", proc.stderr)

    @unittest.skipIf(SH is None, "sh required")
    def test_missing_scanner_fails_open_loudly(self):
        self.assertEqual(self.install().returncode, 0)
        shutil.rmtree(str(_hooks(self.repo) / VENDOR))
        proc = self._run_hook(GIT_ENV)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("scanner missing", proc.stderr)
        self.assertIn(VENDOR, proc.stderr)
        self.assertIn("--install", proc.stderr)
        self.assertIn("NOT scanned", proc.stderr)


# ---------------------------------------------------------------------------------------------
# Task 7 (AC13, AC15, AC17): the vendored files have their own ownership states.
# ---------------------------------------------------------------------------------------------
class TestVendoredOwnership(_Fixture):

    def vendored(self, name="secret-patterns.mjs", repo=None):
        return _hooks(repo or self.repo) / VENDOR / name

    def snapshot(self, repo=None):
        root = _hooks(repo or self.repo)
        files = {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*"))
                 if p.is_file() and not p.name.endswith(".sample")}
        files["manifest"] = self.manifest(repo).read_bytes() if self.manifest(repo).exists() else b""
        return files

    def test_uninstall_removes_recorded_vendored_files_only(self):
        self.assertEqual(self.install().returncode, 0)
        extra = _hooks(self.repo) / VENDOR / "notes.txt"
        extra.write_text("mine\n", encoding="utf-8")
        proc = self.uninstall()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual([p.name for p in (_hooks(self.repo) / VENDOR).iterdir()], ["notes.txt"])
        self.assertFalse(self.manifest().exists())

    def test_modified_vendored_file_is_never_overwritten_or_deleted(self):
        self.assertEqual(self.install().returncode, 0)
        edited = self.vendored().read_text(encoding="utf-8") + "// edited\n"
        self.vendored().write_text(edited, encoding="utf-8")
        self.assertEqual(self.install().returncode, 2)
        self.assertEqual(self.vendored().read_text(encoding="utf-8"), edited)
        self.assertEqual(self.uninstall().returncode, 2)
        self.assertEqual(self.vendored().read_text(encoding="utf-8"), edited)

    def test_planted_entry_in_the_vendored_folder_is_refused(self):
        self.assertEqual(self.install().returncode, 0)
        planted = _hooks(self.repo) / VENDOR / "no-repository-hooks"
        planted.mkdir()
        (planted / "pre-commit").write_text("#!/bin/sh\necho planted\n", encoding="utf-8")
        before = self.snapshot()
        proc = self.install()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no-repository-hooks", proc.stderr)
        self.assertEqual(self.snapshot(), before)

    @unittest.skipUnless(POSIX, "symlinks need a privilege on Windows")
    def test_symlinked_vendored_folder_or_file_is_refused(self):
        outside = self.base / "outside"
        outside.mkdir()
        _hooks(self.repo).mkdir(exist_ok=True)
        (_hooks(self.repo) / VENDOR).symlink_to(outside)
        self.assertEqual(self.install().returncode, 2)
        self.assertEqual(list(outside.iterdir()), [])
        (_hooks(self.repo) / VENDOR).unlink()
        self.assertEqual(self.install().returncode, 0)
        target = self.base / "copy.mjs"
        target.write_bytes(self.vendored().read_bytes())
        self.vendored().unlink()
        self.vendored().symlink_to(target)
        self.assertEqual(self.install().returncode, 2)
        self.assertTrue(self.vendored().is_symlink())

    def test_check_reports_stale_after_plugin_update_and_install_refreshes(self):
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(_check(self.plugin, self.repo)["scanner"], "current")
        source = self.plugin / "hooks" / "secret-patterns.mjs"
        source.write_text(source.read_text(encoding="utf-8") + "// newer plugin\n", encoding="utf-8")
        status = _check(self.plugin, self.repo)
        self.assertEqual(status["scanner"], "stale")
        self.assertEqual(status["vendored/secret-patterns.mjs"], "stale")
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(_check(self.plugin, self.repo)["scanner"], "current")
        self.assertEqual(self.vendored().read_bytes(), source.read_bytes().replace(b"\r\n", b"\n"))

    def test_check_names_each_scanner_state(self):
        self.assertEqual(_check(self.plugin, self.repo)["scanner"], "missing")
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(_check(self.plugin, self.repo)["scanner"], "current")
        self.manifest().unlink()
        self.assertEqual(_check(self.plugin, self.repo)["scanner"], "unclaimed")
        self.assertEqual(self.install().returncode, 0)
        self.vendored().write_text("// edited\n", encoding="utf-8")
        self.assertEqual(_check(self.plugin, self.repo)["scanner"], "modified")
        self.manifest().unlink()
        self.assertEqual(_check(self.plugin, self.repo)["scanner"], "foreign")

    def test_retired_vendored_name_does_not_block_an_upgrade(self):
        installer = _load_installer(self.plugin, "retired")
        self.assertEqual(installer.cmd_install(self.repo), 0)
        retired = installer.VENDORED[-1]
        installer.VENDORED = installer.VENDORED[:-1]
        self.assertIn(retired, installer.KNOWN_VENDORED)
        self.assertEqual(installer.cmd_install(self.repo), 0)
        self.assertFalse(self.vendored(retired).exists())
        data = json.loads(self.manifest().read_text(encoding="utf-8"))
        self.assertNotIn(retired, data["vendored"])

    # Controls: these adopt and exit 0 before and after the change.
    def test_lost_manifest_is_adopted(self):
        self.assertEqual(self.install().returncode, 0)
        self.manifest().unlink()
        self.assertEqual(self.install().returncode, 0)
        self.assertTrue(self.manifest().exists())

    def test_manifest_binding_for_another_mount_is_adopted(self):
        self.assertEqual(self.install().returncode, 0)
        hashes = {n: hashlib.sha256((_hooks(self.repo) / n).read_bytes()).hexdigest() for n in HOOK_NAMES}
        self.manifest().write_text(json.dumps({"version": 1, "hooks_dir": "/mnt/z/elsewhere/.git/hooks",
                                               "hooks": hashes}), encoding="utf-8")
        self.assertEqual(self.install().returncode, 0)

    def test_moved_repository_install_adopts(self):
        self.assertEqual(self.install().returncode, 0)
        moved = self.repo.rename(self.base / "moved")
        self.assertEqual(self.install(repo=moved).returncode, 0)

    def test_reinstall_is_byte_identical(self):
        self.assertEqual(self.install().returncode, 0)
        before = self.snapshot()
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_manifest_is_lf_only(self):
        self.assertEqual(self.install().returncode, 0)
        self.assertNotIn(b"\r", self.manifest().read_bytes())

    def test_foreign_hook_and_external_path_rules_unchanged(self):
        _hooks(self.repo).mkdir(exist_ok=True)
        foreign = _hooks(self.repo) / "pre-commit"
        foreign.write_text("#!/bin/sh\necho FOREIGN\n", encoding="utf-8")
        self.assertEqual(self.install().returncode, 2)
        self.assertEqual(foreign.read_text(encoding="utf-8"), "#!/bin/sh\necho FOREIGN\n")
        self.assertFalse((_hooks(self.repo) / VENDOR).exists(), "a refused install wrote files")


# ---------------------------------------------------------------------------------------------
# Task 8 (AC16): a recorded hook is replaceable only when it is generator output; today's bodies
# migrate. Task 9 (AC18): the manifest is bound relative to the repository.
# ---------------------------------------------------------------------------------------------
class TestHookMigrationAndBinding(_Fixture):

    def _old_install(self, scanner, *, legacy=False, manifest=True):
        installer = _load_installer(self.plugin, "old")
        hooks = _hooks(self.repo)
        hooks.mkdir(exist_ok=True)
        digests = {}
        for name in HOOK_NAMES:
            body = (installer._legacy_hook_body(name, scanner) if legacy
                    else installer._absolute_digest_body(name, scanner))
            with open(str(hooks / name), "w", encoding="utf-8", newline="\n") as handle:
                handle.write(body)
            digests[name] = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if manifest:
            self.manifest().write_text(json.dumps({"version": 1, "hooks_dir": str(hooks.resolve()),
                                                   "hooks": digests}), encoding="utf-8")

    def test_origin_main_digest_install_migrates(self):
        self._old_install("/old/plugin/hooks/git-hook-scan.mjs")
        proc = self.install()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        installer = _load_installer(self.plugin, "new")
        self.assertEqual((_hooks(self.repo) / "pre-commit").read_text(encoding="utf-8"),
                         installer.hook_body("pre-commit"))
        self.assertTrue((_hooks(self.repo) / VENDOR / "git-hook-scan.mjs").is_file())

    def test_legacy_body_without_manifest_migrates(self):
        self._old_install("D:/agentic-sdlc/hooks/git-hook-scan.mjs", legacy=True, manifest=False)
        self.assertEqual(self.install().returncode, 0)

    def test_crafted_manifest_cannot_make_install_overwrite_a_user_hook(self):
        hooks = _hooks(self.repo)
        hooks.mkdir(exist_ok=True)
        mine = "#!/bin/sh\necho mine\n"
        (hooks / "pre-commit").write_text(mine, encoding="utf-8")
        digest = hashlib.sha256((hooks / "pre-commit").read_bytes()).hexdigest()
        self.manifest().write_text(json.dumps({"version": 1, "hooks_dir": str(hooks.resolve()),
                                               "hooks": {"pre-commit": digest}}), encoding="utf-8")
        self.assertEqual(self.install().returncode, 2)
        self.assertEqual((hooks / "pre-commit").read_text(encoding="utf-8"), mine)

    def test_crafted_manifest_cannot_make_uninstall_remove_a_user_hook(self):
        hooks = _hooks(self.repo)
        hooks.mkdir(exist_ok=True)
        mine = "#!/bin/sh\necho mine\n"
        (hooks / "pre-commit").write_text(mine, encoding="utf-8")
        digest = hashlib.sha256((hooks / "pre-commit").read_bytes()).hexdigest()
        self.manifest().write_text(json.dumps({"version": 1, "hooks_dir": str(hooks.resolve()),
                                               "hooks": {"pre-commit": digest}}), encoding="utf-8")
        self.assertEqual(self.uninstall().returncode, 2)
        self.assertEqual((hooks / "pre-commit").read_text(encoding="utf-8"), mine)

    def test_version_1_manifest_still_read(self):
        # 0.7.0's digest bodies with its version 1 manifest are recorded, so --uninstall removes them;
        # without reading version 1 they would be unclaimed and left in place.
        self._old_install("/old/plugin/hooks/git-hook-scan.mjs")
        status = _check(self.plugin, self.repo)
        self.assertEqual(status["pre-commit"], "installed-stale")
        proc = self.uninstall()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        for name in HOOK_NAMES:
            self.assertFalse((_hooks(self.repo) / name).exists(), name)

    def test_unrecorded_generator_body_for_another_path_is_adopted(self):
        # D2: byte-identical generator output for the path it names is ours; one byte off is not.
        self._old_install("/elsewhere/agentic-sdlc/hooks/git-hook-scan.mjs", manifest=False)
        self.assertEqual(self.install().returncode, 0)
        variant = self.base / "variant"
        _make_repo(variant)
        installer = _load_installer(self.plugin, "variant")
        _hooks(variant).mkdir(exist_ok=True)
        body = installer._absolute_digest_body("pre-commit", "/elsewhere/agentic-sdlc/hooks/git-hook-scan.mjs")
        (_hooks(variant) / "pre-commit").write_text(body.replace("exec node", "exec  node"), encoding="utf-8")
        self.assertEqual(self.install(repo=variant).returncode, 2)

    def test_moved_repository_check_and_uninstall_without_reinstall(self):
        self.assertEqual(self.install().returncode, 0)
        moved = self.repo.rename(self.base / "moved")
        status = _check(self.plugin, moved)
        for name in HOOK_NAMES:
            self.assertEqual(status[name], "installed", name)
        self.assertEqual(status["scanner"], "current")
        proc = self.uninstall(repo=moved)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertFalse((_hooks(moved) / "pre-commit").exists())
        self.assertFalse((_hooks(moved) / VENDOR).exists())

    def test_manifest_paths_are_posix(self):
        self.assertEqual(self.install().returncode, 0)
        data = json.loads(self.manifest().read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 2)
        self.assertEqual(data["hooks_dir"], {"base": "common", "path": "hooks"})



# ---------------------------------------------------------------------------------------------
# Task 11 (AC20): --uninstall removes only verified bytes, inside the hooks folder.
# ---------------------------------------------------------------------------------------------
class TestR1SecurityInstaller(_Fixture):

    def _rewrite_manifest(self, update):
        data = json.loads(self.manifest().read_text(encoding="utf-8"))
        update(data)
        self.manifest().write_text(json.dumps(data), encoding="utf-8")

    def test_uninstall_keeps_an_unverifiable_vendored_file(self):
        self.assertEqual(self.install().returncode, 0)
        edited = _hooks(self.repo) / VENDOR / "git-exec.mjs"
        edited.write_text(edited.read_text(encoding="utf-8") + "// hand edit\n", encoding="utf-8")
        digest = hashlib.sha256(edited.read_bytes()).hexdigest()
        self._rewrite_manifest(lambda data: data["vendored"].__setitem__("git-exec.mjs", digest))
        proc = self.uninstall()
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertTrue(edited.exists(), "a file whose bytes are not the plugin's was deleted")
        self.assertIn("--install", proc.stdout)
        self.assertFalse((_hooks(self.repo) / VENDOR / "git-hook-scan.mjs").exists())

    def test_uninstall_exit_code_follows_the_record(self):
        self.assertEqual(self.install().returncode, 0)
        (_hooks(self.repo) / VENDOR / "notes.txt").write_text("mine\n", encoding="utf-8")
        self.assertEqual(self.uninstall().returncode, 0, "an unrecorded file alone must not fail uninstall")
        (_hooks(self.repo) / VENDOR / "notes.txt").unlink()
        self.assertEqual(self.install().returncode, 0)
        vendored = _hooks(self.repo) / VENDOR / "secret-patterns.mjs"
        vendored.write_text("// edited\n", encoding="utf-8")
        self.assertEqual(self.uninstall().returncode, 2, "a kept recorded file must fail uninstall")
        self.assertTrue(vendored.exists())

    def test_manifest_paths_outside_the_hooks_folder_are_ignored(self):
        self.assertEqual(self.install().returncode, 0)
        outside = self.base / "outside.txt"
        outside.write_text("keep me\n", encoding="utf-8")
        readme = self.repo / "readme.md"
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()

        def update(data):
            data["vendored"][str(outside)] = digest(outside)
            data["vendored"]["../../readme.md"] = digest(readme)
            data["hooks"]["../../readme.md"] = digest(readme)
        self._rewrite_manifest(update)
        self.assertEqual(self.uninstall().returncode, 0)
        self.assertTrue(outside.exists())
        self.assertTrue(readme.exists())

    @unittest.skipUnless(POSIX and NODE is not None, "POSIX path names and node required")
    def test_repo_path_with_shell_metacharacters_never_executes(self):
        name = "repo $(touch PWNED) `touch PWNED2` 'q' \"dq\""
        repo = self.repo.rename(self.base / name)
        self.assertEqual(self.install(repo=repo).returncode, 0)
        self.stage_token(repo)
        proc = self.commit(repo)
        self.assertNotEqual(proc.returncode, 0, proc.stderr[-300:])
        self.assertNotIn("scanner missing", proc.stderr)
        for folder in (self.base, repo, repo / ".git" / "hooks"):
            self.assertFalse((folder / "PWNED").exists())
            self.assertFalse((folder / "PWNED2").exists())


# ---------------------------------------------------------------------------------------------
# Round 1 security review follow-ups for the installer and the hook body (new tasks).
# ---------------------------------------------------------------------------------------------
class TestR1InstallerReviewFollowUps(_Fixture):

    @unittest.skipUnless(POSIX, "hard links and FIFOs on POSIX")
    def test_hard_linked_hook_target_is_not_written_through(self):
        installer = _load_installer(self.plugin, "hardlink")
        outside = self.base / "outside-hook"
        body = installer._legacy_hook_body("pre-commit")
        with open(str(outside), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
        _hooks(self.repo).mkdir(exist_ok=True)
        os.link(str(outside), str(_hooks(self.repo) / "pre-commit"))
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(outside.read_text(encoding="utf-8"), body, "the install wrote through a hard link")
        self.assertEqual((_hooks(self.repo) / "pre-commit").read_text(encoding="utf-8"),
                         installer.hook_body("pre-commit"))

    @unittest.skipUnless(POSIX and hasattr(os, "mkfifo"), "FIFOs on POSIX")
    def test_fifo_named_like_a_hook_does_not_hang(self):
        _hooks(self.repo).mkdir(exist_ok=True)
        os.mkfifo(str(_hooks(self.repo) / "pre-commit"))
        proc = subprocess.run([sys.executable, str(self.plugin / "scripts" / INSTALLER.name), "--check",
                               "--repo", str(self.repo)], env=GIT_ENV, capture_output=True, text=True,
                              encoding="utf-8", timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("pre-commit=foreign", proc.stdout)

    @unittest.skipIf(SH is None or NODE is None, "sh and node required")
    def test_hook_run_without_a_path_in_0_runs_no_scanner_from_the_cwd(self):
        self.assertEqual(self.install().returncode, 0)
        lure = self.base / "lure"
        (lure / VENDOR).mkdir(parents=True)
        marker = self.base / "lure-ran"
        (lure / VENDOR / "git-hook-scan.mjs").write_text(
            "import { writeFileSync } from 'node:fs';\nwriteFileSync(" + json.dumps(str(marker)) + ", 'x');\n",
            encoding="utf-8")
        shutil.copy2(str(_hooks(self.repo) / "pre-commit"), str(lure / "pre-commit"))
        proc = subprocess.run([SH, "pre-commit"], cwd=str(lure), env=GIT_ENV, capture_output=True,
                              text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(marker.exists(), "a scanner from the current directory ran")
        self.assertIn("NOT scanned", proc.stderr)

    @unittest.skipUnless(POSIX and SH is not None, "a backslash in a folder name needs POSIX")
    def test_warning_survives_a_backslash_in_the_hook_path(self):
        self.assertEqual(self.install().returncode, 0)
        odd = self.base / "odd\\c-dir"
        odd.mkdir()
        shutil.copy2(str(_hooks(self.repo) / "pre-commit"), str(odd / "pre-commit"))
        proc = subprocess.run([SH, str(odd / "pre-commit")], cwd=str(self.base), env=GIT_ENV,
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("NOT scanned", proc.stderr)

    @unittest.skipUnless(POSIX, "file modes on POSIX")
    def test_hook_is_executable_before_it_replaces_the_old_one(self):
        # Review 2 row 5: the mode was set after os.replace, so a commit in that window ran no hook.
        installer = _load_installer(self.plugin, "mode")
        modes = []
        real_replace = installer.os.replace

        def spy(src, dst):
            if Path(dst).name in HOOK_NAMES:
                modes.append(os.stat(src).st_mode & 0o111)
            return real_replace(src, dst)
        installer.os.replace = spy
        try:
            self.assertEqual(installer.cmd_install(self.repo), 0)
        finally:
            installer.os.replace = real_replace
        self.assertEqual(len(modes), len(HOOK_NAMES))
        self.assertTrue(all(modes), "a hook was put in place without its execute bit")

    def test_interrupted_write_leftover_does_not_block_install(self):
        # An install interrupted between the temp write and the rename leaves `.<name>.agentic-sdlc-tmp`;
        # that is the installer's own scratch name, not a foreign entry that refuses every later install.
        self.assertEqual(self.install().returncode, 0)
        leftover = _hooks(self.repo) / VENDOR / ".git-exec.mjs.agentic-sdlc-tmp"
        leftover.write_text("partial", encoding="utf-8")
        proc = self.install()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(leftover.exists())
        self.assertEqual(_check(self.plugin, self.repo)["scanner"], "current")

    def test_d2_does_not_adopt_a_body_whose_path_runs_shell_code(self):
        installer = _load_installer(self.plugin, "d2-shell")
        for scanner in ("/tmp/$(touch x)/hooks/git-hook-scan.mjs", "/tmp/`id`/hooks/git-hook-scan.mjs",
                        '/tmp/a"b/hooks/git-hook-scan.mjs'):
            with self.subTest(scanner=scanner):
                hook = self.base / ("hook-" + str(abs(hash(scanner))))
                with open(str(hook), "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(installer._legacy_hook_body("pre-commit", scanner))
                self.assertEqual(installer.hook_state(hook, "pre-commit"), "foreign")


# ---------------------------------------------------------------------------------------------
# Task 10 (AC19): one checkout used by WSL git and by Windows git.exe. Environment-dependent: it
# runs only inside WSL with Windows interop, AGENTIC_LIVE_WSL=1, and Windows git, node and Python
# 3.10+; it writes a temporary repository under the Windows temp folder. CI skips it.
# ---------------------------------------------------------------------------------------------
def _live_wsl_reason():
    if os.environ.get("AGENTIC_LIVE_WSL") != "1":
        return "set AGENTIC_LIVE_WSL=1 to run the live WSL/Windows check"
    try:
        kernel = Path("/proc/version").read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        kernel = ""
    if "microsoft" not in kernel:
        return "not running inside WSL"
    for tool in ("git.exe", "cmd.exe", "py.exe", "wslpath", "python3"):
        if shutil.which(tool) is None:
            return tool + " not found"
    run = dict(capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if "node" not in subprocess.run(["cmd.exe", "/c", "where", "node"], **run).stdout.lower():
        return "no Windows node on PATH"
    version = subprocess.run(["py.exe", "-3", "-c", "import sys; print(sys.version_info >= (3, 10))"], **run)
    if "True" not in version.stdout:
        return "Windows Python 3.10+ (py -3) not found"
    return ""


LIVE_WSL_REASON = _live_wsl_reason() if POSIX else "not running inside WSL"


@unittest.skipIf(bool(LIVE_WSL_REASON), LIVE_WSL_REASON or "live WSL check")
class TestLiveWslInterop(unittest.TestCase):

    installer = Path(os.environ.get("AGENTIC_INSTALLER") or str(INSTALLER))

    @staticmethod
    def _out(argv, **kw):
        return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=180, **kw)

    def _winpath(self, path):
        return self._out(["wslpath", "-w", str(path)]).stdout.strip()

    def setUp(self):
        temp = self._out(["cmd.exe", "/c", "echo %TEMP%"]).stdout.strip().splitlines()[-1]
        base = Path(self._out(["wslpath", "-u", temp]).stdout.strip())
        self.root = Path(tempfile.mkdtemp(prefix="agentic-live-wsl-", dir=str(base)))
        self.addCleanup(shutil.rmtree, str(self.root), ignore_errors=True)
        self.repo = self.root / "repo"
        _make_repo(self.repo)
        self.win_repo = self._winpath(self.repo)

    def _stage(self, name, text):
        (self.repo / name).write_text(text, encoding="utf-8")
        _git(self.repo, "add", name)

    def _commit_wsl(self, message):
        return _git(self.repo, "commit", "-m", message, check=False)

    def _commit_windows(self, message):
        return self._out(["git.exe", "-c", "safe.directory=*", "-C", self.win_repo, "commit", "-m", message])

    def _assert_both_sides(self):
        self._stage("config.py", "key = '" + SECRET + "'\n")
        for side, run in (("wsl", self._commit_wsl), ("windows", self._commit_windows)):
            with self.subTest(side=side):
                proc = run("fix: token")
                self.assertNotEqual(proc.returncode, 0, side + " committed a staged token: " + proc.stderr[-300:])
                self.assertNotIn("scanner missing", proc.stderr)
        _git(self.repo, "reset", "-q", "config.py")
        for side, run in (("wsl", self._commit_wsl), ("windows", self._commit_windows)):
            self._stage("notes-" + side + ".md", "clean " + side + "\n")
            proc = run("docs: " + side)
            self.assertEqual(proc.returncode, 0, side + " clean commit failed: " + proc.stderr[-300:])

    def test_install_from_wsl_scans_on_both_sides(self):
        proc = self._out([sys.executable, str(self.installer), "--install", "--repo", str(self.repo)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self._assert_both_sides()

    def test_install_from_windows_scans_on_both_sides(self):
        proc = self._out(["py.exe", "-3", self._winpath(self.installer), "--install", "--repo", self.win_repo])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self._assert_both_sides()


if __name__ == "__main__":
    unittest.main()
