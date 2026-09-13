"""Fail-closed adapter to the hook layer's canonical high-confidence secret redactor."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
REDACTOR = REPO / "hooks" / "redact-sensitive.mjs"


def _redact(text: str, *, structured: bool = False) -> str:
    node = shutil.which("node")
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
