"""Write a git diff review package to a file.

The package keeps large diffs out of controller context while giving a reviewer a
single file containing commit list, stat, and full diff.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def git(args: list[str]) -> str:
    proc = subprocess.run(["git", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git command failed")
    return proc.stdout.strip()


def default_out_dir() -> Path:
    proc = subprocess.run(
        ["git", "rev-parse", "--git-path", "sdd"],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return Path(".sdd")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base")
    parser.add_argument("head")
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    out_dir = args.out_dir or default_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out = out_dir / f"review-package-{args.base[:12]}-{args.head[:12]}-{stamp}.md"
    try:
        log = git(["log", "--oneline", f"{args.base}..{args.head}"])
        stat = git(["diff", "--stat", args.base, args.head])
        diff = git(["diff", "-U10", args.base, args.head])
    except RuntimeError as exc:
        print(f"error={exc}")
        return 1

    out.write_text(
        "\n".join([
            "# Review Package",
            "",
            f"Range: `{args.base}..{args.head}`",
            "",
            "## Commits",
            "```",
            log,
            "```",
            "",
            "## Diff Stat",
            "```",
            stat,
            "```",
            "",
            "## Diff",
            "```diff",
            diff,
            "```",
            "",
        ]),
        encoding="utf-8",
    )
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
