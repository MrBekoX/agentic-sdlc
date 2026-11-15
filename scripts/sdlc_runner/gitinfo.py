"""Git facts and change lists for the runner, with every git call hardened (contract §1, §5).

git is resolved from an absolute PATH entry only, never the cwd and never a PATH entry inside the
folder the call runs in (the project), and runs with:
- no fsmonitor program (`-c core.fsmonitor=`) and no repository hooks (`core.hooksPath` points at
  an empty folder this process creates), so a cloned repository cannot run code through a query;
- no optional index writes (`--no-optional-locks`), so a read-only `.git` (the Codex sandbox)
  still answers and the runner never races the user's own git for `index.lock`;
- no pager, no colour, `diff.relative=false`, no network (`protocol.allow=never`, no lazy fetch);
- English messages (`LC_ALL=C`), so a failure reason can be named on any locale;
- without the repository-location variables a parent git exports (GIT_DIR, GIT_INDEX_FILE, ...),
  which would otherwise point every query at another repository;
- `--no-ext-diff --no-textconv` on every diff.
Not closable by a setting: a repository `filter.<name>.clean` driver can still run when git
compares worktree files (the same residual hooks/git-exec.mjs documents).

Paths come back POSIX-style and relative to the project folder, even when that folder is below the
work-tree top. Output is decoded as UTF-8 with replacement, so a POSIX file name that is not UTF-8
is listed with U+FFFD and fingerprints as "absent".
"""
from __future__ import annotations

import atexit
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from . import fingerprint, paths
from .textio import SdlcError

GIT_TIMEOUT = 120
# `git rev-parse --local-env-vars` (git 2.53): variables that relocate the repository, its index,
# its objects or its configuration. They are dropped from every git child's environment.
LOCAL_ENV_VARS = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
    "GIT_OBJECT_DIRECTORY", "GIT_DIR", "GIT_WORK_TREE", "GIT_IMPLICIT_WORK_TREE", "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE", "GIT_NO_REPLACE_OBJECTS", "GIT_REPLACE_REF_BASE", "GIT_PREFIX",
    "GIT_SHALLOW_FILE", "GIT_COMMON_DIR",
)
_SHA_RE = re.compile(r"[0-9a-fA-F]{4,64}")
_NO_HOOKS = []
_NO_HOOKS_LOCK = threading.Lock()


def git_available() -> bool:
    """True when a git program is found on an absolute PATH entry (run_git may still refuse one
    that lies inside the project: git_missing)."""
    return paths.resolve_program("git") is not None


def _remove_dir(path: str) -> None:
    try:
        os.rmdir(path)
    except OSError:
        pass


def _make_private_dir():
    """An empty 0700 folder in the temp dir, or None.

    Not tempfile.mkdtemp: on Windows it retries a refused create up to os.TMP_MAX (2**31 - 1)
    times when the folder looks writable, which hangs for good under an ACL deny (seen 2026-10-22).
    """
    try:
        base = tempfile.gettempdir()
    except (OSError, ValueError):
        return None
    for _ in range(16):
        candidate = os.path.join(base, "sdlc-no-hooks-" + os.urandom(8).hex())
        try:
            os.mkdir(candidate, 0o700)
        except FileExistsError:
            continue
        except OSError:
            return None
        return candidate
    return None


def _no_hooks_dir() -> str:
    """The folder core.hooksPath points at: empty, created once per process, removed at exit."""
    with _NO_HOOKS_LOCK:
        if _NO_HOOKS and os.path.isdir(_NO_HOOKS[0]):
            return _NO_HOOKS[0]
        made = _make_private_dir()
        if made is None:
            # No usable temp dir: a folder inside the runner that is never created. An empty
            # `core.hooksPath=` would instead send the lookup to `/<hook>` (a drive root on Windows).
            return str(paths.plugin_root() / "scripts" / "sdlc_runner" / "no-repository-hooks")
        atexit.register(_remove_dir, made)
        _NO_HOOKS[:] = [made]
        return made


def _git_env() -> dict:
    env = dict(os.environ)
    for name in LOCAL_ENV_VARS:
        env.pop(name, None)
    env.update({
        "LC_ALL": "C",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_LAZY_FETCH": "1",
        "NoDefaultCurrentDirectoryInExePath": "1",
    })
    return env


def run_git(project, *args, timeout=GIT_TIMEOUT) -> subprocess.CompletedProcess:
    """Run `git <args>` in `project` with the hardening above and return the completed process.

    A non-zero exit is returned for the caller to judge. No git on PATH outside `project` raises
    SdlcError(2, "git_missing"); a timeout SdlcError(2, "git_timeout:<subcommand>"); a spawn
    failure SdlcError(2, "git_failed:<subcommand>:<error class>").
    """
    git = paths.resolve_program("git", exclude=project)
    if git is None:
        raise SdlcError(2, "git_missing")
    argv = [str(a) for a in args]
    if argv and argv[0] == "diff":
        argv = ["diff", "--no-ext-diff", "--no-textconv"] + argv[1:]
    command = [git, "--no-pager", "--no-optional-locks",
               "-c", "core.fsmonitor=", "-c", "core.hooksPath=" + _no_hooks_dir(),
               "-c", "color.ui=never", "-c", "diff.relative=false", "-c", "protocol.allow=never"]
    name = argv[0] if argv else "git"
    try:
        return subprocess.run(
            command + argv, cwd=str(project), env=_git_env(), stdin=subprocess.DEVNULL,
            capture_output=True, shell=False, text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise SdlcError(2, "git_timeout:" + name) from None
    except (OSError, subprocess.SubprocessError) as exc:
        raise SdlcError(2, "git_failed:%s:%s" % (name, type(exc).__name__)) from None


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line[:200]
    return "no output"


def _failure_reason(stderr: str) -> str:
    text = (stderr or "").lower()
    if "not a git repository" in text:
        return "not_a_repo"
    if "dubious ownership" in text:
        return "dubious_ownership"
    return "git_error"


def _head(project):
    proc = run_git(project, "rev-parse", "-q", "--verify", "HEAD^{commit}")
    sha = proc.stdout.strip()
    return sha if proc.returncode == 0 and _SHA_RE.fullmatch(sha) else None


def head_sha(project):
    """The HEAD commit id, or None (no git, not a repository, unborn or unreadable HEAD)."""
    if not git_available():
        return None
    try:
        return _head(project)
    except SdlcError:
        return None


def _open_exclusive(path: str) -> int:
    return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)


def _dir_accepts_file(directory) -> bool:
    """Create and delete one new file in `directory` (a single O_EXCL create: never a retry loop)."""
    probe = os.path.join(str(directory), ".sdlc-write-probe-%d-%s" % (os.getpid(), os.urandom(6).hex()))
    try:
        handle = _open_exclusive(probe)
    except OSError:
        return False
    try:
        os.close(handle)
    except OSError:
        pass
    attempts = 4 if sys.platform == "win32" else 1  # a scanner may hold a new file for a moment
    for attempt in range(attempts):
        try:
            os.unlink(probe)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            if attempt == attempts - 1:
                return False
            time.sleep(0.05 * (attempt + 1))
    return False


def facts(project) -> dict:
    """Git facts for `start`; never raises.

    {"repo", "unborn", "head", "branch", "detached", "writable", "reason"}: `writable` is true when
    the git dir (and the common dir of a linked worktree) accepts a temp file create+delete;
    `reason` is None, or a named reason the facts are partial: git_missing, project_missing,
    not_a_repo, not_a_work_tree, dubious_ownership, head_unreadable, git_error, or a run_git error
    message such as git_timeout:rev-parse.
    """
    result = {"repo": False, "unborn": False, "head": None, "branch": None,
              "detached": False, "writable": False, "reason": None}
    root = Path(project)
    if not git_available():
        result["reason"] = "git_missing"
        return result
    if not root.is_dir():
        result["reason"] = "project_missing"
        return result
    try:
        where = run_git(root, "rev-parse", "--is-inside-work-tree", "--absolute-git-dir", "--git-common-dir")
        if where.returncode != 0:
            result["reason"] = _failure_reason(where.stderr)
            return result
        lines = where.stdout.splitlines()
        if len(lines) < 3 or lines[0].strip() != "true":
            result["reason"] = "not_a_work_tree"
            return result
        result["repo"] = True
        git_dirs = [Path(lines[1].strip())]
        common = Path(lines[2].strip())
        git_dirs.append(common if common.is_absolute() else root / common)
        result["head"] = _head(root)
        symbolic = run_git(root, "symbolic-ref", "-q", "HEAD")
        if symbolic.returncode == 0:
            ref = symbolic.stdout.strip()
            result["branch"] = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
        elif symbolic.returncode == 1:
            result["detached"] = True  # HEAD names a commit, not a branch
        else:
            result["reason"] = "head_unreadable"
        if result["head"] is None:
            if result["branch"] is not None:
                result["unborn"] = True  # HEAD names a branch with no commit yet
            else:
                result["reason"] = "head_unreadable"
    except SdlcError as exc:
        result["reason"] = exc.message
        return result
    seen = []
    for directory in git_dirs:
        resolved = os.path.normcase(os.path.abspath(str(directory)))
        if resolved not in seen:
            seen.append(resolved)
    result["writable"] = all(_dir_accepts_file(directory) for directory in seen)
    return result


def _parse_status_z(raw: str) -> list:
    """Paths from `git status --porcelain=v1 -z`: `XY path`, and for a rename or copy `XY new\\0old`.

    A rename lists the new path and the old one (the old path is gone, which is a change); a copy
    lists only the new path. A trailing `/` (an untracked nested repository) is dropped.
    """
    records = raw.split("\0")
    found = []
    index = 0
    while index < len(records):
        entry = records[index]
        index += 1
        if len(entry) < 4:
            continue  # the empty record after the last NUL
        status, name = entry[:2], entry[3:]
        found.append(name.rstrip("/"))
        if "R" in status or "C" in status:
            if index < len(records):
                original = records[index]
                index += 1
                if "R" in status and original:
                    found.append(original.rstrip("/"))
    return found


def _check(proc: subprocess.CompletedProcess, name: str) -> None:
    if proc.returncode != 0:
        raise SdlcError(2, "git_failed:%s:%s" % (name, _first_line(proc.stderr)))


def _prefix(project) -> str:
    """The project folder relative to the work-tree top ("" at the top, else "sub/dir/")."""
    proc = run_git(project, "rev-parse", "--show-prefix")
    if proc.returncode != 0:
        if _failure_reason(proc.stderr) == "not_a_repo":
            raise SdlcError(2, "not_a_git_repo")
        raise SdlcError(2, "git_failed:rev-parse:" + _first_line(proc.stderr))
    return proc.stdout.rstrip("\r\n")


def _printable(value) -> str:
    return repr(value)[:80]


def changed_paths(project, base=None) -> list:
    """Sorted changed paths relative to `project` (contract §5).

    `git status --porcelain=v1 -z --untracked-files=all` (renames off, so a moved file lists its
    old and new path whatever the user's rename settings), plus `git diff --name-only -z <base>`
    when `base` is given, without docs/agentic-sdlc/** and .git/**. `base` must be a commit id
    (hex); anything else is SdlcError(2, "bad_base_commit:..."), so it can never reach git as an
    option. Outside a repository: SdlcError(2, "not_a_git_repo").
    """
    if base is not None and not (isinstance(base, str) and _SHA_RE.fullmatch(base)):
        raise SdlcError(2, "bad_base_commit:" + _printable(base))
    root = Path(project)
    prefix = _prefix(root)
    status = run_git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames")
    _check(status, "status")
    names = set(_parse_status_z(status.stdout))
    if base is not None:
        diff = run_git(root, "diff", "--name-only", "-z", "--no-renames", base, "--")
        _check(diff, "diff")
        names.update(name for name in diff.stdout.split("\0") if name)
    changed = set()
    for name in names:
        if prefix:
            if not name.startswith(prefix):
                continue
            name = name[len(prefix):]
        if name and not fingerprint.is_excluded(name):
            changed.add(name)
    return sorted(changed)
