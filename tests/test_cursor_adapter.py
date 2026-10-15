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


if __name__ == "__main__":
    unittest.main()
