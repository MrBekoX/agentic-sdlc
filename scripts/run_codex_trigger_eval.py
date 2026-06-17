"""Run Codex route/trigger evals against local skill descriptions.

This is intentionally separate from run_trigger_eval.py. Claude Code exposes
Skill/Read tool events, so the Claude runner can inspect actual tool order.
Codex CLI does not expose a comparable Skill tool event in `codex exec --json`,
so this runner checks Codex's route decision as a compact classifier.

Eval-set JSON: {"queries": [{"query": "...", "should_trigger": true}, ...]}
Output: sorted key=value lines + codex_trigger_eval=passed|failed.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any


def split_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fields: dict[str, str] = {}
    for raw in text[3:end].splitlines():
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        fields[key.strip()] = value.strip().strip('"')
    return fields


def read_skill(skill_path: Path) -> tuple[str, str]:
    text = (skill_path / "SKILL.md").read_text(encoding="utf-8")
    fm = split_frontmatter(text)
    return fm.get("name", skill_path.name), fm.get("description", "")


def load_skills(skills_dir: Path) -> list[tuple[str, str]]:
    skills = []
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        name, desc = read_skill(skill_md.parent)
        if name and desc:
            skills.append((name, desc))
    return skills


def build_prompt(query: str, skills: list[tuple[str, str]]) -> str:
    skill_lines = "\n".join(f"- {name}: {desc}" for name, desc in skills)
    return (
        "Choose the smallest sufficient AGENTIC-SDLC skill for the user prompt.\n"
        "If the user explicitly names or asks to call/use one listed AGENTIC-SDLC skill, "
        "return that named skill unless the request is clearly impossible or contradictory.\n"
        "Return JSON only, with this exact shape: "
        '{"skill":"<one listed skill>","needs_dev_flow":true|false}.\n'
        "Set needs_dev_flow true only for end-to-end/full SDLC implementation.\n\n"
        f"Skills:\n{skill_lines}\n\n"
        f"User prompt:\n{query}\n"
    )


def kill_process_tree(proc: subprocess.Popen) -> None:
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


def extract_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    candidates = [text]
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def parse_codex_events(lines: list[str]) -> tuple[str | None, dict[str, Any]]:
    final_text = ""
    usage: dict[str, Any] = {}
    warning_count = 0
    for raw in lines:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            if raw.strip():
                warning_count += 1
            continue
        if event.get("type") == "item.completed":
            item = event.get("item", {})
            if item.get("type") == "agent_message":
                final_text = item.get("text", "") or final_text
            elif item.get("type") == "error":
                warning_count += 1
        elif event.get("type") == "turn.completed":
            usage = event.get("usage", {}) or {}
    parsed = extract_json_object(final_text)
    skill = None
    if parsed and isinstance(parsed.get("skill"), str):
        skill = parsed["skill"].strip()
    usage["warning_count"] = warning_count
    return skill, usage


def run_codex_once(prompt: str, project_root: Path, args: argparse.Namespace, transcript_path: Path | None) -> tuple[str | None, dict[str, Any], str | None]:
    codex = shutil.which("codex")
    if not codex:
        return None, {}, "codex_missing"
    cmd = [
        codex,
        "-a", "never",
        "exec",
        "--json",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "-m", args.model,
        "-c", f'model_reasoning_effort="{args.reasoning_effort}"',
        "-c", 'model_verbosity="low"',
        "-s", "read-only",
        "-C", str(project_root),
        "-",
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=project_root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    lines: queue.Queue[str] = queue.Queue()

    def read_stdout() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.put(line)

    reader = threading.Thread(target=read_stdout, daemon=True)
    reader.start()
    assert proc.stdin is not None
    proc.stdin.write(prompt)
    proc.stdin.close()

    captured: list[str] = []
    deadline = time.monotonic() + args.timeout
    try:
        while True:
            if time.monotonic() > deadline:
                kill_process_tree(proc)
                return None, {}, "timeout"
            try:
                line = lines.get(timeout=0.1)
            except queue.Empty:
                if proc.poll() is not None:
                    break
                continue
            captured.append(line)
    finally:
        kill_process_tree(proc)

    if transcript_path:
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text("".join(captured), encoding="utf-8")
    actual, usage = parse_codex_events(captured)
    return actual, usage, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Codex route/trigger eval runner.")
    parser.add_argument("--skill-path", required=True, type=Path)
    parser.add_argument("--eval-set", required=True, type=Path)
    parser.add_argument("--skills-dir", type=Path, default=Path(__file__).resolve().parents[1] / "skills")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--model", default="gpt-5.4-mini")
    parser.add_argument("--reasoning-effort", default="low")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--query-limit", type=int, default=0)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--transcript-dir", type=Path)
    args = parser.parse_args(argv)

    target_skill, _ = read_skill(args.skill_path)
    queries = json.loads(args.eval_set.read_text(encoding="utf-8"))["queries"]
    if args.smoke:
        args.runs = 1
        args.query_limit = args.query_limit or 1
        args.timeout = min(args.timeout, 90)
    if args.query_limit:
        queries = queries[:args.query_limit]
    skills = load_skills(args.skills_dir)

    fields: dict[str, Any] = {
        "runtime": "codex",
        "model": args.model,
        "skill": target_skill,
        "runs_per_query": args.runs,
        "semantics": "route-classifier",
    }
    errors: list[str] = []
    passed = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_reasoning_tokens = 0

    for i, query in enumerate(queries):
        matches = 0
        actuals = []
        for run_index in range(args.runs):
            prompt = build_prompt(query["query"], skills)
            transcript_path = None
            if args.transcript_dir:
                transcript_path = args.transcript_dir / f"{target_skill}-q{i}-run{run_index}.jsonl"
            actual, usage, error = run_codex_once(prompt, args.project_root, args, transcript_path)
            if error:
                errors.append(f"q{i}_{error}")
                continue
            actuals.append(actual or "")
            if actual == target_skill:
                matches += 1
            total_input_tokens += int(usage.get("input_tokens") or 0)
            total_output_tokens += int(usage.get("output_tokens") or 0)
            total_reasoning_tokens += int(usage.get("reasoning_output_tokens") or 0)
        rate = matches / args.runs
        ok = (rate >= args.threshold) if query["should_trigger"] else (rate < args.threshold)
        fields[f"q{i}_actual"] = ",".join(actuals)
        fields[f"q{i}_should={str(query['should_trigger']).lower()}_rate"] = f"{rate:.2f}"
        if ok:
            passed += 1
        else:
            errors.append(f"q{i}_mismatch:should_trigger={query['should_trigger']},rate={rate:.2f}")

    fields["queries_passed"] = f"{passed}/{len(queries)}"
    fields["input_tokens"] = total_input_tokens
    fields["output_tokens"] = total_output_tokens
    fields["reasoning_output_tokens"] = total_reasoning_tokens
    fields["codex_trigger_eval"] = "failed" if errors else "passed"

    for line in sorted([f"{key}={value}" for key, value in fields.items()] + [f"error={err}" for err in errors]):
        print(line)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
