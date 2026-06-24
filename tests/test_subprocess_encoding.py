"""Guard: subprocess text-mode decoding in the test suite must be UTF-8.

Why this exists (the verification blind spot it closes): `subprocess.run(..., text=True)`
without an explicit `encoding` decodes the child's stdout/stderr with the PLATFORM LOCALE
codec — cp1254 on a Turkish Windows, cp1252 elsewhere, UTF-8 on Linux. Our hooks/scripts
emit non-ASCII (e.g. the `⚠️`/`🛑`/`🔒` status emojis), so a test that passes on a
UTF-8 Linux box can raise `UnicodeDecodeError` on Windows — making the gate's verdict
depend on the platform it ran on. A green run on one OS then hides a real failure on another.

Forcing `encoding="utf-8"` on every text-mode subprocess call makes the gate locale-
independent: the same pass/fail verdict on Linux, macOS, and Windows.
"""
import ast
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent


def _text_mode_without_encoding(path: Path) -> list[int]:
    """Line numbers of subprocess.run(...) calls that decode in text mode but set no encoding."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        is_subprocess_run = (
            isinstance(fn, ast.Attribute)
            and fn.attr == "run"
            and isinstance(fn.value, ast.Name)
            and fn.value.id == "subprocess"
        )
        if not is_subprocess_run:
            continue
        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}

        def _is_true(name: str) -> bool:
            v = kwargs.get(name)
            return isinstance(v, ast.Constant) and v.value is True

        text_mode = _is_true("text") or _is_true("universal_newlines")
        if text_mode and "encoding" not in kwargs:
            offenders.append(node.lineno)
    return offenders


class TestSubprocessUtf8(unittest.TestCase):
    def test_text_mode_subprocess_calls_set_utf8(self):
        offenders = {}
        for path in sorted(TESTS_DIR.rglob("test_*.py")):
            bad = _text_mode_without_encoding(path)
            if bad:
                offenders[path.relative_to(TESTS_DIR).as_posix()] = bad
        self.assertEqual(
            offenders,
            {},
            "subprocess.run(text=True) without encoding='utf-8' decodes with the platform "
            "locale codec and breaks on our tools' non-ASCII output (UnicodeDecodeError on "
            f"Windows cp1254). Add encoding='utf-8' to: {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
