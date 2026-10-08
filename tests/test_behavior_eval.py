import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import run_behavior_eval as runner


REPO = Path(__file__).resolve().parents[1]


class TestBehaviorEvalHarness(unittest.TestCase):
    def test_dry_run_validates_fixture(self):
        proc = subprocess.run(
            [
                sys.executable,
                "scripts/run_behavior_eval.py",
                "--eval-set",
                "tests/skills/behavior/completion-claim-gate.json",
                "--dry-run",
            ],
            cwd=REPO,
            capture_output=True,
            text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("behavior_eval=dry-run-passed", proc.stdout)


class TestBehaviorTextScope(unittest.TestCase):
    """AC21: required and forbidden patterns match only main-session assistant text and result.result."""

    def test_ac21_init_only_stream_fails_required_command_pattern(self):
        stream = json.dumps({
            "type": "system",
            "subtype": "init",
            "slash_commands": ["command"],
            "tools": ["Bash"],
        })
        errors = runner.check_case(
            {"id": "probe", "prompt": "p", "required_patterns": ["command"]},
            stream,
        )
        self.assertEqual(errors, ["probe:missing:command"])

    def test_ac21_forbidden_patterns_use_the_same_text_set(self):
        stream = "\n".join((
            json.dumps({"type": "system", "subtype": "init", "slash_commands": ["forbidden-word"]}),
            "stderr mention of forbidden-word",
        ))
        errors = runner.check_case(
            {"id": "probe", "prompt": "p", "forbidden_patterns": ["forbidden-word"]},
            stream,
        )
        self.assertEqual(errors, [])

    def test_ac21_matches_main_session_assistant_text_and_result(self):
        stream = "\n".join((
            json.dumps({"type": "assistant",
                        "message": {"content": [{"type": "text", "text": "hello command"}]}}),
            json.dumps({"type": "result", "result": "done with command"}),
        ))
        errors = runner.check_case(
            {"id": "probe", "prompt": "p", "required_patterns": ["hello command", "done with command"]},
            stream,
        )
        self.assertEqual(errors, [])


class TestClaudeChildEnvironment(unittest.TestCase):
    """AC18: CLAUDE_CODE_SIMPLE is stripped from the behavior runner child environment."""

    def test_ac18_strips_claude_code_simple_from_child_env(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SIMPLE": "1"}), \
                    mock.patch.object(runner.subprocess, "run") as run:
                run.return_value = subprocess.CompletedProcess(["claude"], 0, stdout="", stderr="")
                runner.run_claude("prompt", Path(td), 1, None)
            self.assertTrue(run.called)
            env = run.call_args.kwargs.get("env")
            self.assertIsNotNone(env)
            self.assertNotIn("CLAUDE_CODE_SIMPLE", env)

