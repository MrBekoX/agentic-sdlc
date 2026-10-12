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


class FakeProcess:
    """A child that has already exited; `stdout` is what it printed before exiting."""

    pid = 4242

    def __init__(self, lines, returncode):
        self.stdout = iter(lines)
        self.returncode = returncode

    def poll(self):
        return self.returncode

    def kill(self):  # never reached: kill_process_tree is stubbed in these tests
        raise AssertionError("a fake process must not be killed")


class FakeRunningProcess(FakeProcess):
    """A child that never exits within the test: poll() stays None."""

    def poll(self):
        return None


class TestUnmeasuredRuns(unittest.TestCase):
    """A run that produced no trigger measurement must not be counted as "did not trigger".

    A process failure used to return False from run_streaming, so a negative query (should_trigger
    false) PASSED when the CLI was unauthenticated, out of quota or killed by the timeout."""

    def _stream(self, process, timeout=5):
        with mock.patch.object(runner.subprocess, "Popen", return_value=process), \
                mock.patch.object(runner, "kill_process_tree"):
            return runner.run_streaming(
                ["claude", "-p", "q"], Path("."), {}, timeout, runner.TriggerDetector("clean-1", "spec-authoring"),
            )

    def test_a_failed_process_is_unmeasured_not_untriggered(self):
        with self.assertRaises(runner.UnmeasuredRun) as caught:
            self._stream(FakeProcess([], 1))
        self.assertEqual(caught.exception.reason, "exit_1")

    def test_a_failed_process_with_output_is_still_unmeasured(self):
        with self.assertRaises(runner.UnmeasuredRun) as caught:
            self._stream(FakeProcess(["Credit balance is too low\n"], 1))
        self.assertEqual(caught.exception.reason, "exit_1")

    def test_a_clean_exit_with_no_output_is_unmeasured(self):
        with self.assertRaises(runner.UnmeasuredRun) as caught:
            self._stream(FakeProcess([], 0))
        self.assertEqual(caught.exception.reason, "no_output")

    def test_a_timeout_is_unmeasured(self):
        with self.assertRaises(runner.UnmeasuredRun) as caught:
            self._stream(FakeRunningProcess([], None), timeout=0)
        self.assertEqual(caught.exception.reason, "timeout")

    def test_an_error_result_without_a_decision_is_unmeasured(self):
        # An unauthenticated or out-of-quota CLI still emits a `result` event, flagged is_error.
        error = json.dumps({"type": "result", "subtype": "success", "is_error": True}) + "\n"
        with self.assertRaises(runner.UnmeasuredRun) as caught:
            self._stream(FakeProcess([error], 0))
        self.assertEqual(caught.exception.reason, "result_error")

    def test_a_missing_cli_is_unmeasured(self):
        with mock.patch.object(runner.subprocess, "Popen", side_effect=FileNotFoundError("claude")), \
                self.assertRaises(runner.UnmeasuredRun) as caught:
            runner.run_streaming(["claude"], Path("."), {}, 5, runner.TriggerDetector("c", "s"))
        self.assertEqual(caught.exception.reason, "claude_missing")

    def test_control_an_answer_without_the_skill_is_untriggered(self):
        self.assertIs(self._stream(FakeProcess([result_event() + "\n"], 0)), False)

    def test_control_a_skill_call_is_triggered(self):
        line = assistant_tool("Skill", {"skill": "agentic-sdlc:spec-authoring"}) + "\n"
        self.assertIs(self._stream(FakeProcess([line], 0)), True)

    def _main(self, queries, side_effect, runs="2"):
        with tempfile.TemporaryDirectory() as td:
            eval_set = Path(td) / "eval.json"
            eval_set.write_text(json.dumps({"queries": queries}), encoding="utf-8")
            out = io.StringIO()
            with mock.patch.object(runner, "run_once", side_effect=side_effect), redirect_stdout(out):
                code = runner.main([
                    "--skill-path", str(SKILL_PATH), "--eval-set", str(eval_set),
                    "--runs", runs, "--plugin-dir", str(REPO),
                ])
        return code, out.getvalue()

    def test_main_reports_an_unmeasured_negative_query_as_unmeasured_not_passed(self):
        def fail(*_args, **_kwargs):
            raise runner.UnmeasuredRun("exit_1")

        code, out = self._main([{"query": "unrelated", "should_trigger": False}], fail)
        self.assertEqual(code, 3, out)
        self.assertIn("trigger_eval=unmeasured", out)
        self.assertNotIn("trigger_eval=passed", out)
        self.assertIn("queries_passed=0/1", out)
        self.assertIn("error=q0_unmeasured:runs=2,reason=exit_1", out)

    def test_main_does_not_hide_a_mismatch_behind_an_unmeasured_query(self):
        def run(query, *_args, **_kwargs):
            if query == "a":
                raise runner.UnmeasuredRun("timeout")
            return True  # triggered on a negative query: a real mismatch

        queries = [{"query": "a", "should_trigger": True}, {"query": "b", "should_trigger": False}]
        code, out = self._main(queries, run)
        self.assertEqual(code, 1, out)
        self.assertIn("trigger_eval=failed", out)
        self.assertIn("error=q0_unmeasured:runs=2,reason=timeout", out)
        self.assertIn("error=q1_mismatch:should_trigger=False,rate=1.00", out)

    def test_main_still_passes_when_every_run_was_measured(self):
        code, out = self._main([{"query": "unrelated", "should_trigger": False}], lambda *_a, **_k: False)
        self.assertEqual(code, 0, out)
        self.assertIn("trigger_eval=passed", out)

    def test_the_batch_wrapper_labels_an_unmeasured_skill_as_unmeasured(self):
        from scripts import run_all_trigger_evals as batch

        with tempfile.TemporaryDirectory() as td:
            skill = Path(td) / "skills" / "demo"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: demo\n---\n", encoding="utf-8")
            args = mock.Mock(runtime="claude")
            out = io.StringIO()
            with mock.patch.object(batch, "run_single_eval", return_value=(3, "trigger_eval=unmeasured\n")), \
                    redirect_stdout(out):
                total, passed, failures = batch.run_evaluations(
                    [("demo", skill, Path(td) / "e.json")], ("claude",), args,
                )
        self.assertEqual((total, passed, failures), (1, 0, ["claude:demo:exit_3"]))
        self.assertIn("claude:demo:status=unmeasured", out.getvalue())


if __name__ == "__main__":
    unittest.main()
