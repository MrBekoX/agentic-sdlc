import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import run_codex_trigger_eval as runner


class TestCodexTriggerEval(unittest.TestCase):
    SKILL = Path(__file__).resolve().parents[1] / "skills" / "spec-authoring"
    EVAL = Path(__file__).resolve().parents[1] / "tests" / "skills" / "evals" / "spec-authoring.json"

    def test_extract_json_object_from_plain_json(self):
        parsed = runner.extract_json_object('{"skill":"spec-authoring","needs_dev_flow":false}')
        self.assertEqual(parsed["skill"], "spec-authoring")
        self.assertFalse(parsed["needs_dev_flow"])

    def test_extract_json_object_from_wrapped_text(self):
        parsed = runner.extract_json_object('Result: {"skill":"plan-authoring","needs_dev_flow":false}')
        self.assertEqual(parsed["skill"], "plan-authoring")

    def test_parse_codex_events_reads_agent_message_and_usage(self):
        lines = [
            json.dumps({"type": "thread.started", "thread_id": "t"}),
            json.dumps({
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": '{"skill":"spec-authoring","needs_dev_flow":false}',
                },
            }),
            json.dumps({
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 12,
                    "output_tokens": 3,
                    "reasoning_output_tokens": 1,
                },
            }),
        ]
        skill, usage = runner.parse_codex_events(lines)
        self.assertEqual(skill, "spec-authoring")
        self.assertEqual(usage["input_tokens"], 12)
        self.assertEqual(usage["output_tokens"], 3)
        self.assertEqual(usage["reasoning_output_tokens"], 1)

    def test_default_live_project_is_ephemeral_and_removed(self):
        observed = {}

        def fake_run(_prompt, project_root, _args, _transcript_path):
            observed["project_root"] = project_root
            self.assertTrue(project_root.is_dir())
            return "spec-authoring", {}, None

        with mock.patch.object(runner, "run_codex_once", side_effect=fake_run):
            result = runner.main([
                "--skill-path", str(self.SKILL),
                "--eval-set", str(self.EVAL),
                "--smoke",
            ])

        self.assertEqual(result, 0)
        self.assertNotEqual(observed["project_root"], Path(__file__).resolve().parents[1])
        self.assertFalse(observed["project_root"].exists())

    def test_explicit_project_root_requires_opt_in(self):
        with tempfile.TemporaryDirectory() as td, self.assertRaises(SystemExit) as raised:
            runner.main([
                "--skill-path", str(self.SKILL),
                "--eval-set", str(self.EVAL),
                "--smoke",
                "--project-root", td,
            ])
        self.assertEqual(raised.exception.code, 2)

    def test_explicit_project_root_with_opt_in_is_used(self):
        observed = {}

        def fake_run(_prompt, project_root, _args, _transcript_path):
            observed["project_root"] = project_root
            return "spec-authoring", {}, None

        with tempfile.TemporaryDirectory() as td, mock.patch.object(
            runner, "run_codex_once", side_effect=fake_run
        ):
            result = runner.main([
                "--skill-path", str(self.SKILL),
                "--eval-set", str(self.EVAL),
                "--smoke",
                "--project-root", td,
                "--allow-writable-project",
            ])
            self.assertEqual(observed["project_root"], Path(td).resolve())

        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
