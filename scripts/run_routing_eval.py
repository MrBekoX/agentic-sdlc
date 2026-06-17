"""Live routing eval for the using-agentic-sdlc meta-router.

Question: given a natural user prompt, does the router reach the correct *focused* skill — and do
the pipeline's feeder skills stay independently reachable (a narrow prompt must NOT escalate to
agentic-sdlc-pipeline)?

For each scenario {prompt, expected, escalation}, runs `claude -p <prompt>` with this plugin loaded
and records every Skill invocation (and Read of skills/<name>/SKILL.md) in the transcript. A scenario
PASSES when:
  - `expected` is among the routed skills, AND
  - unless `escalation` is true, `agentic-sdlc-pipeline` is NOT routed.
The router skill `using-agentic-sdlc` itself is ignored when collecting the focused route.

Windows-safe (no select); kills the process tree on timeout. Output: sorted key=value lines +
routing_eval=passed|failed; exit 1 if any scenario fails.
"""
from __future__ import annotations

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

ROUTER = "using-agentic-sdlc"


def collect_routes(lines: list[str]) -> list[str]:
    """Return focused skill names invoked via Skill, or Read of skills/<name>/SKILL.md (router excluded)."""
    routes: list[str] = []

    def add(name: str) -> None:
        name = (name or "").split(":")[-1].strip()
        if name and name != ROUTER and name not in routes:
            routes.append(name)

    skill_read = re.compile(r"skills[\\/]+([A-Za-z0-9-]+)[\\/]+SKILL\.md")
    acc: dict[int, dict] = {}
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        etype = event.get("type")
        if etype == "assistant":
            for item in event.get("message", {}).get("content", []):
                if item.get("type") != "tool_use":
                    continue
                if item.get("name") == "Skill":
                    add(item.get("input", {}).get("skill", ""))
                elif item.get("name") == "Read":
                    m = skill_read.search(str(item.get("input", {}).get("file_path", "")))
                    if m:
                        add(m.group(1))
        elif etype == "stream_event":
            se = event.get("event", {})
            st = se.get("type")
            idx = int(se.get("index", 0))
            if st == "content_block_start":
                cb = se.get("content_block", {})
                if cb.get("type") == "tool_use":
                    acc[idx] = {"name": cb.get("name", ""), "json": ""}
            elif st == "content_block_delta":
                d = se.get("delta", {})
                if d.get("type") == "input_json_delta" and idx in acc:
                    acc[idx]["json"] += d.get("partial_json", "")
            elif st == "content_block_stop" and idx in acc:
                pend = acc.pop(idx)
                try:
                    payload = json.loads(pend["json"] or "{}")
                except json.JSONDecodeError:
                    payload = {}
                if pend["name"] == "Skill":
                    add(payload.get("skill", ""))
                elif pend["name"] == "Read":
                    m = skill_read.search(str(payload.get("file_path", "")))
                    if m:
                        add(m.group(1))
    return routes


def kill_process_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        proc.kill()


def run_claude(prompt: str, args: argparse.Namespace, transcript_path: Path | None) -> list[str]:
    cmd = [
        "claude", "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--no-session-persistence",
        "--permission-mode", "dontAsk",
        "--plugin-dir", str(args.project_root),
    ]
    if args.model:
        cmd += ["--model", args.model]
    if args.max_turns:
        cmd += ["--max-turns", str(args.max_turns)]
    if args.max_budget_usd:
        cmd += ["--max-budget-usd", str(args.max_budget_usd)]
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    proc = subprocess.Popen(
        cmd, cwd=args.project_root, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", creationflags=creationflags,
    )
    lines: queue.Queue[str] = queue.Queue()

    def reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.put(line)

    threading.Thread(target=reader, daemon=True).start()
    captured: list[str] = []
    deadline = time.monotonic() + args.timeout
    try:
        while True:
            if time.monotonic() > deadline:
                kill_process_tree(proc)
                break
            try:
                captured.append(lines.get(timeout=0.1))
            except queue.Empty:
                if proc.poll() is not None:
                    break
    finally:
        kill_process_tree(proc)
    if transcript_path:
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text("".join(captured), encoding="utf-8")
    return captured


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Live using-agentic-sdlc routing eval.")
    p.add_argument("--eval-set", required=True, type=Path)
    p.add_argument("--model", default="haiku")
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--max-turns", type=int, default=3)
    p.add_argument("--max-budget-usd", default="0.15")
    p.add_argument("--scenario-limit", type=int, default=0)
    p.add_argument("--transcript-dir", type=Path)
    p.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = p.parse_args(argv)

    scenarios = json.loads(args.eval_set.read_text(encoding="utf-8"))["scenarios"]
    if args.scenario_limit:
        scenarios = scenarios[:args.scenario_limit]

    fields: dict[str, object] = {"runtime": "claude", "model": args.model, "router": ROUTER,
                                 "semantics": "live Skill routing"}
    errors: list[str] = []
    passed = 0
    for i, sc in enumerate(scenarios):
        expected = sc["expected"].split(":")[-1]
        escalation = bool(sc.get("escalation"))
        tpath = args.transcript_dir / f"scenario-{i}.jsonl" if args.transcript_dir else None
        routes = collect_routes(run_claude(sc["prompt"], args, tpath))
        expected_hit = expected in routes
        over_escalated = (not escalation) and ("agentic-sdlc-pipeline" in routes)
        ok = expected_hit and not over_escalated
        fields[f"q{i}_expected"] = expected
        fields[f"q{i}_routed"] = ",".join(routes) or "(none)"
        fields[f"q{i}_status"] = "passed" if ok else "failed"
        if ok:
            passed += 1
        else:
            reason = "no_expected" if not expected_hit else "over_escalated_to_pipeline"
            errors.append(f"q{i}_{reason}:expected={expected},routed={','.join(routes) or '(none)'}")

    fields["scenarios_passed"] = f"{passed}/{len(scenarios)}"
    fields["routing_eval"] = "failed" if errors else "passed"
    for line in sorted([f"{k}={v}" for k, v in fields.items()] + [f"error={e}" for e in errors]):
        print(line)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
