import json
import os
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

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
            ["feedback-triage", "implementation-control"],
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
                ("implementation-control", "Use for final implementation audit."),
                ("completion-claim-gate", "Use before done/fixed/passing claims."),
            ],
        )

        self.assertIn("Final implementation or process audit", prompt)
        self.assertIn("implementation-control", prompt)
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

    def test_explicit_project_root_requires_writable_opt_in(self):
        with tempfile.TemporaryDirectory() as td, self.assertRaises(SystemExit) as raised:
            runner.main([
                "--eval-set",
                str(REPO / "tests/skills/routing/using-agentic-sdlc.json"),
                "--project-root",
                td,
                "--smoke",
            ])
        self.assertEqual(raised.exception.code, 2)

    def test_default_live_working_directory_is_ephemeral_and_not_plugin_source(self):
        observed = {}

        def capture(args, scenarios, skills):
            observed["project_root"] = args.project_root
            observed["plugin_dir"] = args.plugin_dir
            self.assertTrue(args.project_root.is_dir())
            return 0

        with mock.patch.object(runner, "run_loaded_eval", side_effect=capture):
            result = runner.main([
                "--eval-set",
                str(REPO / "tests/skills/routing/using-agentic-sdlc.json"),
                "--smoke",
            ])
        self.assertEqual(result, 0)
        self.assertEqual(observed["plugin_dir"], REPO)
        self.assertNotEqual(observed["project_root"], REPO)
        self.assertFalse(observed["project_root"].exists())

    def test_claude_command_uses_plugin_source_separate_from_cwd(self):
        source = REPO
        with tempfile.TemporaryDirectory() as td:
            args = Namespace(
                project_root=Path(td),
                plugin_dir=source,
                model="haiku",
                max_turns=1,
                max_budget_usd="0.01",
                timeout=1,
            )
            with mock.patch.object(runner.subprocess, "Popen", side_effect=FileNotFoundError) as popen:
                _, error = runner.run_claude("route", args, None)
            self.assertEqual(error, "claude_missing")
            command = popen.call_args.args[0]
            self.assertEqual(command[command.index("--plugin-dir") + 1], str(source))
            self.assertEqual(popen.call_args.kwargs["cwd"], Path(td))


class TestSubagentRoutes(unittest.TestCase):
    """AC20: a Skill invoked only by a subagent is not a route."""

    def test_ac20_subagent_only_skill_is_not_a_route(self):
        lines = [json.dumps({
            "type": "assistant",
            "parent_tool_use_id": "agent-1",
            "message": {"content": [{"type": "tool_use", "name": "Skill",
                                     "input": {"skill": "feature-build"}}]},
        })]
        self.assertEqual(runner.collect_claude_routes(lines), [])

    def test_ac20_main_session_skill_is_unchanged(self):
        lines = [json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": "Skill",
                                     "input": {"skill": "feature-build"}}]},
        })]
        self.assertEqual(runner.collect_claude_routes(lines), ["feature-build"])


class TestClaudeChildEnvironment(unittest.TestCase):
    """AC18: CLAUDE_CODE_SIMPLE is stripped from the routing runner child environment."""

    def test_ac18_strips_claude_code_simple_from_child_env(self):
        with tempfile.TemporaryDirectory() as td:
            args = Namespace(
                project_root=Path(td),
                plugin_dir=REPO,
                model="haiku",
                max_turns=1,
                max_budget_usd="0.01",
                timeout=1,
            )
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SIMPLE": "1"}), \
                    mock.patch.object(runner.subprocess, "Popen", side_effect=FileNotFoundError) as popen:
                runner.run_claude("route", args, None)
            self.assertTrue(popen.called)
            env = popen.call_args.kwargs["env"]
            self.assertNotIn("CLAUDE_CODE_SIMPLE", env)


if __name__ == "__main__":
    unittest.main()
