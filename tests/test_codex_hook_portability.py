"""Execute shipped Codex command strings after relocation, independently of session cwd.

These are real shell/handler checks, not proof of Codex's reviewed hook lifecycle.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "hooks" / "hooks-codex.json"
HANDLERS = {
    "scan-commit.mjs", "destructive-command-guard.mjs", "branch-guard.mjs",
    "scan-write-codex.mjs", "flow-order-guard-codex.mjs", "session-start-codex.mjs",
    "completion-claim-guard-codex.mjs", "flow-step-guard-codex.mjs",
}


def handlers():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    return [(event, handler) for event, blocks in config["hooks"].items()
            for block in blocks for handler in block["hooks"]]


def package_dependencies(root):
    """Resolve the named hook closure, including non-module runtime dependencies."""
    pending = [root / "hooks" / name for name in HANDLERS]
    required = {root / "hooks" / "flow-requirements.json",
                root / "scripts" / "validate_artifacts.py"}
    while pending:
        path = pending.pop()
        if path in required:
            continue
        required.add(path)
        if path.is_file():
            for rel in re.findall(r"from\s+['\"](\./[^'\"]+\.mjs)['\"]", path.read_text(encoding="utf-8")):
                pending.append(path.parent / rel[2:])
    return required


class TestCodexPortableWiring(unittest.TestCase):
    def test_all_eight_handlers_read_root_as_data_with_windows_override(self):
        entries = handlers()
        self.assertEqual(len(entries), 8)
        found = set()
        for event, handler in entries:
            with self.subTest(event=event, command=handler["command"]):
                command = handler["command"]
                self.assertIn("process.env.PLUGIN_ROOT", command)
                self.assertIn("pathToFileURL", command)
                self.assertIn("process.argv[1]=", command)
                self.assertNotIn("${PLUGIN_ROOT}", command)
                self.assertEqual(handler["commandWindows"], "node.exe" + command[len("node"):])
                names = set(re.findall(r"[a-z-]+\.mjs", command))
                self.assertEqual(len(names), 1)
                found.update(names)
        self.assertEqual(found, HANDLERS)

    def test_runtime_dependency_closure_exists(self):
        self.assertEqual(sorted(str(p.relative_to(REPO)) for p in package_dependencies(REPO)
                                if not p.is_file()), [])

    def test_missing_handler_import_requirements_or_validator_is_detected(self):
        for missing in ("hooks/session-start-codex.mjs", "hooks/secret-patterns.mjs",
                        "hooks/flow-requirements.json", "scripts/validate_artifacts.py"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                shutil.copytree(REPO / "hooks", root / "hooks")
                (root / "scripts").mkdir()
                shutil.copy2(REPO / "scripts" / "validate_artifacts.py", root / "scripts")
                (root / missing).unlink()
                self.assertIn(root / missing, {p for p in package_dependencies(root) if not p.is_file()})


@unittest.skipUnless(shutil.which("node"), "node not available")
class TestCodexRelocatedCommands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.cwd = self.base / "unrelated project"
        self.cwd.mkdir()
        self.root = self.base / "installed plugin çığ $ ` & # % '"
        shutil.copytree(REPO / "hooks", self.root / "hooks")
        (self.root / "scripts").mkdir()
        shutil.copy2(REPO / "scripts" / "validate_artifacts.py", self.root / "scripts")

    def shells(self):
        if os.name == "nt":
            # Codex's Windows shell depends on its execution environment, not commandWindows.
            shell = os.environ.get("COMSPEC") or shutil.which("cmd.exe")
            self.assertTrue(shell, "Windows command shell missing")
            result = [(shell, ["/d", "/s", "/c"])]
            for name in ("powershell", "pwsh"):
                if executable := shutil.which(name):
                    result.append((executable, ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command"]))
            return result
        return [("/bin/sh", ["-c"])]

    def execute(self, handler, payload, shell, flags, extra_env=None):
        command = handler.get("commandWindows", handler["command"]) if os.name == "nt" else handler["command"]
        # Mirror the runtime's raw interpolation before shell parsing; new commands avoid it.
        command = command.replace("${PLUGIN_ROOT}", str(self.root))
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTIC_")}
        env.update({"PLUGIN_ROOT": str(self.root), **(extra_env or {})})
        argv = [shell, *flags, command]
        if os.name == "nt" and Path(shell).name.lower() == "cmd.exe":
            # Codex uses raw_arg for cmd's command string. Python's list2cmdline instead
            # inserts backslash-escaped quotes, which cmd does not interpret the same way.
            argv = f'"{shell}" /d /s /c "{command}"'
        proc = subprocess.run(argv, input=json.dumps(payload), cwd=self.cwd,
                              env=env, capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, "")
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def test_all_serialized_commands_execute_from_relocated_package(self):
        self.assertTrue(all(p.is_file() for p in package_dependencies(self.root)))
        for shell, flags in self.shells():
            for event, handler in handlers():
                with self.subTest(shell=shell, event=event, command=handler["command"]):
                    payload = {"hook_event_name": event, "cwd": str(self.cwd), "tool_name": "Bash",
                               "tool_input": {"command": "git status"}, "stop_hook_active": True}
                    out = self.execute(handler, payload, shell, flags)
                    if event == "SessionStart":
                        self.assertIn("AGENTIC_SDLC_CODEX_BOOTSTRAP", out["hookSpecificOutput"]["additionalContext"])

    def test_destructive_denial_and_flow_order_entrypoint_survive_relocation(self):
        rollout = self.cwd / "empty.jsonl"
        rollout.write_text("", encoding="utf-8")
        cases = [
            ("destructive-command-guard.mjs", {"tool_name": "Bash", "tool_input": {"command": "git reset --hard HEAD"}}, {}),
            ("flow-order-guard-codex.mjs", {"tool_name": "apply_patch", "cwd": str(self.cwd),
                "transcript_path": str(rollout), "tool_input": {"command": "*** Begin Patch\n*** Add File: src/app.py\n+x = 1\n*** End Patch"}},
             {"AGENTIC_FLOW_ORDER_BLOCK": "true"}),
        ]
        for shell, flags in self.shells():
            for name, payload, env in cases:
                with self.subTest(shell=shell, handler=name):
                    handler = next(h for _, h in handlers() if name in h["command"])
                    out = self.execute(handler, payload, shell, flags, env)
                    self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
                    if name.startswith("flow-order"):
                        self.assertIn("spec", out["hookSpecificOutput"]["permissionDecisionReason"])
                        self.assertIn("plan", out["hookSpecificOutput"]["permissionDecisionReason"])
