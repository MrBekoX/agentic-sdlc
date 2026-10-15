"""Install, update, or uninstall the Cursor copy of agentic-sdlc.

The destination is Cursor's documented local-plugin directory, resolved from the
current user's home when this command runs. Pass --dest to place that copy
somewhere else. Files the installer did not write are left in place, including
on uninstall. This does not submit the plugin to the Cursor Marketplace and it
does not edit Cursor settings outside the destination directory.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_cursor_plugin import validate


RECEIPT = ".cursor-plugin/install-receipt.json"
SKIP_DIRECTORIES = {
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".venv", "venv", "node_modules", ".claude", ".codex", ".zcode", ".opencode",
    ".worktrees", "artifacts", "eval-results", "reviews", "dist", "build",
    "tests", ".github",
}
SKIP_FILES = {".DS_Store", "install-receipt.json"}
PYTHON_PROBE = "import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)"


def default_destination() -> Path:
    """Cursor's documented per-user local plugin folder, resolved at runtime."""
    return Path.home() / ".cursor" / "plugins" / "local" / "agentic-sdlc"


def _which(name: str) -> str | None:
    return shutil.which(name)


def dependency_errors() -> list[str]:
    """Missing runtime tools. The messages name the tool and the next action."""
    errors = []
    node = _which("node")
    if node is None:
        errors.append(
            "error=node_missing: install Node.js 22 or newer and make the node command available on PATH. "
            "Cursor hooks cannot start the shared guards without it."
        )
    else:
        probe = subprocess.run([node, "-e", "process.exit(0)"], capture_output=True, timeout=20)
        if probe.returncode != 0:
            errors.append("error=node_unusable: the node command on PATH did not run. Reinstall Node.js and reopen the terminal.")
    python_ok = False
    for argv in (["python3", "-c", PYTHON_PROBE], ["python", "-c", PYTHON_PROBE], ["py", "-3", "-c", PYTHON_PROBE]):
        if _which(argv[0]) is None:
            continue
        probe = subprocess.run(argv, capture_output=True, timeout=20)
        if probe.returncode == 0:
            python_ok = True
            break
    if not python_ok:
        errors.append(
            "error=python_missing: install Python 3.8 or newer as python3, python, or py -3. "
            "Skill helpers such as scripts/validate_artifacts.py need it."
        )
    if _which("git") is None:
        errors.append("error=git_missing: install Git and make the git command available on PATH. Branch and commit guards read the repository with it.")
    return errors


def _inside(parent: Path, child: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _package_files(package: Path) -> list[str]:
    files = []
    for dirpath, dirnames, filenames in os.walk(package, followlinks=False):
        current = Path(dirpath)
        dirnames[:] = sorted(
            name for name in dirnames
            if name not in SKIP_DIRECTORIES and not (current / name).is_symlink()
        )
        for name in sorted(filenames):
            if name in SKIP_FILES or name.endswith(".pyc"):
                continue
            path = current / name
            if path.is_symlink():
                try:
                    path.resolve().relative_to(package.resolve())
                except ValueError:
                    continue
            if not path.is_file():
                continue
            files.append(path.relative_to(package).as_posix())
    return files


def _load_receipt(dest: Path) -> list[str]:
    file = dest / RECEIPT
    if not file.is_file():
        return []
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    managed = data.get("managed") if isinstance(data, dict) else None
    if not isinstance(managed, list):
        return []
    return [item for item in managed if isinstance(item, str) and _safe_receipt_path(item)]


def _safe_receipt_path(value: str) -> bool:
    parts = value.split("/")
    return bool(value) and ".." not in parts and not value.startswith("/") and "\\" not in value


def _prune_empty(dest: Path, relative: str) -> None:
    current = (dest / relative).parent
    while current != dest and current.is_dir():
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def install(package: Path, dest: Path) -> tuple[int, list[str]]:
    package = package.resolve()
    dest = dest.resolve()
    if not (package / ".cursor-plugin" / "plugin.json").is_file():
        return 1, [
            "error=cursor_package_invalid: the package directory has no .cursor-plugin/plugin.json",
            "cursor_install=failed",
        ]
    if dest == package or _inside(package, dest) or _inside(dest, package):
        return 1, [
            "error=cursor_dest_overlaps_package: choose a destination outside the package directory",
            "cursor_install=failed",
        ]
    previous = set(_load_receipt(dest))
    managed = _package_files(package)
    dest.mkdir(parents=True, exist_ok=True)
    for relative in managed:
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(package / relative, target)
    stale = previous - set(managed) - {RECEIPT}
    for relative in sorted(stale):
        target = dest / relative
        if target.is_file() or target.is_symlink():
            target.unlink()
            _prune_empty(dest, relative)
    receipt = {
        "name": "agentic-sdlc",
        "managed": managed,
    }
    receipt_path = dest / RECEIPT
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return 0, [
        f"cursor_plugin_dest={dest}",
        f"managed_files={len(managed)}",
        "cursor_install=installed",
    ]


def _report_installed_package(dest: Path) -> int:
    errors = validate(dest.resolve())
    for error in errors:
        print("error=" + error)
    print("cursor_plugin=" + ("failed" if errors else "passed"))
    return 1 if errors else 0


def uninstall(dest: Path) -> tuple[int, list[str]]:
    dest = dest.resolve()
    managed = _load_receipt(dest)
    if not managed:
        return 1, [
            "error=cursor_install_receipt_missing: uninstall refused because this directory has no agentic-sdlc install receipt",
            "cursor_uninstall=failed",
        ]
    for relative in managed:
        target = dest / relative
        if target.is_file() or target.is_symlink():
            target.unlink()
            _prune_empty(dest, relative)
    receipt = dest / RECEIPT
    if receipt.is_file():
        receipt.unlink()
    _prune_empty(dest, RECEIPT)
    if dest.is_dir():
        try:
            dest.rmdir()
        except OSError:
            return 0, ["cursor_uninstall=removed_managed_files", f"cursor_plugin_dest={dest}"]
    return 0, ["cursor_uninstall=removed"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "update", "uninstall"))
    parser.add_argument("--package", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--dest", type=Path)
    parser.add_argument("--skip-dependency-check", action="store_true")
    args = parser.parse_args(argv)
    dest = (args.dest or default_destination()).expanduser()
    if args.action == "uninstall":
        code, lines = uninstall(dest)
        for line in lines:
            print(line)
        return code
    if not args.skip_dependency_check:
        errors = dependency_errors()
        if errors:
            for error in errors:
                print(error)
            print("cursor_install=failed")
            return 1
    code, lines = install(args.package, dest)
    for line in lines:
        print(line)
    if code != 0:
        return code
    return _report_installed_package(dest)


if __name__ == "__main__":
    raise SystemExit(main())
