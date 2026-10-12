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


# Constants for file paths and configurations
REPO = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO / "skills"
EVALS_DIR = REPO / "tests" / "skills" / "evals"
DEFAULT_TRANSCRIPT_DIR = REPO / "tests" / "artifacts" / "trigger-matrix"

# Default values for command arguments
DEFAULT_RUNS = 3
DEFAULT_THRESHOLD = 0.5
DEFAULT_TIMEOUT = 90
DEFAULT_QUERY_LIMIT = 0
DEFAULT_CLAUDE_MODEL = "haiku"
DEFAULT_MAX_BUDGET_USD = "0.10"
DEFAULT_CODEX_MODEL = "gpt-5.4-mini"
DEFAULT_REASONING_EFFORT = "low"

# Exit code scripts/run_trigger_eval.py uses when a run produced no measurement (see its docstring).
EXIT_UNMEASURED = 3

# Output format constants
STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_UNMEASURED = "unmeasured"
PREFIX_TRIGGER_MATRIX = "trigger_matrix"
PREFIX_MATRIX_PASSED = "matrix_passed"
PREFIX_ERROR = "error"


def skill_eval_pairs(skills_dir: Path, evals_dir: Path, only: str | None) -> list[tuple[str, Path, Path]]:
    """Find all skill-eval pairs for testing.

    Returns tuples of (skill_name, skill_path, eval_path) for each eval fixture.
    Filters by skill name if `only` is provided.
    """
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
    """Execute a subprocess command and return exit code and combined output."""
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def build_common_args(args: argparse.Namespace, skill_path: Path, eval_path: Path) -> list[str]:
    """Build command arguments common to both runtimes."""
    return [
        sys.executable,
        str(skill_path),
        str(eval_path),
        str(args.runs),
        str(args.threshold),
        str(args.timeout),
    ]


def build_claude_cmd(args: argparse.Namespace, skill_path: Path, eval_path: Path, skill_name: str) -> list[str]:
    """Build command list for Claude Code eval runner."""
    base_cmd = build_common_args(args, skill_path, eval_path)
    cmd = [
        base_cmd[0],
        str(REPO / "scripts" / "run_trigger_eval.py"),
        "--skill-path",
        base_cmd[1],
        "--eval-set",
        base_cmd[2],
        "--runs",
        base_cmd[3],
        "--threshold",
        base_cmd[4],
        "--timeout",
        base_cmd[5],
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


def build_codex_cmd(args: argparse.Namespace, skill_path: Path, eval_path: Path, skill_name: str) -> list[str]:
    """Build command list for Codex eval runner."""
    base_cmd = build_common_args(args, skill_path, eval_path)
    cmd = [
        base_cmd[0],
        str(REPO / "scripts" / "run_codex_trigger_eval.py"),
        "--skill-path",
        base_cmd[1],
        "--eval-set",
        base_cmd[2],
        "--runs",
        base_cmd[3],
        "--threshold",
        base_cmd[4],
        "--timeout",
        base_cmd[5],
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


def run_single_eval(runtime: str, skill_name: str, skill_path: Path, eval_path: Path, args: argparse.Namespace) -> tuple[int, str]:
    """Run a single evaluation and return exit code and output."""
    if runtime == "claude":
        cmd = build_claude_cmd(args, skill_path, eval_path, skill_name)
    else:
        cmd = build_codex_cmd(args, skill_path, eval_path, skill_name)
    return run_command(cmd, REPO)


def print_eval_result(runtime: str, skill_name: str, status: str, output: str) -> None:
    """Print evaluation results with runtime prefix."""
    print(f"{runtime}:{skill_name}:status={status}", flush=True)
    for line in output.splitlines():
        if line.strip():
            print(f"{runtime}:{skill_name}:{line}", flush=True)


def print_missing_skill_error(runtime: str, skill_name: str) -> None:
    """Print error message for missing SKILL.md file."""
    print(f"{runtime}:{skill_name}:status={STATUS_FAILED}", flush=True)
    print(f"{runtime}:{skill_name}:error=missing_skill", flush=True)


def print_final_results(passed: int, total: int, failures: list[str]) -> None:
    """Print summary of all evaluation results."""
    print(f"{PREFIX_MATRIX_PASSED}={passed}/{total}", flush=True)
    matrix_status = STATUS_FAILED if failures else STATUS_PASSED
    print(f"{PREFIX_TRIGGER_MATRIX}={matrix_status}", flush=True)
    for failure in failures:
        print(f"{PREFIX_ERROR}={failure}", flush=True)


def create_parser() -> argparse.ArgumentParser:
    """Create and configure argument parser."""
    parser = argparse.ArgumentParser(description="Run all AGENTIC-SDLC trigger eval fixtures.")
    parser.add_argument("--runtime", choices=("claude", "codex", "both"), default="claude")
    parser.add_argument("--skills-dir", type=Path, default=SKILLS_DIR)
    parser.add_argument("--evals-dir", type=Path, default=EVALS_DIR)
    parser.add_argument("--transcript-dir", type=Path, default=DEFAULT_TRANSCRIPT_DIR)
    parser.add_argument("--skill", help="Run only one skill by name.")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS,
                        help="Runs per query for majority voting (rate = matches/runs vs --threshold). "
                             "Default 3 so run-to-run flakiness is measured, not masked; --smoke forces 1.")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--query-limit", type=int, default=DEFAULT_QUERY_LIMIT)
    parser.add_argument("--smoke", action="store_true", help="Forward smoke mode to child runners.")
    parser.add_argument("--claude-model", default=DEFAULT_CLAUDE_MODEL)
    parser.add_argument("--max-budget-usd", default=DEFAULT_MAX_BUDGET_USD)
    parser.add_argument("--codex-model", default=DEFAULT_CODEX_MODEL)
    parser.add_argument("--reasoning-effort", default=DEFAULT_REASONING_EFFORT)
    return parser


def get_runtimes(runtime: str) -> tuple[str, ...]:
    """Return tuple of runtime names based on --runtime argument."""
    return ("claude", "codex") if runtime == "both" else (runtime,)


def run_evaluations(pairs: list[tuple[str, Path, Path]], runtimes: tuple[str, ...], args: argparse.Namespace) -> tuple[int, int, list[str]]:
    """Run all evaluations for given pairs and runtimes.

    Returns (total_count, passed_count, failures_list).
    """
    failures: list[str] = []
    total = 0
    passed = 0

    for runtime in runtimes:
        for skill_name, skill_path, eval_path in pairs:
            total += 1

            # Check if SKILL.md exists
            if not (skill_path / "SKILL.md").exists():
                failures.append(f"{runtime}:{skill_name}:missing_skill")
                print_missing_skill_error(runtime, skill_name)
                continue

            # Run evaluation
            code, output = run_single_eval(runtime, skill_name, skill_path, eval_path, args)
            status = STATUS_PASSED if code == 0 else (STATUS_UNMEASURED if code == EXIT_UNMEASURED else STATUS_FAILED)

            # Track results
            if code == 0:
                passed += 1
            else:
                failures.append(f"{runtime}:{skill_name}:exit_{code}")

            # Print results
            print_eval_result(runtime, skill_name, status, output)

    return total, passed, failures


def main(argv: list[str] | None = None) -> int:
    """Main entry point for running all trigger evals."""
    args = create_parser().parse_args(argv)

    # Find all skill-eval pairs
    pairs = skill_eval_pairs(args.skills_dir, args.evals_dir, args.skill)
    if not pairs:
        print(f"{PREFIX_TRIGGER_MATRIX}={STATUS_FAILED}")
        print(f"{PREFIX_ERROR}=no_eval_pairs")
        return 1

    # Determine which runtimes to execute
    runtimes = get_runtimes(args.runtime)

    # Run all evaluations
    total, passed, failures = run_evaluations(pairs, runtimes, args)

    # Print final summary
    print_final_results(passed, total, failures)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
