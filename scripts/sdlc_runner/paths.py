"""Where things live: the plugin root, the user's project root, a work package, and safe names.

The runner finds its own root from __file__; state lives in the user's project, never in the
plugin root (Codex runs a cached copy; Claude Code reads the marketplace folder).
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path

from .textio import SdlcError, is_link_like

AGENTIC_ROOT = "docs/agentic-sdlc"
GIT_TIMEOUT = 15

_WORK_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_NOT_SLUG_CHAR = re.compile(r"[^a-z0-9-]")
# Windows refuses these as file or folder names, with or without an extension, so a package or
# artifact named after one cannot be created or checked out there.
_WINDOWS_DEVICES = frozenset(
    ["con", "prn", "aux", "nul"] + ["com%d" % i for i in range(1, 10)] + ["lpt%d" % i for i in range(1, 10)]
)
_WIN_ABSOLUTE = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\|//)")
_RESOLVER = []


def plugin_root() -> Path:
    """The plugin root: scripts/sdlc_runner/paths.py -> scripts -> root."""
    return Path(__file__).resolve().parents[2]


def _resolver():
    """scripts/resolve_work_package.py, loaded by path so neither sys.path nor the cwd can swap it."""
    if not _RESOLVER:
        source = plugin_root() / "scripts" / "resolve_work_package.py"
        spec = importlib.util.spec_from_file_location("_sdlc_resolve_work_package", str(source))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _RESOLVER.append(module)
    return _RESOLVER[0]


def _is_device_name(name: str) -> bool:
    return name.split(".", 1)[0].lower() in _WINDOWS_DEVICES


def valid_slug(s) -> bool:
    """The resolver's slug rule (kebab-case, at most 64 characters, not a reserved folder name).

    Stricter in two places: a trailing newline (the resolver's `$` lets one through) and Windows
    device names such as `con` or `nul` are refused.
    """
    if not isinstance(s, str) or "\n" in s or _is_device_name(s):
        return False
    return bool(_resolver().is_valid_slug(s))


def valid_work_id(s) -> bool:
    """`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`, no `..`, and no Windows device name before the first dot."""
    return (isinstance(s, str) and _WORK_ID_RE.fullmatch(s) is not None and ".." not in s
            and not _is_device_name(s))


def slug_from_work_id(work_id: str) -> str:
    """The default slug: lowercased, every other character turned into `-`, trimmed. May be invalid."""
    slug = _NOT_SLUG_CHAR.sub("-", str(work_id).lower()).strip("-")
    return slug[:64].rstrip("-")


def _printable(value) -> str:
    return str(value).replace("\r", "\\r").replace("\n", "\\n")


def package_dir(project, slug: str) -> Path:
    """<project>/docs/agentic-sdlc/<slug>; an invalid slug is a usage error, never a path.

    A folder on the way (`docs`, `docs/agentic-sdlc` or the package itself) that is a symlink or a
    junction is SdlcError(2, "linked_package_path:<relative path>"): a cloned repository could
    otherwise send state.json, the logs and the lock outside the project.
    """
    if not valid_slug(slug):
        raise SdlcError(2, "bad_slug:" + _printable(slug))
    current = Path(project)
    parts = AGENTIC_ROOT.split("/") + [slug]
    for depth, part in enumerate(parts, start=1):
        current = current / part
        if is_link_like(current):
            raise SdlcError(2, "linked_package_path:" + "/".join(parts[:depth]))
    return current


def _inside_folder(path: str, folder: str) -> bool:
    try:
        real = os.path.normcase(os.path.realpath(path))
        base = os.path.normcase(os.path.realpath(folder))
        return os.path.commonpath([real, base]) == base
    except (OSError, ValueError):  # ValueError: different drives
        return False


def _bare_name(name) -> bool:
    """A program name with no folder, drive, stream or parent part in it."""
    if not isinstance(name, str) or name in ("", ".", "..") or "\0" in name:
        return False
    if "/" in name or "\\" in name or os.path.isabs(name):
        return False
    return not (sys.platform == "win32" and ":" in name)


def resolve_program(name: str, shims: bool = False, exclude=None):
    """Absolute path of `name` from an absolute PATH entry, or None.

    `name` must be a bare program name: one with a folder, a drive or a stream in it is refused,
    so it can never name a file outside PATH. Relative PATH entries are skipped and the current
    directory is never searched (Python's shutil.which on Windows looks there first before 3.12).
    `exclude` (a folder, usually the project root) also skips every PATH entry inside it, so a
    program planted in the project cannot answer even when a project folder (an activated
    .venv, direnv's PATH_add) is on PATH. On Windows a bare name tries `.exe` and `.com`, plus
    `.cmd` and `.bat` only when `shims` is true (contract §12: program names on the run
    allowlist); an explicit extension must be one of those.
    """
    if not _bare_name(name):
        return None
    win = sys.platform == "win32"
    if win:
        allowed = [".exe", ".com"] + ([".cmd", ".bat"] if shims else [])
        names = [name] if os.path.splitext(name)[1].lower() in allowed else [name + ext for ext in allowed]
    else:
        names = [name]
    excluded = None if exclude is None else os.fspath(exclude)
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if win:
            entry = entry.strip().strip('"')
            if not _WIN_ABSOLUTE.match(entry):
                continue
        elif not entry.startswith("/"):
            continue
        if excluded is not None and _inside_folder(entry, excluded):
            continue
        for candidate in names:
            full = os.path.join(entry, candidate)
            if os.path.isfile(full) and (win or os.access(full, os.X_OK)):
                return full
    return None


def _git_toplevel(cwd: Path):
    """The work-tree top of `cwd`, asked through gitinfo.run_git (same hardening as every git call:
    GIT_DIR, GIT_WORK_TREE and the other repository-location variables dropped, no hooks, no
    fsmonitor, no git planted below `cwd`), or None."""
    from . import gitinfo  # gitinfo imports this module

    try:
        proc = gitinfo.run_git(cwd, "rev-parse", "--show-toplevel", timeout=GIT_TIMEOUT)
    except SdlcError:
        return None
    top = proc.stdout.strip()
    if proc.returncode != 0 or not top:
        return None
    return Path(top).resolve()


def project_root(cwd, override=None) -> Path:
    """`override` when given; else the git work-tree top of `cwd`; else `cwd` itself."""
    if override is not None:
        return Path(override).resolve()
    base = Path(cwd).resolve()
    top = _git_toplevel(base)
    return top if top is not None else base
