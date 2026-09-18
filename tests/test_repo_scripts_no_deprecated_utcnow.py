"""No shipped Python script may call the deprecated datetime.utcnow() (removed in a future Python)."""

import ast
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT_DIRS = ("scripts", "hooks", "skills")


def utcnow_calls(path: Path) -> list[int]:
    """Line numbers of `datetime.utcnow()`-shaped calls in one module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "utcnow":
            found.append(node.lineno)
    return found


class TestNoDeprecatedUtcnow(unittest.TestCase):
    def test_no_shipped_script_calls_utcnow(self):
        offenders = {}
        for folder in SCRIPT_DIRS:
            for path in sorted((REPO / folder).rglob("*.py")):
                lines = utcnow_calls(path)
                if lines:
                    offenders[path.relative_to(REPO).as_posix()] = lines
        self.assertEqual(offenders, {}, "use datetime.now(timezone.utc); utcnow() is deprecated")
