#!/usr/bin/env python3
"""Resolve the external skill-creator root for skill-authoring workflows.

Default mode checks the files needed for validation, behavioral review, and
packaging without executing external code. Narrow with --require. Pass --install
only when an official marketplace dependency installation is authorized.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


CAPABILITIES = {
    "validate": ("scripts/quick_validate.py",),
    "benchmark": ("scripts/aggregate_benchmark.py",),
    "viewer": ("eval-viewer/generate_review.py", "eval-viewer/viewer.html"),
    "package": ("scripts/package_skill.py", "scripts/quick_validate.py"),
    "schemas": ("references/schemas.md",),
    # These are the external Claude harnesses, not Codex runners. File presence
    # alone does not establish CLI/auth, platform, or Python dependency support.
    "trigger": ("scripts/run_eval.py", "scripts/utils.py"),
    "optimize": (
        "scripts/run_loop.py", "scripts/run_eval.py",
        "scripts/improve_description.py", "scripts/generate_report.py", "scripts/utils.py",
    ),
}
DEFAULT_CAPABILITIES = ("validate", "benchmark", "viewer", "package", "schemas")


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
        ]
    )
    official = home() / ".claude/plugins/cache/claude-plugins-official/skill-creator"
    if official.is_dir():
        for version in sorted((p for p in official.iterdir() if p.is_dir()), reverse=True):
            out.append((f"claude-official-cache:{version.name}", version / "skills/skill-creator"))
    return out


def is_skill_creator_root(path: Path) -> bool:
    if not (path / "SKILL.md").is_file() or not (path / "scripts").is_dir():
        return False
    try:
        text = (path / "SKILL.md").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    return bool(re.search(r"(?m)^name:\s*skill-creator\s*$", text))


def missing_files(path: Path, required: tuple[str, ...]) -> list[str]:
    return sorted({
        relative for capability in required for relative in CAPABILITIES[capability]
        if not (path / relative).is_file()
    })


def available_capabilities(path: Path) -> list[str]:
    return [name for name in CAPABILITIES if not missing_files(path, (name,))]


def discover(
    required: tuple[str, ...] = DEFAULT_CAPABILITIES,
    diagnostics: dict[str, str] | None = None,
) -> tuple[str, Path] | None:
    skipped = 0
    for source, path in candidate_paths():
        if is_skill_creator_root(path):
            missing = missing_files(path, required)
            if not missing:
                return source, path.resolve()
            skipped += 1
            if diagnostics is not None:
                prefix = f"candidate_{skipped}"
                diagnostics.update({
                    f"{prefix}_root": str(path.resolve()),
                    f"{prefix}_source": source,
                    f"{prefix}_missing_files": ",".join(missing),
                })
    return None


def trust_for(source: str) -> str:
    return "explicit-unverified" if source in {"skill_creator_root", "agentic_sdlc_skill_creator_root"} else "official"


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
        "--require", nargs="+", choices=tuple(CAPABILITIES),
        default=DEFAULT_CAPABILITIES,
        help="Required resource capabilities (default: validate benchmark viewer package schemas).",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="If capabilities are missing, explicitly install from the Claude official marketplace.",
    )
    args = parser.parse_args(argv)

    required = tuple(dict.fromkeys(args.require))
    fields = {"skill_creator_required": ",".join(required)}
    found = discover(required, fields)
    if found:
        source, path = found
        emit(
            {
                **fields,
                "skill_creator_root": str(path),
                "skill_creator_source": source,
                "skill_creator_trust": trust_for(source),
                "skill_creator_status": "found",
                "skill_creator_capabilities": ",".join(available_capabilities(path)),
            }
        )
        return 0

    if not args.install:
        emit(
            {
                **fields,
                "install_command": "claude plugin install skill-creator@claude-plugins-official",
                "skill_creator_status": "missing_capabilities" if "candidate_1_root" in fields else "missing",
            }
        )
        return 2

    rc, message = install_with_claude()
    fields = {
        "skill_creator_required": ",".join(required),
        "install_command": "claude plugin install skill-creator@claude-plugins-official",
        "install_exit": str(rc),
    }
    found = discover(required, fields)
    if message:
        fields["install_message"] = message
    if found:
        source, path = found
        fields.update(
            {
                "skill_creator_root": str(path),
                "skill_creator_source": source,
                "skill_creator_trust": trust_for(source),
                "skill_creator_status": "installed",
                "skill_creator_capabilities": ",".join(available_capabilities(path)),
            }
        )
        emit(fields)
        return 0

    fields["skill_creator_status"] = "missing_after_install"
    emit(fields)
    return rc if rc else 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
