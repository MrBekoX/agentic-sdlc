"""Run or validate Claude behavior eval fixtures.

This is the procedure layer above trigger evals. It can run `claude -p` when the
CLI is available, but also supports `--dry-run` so CI can validate fixture shape
without requiring a live model.

Eval-set JSON:
{
  "cases": [
    {
      "id": "short-id",
      "prompt": "user prompt",
      "required_patterns": ["regex"],
      "forbidden_patterns": ["regex"]
    }
  ]
}
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def load_eval(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("eval set must contain non-empty 'cases'")
    for case in cases:
        for key in ("id", "prompt"):
            if not isinstance(case.get(key), str) or not case[key].strip():
                raise ValueError(f"case missing string '{key}': {case!r}")
        for key in ("required_patterns", "forbidden_patterns"):
            values = case.get(key, [])
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                raise ValueError(f"case {case['id']} has invalid {key}")
            for pattern in values:
                re.compile(pattern)
    return cases


def run_claude(prompt: str, cwd: Path, timeout: int, model: str | None) -> str:
    cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose"]
    if model:
        cmd += ["--model", model]
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    return (proc.stdout or "") + "\n" + (proc.stderr or "")


def check_case(case: dict, transcript: str) -> list[str]:
    errors = []
    for pattern in case.get("required_patterns", []):
        if not re.search(pattern, transcript, re.IGNORECASE | re.MULTILINE):
            errors.append(f"{case['id']}:missing:{pattern}")
    for pattern in case.get("forbidden_patterns", []):
        if re.search(pattern, transcript, re.IGNORECASE | re.MULTILINE):
            errors.append(f"{case['id']}:forbidden:{pattern}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-set", required=True, type=Path)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--model")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-missing-claude", action="store_true")
    args = parser.parse_args(argv)

    try:
        cases = load_eval(args.eval_set)
    except (OSError, ValueError, json.JSONDecodeError, re.error) as exc:
        print(f"error={type(exc).__name__}:{exc}")
        print("behavior_eval=failed")
        return 1

    if args.dry_run:
        print(f"cases={len(cases)}")
        print("behavior_eval=dry-run-passed")
        return 0

    if shutil.which("claude") is None:
        print("claude=missing")
        print("behavior_eval=skipped" if args.allow_missing_claude else "behavior_eval=failed")
        return 0 if args.allow_missing_claude else 2

    errors = []
    for case in cases:
        transcript = run_claude(case["prompt"], args.project_root, args.timeout, args.model)
        errors.extend(check_case(case, transcript))
    for err in errors:
        print(f"error={err}")
    print(f"cases={len(cases)}")
    print("behavior_eval=failed" if errors else "behavior_eval=passed")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
