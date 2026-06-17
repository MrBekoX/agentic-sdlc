"""Windows-safe triggering eval (description-optimization harness).

Why this exists: skill-creator's `run_eval.py` is the triggering/description-optimization harness,
but it is broken on Windows — at `run_eval.py:108` it calls `select.select([process.stdout], ...)`,
and Windows `select` accepts only sockets (not pipe handles) -> `OSError WinError 10038`. This is a
faithful drop-in: same command-file planting and same stream-json trigger-detection state machine,
but it reads the subprocess output with `subprocess.run(capture_output=True, timeout=...)` (which
drains pipes via threads on Windows) instead of `select` — so it runs everywhere.

For each query it plants a `commands/<skill>-skill-<uuid>.md` (so the description under test
appears in available skills), runs `claude -p <query> --output-format stream-json --verbose
--include-partial-messages`, and detects whether the FIRST tool action is a Skill/Read invocation of
this skill (matched by the unique command name OR the real skill name, so a registered skill counts).

Usage:
  python run_trigger_eval.py --skill-path <dir> --eval-set <json> [--runs N] [--threshold 0.5] [--model M]
eval-set JSON: {"queries": [{"query": "...", "should_trigger": true}, ...]}
Output: sorted key=value lines + trigger_eval=passed|failed; exit 1 if any query fails.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path


def read_skill(skill_path):
    sk = Path(skill_path) / "SKILL.md"
    text = sk.read_text(encoding="utf-8")
    name = re.search(r"(?m)^name:\s*(.+)$", text)
    desc = re.search(r"(?m)^description:\s*(.+)$", text)
    return (name.group(1).strip() if name else Path(skill_path).name,
            desc.group(1).strip() if desc else "")


def detect_trigger(lines, clean_name, skill_name):
    """Replay run_eval's stream state machine over the full output (no select)."""
    def matches(s):
        return clean_name in (s or "") or skill_name in (s or "")
    pending = None
    acc = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = event.get("type")
        if t == "stream_event":
            se = event.get("event", {})
            st = se.get("type", "")
            if st == "content_block_start":
                cb = se.get("content_block", {})
                if cb.get("type") == "tool_use":
                    nm = cb.get("name", "")
                    if nm in ("Skill", "Read"):
                        pending, acc = nm, ""
                    else:
                        return False  # a different tool fired first
            elif st == "content_block_delta" and pending:
                d = se.get("delta", {})
                if d.get("type") == "input_json_delta":
                    acc += d.get("partial_json", "")
                    if matches(acc):
                        return True
            elif st in ("content_block_stop", "message_stop"):
                if pending:
                    return matches(acc)
                if st == "message_stop":
                    return False
        elif t == "assistant":
            for ci in event.get("message", {}).get("content", []):
                if ci.get("type") != "tool_use":
                    continue
                nm, inp = ci.get("name", ""), ci.get("input", {})
                if nm == "Skill" and matches(inp.get("skill", "")):
                    return True
                if nm == "Read" and matches(inp.get("file_path", "")):
                    return True
                return False  # first tool action wasn't this skill
        elif t == "result":
            return False
    return False


def run_once(query, skill_name, skill_desc, project_root, timeout, model):
    uid = uuid.uuid4().hex[:8]
    clean = f"{skill_name}-skill-{uid}"
    cdir = Path(project_root) / "commands"
    cdir.mkdir(parents=True, exist_ok=True)
    cf = cdir / f"{clean}.md"
    indented = "\n  ".join(skill_desc.split("\n"))
    cf.write_text(f"---\ndescription: |\n  {indented}\n---\n\n# {skill_name}\n\nThis skill handles: {skill_desc}\n", encoding="utf-8")
    try:
        cmd = ["claude", "-p", query, "--output-format", "stream-json", "--verbose", "--include-partial-messages"]
        if model:
            cmd += ["--model", model]
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        try:
            r = subprocess.run(cmd, cwd=project_root, env=env, stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
            return detect_trigger((r.stdout or "").splitlines(), clean, skill_name)
        except subprocess.TimeoutExpired:
            return False
    finally:
        if cf.exists():
            cf.unlink()


def main(argv=None):
    p = argparse.ArgumentParser(description="Windows-safe triggering eval (no select.select).")
    p.add_argument("--skill-path", required=True)
    p.add_argument("--eval-set", required=True)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--threshold", type=float, default=0.5)
    p.add_argument("--timeout", type=int, default=180)
    p.add_argument("--model", default=None)
    p.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]))
    args = p.parse_args(argv)

    skill_name, skill_desc = read_skill(args.skill_path)
    queries = json.loads(Path(args.eval_set).read_text(encoding="utf-8"))["queries"]

    errors, fields = [], {"skill": skill_name, "runs_per_query": args.runs}
    passed = 0
    for i, q in enumerate(queries):
        triggers = sum(run_once(q["query"], skill_name, skill_desc, args.project_root, args.timeout, args.model)
                       for _ in range(args.runs))
        rate = triggers / args.runs
        ok = (rate >= args.threshold) if q["should_trigger"] else (rate < args.threshold)
        fields[f"q{i}_should={str(q['should_trigger']).lower()}_rate"] = f"{rate:.2f}"
        if ok:
            passed += 1
        else:
            errors.append(f"q{i}_mismatch:should_trigger={q['should_trigger']},rate={rate:.2f}")
    fields["queries_passed"] = f"{passed}/{len(queries)}"
    fields["trigger_eval"] = "failed" if errors else "passed"

    for line in sorted([f"{k}={v}" for k, v in fields.items()] + [f"error={e}" for e in errors]):
        print(line)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
