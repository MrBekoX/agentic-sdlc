"""Normalised fingerprints of files, artifact bodies and named file sets, plus the no-git walk.

Contract §5. Content is hashed after removing one leading UTF-8 byte-order mark and turning CRLF
into LF, so a Windows checkout or an editor's BOM never reopens a step or a gate. Paths are
POSIX-style and relative to the project root. Glob matching is the runner's own translator
(`**`, `*`, `?`, `{a,b}`), case-sensitive on every platform, with no fnmatch case folding. The
package-tree and `.git` exclusions alone ignore ASCII case: on a case-insensitive file system
(Windows, default macOS) a project with a `Docs/` folder gets its package in `Docs/agentic-sdlc`,
and git and the walk report it with that spelling.

Only regular files are read. A symlink is fingerprinted by its target text and never followed (a
link to /dev/zero or a huge file elsewhere would hang or leak), a folder is "dir", any other
non-regular file (a FIFO would block a read forever) is "special", and a file that exists but
cannot be read is "unreadable". A missing file is the literal "absent" (contract).
"""
from __future__ import annotations

import functools
import hashlib
import os
import re
import stat
from pathlib import Path

from . import frontmatter
from .paths import AGENTIC_ROOT
from .textio import SdlcError, is_link_like, read_text

ABSENT = "absent"
DIR = "dir"
SPECIAL = "special"
UNREADABLE = "unreadable"
OUTSIDE = "outside"

WALK_LIMIT = 20000
# Skipped at any depth by the no-git walk; the package tree is skipped at the project root only.
WALK_SKIP_DIRS = frozenset([".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__"])
# Never a source or test change: the runner's own package tree and git's folder (contract §5).
EXCLUDED_ROOTS = (AGENTIC_ROOT, ".git")

_BOM = b"\xef\xbb\xbf"
_CHUNK = 1 << 20
_MAX_BRACE_EXPANSION = 1024
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def norm_bytes(b) -> bytes:
    """One leading UTF-8 BOM removed, every CRLF turned into LF. A lone CR is content."""
    data = bytes(b)
    if data.startswith(_BOM):
        data = data[len(_BOM):]
    return data.replace(b"\r\n", b"\n")


def _hash_regular_file(target: str) -> str:
    """sha256 of norm_bytes(file bytes), read in chunks so a large file never sits in memory."""
    digest = hashlib.sha256()
    carry = b""
    leading = True
    with open(target, "rb") as handle:
        while True:
            chunk = handle.read(_CHUNK)
            if not chunk:
                break
            data = carry + chunk
            if leading:
                if len(data) < len(_BOM) and _BOM.startswith(data):
                    carry = data  # may still turn into a BOM
                    continue
                leading = False
                if data.startswith(_BOM):
                    data = data[len(_BOM):]
            # A CR at the end of a chunk may pair with an LF at the start of the next one.
            if data.endswith(b"\r"):
                carry, data = b"\r", data[:-1]
            else:
                carry = b""
            digest.update(data.replace(b"\r\n", b"\n"))
    digest.update(norm_bytes(carry) if leading else carry)
    return digest.hexdigest()


def file_fp(path) -> str:
    """sha256 hex of the normalised bytes; "absent" when missing (see the module notes for links)."""
    target = os.fspath(path)
    try:
        info = os.lstat(target)
    except (FileNotFoundError, NotADirectoryError):
        return ABSENT
    except OSError:
        return UNREADABLE
    mode = info.st_mode
    if stat.S_ISLNK(mode):
        try:
            link = os.readlink(target)
        except OSError:
            return UNREADABLE
        return hashlib.sha256(b"symlink\0" + os.fsencode(link)).hexdigest()
    if stat.S_ISDIR(mode):
        return DIR
    if not stat.S_ISREG(mode):
        return SPECIAL
    try:
        return _hash_regular_file(target)
    except (FileNotFoundError, NotADirectoryError):
        return ABSENT  # removed between the stat and the read
    except OSError:
        return UNREADABLE


def body_fp(path) -> str:
    """sha256 hex of the text after the frontmatter block; "absent" when the file is missing.

    The body is read like every project artifact (BOM and CRLF normalised) and its trailing
    newlines are reduced to exactly one, the same form frontmatter.render writes, so the runner
    stamping its own frontmatter never moves a body (or gate) fingerprint. Bytes that are not
    UTF-8 are kept as they are (surrogateescape there and back), so two bodies that differ only
    in such bytes never share a fingerprint; valid UTF-8 hashes exactly as its text.
    """
    target = os.fspath(path)
    try:
        info = os.stat(target)
    except (FileNotFoundError, NotADirectoryError):
        return ABSENT
    except OSError:
        return UNREADABLE
    if stat.S_ISDIR(info.st_mode):
        return DIR
    if not stat.S_ISREG(info.st_mode):
        return SPECIAL
    try:
        text = read_text(target, errors="surrogateescape")
    except (FileNotFoundError, NotADirectoryError):
        return ABSENT
    except OSError:
        return UNREADABLE
    body = frontmatter.split(text)[1].rstrip("\n")
    canonical = body + "\n" if body else ""
    return hashlib.sha256(canonical.encode("utf-8", "surrogateescape")).hexdigest()


def _path_bytes(name: str) -> bytes:
    return name.encode("utf-8", "surrogateescape")


def _inside(name: str) -> bool:
    """True for a relative POSIX path that stays inside the project (no root, drive or `..`)."""
    if not name or name.startswith("/"):
        return False
    if os.name == "nt" and ("\\" in name or ":" in name):
        return False  # a drive, a UNC path or a stream name; none is a valid Windows file name
    return ".." not in name.split("/")


def set_fp(project, names, head) -> str:
    """sha256 hex over the HEAD commit and the sorted (path, file_fp) pairs of a named set.

    Order and duplicates do not matter. A member that is missing counts as "absent"; a name that
    would leave the project is never read (it counts as "outside").
    """
    root = Path(project)
    digest = hashlib.sha256()
    digest.update(b"head\0" + (head or "-").encode("utf-8") + b"\n")
    for name in sorted(set(names)):
        fp = file_fp(root.joinpath(*name.split("/"))) if _inside(name) else OUTSIDE
        digest.update(_path_bytes(name) + b"\0" + fp.encode("ascii") + b"\n")
    return digest.hexdigest()


# --- globs -------------------------------------------------------------------------------------

def _matching_brace(text: str, start: int) -> int:
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _split_top(text: str) -> list:
    parts, depth, start = [], 0, 0
    for index, char in enumerate(text):
        if char == "{":
            depth += 1
        elif char == "}" and depth:
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return parts


def _expand_braces(pattern: str, budget: int) -> list:
    """Bash-style brace expansion: `{a,b}` alternates, `{a}` and an unmatched `{` stay literal."""
    for start, char in enumerate(pattern):
        if char != "{":
            continue
        end = _matching_brace(pattern, start)
        if end < 0:
            continue
        options = _split_top(pattern[start + 1:end])
        if len(options) < 2:
            continue
        head, tail = pattern[:start], pattern[end + 1:]
        expanded = []
        for option in options:
            expanded.extend(_expand_braces(head + option + tail, budget))
            if len(expanded) > budget:
                raise ValueError("glob expands to more than %d patterns: %r" % (budget, pattern))
        return expanded
    return [pattern]


def _translate(pattern: str) -> str:
    """Regex for one brace-free glob.

    `**` as a whole segment: `**/` is zero or more folders, a trailing `/**` is everything inside
    (not the folder itself), `**` alone is everything. Any other `*` run matches within one
    segment, `?` one character other than `/`; every other character is literal.
    """
    out = []
    index, size = 0, len(pattern)
    while index < size:
        char = pattern[index]
        if char == "*":
            end = index
            while end < size and pattern[end] == "*":
                end += 1
            whole = (end - index >= 2 and (index == 0 or pattern[index - 1] == "/")
                     and (end == size or pattern[end] == "/"))
            if not whole:
                out.append("[^/]*")
                index = end
            elif end == size:
                out.append(".*" if index == 0 else ".+")
                index = end
            else:
                out.append("(?:.*/)?")
                index = end + 1
            continue
        out.append("[^/]" if char == "?" else re.escape(char))
        index += 1
    return "".join(out)


@functools.lru_cache(maxsize=256)
def _compiled(globs: tuple):
    alternatives = []
    for glob in globs:
        for expanded in _expand_braces(str(glob), _MAX_BRACE_EXPANSION):
            alternatives.append(_translate(expanded))
    if not alternatives:
        return re.compile(r"(?!)")
    return re.compile(r"(?:%s)\Z" % "|".join(alternatives), re.DOTALL)


def glob_match(path: str, pattern: str) -> bool:
    """True when the POSIX relative `path` matches `pattern`. ValueError for an exploding brace set."""
    return _compiled((pattern,)).match(path) is not None


def is_excluded(path: str) -> bool:
    """The package tree `docs/agentic-sdlc/**` and `.git/**` (each folder included) at the root,
    in any ASCII case (see the module notes)."""
    folded = path.translate(_ASCII_LOWER)
    return any(folded == root or folded.startswith(root + "/") for root in EXCLUDED_ROOTS)


def classify(paths, test_globs):
    """(source, tests): sorted, de-duplicated, excluded paths dropped; tests match `test_globs`."""
    matcher = _compiled(tuple(test_globs))
    source, tests = [], []
    for path in sorted(set(paths)):
        if is_excluded(path):
            continue
        (tests if matcher.match(path) else source).append(path)
    return source, tests


# --- no-git fallback ---------------------------------------------------------------------------

def _link_like(full: str) -> bool:
    """A symlink or a Windows junction (os.walk enters junctions before Python 3.12); a OneDrive
    Files On-Demand folder (also a reparse point) is walked."""
    return is_link_like(full)


def _key(rel: str) -> str:
    # An undecodable POSIX name keeps a JSON-safe key; its bytes are still read through `rel`.
    return rel.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def walk_snapshot(project, limit=WALK_LIMIT) -> dict:
    """{relative path: file_fp} for the project, sorted by path (contract §5, no git).

    Skips WALK_SKIP_DIRS at any depth and docs/agentic-sdlc (any ASCII case) at the root; never
    enters a linked folder (the link itself is an entry). More than `limit` entries raises
    SdlcError(2, "not_a_git_repo_and_too_large") before any file is hashed.
    """
    root = os.fspath(project)
    found = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        rel_dir = os.path.relpath(dirpath, root)
        rel_dir = "" if rel_dir == os.curdir else rel_dir.replace(os.sep, "/") + "/"
        enter = []
        for name in dirnames:
            rel = rel_dir + name
            if name in WALK_SKIP_DIRS or rel.translate(_ASCII_LOWER) == AGENTIC_ROOT:
                continue
            if _link_like(os.path.join(dirpath, name)):
                found.append(rel)
            else:
                enter.append(name)
        dirnames[:] = enter
        found.extend(rel_dir + name for name in filenames)
        if len(found) > limit:
            raise SdlcError(2, "not_a_git_repo_and_too_large")
    snapshot = {}
    for rel in sorted(found):
        snapshot[_key(rel)] = file_fp(os.path.join(root, *rel.split("/")))
    return snapshot


def snapshot_changed(project, baseline: dict, limit=WALK_LIMIT) -> list:
    """Sorted paths whose fingerprint differs from `baseline` (edited, added or removed)."""
    current = walk_snapshot(project, limit)
    return sorted(key for key in set(current) | set(baseline) if current.get(key) != baseline.get(key))
