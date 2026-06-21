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

    def test_blocks_recursive_rm_forms(self):
        blocked = [
            "rm -rf ./tmp",
            "rm -fr ./tmp",
            "rm -r -f ./tmp",
            "rm --recursive --force ./tmp",
            "rm -r ./tmp",
            "rm -R ./tmp",
            "echo before; rm -r ./tmp",
            "git status && rm --recursive ./tmp",
            "(rm -rf ./tmp)",
            "{ rm -rf ./tmp; }",
            "echo $(rm -rf ./tmp)",
            "/bin/rm -rf ./tmp",
            "sudo rm -rf ./tmp",
            "command rm -rf ./tmp",
            "git status; sudo rm -rf ./tmp",
            "sudo -E rm -rf ./tmp",
            "sudo -u root rm -rf ./tmp",
            "sudo FOO=bar rm -rf ./tmp",
            "env FOO=bar rm -rf ./tmp",
            "env -u FOO rm -rf ./tmp",
            "rm.exe -rf ./tmp",
            "rm ./tmp -Recurse",
        ]
        for command in blocked:
            with self.subTest(command=command):
                out = self.run_hook(command)
                reason = out["hookSpecificOutput"]["permissionDecisionReason"]
                self.assertIn("rm-recursive", reason)

    def test_blocks_recursive_remove_item_forms(self):
        blocked = [
            "Remove-Item ./tmp -Recurse",
            "Remove-Item ./tmp -r",
            "Remove-Item ./tmp -Re",
            "Remove-Item ./tmp -Rec",
            "Remove-Item ./tmp -Recurse -Force",
            "Write-Output ok; Remove-Item ./tmp -Recurse",
            "ri ./tmp -Recurse",
            "del ./tmp -Recurse",
            "erase ./tmp -Recurse",
            "rd ./tmp -Recurse",
            "rmdir ./tmp -Recurse",
            "powershell -Command Remove-Item ./tmp -Recurse",
            "powershell -Command Remove-Item ./tmp -Re",
            'pwsh -c "Remove-Item ./tmp -Recurse"',
        ]
        for command in blocked:
            with self.subTest(command=command):
                out = self.run_hook(command)
                reason = out["hookSpecificOutput"]["permissionDecisionReason"]
                self.assertIn("powershell-remove-item-recurse", reason)

    def test_blocks_git_clean_fdx(self):
        out = self.run_hook("git clean -fdx")
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("git-clean-force", reason)

    def test_allows_non_destructive_commands(self):
        allowed = [
            "git status --short",
            "rm -f file.txt",
            "Remove-Item file.txt -Force",
            "ls -r",
            "rm file.txt; ls -r",
            "Remove-Item file.txt; Get-ChildItem -Recurse",
            "printf '; rm -rf ./tmp'",
            'echo "rm -rf ./tmp"',
            "Write-Output '; Remove-Item ./tmp -Recurse'",
        ]
        for command in allowed:
            with self.subTest(command=command):
                out = self.run_hook(command)
                self.assertEqual(out, {})

    # Regression: bypasses confirmed by the multi-lens-review run (2026-06-21).
    def test_blocks_git_global_option_bypasses(self):
        # git global options before the subcommand defeat an adjacency-only match.
        blocked = [
            ("git -C /tmp reset --hard", "git-reset-hard"),
            ("git -c core.pager=cat reset --hard HEAD", "git-reset-hard"),
            ("git --no-pager reset --hard", "git-reset-hard"),
            ("git -C /tmp clean -fdx", "git-clean-force"),
        ]
        for command, label in blocked:
            with self.subTest(command=command):
                out = self.run_hook(command)
                reason = out["hookSpecificOutput"]["permissionDecisionReason"]
                self.assertIn(label, reason)

    def test_blocks_rm_long_recursive_flag_bundles(self):
        # Recursive short-flag bundles longer than 5 chars (the old arg.length<=5 cap).
        for command in ["rm -rfvvv ./tmp", "rm -vfrii ./tmp", "rm -fdrvv ./tmp"]:
            with self.subTest(command=command):
                out = self.run_hook(command)
                reason = out["hookSpecificOutput"]["permissionDecisionReason"]
                self.assertIn("rm-recursive", reason)

    def test_blocks_wrapped_recursive_rm(self):
        # Shell -c payloads, eval, and prefix wrappers that hide the real command.
        blocked = [
            'bash -c "rm -rf ./tmp"',
            "sh -c 'rm -rf ./tmp'",
            'zsh -c "rm -rf ./tmp"',
            'eval "rm -rf ./tmp"',
            "timeout 5 rm -rf ./tmp",
            "timeout -s KILL 5 rm -rf ./tmp",
            "nohup rm -rf ./tmp",
            "nice -n 10 rm -rf ./tmp",
            "nice rm -rf ./tmp",
            "setsid rm -rf ./tmp",
            "xargs rm -rf",
        ]
        for command in blocked:
            with self.subTest(command=command):
                out = self.run_hook(command)
                reason = out["hookSpecificOutput"]["permissionDecisionReason"]
                self.assertIn("rm-recursive", reason)

    def test_allows_wrappers_and_global_options_on_safe_commands(self):
        # False-positive boundary: wrappers / global options on non-destructive commands stay allowed.
        allowed = [
            "timeout 5 ls -la",
            "nice -n 10 ls",
            'bash -c "ls -la"',
            "sh -c 'echo hi'",
            "git -C /repo status",
            "git --no-pager log --oneline",
            "nohup sleep 30",
            "xargs ls",
            "time rm file.txt",
        ]
        for command in allowed:
            with self.subTest(command=command):
                out = self.run_hook(command)
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
class TestCompletionClaimGuard(unittest.TestCase):
    HOOK = REPO / "hooks" / "completion-claim-guard.mjs"

    def _transcript(self, td, lines):
        path = Path(td) / "transcript.jsonl"
        path.write_text("\n".join(json.dumps(o) for o in lines), encoding="utf-8")
        return path

    def run_hook(self, lines, *, block=False, stop_active=False):
        with tempfile.TemporaryDirectory() as td:
            tpath = self._transcript(td, lines)
            env = os.environ.copy()
            if block:
                env["AGENTIC_COMPLETION_GATE_BLOCK"] = "true"
            proc = subprocess.run(
                [NODE, str(self.HOOK)],
                env=env,
                input=json.dumps({"transcript_path": str(tpath), "stop_hook_active": stop_active}),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = (proc.stdout or "").strip()
            return json.loads(out) if out else {}

    @staticmethod
    def _assistant(text):
        return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}

    @staticmethod
    def _gate_call():
        return {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Skill", "input": {"skill": "agentic-sdlc:completion-claim-gate"}}]}}

    def test_warns_on_claim_without_gate(self):
        out = self.run_hook([self._assistant("Feature complete. All tests passing.")])
        self.assertIn("systemMessage", out)
        self.assertNotIn("decision", out)

    def test_blocks_on_claim_without_gate_when_strict(self):
        out = self.run_hook([self._assistant("Implementation complete and ready to merge.")], block=True)
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("completion-claim-gate", out.get("reason", ""))

    def test_silent_when_gate_invoked(self):
        out = self.run_hook([self._gate_call(), self._assistant("Feature complete. All tests passing.")], block=True)
        self.assertEqual(out, {})

    def test_silent_without_claim(self):
        out = self.run_hook([self._assistant("Here is the current state; a couple of tests still fail.")], block=True)
        self.assertEqual(out, {})

    def test_loop_guard_allows_when_stop_hook_active(self):
        out = self.run_hook([self._assistant("Feature complete. All tests passing.")], block=True, stop_active=True)
        self.assertEqual(out, {})


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
        self.assertIn("agentic-sdlc-pipeline is only for full-envelope", context)
        self.assertIn("Route by semantic intent", context)
        self.assertIn("agentic-sdlc:mind-spark", context)
        self.assertIn("agentic-sdlc:plan-authoring", context)
        self.assertIn("never ask for bug details first", context)
        self.assertIn("agentic-sdlc:implementasyon-control", context)
        self.assertIn("agentic-sdlc:completion-claim-gate", context)
        self.assertIn("fresh evidence", context)
        self.assertIn("Skill tool", context)


@unittest.skipIf(NODE is None, "node not available")
class TestCodexSessionStartHook(unittest.TestCase):
    def test_injects_codex_specific_bootstrap_without_claude_tooling(self):
        proc = subprocess.run(
            [NODE, str(REPO / "hooks" / "session-start-codex.mjs")],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        context = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("AGENTIC_SDLC_CODEX_BOOTSTRAP", context)
        self.assertIn("AGENTIC-SDLC Codex plugin", context)
        self.assertIn("root skills/", context)
        self.assertIn("Codex does not expose Claude Code Skill, Workflow, or Agent transcript events", context)
        self.assertIn("embedded author -> critic -> revise adapter", context)
        self.assertIn("completion-claim-gate", context)
        self.assertNotIn("Skill tool", context)
        self.assertNotIn("calling the Skill tool", context)
