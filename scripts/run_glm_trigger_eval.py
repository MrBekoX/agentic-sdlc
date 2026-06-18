"""Run GLM route/trigger evals against local skill descriptions via opencode.

This is the opencode + Z.AI Coding Plan variant of run_codex_trigger_eval.py.
Claude Code exposes Skill/Read tool events; Codex/GLM do not, so this runner
checks the model's route decision as a compact classifier: it lists every
skill name+description, asks the model to pick the smallest sufficient one, and
compares the pick to the expected target.

Billing: calls go through `opencode run` which uses the Z.AI Coding Plan
credential (flat-rate, $0/token) — i.e. the plan quota, not a separate API key.

Isolation: opencode auto-loads AGENTS.md/CLAUDE.md from cwd, which would bias
routing. Each call therefore runs in a neutral temp cwd so only the prompt's
skill descriptions influence the classification.

Eval-set JSON: {"queries": [{"query": "...", "should_trigger": true}, ...]}
Output: sorted key=value lines + glm_trigger_eval=passed|failed.
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
import tempfile
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


def parse_opencode_events(lines: list[str]) -> tuple[str | None, dict[str, Any]]:
    """opencode --format json emits newline-delimited events.

    Model text is in {"type":"text","part":{"type":"text","text":"<...>"}}.
    Usage is in {"type":"step_finish","part":{"tokens":{"input":..,"output":..,"reasoning":..},"cost":..}}.
    """
    texts: list[str] = []
    usage: dict[str, Any] = {}
    warning_count = 0
    for raw in lines:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            if raw.strip():
                warning_count += 1
            continue
        etype = event.get("type")
        if etype == "text":
            part = event.get("part") or {}
            if isinstance(part.get("text"), str):
                texts.append(part["text"])
        elif etype == "step_finish":
            part = event.get("part") or {}
            tokens = part.get("tokens") or {}
            usage["input_tokens"] = tokens.get("input", 0)
            usage["output_tokens"] = tokens.get("output", 0)
            usage["reasoning_output_tokens"] = tokens.get("reasoning", 0)
            usage["cost"] = part.get("cost", 0)
        elif etype in ("error", "tool_call") or isinstance(event.get("error"), str):
            if etype in ("tool_call", "error"):
                warning_count += 1
    final_text = "".join(texts)
    parsed = extract_json_object(final_text)
    skill = None
    if parsed and isinstance(parsed.get("skill"), str):
        skill = parsed["skill"].strip()
    usage["warning_count"] = warning_count
    return skill, usage


def run_opencode_once(
    prompt: str, model: str, timeout: int, eval_cwd: Path, transcript_path: Path | None
) -> tuple[str | None, dict[str, Any], str | None]:
    opencode = shutil.which("opencode")
    if not opencode:
        return None, {}, "opencode_missing"
    # Prompt passed as a single argv element (no shell) so newlines/quotes are safe.
    cmd = [opencode, "run", prompt, "--model", model, "--format", "json"]
    proc = subprocess.Popen(
        cmd,
        cwd=str(eval_cwd),
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

    captured: list[str] = []
    deadline = time.monotonic() + timeout
    try:
        while True:
            if time.monotonic() > deadline:
                kill_process_tree(proc)
                return None, {}, "timeout"
            try:
                line = lines.get(timeout=0.2)
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
    actual, usage = parse_opencode_events(captured)
    return actual, usage, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GLM (opencode + Z.AI Coding Plan) route/trigger eval runner.")
    parser.add_argument("--skill-path", required=True, type=Path)
    parser.add_argument("--eval-set", required=True, type=Path)
    parser.add_argument("--skills-dir", type=Path, default=Path(__file__).resolve().parents[1] / "skills")
    parser.add_argument("--model", default="zai-coding-plan/glm-4.7")
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Runs per query for majority voting (rate = matches/runs vs --threshold). "
        "Default 1 (GLM calls are heavier); raise to 3 to measure flakiness.",
    )
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

    # Neutral cwd so opencode does NOT auto-load this project's AGENTS.md/CLAUDE.md
    # (which would bias routing). The classifier must see only the prompt's descriptions.
    eval_cwd = Path(tempfile.mkdtemp(prefix="glm-eval-"))

    fields: dict[str, Any] = {
        "runtime": "opencode-glm",
        "model": args.model,
        "skill": target_skill,
        "runs_per_query": args.runs,
        "semantics": "route-classifier",
        "billing": "zai-coding-plan",
    }
    errors: list[str] = []
    passed = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_reasoning_tokens = 0
    total_cost = 0.0

    for i, query in enumerate(queries):
        matches = 0
        actuals = []
        for run_index in range(args.runs):
            prompt = build_prompt(query["query"], skills)
            transcript_path = None
            if args.transcript_dir:
                transcript_path = args.transcript_dir / f"{target_skill}-q{i}-run{run_index}.jsonl"
            actual, usage, error = run_opencode_once(prompt, args.model, args.timeout, eval_cwd, transcript_path)
            if error:
                errors.append(f"q{i}_{error}")
                continue
            actuals.append(actual or "NONE")
            if actual == target_skill:
                matches += 1
            total_input_tokens += int(usage.get("input_tokens") or 0)
            total_output_tokens += int(usage.get("output_tokens") or 0)
            total_reasoning_tokens += int(usage.get("reasoning_output_tokens") or 0)
            total_cost += float(usage.get("cost") or 0.0)
        rate = matches / args.runs if args.runs else 0.0
        ok = (rate >= args.threshold) if query["should_trigger"] else (rate < args.threshold)
        fields[f"q{i}_actual"] = ",".join(actuals)
        fields[f"q{i}_should={str(query['should_trigger']).lower()}_rate"] = f"{rate:.2f}"
        if ok:
            passed += 1
        else:
            errors.append(f"q{i}_mismatch:should_trigger={query['should_trigger']},rate={rate:.2f},actual={','.join(actuals)}")

    fields["queries_passed"] = f"{passed}/{len(queries)}"
    fields["input_tokens"] = total_input_tokens
    fields["output_tokens"] = total_output_tokens
    fields["reasoning_output_tokens"] = total_reasoning_tokens
    fields["cost_usd"] = f"{total_cost:.6f}"
    fields["glm_trigger_eval"] = "failed" if errors else "passed"

    for line in sorted([f"{key}={value}" for key, value in fields.items()] + [f"error={err}" for err in errors]):
        print(line)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
