import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


@unittest.skipIf(NODE is None, "node not available")
class TestDestructiveCommandGuard(unittest.TestCase):
    def run_hook(self, command):
        proc = subprocess.run(
            [NODE, str(REPO / "hooks" / "destructive-command-guard.mjs")],
            input=json.dumps({"tool_input": {"command": command}}),
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def test_blocks_git_reset_hard(self):
        out = self.run_hook("git reset --hard HEAD")
        decision = out["hookSpecificOutput"]["permissionDecision"]
        self.assertEqual(decision, "deny")

    def test_blocks_rm_rf(self):
        out = self.run_hook("rm -rf ./tmp")
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("rm-rf", reason)

    def test_blocks_git_clean_fdx(self):
        out = self.run_hook("git clean -fdx")
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("git-clean-force", reason)

    def test_allows_non_destructive_command(self):
        out = self.run_hook("git status --short")
        self.assertEqual(out, {})


@unittest.skipIf(NODE is None or shutil.which("git") is None, "node or git not available")
class TestBranchGuard(unittest.TestCase):
    def run_hook(self, command, cwd, block=False):
        env = os.environ.copy()
        if block:
            env["AGENTIC_BRANCH_GUARD_BLOCK"] = "true"
        proc = subprocess.run(
            [NODE, str(REPO / "hooks" / "branch-guard.mjs")],
            cwd=cwd,
            env=env,
            input=json.dumps({"tool_input": {"command": command}}),
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def test_blocks_main_branch_when_strict_even_before_first_commit(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", "-b", "main"], cwd=td, check=True, capture_output=True)
            out = self.run_hook("git commit -m test", td, block=True)
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_warns_main_branch_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", "-b", "main"], cwd=td, check=True, capture_output=True)
            out = self.run_hook("git push origin main", td, block=False)
            self.assertIn("systemMessage", out)
            self.assertNotIn("hookSpecificOutput", out)


@unittest.skipIf(NODE is None, "node not available")
class TestSessionStartHook(unittest.TestCase):
    def test_injects_agentic_sdlc_bootstrap(self):
        proc = subprocess.run(
            [NODE, str(REPO / "hooks" / "session-start.mjs")],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        context = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("AGENTIC_SDLC_BOOTSTRAP", context)
        self.assertIn("root skills/", context)
        self.assertIn("using-agentic-sdlc", context)
        self.assertIn("smallest sufficient skill", context)
        self.assertIn("session-local routing memory", context)
        self.assertIn("agentic-sdlc-pipeline is only for full-envelope", context)
