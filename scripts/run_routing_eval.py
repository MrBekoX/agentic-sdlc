"""Live routing eval for the using-agentic-sdlc meta-router.

Question: given a natural user prompt, does the router reach the correct focused
skill, and do the pipeline's feeder skills stay independently reachable?

Claude Code exposes Skill/Read tool events, so the Claude path inspects actual
tool routing. Codex does not expose equivalent Skill tool events in `codex exec
--json`, so the Codex path evaluates the same routing decision as a compact
classifier over the local skill descriptions.

Eval-set JSON:
  {"scenarios": [{"prompt": "...", "expected": "mind-spark", "escalation": false}]}

A scenario passes when:
  - expected is among the routed skills, and
  - unless escalation is true, agentic-sdlc-pipeline is not routed.

Output: sorted key=value lines plus routing_eval=passed|failed.
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


ROUTER = "using-agentic-sdlc"
PIPELINE = "agentic-sdlc-pipeline"
DEFAULT_CODEX_MODEL = "gpt-5.3-codex-spark"
DEFAULT_CLAUDE_MODEL = "haiku"
CODEX_MODEL_ALIASES = {
    "gpt-5.3-spark": "gpt-5.3-codex-spark",
    "gpt-5.3-codex-spark": "gpt-5.3-codex-spark",
}


def normalize_skill(name: str) -> str:
    return (name or "").split(":")[-1].strip()


def resolve_codex_model(model: str) -> str:
    key = model.strip().lower()
    return CODEX_MODEL_ALIASES.get(key, model)


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
    skills: list[tuple[str, str]] = []
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        name, description = read_skill(skill_md.parent)
        name = normalize_skill(name)
        if name and name != ROUTER and description:
            skills.append((name, description))
    return skills


def load_scenarios(
    eval_set: Path,
    scenario_limit: int = 0,
    scenario_indexes: list[int] | None = None,
) -> list[tuple[int, dict[str, Any]]]:
    data = json.loads(eval_set.read_text(encoding="utf-8"))
    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("eval set must contain non-empty 'scenarios'")

    loaded: list[tuple[int, dict[str, Any]]] = []
    for index, scenario in enumerate(scenarios):
        if not isinstance(scenario, dict):
            raise ValueError(f"scenario {index} must be an object")
        prompt = scenario.get("prompt")
        expected = scenario.get("expected")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"scenario {index} missing prompt")
        if not isinstance(expected, str) or not expected.strip():
            raise ValueError(f"scenario {index} missing expected")
        escalation = scenario.get("escalation", False)
        if not isinstance(escalation, bool):
            raise ValueError(f"scenario {index} invalid escalation")
        loaded.append((
            index,
            {
                "prompt": prompt.strip(),
                "expected": normalize_skill(expected),
                "escalation": escalation,
            },
        ))

    if scenario_indexes:
        wanted = set(scenario_indexes)
        available = {index for index, _ in loaded}
        missing = sorted(wanted - available)
        if missing:
            raise ValueError(f"scenario-index out of range: {missing}")
        loaded = [(index, scenario) for index, scenario in loaded if index in wanted]

    if scenario_limit:
        loaded = loaded[:scenario_limit]
    return loaded


def build_codex_prompt(query: str, skills: list[tuple[str, str]]) -> str:
    skill_lines = "\n".join(f"- {name}: {description}" for name, description in skills)
    return (
        "You are simulating the AGENTIC-SDLC using-agentic-sdlc router.\n"
        "Choose exactly one listed target skill for the user prompt.\n"
        "Choose focused feeder skills directly when the prompt asks for one bounded step "
        "(brainstorming, WHAT spec, HOW plan, bug fix, feature build, tests, review, audit, "
        "feedback triage, dispatch choice, or final implementation audit).\n"
        "An ordinary new feature or endpoint request routes to feature-build, not "
        "agentic-sdlc-pipeline, unless the user explicitly asks for the full gated SDLC envelope "
        "or release/PR-ready end-to-end evidence.\n"
        "Final implementation or process audit before a final report routes to "
        "implementasyon-control. Choose completion-claim-gate only for validating a specific "
        "done/fixed/passing/ready claim, not for auditing the whole SDLC flow.\n"
        "Choose agentic-sdlc-pipeline only for explicit or clearly end-to-end SDLC work that "
        "needs the full spec-plan-build-test-review-audit loop.\n"
        "Return JSON only, with this exact shape: "
        '{"skill":"<one listed skill>","needs_dev_flow":true|false}.\n'
        "Set needs_dev_flow true only when the chosen skill is agentic-sdlc-pipeline.\n\n"
        f"Target skills:\n{skill_lines}\n\n"
        f"User prompt:\n{query}\n"
    )


def collect_claude_routes(lines: list[str]) -> list[str]:
    """Return focused skill names invoked via Skill or Read, excluding the router."""
    routes: list[str] = []

    def add(name: str) -> None:
        name = normalize_skill(name)
        if name and name != ROUTER and name not in routes:
            routes.append(name)

    skill_read = re.compile(r"skills[\\/]+([A-Za-z0-9-]+)[\\/]+SKILL\.md")
    acc: dict[int, dict[str, str]] = {}
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
            stype = se.get("type")
            idx = int(se.get("index", 0))
            if stype == "content_block_start":
                cb = se.get("content_block", {})
                if cb.get("type") == "tool_use":
                    acc[idx] = {"name": cb.get("name", ""), "json": ""}
            elif stype == "content_block_delta":
                delta = se.get("delta", {})
                if delta.get("type") == "input_json_delta" and idx in acc:
                    acc[idx]["json"] += delta.get("partial_json", "")
            elif stype == "content_block_stop" and idx in acc:
                pending = acc.pop(idx)
                try:
                    payload = json.loads(pending["json"] or "{}")
                except json.JSONDecodeError:
                    payload = {}
                if pending["name"] == "Skill":
                    add(payload.get("skill", ""))
                elif pending["name"] == "Read":
                    m = skill_read.search(str(payload.get("file_path", "")))
                    if m:
                        add(m.group(1))
    return routes


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


def run_claude(
    prompt: str,
    args: argparse.Namespace,
    transcript_path: Path | None,
    expected_skill: str = "",
    escalation: bool = False,
) -> tuple[list[str], str | None]:
    cmd = [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--no-session-persistence",
        "--permission-mode",
        "dontAsk",
        "--plugin-dir",
        str(args.project_root),
    ]
    if args.model:
        cmd += ["--model", args.model]
    if args.max_turns:
        cmd += ["--max-turns", str(args.max_turns)]
    if args.max_budget_usd:
        cmd += ["--max-budget-usd", str(args.max_budget_usd)]

    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=args.project_root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
    except FileNotFoundError:
        return [], "claude_missing"

    lines: queue.Queue[str] = queue.Queue()

    def reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.put(line)

    threading.Thread(target=reader, daemon=True).start()
    captured: list[str] = []
    timed_out = False
    deadline = time.monotonic() + args.timeout
    norm_expected = normalize_skill(expected_skill)
    try:
        while True:
            if time.monotonic() > deadline:
                timed_out = True
                kill_process_tree(proc)
                break
            try:
                line = lines.get(timeout=0.1)
            except queue.Empty:
                if proc.poll() is not None:
                    break
                continue
            captured.append(line)
            # Early stop once the routing decision is observable, so a correct route whose
            # skill then runs a long auditor/agent pass is not misread as a timeout. The
            # routing eval measures the route decision, not full skill execution. Only the
            # Skill/Read tool events carry route signal, so skip the per-line parse otherwise.
            if "Skill" in line or "SKILL.md" in line:
                routes = collect_claude_routes(captured)
                if routes and (
                    (not escalation and PIPELINE in routes)  # over-escalation: decided (fails later)
                    or (norm_expected and norm_expected in routes)  # expected feeder reached
                ):
                    kill_process_tree(proc)
                    break
    finally:
        kill_process_tree(proc)

    if transcript_path:
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text("".join(captured), encoding="utf-8")
    return captured, "timeout" if timed_out else None


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
        skill = normalize_skill(parsed["skill"])
    usage["warning_count"] = warning_count
    return skill, usage


def unwrap_codex_error_message(message: Any) -> str | None:
    if not isinstance(message, str) or not message.strip():
        return None
    text = message.strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return " ".join(text.split())
    if not isinstance(payload, dict):
        return " ".join(text.split())
    error = payload.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return " ".join(error["message"].split())
    if isinstance(payload.get("message"), str):
        return " ".join(payload["message"].split())
    return " ".join(text.split())


def extract_codex_error(lines: list[str]) -> str | None:
    for raw in reversed(lines):
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.failed":
            message = unwrap_codex_error_message(event.get("error", {}).get("message"))
            if message:
                return message
        if event.get("type") == "error":
            message = unwrap_codex_error_message(event.get("message"))
            if message:
                return message
    return None


def build_codex_command(codex: str, args: argparse.Namespace, project_root: Path) -> list[str]:
    return [
        codex,
        "-a",
        "never",
        "exec",
        "--json",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "-m",
        resolve_codex_model(args.model),
        "-c",
        f'model_reasoning_effort="{args.reasoning_effort}"',
        "-c",
        'model_verbosity="low"',
        "-s",
        "read-only",
        "-C",
        str(project_root),
        "-",
    ]


def run_codex_once(
    prompt: str,
    project_root: Path,
    args: argparse.Namespace,
    transcript_path: Path | None,
) -> tuple[str | None, dict[str, Any], str | None]:
    codex = shutil.which("codex")
    if not codex:
        return None, {}, "codex_missing"

    proc = subprocess.Popen(
        build_codex_command(codex, args, project_root),
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

    threading.Thread(target=read_stdout, daemon=True).start()
    try:
        assert proc.stdin is not None
        proc.stdin.write(prompt)
        proc.stdin.close()
    except OSError:
        kill_process_tree(proc)
        return None, {}, "codex_stdin_error"

    captured: list[str] = []
    timed_out = False
    deadline = time.monotonic() + args.timeout
    try:
        while True:
            if time.monotonic() > deadline:
                timed_out = True
                kill_process_tree(proc)
                break
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

    if timed_out:
        return None, {}, "timeout"

    actual, usage = parse_codex_events(captured)
    exit_code = proc.poll()
    if exit_code not in (0, None) and not actual:
        detail = extract_codex_error(captured)
        return None, usage, f"codex_error:{detail}" if detail else f"codex_exit_{exit_code}"
    return actual, usage, None


def evaluate_route(expected: str, routes: list[str], escalation: bool) -> tuple[bool, str | None]:
    expected = normalize_skill(expected)
    normalized_routes = [normalize_skill(route) for route in routes if normalize_skill(route)]
    if not escalation and PIPELINE in normalized_routes:
        return False, "over_escalated_to_pipeline"
    if expected not in normalized_routes:
        return False, "no_expected"
    return True, None


def route_once(
    scenario: dict[str, Any],
    skills: list[tuple[str, str]],
    args: argparse.Namespace,
    run_index: int,
    scenario_index: int,
) -> tuple[list[str], dict[str, Any], str | None]:
    transcript_path = None
    if args.transcript_dir:
        transcript_path = args.transcript_dir / f"scenario-{scenario_index}-run{run_index}.jsonl"

    if args.runtime == "claude":
        lines, error = run_claude(
            scenario["prompt"],
            args,
            transcript_path,
            expected_skill=scenario.get("expected", ""),
            escalation=bool(scenario.get("escalation", False)),
        )
        return collect_claude_routes(lines), {}, error

    prompt = build_codex_prompt(scenario["prompt"], skills)
    actual, usage, error = run_codex_once(prompt, args.project_root, args, transcript_path)
    routes = [actual] if actual else []
    return routes, usage, error


def runtime_default_model(runtime: str) -> str:
    return DEFAULT_CLAUDE_MODEL if runtime == "claude" else DEFAULT_CODEX_MODEL


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live using-agentic-sdlc routing eval.")
    parser.add_argument("--eval-set", required=True, type=Path)
    parser.add_argument("--runtime", choices=("codex", "claude"), default="codex")
    parser.add_argument("--model")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Runs per scenario. Default 3 so per-run model variance is measured, not masked: "
        "haiku routing swings ~0.6-1.0 between runs, so a single draw (runs=1) can read 15/15 "
        "by luck. Strict threshold (1.0) then requires every run to route correctly. --smoke forces 1.",
    )
    parser.add_argument("--threshold", type=float, default=1.0)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--max-turns", type=int, default=3)
    parser.add_argument("--max-budget-usd", default="0.15")
    parser.add_argument(
        "--scenario-index",
        action="append",
        type=int,
        default=[],
        help="Run only this zero-based scenario index; may be repeated.",
    )
    parser.add_argument("--scenario-limit", type=int, default=0)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--transcript-dir", type=Path)
    parser.add_argument("--skills-dir", type=Path, default=Path(__file__).resolve().parents[1] / "skills")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)

    if args.runs < 1:
        print("error=ValueError:runs must be >= 1")
        print("routing_eval=failed")
        return 2
    if not 0 < args.threshold <= 1:
        print("error=ValueError:threshold must be > 0 and <= 1")
        print("routing_eval=failed")
        return 2
    if args.smoke:
        args.runs = 1
        args.scenario_limit = args.scenario_limit or 1
        args.timeout = min(args.timeout, 90)
    args.model = args.model or runtime_default_model(args.runtime)

    try:
        scenarios = load_scenarios(args.eval_set, args.scenario_limit, args.scenario_index)
        skills = load_skills(args.skills_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error={type(exc).__name__}:{exc}")
        print("routing_eval=failed")
        return 1

    fields: dict[str, object] = {
        "runtime": args.runtime,
        "model": args.model,
        "router": ROUTER,
        "runs_per_scenario": args.runs,
        "semantics": "route-classifier" if args.runtime == "codex" else "live Skill routing",
    }
    if args.runtime == "codex":
        fields["reasoning_effort"] = args.reasoning_effort

    errors: list[str] = []
    passed = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_reasoning_tokens = 0

    for scenario_index, scenario in scenarios:
        expected = scenario["expected"]
        escalation = bool(scenario["escalation"])
        matches = 0
        actual_runs: list[str] = []
        hard_errors: list[str] = []
        last_reason = "no_expected"

        for run_index in range(args.runs):
            routes, usage, error = route_once(scenario, skills, args, run_index, scenario_index)
            actual_runs.append(",".join(routes) or "(none)")
            if error:
                hard_errors.append(error)
                continue

            ok, reason = evaluate_route(expected, routes, escalation)
            if ok:
                matches += 1
            elif reason == "over_escalated_to_pipeline":
                hard_errors.append(reason)
            else:
                last_reason = reason or last_reason

            total_input_tokens += int(usage.get("input_tokens") or 0)
            total_output_tokens += int(usage.get("output_tokens") or 0)
            total_reasoning_tokens += int(usage.get("reasoning_output_tokens") or 0)

        rate = matches / args.runs
        ok = not hard_errors and rate >= args.threshold
        fields[f"q{scenario_index}_expected"] = expected
        fields[f"q{scenario_index}_routed"] = ";".join(actual_runs)
        fields[f"q{scenario_index}_rate"] = f"{rate:.2f}"
        fields[f"q{scenario_index}_status"] = "passed" if ok else "failed"

        if ok:
            passed += 1
            continue

        reason = hard_errors[0] if hard_errors else last_reason
        errors.append(
            f"q{scenario_index}_{reason}:expected={expected},routed={';'.join(actual_runs)}"
        )

    fields["scenarios_passed"] = f"{passed}/{len(scenarios)}"
    fields["input_tokens"] = total_input_tokens
    fields["output_tokens"] = total_output_tokens
    fields["reasoning_output_tokens"] = total_reasoning_tokens
    fields["routing_eval"] = "failed" if errors else "passed"

    for line in sorted([f"{key}={value}" for key, value in fields.items()] + [f"error={err}" for err in errors]):
        print(line)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
