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
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

try:
    from scripts.eval_safety import require_slug, resolve_under
    from scripts.sensitive_redaction import redact_text
except ModuleNotFoundError:
    from eval_safety import require_slug, resolve_under
    from sensitive_redaction import redact_text


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
    return require_slug(fm.get("name", skill_path.name), "skill name"), fm.get("description", "")


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
        "Choose focused feeder skills directly when the prompt asks for one bounded step "
        "(brainstorming, WHAT spec, HOW plan, bug fix, feature build, refactor, tests, review, "
        "audit, feedback triage, dispatch choice, or final implementation audit).\n"
        "An ordinary new feature or endpoint request routes to feature-build, not "
        "agentic-sdlc-pipeline, unless the user explicitly asks for the full gated SDLC envelope "
        "or release/PR-ready end-to-end evidence.\n"
        "A behavior-preserving refactor (even with characterization tests) routes to safe-refactor, "
        "not agentic-sdlc-pipeline, unless the user asks for the full SDLC envelope.\n"
        "An orchestration decision (main loop vs sub-agent vs workflow vs agent-team) routes to "
        "dispatch-strategy, not using-agentic-sdlc.\n"
        "Final implementation or process audit before a final report routes to "
        "implementation-control. Choose completion-claim-gate only for validating a specific "
        "done/fixed/passing/ready claim, not for auditing the whole SDLC flow.\n"
        "Choose agentic-sdlc-pipeline only for explicit or clearly end-to-end SDLC work that "
        "needs the full spec-plan-build-test-review-audit loop.\n"
        "Return JSON only, with this exact shape: "
        '{"skill":"<one listed skill>","needs_dev_flow":true|false}.\n'
        "Set needs_dev_flow true only when the chosen skill is agentic-sdlc-pipeline.\n\n"
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
        transcript_path.write_text(redact_text("".join(captured)), encoding="utf-8")
    actual, usage = parse_codex_events(captured)
    return actual, usage, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Codex route/trigger eval runner.")
    parser.add_argument("--skill-path", required=True, type=Path)
    parser.add_argument("--eval-set", required=True, type=Path)
    parser.add_argument("--skills-dir", type=Path, default=Path(__file__).resolve().parents[1] / "skills")
    parser.add_argument(
        "--project-root",
        type=Path,
        help="explicit real checkout context (default: an ephemeral empty directory)",
    )
    parser.add_argument(
        "--allow-writable-project",
        action="store_true",
        help="Explicitly authorize exposing --project-root to the live Codex classifier; Codex still runs read-only.",
    )
    parser.add_argument("--model", default="gpt-5.4-mini")
    parser.add_argument("--reasoning-effort", default="low")
    parser.add_argument("--runs", type=int, default=3, help="Runs per query for majority voting (rate = matches/runs vs --threshold). Default 3 so run-to-run flakiness is measured, not masked; --smoke forces 1.")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--query-limit", type=int, default=0)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--transcript-dir", type=Path)
    args = parser.parse_args(argv)

    if args.project_root is not None and not args.allow_writable_project:
        parser.error("--project-root requires --allow-writable-project")

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

    temporary_project = None
    if args.project_root is not None:
        args.project_root = args.project_root.resolve()
    else:
        temporary_project = tempfile.TemporaryDirectory(prefix="agentic-sdlc-codex-trigger-")
        args.project_root = Path(temporary_project.name)

    try:
        for i, query in enumerate(queries):
            matches = 0
            actuals = []
            for run_index in range(args.runs):
                prompt = build_prompt(query["query"], skills)
                transcript_path = None
                if args.transcript_dir:
                    transcript_path = resolve_under(
                        args.transcript_dir,
                        f"{target_skill}-q{i}-run{run_index}.jsonl",
                        "transcript filename",
                    )
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
    finally:
        if temporary_project is not None:
            temporary_project.cleanup()

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
