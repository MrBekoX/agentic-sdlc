import json
import unittest

from scripts import run_codex_trigger_eval as runner


class TestCodexTriggerEval(unittest.TestCase):
    def test_extract_json_object_from_plain_json(self):
        parsed = runner.extract_json_object('{"skill":"spec-flow","needs_dev_flow":false}')
        self.assertEqual(parsed["skill"], "spec-flow")
        self.assertFalse(parsed["needs_dev_flow"])

    def test_extract_json_object_from_wrapped_text(self):
        parsed = runner.extract_json_object('Result: {"skill":"plan-flow","needs_dev_flow":false}')
        self.assertEqual(parsed["skill"], "plan-flow")

    def test_parse_codex_events_reads_agent_message_and_usage(self):
        lines = [
            json.dumps({"type": "thread.started", "thread_id": "t"}),
            json.dumps({
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": '{"skill":"spec-flow","needs_dev_flow":false}',
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
        self.assertEqual(skill, "spec-flow")
        self.assertEqual(usage["input_tokens"], 12)
        self.assertEqual(usage["output_tokens"], 3)
        self.assertEqual(usage["reasoning_output_tokens"], 1)


if __name__ == "__main__":
    unittest.main()
