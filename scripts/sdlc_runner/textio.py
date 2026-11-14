"""Text and JSON I/O for the runner: UTF-8 everywhere, LF on disk, atomic replaces.

Every runner write goes through write_text_atomic and every read of a project artifact through
read_text, so a Windows console code page, a CRLF checkout or an editor's byte-order mark never
changes what the runner writes, reads or hashes. Bytes that are not UTF-8 are refused by name
(`not_utf8:<path>`), never replaced, so a read-modify-write cannot turn a user's text into U+FFFD.
"""
from __future__ import annotations

import json
import os
import re
import stat
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_BOM = "﻿"
# Lone surrogates: what POSIX argv and file names carry for undecodable bytes (surrogateescape).
_LONE_SURROGATE = re.compile("[\ud800-\udfff]")
_MOUNT_POINT = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)
_TEMP_TRIES = 16


class SdlcError(Exception):
    """An error the user must see. `code` is the process exit code (2 usage/state, 3 halt, 4 refused)."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.message


def utf8_output() -> None:
    """Print UTF-8 whatever the console code page, so a non-ASCII path or quote never crashes a card."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def read_text(path, errors: str = "strict") -> str:
    """UTF-8 text with a leading byte-order mark removed and CRLF turned into LF.

    Bytes that are not UTF-8 raise SdlcError(2, "not_utf8:<path>") (the validator refuses such a
    file too). `errors="surrogateescape"` keeps each undecodable byte as its own lone surrogate
    instead, for a lossless fingerprint; nothing read that way is ever written back.
    """
    data = Path(path).read_bytes()
    try:
        text = data.decode("utf-8", errors=errors)
    except UnicodeDecodeError:
        raise SdlcError(2, "not_utf8:" + str(path)) from None
    if text.startswith(_BOM):
        text = text[1:]
    return text.replace("\r\n", "\n")


def is_link_like(path) -> bool:
    """A symlink or a Windows junction (a mount-point reparse point), judged without following it.

    Only the mount-point tag counts: a OneDrive Files On-Demand folder is a reparse point too.
    """
    try:
        info = os.lstat(os.fspath(path))
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    return getattr(info, "st_reparse_tag", 0) == _MOUNT_POINT


def _refuse_links(root: Path, folder: Path, target: Path) -> None:
    """SdlcError unless `folder` is `root` or below it with no linked folder in between."""
    try:
        rel = folder.relative_to(root)
    except ValueError:
        raise SdlcError(2, "outside_root:" + str(target)) from None
    if ".." in rel.parts:
        raise SdlcError(2, "outside_root:" + str(target))
    current = root
    for part in rel.parts:
        current = current / part
        if is_link_like(current):
            raise SdlcError(2, "linked_path:" + current.relative_to(root).as_posix())


_UMASK = []


def _default_mode(target: Path):
    """The temp file is created 0600; a new file gets the usual 0666 & ~umask, an existing one its own bits."""
    if os.name != "posix":
        return None
    try:
        return target.stat().st_mode & 0o7777
    except OSError:
        pass
    if not _UMASK:  # read once: os.umask can only be read by setting it
        current = os.umask(0o022)
        os.umask(current)
        _UMASK.append(current)
    return 0o666 & ~_UMASK[0]


def _create_temp(target: Path):
    """(fd, path) of a new temp file next to `target`, or SdlcError(2, "unwritable:<target>").

    A bounded O_EXCL loop, not tempfile.mkstemp: on Windows mkstemp retries a refused create up to
    os.TMP_MAX (2**31 - 1) times while the folder looks writable, which hangs for good under an
    ACL deny (seen 2026-10-22). Only a name clash is retried; any other refusal fails at once.
    """
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
             | getattr(os, "O_NOINHERIT", 0) | getattr(os, "O_NOFOLLOW", 0))
    for _ in range(_TEMP_TRIES):
        tmp = os.path.join(str(target.parent), "." + target.name + "." + os.urandom(6).hex() + ".tmp")
        try:
            return os.open(tmp, flags, 0o600), tmp
        except FileExistsError:
            continue
        except OSError:
            break
    raise SdlcError(2, "unwritable:" + str(target))


def write_text_atomic(path, text: str, within=None) -> None:
    """Write UTF-8 text with LF line endings through a temp file in the same directory.

    The target is replaced in one os.replace, so a reader or a killed runner leaves the old file or
    the new one, never half of either. Parent directories are created. An existing file keeps its
    permission bits; a link at the target itself is replaced, never followed. No fsync: it guards
    only against power loss and costs about 1.8 s per call on a WSL2 ext4 disk (measured
    2026-10-22); a file lost that way reads as corrupt (exit 2), not stale.

    `within` (a folder, usually the package dir): the target must lie below it and no existing
    folder between the two may be a symlink or a junction, so a committed link cannot send a write
    outside the package (SdlcError 2 "outside_root:<path>" / "linked_path:<relative folder>").
    Text that cannot be UTF-8 (a lone surrogate) is SdlcError(2, "unencodable_text:<path>"); a
    write the file system refuses is SdlcError(2, "unwritable:<path>"). The old file is kept and
    no temp file is left either way.
    """
    target = Path(path)
    if within is not None:
        _refuse_links(Path(within), target.parent, target)
    try:
        data = text.encode("utf-8")
    except UnicodeEncodeError:
        raise SdlcError(2, "unencodable_text:" + str(target)) from None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise SdlcError(2, "unwritable:" + str(target)) from None
    fd, tmp = _create_temp(target)
    try:
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
        finally:
            os.close(fd)
        mode = _default_mode(target)
        if mode is not None:
            os.chmod(tmp, mode)
        _replace(tmp, str(target))
    except BaseException as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        if isinstance(exc, OSError):
            raise SdlcError(2, "unwritable:" + str(target)) from None
        raise


def _replace(src: str, dst: str) -> None:
    # On Windows a scanner or editor holding the target open makes os.replace fail for a moment.
    attempts = 6 if sys.platform == "win32" else 1
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.05 * (attempt + 1))


def dumps_json(obj, **kwargs) -> str:
    """json.dumps with UTF-8 characters kept and each lone surrogate written as a `\\udcXX` escape.

    A lone surrogate (an undecodable byte in a POSIX argv) cannot be encoded as UTF-8; as an escape
    it stays valid UTF-8 JSON and json.loads gives the same string back.
    """
    text = json.dumps(obj, ensure_ascii=False, **kwargs)
    return _LONE_SURROGATE.sub(lambda m: "\\u%04x" % ord(m.group(0)), text)


def read_json(path) -> object:
    return json.loads(read_text(path))


def write_json_atomic(path, obj, within=None) -> None:
    """Sorted keys, two-space indent, UTF-8 characters kept, one trailing newline."""
    write_text_atomic(path, dumps_json(obj, sort_keys=True, indent=2) + "\n", within=within)


def now_iso() -> str:
    """Current UTC time as 2026-10-22T18:00:00Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
