"""Update local plugin version metadata.

Usage:
  python scripts/bump_version.py 0.2.0
  python scripts/bump_version.py --check

This updates the shared VERSION plus Claude Code and Codex plugin manifests.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERSION_FILE = REPO / "VERSION"
PLUGIN_JSON = REPO / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = REPO / ".claude-plugin" / "marketplace.json"
CODEX_PLUGIN_JSON = REPO / ".codex-plugin" / "plugin.json"
README = REPO / "README.md"
CHANGELOG = REPO / "CHANGELOG.md"
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def current_versions() -> dict[str, str]:
    plugin = read_json(PLUGIN_JSON)
    marketplace = read_json(MARKETPLACE_JSON)
    codex_plugin = read_json(CODEX_PLUGIN_JSON)
    return {
        "VERSION": VERSION_FILE.read_text(encoding="utf-8").strip(),
        ".claude-plugin/plugin.json": plugin.get("version", ""),
        ".claude-plugin/marketplace.json": marketplace["plugins"][0].get("version", ""),
        ".codex-plugin/plugin.json": codex_plugin.get("version", ""),
        "README.md": (re.search(r"`Version ([^`]+)`", README.read_text(encoding="utf-8")) or [None, ""])[1],
    }


def check(release: bool = False) -> int:
    versions = current_versions()
    for key in sorted(versions):
        print(f"{key}={versions[key]}")
    unique = set(versions.values())
    if len(unique) != 1:
        print("version_check=failed")
        return 1
    if release:
        version = next(iter(unique))
        changelog = CHANGELOG.read_text(encoding="utf-8")
        unreleased = re.search(r"(?ms)^## Unreleased[^\n]*\n(.*?)(?=^## |\Z)", changelog)
        if unreleased and unreleased.group(1).strip():
            print("release_check=failed:nonempty_unreleased")
            return 1
        if not re.search(rf"(?m)^## {re.escape(version)} - \d{{4}}-\d{{2}}-\d{{2}}$", changelog):
            print("release_check=failed:missing_changelog_release")
            return 1
        print("release_check=passed")
    print("version_check=passed")
    return 0


def bump(version: str) -> int:
    if not SEMVER_RE.match(version):
        print(f"error=invalid_semver:{version}")
        return 2
    plugin = read_json(PLUGIN_JSON)
    marketplace = read_json(MARKETPLACE_JSON)
    codex_plugin = read_json(CODEX_PLUGIN_JSON)
    plugin["version"] = version
    marketplace["plugins"][0]["version"] = version
    codex_plugin["version"] = version
    VERSION_FILE.write_text(version + "\n", encoding="utf-8")
    write_json(PLUGIN_JSON, plugin)
    write_json(MARKETPLACE_JSON, marketplace)
    write_json(CODEX_PLUGIN_JSON, codex_plugin)
    print(f"version={version}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version", nargs="?")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--release-check", action="store_true")
    args = parser.parse_args(argv)
    if args.check or args.release_check:
        return check(release=args.release_check)
    if not args.version:
        parser.error("version is required unless --check or --release-check is used")
    return bump(args.version)


if __name__ == "__main__":
    sys.exit(main())
