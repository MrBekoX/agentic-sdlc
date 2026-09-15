#!/usr/bin/env python3
"""Offline strict flow evidence for one Codex rollout (publication-readiness 0.4.3; AC43, AC44, AC119, AC120).

Usage: python3 scripts/strict_flow_evidence.py --rollout <rollout.jsonl> --cwd <repository dir>

Prints exactly three lines:
  strict_evidence=green|partial|missing
  strict_completion=satisfied|unsatisfied|n/a
  strict_branch=protected|ok|unknown
and exits 0 only for green evidence with a satisfied or n/a completion, otherwise 1. A preflight or
evaluation failure prints missing/unsatisfied/unknown, writes one fixed error code word to stderr and
exits 2. Output never carries paths, branch names or rollout bytes. The evaluation is
deriveStrictEvidence in hooks/codex-flow-evidence.mjs, run under node; the live hooks never call it.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENGINE = REPO / "hooks" / "codex-flow-evidence.mjs"
MAX_ROLLOUT_BYTES = 8 * 1024 * 1024  # the rollout readers' whole-file ceiling
NODE_TIMEOUT_SECONDS = 120
KEYS = ("evidence", "completion", "branch")
ALLOWED = {
    "evidence": {"green", "partial", "missing"},
    "completion": {"satisfied", "unsatisfied", "n/a"},
    "branch": {"protected", "ok", "unknown"},
}
ERROR_RESULT = {"evidence": "missing", "completion": "unsatisfied", "branch": "unknown"}
NODE_SCRIPT = ("const [rollout, cwd] = process.argv.slice(1);"
               "const m = await import(%s);"
               "process.stdout.write(JSON.stringify(m.deriveStrictEvidence(rollout, cwd)));")


class StrictEvidenceError(Exception):
    """Carries a fixed error code word only, never an input path or byte."""


def preflight(rollout: Path, cwd: Path) -> None:
    if not cwd.is_dir():
        raise StrictEvidenceError("cwd_invalid")
    try:
        if not rollout.is_file():
            raise StrictEvidenceError("rollout_invalid")
        if rollout.stat().st_size > MAX_ROLLOUT_BYTES:
            raise StrictEvidenceError("rollout_too_large")
        text = rollout.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise StrictEvidenceError("rollout_unreadable") from error
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError as error:
            raise StrictEvidenceError("rollout_malformed") from error
        if not isinstance(record, dict):
            raise StrictEvidenceError("rollout_malformed")


def evaluate(rollout: Path, cwd: Path) -> dict:
    node = shutil.which("node")
    if not node:
        raise StrictEvidenceError("node_missing")
    env = dict(os.environ, AGENTIC_SDLC_PYTHON=sys.executable)
    try:
        proc = subprocess.run(
            [node, "--input-type=module", "-e", NODE_SCRIPT % json.dumps(ENGINE.as_uri()), str(rollout), str(cwd)],
            capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_SECONDS, env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise StrictEvidenceError("node_failed") from error
    if proc.returncode != 0:
        raise StrictEvidenceError("node_failed")
    try:
        result = json.loads(proc.stdout)
    except ValueError as error:
        raise StrictEvidenceError("engine_output_invalid") from error
    if not isinstance(result, dict) or result.get("error") is True:
        raise StrictEvidenceError("engine_error")
    if any(result.get(key) not in ALLOWED[key] for key in KEYS):
        raise StrictEvidenceError("engine_output_invalid")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Offline strict flow evidence for one Codex rollout.")
    parser.add_argument("--rollout", required=True, help="Codex rollout JSONL file (at most 8 MiB)")
    parser.add_argument("--cwd", required=True, help="repository directory holding the spec/plan artifacts")
    args = parser.parse_args(argv)
    rollout, cwd = Path(args.rollout), Path(args.cwd)
    try:
        preflight(rollout, cwd)
        result = evaluate(rollout.resolve(), cwd.resolve())
        code = 0 if result["evidence"] == "green" and result["completion"] in ("satisfied", "n/a") else 1
    except StrictEvidenceError as error:
        result, code = ERROR_RESULT, 2
        print(error.args[0], file=sys.stderr)
    for key in KEYS:
        print(f"strict_{key}={result[key]}")
    return code


if __name__ == "__main__":
    sys.exit(main())
