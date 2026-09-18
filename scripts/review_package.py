"""Write a git diff review package to a file.

The package keeps large diffs out of controller context while giving a reviewer a
single file containing commit list, stat, and full diff.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.sensitive_redaction import redact_text
except ModuleNotFoundError:
    from sensitive_redaction import redact_text


def _slug(ref: str) -> str:
    """Make a ref safe to embed in the output filename: a ref like `origin/main` or a crafted
    `../x` would otherwise inject a path separator and write outside out_dir. Keep only
    filename-safe chars; '/' (and any other separator) collapses to '_', so no traversal."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", ref)[:12]


def git(args: list[str]) -> str:
    proc = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git command failed")
    return proc.stdout.strip()


def default_out_dir() -> Path:
    proc = subprocess.run(
        ["git", "rev-parse", "--git-path", "sdd"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
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

    # git parses any argument beginning with '-' as an option, not a revision. A ref like
    # `--output=<file>` would turn the `git diff/log` calls below into an arbitrary file write
    # (git option injection). git itself forbids ref/branch names starting with '-', so
    # refusing them here loses no legitimate input and closes the injection at the boundary.
    for ref in (args.base, args.head):
        if ref.startswith("-"):
            print(f"error=invalid ref (must not start with '-'): {ref!r}")
            return 1

    out_dir = args.out_dir or default_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = out_dir / f"review-package-{_slug(args.base)}-{_slug(args.head)}-{stamp}.md"
    try:
        log = git(["log", "--oneline", f"{args.base}..{args.head}"])
        stat = git(["diff", "--stat", args.base, args.head])
        diff = git(["diff", "-U10", args.base, args.head])
    except RuntimeError as exc:
        print(f"error={exc}")
        return 1

    package = "\n".join([
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
        ])
    try:
        out.write_text(redact_text(package), encoding="utf-8")
    except RuntimeError as exc:
        print(f"error={exc}")
        return 1
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
