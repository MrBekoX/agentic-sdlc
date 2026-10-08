"""Run or validate Claude behavior eval fixtures.

This is the procedure layer above trigger evals. It can run `claude -p` when the
CLI is available, but also supports `--dry-run` so local automation can validate fixture shape
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
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from scripts.eval_safety import require_slug
except ModuleNotFoundError:
    from eval_safety import require_slug


def load_eval(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("eval set must contain non-empty 'cases'")
    for case in cases:
        for key in ("id", "prompt"):
            if not isinstance(case.get(key), str) or not case[key].strip():
                raise ValueError(f"case missing string '{key}': {case!r}")
        require_slug(case["id"], "case id")
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
    env = {key: value for key, value in os.environ.items() if key != "CLAUDE_CODE_SIMPLE"}
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    return (proc.stdout or "") + "\n" + (proc.stderr or "")


def behavior_text(transcript: str) -> str:
    """Main-session assistant text and result.result only; system/init, stderr and subagents are ignored."""
    parts: list[str] = []
    for raw in transcript.split("\n"):
        raw = raw.strip()
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("parent_tool_use_id"):
            continue
        etype = event.get("type")
        if etype == "assistant":
            content = event.get("message", {}).get("content") if isinstance(event.get("message"), dict) else None
            for item in content if isinstance(content, list) else []:
                if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                    parts.append(item["text"])
        elif etype == "result" and isinstance(event.get("result"), str):
            parts.append(event["result"])
    return "\n".join(parts)


def check_case(case: dict, transcript: str) -> list[str]:
    errors = []
    text = behavior_text(transcript)
    for pattern in case.get("required_patterns", []):
        if not re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
            errors.append(f"{case['id']}:missing:{pattern}")
    for pattern in case.get("forbidden_patterns", []):
        if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
            errors.append(f"{case['id']}:forbidden:{pattern}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-set", required=True, type=Path)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--allow-writable-project", action="store_true")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--model")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-missing-claude", action="store_true")
    args = parser.parse_args(argv)

    if args.project_root and not args.allow_writable_project:
        parser.error("--project-root requires --allow-writable-project")

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
    with tempfile.TemporaryDirectory(prefix="agentic-sdlc-behavior-") as td:
        project_root = args.project_root.resolve() if args.project_root else Path(td)
        for case in cases:
            transcript = run_claude(case["prompt"], project_root, args.timeout, args.model)
            errors.extend(check_case(case, transcript))
    for err in errors:
        print(f"error={err}")
    print(f"cases={len(cases)}")
    print("behavior_eval=failed" if errors else "behavior_eval=passed")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
