"""Update local plugin version metadata.

Usage:
  python3 scripts/bump_version.py 0.2.0
  python3 scripts/bump_version.py --check
  python3 scripts/bump_version.py --audit

A bump writes the shared VERSION, every runtime plugin manifest, this plugin's entries in every
marketplace catalog, and every visible README, docs and SECURITY.md version declaration (including
the release verdict template's ``version=`` line and the supported ``X.Y.x`` line), replacing only
the declared values, then runs --check on the result.
--check compares the manifests and every visible declaration to VERSION (the SECURITY.md line to
its ``X.Y`` minor line). A catalog entry of another plugin is neither checked nor bumped.
--audit answers a different question: is any shipped manifest missing from that comparison?
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
CHANGELOG = REPO / "CHANGELOG.md"
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
# The catalog entries that are this plugin's (RL-9). Kimi-style catalogs name an entry by ``id``.
PLUGIN_NAME = "agentic-sdlc"
# Every runtime manifest that declares this plugin's version, with how the version is nested.
# The adapter manifests (Kimi, ZCode, Grok) are optional members: a skills-only archive and any future
# adapter removal leave them absent, and an absent file is not drift. That each one exists in the
# repository is asserted by that adapter's own packaging test; what belongs here is the version.
MANIFESTS = (
    (".claude-plugin/plugin.json", "plugin"),
    (".claude-plugin/marketplace.json", "marketplace"),
    (".codex-plugin/plugin.json", "plugin"),
    (".kimi-plugin/plugin.json", "plugin"),
    (".zcode-plugin/plugin.json", "plugin"),
    ("marketplace.json", "marketplace"),          # root, ZCode marketplace schema
    (".grok-plugin/plugin.json", "plugin"),
    (".grok-plugin/marketplace.json", "marketplace"),
    (".cursor-plugin/plugin.json", "plugin"),
    (".cursor-plugin/marketplace.json", "marketplace"),
    # agy 1.5.14 reads `version` here and, without one, falls back to .claude-plugin/plugin.json
    # (probe 2026-11-21); the schema https://antigravity.google/schemas/v1/plugin.json allows it.
    (".antigravity-plugin/plugin.json", "plugin"),
)
MANIFEST_KEYS = tuple(path for path, _kind in MANIFESTS)
# Adapter manifests whose upstream schema forbids a plugin ``version`` property. ``--check`` rejects a
# ``version`` field in one, ``bump`` leaves it unversioned and ``--audit`` still counts it as
# registered. None today: the Antigravity manifest moved to MANIFESTS once agy's schema was shown
# to accept ``version``.
VERSIONLESS_PLUGIN_MANIFESTS: tuple = ()
# Directories that never hold a shipped manifest. tests/ is pruned because its fixtures write
# synthetic plugin.json files that would otherwise read as unregistered manifests.
AUDIT_SKIP_DIRS = frozenset({".git", "__pycache__", ".venv", "venv", "node_modules", "tests", "out", "mcps", ".claude"})
# Visible version declarations. Values are compared exactly (no whitespace normalization);
# other version-shaped text, such as a historical ``version `0.3.0` `` note, is not a declaration.
README_BADGE_RE = re.compile(r"(?m)^> `Version ([^`]*)`")
README_VERSION_TOKEN_RE = re.compile(r"`Version ([^`]*)`")
README_CURRENT_VERSION_RE = re.compile(r"Current version: `([^`]*)`\.")
PLUGIN_README_VERSION_RE = re.compile(r"(?m)^> Version: `([^`]*)`\.")
RELEASE_READINESS_VERSION_RE = re.compile(r"This file is the publish gate for `agentic-sdlc` version `([^`]*)`\.")
# The release verdict template keeps exactly one bare ``version=<semver>`` line.
VERDICT_TEMPLATE_VERSION_RE = re.compile(r"(?m)^version=(\d+\.\d+\.\d+)$")
# RL-8: the security policy names the supported minor line (``0.7.x``); group 1 is ``0.7``.
SECURITY_SUPPORTED_RE = re.compile(r"Security fixes are provided for the latest `([^`]*)\.x` release\.")
# (path, declaration, pattern); each pattern captures the declared value in group 1.
DECLARATIONS = (
    ("README.md", "version-badge", README_BADGE_RE),
    ("README.md", "version-token", README_VERSION_TOKEN_RE),
    ("README.md", "current-version-sentence", README_CURRENT_VERSION_RE),
    ("docs/plugin-readme.md", "version-line", PLUGIN_README_VERSION_RE),
    ("docs/release-readiness.md", "publish-gate-sentence", RELEASE_READINESS_VERSION_RE),
    ("docs/release-readiness.md", "verdict-template-version", VERDICT_TEMPLATE_VERSION_RE),
    ("SECURITY.md", "supported-minor-line", SECURITY_SUPPORTED_RE),
)
# Declarations that state a value derived from VERSION rather than VERSION itself.
MINOR_LINE_DECLARATIONS = frozenset({("SECURITY.md", "supported-minor-line")})


def declared_value(path: str, declaration: str, version: str) -> str:
    """The value a declaration must hold for ``version``: VERSION itself, or its X.Y minor line."""
    if (path, declaration) in MINOR_LINE_DECLARATIONS:
        return ".".join(version.split(".")[:2])
    return version


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def version_declarations(root: Path = REPO) -> dict[tuple[str, str], list[str]]:
    texts = {path: (root / path).read_text(encoding="utf-8") for path, _, _ in DECLARATIONS}
    return {(path, declaration): pattern.findall(texts[path]) for path, declaration, pattern in DECLARATIONS}


def plugin_entries(data) -> list:
    """This plugin's entries in a marketplace catalog, in catalog order (RL-9)."""
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, list):
        return []
    return [entry for entry in plugins if isinstance(entry, dict)
            and (entry.get("name") if "name" in entry else entry.get("id")) == PLUGIN_NAME]


def manifest_version(root: Path, path: str, kind: str) -> str | None:
    """The version declared by one manifest, or None when the file is absent.

    A catalog reports every entry of this plugin: one value when they agree, the distinct values
    joined by commas when they do not (never equal to VERSION, so --check fails), and an empty
    value when the catalog has no entry for this plugin.
    """
    file = root / path
    if not file.is_file():
        return None
    data = read_json(file)
    if kind == "marketplace":
        versions = list(dict.fromkeys("" if entry.get("version") is None else str(entry["version"])
                                      for entry in plugin_entries(data)))
        return ",".join(versions)
    return data.get("version", "")


def current_versions(root: Path = REPO) -> dict[str, str]:
    declarations = version_declarations(root)

    def first(path: str, declaration: str) -> str:
        values = declarations[(path, declaration)]
        return values[0] if values else ""

    manifests = {}
    for path, kind in MANIFESTS:
        value = manifest_version(root, path, kind)
        if value is not None:
            manifests[path] = value

    return {
        "VERSION": (root / "VERSION").read_text(encoding="utf-8").strip(),
        **manifests,
        "README.md": first("README.md", "version-token"),
        "README.md:current-version-sentence": first("README.md", "current-version-sentence"),
        "docs/plugin-readme.md": first("docs/plugin-readme.md", "version-line"),
        "docs/release-readiness.md": first("docs/release-readiness.md", "publish-gate-sentence"),
        "docs/release-readiness.md:verdict-template-version": first("docs/release-readiness.md", "verdict-template-version"),
        "SECURITY.md:supported-minor-line": first("SECURITY.md", "supported-minor-line"),
    }


def declaration_failures(versions: dict[str, str], root: Path = REPO) -> list[str]:
    version = versions["VERSION"]
    failures = [f"version_mismatch={key}:version:{versions[key]}"
                for key in MANIFEST_KEYS if key in versions and versions[key] != version]
    for rel in VERSIONLESS_PLUGIN_MANIFESTS:
        file = root / rel
        if file.is_file():
            data = read_json(file)
            if "version" in data:
                failures.append(f"version_unsupported={rel}:version:{data['version']}")
    for (path, declaration), values in version_declarations(root).items():
        if declaration == "version-badge":
            # Presence only: the badge value is also a version token, checked below.
            if not values:
                failures.append(f"version_missing={path}:{declaration}")
            continue
        if not values and declaration != "version-token":
            failures.append(f"version_missing={path}:{declaration}")
        expected = declared_value(path, declaration, version)
        failures.extend(f"version_mismatch={path}:{declaration}:{value}" for value in values if value != expected)
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
    updated: list[tuple[Path, dict]] = []
    for path, kind in MANIFESTS:
        file = root / path
        if not file.is_file():
            continue
        data = read_json(file)
        if kind == "marketplace":
            # Every entry of this plugin and no other (RL-9): --check reads the same entries.
            for entry in plugin_entries(data):
                entry["version"] = version
        else:
            data["version"] = version
        updated.append((file, data))
    texts: dict[str, str] = {}
    for path, declaration, pattern in DECLARATIONS:
        if path not in texts:
            texts[path] = (root / path).read_text(encoding="utf-8")
        texts[path] = replace_declared_values(texts[path], pattern, declared_value(path, declaration, version))
    (root / "VERSION").write_text(version + "\n", encoding="utf-8", newline="\n")
    for file, data in updated:
        write_json(file, data)
    for path, text in texts.items():
        (root / path).write_text(text, encoding="utf-8", newline="\n")
    print(f"version={version}")
    return check(root=root)


def _tracked_paths(root: Path) -> list[str] | None:
    """Everything git tracks at root, or None when git cannot answer."""
    try:
        proc = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                              capture_output=True, check=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return [entry for entry in proc.stdout.decode("utf-8", "replace").split("\0") if entry]


def _walked_paths(root: Path) -> list[str]:
    """Fallback discovery when git is unavailable: walk, pruning the trees that never ship."""
    paths: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in AUDIT_SKIP_DIRS)
        paths.extend((Path(dirpath) / name).relative_to(root).as_posix() for name in filenames)
    return paths


def discovered_manifests(root: Path = REPO) -> list[str]:
    """Repository-relative plugin/marketplace manifests that declare a version.

    Tracked files only. A scratch clone or comparison checkout under the repository root carries
    another project's manifests, and those are not this project's version declarations.
    """
    candidates = _tracked_paths(root)
    if candidates is None:
        candidates = _walked_paths(root)
    found: list[str] = []
    for rel in sorted(candidates):
        name = rel.rsplit("/", 1)[-1]
        if name != "plugin.json" and not (name == "marketplace.json" or
                                         name.startswith("marketplace-") and name.endswith(".json")):
            continue
        if rel in VERSIONLESS_PLUGIN_MANIFESTS:
            if (root / rel).is_file():
                found.append(rel)
            continue
        # Named marketplace files may carry a schema version at the top level.
        # Only a plugins[] entry version is a plugin version to register/audit.
        kind = "plugin" if name == "plugin.json" else "marketplace"
        try:
            declared = manifest_version(root, rel, kind)
        except (OSError, ValueError, AttributeError):
            # Unreadable or unexpectedly shaped: that is a packaging-test finding, not a
            # version-drift one. The audit only reports manifests it can read.
            continue
        if declared:
            found.append(rel)
    for rel in VERSIONLESS_PLUGIN_MANIFESTS:
        if rel not in found and (root / rel).is_file():
            try:
                data = read_json(root / rel)
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and data.get("name"):
                found.append(rel)
    return sorted(found)


def audit(root: Path = REPO) -> int:
    """Report shipped manifests that the version comparison does not cover.

    A new runtime adapter arrives as a new manifest. Unless it is listed in MANIFESTS, a bump
    leaves it behind silently and only that adapter's own test notices — which is how the ZCode
    and Grok manifests came to sit outside the one version source.
    """
    registered = set(MANIFEST_KEYS) | set(VERSIONLESS_PLUGIN_MANIFESTS)
    discovered = discovered_manifests(root)
    unregistered = [rel for rel in discovered if rel not in registered]
    for rel in discovered:
        print(f"audit_manifest={rel}:{'registered' if rel in registered else 'unregistered'}")
    for rel in (*MANIFEST_KEYS, *VERSIONLESS_PLUGIN_MANIFESTS):
        if not (root / rel).is_file():
            # Not a failure: adapter manifests are optional members (see MANIFESTS).
            print(f"audit_absent={rel}")
    print("audit=" + ("failed" if unregistered else "passed"))
    return 1 if unregistered else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version", nargs="?")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--release-check", action="store_true")
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args(argv)
    if args.audit:
        return audit()
    if args.check or args.release_check:
        return check(release=args.release_check)
    if not args.version:
        parser.error("version is required unless --check, --release-check or --audit is used")
    return bump(args.version)


if __name__ == "__main__":
    sys.exit(main())
