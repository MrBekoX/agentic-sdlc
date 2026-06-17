import json
import unittest

from scripts import run_trigger_eval as runner


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
        self.skill = "spec-flow"

    def test_allows_agents_prelude_before_skill(self):
        detector = runner.TriggerDetector(self.clean, self.skill)
        decision = detector.feed(assistant_tool("Read", {"file_path": r"C:\repo\agentic-sdlc\AGENTS.md"}))
        self.assertIsNone(decision)
        self.assertIsNone(detector.feed(result_event()))

        decision = detector.feed(assistant_tool("Skill", {"skill": "agentic-sdlc:spec-flow"}))
        self.assertTrue(decision)

    def test_allows_claude_project_memory_prelude_before_skill(self):
        detector = runner.TriggerDetector(self.clean, self.skill)
        decision = detector.feed(assistant_tool(
            "Read",
            {"file_path": r"C:\repo\memory\MEMORY.md"},
        ))
        self.assertIsNone(decision)
        self.assertIsNone(detector.feed(result_event()))

        decision = detector.feed(assistant_tool("Skill", {"skill": "agentic-sdlc:spec-flow"}))
        self.assertTrue(decision)

    def test_command_file_read_is_not_a_skill_trigger(self):
        detector = runner.TriggerDetector(self.clean, self.skill)
        decision = detector.feed(assistant_tool("Read", {"file_path": rf"C:\repo\agentic-sdlc\commands\{self.clean}.md"}))
        self.assertIsNone(decision)

    def test_real_skill_file_read_counts_as_trigger(self):
        detector = runner.TriggerDetector(self.clean, self.skill)
        decision = detector.feed(assistant_tool("Read", {"file_path": r"C:\repo\agentic-sdlc\skills\spec-flow\SKILL.md"}))
        self.assertTrue(decision)

    def test_other_first_read_blocks_trigger(self):
        detector = runner.TriggerDetector(self.clean, self.skill)
        decision = detector.feed(assistant_tool("Read", {"file_path": r"C:\repo\agentic-sdlc\skills\plan-flow\SKILL.md"}))
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
    def test_replay_continues_after_allowed_prelude(self):
        clean = "spec-flow-skill-abcd1234"
        lines = [
            assistant_tool("Read", {"file_path": r"C:\repo\agentic-sdlc\AGENTS.md"}),
            result_event(),
            assistant_tool("Skill", {"skill": "agentic-sdlc:spec-flow"}),
        ]
        self.assertTrue(runner.detect_trigger(lines, clean, "spec-flow"))

    def test_replay_does_not_count_command_file_read(self):
        clean = "spec-flow-skill-abcd1234"
        lines = [assistant_tool("Read", {"file_path": rf"C:\repo\agentic-sdlc\commands\{clean}.md"})]
        self.assertFalse(runner.detect_trigger(lines, clean, "spec-flow"))


if __name__ == "__main__":
    unittest.main()
