import re
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
CI = REPO / ".github" / "workflows" / "ci.yml"


class TestCiPolicy(unittest.TestCase):
    def test_ci_is_validation_only_and_read_only(self):
        text = CI.read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^permissions:\s*\n\s+contents:\s*read\s*$")
        forbidden = [
            r"\bgh\s+release\b",
            r"\bnpm\s+publish\b",
            r"\bgit\s+push\b",
            r"\bplugin\s+publish\b",
            r"\bclaude\b.*\bpublish\b",
        ]
        run_lines = "\n".join(
            line.strip()
            for line in text.splitlines()
            if re.match(r"^\s*run:\s*", line)
        )
        for pattern in forbidden:
            self.assertNotRegex(run_lines, pattern)
