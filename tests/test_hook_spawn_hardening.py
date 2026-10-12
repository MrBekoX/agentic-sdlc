"""Hooks run inside the user's project, which may be hostile; their child processes must not be.

Security analysis #1 (cross-platform-distribution) reproduced each case below against the hooks:

* A bare `git` spawn resolves through the working directory on Windows (and through a relative
  `PATH` entry such as `.` on every OS), so a `git` planted in the project ran from the
  SessionStart, commit, branch and Stop hooks.
* `color.ui=always` or a committed `.gitattributes` with `-diff` hid every added line from the
  commit scanners (coloured `+` lines, "Binary files differ").
* NUL-separated listings stopped trimming names, so ` id_rsa` or `cert.p12 ` slipped past the
  credential-filename check; raw control characters in a name reached guard output verbatim.
* The flow validator ran Python in the project directory without `-I`, so a planted
  `sitecustomize.py` (via an empty `PYTHONPATH` entry) or a version-shim file there controlled it.

Planted programs here write a marker file; the guard must still decide correctly and the marker must
not appear. POSIX-only where the case needs an executable shell script.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
GIT = shutil.which("git")
SECRET = "ghp_" + "a1B2" * 9
POSIX = os.name != "nt"


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          check=True)


def _repo(root, branch="feature"):
    _git(["init", "-q", "-b", branch], root)
    _git(["config", "user.email", "t@e.st"], root)
    _git(["config", "user.name", "t"], root)
    _git(["config", "commit.gpgsign", "false"], root)


def _planted(directory, name, marker):
    path = Path(directory, name)
    path.write_text("#!/bin/sh\ntouch '%s'\nexit 0\n" % marker, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


@unittest.skipIf(NODE is None or GIT is None, "node or git not available")
class TestPlantedGitIsNeverRun(unittest.TestCase):
    """`.` first on PATH is the POSIX analogue of Windows' current-directory search."""

    def _hostile_project(self):
        td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        _repo(td, branch="main")
        marker = td / "PLANTED-GIT-RAN"
        return td, marker

    def _env(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTIC_")}
        env["PATH"] = os.pathsep.join([".", str(Path(GIT).parent), str(Path(NODE).parent)])
        env["AGENTIC_BRANCH_GUARD_BLOCK"] = "true"
        return env

    @unittest.skipUnless(POSIX, "needs an executable shell-script git")
    def test_hooks_never_execute_a_project_git(self):
        payload = lambda td: json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                         "cwd": str(td), "tool_input": {"command": "git commit -m x"}})
        for hook in ("session-start.mjs", "session-start-codex.mjs", "scan-commit.mjs",
                     "branch-guard.mjs", "worktree-scan.mjs"):
            with self.subTest(hook=hook):
                td, marker = self._hostile_project()
                _planted(td, "git", marker)
                proc = subprocess.run([NODE, str(REPO / "hooks" / hook)], cwd=td, env=self._env(),
                                      input=payload(td), capture_output=True, text=True,
                                      encoding="utf-8", timeout=60)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertFalse(marker.exists(), "%s executed a git planted in the project" % hook)

    @unittest.skipUnless(POSIX, "needs an executable shell-script git")
    def test_the_branch_guard_still_sees_the_real_branch(self):
        td, marker = self._hostile_project()
        _planted(td, "git", marker)
        proc = subprocess.run([NODE, str(REPO / "hooks" / "branch-guard.mjs")], cwd=td, env=self._env(),
                              input=json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                                "cwd": str(td), "tool_input": {"command": "git commit -m x"}}),
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        out = json.loads(proc.stdout) if proc.stdout.strip() else {}
        self.assertEqual(out.get("hookSpecificOutput", {}).get("permissionDecision"), "deny")
        self.assertFalse(marker.exists())


@unittest.skipIf(NODE is None or GIT is None, "node or git not available")
class TestGitSettingsCannotBlindTheScanners(unittest.TestCase):
    def _staged(self, configure):
        td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        _repo(td)
        configure(td)
        (td / "app.cfg").write_text("TOKEN = " + SECRET + "\n", encoding="utf-8")
        _git(["add", "-A"], td)
        return td

    def _scan_commit(self, td, cwd=None):
        cwd = cwd or td
        proc = subprocess.run([NODE, str(REPO / "hooks" / "scan-commit.mjs")], cwd=cwd,
                              input=json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                                "cwd": str(cwd), "tool_input": {"command": "git commit -m x"}}),
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout) if proc.stdout.strip() else {}
        return out.get("hookSpecificOutput", {}).get("permissionDecision")

    def _pre_commit(self, td):
        proc = subprocess.run([NODE, str(REPO / "hooks" / "git-hook-scan.mjs"), "pre-commit"], cwd=td,
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        return proc.returncode

    def test_forced_colour_does_not_hide_added_lines(self):
        td = self._staged(lambda r: _git(["config", "color.ui", "always"], r))
        self.assertEqual(self._scan_commit(td), "deny")
        self.assertNotEqual(self._pre_commit(td), 0)

    def test_a_no_diff_attribute_does_not_hide_added_lines(self):
        def attrs(r):
            (r / ".gitattributes").write_text("*.cfg -diff\n", encoding="utf-8")
        td = self._staged(attrs)
        self.assertEqual(self._scan_commit(td), "deny")
        self.assertNotEqual(self._pre_commit(td), 0)

    # Security analysis #2: `color.diff` (and its older alias `diff.color`) outrank `color.ui`, so
    # `-c color.ui=never` alone left every added line coloured; `diff.relative` hid every file
    # outside the session's subdirectory; the default 1 MiB buffer turned a lockfile-sized change
    # into "NOT scanned".
    def test_a_diff_specific_colour_key_does_not_hide_added_lines(self):
        for key in ("color.diff", "diff.color"):
            with self.subTest(key=key):
                td = self._staged(lambda r, k=key: _git(["config", k, "always"], r))
                self.assertEqual(self._scan_commit(td), "deny")
                self.assertNotEqual(self._pre_commit(td), 0)

    def test_relative_diffs_do_not_hide_files_outside_the_subdirectory(self):
        def relative(r):
            _git(["config", "diff.relative", "true"], r)
            (r / "sub").mkdir()
            (r / "sub" / "keep.txt").write_text("x\n", encoding="utf-8")
        td = self._staged(relative)
        self.assertEqual(self._scan_commit(td, cwd=td / "sub"), "deny")

    def test_a_large_staged_diff_is_still_scanned(self):
        def large(r):
            (r / "big.lock").write_text(("x" * 99 + "\n") * 11000, encoding="utf-8")
        td = self._staged(large)
        self.assertEqual(self._scan_commit(td), "deny")


@unittest.skipIf(NODE is None or GIT is None, "node or git not available")
class TestScannerReach(unittest.TestCase):
    """Security analysis #2: what a repository's own state could keep the scanners from seeing."""

    def _committed(self):
        td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        _repo(td)
        (td / "README.md").write_text("x\n", encoding="utf-8")
        _git(["add", "-A"], td)
        _git(["commit", "-qm", "base"], td)
        return td

    def _hook(self, name, cwd, payload, *args):
        state = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, state, ignore_errors=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTIC_")}
        env["AGENTIC_WORKTREE_SCAN_STATE"] = str(state / "seen.json")
        return subprocess.run([NODE, str(REPO / "hooks" / name), *args], cwd=cwd, env=env,
                              input=json.dumps(payload), capture_output=True, text=True,
                              encoding="utf-8", timeout=60)

    def _commit_decision(self, td):
        proc = self._hook("scan-commit.mjs", td, {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                                  "cwd": str(td), "tool_input": {"command": "git commit -m x"}})
        out = json.loads(proc.stdout) if proc.stdout.strip() else {}
        return out.get("hookSpecificOutput", {}).get("permissionDecision")

    @unittest.skipUnless(POSIX, "needs a committed symlink")
    def test_a_type_change_still_reveals_a_credential_file_name(self):
        td = self._committed()
        (td / "deploy.p12").symlink_to("README.md")
        _git(["add", "deploy.p12"], td)
        _git(["commit", "-qm", "link"], td)
        (td / "deploy.p12").unlink()
        (td / "deploy.p12").write_bytes(b"\x30\x82\x01\x00binary-key")
        _git(["add", "deploy.p12"], td)
        self.assertEqual(self._commit_decision(td), "deny")
        proc = self._hook("git-hook-scan.mjs", td, {}, "pre-commit")
        self.assertNotEqual(proc.returncode, 0)

    @unittest.skipUnless(POSIX, "needs an executable repository hook")
    def test_read_only_git_calls_do_not_run_repository_hooks(self):
        td = self._committed()
        marker = td.parent / (td.name + "-REPO-HOOK-RAN")
        self.addCleanup(lambda: marker.exists() and marker.unlink())
        hook = td / ".git" / "hooks" / "post-index-change"
        hook.write_text("#!/bin/sh\ntouch '%s'\n" % marker, encoding="utf-8")
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
        os.utime(td / "README.md", (1, 1))  # stat-dirty: the next index refresh rewrites the index
        self._hook("worktree-scan.mjs", td, {"hook_event_name": "Stop", "cwd": str(td), "session_id": "reach"})
        self._hook("session-start.mjs", td, {"hook_event_name": "SessionStart", "cwd": str(td)})
        self.assertFalse(marker.exists(), "a read-only scan ran a repository hook")

    def test_added_lines_that_start_with_plus_signs_are_scanned(self):
        # The header filter `!l.startsWith('+++')` also dropped every ADDED line whose content
        # starts with `++`, so `++ <token>` passed all three scanners.
        td = self._committed()
        (td / "notes.md").write_text("++ " + SECRET + "\n", encoding="utf-8")
        _git(["add", "notes.md"], td)
        self.assertEqual(self._commit_decision(td), "deny")
        self.assertNotEqual(self._hook("git-hook-scan.mjs", td, {}, "pre-commit").returncode, 0)
        stop = self._hook("worktree-scan.mjs", td, {"hook_event_name": "Stop", "cwd": str(td), "session_id": "plus"})
        self.assertIn("uncommitted change", stop.stdout)

    def test_hook_lookup_is_disabled_inside_the_plugin_not_at_the_filesystem_root(self):
        # An empty `core.hooksPath=` sends hook lookup to `/<hook>`: on Windows the current drive's
        # root, which other local users can often write.
        td = self._committed()
        code = ("import { runGit } from %s;"
                "process.stdout.write(runGit(['rev-parse', '--git-path', 'hooks/post-index-change'],"
                " { cwd: %s, encoding: 'utf8' }))"
                % (json.dumps((REPO / "hooks" / "git-exec.mjs").as_uri()), json.dumps(str(td))))
        proc = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True,
                              encoding="utf-8", timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lookup = Path(proc.stdout.strip())
        self.assertTrue(lookup.is_absolute(), lookup)
        self.assertEqual(lookup.parent.parent.resolve(), (REPO / "hooks").resolve())
        self.assertFalse(lookup.parent.exists(), "the disabled-hooks folder must never exist")

    def test_ignored_files_are_not_pushed_past_the_untracked_cap(self):
        # 200 ordinary untracked files filled the cap before the ignored `.env` was reached.
        td = self._committed()
        (td / ".gitignore").write_text(".env\n", encoding="utf-8")
        (td / "many").mkdir()
        for index in range(201):
            (td / "many" / ("f%03d.txt" % index)).write_text("x\n", encoding="utf-8")
        (td / ".env").write_text("TOKEN=" + SECRET + "\n", encoding="utf-8")
        proc = self._hook("worktree-scan.mjs", td, {"hook_event_name": "Stop", "cwd": str(td), "session_id": "cap"})
        self.assertIn(".env", proc.stdout)

    def test_a_deep_ignored_cache_does_not_hide_a_top_level_env(self):
        # `.cache/…` sorts before `.env`, and `.env` is not a credential FILE NAME, so only its
        # content scan finds the token; a fixed share of the cap for ignored files missed it.
        td = self._committed()
        (td / ".gitignore").write_text(".cache/\n.env\n", encoding="utf-8")
        (td / ".cache").mkdir()
        for index in range(150):
            (td / ".cache" / ("c%03d" % index)).write_text("x\n", encoding="utf-8")
        (td / ".env").write_text("TOKEN=" + SECRET + "\n", encoding="utf-8")
        proc = self._hook("worktree-scan.mjs", td, {"hook_event_name": "Stop", "cwd": str(td), "session_id": "cache"})
        self.assertIn(".env", proc.stdout)

    def test_large_ignored_files_do_not_use_up_the_budget_for_new_files(self):
        # Reading ignored files first let 20 large logs spend the byte budget before a new
        # untracked source file with a token was reached.
        td = self._committed()
        (td / ".gitignore").write_text("logs/\n", encoding="utf-8")
        (td / "logs").mkdir()
        for index in range(20):
            (td / "logs" / ("l%02d.log" % index)).write_text(("y" * 99 + "\n") * 2500, encoding="utf-8")
        (td / "config.js").write_text("const t = '" + SECRET + "';\n", encoding="utf-8")
        proc = self._hook("worktree-scan.mjs", td, {"hook_event_name": "Stop", "cwd": str(td), "session_id": "logs"})
        self.assertIn("config.js", proc.stdout)

    def test_a_new_multi_file_feature_is_read_despite_large_ignored_artifacts(self):
        # Alternating file SLOTS still let ignored artifacts (coverage HTML, logs) spend the BYTE
        # budget before the later files of a new feature were read.
        layouts = {
            "logs": (".gitignore-logs", "logs", 40, 200 * 1024, "src/payments", 30, ".py"),
            "htmlcov": (".gitignore-htmlcov", "htmlcov", 120, 120 * 1024, "app/svc", 40, ".py"),
        }
        for name, (_label, ignored_dir, count, size, feature, files, suffix) in layouts.items():
            with self.subTest(layout=name):
                td = self._committed()
                (td / ".gitignore").write_text(ignored_dir + "/\n", encoding="utf-8")
                (td / ignored_dir).mkdir()
                line = "z" * 99 + "\n"
                for index in range(count):
                    (td / ignored_dir / ("a%03d.txt" % index)).write_text(line * (size // 100), encoding="utf-8")
                (td / feature).mkdir(parents=True)
                for index in range(files):
                    body = "x = %d\n" % index
                    if index == files - 1:
                        body += "token = '" + SECRET + "'\n"
                    (td / feature / ("m%02d%s" % (index, suffix))).write_text(body, encoding="utf-8")
                proc = self._hook("worktree-scan.mjs", td,
                                  {"hook_event_name": "Stop", "cwd": str(td), "session_id": "feature-" + name})
                self.assertIn("m%02d%s" % (files - 1, suffix), proc.stdout)

    def test_a_large_vendor_tree_does_not_overflow_the_ignored_listing(self):
        # The ignored listing walked node_modules and overflowed its buffer, dropping every ignored
        # file (`.env` included); vendor trees are now excluded by pathspec before listing.
        td = self._committed()
        (td / ".gitignore").write_text("node_modules/\n.env\n", encoding="utf-8")
        vendor = td / "node_modules" / ("p" * 60)
        vendor.mkdir(parents=True)
        for index in range(45000):
            (vendor / ("f%05d-%s.js" % (index, "q" * 40))).touch()
        (td / ".env").write_text("TOKEN=" + SECRET + "\n", encoding="utf-8")
        proc = self._hook("worktree-scan.mjs", td, {"hook_event_name": "Stop", "cwd": str(td), "session_id": "vendor"})
        self.assertIn(".env", proc.stdout)

    def test_the_stop_scan_reads_untracked_files_from_a_subdirectory(self):
        td = self._committed()
        (td / "app").mkdir()
        (td / "app" / "notes.txt").write_text("TOKEN = " + SECRET + "\n", encoding="utf-8")
        proc = self._hook("worktree-scan.mjs", td / "app",
                          {"hook_event_name": "Stop", "cwd": str(td / "app"), "session_id": "subdir"})
        self.assertIn("notes.txt", proc.stdout)


@unittest.skipIf(NODE is None, "node not available")
class TestPathEntries(unittest.TestCase):
    def test_quoted_windows_path_entries_are_unquoted(self):
        # Windows allows `"C:\Program Files\Git\cmd"` in PATH; the bare spawn found git there, the
        # absolute-entry rule did not, and every git-based guard failed open.
        code = ("import { pathEntries } from %s;"
                "process.stdout.write(JSON.stringify([pathEntries(%s, true), pathEntries(%s, false)]))"
                % (json.dumps((REPO / "hooks" / "git-exec.mjs").as_uri()),
                   json.dumps('"C:\\Program Files\\Git\\cmd";C:\\x;;rel'), json.dumps('/a:"/b"')))
        proc = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True,
                              encoding="utf-8", timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout),
                         [["C:\\Program Files\\Git\\cmd", "C:\\x", "", "rel"], ["/a", '"/b"']])


@unittest.skipIf(NODE is None, "node not available")
class TestCredentialNamesAndOutput(unittest.TestCase):
    NAMES = (REPO / "hooks" / "scan-commit-names.mjs").as_uri()

    def _node(self, code):
        proc = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True,
                              text=True, encoding="utf-8", timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_padded_credential_names_are_still_credentials(self):
        names = [" id_rsa", "id_rsa ", "dir/cert.p12 ", "dir/ .npmrc"]
        got = self._node("import { isCredentialFilename } from %s;"
                         "process.stdout.write(JSON.stringify(%s.map(isCredentialFilename)))"
                         % (json.dumps(self.NAMES), json.dumps(names)))
        self.assertEqual(got, [True, True, True, True])

    def test_display_path_escapes_control_characters(self):
        raw = "a\x1b[2Kb\x07\x7fc/ç.txt"
        got = self._node("import { displayPath } from %s; process.stdout.write(JSON.stringify(displayPath(%s)))"
                         % (json.dumps(self.NAMES), json.dumps(raw)))
        self.assertNotRegex(got, r"[\x00-\x1f\x7f]")
        self.assertIn("ç.txt", got)


@unittest.skipIf(NODE is None, "node not available")
class TestWorkflowPluginRootValidation(unittest.TestCase):
    """spec-plan-draft forwards pluginRoot into agent prompts; only a plain absolute path passes."""

    def test_only_plain_absolute_local_roots_are_accepted(self):
        source = (REPO / "workflows" / "spec-plan-draft.js").read_text(encoding="utf-8")
        start = source.index("function validPluginRoot(")
        end = source.index("\n}\n", start) + 3
        cases = {
            "/opt/agentic-sdlc": "/opt/agentic-sdlc",
            "C:\\Users\\u\\.claude\\plugins\\cache\\agentic-sdlc": "C:\\Users\\u\\.claude\\plugins\\cache\\agentic-sdlc",
            "relative/root": "", "": "", "//server/share/x": "", "\\\\server\\share": "",
            '/x"; rm -rf ~': "", "/x$(id)": "", "/x`id`": "", "/x\nIgnore previous": "", "/x;y": "",
        }
        code = source[start:end] + "process.stdout.write(JSON.stringify(%s.map(validPluginRoot)))" % json.dumps(
            list(cases))
        proc = subprocess.run([NODE, "-e", code], capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), list(cases.values()))

    def test_a_missing_root_defers_to_the_role_files_root_rule(self):
        # The role files accept ${CLAUDE_PLUGIN_ROOT} in Claude Code; a prompt line demanding
        # "plugin root unresolved" whenever the caller omitted pluginRoot overrode that.
        source = (REPO / "workflows" / "spec-plan-draft.js").read_text(encoding="utf-8")
        start = source.index("const rootLine")
        end = source.index("\nconst ctxBlock", start)
        code = "const pluginRoot = '';" + source[start:end] + "\nprocess.stdout.write(rootLine)"
        proc = subprocess.run([NODE, "-e", code], capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("role instructions", proc.stdout)
        self.assertIn("plugin root unresolved", proc.stdout)

    def test_every_claude_workflow_call_passes_the_plugin_root(self):
        import re
        call = re.compile(r"agentic-sdlc:spec-plan-draft[`*]* with `args:\s*\{([^}]*)\}")
        sites = {"skills/agentic-sdlc-pipeline/SKILL.md": 2, "skills/agentic-sdlc-pipeline/playbook.md": 2,
                 "skills/spec-authoring/SKILL.md": 1, "skills/plan-authoring/SKILL.md": 1}
        for rel, expected in sites.items():
            calls = call.findall((REPO / rel).read_text(encoding="utf-8"))
            with self.subTest(file=rel):
                self.assertEqual(len(calls), expected)
                for args in calls:
                    self.assertRegex(args, r"pluginRoot:\s*[\"']<runtime-root>[\"']")


@unittest.skipIf(NODE is None, "node not available")
@unittest.skipUnless(POSIX, "needs an executable shell-script interpreter wrapper")
class TestValidatorInterpreterIsolation(unittest.TestCase):
    """The validator runs from the plugin root with `-I`, never configured by the project."""

    def test_probe_and_validator_run_isolated_from_the_project(self):
        td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        bindir, project = td / "bin", td / "project"
        bindir.mkdir()
        (project / "docs" / "agentic-sdlc" / "specs").mkdir(parents=True)
        (project / "docs" / "agentic-sdlc" / "specs" / "x.md").write_text("spec\n", encoding="utf-8")
        log = td / "calls.log"
        wrapper = bindir / "python3"
        wrapper.write_text('#!/bin/sh\nprintf "%%s|%%s\\n" "$(pwd)" "$*" >> "%s"\nexec "%s" "$@"\n'
                           % (log, sys.executable), encoding="utf-8")
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
        driver = ("import { runValidator } from %s;"
                  "process.stdout.write(String(runValidator('spec', 'docs/agentic-sdlc/specs/x.md', null, %s)))"
                  % (json.dumps((REPO / "hooks" / "flow-evidence.mjs").as_uri()), json.dumps(str(project))))
        env = {k: v for k, v in os.environ.items() if k.upper() not in ("PATH", "AGENTIC_SDLC_PYTHON")}
        env["PATH"] = os.pathsep.join([str(bindir), str(Path(NODE).parent)])
        proc = subprocess.run([NODE, "--input-type=module", "-e", driver], cwd=project, env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "1", "a stub spec must still fail validation")
        calls = [line.split("|", 1) for line in log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(calls), 2, calls)               # the probe, then the validator
        for cwd, argv in calls:
            self.assertEqual(Path(cwd).resolve(), REPO.resolve())
            self.assertTrue(argv.startswith("-I "), argv)


if __name__ == "__main__":
    unittest.main()
