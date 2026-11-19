"""Regression tests for the release and packaging findings RL-1..RL-10 of the f430715 bug audit.

Installers and builders run only against temporary package and destination directories; the
Cursor installer always gets an explicit destination, so the real profile is never touched.
Synthetic secrets are assembled at run time.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import secrets
import shutil
import string
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))
import build_release  # noqa: E402
import check_cursor_plugin  # noqa: E402
import install_cursor_plugin  # noqa: E402


def _load(name):
    spec = importlib.util.spec_from_file_location(name + "_rl_under_test", SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bump_version = _load("bump_version")
check_native_lifecycle = _load("check_native_lifecycle")
check_codex_hook_trust = _load("check_codex_hook_trust")

HAS_GIT = shutil.which("git") is not None
HAS_NODE = shutil.which("node") is not None
PRIVATE_FILES = {
    ".env": "SYNTHETIC=1\n",
    "settings.local.json": "{}\n",
    "AGENTS.md": "local\n",
    "CLAUDE.md": "local\n",
    "session-reports/2026-11-18-report.md": "local report\n",
    ".video_agent/state.json": "{}\n",
    "audit-docs/dump.md": "dump\n",
    ".handoffs/h.md": "handoff\n",
    "agentic-sdlc-prompts/plan.md": "prompt\n",
}


def _write(root: Path, files: dict) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))


def _quiet(func, *args, **kwargs):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = func(*args, **kwargs)
    return result, out.getvalue()


def _token() -> str:
    alphabet = string.ascii_letters + string.digits
    return "gh" + "p_" + "".join(secrets.choice(alphabet) for _ in range(36))


class ScratchGit:
    """A git repository in a temporary directory, isolated from the host git configuration."""

    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        config = root.parent / (root.name + ".gitconfig")
        config.write_bytes(b"")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(
            GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=str(config), GIT_TERMINAL_PROMPT="0",
            GIT_AUTHOR_NAME="Scratch", GIT_AUTHOR_EMAIL="scratch@example.invalid",
            GIT_COMMITTER_NAME="Scratch", GIT_COMMITTER_EMAIL="scratch@example.invalid",
            GIT_AUTHOR_DATE="2026-01-01T00:00:00Z", GIT_COMMITTER_DATE="2026-01-01T00:00:00Z",
        )
        self.git("init", "-q", "-b", "main")
        self.git("config", "core.autocrlf", "false")

    def git(self, *args) -> str:
        proc = subprocess.run(["git", *args], cwd=self.root, env=self.env, capture_output=True)
        if proc.returncode != 0:
            raise AssertionError(proc.stderr.decode("utf-8", "replace"))
        return proc.stdout.decode("utf-8", "replace")

    def commit(self, files: dict, force: bool = False) -> None:
        _write(self.root, files)
        self.git("add", *(["-f"] if force else []), "--", *files)
        self.git("commit", "-q", "-m", "c")


class TmpCase(unittest.TestCase):
    def setUp(self):
        handle = tempfile.TemporaryDirectory()
        self.addCleanup(handle.cleanup)
        self.tmp = Path(handle.name)


# ---------------------------------------------------------------- RL-1 / RL-10 Cursor installer

def _receipt(dest: Path):
    path = dest / install_cursor_plugin.RECEIPT
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


class TestRl1InstallerOwnsOnlyItsFiles(TmpCase):
    def package(self, files):
        pkg = self.tmp / "pkg"
        _write(pkg, {".cursor-plugin/plugin.json": "{}\n", **files})
        return pkg

    def test_rl1_install_refuses_a_nonempty_destination_without_a_receipt(self):
        pkg = self.package({"README.md": "plugin readme\n"})
        dest = self.tmp / "dest"
        _write(dest, {"README.md": "user readme\n"})
        code, lines = install_cursor_plugin.install(pkg, dest)
        self.assertEqual(code, 1, lines)
        self.assertIn("cursor_install=failed", lines)
        self.assertTrue(any(line.startswith("error=cursor_dest_not_empty") for line in lines), lines)
        self.assertEqual((dest / "README.md").read_text(encoding="utf-8"), "user readme\n")
        self.assertIsNone(_receipt(dest))

    def test_rl1_update_never_takes_over_a_file_the_installer_did_not_write(self):
        pkg = self.package({"a.txt": "a1\n"})
        dest = self.tmp / "dest"
        self.assertEqual(install_cursor_plugin.install(pkg, dest)[0], 0)
        _write(dest, {"b.txt": "user b\n"})
        _write(pkg, {"a.txt": "a2\n", "b.txt": "plugin b\n"})
        code, lines = install_cursor_plugin.install(pkg, dest)
        self.assertEqual(code, 1, lines)
        self.assertIn("error=cursor_dest_file_unmanaged:b.txt", lines)
        self.assertEqual((dest / "b.txt").read_text(encoding="utf-8"), "user b\n")
        self.assertNotIn("b.txt", _receipt(dest)["managed"])
        self.assertEqual(install_cursor_plugin.uninstall(dest)[0], 0)
        self.assertEqual((dest / "b.txt").read_text(encoding="utf-8"), "user b\n")
        self.assertFalse((dest / "a.txt").exists())

    def test_rl1_an_empty_existing_destination_is_accepted(self):
        pkg = self.package({"a.txt": "a\n"})
        dest = self.tmp / "dest"
        dest.mkdir()
        code, lines = install_cursor_plugin.install(pkg, dest)
        self.assertEqual(code, 0, lines)
        self.assertEqual(sorted(_receipt(dest)["managed"]), [".cursor-plugin/plugin.json", "a.txt"])

    def test_rl1_an_interrupted_install_leaves_a_receipt_so_the_retry_proceeds(self):
        pkg = self.package({"a.txt": "a\n", "b.txt": "b\n"})
        dest = self.tmp / "dest"
        real_copy = shutil.copy2
        calls = []

        def failing_copy(src, dst, *args, **kwargs):
            calls.append(dst)
            if len(calls) == 2:
                raise OSError("disk full")
            return real_copy(src, dst, *args, **kwargs)

        with mock.patch.object(install_cursor_plugin.shutil, "copy2", failing_copy):
            with self.assertRaises(OSError):
                install_cursor_plugin.install(pkg, dest)
        self.assertIsNotNone(_receipt(dest))
        code, lines = install_cursor_plugin.install(pkg, dest)
        self.assertEqual(code, 0, lines)
        self.assertEqual(install_cursor_plugin.uninstall(dest)[0], 0)
        self.assertFalse(dest.exists())


class TestRl10ReceiptPathsStayInsideTheDestination(TmpCase):
    def test_rl10_receipt_rejects_windows_drive_and_other_absolute_forms(self):
        dest = self.tmp / "dest"
        managed = ["C:/Windows/win.ini", "c:relative.txt", "D:\\x.txt", "/etc/hosts", "//server/share/x",
                   "\\\\server\\share\\x", "../outside.txt", "a/../../b", "ok/file.txt", "", "a\x00b"]
        _write(dest, {install_cursor_plugin.RECEIPT: json.dumps({"name": "agentic-sdlc", "managed": managed})})
        self.assertEqual(install_cursor_plugin._load_receipt(dest), ["ok/file.txt"])

    @unittest.skipIf(os.name == "nt", "symlink creation needs a privilege on Windows")
    def test_rl10_uninstall_does_not_delete_through_a_symlinked_folder(self):
        outside = self.tmp / "outside"
        _write(outside, {"victim.txt": "keep\n"})
        dest = self.tmp / "dest"
        _write(dest, {"own.txt": "x\n", install_cursor_plugin.RECEIPT: json.dumps(
            {"name": "agentic-sdlc", "managed": ["own.txt", "link/victim.txt"]})})
        (dest / "link").symlink_to(outside, target_is_directory=True)
        code, _lines = install_cursor_plugin.uninstall(dest)
        self.assertEqual(code, 0)
        self.assertEqual((outside / "victim.txt").read_text(encoding="utf-8"), "keep\n")
        self.assertFalse((dest / "own.txt").exists())


# ---------------------------------------------------------------- RL-3 package copies

class TestRl3CopiesHoldOnlyShippableFiles(TmpCase):
    COMMITTED = {
        ".cursor-plugin/plugin.json": "{}\n",
        "README.md": "readme\n",
        "skills/demo/SKILL.md": "---\nname: demo\ndescription: Use for demo.\n---\n",
    }

    def checkout(self):
        repo = ScratchGit(self.tmp / "pkg")
        repo.commit(self.COMMITTED)
        repo.commit({"CLAUDE.md": "force-added local file\n"}, force=True)
        _write(repo.root, {**PRIVATE_FILES, "untracked-notes.txt": "scratch\n"})
        return repo.root

    def extracted(self):
        pkg = self.tmp / "extracted"
        _write(pkg, {**self.COMMITTED, **PRIVATE_FILES})
        return pkg

    def assert_only_shippable(self, root: Path, extra=()):
        present = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
        expected = sorted(set(self.COMMITTED) | set(extra))
        self.assertEqual(present, expected)

    @unittest.skipUnless(HAS_GIT, "git not available")
    def test_rl3_installer_copies_the_committed_tree_of_a_checkout(self):
        dest = self.tmp / "dest"
        code, lines = install_cursor_plugin.install(self.checkout(), dest)
        self.assertEqual(code, 0, lines)
        self.assertEqual(sorted(_receipt(dest)["managed"]), sorted(self.COMMITTED))
        self.assert_only_shippable(dest, extra=[install_cursor_plugin.RECEIPT])

    def test_rl3_installer_drops_excluded_classes_from_an_extracted_package(self):
        dest = self.tmp / "dest"
        code, lines = install_cursor_plugin.install(self.extracted(), dest)
        self.assertEqual(code, 0, lines)
        self.assertEqual(sorted(_receipt(dest)["managed"]), sorted(self.COMMITTED))

    @unittest.skipUnless(HAS_GIT, "git not available")
    def test_rl3_native_lifecycle_copy_of_a_checkout_holds_only_committed_files(self):
        dest = self.tmp / "copy"
        check_native_lifecycle.copy_package(self.checkout(), dest)
        self.assert_only_shippable(dest)

    def test_rl3_native_lifecycle_copy_of_an_extracted_package_drops_private_files(self):
        dest = self.tmp / "copy"
        check_native_lifecycle.copy_package(self.extracted(), dest)
        self.assert_only_shippable(dest)


# ---------------------------------------------------------------- RL-2 / RL-5 / RL-7 release builder

class TestRl5LocalOnlyRootsNeverShip(TmpCase):
    LOCAL_ONLY = (
        "session-reports/2026-11-18-report.md", ".video_agent/state.json", ".codegraph/index.db",
        ".zcode/workflows/x.ts", ".opencode/config.json", ".omo/run.json", ".sdd/state.json",
        ".worktrees/fix/README.md", ".tmp-superpowers-compare/x.md", "_tmp_superpowers_benchmark/x.md",
        "mcps/server.json", "debug.txt", "scheduled_tasks.lock", "2026-11-18-120000-trace.txt",
        "Session-Reports/x.md", "nested/session-reports/x.md",
    )
    NEAR_MISSES = (
        "docs/session-reports.md", ".zcode-plugin/plugin.json", "skills/x/debugging.txt",
        "docs/2026-11-18-120000-trace.txt", "scripts/mcps.py",
    )

    def test_rl5_local_only_roots_have_an_exclusion_class(self):
        for path in self.LOCAL_ONLY:
            with self.subTest(path=path):
                self.assertIsNotNone(build_release.exclusion_class(path, "100644"))
        for path in self.NEAR_MISSES:
            with self.subTest(near_miss=path):
                self.assertIsNone(build_release.exclusion_class(path, "100644"))

    def test_rl5_local_only_rule_is_linear_on_a_long_single_segment(self):
        import time
        long_name = "2026-11-18-" + "a." * 200000 + "tx"
        started = time.monotonic()
        self.assertEqual(build_release.exclusion_class(long_name, "100644"), None)
        self.assertEqual(build_release.exclusion_class(long_name + "t", "100644"), 8)
        self.assertLess(time.monotonic() - started, 2.0)

    @unittest.skipUnless(HAS_GIT, "git not available")
    def test_rl5_build_refuses_force_added_local_only_files(self):
        repo = ScratchGit(self.tmp / "repo")
        repo.commit({"LICENSE": "MIT\n"})
        repo.commit({"session-reports/r.md": "local\n", ".video_agent/state.json": "{}\n"}, force=True)
        result, text = _quiet(build_release.build_archive, repo.root, self.tmp / "out" / "a.zip")
        self.assertEqual(result.exit_code, 1, text)
        self.assertIn("build=failed", text)
        self.assertRegex(text, r"(?m)^error=excluded_member:class-\d+:session-reports/r\.md$")
        self.assertRegex(text, r"(?m)^error=excluded_member:class-\d+:\.video_agent/state\.json$")


class TestRl2SecretScanReadsUtf16(TmpCase):
    def ps1(self, token: str) -> str:
        return "$env:GITHUB_TOKEN = '" + token + "'\r\nWrite-Output 'deploy'\r\n"

    def test_rl2_utf16_and_utf32_text_is_decoded_for_the_scan(self):
        text = self.ps1("placeholder")
        for label, data in (
            ("utf-16-le bom", b"\xff\xfe" + text.encode("utf-16-le")),
            ("utf-16-be bom", b"\xfe\xff" + text.encode("utf-16-be")),
            ("utf-16-le no bom", text.encode("utf-16-le")),
            ("utf-16-be no bom", text.encode("utf-16-be")),
            ("utf-32-le bom", b"\xff\xfe\x00\x00" + text.encode("utf-32-le")),
            ("utf-32-be bom", b"\x00\x00\xfe\xff" + text.encode("utf-32-be")),
        ):
            with self.subTest(encoding=label):
                texts = build_release._member_texts(data)
                self.assertEqual(texts[0], text)
                self.assertEqual(texts[1:], [data.decode("utf-8", "replace")])  # R2-RL-1: UTF-8 too
        # UTF-8 text decodes exactly as before, BOM included, so reviewed-finding line hashes stay put.
        self.assertEqual(build_release._member_texts(b"\xef\xbb\xbf" + text.encode("utf-8")), ["\ufeff" + text])
        self.assertEqual(build_release._member_texts(text.encode("utf-8")), [text])

    def test_rl2_binary_members_stay_binary(self):
        png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(range(256)) * 4
        self.assertEqual(build_release._member_texts(png), [])

    @unittest.skipUnless(HAS_GIT and HAS_NODE, "git or node not available")
    def test_rl2_verify_reports_a_token_in_a_utf16_member(self):
        repo = ScratchGit(self.tmp / "repo")
        text = self.ps1(_token())
        repo.commit({
            "LICENSE": "MIT\n",
            "scripts/deploy-utf16.ps1": b"\xff\xfe" + text.encode("utf-16-le"),
            "scripts/deploy-utf16be.ps1": text.encode("utf-16-be"),
        })
        out = self.tmp / "out" / "a.zip"
        built, build_text = _quiet(build_release.build_archive, repo.root, out)
        self.assertEqual(built.exit_code, 0, build_text)
        report, text_out = _quiet(build_release.verify_archive, out, repo.root)
        self.assertEqual(report.exit_code, 1, text_out)
        self.assertIn("verify=failed", text_out)
        for name in ("scripts/deploy-utf16.ps1", "scripts/deploy-utf16be.ps1"):
            with self.subTest(member=name):
                self.assertRegex(text_out, r"(?m)^secret_finding=" + re.escape(name) + r":1:")
        self.assertIn("binary_members_skipped=0", text_out)


@unittest.skipUnless(HAS_GIT, "git not available")
class TestRl7SkillsOnlyKeepsTheRoleFolder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True, encoding="utf-8").strip()
        cls.members = build_release._select_skills_only(build_release._commit_members(commit, cwd=REPO))

    def test_rl7_role_folder_references_point_at_the_shipped_role_files(self):
        roles = build_release.PUBLIC_REFERENCE_ROOT + "/roles/"
        pipeline = self.members["skills/agentic-sdlc-pipeline/SKILL.md"][1].decode("utf-8")
        self.assertIn("<runtime-root>/" + roles, pipeline)
        for path, (_mode, data) in sorted(self.members.items()):
            if not path.endswith(".md"):
                continue
            text = data.decode("utf-8")
            with self.subTest(path=path):
                rewritten = re.search(r".{0,40}(?<![\w./-])agents/? \(source checkout only\).{0,20}", text)
                self.assertIsNone(rewritten, rewritten and rewritten.group(0))
                self.assertFalse("<runtime-root>/agents/" in text, path)


# ---------------------------------------------------------------- RL-4 CI workflow

CI = REPO / ".github" / "workflows" / "ci.yml"
_TERM = re.compile(r"^startsWith\((github\.(?:ref|head_ref)), '([^']*)'\)$")
_STEP_TERM = re.compile(r"^(steps\.[A-Za-z0-9_-]+\.outputs\.[A-Za-z0-9_-]+) == '([^']*)'$")
VERSION_CHANGED = "steps.version_change.outputs.changed"


def _parse_steps(text: str, job: str) -> list:
    """{name, id, if, run} for each step of one job; a stdlib-only line parse."""
    lines = text.splitlines()
    start = lines.index("  %s:" % job)
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^  [A-Za-z0-9_-]+:$", lines[i])), len(lines))
    steps, current, in_run = [], None, False
    for line in lines[start:end]:
        if line.startswith("      - "):
            current = {"name": None, "id": None, "if": None, "run": []}
            steps.append(current)
            line = "        " + line[len("      - "):]
        if current is None or not line.startswith("        "):
            continue
        body = line.strip()
        if not line.startswith("         "):
            key, _, value = body.partition(":")
            in_run = key == "run" and value.strip() == "|"
            if key in ("name", "id"):
                current[key] = value.strip().strip('"')
            elif key == "if":
                current["if"] = value.strip()
            elif key == "run" and not in_run:
                current["run"].append(value.strip())
        elif in_run:
            current["run"].append(line[10:] if line.startswith("          ") else body)
    for step in steps:
        step["run"] = "\n".join(step["run"])
    return steps


def _workflow_steps(text: str, job: str) -> list:
    """(name, if-condition or None, run text) for each step of one job."""
    return [(step["name"], step["if"], step["run"]) for step in _parse_steps(text, job)]


def _condition_holds(condition, context: dict) -> bool:
    """Evaluate a step `if:` of `startsWith(github.ref|github.head_ref, '...')` and
    `steps.<id>.outputs.<name> == '...'` terms joined by ||."""
    if condition is None:
        return True
    expression = condition
    if expression.startswith("${{") and expression.endswith("}}"):
        expression = expression[3:-2]
    result = False
    for term in expression.split("||"):
        match = _TERM.match(term.strip())
        step = _STEP_TERM.match(term.strip())
        if match:
            result = result or context.get(match.group(1), "").startswith(match.group(2))
        elif step:
            result = result or context.get(step.group(1), "") == step.group(2)
        else:
            raise AssertionError("unsupported if: term %r in %r" % (term, condition))
    return result


def _ctx(ref, head_ref="", changed="false"):
    return {"github.ref": ref, "github.head_ref": head_ref, VERSION_CHANGED: changed}


CI_CONTEXTS = {
    "feature pull request": (_ctx("refs/pull/40/merge", "feat/new-thing"), False),
    "lesson branch named release-check": (_ctx("refs/pull/30/merge", "docs/lesson-release-check"), False),
    "push to main": (_ctx("refs/heads/main"), False),
    "release pull request": (_ctx("refs/pull/26/merge", "chore/release-0.7.0"), True),
    "manual run on a release branch": (_ctx("refs/heads/chore/release-0.8.0"), True),
    "manual run on a tag": (_ctx("refs/tags/v0.8.0"), True),
    # R2-RL-4: a VERSION change is a release whatever the branch is called.
    "pull request that changes VERSION": (_ctx("refs/pull/41/merge", "feat/bump", changed="true"), True),
    "push to main that changes VERSION": (_ctx("refs/heads/main", changed="true"), True),
}


class TestRl4ReleaseCheckRunsOnlyForReleases(unittest.TestCase):
    def setUp(self):
        self.steps = _workflow_steps(CI.read_text(encoding="utf-8"), "deterministic-gate")

    def test_rl4_release_check_runs_only_for_release_branches_and_tags(self):
        release = [(name, cond) for name, cond, run in self.steps if "bump_version.py --release-check" in run]
        self.assertTrue(release, "the release check must stay in the workflow for release runs")
        for label, (context, expected) in CI_CONTEXTS.items():
            for name, cond in release:
                with self.subTest(context=label, step=name):
                    self.assertEqual(_condition_holds(cond, context), expected, cond)

    def test_rl4_every_pull_request_runs_the_version_check(self):
        checks = [(name, cond) for name, cond, run in self.steps
                  if re.search(r"bump_version\.py --check\b", run)]
        source = [item for item in checks if not (item[0] or "").startswith("Archive")]
        self.assertTrue(source, "the source steps must run bump_version.py --check")
        for name, cond in source:
            for label, (context, _expected) in CI_CONTEXTS.items():
                with self.subTest(context=label, step=name):
                    self.assertTrue(_condition_holds(cond, context))

    def test_rl4_the_condition_parser_sees_an_unconditioned_step(self):
        # Negative control: the f430715 form had no condition, so it ran on every pull request.
        self.assertTrue(_condition_holds(None, CI_CONTEXTS["feature pull request"][0]))
        with self.assertRaises(AssertionError):
            _condition_holds("${{ github.event_name == 'push' }}", {})


# ---------------------------------------------------------------- RL-8 / RL-9 version tooling

README = "# agentic-sdlc\n\n> `Version 0.4.3` - `MIT`\n\n## Versioning\n\nCurrent version: `0.4.3`.\n"
PLUGIN_README = "# Plugin reference\n\n> Version: `0.4.3`. Reference.\n"
RELEASE_READINESS = ("# Release Readiness\n\nThis file is the publish gate for `agentic-sdlc` version `0.4.3`. "
                     "Gate.\n\n```text\nversion=0.4.3\n```\n")
SECURITY = ("# Security Policy\n\n## Supported versions\n\nSecurity fixes are provided for the latest `0.4.x` "
            "release. Older releases are unsupported.\n")


class VersionTreeCase(TmpCase):
    def tree(self, security=SECURITY, manifests=None):
        base = {
            ".claude-plugin/plugin.json": {"name": "agentic-sdlc", "version": "0.4.3"},
            ".claude-plugin/marketplace.json": {"plugins": [{"name": "agentic-sdlc", "version": "0.4.3"}]},
            ".codex-plugin/plugin.json": {"name": "agentic-sdlc", "version": "0.4.3"},
        }
        base.update(manifests or {})
        files = {rel: json.dumps(data) + "\n" for rel, data in base.items()}
        files.update({
            "VERSION": "0.4.3\n", "README.md": README, "docs/plugin-readme.md": PLUGIN_README,
            "docs/release-readiness.md": RELEASE_READINESS, "SECURITY.md": security,
            "CHANGELOG.md": "# Changelog\n\n## Unreleased\n\n## 0.4.3 - 2026-09-14\n\n- Notes.\n",
        })
        root = self.tmp / "tree"
        _write(root, files)
        return root

    def check(self, root):
        return _quiet(bump_version.check, root=root)


class TestRl8SecurityPolicyLineIsVersioned(VersionTreeCase):
    def test_rl8_check_fails_on_a_stale_supported_minor_line(self):
        root = self.tree(security=SECURITY.replace("`0.4.x`", "`0.3.x`"))
        code, out = self.check(root)
        self.assertEqual(code, 1, out)
        self.assertIn("version_mismatch=SECURITY.md:supported-minor-line:0.3", out)

    def test_rl8_check_fails_when_the_supported_line_is_missing(self):
        code, out = self.check(self.tree(security="# Security Policy\n\nNo supported-version line.\n"))
        self.assertEqual(code, 1, out)
        self.assertIn("version_missing=SECURITY.md:supported-minor-line", out)

    def test_rl8_bump_rewrites_the_supported_minor_line(self):
        root = self.tree()
        code, out = _quiet(bump_version.bump, "0.5.0", root=root)
        self.assertEqual(code, 0, out)
        self.assertIn("latest `0.5.x` release", (root / "SECURITY.md").read_text(encoding="utf-8"))
        self.assertEqual(self.check(root)[0], 0)

    def test_rl8_repository_security_policy_names_the_current_minor_line(self):
        version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
        minor = ".".join(version.split(".")[:2])
        values = bump_version.version_declarations(REPO)[("SECURITY.md", "supported-minor-line")]
        self.assertEqual(values, [minor])


class TestRl9OnlyThisPluginsCatalogEntriesCount(VersionTreeCase):
    def test_rl9_check_reads_every_agentic_sdlc_entry(self):
        catalog = {"plugins": [{"name": "agentic-sdlc", "version": "0.4.3"},
                               {"name": "agentic-sdlc", "version": "0.4.2"}]}
        code, out = self.check(self.tree(manifests={".claude-plugin/marketplace.json": catalog}))
        self.assertEqual(code, 1, out)
        self.assertIn("version_mismatch=.claude-plugin/marketplace.json:version:", out)

    def test_rl9_check_ignores_entries_of_other_plugins(self):
        catalog = {"plugins": [{"name": "other-plugin", "version": "9.9.9"},
                               {"name": "agentic-sdlc", "version": "0.4.3"}]}
        code, out = self.check(self.tree(manifests={".claude-plugin/marketplace.json": catalog}))
        self.assertEqual(code, 0, out)
        self.assertIn(".claude-plugin/marketplace.json=0.4.3", out)

    def test_rl9_bump_leaves_other_plugins_alone(self):
        catalog = {"plugins": [{"name": "other-plugin", "version": "9.9.9"},
                               {"name": "agentic-sdlc", "version": "0.4.3"}]}
        root = self.tree(manifests={".claude-plugin/marketplace.json": catalog})
        code, out = _quiet(bump_version.bump, "0.5.0", root=root)
        self.assertEqual(code, 0, out)
        written = json.loads((root / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual([(e["name"], e["version"]) for e in written["plugins"]],
                         [("other-plugin", "9.9.9"), ("agentic-sdlc", "0.5.0")])

    def cursor_errors(self, plugins):
        root = self.tmp / "cursor"
        _write(root, {
            ".cursor-plugin/plugin.json": json.dumps({"name": "agentic-sdlc", "version": "0.4.3"}),
            ".cursor-plugin/marketplace.json": json.dumps({"plugins": plugins}),
            "VERSION": "0.4.3\n",
        })
        return [e for e in check_cursor_plugin.validate(root) if e.startswith("cursor_marketplace")]

    def test_rl9_cursor_checker_finds_this_plugin_after_another_entry(self):
        self.assertEqual(self.cursor_errors([{"name": "other", "source": "./other", "version": "1.0.0"},
                                             {"name": "agentic-sdlc", "source": ".", "version": "0.4.3"}]), [])

    def test_rl9_cursor_checker_reads_every_entry_of_this_plugin(self):
        errors = self.cursor_errors([{"name": "agentic-sdlc", "source": ".", "version": "0.4.3"},
                                     {"name": "agentic-sdlc", "source": ".", "version": "0.4.2"}])
        self.assertEqual(errors, ["cursor_marketplace_version_mismatch"])


# ---------------------------------------------------------------- audit note: hook-trust default id

class TestTrustCheckDefaultPluginId(unittest.TestCase):
    def test_rl_note_trust_check_defaults_to_the_documented_install_id(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        codex = readme.split("\n### Codex\n", 1)[1].split("\n## ", 1)[0]
        documented = re.search(r"codex plugin add (agentic-sdlc@[\w.-]+)", codex).group(1)
        self.assertEqual(check_codex_hook_trust.DEFAULT_PLUGIN, documented)



# ---------------------------------------------------------------- round 2 (security review of the fixes)

class TestR2Rl1ByteOrderMarkNeverHidesUtf8(TmpCase):
    """R2-RL-1: a UTF-16 mark in front of NUL-free UTF-8 must not turn a secret into mojibake."""

    def members(self):
        line = "token = '" + _token() + "'\n"
        return {
            "LICENSE": "MIT\n",
            # NUL-free UTF-8 after a UTF-16LE / UTF-16BE mark: base read these as UTF-8.
            "scripts/le-mark.ps1": b"\xff\xfe" + line.encode("utf-8"),
            "scripts/be-mark.ps1": b"\xfe\xff" + line.encode("utf-8"),
            # The same with one NUL further on, which also makes the mark look trustworthy.
            "scripts/le-mark-nul.ps1": b"\xff\xfe" + line.encode("utf-8") + b"pad\x00pad\n",
        }

    def test_r2_rl1_every_decoding_of_a_marked_member_includes_utf8(self):
        for name, data in self.members().items():
            if isinstance(data, bytes):
                with self.subTest(member=name):
                    self.assertIn(data.decode("utf-8", "replace"), build_release._member_texts(data))

    @unittest.skipUnless(HAS_GIT and HAS_NODE, "git or node not available")
    def test_r2_rl1_verify_reports_a_utf8_token_behind_a_utf16_mark(self):
        repo = ScratchGit(self.tmp / "repo")
        repo.commit(self.members())
        out = self.tmp / "out" / "a.zip"
        built, build_text = _quiet(build_release.build_archive, repo.root, out)
        self.assertEqual(built.exit_code, 0, build_text)
        report, text = _quiet(build_release.verify_archive, out, repo.root)
        self.assertEqual(report.exit_code, 1, text)
        for name in ("scripts/le-mark.ps1", "scripts/be-mark.ps1", "scripts/le-mark-nul.ps1"):
            with self.subTest(member=name):
                self.assertRegex(text, r"(?m)^secret_finding=" + re.escape(name) + r":1:")

    @unittest.skipUnless(HAS_GIT and HAS_NODE, "git or node not available")
    def test_r2_rl1_history_scan_reports_a_utf8_token_behind_a_utf16_mark(self):
        repo = ScratchGit(self.tmp / "repo")
        repo.commit(self.members())
        mirror = self.tmp / "mirror.git"
        repo.git("clone", "--mirror", "-q", str(repo.root), str(mirror))
        report, text = _quiet(build_release.scan_history, mirror)
        self.assertEqual(report.exit_code, 1, text)
        for name in ("scripts/le-mark.ps1", "scripts/be-mark.ps1", "scripts/le-mark-nul.ps1"):
            with self.subTest(member=name):
                self.assertRegex(text, r"(?m)^secret_finding=path=" + re.escape(name) + r" ")


@unittest.skipIf(os.name == "nt", "symlink creation needs a privilege on Windows")
class TestR2Rl2InstallerNeverFollowsALink(TmpCase):
    def test_r2_rl2_update_refuses_a_managed_path_replaced_by_a_symlink(self):
        pkg = self.tmp / "pkg"
        _write(pkg, {".cursor-plugin/plugin.json": "{}\n", "a.txt": "a1\n"})
        dest = self.tmp / "dest"
        self.assertEqual(install_cursor_plugin.install(pkg, dest)[0], 0)
        victim = self.tmp / "outside" / "victim.txt"
        _write(victim.parent, {"victim.txt": "keep\n"})
        (dest / "a.txt").unlink()
        (dest / "a.txt").symlink_to(victim)
        _write(pkg, {"a.txt": "a2\n"})
        code, lines = install_cursor_plugin.install(pkg, dest)
        self.assertEqual(code, 1, lines)
        self.assertIn("error=cursor_dest_file_unmanaged:a.txt", lines)
        self.assertEqual(victim.read_text(encoding="utf-8"), "keep\n")

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW") and os.unlink in os.supports_dir_fd,
                         "no-follow unlink needs dir_fd support")
    def test_r2_rl2_uninstall_does_not_follow_a_folder_swapped_after_the_check(self):
        outside = self.tmp / "outside"
        _write(outside, {"victim.txt": "keep\n"})
        dest = self.tmp / "dest"
        _write(dest, {"own/file.txt": "x\n", install_cursor_plugin.RECEIPT: json.dumps(
            {"name": "agentic-sdlc", "managed": ["own/file.txt", "link/victim.txt"]})})
        (dest / "link").symlink_to(outside, target_is_directory=True)
        # The containment check passes, as it would just before the folder is swapped for a link.
        with mock.patch.object(install_cursor_plugin, "_inside", return_value=True):
            code, _lines = install_cursor_plugin.uninstall(dest)
        self.assertEqual(code, 0)
        self.assertEqual((outside / "victim.txt").read_text(encoding="utf-8"), "keep\n")
        self.assertFalse((dest / "own" / "file.txt").exists())
        self.assertFalse((dest / "own").exists())


class TestR2Rl3UnreadableCheckoutFailsClosed(TmpCase):
    def broken_checkout(self):
        repo = ScratchGit(self.tmp / "pkg")
        repo.commit({".cursor-plugin/plugin.json": "{}\n", "README.md": "readme\n"})
        _write(repo.root, {"CLAUDE.local.md": "local notes\n", "untracked-notes.txt": "scratch\n"})
        # A real repository that git refuses to read (here a damaged HEAD; in the field, for
        # example, a checkout another user owns, which git reports as dubious ownership).
        (repo.root / ".git" / "HEAD").write_text("not a ref\n", encoding="utf-8")
        return repo.root

    @unittest.skipUnless(HAS_GIT, "git not available")
    def test_r2_rl3_package_files_fail_closed_when_git_cannot_list_a_checkout(self):
        with self.assertRaises(build_release.ReleaseError):
            build_release.local_package_files(self.broken_checkout())

    @unittest.skipUnless(HAS_GIT, "git not available")
    def test_r2_rl3_installer_refuses_a_checkout_git_cannot_list(self):
        dest = self.tmp / "dest"
        code, lines = install_cursor_plugin.install(self.broken_checkout(), dest)
        self.assertEqual(code, 1, lines)
        self.assertTrue(any(line.startswith("error=cursor_package_unreadable") for line in lines), lines)
        self.assertFalse(dest.exists())

    @unittest.skipUnless(HAS_GIT, "git not available")
    def test_r2_rl3_lifecycle_copy_refuses_a_checkout_git_cannot_list(self):
        with self.assertRaises(check_native_lifecycle.Failed):
            check_native_lifecycle.copy_package(self.broken_checkout(), self.tmp / "copy")
        self.assertFalse((self.tmp / "copy").exists())

    def test_r2_rl3_a_folder_that_is_no_repository_is_still_walked(self):
        # Control: an extracted package with a stray `.git/HEAD` is not a checkout git could list.
        pkg = self.tmp / "extracted"
        _write(pkg, {".git/HEAD": "ref: refs/heads/main\n", "README.md": "x\n", "CLAUDE.local.md": "x\n"})
        self.assertEqual(build_release.local_package_files(pkg), ["README.md"])

    def test_r2_rl3_claude_local_md_is_a_private_file(self):
        for path in ("CLAUDE.local.md", "skills/x/claude.local.md", "Claude.Local.md"):
            with self.subTest(path=path):
                self.assertEqual(build_release.exclusion_class(path, "100644"), 3)


@unittest.skipIf(os.name == "nt" or not HAS_GIT or shutil.which("bash") is None,
                 "runs the workflow's bash step against a scratch git repository")
class TestR2Rl4VersionChangeIsDetected(TmpCase):
    def detect(self, repo, event, before=""):
        steps = _parse_steps(CI.read_text(encoding="utf-8"), "deterministic-gate")
        step = next((s for s in steps if s["id"] == "version_change"), None)
        self.assertIsNotNone(step, "no step with id version_change")
        names = [s["name"] for s in steps]
        self.assertLess(names.index(step["name"]), names.index("Release consistency"))
        output = self.tmp / "github_output"
        output.write_text("", encoding="utf-8")
        env = dict(repo.env, EVENT_NAME=event, BEFORE=before, GITHUB_OUTPUT=str(output))
        proc = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
                              cwd=repo.root, env=env, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        values = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines() if "=" in line)
        return values.get("changed")

    def merged_pull_request(self, files):
        repo = ScratchGit(self.tmp / ("repo-%d" % len(list(self.tmp.iterdir()))))
        repo.commit({"VERSION": "0.7.0\n", "README.md": "r\n"})
        repo.git("switch", "-q", "-c", "feature")
        repo.commit(files)
        repo.git("switch", "-q", "main")
        repo.commit({"NOTES.md": "main moved on\n"})
        repo.git("merge", "-q", "--no-ff", "-m", "merge", "feature")
        return repo

    def test_r2_rl4_pull_request_changing_version_is_detected(self):
        self.assertEqual(self.detect(self.merged_pull_request({"VERSION": "0.8.0\n"}), "pull_request"), "true")
        self.assertEqual(self.detect(self.merged_pull_request({"README.md": "r2\n"}), "pull_request"), "false")

    def test_r2_rl4_push_changing_version_is_detected(self):
        repo = ScratchGit(self.tmp / "push")
        repo.commit({"VERSION": "0.7.0\n", "README.md": "r\n"})
        before = repo.git("rev-parse", "HEAD").strip()
        repo.commit({"README.md": "r2\n"})
        self.assertEqual(self.detect(repo, "push", before), "false")
        repo.commit({"VERSION": "0.8.0\n"})
        self.assertEqual(self.detect(repo, "push", before), "true")
        # A base the clone does not hold (a force push) fails closed: the release check runs.
        self.assertEqual(self.detect(repo, "push", "1" * 40), "true")
        self.assertEqual(self.detect(repo, "workflow_dispatch"), "false")


if __name__ == "__main__":
    unittest.main()
