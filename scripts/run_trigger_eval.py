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
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path


def read_skill(skill_path):
    sk = Path(skill_path) / "SKILL.md"
    text = sk.read_text(encoding="utf-8")
    name = re.search(r"(?m)^name:\s*(.+)$", text)
    desc = re.search(r"(?m)^description:\s*(.+)$", text)
    return (name.group(1).strip() if name else Path(skill_path).name,
            desc.group(1).strip() if desc else "")


def matches_trigger(value, clean_name, skill_name):
    value = value or ""
    return clean_name in value or skill_name in value


def is_target_skill_read(value, skill_name):
    value = (value or "").replace("\\", "/")
    return f"skills/{skill_name}/SKILL.md" in value


def is_allowed_prelude_read(value, clean_name):
    value = (value or "").replace("\\", "/")
    return (
        value.endswith("/memory/MEMORY.md")
        or f"commands/{clean_name}.md" in value
    )


def detect_trigger(lines, clean_name, skill_name):
    """Replay run_eval's stream state machine over the full output (no select)."""
    pending = None
    acc = ""
    skipping_prelude_result = False
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
                    if pending == "Skill" and matches_trigger(acc, clean_name, skill_name):
                        return True
                    if pending == "Read" and is_target_skill_read(acc, skill_name):
                        return True
            elif st in ("content_block_stop", "message_stop"):
                if pending:
                    if pending == "Skill":
                        return matches_trigger(acc, clean_name, skill_name)
                    if pending == "Read":
                        if is_target_skill_read(acc, skill_name):
                            return True
                        if is_allowed_prelude_read(acc, clean_name):
                            pending, acc = None, ""
                            skipping_prelude_result = True
                            continue
                        return False
                if skipping_prelude_result and st == "message_stop":
                    continue
                if st == "message_stop":
                    return False
        elif t == "assistant":
            for ci in event.get("message", {}).get("content", []):
                if ci.get("type") != "tool_use":
                    continue
                nm, inp = ci.get("name", ""), ci.get("input", {})
                if nm == "Skill" and matches_trigger(inp.get("skill", ""), clean_name, skill_name):
                    return True
                if nm == "Read":
                    path = inp.get("file_path", "")
                    if is_target_skill_read(path, skill_name):
                        return True
                    if is_allowed_prelude_read(path, clean_name):
                        skipping_prelude_result = True
                        continue
                return False  # first tool action wasn't this skill
        elif t == "result":
            if skipping_prelude_result:
                skipping_prelude_result = False
                continue
            return False
    return False


class TriggerDetector:
    def __init__(self, clean_name, skill_name):
        self.clean_name = clean_name
        self.skill_name = skill_name
        self.pending = None
        self.acc = ""
        self.skipping_prelude_result = False

    def matches(self, value):
        return matches_trigger(value, self.clean_name, self.skill_name)

    def is_target_skill_read(self, value):
        return is_target_skill_read(value, self.skill_name)

    def is_allowed_prelude_read(self, value):
        return is_allowed_prelude_read(value, self.clean_name)

    def feed(self, line):
        line = line.strip()
        if not line:
            return None
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return None
        t = event.get("type")
        if t == "stream_event":
            se = event.get("event", {})
            st = se.get("type", "")
            if st == "content_block_start":
                cb = se.get("content_block", {})
                if cb.get("type") == "tool_use":
                    nm = cb.get("name", "")
                    if nm in ("Skill", "Read"):
                        self.pending, self.acc = nm, ""
                    else:
                        return False
            elif st == "content_block_delta" and self.pending:
                d = se.get("delta", {})
                if d.get("type") == "input_json_delta":
                    self.acc += d.get("partial_json", "")
                    if self.pending == "Skill" and self.matches(self.acc):
                        return True
                    if self.pending == "Read" and self.is_target_skill_read(self.acc):
                        return True
            elif st in ("content_block_stop", "message_stop"):
                if self.pending:
                    if self.pending == "Skill":
                        return self.matches(self.acc)
                    if self.pending == "Read":
                        if self.is_target_skill_read(self.acc):
                            return True
                        if self.is_allowed_prelude_read(self.acc):
                            self.pending, self.acc = None, ""
                            self.skipping_prelude_result = True
                            return None
                        return False
                if self.skipping_prelude_result and st == "message_stop":
                    return None
                if st == "message_stop":
                    return False
        elif t == "assistant":
            for ci in event.get("message", {}).get("content", []):
                if ci.get("type") != "tool_use":
                    continue
                nm, inp = ci.get("name", ""), ci.get("input", {})
                if nm == "Skill" and self.matches(inp.get("skill", "")):
                    return True
                if nm == "Read":
                    path = inp.get("file_path", "")
                    if self.is_target_skill_read(path):
                        return True
                    if self.is_allowed_prelude_read(path):
                        self.skipping_prelude_result = True
                        continue
                return False
        elif t == "result":
            if self.skipping_prelude_result:
                self.skipping_prelude_result = False
                return None
            return False
        return None


def kill_process_tree(proc):
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        proc.kill()


def run_streaming(cmd, project_root, env, timeout, detector, transcript_path=None):
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    proc = subprocess.Popen(
        cmd,
        cwd=project_root,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    deadline = time.monotonic() + timeout
    lines = queue.Queue()

    def read_stdout():
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.put(line)

    reader = threading.Thread(target=read_stdout, daemon=True)
    reader.start()
    transcript = None
    if transcript_path:
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript = transcript_path.open("w", encoding="utf-8")
    try:
        while True:
            if time.monotonic() > deadline:
                kill_process_tree(proc)
                return False
            try:
                line = lines.get(timeout=0.1)
            except queue.Empty:
                if proc.poll() is not None:
                    return False
                continue
            if transcript:
                transcript.write(line)
                transcript.flush()
            decision = detector.feed(line)
            if decision is not None:
                kill_process_tree(proc)
                return decision
    finally:
        if transcript:
            transcript.close()
        kill_process_tree(proc)


def run_once(query, skill_name, skill_desc, project_root, timeout, model, max_budget_usd, plugin_dir, transcript_dir, bare, command_shim):
    uid = uuid.uuid4().hex[:8]
    clean = f"{skill_name}-skill-{uid}" if command_shim else f"{skill_name}-live-{uid}"
    cf = None
    if command_shim:
        cdir = Path(project_root) / "commands"
        cdir.mkdir(parents=True, exist_ok=True)
        cf = cdir / f"{clean}.md"
        indented = "\n  ".join(skill_desc.split("\n"))
        cf.write_text(f"---\ndescription: |\n  {indented}\n---\n\n# {skill_name}\n\nThis skill handles: {skill_desc}\n", encoding="utf-8")
    try:
        cmd = [
            "claude", "-p", query,
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--no-session-persistence",
            "--permission-mode", "dontAsk",
        ]
        if bare:
            cmd += ["--bare"]
        if model:
            cmd += ["--model", model]
        if max_budget_usd:
            cmd += ["--max-budget-usd", str(max_budget_usd)]
        if plugin_dir:
            cmd += ["--plugin-dir", str(plugin_dir)]
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        transcript_path = None
        if transcript_dir:
            transcript_path = Path(transcript_dir) / f"{clean}.jsonl"
        return run_streaming(cmd, project_root, env, timeout, TriggerDetector(clean, skill_name), transcript_path)
    finally:
        if cf and cf.exists():
            cf.unlink()


def main(argv=None):
    p = argparse.ArgumentParser(description="Windows-safe triggering eval (no select.select).")
    p.add_argument("--skill-path", required=True)
    p.add_argument("--eval-set", required=True)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--threshold", type=float, default=0.5)
    p.add_argument("--timeout", type=int, default=180)
    p.add_argument("--model", default=None)
    p.add_argument("--max-budget-usd", default=None)
    p.add_argument("--query-limit", type=int, default=0)
    p.add_argument("--smoke", action="store_true", help="Run one query once with safe cleanup.")
    p.add_argument("--plugin-dir", default=None)
    p.add_argument("--transcript-dir", default=None)
    p.add_argument("--bare", action="store_true", help="Run Claude Code in bare mode to isolate plugin trigger behavior from project context; requires ANTHROPIC_API_KEY or apiKeyHelper auth.")
    p.add_argument("--no-command-shim", action="store_true", help="Do not plant commands/<skill>-skill-*.md; use real plugin skills only. Prefer with --plugin-dir when testing this repo's installed plugin.")
    p.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]))
    args = p.parse_args(argv)

    skill_name, skill_desc = read_skill(args.skill_path)
    queries = json.loads(Path(args.eval_set).read_text(encoding="utf-8"))["queries"]
    if args.smoke:
        args.runs = 1
        args.query_limit = args.query_limit or 1
        args.timeout = min(args.timeout, 90)
    if args.query_limit:
        queries = queries[:args.query_limit]

    errors, fields = [], {"skill": skill_name, "runs_per_query": args.runs}
    passed = 0
    for i, q in enumerate(queries):
        triggers = sum(run_once(q["query"], skill_name, skill_desc, args.project_root, args.timeout, args.model, args.max_budget_usd, args.plugin_dir, args.transcript_dir, args.bare, not args.no_command_shim)
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
