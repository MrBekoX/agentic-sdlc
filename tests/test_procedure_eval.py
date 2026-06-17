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
                "tests/skills/procedure/dev-flow.json",
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
                "tests/skills/procedure/dev-flow.json",
                "--transcript",
                "tests/fixtures/transcripts/dev-flow-procedure-pass.jsonl",
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
                "tests/skills/procedure/dev-flow.json",
                "--transcript",
                "tests/fixtures/transcripts/dev-flow-procedure-runtime-error.jsonl",
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
                "tests/skills/procedure/dev-flow.json",
                "--transcript",
                "tests/fixtures/transcripts/dev-flow-procedure-permission-denied.jsonl",
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("permission_denied:Bash", proc.stdout)
        self.assertIn("procedure_eval=failed", proc.stdout)

    def test_live_fixture_has_baseline_commit_before_claude_runs(self):
        case = {
            "id": "dev-flow-feature-no-commit",
            "fixture_dir": "tests/fixtures/dev-flow-basic",
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
