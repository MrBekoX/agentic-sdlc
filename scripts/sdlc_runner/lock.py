"""The exclusive package lock (`<package>/.lock`) around every state-changing command.

The lock file is created with O_EXCL and holds JSON {pid, host, ts, nonce, start}. `host` is the
first 16 hex of the sha256 of the host name, never the name (design §4: the file sits in the
user's project, which the plugin neither ignores nor commits, and the `locked:` message reaches
transcripts). `start` identifies the holder process beyond its pid (its creation time on Windows,
boot id and start tick on Linux; absent where the platform gives none).

A lock is stale when it is older than `stale_seconds` AND its holder is gone: it came from another
host, its pid is not alive on this host, or that pid now names another process (`start` differs;
pids are reused). A lock without `start` is judged by its pid alone. A stale lock is broken by
moving it aside and checking that what was moved is what was judged stale, so two runners breaking
the same lock cannot remove a fresh one. Readers (`card`, `status`) never lock. Release removes the
file only while it still holds this lock's own content.

A lock that cannot be written is SdlcError(2, "lock_unwritable:<path>"): at once when its folder
cannot be made or the file system refuses the create for good (EROFS, ...), after about a second
when a create is refused (EACCES/EPERM) with no lock file in sight, never after the whole timeout.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .textio import SdlcError, now_iso

_POLL_SECONDS = 0.05
# Polls (about one second) a refused create may last with no lock file present: Windows refuses a
# create for a moment while the previous lock file is still being deleted.
_REFUSED_POLLS = 20
_STILL_ACTIVE = 259
_ERROR_ACCESS_DENIED = 5
_CREATED, _EXISTS, _REFUSED = "created", "exists", "refused"


def _host_id() -> str:
    """This host, as the lock stores it: sha256 of the host name, first 16 hex (equality only)."""
    return hashlib.sha256(socket.gethostname().encode("utf-8", "surrogateescape")).hexdigest()[:16]


def _process_start(pid):
    """A string that differs between two processes that held the same pid, or None when unknown."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0 or pid > 0xFFFFFFFF:
        return None
    if sys.platform == "win32":
        return _process_start_windows(pid)
    if sys.platform.startswith("linux"):
        return _process_start_linux(pid)
    return None


def _process_start_linux(pid: int):
    try:
        with open("/proc/%d/stat" % pid, "rb") as handle:
            raw = handle.read().decode("ascii", "replace")
        with open("/proc/sys/kernel/random/boot_id", "rb") as handle:
            boot = handle.read().decode("ascii", "replace").strip()
    except OSError:
        return None
    fields = raw[raw.rfind(")") + 2:].split()  # the command name may hold spaces and parentheses
    if len(fields) < 20 or not fields[19].isdigit():
        return None
    return "linux:%s:%s" % (boot, fields[19])  # field 22 of /proc/<pid>/stat: start time in ticks


def _pid_alive(pid) -> bool:
    """True when `pid` names a live process on this host. Never sends a signal on Windows."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0 or pid > 0xFFFFFFFF:
        return False
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, OverflowError, ValueError):
        return False
    return True


def _kernel32():
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    filetime = ctypes.POINTER(wintypes.FILETIME)
    kernel32.GetProcessTimes.argtypes = (wintypes.HANDLE, filetime, filetime, filetime, filetime)
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    return ctypes, wintypes, kernel32


_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _pid_alive_windows(pid: int) -> bool:
    # os.kill(pid, 0) on Windows TERMINATES the process, so ask the kernel instead.
    ctypes, wintypes, kernel32 = _kernel32()
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _process_start_windows(pid: int):
    ctypes, wintypes, kernel32 = _kernel32()
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel32.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
            return None
        created = times[0]
        return "win:%d" % ((created.dwHighDateTime << 32) | created.dwLowDateTime)
    finally:
        kernel32.CloseHandle(handle)


def _parse(raw):
    try:
        meta = json.loads(raw.decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, ValueError):
        return None
    return meta if isinstance(meta, dict) else None


class PackageLock:
    """Context manager: `with PackageLock(pkg / ".lock"): ...` (waits up to 30 s)."""

    def __init__(self, path, stale_seconds: int = 600):
        self.path = Path(path)
        self.stale_seconds = stale_seconds
        self._token = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False

    def acquire(self, timeout: float = 30) -> None:
        """Take the lock or raise SdlcError(2, "locked:<pid>@<host hash>") once `timeout` seconds
        pass; SdlcError(2, "lock_unwritable:<path>") when the lock cannot be written at all."""
        if self._token is not None:
            raise RuntimeError("this PackageLock is already held")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise SdlcError(2, self._unwritable()) from None
        deadline = time.monotonic() + max(0.0, float(timeout))
        refused = 0
        start = _process_start(os.getpid())
        while True:
            fields = {"host": _host_id(), "nonce": uuid.uuid4().hex, "pid": os.getpid(), "ts": now_iso()}
            if start is not None:
                fields["start"] = start
            token = json.dumps(fields, sort_keys=True).encode("utf-8")
            outcome = self._try_create(token)
            if outcome == _CREATED:
                self._token = token
                return
            seen = self._read()
            if outcome == _REFUSED and seen is None:
                refused += 1  # nothing to wait for: the folder itself refuses the file
                if refused >= _REFUSED_POLLS:
                    raise SdlcError(2, self._unwritable())
            else:
                refused = 0
            if seen is not None and self._is_stale(seen) and self._break(seen):
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SdlcError(2, self._failure(seen))
            time.sleep(min(_POLL_SECONDS, remaining))

    def release(self) -> None:
        token, self._token = self._token, None
        if token is None:
            return
        for attempt in range(6):  # Windows: another runner may hold the file open for a moment
            try:
                if self.path.read_bytes() != token:
                    return  # broken as stale and taken by another runner: not ours to remove
                self.path.unlink()
                return
            except FileNotFoundError:
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(_POLL_SECONDS * (attempt + 1))

    # -- internals -------------------------------------------------------------------------

    def _unwritable(self) -> str:
        return "lock_unwritable:" + str(self.path)

    def _try_create(self, token: bytes) -> str:
        """_CREATED, _EXISTS (a lock file is there), _REFUSED (EACCES/EPERM: Windows refuses a create
        while the previous lock file is still being deleted; also a folder that refuses files), or
        SdlcError for any other failure (EROFS, ENOSPC, a vanished folder)."""
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)
        try:
            fd = os.open(str(self.path), flags, 0o644)
        except FileExistsError:
            return _EXISTS
        except PermissionError:
            return _REFUSED
        except OSError:
            raise SdlcError(2, self._unwritable()) from None
        try:
            view = memoryview(token)
            while view:
                view = view[os.write(fd, view):]
        except BaseException as exc:
            os.close(fd)
            try:
                os.unlink(str(self.path))
            except OSError:
                pass
            if isinstance(exc, OSError):
                raise SdlcError(2, self._unwritable()) from None
            raise
        os.close(fd)
        return _CREATED

    def _read(self):
        try:
            return self.path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError:
            return b""

    def _age(self, meta):
        created = None
        ts = meta.get("ts") if meta else None
        if isinstance(ts, str):
            try:
                created = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
            except ValueError:
                created = None
        if created is None:
            try:
                created = self.path.stat().st_mtime
            except OSError:
                return None
        return time.time() - created

    def _is_stale(self, seen: bytes) -> bool:
        meta = _parse(seen)
        age = self._age(meta)
        if age is None or age <= self.stale_seconds:
            return False
        if not meta or meta.get("host") != _host_id():
            return True
        pid = meta.get("pid")
        if not _pid_alive(pid):
            return True
        recorded = meta.get("start")
        if isinstance(recorded, str) and recorded:
            current = _process_start(pid)
            return current is not None and current != recorded  # the pid now names another process
        return False

    def _break(self, seen: bytes) -> bool:
        aside = self.path.with_name(self.path.name + ".stale-" + uuid.uuid4().hex)
        try:
            os.rename(str(self.path), str(aside))
        except FileNotFoundError:
            return True
        except OSError:
            return False
        try:
            moved = aside.read_bytes()
        except OSError:
            moved = None
        if moved == seen:
            try:
                aside.unlink()
            except OSError:
                pass
            return True
        self._restore(aside)  # a fresh lock replaced the stale one after we read it
        return False

    def _restore(self, aside: Path) -> None:
        try:
            os.link(str(aside), str(self.path))
        except FileExistsError:
            pass
        except OSError:
            if not self.path.exists():
                try:
                    os.replace(str(aside), str(self.path))
                    return
                except OSError:
                    pass
        try:
            aside.unlink()
        except OSError:
            pass

    def _failure(self, seen) -> str:
        if seen is None:
            return self._unwritable()
        meta = _parse(seen) or {}
        return "locked:%s@%s" % (meta.get("pid", "unknown"), meta.get("host", "unknown"))
