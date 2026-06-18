import json
import unittest
from argparse import Namespace
from pathlib import Path

from scripts import run_routing_eval as runner


REPO = Path(__file__).resolve().parents[1]


class TestRoutingEval(unittest.TestCase):
    def test_load_scenarios_validates_using_agentic_sdlc_fixture(self):
        scenarios = runner.load_scenarios(REPO / "tests/skills/routing/using-agentic-sdlc.json", 0)
        self.assertGreaterEqual(len(scenarios), 2)
        self.assertEqual(scenarios[0][0], 0)
        self.assertEqual(scenarios[0][1]["expected"], "mind-spark")
        self.assertFalse(scenarios[0][1]["escalation"])

    def test_load_scenarios_can_filter_by_index(self):
        scenarios = runner.load_scenarios(
            REPO / "tests/skills/routing/using-agentic-sdlc.json",
            scenario_indexes=[9, 11],
        )
        self.assertEqual([index for index, _ in scenarios], [9, 11])
        self.assertEqual(
            [scenario["expected"] for _, scenario in scenarios],
            ["feedback-triage", "implementasyon-control"],
        )

    def test_fixture_includes_language_independent_mind_spark_case(self):
        scenarios = runner.load_scenarios(REPO / "tests/skills/routing/using-agentic-sdlc.json", 0)
        prompts = [scenario["prompt"] for _, scenario in scenarios if scenario["expected"] == "mind-spark"]
        self.assertGreaterEqual(len(prompts), 2)
        self.assertTrue(any("I'm not sure what direction" in prompt for prompt in prompts))

    def test_evaluate_route_accepts_focused_skill_and_rejects_over_escalation(self):
        ok, reason = runner.evaluate_route("mind-spark", ["mind-spark"], escalation=False)
        self.assertTrue(ok)
        self.assertIsNone(reason)

        ok, reason = runner.evaluate_route("mind-spark", ["agentic-sdlc-pipeline"], escalation=False)
        self.assertFalse(ok)
        self.assertEqual(reason, "over_escalated_to_pipeline")

        ok, reason = runner.evaluate_route("agentic-sdlc-pipeline", ["agentic-sdlc-pipeline"], escalation=True)
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_parse_codex_events_reads_agent_message(self):
        lines = [
            json.dumps({"type": "thread.started", "thread_id": "t"}),
            json.dumps({
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": '{"skill":"plan-authoring","needs_dev_flow":false}',
                },
            }),
            json.dumps({
                "type": "turn.completed",
                "usage": {"input_tokens": 10, "output_tokens": 4, "reasoning_output_tokens": 1},
            }),
        ]
        skill, usage = runner.parse_codex_events(lines)
        self.assertEqual(skill, "plan-authoring")
        self.assertEqual(usage["input_tokens"], 10)
        self.assertEqual(usage["reasoning_output_tokens"], 1)

    def test_codex_prompt_keeps_ordinary_endpoint_work_on_feature_build(self):
        prompt = runner.build_codex_prompt(
            "Kullanicilar icin yeni bir CSV export endpoint'i ekle.",
            [
                ("feature-build", "Use when implementing a focused feature."),
                ("agentic-sdlc-pipeline", "Use for full gated SDLC implementation."),
            ],
        )

        self.assertIn("ordinary new feature or endpoint", prompt)
        self.assertIn("feature-build", prompt)
        self.assertIn("not agentic-sdlc-pipeline", prompt)

    def test_codex_prompt_distinguishes_final_audit_from_claim_gate(self):
        prompt = runner.build_codex_prompt(
            "Final cevaptan once spec/plan/TDD/guvenlik akisinin gercekten takip edildigini denetle.",
            [
                ("implementasyon-control", "Use for final implementation audit."),
                ("completion-claim-gate", "Use before done/fixed/passing claims."),
            ],
        )

        self.assertIn("Final implementation or process audit", prompt)
        self.assertIn("implementasyon-control", prompt)
        self.assertIn("completion-claim-gate only", prompt)

    def test_extract_codex_error_reports_model_access_failure(self):
        lines = [
            '2026-06-18T01:30:45Z WARN metadata missing\n',
            json.dumps({
                "type": "error",
                "message": json.dumps({
                    "type": "error",
                    "status": 400,
                    "error": {
                        "type": "invalid_request_error",
                        "message": "The 'GPT-5.3-Spark' model is not supported when using Codex with a ChatGPT account.",
                    },
                }),
            }),
            json.dumps({
                "type": "turn.failed",
                "error": {
                    "message": json.dumps({
                        "type": "error",
                        "status": 400,
                        "error": {
                            "type": "invalid_request_error",
                            "message": "The 'GPT-5.3-Spark' model is not supported when using Codex with a ChatGPT account.",
                        },
                    }),
                },
            }),
        ]

        error = runner.extract_codex_error(lines)

        self.assertIn("GPT-5.3-Spark", error)
        self.assertIn("not supported", error)
        self.assertNotEqual(error, "codex_exit_1")

    def test_gpt_53_spark_alias_resolves_to_codex_catalog_slug(self):
        self.assertEqual(runner.resolve_codex_model("GPT-5.3-Spark"), "gpt-5.3-codex-spark")
        self.assertEqual(runner.resolve_codex_model("gpt-5.3-spark"), "gpt-5.3-codex-spark")
        self.assertEqual(runner.resolve_codex_model("gpt-5.3-codex-spark"), "gpt-5.3-codex-spark")

    def test_build_codex_command_uses_exec_low_reasoning_and_read_only_sandbox(self):
        args = Namespace(model="GPT-5.3-Spark", reasoning_effort="low")
        cmd = runner.build_codex_command("codex", args, REPO)
        self.assertEqual(cmd[:4], ["codex", "-a", "never", "exec"])
        self.assertIn("--json", cmd)
        self.assertIn("--ephemeral", cmd)
        self.assertIn("--ignore-user-config", cmd)
        self.assertIn("--ignore-rules", cmd)
        self.assertIn("--skip-git-repo-check", cmd)
        self.assertIn("-m", cmd)
        self.assertEqual(cmd[cmd.index("-m") + 1], "gpt-5.3-codex-spark")
        self.assertIn('-c', cmd)
        self.assertIn('model_reasoning_effort="low"', cmd)
        self.assertEqual(cmd[cmd.index("-s") + 1], "read-only")
        self.assertEqual(cmd[-1], "-")


if __name__ == "__main__":
    unittest.main()
