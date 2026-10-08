import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from scripts import run_trigger_eval as runner


REPO = Path(__file__).resolve().parents[1]
SKILL_PATH = REPO / "skills" / "spec-authoring"
EVAL_SET = REPO / "tests" / "skills" / "evals" / "spec-authoring.json"


def assistant_tool(name, tool_input):
    return json.dumps({
        "type": "assistant",
        "message": {
            "content": [{
                "type": "tool_use",
                "name": name,
                "input": tool_input,
            }],
        },
    })


def stream_event(event):
    return json.dumps({"type": "stream_event", "event": event})


def result_event():
    return json.dumps({"type": "result"})


class TestTriggerDetector(unittest.TestCase):
    def setUp(self):
        self.clean = "spec-flow-skill-abcd1234"
        self.skill = "spec-authoring"

    def test_project_agent_instruction_read_blocks_trigger(self):
        detector = runner.TriggerDetector(self.clean, self.skill)
        decision = detector.feed(assistant_tool("Read", {"file_path": r"C:\repo\agentic-sdlc\AGENTS.md"}))
        self.assertFalse(decision)

    def test_allows_claude_project_memory_prelude_before_skill(self):
        detector = runner.TriggerDetector(self.clean, self.skill)
        decision = detector.feed(assistant_tool(
            "Read",
            {"file_path": r"C:\repo\memory\MEMORY.md"},
        ))
        self.assertIsNone(decision)
        self.assertIsNone(detector.feed(result_event()))

        decision = detector.feed(assistant_tool("Skill", {"skill": "agentic-sdlc:spec-authoring"}))
        self.assertTrue(decision)

    def test_command_file_read_is_not_a_skill_trigger(self):
        detector = runner.TriggerDetector(self.clean, self.skill)
        decision = detector.feed(assistant_tool("Read", {"file_path": rf"C:\repo\agentic-sdlc\commands\{self.clean}.md"}))
        self.assertIsNone(decision)

    def test_real_skill_file_read_counts_as_trigger(self):
        detector = runner.TriggerDetector(self.clean, self.skill)
        decision = detector.feed(assistant_tool("Read", {"file_path": r"C:\repo\agentic-sdlc\skills\spec-authoring\SKILL.md"}))
        self.assertTrue(decision)

    def test_other_first_read_blocks_trigger(self):
        detector = runner.TriggerDetector(self.clean, self.skill)
        decision = detector.feed(assistant_tool("Read", {"file_path": r"C:\repo\agentic-sdlc\skills\plan-authoring\SKILL.md"}))
        self.assertFalse(decision)

    def test_streaming_command_file_read_does_not_match_mid_delta(self):
        detector = runner.TriggerDetector(self.clean, self.skill)
        start = {
            "type": "content_block_start",
            "content_block": {"type": "tool_use", "name": "Read"},
        }
        first_delta = {
            "type": "content_block_delta",
            "delta": {"type": "input_json_delta", "partial_json": rf'{{"file_path":"C:\repo\agentic-sdlc\commands\{self.clean}'},
        }
        second_delta = {
            "type": "content_block_delta",
            "delta": {"type": "input_json_delta", "partial_json": '.md"}'},
        }
        stop = {"type": "content_block_stop"}

        self.assertIsNone(detector.feed(stream_event(start)))
        self.assertIsNone(detector.feed(stream_event(first_delta)))
        self.assertIsNone(detector.feed(stream_event(second_delta)))
        self.assertIsNone(detector.feed(stream_event(stop)))
        self.assertIsNone(detector.feed(stream_event({"type": "message_stop"})))
        self.assertIsNone(detector.feed(result_event()))


class TestDetectTriggerReplay(unittest.TestCase):
    def test_replay_blocks_after_project_agent_instruction_read(self):
        clean = "spec-flow-skill-abcd1234"
        lines = [
            assistant_tool("Read", {"file_path": r"C:\repo\agentic-sdlc\AGENTS.md"}),
            result_event(),
            assistant_tool("Skill", {"skill": "agentic-sdlc:spec-authoring"}),
        ]
        self.assertFalse(runner.detect_trigger(lines, clean, "spec-authoring"))

    def test_replay_does_not_count_command_file_read(self):
        clean = "spec-flow-skill-abcd1234"
        lines = [assistant_tool("Read", {"file_path": rf"C:\repo\agentic-sdlc\commands\{clean}.md"})]
        self.assertFalse(runner.detect_trigger(lines, clean, "spec-authoring"))


class TestBareRejected(unittest.TestCase):
    """AC18: --bare exits 2 without spawning claude."""

    def test_ac18_bare_exits_2_without_spawning_claude(self):
        with mock.patch.object(runner, "run_once", return_value=True) as run_once, \
                mock.patch.object(runner, "run_streaming") as run_streaming:
            code = runner.main([
                "--skill-path", str(SKILL_PATH),
                "--eval-set", str(EVAL_SET),
                "--bare",
            ])
        self.assertEqual(code, 2)
        run_once.assert_not_called()
        run_streaming.assert_not_called()


class TestClaudeChildEnvironment(unittest.TestCase):
    """AC18: CLAUDE_CODE_SIMPLE is stripped from the trigger runner child environment."""

    def test_ac18_strips_claude_code_simple_from_child_env(self):
        captured = {}

        def fake_streaming(cmd, project_root, env, timeout, detector, transcript_path=None):
            captured["env"] = env
            return False

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(os.environ, {"CLAUDE_CODE_SIMPLE": "1"}), \
                mock.patch.object(runner, "run_streaming", fake_streaming):
            runner.run_once("query", "spec-authoring", "desc", Path(td), 1, None, None, None, None, False, False)
        self.assertIsNotNone(captured.get("env"))
        self.assertNotIn("CLAUDE_CODE_SIMPLE", captured["env"])


class TestCommandShimLocation(unittest.TestCase):
    """AC19: default shim lives under .claude/commands and is cleaned up."""

    def test_ac19_shim_at_claude_commands_during_run_then_removed(self):
        seen = {}

        def fake_streaming(cmd, project_root, env, timeout, detector, transcript_path=None):
            shims = list((Path(project_root) / ".claude" / "commands").glob("*.md"))
            seen["shims"] = shims
            seen["exists"] = all(path.is_file() for path in shims)
            return False

        with tempfile.TemporaryDirectory() as td, mock.patch.object(runner, "run_streaming", fake_streaming):
            root = Path(td)
            runner.run_once("query", "spec-authoring", "desc", root, 1, None, None, None, None, False, True)
            self.assertTrue(seen.get("shims"))
            self.assertTrue(seen.get("exists"))
            self.assertFalse((root / ".claude").exists())

    def test_ac19_created_dirs_removed_on_raise(self):
        def boom(*_args, **_kwargs):
            raise RuntimeError("streaming failed")

        with tempfile.TemporaryDirectory() as td, mock.patch.object(runner, "run_streaming", boom):
            root = Path(td)
            with self.assertRaises(RuntimeError):
                runner.run_once("query", "spec-authoring", "desc", root, 1, None, None, None, None, False, True)
            self.assertFalse((root / ".claude").exists())

    def test_ac19_preserves_preexisting_commands_and_siblings(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(runner, "run_streaming", lambda *a, **k: False):
            root = Path(td)
            commands = root / ".claude" / "commands"
            commands.mkdir(parents=True)
            sibling = root / ".claude" / "settings.json"
            sibling.write_text("{}", encoding="utf-8")
            other = commands / "keep.md"
            other.write_text("keep", encoding="utf-8")
            runner.run_once("query", "spec-authoring", "desc", root, 1, None, None, None, None, False, True)
            self.assertTrue(sibling.is_file())
            self.assertEqual(other.read_text(encoding="utf-8"), "keep")
            self.assertEqual(list(commands.glob("*-skill-*.md")), [])

    def test_ac19_plugin_dir_disables_shim_and_reports(self):
        with mock.patch.object(runner, "run_once", return_value=True) as run_once:
            out = io.StringIO()
            with redirect_stdout(out):
                code = runner.main([
                    "--skill-path", str(SKILL_PATH),
                    "--eval-set", str(EVAL_SET),
                    "--plugin-dir", str(REPO),
                    "--smoke",
                ])
        self.assertEqual(code, 0)
        self.assertIn("command_shim=disabled:plugin-dir", out.getvalue())
        self.assertTrue(run_once.called)
        self.assertFalse(run_once.call_args.args[-1])


if __name__ == "__main__":
    unittest.main()
