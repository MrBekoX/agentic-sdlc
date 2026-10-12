"""Windows-safe triggering eval (description-optimization harness).

Why this exists: skill-creator's `run_eval.py` is the triggering/description-optimization harness,
but it is broken on Windows — at `run_eval.py:108` it calls `select.select([process.stdout], ...)`,
and Windows `select` accepts only sockets (not pipe handles) -> `OSError WinError 10038`. This is a
faithful drop-in: same command-file planting and same stream-json trigger-detection state machine,
but it reads the subprocess output with `subprocess.run(capture_output=True, timeout=...)` (which
drains pipes via threads on Windows) instead of `select` — so it runs everywhere.

For each query it plants a `.claude/commands/<skill>-skill-<uuid>.md` (so the description under test
appears in available skills), runs `claude -p <query> --output-format stream-json --verbose
--include-partial-messages`, and detects whether the FIRST tool action is a Skill/Read invocation of
this skill (matched by the unique command name OR the real skill name, so a registered skill counts).
`--bare` is rejected (exit 2): since 2.1.286 bare mode sends no system reminders, so triggering
cannot be measured. `--plugin-dir` disables the shim so it does not duplicate the installed plugin.

Usage:
  python run_trigger_eval.py --skill-path <dir> --eval-set <json> [--runs N] [--threshold 0.5] [--model M]
eval-set JSON: {"queries": [{"query": "...", "should_trigger": true}, ...]}
Output: sorted key=value lines + trigger_eval=passed|failed|unmeasured.
Exit 0 passed; 1 a measured query missed its expectation; 2 --bare rejected; 3 some run produced no
measurement (CLI missing or failed, timeout, error result) and no measured query failed. A run that
produced no measurement is never counted as "the skill did not trigger".
"""
import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading
import tempfile
import time
import uuid
from pathlib import Path

try:
    from scripts.eval_safety import require_slug, resolve_under
    from scripts.sensitive_redaction import redact_text
except ModuleNotFoundError:  # direct `python3 scripts/...` execution
    from eval_safety import require_slug, resolve_under
    from sensitive_redaction import redact_text


EXIT_UNMEASURED = 3


class UnmeasuredRun(Exception):
    """A live run that yielded no trigger measurement, as opposed to "the skill did not trigger"."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def result_is_error(line):
    """True for a stream-json `result` event the CLI flagged as an error (no model answer to judge)."""
    try:
        event = json.loads(line)
    except (TypeError, ValueError):
        return False
    return isinstance(event, dict) and event.get("type") == "result" and event.get("is_error") is True


def read_skill(skill_path):
    sk = Path(skill_path) / "SKILL.md"
    text = sk.read_text(encoding="utf-8")
    name = re.search(r"(?m)^name:\s*(.+)$", text)
    desc = re.search(r"(?m)^description:\s*(.+)$", text)
    skill_name = name.group(1).strip() if name else Path(skill_path).name
    return (require_slug(skill_name, "skill name"),
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
    """Return True/False once the detector decides; raise UnmeasuredRun when no decision can be made.

    "The skill did not trigger" is a measurement (the model answered, or took another action first).
    A missing CLI, a non-zero exit, an error result, a timeout or an empty stream is NOT: counting it
    as False made a negative query pass whenever the CLI failed."""
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    try:
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
    except OSError as exc:
        reason = "claude_missing" if isinstance(exc, FileNotFoundError) else "spawn_failed"
        raise UnmeasuredRun(reason) from exc
    deadline = time.monotonic() + timeout
    lines = queue.Queue()

    def read_stdout():
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.put(line)

    reader = threading.Thread(target=read_stdout, daemon=True)
    reader.start()
    captured = []
    if transcript_path:
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
    received = 0
    try:
        while True:
            if time.monotonic() > deadline:
                kill_process_tree(proc)
                raise UnmeasuredRun("timeout")
            try:
                line = lines.get(timeout=0.1)
            except queue.Empty:
                exit_code = proc.poll()
                if exit_code is None:
                    continue
                # The child has exited: let the reader thread hand over what is still buffered
                # before deciding that nothing else is coming.
                reader.join(timeout=2)
                if not lines.empty():
                    continue
                if exit_code != 0:
                    raise UnmeasuredRun(f"exit_{exit_code}")
                if received == 0:
                    raise UnmeasuredRun("no_output")
                # A finished run ends with a `result` event (the detector decides on it) or with a
                # decision made earlier; a stream that just stops has no verdict to trust.
                raise UnmeasuredRun("no_decision")
            received += 1
            if transcript_path:
                captured.append(line)
            if result_is_error(line):
                kill_process_tree(proc)
                raise UnmeasuredRun("result_error")
            decision = detector.feed(line)
            if decision is not None:
                kill_process_tree(proc)
                return decision
    finally:
        if transcript_path:
            transcript_path.write_text(redact_text("".join(captured)), encoding="utf-8")
        kill_process_tree(proc)


def run_once(query, skill_name, skill_desc, project_root, timeout, model, max_budget_usd, plugin_dir, transcript_dir, bare, command_shim):
    uid = uuid.uuid4().hex[:8]
    clean = f"{skill_name}-skill-{uid}" if command_shim else f"{skill_name}-live-{uid}"
    cf = None
    created_dirs = []
    if command_shim:
        claude_dir = Path(project_root) / ".claude"
        cdir = claude_dir / "commands"
        if not claude_dir.exists():
            created_dirs.append(claude_dir)
        if not cdir.exists():
            created_dirs.append(cdir)
        cdir.mkdir(parents=True, exist_ok=True)
        cf = resolve_under(cdir, f"{clean}.md", "command shim")
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
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_SIMPLE")}
        transcript_path = None
        if transcript_dir:
            transcript_path = resolve_under(Path(transcript_dir), f"{clean}.jsonl", "transcript filename")
        return run_streaming(cmd, project_root, env, timeout, TriggerDetector(clean, skill_name), transcript_path)
    finally:
        if cf and cf.exists():
            cf.unlink()
        for directory in reversed(created_dirs):
            try:
                directory.rmdir()
            except OSError:
                pass


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
    p.add_argument("--bare", action="store_true", help="Rejected: since 2.1.286 bare mode sends no system reminders, so skill triggering cannot be measured. Exits 2 without spawning claude.")
    p.add_argument("--no-command-shim", action="store_true", help="Do not plant .claude/commands/<skill>-skill-*.md; use real plugin skills only. Prefer with --plugin-dir when testing this repo's installed plugin.")
    p.add_argument("--project-root", type=Path)
    p.add_argument(
        "--allow-writable-project",
        action="store_true",
        help="Allow live Claude execution in an explicitly selected writable project root.",
    )
    args = p.parse_args(argv)

    skill_name, skill_desc = read_skill(args.skill_path)
    if args.bare:
        print("error=bare_rejected:since 2.1.286 bare mode sends no skill listing; triggering cannot be measured")
        print("trigger_eval=failed")
        return 2
    if args.project_root and not args.allow_writable_project:
        p.error("--project-root requires --allow-writable-project")
    if args.plugin_dir:
        args.plugin_dir = Path(args.plugin_dir).resolve()
    queries = json.loads(Path(args.eval_set).read_text(encoding="utf-8"))["queries"]
    if args.smoke:
        args.runs = 1
        args.query_limit = args.query_limit or 1
        args.timeout = min(args.timeout, 90)
    if args.query_limit:
        queries = queries[:args.query_limit]

    errors, fields = [], {"skill": skill_name, "runs_per_query": args.runs}
    use_shim = not args.no_command_shim and not args.plugin_dir
    if args.plugin_dir:
        fields["command_shim"] = "disabled:plugin-dir"
    passed = 0
    mismatches = 0
    unmeasured = 0
    with tempfile.TemporaryDirectory(prefix="agentic-sdlc-trigger-") as td:
        project_root = args.project_root.resolve() if args.project_root else Path(td)
        for i, q in enumerate(queries):
            triggers = 0
            reasons = []
            for _ in range(args.runs):
                try:
                    triggers += bool(run_once(q["query"], skill_name, skill_desc, project_root, args.timeout, args.model, args.max_budget_usd, args.plugin_dir, args.transcript_dir, False, use_shim))
                except UnmeasuredRun as exc:
                    reasons.append(exc.reason)
            should = str(q["should_trigger"]).lower()
            if reasons:
                # A rate over the runs that did measure would hide the ones that did not: the whole
                # query is reported as unmeasured, never as passed or failed.
                unmeasured += 1
                fields[f"q{i}_should={should}_rate"] = "unmeasured"
                errors.append(f"q{i}_unmeasured:runs={len(reasons)},reason={'+'.join(sorted(set(reasons)))}")
                continue
            rate = triggers / args.runs
            ok = (rate >= args.threshold) if q["should_trigger"] else (rate < args.threshold)
            fields[f"q{i}_should={should}_rate"] = f"{rate:.2f}"
            if ok:
                passed += 1
            else:
                mismatches += 1
                errors.append(f"q{i}_mismatch:should_trigger={q['should_trigger']},rate={rate:.2f}")
    fields["queries_passed"] = f"{passed}/{len(queries)}"
    if mismatches:
        fields["trigger_eval"] = "failed"
    elif unmeasured:
        fields["trigger_eval"] = "unmeasured"
    else:
        fields["trigger_eval"] = "passed"

    for line in sorted([f"{k}={v}" for k, v in fields.items()] + [f"error={e}" for e in errors]):
        print(line)
    if mismatches:
        return 1
    return EXIT_UNMEASURED if unmeasured else 0


if __name__ == "__main__":
    sys.exit(main())
