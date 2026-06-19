#!/usr/bin/env python3
"""Resolve the external skill-creator root for skill-authoring workflows.

Default mode is read-only discovery. Pass --install to try the Claude Code
official marketplace install command when discovery fails, then resolve again.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


REQUIRED = ("SKILL.md", "scripts")


def emit(fields: dict[str, str]) -> None:
    for key in sorted(fields):
        print(f"{key}={fields[key]}")


def home() -> Path:
    for name in ("USERPROFILE", "HOME"):
        value = os.environ.get(name)
        if value:
            return Path(value).expanduser()
    try:
        return Path.home()
    except RuntimeError:
        return Path.cwd()


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or home() / ".codex")


def candidate_paths() -> list[tuple[str, Path]]:
    env_names = ("SKILL_CREATOR_ROOT", "AGENTIC_SDLC_SKILL_CREATOR_ROOT")
    out: list[tuple[str, Path]] = []
    for name in env_names:
        value = os.environ.get(name)
        if value:
            out.append((name.lower(), Path(value).expanduser()))

    ch = codex_home()
    out.extend(
        [
            ("codex-system", ch / "skills" / ".system" / "skill-creator"),
            ("codex-user", ch / "skills" / "skill-creator"),
            (
                "claude-official-cache",
                home()
                / ".claude"
                / "plugins"
                / "cache"
                / "claude-plugins-official"
                / "skill-creator"
                / "unknown"
                / "skills"
                / "skill-creator",
            ),
            (
                "claude-legacy-marketplace",
                home()
                / ".claude"
                / "plugins"
                / "marketplaces"
                / "anthropic-agent-skills"
                / "skills"
                / "skill-creator",
            ),
        ]
    )
    return out


def is_skill_creator_root(path: Path) -> bool:
    return path.is_dir() and all((path / name).exists() for name in REQUIRED)


def discover_by_scan() -> tuple[str, Path] | None:
    scan_roots = [
        home() / ".claude" / "plugins" / "cache",
        home() / ".claude" / "plugins" / "marketplaces",
        codex_home() / "skills",
    ]
    for root in scan_roots:
        if not root.is_dir():
            continue
        for path in root.rglob("skill-creator"):
            if is_skill_creator_root(path):
                return ("scan", path)
    return None


def discover() -> tuple[str, Path] | None:
    for source, path in candidate_paths():
        if is_skill_creator_root(path):
            return source, path
    return discover_by_scan()


def install_with_claude() -> tuple[int, str]:
    command = ["claude", "plugin", "install", "skill-creator@claude-plugins-official"]
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except FileNotFoundError:
        return 127, "claude CLI not found"
    except subprocess.TimeoutExpired:
        return 124, "claude plugin install timed out"
    output = (proc.stdout + proc.stderr).strip().replace("\r", "")
    return proc.returncode, output.splitlines()[-1] if output else ""


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--install",
        action="store_true",
        help="If discovery fails, install skill-creator from the Claude official marketplace.",
    )
    args = parser.parse_args(argv)

    found = discover()
    if found:
        source, path = found
        emit(
            {
                "skill_creator_root": str(path),
                "skill_creator_source": source,
                "skill_creator_status": "found",
            }
        )
        return 0

    if not args.install:
        emit(
            {
                "install_command": "claude plugin install skill-creator@claude-plugins-official",
                "skill_creator_status": "missing",
            }
        )
        return 2

    rc, message = install_with_claude()
    found = discover()
    fields = {
        "install_command": "claude plugin install skill-creator@claude-plugins-official",
        "install_exit": str(rc),
    }
    if message:
        fields["install_message"] = message
    if found:
        source, path = found
        fields.update(
            {
                "skill_creator_root": str(path),
                "skill_creator_source": source,
                "skill_creator_status": "installed",
            }
        )
        emit(fields)
        return 0

    fields["skill_creator_status"] = "missing_after_install"
    emit(fields)
    return rc if rc else 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
