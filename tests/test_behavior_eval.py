import subprocess
import sys
import unittest
from pathlib import Path


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
