"""Update local plugin version metadata.

Usage:
  python3 scripts/bump_version.py 0.2.0
  python3 scripts/bump_version.py --check

A bump writes the shared VERSION, the Claude Code and Codex plugin manifests and every
visible README and docs version declaration (including the release verdict template's
``version=`` line), replacing only the declared values, then runs --check on the result.
--check compares the manifests and every visible declaration to VERSION.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
CHANGELOG = REPO / "CHANGELOG.md"
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
MANIFEST_KEYS = (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json", ".codex-plugin/plugin.json")
# Visible version declarations. Values are compared exactly (no whitespace normalization);
# other version-shaped text, such as a historical ``version `0.3.0` `` note, is not a declaration.
README_BADGE_RE = re.compile(r"(?m)^> `Version ([^`]*)`")
README_VERSION_TOKEN_RE = re.compile(r"`Version ([^`]*)`")
README_CURRENT_VERSION_RE = re.compile(r"Current version: `([^`]*)`\.")
PLUGIN_README_VERSION_RE = re.compile(r"(?m)^> Version: `([^`]*)`\.")
RELEASE_READINESS_VERSION_RE = re.compile(r"This file is the publish gate for `agentic-sdlc` version `([^`]*)`\.")
# The release verdict template keeps exactly one bare ``version=<semver>`` line.
VERDICT_TEMPLATE_VERSION_RE = re.compile(r"(?m)^version=(\d+\.\d+\.\d+)$")
# (path, declaration, pattern); each pattern captures the declared value in group 1.
DECLARATIONS = (
    ("README.md", "version-badge", README_BADGE_RE),
    ("README.md", "version-token", README_VERSION_TOKEN_RE),
    ("README.md", "current-version-sentence", README_CURRENT_VERSION_RE),
    ("docs/plugin-readme.md", "version-line", PLUGIN_README_VERSION_RE),
    ("docs/release-readiness.md", "publish-gate-sentence", RELEASE_READINESS_VERSION_RE),
    ("docs/release-readiness.md", "verdict-template-version", VERDICT_TEMPLATE_VERSION_RE),
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def version_declarations(root: Path = REPO) -> dict[tuple[str, str], list[str]]:
    texts = {path: (root / path).read_text(encoding="utf-8") for path, _, _ in DECLARATIONS}
    return {(path, declaration): pattern.findall(texts[path]) for path, declaration, pattern in DECLARATIONS}


def current_versions(root: Path = REPO) -> dict[str, str]:
    plugin = read_json(root / ".claude-plugin" / "plugin.json")
    marketplace = read_json(root / ".claude-plugin" / "marketplace.json")
    codex_plugin = read_json(root / ".codex-plugin" / "plugin.json")
    declarations = version_declarations(root)

    def first(path: str, declaration: str) -> str:
        values = declarations[(path, declaration)]
        return values[0] if values else ""

    return {
        "VERSION": (root / "VERSION").read_text(encoding="utf-8").strip(),
        ".claude-plugin/plugin.json": plugin.get("version", ""),
        ".claude-plugin/marketplace.json": marketplace["plugins"][0].get("version", ""),
        ".codex-plugin/plugin.json": codex_plugin.get("version", ""),
        "README.md": first("README.md", "version-token"),
        "README.md:current-version-sentence": first("README.md", "current-version-sentence"),
        "docs/plugin-readme.md": first("docs/plugin-readme.md", "version-line"),
        "docs/release-readiness.md": first("docs/release-readiness.md", "publish-gate-sentence"),
        "docs/release-readiness.md:verdict-template-version": first("docs/release-readiness.md", "verdict-template-version"),
    }


def declaration_failures(versions: dict[str, str], root: Path = REPO) -> list[str]:
    version = versions["VERSION"]
    failures = [f"version_mismatch={key}:version:{versions[key]}" for key in MANIFEST_KEYS if versions[key] != version]
    for (path, declaration), values in version_declarations(root).items():
        if declaration == "version-badge":
            # Presence only: the badge value is also a version token, checked below.
            if not values:
                failures.append(f"version_missing={path}:{declaration}")
            continue
        if not values and declaration != "version-token":
            failures.append(f"version_missing={path}:{declaration}")
        failures.extend(f"version_mismatch={path}:{declaration}:{value}" for value in values if value != version)
    return failures


def check(release: bool = False, root: Path = REPO) -> int:
    versions = current_versions(root)
    for key in sorted(versions):
        print(f"{key}={versions[key]}")
    failures = declaration_failures(versions, root)
    if failures:
        for line in failures:
            print(line)
        print("version_check=failed")
        return 1
    if release:
        version = versions["VERSION"]
        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
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


def replace_declared_values(text: str, pattern: re.Pattern[str], version: str) -> str:
    def replace(match: re.Match[str]) -> str:
        start, end = match.start(1) - match.start(), match.end(1) - match.start()
        whole = match.group(0)
        return whole[:start] + version + whole[end:]

    return pattern.sub(replace, text)


def bump(version: str, root: Path = REPO) -> int:
    if not SEMVER_RE.match(version):
        print(f"error=invalid_semver:{version}")
        return 2
    # The verdict template line only admits X.Y.Z; refuse before any write so a
    # pre-release or build bump cannot strand it or leave a half-updated tree.
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        print(f"error=unsupported_version:{version}")
        return 2
    plugin_path = root / ".claude-plugin" / "plugin.json"
    marketplace_path = root / ".claude-plugin" / "marketplace.json"
    codex_plugin_path = root / ".codex-plugin" / "plugin.json"
    plugin = read_json(plugin_path)
    marketplace = read_json(marketplace_path)
    codex_plugin = read_json(codex_plugin_path)
    plugin["version"] = version
    marketplace["plugins"][0]["version"] = version
    codex_plugin["version"] = version
    texts: dict[str, str] = {}
    for path, _, pattern in DECLARATIONS:
        if path not in texts:
            texts[path] = (root / path).read_text(encoding="utf-8")
        texts[path] = replace_declared_values(texts[path], pattern, version)
    (root / "VERSION").write_text(version + "\n", encoding="utf-8", newline="\n")
    write_json(plugin_path, plugin)
    write_json(marketplace_path, marketplace)
    write_json(codex_plugin_path, codex_plugin)
    for path, text in texts.items():
        (root / path).write_text(text, encoding="utf-8", newline="\n")
    print(f"version={version}")
    return check(root=root)


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
