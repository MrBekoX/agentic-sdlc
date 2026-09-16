"""Fail-closed adapter to the hook layer's canonical high-confidence secret redactor."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
REDACTOR = REPO / "hooks" / "redact-sensitive.mjs"


def _program_on_absolute_path(name: str) -> str | None:
    """D25 model (5): an absolute path found in an absolute PATH entry, or None.

    Relative entries and the win32 cwd-first lookup are never used. On win32 only
    <name>.exe and <name>.com are tried (PATHEXT is not consulted); elsewhere a
    candidate must be an executable regular file.
    """
    win = sys.platform == "win32"
    absolute = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\|//)" if win else r"/")
    names = (name + ".exe", name + ".com") if win else (name,)
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not absolute.match(entry):
            continue
        for candidate in names:
            full = os.path.join(entry, candidate)
            if os.path.isfile(full) and (win or os.access(full, os.X_OK)):
                return full
    return None


def _redact(text: str, *, structured: bool = False) -> str:
    node = _program_on_absolute_path("node")
    if not node:
        raise RuntimeError("node is required to redact persisted output")
    proc = subprocess.run(
        [node, str(REDACTOR), *(["--json"] if structured else [])],
        input=str(text),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError("secret redaction failed: " + (proc.stderr.strip() or "unknown error"))
    return proc.stdout


def redact_text(text: str) -> str:
    return _redact(text)


def redact_json(value):
    """Return JSON-safe redacted data, retaining credential field-name context."""
    return json.loads(_redact(json.dumps(value, ensure_ascii=False), structured=True))
