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
import stat
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_release import ReleaseError, local_package_files
from check_cursor_plugin import _relative_path, validate


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
    """The files a Cursor copy takes (RL-3): a checkout's committed tree, never a private or local file.

    Selection is the release builder's: `git ls-files` for a checkout, a walk for an extracted
    package, and no path in a release exclusion class (`.env`, `settings.local.json`, `AGENTS.md`,
    `CLAUDE.md`, session reports, audit dumps, symlinks).
    """
    return [relative for relative in local_package_files(package, skip=SKIP_DIRECTORIES)
            if relative.rsplit("/", 1)[-1] not in SKIP_FILES and not relative.endswith(".pyc")]


def _read_receipt(dest: Path) -> list[str] | None:
    """The managed paths of a valid agentic-sdlc receipt, or None when there is none."""
    file = dest / RECEIPT
    if not file.is_file():
        return None
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("name") != "agentic-sdlc":
        return None
    managed = data.get("managed")
    if not isinstance(managed, list):
        return None
    return [item for item in managed if isinstance(item, str) and _safe_receipt_path(item)]


def _load_receipt(dest: Path) -> list[str]:
    return _read_receipt(dest) or []


def _safe_receipt_path(value: str) -> bool:
    # RL-10: the manifest checker's rule rejects drive paths (C:/, c:x), UNC and rooted forms,
    # '..' and control characters; a backslash is never part of a path this installer writes.
    return _relative_path(value) and "\\" not in value


def _managed_target(dest: Path, relative: str) -> Path | None:
    """dest/relative, or None when a symlinked folder would place it outside the destination."""
    target = dest / relative
    return target if _inside(dest, target.parent) else None


# Deleting through folder descriptors opened with O_NOFOLLOW never follows a link, even one swapped
# in after a check (R2-RL-2). Windows has no dir_fd support and keeps the checked path-based delete.
_NO_FOLLOW_DELETE = (hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY")
                     and {os.open, os.stat, os.unlink, os.rmdir} <= os.supports_dir_fd)


def _remove_managed(dest: Path, relative: str) -> None:
    """Delete dest/relative (a file or a link, never what a link points to), then its emptied folders."""
    if not _NO_FOLLOW_DELETE:
        target = _managed_target(dest, relative)
        if target is not None and (target.is_file() or target.is_symlink()):
            target.unlink()
            _prune_empty(dest, relative)
        return
    parts = [part for part in relative.split("/") if part not in ("", ".")]
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    folders = []
    try:
        folders.append(os.open(str(dest), flags))
        for part in parts[:-1]:
            # A link in place of a folder fails here (ELOOP or ENOTDIR), so nothing outside is touched.
            folders.append(os.open(part, flags, dir_fd=folders[-1]))
        mode = os.stat(parts[-1], dir_fd=folders[-1], follow_symlinks=False).st_mode
        if not (stat.S_ISREG(mode) or stat.S_ISLNK(mode)):
            return
        os.unlink(parts[-1], dir_fd=folders[-1])
        for index in range(len(parts) - 2, -1, -1):
            os.rmdir(parts[index], dir_fd=folders[index])  # stops at the first folder that is not empty
    except OSError:
        return
    finally:
        for folder in folders:
            os.close(folder)


def _write_receipt(dest: Path, managed: list[str]) -> None:
    receipt_path = dest / RECEIPT
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps({"name": "agentic-sdlc", "managed": managed}, indent=2) + "\n",
                            encoding="utf-8")


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
    receipt = _read_receipt(dest)
    # RL-1: never write over, and so never later delete, a file this installer did not write. A
    # destination without our receipt must be empty; on an update, a path the new package adds must
    # not already hold a user's file.
    if receipt is None and dest.is_dir() and any(dest.iterdir()):
        return 1, [
            "error=cursor_dest_not_empty: the destination holds files but no agentic-sdlc install receipt; "
            "choose an empty or new directory",
            "cursor_install=failed",
        ]
    previous = set(receipt or [])
    try:
        managed = _package_files(package)
    except ReleaseError:
        return 1, ["error=cursor_package_unreadable: git could not list the package checkout", "cursor_install=failed"]
    # A path the receipt does not own must not exist yet, and no path may land outside the
    # destination through a symlinked folder or be a link itself, which copy2 and the receipt write
    # would follow (R2-RL-2).
    conflicts = [relative for relative in [*managed, RECEIPT] if _managed_target(dest, relative) is None
                 or (dest / relative).is_symlink()
                 or (relative not in previous and relative != RECEIPT and (dest / relative).exists())]
    if conflicts:
        return 1, [f"error=cursor_dest_file_unmanaged:{relative}" for relative in conflicts] + [
            "cursor_install=failed"]
    dest.mkdir(parents=True, exist_ok=True)
    # The receipt names every path this run may write before the first copy, so an interrupted
    # install leaves a destination that the next install or an uninstall still recognises.
    _write_receipt(dest, sorted(previous | set(managed)))
    for relative in managed:
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(package / relative, target)
    stale = previous - set(managed) - {RECEIPT}
    for relative in sorted(stale):
        _remove_managed(dest, relative)
    _write_receipt(dest, managed)
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
        _remove_managed(dest, relative)
    _remove_managed(dest, RECEIPT)
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
