import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


class TestTaskBriefScript(unittest.TestCase):
    def test_extracts_task_to_handoff_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan = root / "plan.md"
            plan.write_text(
                "# Plan\n\nTask 1: First thing\n\nDo A.\n\nTask 2: Second thing\n\nDo B.\n",
                encoding="utf-8",
            )
            proc = subprocess.run(
                [sys.executable, str(REPO / "scripts" / "task_brief.py"), str(plan), "2"],
                cwd=REPO,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            out = Path(proc.stdout.strip())
            self.assertTrue(out.exists())
            text = out.read_text(encoding="utf-8")
            self.assertIn("Task 2: Second thing", text)
            self.assertNotIn("Task 1: First thing", text)
