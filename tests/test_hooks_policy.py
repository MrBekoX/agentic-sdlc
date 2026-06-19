import json
import os
import re
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
        self.assertIn("session-local routing memory", context)
        self.assertIn("agentic-sdlc-pipeline is only for full-envelope", context)
        self.assertIn("Route by semantic intent, not exact keywords or prompt language", context)
        self.assertIn("agentic-sdlc:mind-spark", context)
        self.assertIn("agentic-sdlc:plan-authoring", context)
        self.assertIn("never ask for bug details first", context)
        self.assertIn("after details arrive", context)
        self.assertRegex(
            context,
            re.compile(r"Any-language end-to-end/full-envelope.*agentic-sdlc:agentic-sdlc-pipeline"),
        )
        self.assertIn("agentic-sdlc:test-authoring", context)
        self.assertRegex(context, re.compile(r"Any-language behavior-preserving refactor.*agentic-sdlc:safe-refactor"))
        self.assertIn("before Glob/Read/file-existence checks", context)
        self.assertRegex(context, re.compile(r"Any-language received-review-feedback.*agentic-sdlc:feedback-triage"))
        self.assertRegex(context, re.compile(r"Any-language orchestration decision.*agentic-sdlc:dispatch-strategy"))
        self.assertIn("do not choose a mechanism directly without the Skill call", context)
        self.assertIn("same-purpose skill", context)
        self.assertIn("Any-language clear implementation prompts", context)
        self.assertIn("agentic-sdlc:feature-build", context)
        self.assertIn("ask for the full pipeline", context)
        self.assertIn("Never replace agentic-sdlc:mind-spark with superpowers:brainstorming", context)
        self.assertIn("agentic-sdlc:implementasyon-control", context)
        self.assertIn("do not answer from memory", context)
        self.assertIn("Any-language prompt asking to audit", context)
        self.assertIn("not a passive session preference", context)
        self.assertIn("audit intent requires a Skill call", context)
        self.assertIn("report missing evidence", context)
        self.assertIn("before asking clarifying questions", context)
        self.assertIn("do not say you will use the skill later", context)


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
        self.assertIn("Codex skill invocation via $skill-name or @agentic-sdlc:skill-name", context)
        self.assertIn("embedded author -> critic -> revise adapter", context)
        self.assertIn("completion-claim-gate", context)
        self.assertNotIn("Skill tool", context)
        self.assertNotIn("calling the Skill tool", context)
