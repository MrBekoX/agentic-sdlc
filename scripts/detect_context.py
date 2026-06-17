"""Deterministic agentic-sdlc-pipeline context probe.

Why this exists: agentic-sdlc-pipeline Step 3 needs to know whether a workspace is
greenfield or brownfield and how many recognisable architectural layers it has,
so Claude can choose the right exploration strategy without reading every file.
Steps 6 and 15 need the same probe extended to dependency manifests and build
toolchains.  This script makes those decisions deterministic and machine-readable
rather than gut-feel, so results are diffable and stable across runs.

Design constraints:
- Pure stdlib only (argparse, json, pathlib, re, sys).  No third-party imports.
- Exit 0 ALWAYS — this is a classifier, not a blocking gate.
- Output: sorted flat `key=value` lines, one per line.
"""

import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SOURCE_EXTS = {
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".py", ".cs", ".java", ".go", ".rb", ".php", ".rs",
    ".kt", ".swift", ".vue", ".svelte",
}

# Directory names that signal an architectural layer worth exploring separately.
LAYER_HINTS = {
    "api", "server", "backend", "src", "lib", "ui", "frontend",
    "components", "web", "db", "data", "models", "services",
    "domain", "core", "controllers", "routes", "store", "public",
}

# Directories to skip during traversal.  Narrow set — only well-known noise dirs.
IGNORE = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", "coverage", ".opencode",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_source(path):
    """Return True if path is a source file with a recognised extension."""
    return path.suffix.lower() in SOURCE_EXTS


def _count_source_files(root):
    """Recursively count source files under `root`, skipping IGNORE dirs.

    OSError during traversal (unreadable subtree, symlink loop, a file locked by
    another process — common on Windows) is tolerated: count what is reachable and
    move on. The exit-0 classifier contract must hold even on a hostile tree, and a
    partial count keeps a real codebase from being misread as greenfield.
    """
    count = 0
    try:
        for item in root.rglob("*"):
            # Skip any path that has an IGNORE component.
            if any(part in IGNORE for part in item.parts):
                continue
            try:
                if item.is_file() and _is_source(item):
                    count += 1
            except OSError:
                continue
    except OSError:
        pass  # partial count survives an unreadable subtree
    return count


# ---------------------------------------------------------------------------
# Step 3 — default mode
# ---------------------------------------------------------------------------

def detect(paths):
    """Probe paths for greenfield/brownfield + layer structure (Step 3).

    Args:
        paths: list of str/Path — one or more workspace roots.

    Returns:
        dict with keys: context_detection, source_files, layers (list), explore_mode.
    """
    total_files = 0
    layer_set = set()

    for raw in paths:
        root = Path(raw)

        # --path points at a file directly: count as one source file, no layers.
        if root.is_file():
            if _is_source(root):
                total_files += 1
            continue

        if not root.is_dir():
            # Non-existent or unsupported; contribute 0.
            continue

        total_files += _count_source_files(root)

        # Layers: immediate children dirs only, must be in LAYER_HINTS and have >=1 source.
        try:
            children = list(root.iterdir())
        except OSError:
            children = []  # unreadable root: no detectable layers, never crash
        for child in children:
            try:
                if not child.is_dir() or child.name in IGNORE:
                    continue
                if child.name.lower() not in LAYER_HINTS:
                    continue
                # Lightweight check: at least one source file anywhere inside child.
                has_source = any(
                    _is_source(f)
                    for f in child.rglob("*")
                    if f.is_file() and not any(p in IGNORE for p in f.parts)
                )
            except OSError:
                continue  # unreadable child subtree: skip it, never crash
            if has_source:
                layer_set.add(child.name.lower())

    layers = sorted(layer_set)
    n = total_files

    context_detection = "brownfield" if n > 0 else "greenfield"

    if len(layers) >= 2:
        explore_mode = "parallel"
    elif n > 0:
        explore_mode = "single"
    else:
        explore_mode = "greenfield_inline"

    return {
        "context_detection": context_detection,
        "source_files": n,
        "layers": layers,
        "explore_mode": explore_mode,
    }


# ---------------------------------------------------------------------------
# Step 6 — --probe deps
# ---------------------------------------------------------------------------

def _parse_package_json(text):
    """Return True if package.json declares >=1 external dependency."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return False
    deps = data.get("dependencies", {})
    dev_deps = data.get("devDependencies", {})
    return bool(deps) or bool(dev_deps)


def _parse_requirements_txt(text):
    """Return True if requirements.txt has >=1 non-blank, non-comment line."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return True
    return False


def _parse_pyproject_toml(text):
    """Return True if pyproject.toml declares >=1 external dependency.

    Uses narrow regexes rather than a TOML parser so we stay pure stdlib on
    Python < 3.11.  We check two conventions:
      - PEP 621 / Hatch: `dependencies = [...]` array with >=1 entry.
      - Poetry: `[tool.poetry.dependencies]` table with >=1 key other than `python`.
    """
    # PEP 621 style: dependencies = ["requests>=2", ...]
    pep621 = re.search(r'^dependencies\s*=\s*\[([^\]]*)\]', text, re.MULTILINE | re.DOTALL)
    if pep621:
        entries = [e.strip().strip('"').strip("'") for e in pep621.group(1).split(",")]
        if any(e for e in entries):
            return True

    # Poetry style: [tool.poetry.dependencies] table
    poetry_section = re.search(
        r'\[tool\.poetry\.dependencies\](.*?)(?=^\[|\Z)',
        text,
        re.MULTILINE | re.DOTALL,
    )
    if poetry_section:
        body = poetry_section.group(1)
        for line in body.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith("["):
                # A real key=value line that is not just `python = "^3.x"`.
                key_match = re.match(r'^(\w[\w-]*)\s*=', stripped)
                if key_match and key_match.group(1).lower() != "python":
                    return True
    return False


def _parse_go_mod(text):
    """Return True if go.mod has a require directive."""
    return bool(re.search(r'^\s*require\b', text, re.MULTILINE))


def _parse_cargo_toml(text):
    """Return True if Cargo.toml has >=1 entry under [dependencies]."""
    section = re.search(
        r'\[dependencies\](.*?)(?=^\[|\Z)',
        text,
        re.MULTILINE | re.DOTALL,
    )
    if not section:
        return False
    body = section.group(1)
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return True
    return False


def _parse_csproj(text):
    """Return True if the .csproj file contains a PackageReference."""
    return "<PackageReference" in text


def _parse_gemfile(text):
    """Return True if Gemfile has a line starting with `gem `."""
    return any(line.strip().startswith("gem ") for line in text.splitlines())


def _parse_pom_xml(text):
    """Return True if pom.xml contains a <dependency> element."""
    return "<dependency>" in text


def _parse_composer_json(text):
    """Return True if composer.json has a non-empty require (ignoring sole `php` key)."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return False
    require = data.get("require", {})
    non_php = {k: v for k, v in require.items() if k.lower() != "php"}
    return bool(non_php)


# Map manifest filenames to their parsers.  Glob patterns handled separately.
_MANIFEST_PARSERS = {
    "package.json": _parse_package_json,
    "requirements.txt": _parse_requirements_txt,
    "pyproject.toml": _parse_pyproject_toml,
    "go.mod": _parse_go_mod,
    "Cargo.toml": _parse_cargo_toml,
    "Gemfile": _parse_gemfile,
    "pom.xml": _parse_pom_xml,
    "composer.json": _parse_composer_json,
}


def probe_deps(paths):
    """Scan paths for dependency manifests (Step 6).

    Returns:
        dict with keys: deps_probe ('external'|'stdlib_only'), manifests (list of str).
    """
    found_manifests = []
    has_external = False

    for raw in paths:
        root = Path(raw)
        if not root.is_dir():
            continue

        # Scan top-level manifest files (top-level only — no recursion, matching probe_toolchain).
        for name, parser in _MANIFEST_PARSERS.items():
            candidate = root / name
            if candidate.is_file():
                try:
                    text = candidate.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue  # unreadable manifest: skip, never crash
                if name not in found_manifests:
                    found_manifests.append(name)
                if parser(text):
                    has_external = True

        # .csproj files (glob, top-level only).
        try:
            csproj_files = list(root.glob("*.csproj"))
        except OSError:
            csproj_files = []
        for csproj in csproj_files:
            try:
                text = csproj.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            name = csproj.name
            if name not in found_manifests:
                found_manifests.append(name)
            if _parse_csproj(text):
                has_external = True

    return {
        "deps_probe": "external" if has_external else "stdlib_only",
        "manifests": sorted(found_manifests),
    }


# ---------------------------------------------------------------------------
# Step 15 — --probe toolchain
# ---------------------------------------------------------------------------

_PYTHON_TOOLCHAIN_FILES = {
    "pyproject.toml", "setup.cfg", "ruff.toml", ".ruff.toml", "mypy.ini", "tox.ini",
}
_NODE_SCRIPT_KEYS = {"build", "lint", "test", "typecheck"}


def _node_toolchain(root):
    """Return True if the root has node build tooling indicators."""
    # package.json with relevant scripts
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
            scripts = data.get("scripts", {})
            if any(k in _NODE_SCRIPT_KEYS for k in scripts):
                return True
        except (OSError, json.JSONDecodeError, ValueError):
            pass

    # tsconfig.json
    if (root / "tsconfig.json").is_file():
        return True

    # eslint config variants
    for pattern in (".eslintrc*", "eslint.config.*"):
        if any(root.glob(pattern)):
            return True

    return False


def probe_toolchain(paths):
    """Scan paths for lint/typecheck/build toolchain presence (Step 15).

    Returns:
        dict with keys: toolchain_probe ('present'|'absent'), toolchains (list of str).
    """
    detected = set()

    for raw in paths:
        root = Path(raw)
        if not root.is_dir():
            continue

        if _node_toolchain(root):
            detected.add("node")

        if any((root / f).is_file() for f in _PYTHON_TOOLCHAIN_FILES):
            detected.add("python")

        if any(root.glob("*.csproj")) or any(root.glob("*.sln")):
            detected.add("dotnet")

        if (root / "go.mod").is_file():
            detected.add("go")

        if (root / "Cargo.toml").is_file():
            detected.add("rust")

        if (root / "Makefile").is_file():
            detected.add("make")

    toolchains = sorted(detected)
    return {
        "toolchain_probe": "present" if toolchains else "absent",
        "toolchains": toolchains,
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def emit(fields):
    """Print sorted flat key=value lines.

    Each value is converted to str; lists are comma-joined.
    """
    for key in sorted(fields):
        val = fields[key]
        if isinstance(val, list):
            val = ",".join(val)
        print(f"{key}={val}")


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        description="Deterministic agentic-sdlc-pipeline context probe (stdlib only)."
    )
    p.add_argument(
        "--path",
        action="append",
        required=True,
        metavar="PATH",
        help="Workspace root to inspect (repeatable).",
    )
    p.add_argument(
        "--probe",
        choices=["deps", "toolchain"],
        default=None,
        help="Optional extended probe: 'deps' (Step 6) or 'toolchain' (Step 15).",
    )
    return p


def _safe_default(probe):
    """Conservative output if an OSError escapes the per-item guards (backstop only).

    Degrades VISIBLY (`detect_error=oserror`) rather than silently, and only for
    filesystem errors — a logic bug is NOT an OSError and still surfaces as a crash.
    """
    if probe == "deps":
        return {"deps_probe": "stdlib_only", "manifests": [], "detect_error": "oserror"}
    if probe == "toolchain":
        return {"toolchain_probe": "absent", "toolchains": [], "detect_error": "oserror"}
    return {
        "context_detection": "greenfield",
        "explore_mode": "greenfield_inline",
        "layers": [],
        "source_files": 0,
        "detect_error": "oserror",
    }


def main(argv=None):
    args = build_parser().parse_args(argv)
    paths = args.path

    try:
        if args.probe == "deps":
            result = probe_deps(paths)
            emit({
                "deps_probe": result["deps_probe"],
                "manifests": result["manifests"],
            })
        elif args.probe == "toolchain":
            result = probe_toolchain(paths)
            emit({
                "toolchain_probe": result["toolchain_probe"],
                "toolchains": result["toolchains"],
            })
        else:
            result = detect(paths)
            emit({
                "context_detection": result["context_detection"],
                "explore_mode": result["explore_mode"],
                "layers": result["layers"],
                "source_files": result["source_files"],
            })
    except OSError:
        # Backstop: per-item guards above tolerate the common unreadable-path cases;
        # if an OSError still escapes, degrade visibly to a safe default and honor the
        # exit-0 classifier contract rather than crash the pipeline that depends on it.
        emit(_safe_default(args.probe))

    return 0  # always exit 0 — classifier, not a gate


if __name__ == "__main__":
    sys.exit(main())
