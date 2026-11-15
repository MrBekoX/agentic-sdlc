"""Hash-chained JSONL logs (transitions.jsonl, runs.jsonl, approvals.jsonl, ...).

Each line is one JSON object `{"seq": n, "ts": "...Z", "kind": ..., <payload>, "prev": <hex>}`;
`prev` is the sha256 of the previous line (64 zeros for the first). A line is hashed after a
leading byte-order mark and a trailing CR are removed, so a CRLF checkout keeps the chain.

A crash can leave a final fragment without its newline. When that fragment is not a JSON object it
is a torn write: readers skip it, `verify` ignores it, and the next `append` (under the package
lock) cuts it off. A complete object that only lacks its newline is kept. An unparseable line
anywhere else is corruption: `read` raises and `verify` reports it.

`append` takes no lock itself; callers hold the PackageLock.

A log is a regular file or absent. A symlink (dangling or not), a junction or any other kind of
file at a log path is SdlcError(2, "log_not_regular:<name>") for every call, and opens never follow
a link where the platform can refuse one (O_NOFOLLOW): a link committed into a package must not
make the runner read, truncate or create a file outside it. A lone surrogate in a record (an
undecodable byte of a POSIX argv) is written as a JSON escape, so every line stays UTF-8.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

from .textio import SdlcError, dumps_json, is_link_like, now_iso

ZERO = "0" * 64
_BOM = b"\xef\xbb\xbf"
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_BINARY = getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _parse(raw: bytes):
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _exists_regular(path: Path) -> bool:
    """False when there is nothing at `path`; True for a regular file; SdlcError for anything else."""
    try:
        info = os.lstat(str(path))
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError:
        raise SdlcError(2, "log_unreadable:" + path.name) from None
    if not stat.S_ISREG(info.st_mode) or is_link_like(path):
        raise SdlcError(2, "log_not_regular:" + path.name)
    return True


def _read_bytes(path: Path) -> bytes:
    if not _exists_regular(path):
        return b""
    try:
        fd = os.open(str(path), os.O_RDONLY | _BINARY | _NOFOLLOW)
    except FileNotFoundError:
        return b""
    except OSError:
        raise SdlcError(2, "log_unreadable:" + path.name) from None
    with os.fdopen(fd, "rb") as handle:
        return handle.read()


def _load(path: Path):
    """(file bytes, [(raw line, record or None, line number)], offset of a torn final fragment or None)."""
    data = _read_bytes(path)
    if not data:
        return b"", [], None
    start = len(_BOM) if data.startswith(_BOM) else 0
    entries = []
    torn = None
    pos = start
    line_no = 0
    while pos < len(data):
        nl = data.find(b"\n", pos)
        end = len(data) if nl == -1 else nl
        raw = data[pos:end]
        if raw.endswith(b"\r"):
            raw = raw[:-1]
        line_no += 1
        if raw.strip():
            record = _parse(raw)
            if nl == -1 and record is None:
                torn = pos
                break
            entries.append((raw, record, line_no))
        if nl == -1:
            break
        pos = nl + 1
    return data, entries, torn


def _is_seq(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def append(path, record: dict) -> dict:
    """Append `record` with `seq`, `ts` and `prev` added; returns the stored record."""
    if "kind" not in record:
        raise ValueError("a log record needs a kind")
    path = Path(path)
    data, entries, torn = _load(path)
    if entries:
        last_raw, last, line_no = entries[-1]
        if last is None or not _is_seq(last.get("seq")):
            raise SdlcError(2, "log_corrupt:%s:%d" % (path.name, line_no))
        seq, prev = last["seq"] + 1, _hash(last_raw)
    else:
        seq, prev = 1, ZERO
    stored = {"seq": seq, "ts": now_iso()}
    for key, value in record.items():
        if key not in ("seq", "ts", "prev"):
            stored[key] = value
    stored["prev"] = prev
    line = dumps_json(stored).encode("utf-8")
    size = len(data) if torn is None else torn
    lead = b"\n" if size and data[size - 1:size] != b"\n" else b""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if _exists_regular(path):
            fd = os.open(str(path), os.O_RDWR | _BINARY | _NOFOLLOW)
        else:  # O_EXCL never follows a link that appeared since the check
            fd = os.open(str(path), os.O_RDWR | os.O_CREAT | os.O_EXCL | _BINARY | _NOFOLLOW, 0o666)
        with os.fdopen(fd, "r+b") as handle:
            handle.truncate(size)
            handle.seek(size)
            handle.write(lead + line + b"\n")  # one write; no fsync (see textio.write_text_atomic)
    except OSError:
        raise SdlcError(2, "unwritable:" + str(path)) from None
    return stored


def read(path) -> list:
    """Every record in order; a torn final fragment is skipped, a corrupt line raises SdlcError(2)."""
    path = Path(path)
    records = []
    for _raw, record, line_no in _load(path)[1]:
        if record is None:
            raise SdlcError(2, "log_corrupt:%s:%d" % (path.name, line_no))
        records.append(record)
    return records


def verify(path):
    """(ok, head, first_bad_seq).

    `head` is the sha256 of the last complete line (64 zeros for an empty log). `first_bad_seq` is
    the seq expected at the first line that is not a JSON object, carries the wrong seq, or whose
    `prev` does not match the line before it. A line's own hash is checked only by its successor,
    so an edit of line k shows as k+1, and an edit of the last line is visible only by comparing
    `head` with the chain head printed on an earlier card.
    """
    entries = _load(Path(path))[1]
    head = _hash(entries[-1][0]) if entries else ZERO
    prev, expected = ZERO, 1
    for raw, record, _line_no in entries:
        if record is None or record.get("seq") != expected or not _is_seq(record.get("seq")) \
                or record.get("prev") != prev:
            return False, head, expected
        prev, expected = _hash(raw), expected + 1
    return True, head, None


def head12(path) -> str:
    """First 12 hex of the chain head; twelve zeros for an empty or missing log."""
    entries = _load(Path(path))[1]
    return (_hash(entries[-1][0]) if entries else ZERO)[:12]
