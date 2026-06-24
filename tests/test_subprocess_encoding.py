"""Guard: text-mode subprocess decoding across tests AND scripts must be UTF-8.

Why this exists (the platform blind spot it closes): `subprocess.run/Popen(..., text=True)`
without an explicit `encoding` decodes the child's stdout/stderr with the PLATFORM LOCALE
codec — cp1254 on a Turkish Windows, cp1252 elsewhere, UTF-8 on Linux. Our tools both emit
and consume non-ASCII (status emojis in hook output; commit messages / diffs / file bodies in
the eval and review scripts), so a call that works on a UTF-8 Linux box can raise
`UnicodeDecodeError` on Windows. That makes behaviour — and the gate's verdict — depend on
the OS it ran on (e.g. green on WSL, red on Windows).

Forcing `encoding="utf-8"` on every text-mode subprocess call (tests AND production scripts)
keeps behaviour identical on Linux, macOS, and Windows.
"""
import ast
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCANNED_ROOTS = ("tests", "scripts")
# Calls that DECODE child output when in text mode.
_DECODING_CALLS = {"run", "Popen", "check_output"}


def _text_mode_without_encoding(path: Path) -> list[int]:
    """Line numbers of subprocess.{run,Popen,check_output} calls that decode in text mode
    (text=True / universal_newlines=True) but set no explicit encoding."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        is_subprocess = (
            isinstance(fn, ast.Attribute)
            and fn.attr in _DECODING_CALLS
            and isinstance(fn.value, ast.Name)
            and fn.value.id == "subprocess"
        )
        if not is_subprocess:
            continue
        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}

        def _is_true(name: str) -> bool:
            v = kwargs.get(name)
            return isinstance(v, ast.Constant) and v.value is True

        if (_is_true("text") or _is_true("universal_newlines")) and "encoding" not in kwargs:
            offenders.append(node.lineno)
    return offenders


class TestSubprocessUtf8(unittest.TestCase):
    def test_text_mode_subprocess_calls_set_utf8(self):
        offenders = {}
        for root in SCANNED_ROOTS:
            for path in sorted((REPO / root).rglob("*.py")):
                bad = _text_mode_without_encoding(path)
                if bad:
                    offenders[path.relative_to(REPO).as_posix()] = bad
        self.assertEqual(
            offenders,
            {},
            "subprocess text-mode call without encoding='utf-8' decodes with the platform "
            "locale codec and breaks on non-ASCII output (UnicodeDecodeError on Windows cp1254). "
            f"Add encoding='utf-8' to: {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
