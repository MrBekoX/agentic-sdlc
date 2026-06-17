"""Run live trigger evals for every skill eval fixture.

This is a thin batch wrapper around the runtime-specific runners:
- Claude Code tool-event evals: scripts/run_trigger_eval.py
- Codex route-classifier evals: scripts/run_codex_trigger_eval.py

It continues after failures so one run returns the full skill matrix.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO / "skills"
EVALS_DIR = REPO / "tests" / "skills" / "evals"


def skill_eval_pairs(skills_dir: Path, evals_dir: Path, only: str | None) -> list[tuple[str, Path, Path]]:
    pairs: list[tuple[str, Path, Path]] = []
    for eval_path in sorted(evals_dir.glob("*.json")):
        name = eval_path.stem
        if only and name != only:
            continue
        skill_path = skills_dir / name
        if not (skill_path / "SKILL.md").exists():
            pairs.append((name, skill_path, eval_path))
            continue
        pairs.append((name, skill_path, eval_path))
    return pairs


def run_command(cmd: list[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def claude_cmd(args: argparse.Namespace, skill_path: Path, eval_path: Path, skill_name: str) -> list[str]:
    cmd = [
        sys.executable,
        str(REPO / "scripts" / "run_trigger_eval.py"),
        "--skill-path",
        str(skill_path),
        "--eval-set",
        str(eval_path),
        "--runs",
        str(args.runs),
        "--threshold",
        str(args.threshold),
        "--timeout",
        str(args.timeout),
        "--plugin-dir",
        str(REPO),
        "--no-command-shim",
        "--transcript-dir",
        str(args.transcript_dir / "claude" / skill_name),
    ]
    if args.claude_model:
        cmd += ["--model", args.claude_model]
    if args.max_budget_usd:
        cmd += ["--max-budget-usd", str(args.max_budget_usd)]
    if args.query_limit:
        cmd += ["--query-limit", str(args.query_limit)]
    if args.smoke:
        cmd += ["--smoke"]
    return cmd


def codex_cmd(args: argparse.Namespace, skill_path: Path, eval_path: Path, skill_name: str) -> list[str]:
    cmd = [
        sys.executable,
        str(REPO / "scripts" / "run_codex_trigger_eval.py"),
        "--skill-path",
        str(skill_path),
        "--eval-set",
        str(eval_path),
        "--runs",
        str(args.runs),
        "--threshold",
        str(args.threshold),
        "--timeout",
        str(args.timeout),
        "--model",
        args.codex_model,
        "--reasoning-effort",
        args.reasoning_effort,
        "--transcript-dir",
        str(args.transcript_dir / "codex" / skill_name),
    ]
    if args.query_limit:
        cmd += ["--query-limit", str(args.query_limit)]
    if args.smoke:
        cmd += ["--smoke"]
    return cmd


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run all AGENTIC-SDLC trigger eval fixtures.")
    parser.add_argument("--runtime", choices=("claude", "codex", "both"), default="claude")
    parser.add_argument("--skills-dir", type=Path, default=SKILLS_DIR)
    parser.add_argument("--evals-dir", type=Path, default=EVALS_DIR)
    parser.add_argument("--transcript-dir", type=Path, default=REPO / "tests" / "artifacts" / "trigger-matrix")
    parser.add_argument("--skill", help="Run only one skill by name.")
    parser.add_argument("--runs", type=int, default=3, help="Runs per query for majority voting (rate = matches/runs vs --threshold). Default 3 so run-to-run flakiness is measured, not masked; --smoke forces 1.")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--query-limit", type=int, default=0)
    parser.add_argument("--smoke", action="store_true", help="Forward smoke mode to child runners.")
    parser.add_argument("--claude-model", default="haiku")
    parser.add_argument("--max-budget-usd", default="0.10")
    parser.add_argument("--codex-model", default="gpt-5.4-mini")
    parser.add_argument("--reasoning-effort", default="low")
    args = parser.parse_args(argv)

    pairs = skill_eval_pairs(args.skills_dir, args.evals_dir, args.skill)
    if not pairs:
        print("trigger_matrix=failed")
        print("error=no_eval_pairs")
        return 1

    runtimes = ("claude", "codex") if args.runtime == "both" else (args.runtime,)
    failures: list[str] = []
    total = 0
    passed = 0

    for runtime in runtimes:
        for skill_name, skill_path, eval_path in pairs:
            total += 1
            if not (skill_path / "SKILL.md").exists():
                failures.append(f"{runtime}:{skill_name}:missing_skill")
                print(f"{runtime}:{skill_name}:status=failed", flush=True)
                print(f"{runtime}:{skill_name}:error=missing_skill", flush=True)
                continue
            cmd = claude_cmd(args, skill_path, eval_path, skill_name) if runtime == "claude" else codex_cmd(args, skill_path, eval_path, skill_name)
            code, output = run_command(cmd, REPO)
            status = "passed" if code == 0 else "failed"
            if code == 0:
                passed += 1
            else:
                failures.append(f"{runtime}:{skill_name}:exit_{code}")
            print(f"{runtime}:{skill_name}:status={status}", flush=True)
            for line in output.splitlines():
                if line.strip():
                    print(f"{runtime}:{skill_name}:{line}", flush=True)

    print(f"matrix_passed={passed}/{total}", flush=True)
    print(f"trigger_matrix={'failed' if failures else 'passed'}", flush=True)
    for failure in failures:
        print(f"error={failure}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
