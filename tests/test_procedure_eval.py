import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import scripts.run_procedure_eval as procedure_eval


REPO = Path(__file__).resolve().parents[1]


class TestProcedureEvalHarness(unittest.TestCase):
    def test_dry_run_validates_dev_flow_fixture(self):
        proc = subprocess.run(
            [
                sys.executable,
                "scripts/run_procedure_eval.py",
                "--eval-set",
                "tests/skills/procedure/agentic-sdlc-pipeline.json",
                "--dry-run",
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("procedure_eval=dry-run-passed", proc.stdout)

    def test_sample_transcript_passes_dev_flow_coverage(self):
        proc = subprocess.run(
            [
                sys.executable,
                "scripts/run_procedure_eval.py",
                "--eval-set",
                "tests/skills/procedure/agentic-sdlc-pipeline.json",
                "--transcript",
                "tests/fixtures/transcripts/agentic-sdlc-pipeline-procedure-pass.jsonl",
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("procedure_eval=passed", proc.stdout)

    def test_codex_adapter_transcript_satisfies_non_claude_spec_plan_gate(self):
        proc = subprocess.run(
            [
                sys.executable,
                "scripts/run_procedure_eval.py",
                "--eval-set",
                "tests/skills/procedure/agentic-sdlc-pipeline.json",
                "--transcript",
                "tests/fixtures/transcripts/agentic-sdlc-pipeline-procedure-codex-adapter-pass.jsonl",
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("procedure_eval=passed", proc.stdout)

    def test_runtime_error_transcript_fails_even_with_required_calls(self):
        proc = subprocess.run(
            [
                sys.executable,
                "scripts/run_procedure_eval.py",
                "--eval-set",
                "tests/skills/procedure/agentic-sdlc-pipeline.json",
                "--transcript",
                "tests/fixtures/transcripts/agentic-sdlc-pipeline-procedure-runtime-error.jsonl",
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("runtime_error:error_max_budget_usd", proc.stdout)
        self.assertIn("procedure_eval=failed", proc.stdout)

    def test_permission_denial_transcript_fails_even_with_required_calls(self):
        proc = subprocess.run(
            [
                sys.executable,
                "scripts/run_procedure_eval.py",
                "--eval-set",
                "tests/skills/procedure/agentic-sdlc-pipeline.json",
                "--transcript",
                "tests/fixtures/transcripts/agentic-sdlc-pipeline-procedure-permission-denied.jsonl",
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("permission_denied:Bash", proc.stdout)
        self.assertIn("procedure_eval=failed", proc.stdout)

    def test_agent_dispatch_satisfies_mapped_gate_skill(self):
        # A gate delegated to its specialist agent counts as satisfied (delegation path).
        trace = procedure_eval.Trace()
        procedure_eval._record_tool(
            trace, "Agent", {"subagent_type": "agentic-sdlc:security-reviewer", "description": "review the diff"}
        )
        procedure_eval._record_tool(
            trace, "Agent", {"subagent_type": "agentic-sdlc:implementation-auditor", "description": "audit flow"}
        )
        self.assertTrue(procedure_eval.required_skill_satisfied(trace, "agentic-sdlc:security-audit"))
        self.assertTrue(procedure_eval.required_skill_satisfied(trace, "agentic-sdlc:implementasyon-control"))

    def test_unmapped_gate_skill_not_satisfied_by_agent(self):
        # A skill with no agent equivalent still requires an actual Skill call.
        trace = procedure_eval.Trace()
        procedure_eval._record_tool(trace, "Agent", {"subagent_type": "agentic-sdlc:security-reviewer"})
        self.assertFalse(procedure_eval.required_skill_satisfied(trace, "agentic-sdlc:completion-claim-gate"))
        # And the direct Skill call still satisfies it.
        procedure_eval._record_tool(trace, "Skill", {"skill": "agentic-sdlc:completion-claim-gate"})
        self.assertTrue(procedure_eval.required_skill_satisfied(trace, "agentic-sdlc:completion-claim-gate"))

    def test_dispatch_strategy_satisfied_by_delegation(self):
        # Dispatching a sub-agent IS the mechanism decision dispatch-strategy makes.
        trace = procedure_eval.Trace()
        procedure_eval._record_tool(trace, "Agent", {"subagent_type": "Explore", "description": "scan"})
        self.assertTrue(procedure_eval.required_skill_satisfied(trace, "agentic-sdlc:dispatch-strategy"))

    def test_dispatch_strategy_not_satisfied_without_delegation(self):
        # All-inline work with no dispatch and no Skill call still fails the gate.
        trace = procedure_eval.Trace()
        procedure_eval._record_tool(trace, "Read", {"file_path": "greeting.py"})
        procedure_eval._record_tool(trace, "Workflow", {"name": "agentic-sdlc:spec-plan-draft"})
        self.assertFalse(procedure_eval.required_skill_satisfied(trace, "agentic-sdlc:dispatch-strategy"))
        procedure_eval._record_tool(trace, "Skill", {"skill": "agentic-sdlc:dispatch-strategy"})
        self.assertTrue(procedure_eval.required_skill_satisfied(trace, "agentic-sdlc:dispatch-strategy"))

    def test_pipeline_case_fails_when_relevant_core_workflow_skill_is_missing(self):
        case = procedure_eval.load_eval(REPO / "tests/skills/procedure/agentic-sdlc-pipeline.json")[0]
        trace = procedure_eval.Trace()
        procedure_eval._record_tool(trace, "Skill", {"skill": "agentic-sdlc:dispatch-strategy"})
        procedure_eval._record_tool(trace, "Workflow", {"name": "agentic-sdlc:spec-plan-draft"})
        procedure_eval._record_tool(
            trace,
            "shell_command",
            {"command": "python ${PLUGIN_ROOT}/scripts/detect_context.py --path ."},
        )
        procedure_eval._record_tool(trace, "write_file", {"file_path": "docs/specs/greeting-suffix.md"})
        procedure_eval._record_tool(
            trace,
            "shell_command",
            {"command": "python ${PLUGIN_ROOT}/scripts/validate_artifacts.py --mode spec --file docs/specs/greeting-suffix.md"},
        )
        procedure_eval._record_tool(trace, "write_file", {"file_path": "docs/plans/greeting-suffix.md"})
        procedure_eval._record_tool(
            trace,
            "shell_command",
            {"command": "python ${PLUGIN_ROOT}/scripts/validate_artifacts.py --mode plan --file docs/plans/greeting-suffix.md --spec docs/specs/greeting-suffix.md --strict"},
        )
        procedure_eval._record_tool(trace, "Skill", {"skill": "agentic-sdlc:security-audit"})
        procedure_eval._record_tool(trace, "Skill", {"skill": "agentic-sdlc:implementasyon-control"})
        procedure_eval._record_tool(trace, "Skill", {"skill": "agentic-sdlc:completion-claim-gate"})

        errors = procedure_eval.evaluate_case(case, trace, REPO)

        self.assertIn("missing_skill:agentic-sdlc:feature-build", errors)
        self.assertNotIn("missing_skill:agentic-sdlc:security-audit", errors)
        self.assertNotIn("missing_workflow:agentic-sdlc:spec-plan-draft", errors)

    def test_live_fixture_has_baseline_commit_before_claude_runs(self):
        case = {
            "id": "agentic-sdlc-pipeline-feature-no-commit",
            "fixture_dir": "tests/fixtures/agentic-sdlc-pipeline-basic",
        }
        with tempfile.TemporaryDirectory() as td:
            cwd = procedure_eval.copy_fixture(case, Path(td))
            proc = subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD"],
                cwd=cwd,
                capture_output=True,
                text=True,
            )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
