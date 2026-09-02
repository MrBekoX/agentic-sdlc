"""Extract a numbered task from a plan into a handoff file.

The output file is meant for subagent dispatch prompts: the task brief is the
single source of requirements, so the controller does not paste a large plan into
conversation context repeatedly.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    from scripts.sensitive_redaction import redact_text
except ModuleNotFoundError:
    from sensitive_redaction import redact_text


def extract_task(text: str, number: int) -> str:
    start_re = re.compile(rf"(?m)^(?:#{1,6}\s*)?(?:Task|Görev|Gorev)\s+{number}\b[:.\-\s]*(.*)$")
    any_task_re = re.compile(r"(?m)^(?:#{1,6}\s*)?(?:Task|Görev|Gorev)\s+\d+\b")
    start = start_re.search(text)
    if not start:
        raise ValueError(f"task {number} not found")
    next_match = any_task_re.search(text, start.end())
    end = next_match.start() if next_match else len(text)
    return text[start.start():end].strip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan_file", type=Path)
    parser.add_argument("task_number", type=int)
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args(argv)

    plan = args.plan_file.resolve()
    if not plan.exists():
        print(f"error=plan_file_missing:{plan}")
        return 2
    try:
        task = extract_task(plan.read_text(encoding="utf-8"), args.task_number)
    except ValueError as exc:
        print(f"error={exc}")
        return 1

    out_dir = (args.out_dir or plan.parent / ".handoffs").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out = out_dir / f"task-{args.task_number}-brief-{stamp}.md"
    try:
        source = plan.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        source = plan.name
    brief = f"# Task {args.task_number} Brief\n\nSource plan: `{source}`\n\n{task}"
    try:
        out.write_text(redact_text(brief), encoding="utf-8")
    except RuntimeError as exc:
        print(f"error={exc}")
        return 1
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
