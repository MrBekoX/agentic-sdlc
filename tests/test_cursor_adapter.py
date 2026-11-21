"""Cursor package structure, portable install, and relocated hook replay.

These checks do not start the Cursor IDE. A passing hook replay is not a
Customize load or a model turn.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import check_cursor_plugin
import check_plugin_portability
import install_cursor_plugin
import project_roles


def _run(command, payload, env, cwd):
    if os.name == "nt":
        shell = os.environ.get("COMSPEC") or shutil.which("cmd.exe")
        argv = f'"{shell}" /d /s /c "{command}"'
    else:
        argv = ["/bin/sh", "-c", command]
    return subprocess.run(
        argv,
        input=json.dumps(payload),
        text=True,
        encoding="utf-8",
        capture_output=True,
        env=env,
        cwd=cwd,
        timeout=25,
    )


class CursorPackageTests(unittest.TestCase):
    def test_manifest_and_components_validate(self):
        self.assertEqual(check_cursor_plugin.validate(REPO), [])
        self.assertFalse((REPO / "hooks" / "hooks.json").exists())
        self.assertFalse((REPO / "plugin.json").exists())

    def test_hook_commands_keep_the_install_path_out_of_shell_code(self):
        wire = json.loads((REPO / "hooks" / "hooks-cursor.json").read_text(encoding="utf-8"))
        flat = json.dumps(wire)
        self.assertNotIn("${CURSOR_PLUGIN_ROOT}", flat)
        self.assertNotIn("CLAUDE_PLUGIN_ROOT", flat)
        self.assertNotRegex(flat, r"[A-Za-z]:[\\/]|/home/|/Users/")
        for event, entries in wire["hooks"].items():
            for entry in entries:
                self.assertIn("process.env.CURSOR_PLUGIN_ROOT", entry["command"])
                self.assertIn("pathToFileURL", entry["command"])
                self.assertIn("cursor-launch.mjs", entry["command"])
                self.assertTrue(entry["command"].startswith("node -e "), event)

    def test_portability_closure_includes_the_cursor_wire(self):
        errors = check_plugin_portability.portability_errors(check_plugin_portability.runtime_members(REPO))
        self.assertEqual(errors, [])

    def test_missing_tools_name_the_missing_command(self):
        with mock.patch.object(install_cursor_plugin, "_which", return_value=None):
            errors = install_cursor_plugin.dependency_errors()
        self.assertTrue(any(item.startswith("error=node_missing:") for item in errors))
        self.assertTrue(any(item.startswith("error=python_missing:") for item in errors))
        self.assertTrue(any(item.startswith("error=git_missing:") for item in errors))

    def test_uninstall_without_a_receipt_deletes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "not-installed"
            dest.mkdir()
            (dest / "settings.json").write_text("{}", encoding="utf-8")
            code, _lines = install_cursor_plugin.uninstall(dest)
            self.assertEqual(code, 1)
            self.assertEqual((dest / "settings.json").read_text(encoding="utf-8"), "{}")


@unittest.skipUnless(shutil.which("node") and shutil.which("git"), "node or git not available")
class CursorInstallAndHookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.dest = base / "ev klasörü" / "Türkçe eklenti"
        self.project = base / "unrelated target"
        self.project.mkdir()
        self.sibling = self.dest.parent / "other-plugin"
        self.sibling.mkdir(parents=True)
        (self.sibling / "settings.json").write_text('{"keep": true}\n', encoding="utf-8")

    def test_install_update_and_uninstall_keep_user_files(self):
        first, _lines = install_cursor_plugin.install(REPO, self.dest)
        self.assertEqual(first, 0)
        self.assertEqual(check_cursor_plugin.validate(self.dest), [])
        (self.dest / "user-keep.txt").write_text("keep-me", encoding="utf-8")
        skill = self.dest / "skills" / "using-agentic-sdlc" / "SKILL.md"
        skill.write_text(skill.read_text(encoding="utf-8") + "\nUSER EDIT\n", encoding="utf-8")
        updated, _lines = install_cursor_plugin.install(REPO, self.dest)
        self.assertEqual(updated, 0)
        self.assertNotIn("USER EDIT", skill.read_text(encoding="utf-8"))
        self.assertEqual((self.dest / "user-keep.txt").read_text(encoding="utf-8"), "keep-me")
        self.assertEqual(json.loads((self.sibling / "settings.json").read_text(encoding="utf-8")), {"keep": True})
        self.assertFalse((self.dest / "hooks" / "hooks.json").exists())
        removed, _lines = install_cursor_plugin.uninstall(self.dest)
        self.assertEqual(removed, 0)
        self.assertFalse(skill.exists())
        self.assertEqual((self.dest / "user-keep.txt").read_text(encoding="utf-8"), "keep-me")
        self.assertTrue((self.sibling / "settings.json").is_file())

    def test_relocated_hooks_resolve_a_non_ascii_install_path(self):
        installed, _lines = install_cursor_plugin.install(REPO, self.dest)
        self.assertEqual(installed, 0)
        wire = json.loads((self.dest / "hooks" / "hooks-cursor.json").read_text(encoding="utf-8"))
        env = {key: value for key, value in os.environ.items() if not key.startswith("AGENTIC_")}
        env["CURSOR_PLUGIN_ROOT"] = str(self.dest)
        env["CURSOR_PROJECT_DIR"] = str(self.project)
        shell = next(item["command"] for item in wire["hooks"]["beforeShellExecution"]
                     if "destructive-command-guard.mjs" in item["command"])
        denied = _run(shell, {"command": "rm -rf /tmp/example", "cwd": str(self.project)}, env, self.project)
        self.assertEqual(denied.returncode, 0, denied.stderr)
        self.assertEqual(json.loads(denied.stdout)["permission"], "deny")
        allowed = _run(shell, {"command": "git status", "cwd": str(self.project)}, env, self.project)
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertEqual(json.loads(allowed.stdout)["permission"], "allow")
        unset = env.copy()
        unset.pop("CURSOR_PLUGIN_ROOT", None)
        missing = _run(shell, {"command": "git status"}, unset, self.project)
        self.assertEqual(missing.returncode, 1)
        self.assertIn("error=cursor_plugin_root_unset", missing.stderr)
        session = next(item["command"] for item in wire["hooks"]["sessionStart"])
        started = _run(session, {}, env, Path(tempfile.gettempdir()))
        self.assertEqual(started.returncode, 0, started.stderr)
        context = json.loads(started.stdout)["additional_context"]
        self.assertIn(str(self.dest), context)
        self.assertIn("using-agentic-sdlc", context)
        self.assertIn("agentic-sdlc-pipeline", context)
        write = next(item["command"] for item in wire["hooks"]["preToolUse"] if "scan-write.mjs" in item["command"])
        secret = "ghp_" + "a1B2" * 9
        scanned = _run(write, {
            "tool_name": "Write",
            "cwd": str(self.project),
            "tool_input": {"path": "src/app.py", "contents": f'token = "{secret}"\n'},
        }, env, self.project)
        self.assertEqual(scanned.returncode, 0, scanned.stderr)
        self.assertEqual(json.loads(scanned.stdout)["permission"], "deny")
        self.assertNotIn(secret, scanned.stdout)


class CursorRoleFileTests(unittest.TestCase):
    """Cursor reads plugin roles from cursor/agents/: the shared role bodies with Cursor frontmatter
    (plan Task 14). Read-only roles carry `readonly: true` (the documented key for .cursor/agents)
    and `permissionMode: readonly` (the key Cursor's plugin loader reads, per its 2026-10-16 forum
    reply); a role with a writing or shell tool carries neither."""

    WRITING = {"Write", "Edit", "Bash", "PowerShell", "NotebookEdit"}

    @staticmethod
    def _split(path):
        text = path.read_text(encoding="utf-8")
        head, body = text[4:].split("\n---\n", 1)
        fields = {}
        for line in head.splitlines():
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
        return fields, body

    def test_the_manifest_points_at_the_cursor_role_files(self):
        manifest = json.loads((REPO / ".cursor-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["agents"], "./cursor/agents/")

    def test_every_shared_role_has_a_cursor_mirror_and_no_other(self):
        shared = sorted(p.name for p in (REPO / "agents").glob("*.md"))
        mirrors = sorted(p.name for p in (REPO / "cursor" / "agents").glob("*.md"))
        self.assertEqual(mirrors, shared)

    def test_each_mirror_keeps_the_body_name_and_description(self):
        for source in sorted((REPO / "agents").glob("*.md")):
            with self.subTest(role=source.stem):
                fields, body = self._split(source)
                cursor_fields, cursor_body = self._split(REPO / "cursor" / "agents" / source.name)
                self.assertEqual(cursor_body, body)
                self.assertEqual((cursor_fields["name"], cursor_fields["description"]),
                                 (fields["name"], fields["description"]))
                self.assertEqual(cursor_fields["model"], "inherit")
                tools = {t.strip() for t in fields.get("tools", "").split(",") if t.strip()}
                expected = {"name", "description", "model"}
                if not tools & self.WRITING:
                    expected |= {"readonly", "permissionMode"}
                    self.assertEqual((cursor_fields["readonly"], cursor_fields["permissionMode"]),
                                     ("true", "readonly"))
                self.assertEqual(set(cursor_fields), expected)

    def test_the_loop_roles_are_read_only_and_the_scribe_is_not(self):
        for role, read_only in (("spec-plan-author", True), ("spec-plan-critic", True), ("draft-scribe", False)):
            with self.subTest(role=role):
                fields, _body = self._split(REPO / "cursor" / "agents" / (role + ".md"))
                self.assertEqual(fields.get("readonly") == "true", read_only)

    def test_the_cursor_checker_accepts_the_mirrors(self):
        self.assertEqual([e for e in check_cursor_plugin.validate(REPO) if "agent" in e], [])

    def test_the_committed_mirror_equals_the_generated_projection(self):
        # AC11 drift gate: cursor/agents/ is generated from agents/*.md by scripts/project_roles.py.
        # Regenerate with `python3 scripts/project_roles.py --target cursor --write`.
        self.assertEqual(project_roles.check_mirror(REPO, "cursor"), [])


class CursorLauncherFailClosedTests(unittest.TestCase):
    """Plan Task 20: for `beforeShellExecution` the launcher denies when the command guard crashes or
    answers with output it cannot read; empty output stays an allow, and the other events keep
    failing open. The launcher only starts handlers that sit next to it, so each case copies it into
    a temp folder beside a stand-in handler with an allowed name."""

    HANDLER = "destructive-command-guard.mjs"

    def setUp(self):
        if shutil.which("node") is None:
            self.skipTest("node not available")
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        shutil.copyfile(REPO / "hooks" / "cursor-launch.mjs", self.tmp / "cursor-launch.mjs")

    def launch(self, event, handler_source, payload=None):
        (self.tmp / self.HANDLER).write_text(handler_source, encoding="utf-8")
        proc = subprocess.run([shutil.which("node"), str(self.tmp / "cursor-launch.mjs"), "--event", event,
                               "--handler", self.HANDLER],
                              input=json.dumps(payload or {"command": "git status", "cwd": str(self.tmp)}),
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout), proc.stderr

    def test_a_crashed_or_unreadable_guard_denies_the_shell_command(self):
        for name, source, error in (("crash", "process.exit(3);\n", "cursor_handler_failed"),
                                    ("throw", "throw new Error('boom');\n", "cursor_handler_failed"),
                                    ("invalid", "process.stdout.write('not json');\n", "cursor_handler_output_invalid")):
            with self.subTest(handler=name):
                out, stderr = self.launch("beforeShellExecution", source)
                self.assertEqual(out["permission"], "deny", out)
                self.assertIn(error, out["agent_message"])
                self.assertIn("error=" + error, stderr)

    def test_an_answer_that_is_not_an_object_denies_the_shell_command(self):
        for value in ("null", "42", "[]", '"allow"'):
            with self.subTest(answer=value):
                out, stderr = self.launch("beforeShellExecution", "process.stdout.write(%r);\n" % value)
                self.assertEqual(out["permission"], "deny", out)
                self.assertIn("error=cursor_handler_output_invalid", stderr)

    def test_a_missing_project_folder_does_not_lock_the_shell(self):
        # A deleted folder (or a stale workspace root) used to make the spawn itself fail, which now
        # denies: the launcher runs the guard from its own folder instead, so `cd ..` still works.
        gone = self.tmp / "deleted-project"
        launcher = REPO / "hooks" / "cursor-launch.mjs"
        for payload, expected in (({"command": "cd ..", "cwd": str(gone)}, "allow"),
                                  ({"command": "rd /s /q build", "cwd": str(gone)}, "deny"),
                                  ({"command": "git status", "workspace_roots": [str(gone)]}, "allow")):
            with self.subTest(payload=payload):
                proc = subprocess.run([shutil.which("node"), str(launcher), "--event", "beforeShellExecution",
                                       "--handler", self.HANDLER], input=json.dumps(payload),
                                      capture_output=True, text=True, encoding="utf-8", timeout=30,
                                      env={k: v for k, v in os.environ.items() if k != "CURSOR_PROJECT_DIR"})
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(json.loads(proc.stdout)["permission"], expected, proc.stdout + proc.stderr)

    def test_empty_output_allows_and_other_events_stay_open(self):
        out, _ = self.launch("beforeShellExecution", "")
        self.assertEqual(out, {"permission": "allow"})
        for source in ("process.exit(3);\n", "process.stdout.write('not json');\n"):
            with self.subTest(source=source):
                out, _ = self.launch("preToolUse", source, {"tool_name": "Write", "cwd": str(self.tmp),
                                                             "tool_input": {"path": "a.txt", "contents": "x"}})
                self.assertEqual(out, {"permission": "allow"})

    def test_cmd_tree_deletes_are_denied_through_the_launcher(self):
        shutil.copyfile(REPO / "hooks" / "cursor-launch.mjs", self.tmp / "cursor-launch.mjs")
        hooks = REPO / "hooks"
        for command, expected in (("cmd /c rd /s /q build", "deny"), ('cmd /d /s /c "r^d /s /q build"', "deny"),
                                  ("cmd /c echo ok & del /s /q *.log", "deny"), ("dir /s", "allow"),
                                  ("rmdir build", "allow")):
            with self.subTest(command=command):
                proc = subprocess.run([shutil.which("node"), str(hooks / "cursor-launch.mjs"), "--event",
                                       "beforeShellExecution", "--handler", self.HANDLER],
                                      input=json.dumps({"command": command, "cwd": str(self.tmp)}),
                                      capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(json.loads(proc.stdout)["permission"], expected, proc.stdout)


if __name__ == "__main__":
    unittest.main()
