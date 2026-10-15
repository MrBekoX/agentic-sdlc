#!/usr/bin/env python3
"""No-model native install/refresh/uninstall lifecycle check through each vendor's plugin manager.

Usage:
  python3 scripts/check_native_lifecycle.py --package <dir>
      [--platform claude|codex|grok|kimi|zcode|all] [--require <platform>]... [--keep-temp]
      [--timeout <seconds>]

`--package` is an extracted release package or a checkout. For each selected platform the check
copies it (without `.git`) into a fresh temporary root, below a path segment holding a space and
non-ASCII characters, points every profile variable of the vendor CLI into that root, and drives
the vendor's own plugin manager:

  install -> component discovery -> refresh from the copy with a bumped manifest version and a
  changed marker file -> uninstall

A platform passes only when every step succeeds, discovery reports the package's own skill count
(skill directories holding SKILL.md, plus each commands/*.md where the platform migrates commands
into skills), the refreshed install holds the changed marker bytes and the bumped version, the
uninstall removes the plugin record, an unrelated sentinel setting written before the install
survives every step, and the platform's registry was written inside the temporary root.

Recipes: Claude Code `claude plugin marketplace add|install|list|details|update|uninstall`;
Codex a personal catalog under the isolated HOME with `codex plugin add|list|remove` and the
read-only `skills/list` request of `codex app-server --stdio`; Grok `grok plugin
install|list|uninstall` and `grok inspect --json`; Kimi Code the local `kimi web` REST API (bound to
127.0.0.1) with the bearer token from its startup banner, or else from the token file it keeps in
the isolated profile; ZCode has no supported headless installer (see run_platform).

It never sends a model prompt: every argv must start with an allowlisted plugin-management word,
each subcommand is probed with `--help` first (an older CLI never receives plugin argv), and the
child environment is built from an allowlist that carries no provider key or cloud credential.

Output: exactly one line per selected platform, in the order claude, codex, grok, kimi, zcode:
  native_<platform>=passed | native_<platform>=failed:<reason> | native_<platform>=not-run:<reason>
Reasons are short slugs without paths, user names or host names. Exit codes: 0 when no line is
failed and every --require'd platform passed; 1 otherwise; 2 for usage errors. `--keep-temp`
keeps each temporary root and names it on stderr (debugging only).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import queue
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PLATFORMS = ("claude", "codex", "grok", "kimi", "zcode")
HOSTILE_SEGMENT = "plug in \u011f \u76ee\u5f55"
# Codex splits marketplace sources on '#', Grok sources on '@' and '#'; cmd.exe expands '%' and '&'.
PATH_HAZARDS = "#&%@"
CODEX_CATALOG = "native-lifecycle"
DEFAULT_TIMEOUT = 180.0
SERVER_START_SECONDS = 60.0
KILL_WAIT_SECONDS = 10.0
READER_JOIN_SECONDS = 5.0
POLL_SECONDS = 0.25
REFRESH_MARKER = b"\n<!-- native lifecycle refresh marker -->\n"
PREFERRED_MARKER_SKILL = "using-agentic-sdlc"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
REASON_RE = re.compile(r"^[a-z0-9_]+(?::[a-z0-9_=,.-]+)?$")
MAX_REASON = 96
CLIENT_INFO = {"name": "agentic_sdlc_native_lifecycle", "version": "1"}

# BINDING no-prompt rule: every argv starts with one of these words and carries no prompt token.
ALLOWED_HEADS = {
    "claude": ("plugin",),
    "codex": ("plugin", "app-server"),
    "grok": ("plugin", "inspect"),
    "kimi": ("web",),
}
FORBIDDEN_TOKENS = frozenset({"-p", "--prompt", "exec", "e", "agent", "--host", "--rc",
                              "--remote-control", "--dangerous-bypass-auth"})

# Platform manifests: the first file names the plugin and carries the version the refresh bumps;
# the others are marketplace indexes whose entry for the plugin is bumped with it.
MANIFESTS = {
    "claude": (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json"),
    "codex": (".codex-plugin/plugin.json",),
    "grok": (".grok-plugin/plugin.json", ".grok-plugin/marketplace.json"),
    "kimi": (".kimi-plugin/plugin.json",),
}

_PASS_THROUGH = ("SystemRoot", "ComSpec", "PATHEXT", "LANG", "LC_ALL")
_DISABLE_FLAGS = {
    "DISABLE_AUTOUPDATER": "1",
    "DISABLE_TELEMETRY": "1",
    "DISABLE_ERROR_REPORTING": "1",
    "GROK_DISABLE_AUTOUPDATER": "1",
    "GROK_TELEMETRY_ENABLED": "false",
    "KIMI_DISABLE_TELEMETRY": "1",
}
_ABSOLUTE_WINDOWS_ENTRY = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|//)")
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_SHIM_SUFFIXES = (".cmd", ".bat", ".ps1")
_MISSING = object()
_EOF = object()


class NotRun(Exception):
    """The platform could not be exercised here; `reason` is a slug."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class Failed(Exception):
    """The platform was exercised and a lifecycle requirement failed; `reason` is a slug."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------- pure helpers

def format_line(platform: str, state: str, reason) -> str:
    return "native_%s=%s" % (platform, state if state == "passed" else "%s:%s" % (state, reason))


def exit_code(results: dict, required) -> int:
    if any(state == "failed" for state, _ in results.values()):
        return 1
    if any(results.get(name, ("not-run", None))[0] != "passed" for name in required):
        return 1
    return 0


def safe_reason(reason, forbidden=()) -> str:
    """Return `reason` when it is a short slug free of every forbidden value, else internal_error."""
    if not isinstance(reason, str) or len(reason) > MAX_REASON or not REASON_RE.match(reason):
        return "internal_error"
    if any(item and item in reason for item in forbidden):
        return "internal_error"
    return reason


def bump_version(version) -> str:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(version or ""))
    if not match:
        raise Failed("version_unparseable")
    major, minor, patch = match.groups()
    return "%s.%s.%d" % (major, minor, int(patch) + 1)


def banner_token(text: str):
    """The bearer token from a `kimi web` startup banner's `Token:` line, or None.

    Only a newline-terminated line counts, so a banner still being written never yields half a token.
    """
    match = re.search(r"^[ \t]*Token:[ \t]*(\S+)[ \t]*\r?\n", _ANSI_ESCAPE.sub("", text), re.M)
    return match.group(1) if match else None


def package_counts(package) -> tuple:
    """(skill directories holding SKILL.md, commands/*.md files) of a package."""
    package = Path(package)
    skills_dir = package / "skills"
    skills = sum(1 for p in skills_dir.iterdir() if (p / "SKILL.md").is_file()) if skills_dir.is_dir() else 0
    commands_dir = package / "commands"
    commands = sum(1 for p in commands_dir.glob("*.md") if p.is_file()) if commands_dir.is_dir() else 0
    return skills, commands


def copy_package(source, dest) -> None:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        str(source),
        str(dest),
        ignore=shutil.ignore_patterns(
            ".git",
            ".pytest_cache",
            "__pycache__",
            "audit-docs",
            "artifacts",
            "build",
            "dist",
            ".opencode",
            ".claude",
            ".worktrees",
            ".tmp-superpowers-compare",
        ),
        ignore_dangling_symlinks=True,
    )


def _absolute_entry(entry: str) -> bool:
    if not entry:
        return False
    if sys.platform == "win32":
        return bool(_ABSOLUTE_WINDOWS_ENTRY.match(entry))
    return entry.startswith("/")


def resolve_cli(name: str, path_value=None, windows=None) -> str:
    """The CLI as the first absolute-PATH hit, like the maintainer's shell would find it.

    A relative or empty PATH entry is never searched. With Windows rules only <name>.exe and
    <name>.com run; when the first folder holding the name has only a .cmd/.bat/.ps1 shim the CLI
    is refused, because a shim reparses its arguments through a shell.
    """
    if windows is None:
        windows = sys.platform == "win32"
    if path_value is None:
        path_value = os.environ.get("PATH", "")
    for entry in path_value.split(os.pathsep):
        if not _absolute_entry(entry):
            continue
        if windows:
            for suffix in (".exe", ".com"):
                candidate = os.path.join(entry, name + suffix)
                if os.path.isfile(candidate):
                    return candidate
            if any(os.path.isfile(os.path.join(entry, name + suffix)) for suffix in _SHIM_SUFFIXES):
                raise NotRun("cli_is_script_shim")
        else:
            candidate = os.path.join(entry, name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    raise NotRun("cli_absent")


def _lookup(env: dict, name: str):
    if name in env:
        return env[name]
    if sys.platform == "win32":
        upper = name.upper()
        for key, value in env.items():
            if key.upper() == upper:
                return value
    return None


def build_child_env(root, home=None, base_env=None) -> dict:
    """The complete child environment: an allowlist, with every profile folder inside `root`.

    Nothing else from the parent passes, so provider keys, cloud credentials, CI tokens and proxy
    settings never reach a vendor CLI. The folders are created.
    """
    base = dict(os.environ if base_env is None else base_env)
    root = Path(root)
    home = Path(home) if home is not None else root / "home"
    folders = {
        "HOME": home, "USERPROFILE": home,
        "APPDATA": root / "appdata", "LOCALAPPDATA": root / "localappdata",
        "XDG_CONFIG_HOME": root / "xdg" / "config", "XDG_DATA_HOME": root / "xdg" / "data",
        "XDG_CACHE_HOME": root / "xdg" / "cache",
        "CLAUDE_CONFIG_DIR": root / "claude", "CODEX_HOME": root / "codex",
        "GROK_HOME": root / "grok", "KIMI_CODE_HOME": root / "kimi",
        "TEMP": root / "tmp", "TMP": root / "tmp", "TMPDIR": root / "tmp",
    }
    path_value = _lookup(base, "PATH") or ""
    env = {"PATH": os.pathsep.join(e for e in path_value.split(os.pathsep) if _absolute_entry(e))}
    for name in _PASS_THROUGH:
        value = _lookup(base, name)
        if value:
            env[name] = value
    for name, folder in folders.items():
        folder.mkdir(parents=True, exist_ok=True)
        env[name] = str(folder)
    env.update(_DISABLE_FLAGS)
    return env


# ---------------------------------------------------------------- process helpers

def _group_kwargs() -> dict:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _terminate_tree(proc: subprocess.Popen) -> None:
    """Kill a still-running child together with its process tree (never a reaped pid)."""
    if sys.platform == "win32":
        if proc.poll() is None:
            taskkill = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "taskkill.exe")
            try:
                subprocess.run([taskkill, "/T", "/F", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=KILL_WAIT_SECONDS)
            except (OSError, subprocess.SubprocessError):
                proc.kill()
    elif proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
    try:
        proc.wait(timeout=KILL_WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        pass


def _reader(stream, sink: queue.Queue) -> None:
    try:
        for line in stream:
            sink.put(line)
    except (OSError, ValueError):
        pass
    finally:
        sink.put(_EOF)


def _remove_tree(path: Path) -> None:
    def retry(func, target, _info):
        try:
            os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
            func(target)
        except OSError:
            pass

    for _ in range(3):
        if not path.exists():
            return
        if sys.version_info >= (3, 12):
            shutil.rmtree(str(path), onexc=retry)
        else:
            shutil.rmtree(str(path), onerror=retry)
        if path.exists():
            time.sleep(0.5)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _inside(path, root) -> bool:
    try:
        Path(os.path.realpath(str(path))).relative_to(os.path.realpath(str(root)))
        return True
    except ValueError:
        return False


def _inside_repository(path: Path) -> bool:
    return any((parent / ".git").exists() for parent in path.parents)


# ---------------------------------------------------------------- manifests and settings

def _read_json(path: Path, reason: str = "manifest_invalid"):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise Failed(reason) from None


def _write_json(path: Path, value) -> None:
    path.write_bytes((json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def _parse_json(text: str, step: str):
    text = text.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    for line in reversed(text.splitlines()):
        if line.strip():
            try:
                return json.loads(line)
            except ValueError:
                break
    raise Failed(step + "_unparseable")


def _plugin_name(package: Path, platform: str) -> str:
    path = package / MANIFESTS[platform][0]
    if not path.is_file():
        raise NotRun("no_platform_manifest")
    manifest = _read_json(path)
    name = manifest.get("name") if isinstance(manifest, dict) else None
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise Failed("manifest_invalid")
    return name


def _toml_value(text: str, table: tuple, key: str):
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        tomllib = None
    if tomllib is not None:
        try:
            node = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return _MISSING
        for part in table:
            node = node.get(part) if isinstance(node, dict) else None
        return node.get(key, _MISSING) if isinstance(node, dict) else _MISSING
    current = ()
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            current = tuple(part.strip().strip('"') for part in line.strip("[]").split("."))
        elif "=" in line and current == tuple(table):
            name, value = (part.strip() for part in line.split("=", 1))
            if name == key:
                return {"true": True, "false": False}.get(value, value.strip('"'))
    return _MISSING


# The unrelated setting each profile holds before the install; it must survive every step.
SENTINELS = {
    "claude": ("CLAUDE_CONFIG_DIR", "settings.json",
               '{\n  "env": {\n    "AGENTIC_NATIVE_LIFECYCLE_SENTINEL": "keep"\n  }\n}\n'),
    "codex": ("CODEX_HOME", "config.toml", '[profiles.native_lifecycle_sentinel]\nmodel = "sentinel-model"\n'),
    "grok": ("GROK_HOME", "config.toml", "[cli]\nauto_update = false\n\n[ui]\nvim_mode = true\n"),
    "kimi": ("KIMI_CODE_HOME", "tui.toml", 'theme = "dark"\n'),
}


def _sentinel_holds(platform: str, text: str) -> bool:
    if platform == "claude":
        try:
            settings = json.loads(text)
        except ValueError:
            return False
        env = settings.get("env") if isinstance(settings, dict) else None
        return isinstance(env, dict) and env.get("AGENTIC_NATIVE_LIFECYCLE_SENTINEL") == "keep"
    if platform == "codex":
        return _toml_value(text, ("profiles", "native_lifecycle_sentinel"), "model") == "sentinel-model"
    if platform == "grok":
        return _toml_value(text, ("ui",), "vim_mode") is True
    return _toml_value(text, (), "theme") == "dark"


# ---------------------------------------------------------------- one platform run

class Lifecycle:
    """One platform's disposable profile, package copy and guarded CLI runner."""

    def __init__(self, platform: str, package: Path, timeout: float):
        self.platform = platform
        self.package = package
        self.timeout = timeout
        self.plugin = _plugin_name(package, platform)
        self.cli = resolve_cli(platform)
        self.skills, self.commands = package_counts(package)
        self.marker = None
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.root = Path(tempfile.mkdtemp(prefix="native-lifecycle-"))
        try:
            self._layout()
        except BaseException:
            _remove_tree(self.root)
            raise

    def _layout(self) -> None:
        if _inside_repository(self.root):
            raise NotRun("temp_inside_repository")
        hostile = self.root / HOSTILE_SEGMENT
        self.source = hostile / "plugins" / self.plugin
        if any(ch in str(self.source) for ch in PATH_HAZARDS):
            raise NotRun("temp_path_hazard")
        self.cwd = self.root / "cwd"
        self.cwd.mkdir()
        # Codex reads the personal catalog under HOME, so its HOME is the hostile folder itself.
        self.home = hostile if self.platform == "codex" else self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.env = build_child_env(self.root, home=self.home)

    def folder(self, variable: str) -> Path:
        return Path(self.env[variable])

    def close(self, keep: bool) -> None:
        if keep:
            sys.stderr.write("kept native lifecycle root for %s: %s\n" % (self.platform, self.root))
        else:
            _remove_tree(self.root)

    # -- argv guard and runner

    def guard(self, argv) -> None:
        if not argv or argv[0] not in ALLOWED_HEADS[self.platform] or FORBIDDEN_TOKENS.intersection(argv):
            raise Failed("argv_not_allowed")

    def run(self, argv, step: str, check: bool = True) -> tuple:
        self.guard(argv)
        try:
            proc = subprocess.Popen([self.cli] + list(argv), cwd=str(self.cwd), env=self.env,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, **_group_kwargs())
        except OSError:
            raise Failed(step + "_spawn_failed") from None
        try:
            out, err = proc.communicate(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            _terminate_tree(proc)
            try:
                proc.communicate(timeout=KILL_WAIT_SECONDS)
            except (subprocess.TimeoutExpired, OSError, ValueError):
                pass
            raise Failed(step + "_timeout") from None
        except BaseException:
            # SIGTERM/SIGHUP (raised as SystemExit) or Ctrl+C: the child runs in its own session, so
            # no group signal reaches it. Stop it before the temporary root is removed.
            _terminate_tree(proc)
            raise
        result = (proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"))
        if check and proc.returncode != 0:
            raise Failed(step + "_failed")
        return result

    def probe(self, words, flags=()) -> None:
        """`<cli> <words> --help` must print that subcommand's usage (and flags), or the CLI is too old."""
        try:
            code, out, err = self.run(list(words) + ["--help"], "probe", check=False)
        except Failed as exc:
            raise NotRun("cli_unresponsive" if exc.reason == "probe_timeout" else "cli_unusable") from None
        text = out + "\n" + err
        usage = r"Usage:\s+\S+\s+" + r"\s+".join(re.escape(w) + r"(?:\|[\w-]+)*" for w in words) + r"(?=\s|$)"
        if code != 0 or not re.search(usage, text) or any(flag not in text for flag in flags):
            raise NotRun("cli_too_old")

    # -- package copy, sentinel, assertions

    def prepare_source(self) -> None:
        copy_package(self.package, self.source)
        preferred = Path("skills") / PREFERRED_MARKER_SKILL / "SKILL.md"
        if (self.source / preferred).is_file():
            self.marker = preferred
        else:
            self.marker = next(Path("skills") / p.name / "SKILL.md" for p in sorted((self.source / "skills").iterdir())
                               if (p / "SKILL.md").is_file())

    def write_sentinel(self) -> None:
        variable, name, text = SENTINELS[self.platform]
        (self.folder(variable) / name).write_bytes(text.encode("utf-8"))

    def check_sentinel(self) -> None:
        variable, name, _ = SENTINELS[self.platform]
        try:
            text = (self.folder(variable) / name).read_text(encoding="utf-8")
        except OSError:
            raise Failed("sentinel_lost") from None
        if not _sentinel_holds(self.platform, text):
            raise Failed("sentinel_lost")

    def installed_root(self, value, reason: str = "install_not_recorded") -> Path:
        if not isinstance(value, str) or not value:
            raise Failed(reason)
        path = Path(value)
        if not _inside(path, self.root):
            raise Failed("install_outside_profile")
        return path

    def check_bytes(self, installed: Path, reason: str) -> None:
        try:
            same = (installed / self.marker).read_bytes() == (self.source / self.marker).read_bytes()
        except OSError:
            same = False
        if not same:
            raise Failed(reason)

    def expect(self, got: int, expected: int, label: str = "discovery_mismatch") -> None:
        if got != expected:
            raise Failed("%s:expected=%d,got=%d" % (label, expected, got))

    def refresh_source(self) -> str:
        """Bump the copy's manifest version(s) and change its marker file; return the new version."""
        files = MANIFESTS[self.platform]
        manifest = _read_json(self.source / files[0])
        if not isinstance(manifest, dict):
            raise Failed("manifest_invalid")
        version = bump_version(manifest.get("version"))
        manifest["version"] = version
        _write_json(self.source / files[0], manifest)
        for rel in files[1:]:
            path = self.source / rel
            if not path.is_file():
                continue
            index = _read_json(path)
            for entry in index.get("plugins", []) if isinstance(index, dict) else []:
                if isinstance(entry, dict) and entry.get("name") == self.plugin and "version" in entry:
                    entry["version"] = version
            _write_json(path, index)
        with open(str(self.source / self.marker), "ab") as handle:
            handle.write(REFRESH_MARKER)
        return version

    def verify_isolation(self, evidence: Path) -> None:
        if not evidence.exists() or not _inside(evidence, self.root):
            raise Failed("isolation_unverified")


# ---------------------------------------------------------------- Claude Code

def _claude_record(lc: Lifecycle, plugin_id: str):
    _, out, _ = lc.run(["plugin", "list", "--json"], "list")
    entries = _parse_json(out, "list")
    if not isinstance(entries, list):
        raise Failed("list_unparseable")
    return next((e for e in entries if isinstance(e, dict) and e.get("id") == plugin_id), None)


def check_claude(lc: Lifecycle) -> None:
    index = _read_json(lc.package / ".claude-plugin" / "marketplace.json")
    market = index.get("name") if isinstance(index, dict) else None
    listed = isinstance(index, dict) and any(isinstance(e, dict) and e.get("name") == lc.plugin
                                             for e in index.get("plugins", []))
    if not isinstance(market, str) or not NAME_RE.match(market) or not listed:
        raise Failed("manifest_invalid")
    plugin_id = "%s@%s" % (lc.plugin, market)
    # Only `plugin list` output is parsed (--json); every other step is judged by its exit status
    # and by the state it leaves, so older 2.1.x builds without --json on every subcommand qualify.
    for words, flags in ((("plugin", "marketplace", "add"), ()), (("plugin", "install"), ()),
                         (("plugin", "list"), ("--json",)), (("plugin", "details"), ()),
                         (("plugin", "marketplace", "update"), ()), (("plugin", "update"), ()),
                         (("plugin", "uninstall"), ())):
        lc.probe(words, flags)
    lc.prepare_source()
    lc.write_sentinel()
    lc.run(["plugin", "marketplace", "add", str(lc.source)], "marketplace_add")
    lc.check_sentinel()
    lc.run(["plugin", "install", plugin_id], "install")
    lc.check_sentinel()
    record = _claude_record(lc, plugin_id)
    if record is None:
        raise Failed("install_not_recorded")
    lc.check_bytes(lc.installed_root(record.get("installPath")), "installed_bytes_mismatch")
    _, out, _ = lc.run(["plugin", "details", plugin_id], "discovery")
    match = re.search(r"^\s*Skills \((\d+)\)", out, re.M)
    if not match:
        raise Failed("discovery_failed")
    lc.expect(int(match.group(1)), lc.skills + lc.commands)
    version = lc.refresh_source()
    lc.run(["plugin", "marketplace", "update", market], "refresh")
    lc.run(["plugin", "update", plugin_id], "refresh")
    lc.check_sentinel()
    record = _claude_record(lc, plugin_id)
    if record is None or record.get("version") != version:
        raise Failed("refresh_not_applied")
    lc.check_bytes(lc.installed_root(record.get("installPath"), "refresh_not_applied"), "refresh_not_applied")
    lc.run(["plugin", "uninstall", plugin_id], "uninstall")
    lc.check_sentinel()
    if _claude_record(lc, plugin_id) is not None:
        raise Failed("record_not_removed")
    lc.verify_isolation(lc.folder("CLAUDE_CONFIG_DIR") / "plugins" / "installed_plugins.json")


# ---------------------------------------------------------------- Codex

def _codex_installed(lc: Lifecycle, plugin_id: str) -> bool:
    _, out, _ = lc.run(["plugin", "list", "--json"], "list")
    data = _parse_json(out, "list")
    installed = data.get("installed") if isinstance(data, dict) else None
    if not isinstance(installed, list):
        raise Failed("list_unparseable")
    return any(isinstance(e, dict) and e.get("pluginId") == plugin_id and e.get("installed", True) is not False
               for e in installed)


def _codex_await(sink: queue.Queue, request_id: int, deadline: float) -> dict:
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Failed("discovery_timeout")
        try:
            item = sink.get(timeout=remaining)
        except queue.Empty:
            raise Failed("discovery_timeout") from None
        if item is _EOF:
            raise Failed("discovery_failed")
        line = item.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except (ValueError, RecursionError):
            raise Failed("discovery_failed") from None
        if not isinstance(message, dict) or "method" in message or message.get("id") != request_id:
            continue
        if "result" not in message:
            raise Failed("discovery_failed")
        return message["result"]


def _codex_skill_names(lc: Lifecycle) -> list:
    """`skills/list` over `codex app-server --stdio`: read-only, no thread, no model turn."""
    argv = ["app-server", "--stdio"]
    lc.guard(argv)
    try:
        proc = subprocess.Popen([lc.cli] + argv, cwd=str(lc.cwd), env=lc.env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                encoding="utf-8", errors="replace", **_group_kwargs())
    except OSError:
        raise Failed("discovery_spawn_failed") from None
    sink: queue.Queue = queue.Queue()
    reader = threading.Thread(target=_reader, args=(proc.stdout, sink), daemon=True)
    reader.start()
    deadline = time.monotonic() + lc.timeout

    def send(message: dict) -> None:
        try:
            proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.flush()
        except (OSError, ValueError):
            raise Failed("discovery_failed") from None

    try:
        send({"id": 1, "method": "initialize",
              "params": {"clientInfo": CLIENT_INFO, "capabilities": {"experimentalApi": False}}})
        _codex_await(sink, 1, deadline)
        send({"method": "initialized"})
        send({"id": 2, "method": "skills/list", "params": {"cwds": [str(lc.cwd)], "forceReload": True}})
        result = _codex_await(sink, 2, deadline)
    finally:
        _terminate_tree(proc)
        reader.join(timeout=READER_JOIN_SECONDS)
        for stream in (proc.stdin, proc.stdout):
            if stream is proc.stdout and reader.is_alive():
                continue
            try:
                stream.close()
            except (OSError, ValueError):
                pass
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, list):
        raise Failed("discovery_failed")
    return [skill.get("name") for entry in data if isinstance(entry, dict)
            for skill in entry.get("skills", []) if isinstance(skill, dict)]


def check_codex(lc: Lifecycle) -> None:
    plugin_id = "%s@%s" % (lc.plugin, CODEX_CATALOG)
    for words, flags in ((("plugin", "add"), ("--json",)), (("plugin", "list"), ("--json",)),
                         (("plugin", "remove"), ("--json",)), (("app-server",), ("--stdio",))):
        lc.probe(words, flags)
    lc.prepare_source()
    catalog = lc.home / ".agents" / "plugins" / "marketplace.json"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    _write_json(catalog, {"name": CODEX_CATALOG, "plugins": [{
        "name": lc.plugin, "source": {"source": "local", "path": "./plugins/" + lc.plugin},
        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "category": "Developer Tools"}]})
    lc.write_sentinel()
    _, out, _ = lc.run(["plugin", "add", plugin_id, "--json"], "install")
    lc.check_sentinel()
    result = _parse_json(out, "install")
    if not isinstance(result, dict) or not _codex_installed(lc, plugin_id):
        raise Failed("install_not_recorded")
    lc.check_bytes(lc.installed_root(result.get("installedPath")), "installed_bytes_mismatch")
    prefix = lc.plugin + ":"
    names = _codex_skill_names(lc)
    lc.expect(sum(1 for name in names if isinstance(name, str) and name.startswith(prefix)),
              lc.skills + lc.commands)
    version = lc.refresh_source()
    _, out, _ = lc.run(["plugin", "add", plugin_id, "--json"], "refresh")
    lc.check_sentinel()
    result = _parse_json(out, "refresh")
    if not isinstance(result, dict) or result.get("version") != version:
        raise Failed("refresh_not_applied")
    lc.check_bytes(lc.installed_root(result.get("installedPath"), "refresh_not_applied"), "refresh_not_applied")
    lc.run(["plugin", "remove", plugin_id, "--json"], "uninstall")
    lc.check_sentinel()
    if _codex_installed(lc, plugin_id):
        raise Failed("record_not_removed")
    lc.verify_isolation(lc.folder("CODEX_HOME") / "plugins")


# ---------------------------------------------------------------- Grok

def _grok_record(lc: Lifecycle):
    _, out, _ = lc.run(["plugin", "list", "--json"], "list")
    entries = _parse_json(out, "list")
    if not isinstance(entries, list):
        raise Failed("list_unparseable")
    return next((e for e in entries if isinstance(e, dict) and e.get("name") == lc.plugin), None)


def check_grok(lc: Lifecycle) -> None:
    for words, flags in ((("plugin", "install"), ("--trust",)), (("plugin", "list"), ("--json",)),
                         (("plugin", "uninstall"), ()), (("inspect",), ("--json",))):
        lc.probe(words, flags)
    lc.prepare_source()
    lc.write_sentinel()
    lc.run(["plugin", "install", str(lc.source), "--trust"], "install")
    lc.check_sentinel()
    record = _grok_record(lc)
    if record is None:
        raise Failed("install_not_recorded")
    lc.check_bytes(lc.installed_root(record.get("path")), "installed_bytes_mismatch")
    _, out, _ = lc.run(["inspect", "--json"], "discovery")
    report = _parse_json(out, "discovery")
    skills = report.get("skills") if isinstance(report, dict) else None
    if not isinstance(skills, list):
        raise Failed("discovery_failed")
    lc.expect(sum(1 for s in skills if isinstance(s, dict) and isinstance(s.get("source"), dict)
                  and s["source"].get("type") == "plugin" and s["source"].get("plugin_name") == lc.plugin),
              lc.skills + lc.commands)
    # A local install is not refreshed by `grok plugin update` ("already live"), and installing the
    # same plugin again is refused, so the refresh is uninstall + install of the bumped copy.
    version = lc.refresh_source()
    lc.run(["plugin", "uninstall", lc.plugin], "refresh")
    lc.run(["plugin", "install", str(lc.source), "--trust"], "refresh")
    lc.check_sentinel()
    record = _grok_record(lc)
    if record is None or record.get("version") != version:
        raise Failed("refresh_not_applied")
    lc.check_bytes(lc.installed_root(record.get("path"), "refresh_not_applied"), "refresh_not_applied")
    lc.run(["plugin", "uninstall", lc.plugin], "uninstall")
    lc.check_sentinel()
    if _grok_record(lc) is not None:
        raise Failed("record_not_removed")
    lc.verify_isolation(lc.folder("GROK_HOME") / "installed-plugins")


# ---------------------------------------------------------------- Kimi Code

class _KimiServer:
    """The local `kimi web` server of the isolated profile; token auth only, bound to 127.0.0.1."""

    def __init__(self, lc: Lifecycle):
        self.lc = lc
        self.port = _free_port()
        self.token = None
        self.proc = None
        self.banner = None

    def start(self) -> None:
        argv = ["web", "--no-open", "--port", str(self.port)]
        self.lc.guard(argv)
        # The startup banner (it names the bearer token) goes to a file inside the temporary root,
        # never to this process's output.
        self.banner = self.lc.root / "kimi-web.out"
        try:
            with open(str(self.banner), "wb") as banner:
                self.proc = subprocess.Popen([self.lc.cli] + argv, cwd=str(self.lc.cwd), env=self.lc.env,
                                             stdin=subprocess.DEVNULL, stdout=banner,
                                             stderr=subprocess.DEVNULL, **_group_kwargs())
        except OSError:
            raise NotRun("server_start_failed") from None
        token_file = self.lc.folder("KIMI_CODE_HOME") / "server.token"
        deadline = time.monotonic() + min(SERVER_START_SECONDS, self.lc.timeout)
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise NotRun("server_start_failed")
            self.token = self.token or self._discover_token(token_file)
            if self.token:
                status = self._status("/api/v1/meta")
                if status == 200:
                    return
                if status in (401, 403):
                    raise NotRun("server_auth_unavailable")
            time.sleep(POLL_SECONDS)
        raise NotRun("server_start_failed" if self.token else "server_token_missing")

    def _discover_token(self, token_file: Path):
        """The `Token:` line of the startup banner, else the token file the server keeps in its profile."""
        try:
            token = banner_token(self.banner.read_bytes().decode("utf-8", "replace"))
        except OSError:
            token = None
        if token:
            return token
        try:
            return token_file.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    def stop(self) -> None:
        if self.proc is not None:
            _terminate_tree(self.proc)

    def _request(self, method: str, path: str, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Authorization": "Bearer " + (self.token or "")}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), data=data,
                                         method=method, headers=headers)
        return self.lc.opener.open(request, timeout=self.lc.timeout)

    def _status(self, path: str):
        try:
            with self._request("GET", path) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            return exc.code
        except (urllib.error.URLError, OSError):
            return None

    def call(self, method: str, path: str, step: str, body=None):
        try:
            with self._request(method, path, body) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError):
            raise Failed(step + "_failed") from None
        if not isinstance(payload, dict) or payload.get("code") != 0:
            raise Failed(step + "_failed")
        return payload.get("data")


def _kimi_record(lc: Lifecycle, server: _KimiServer):
    data = server.call("GET", "/api/v1/plugins", "list")
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, list):
        raise Failed("list_unparseable")
    return next((p for p in plugins if isinstance(p, dict) and p.get("id") == lc.plugin), None)


def check_kimi(lc: Lifecycle) -> None:
    # No `kimi plugin` subcommand exists and `kimi -p` always runs a model turn, so the plugin
    # manager is reached through the local server's REST API instead.
    lc.probe(("web",), ("--no-open", "--port"))
    lc.prepare_source()
    lc.write_sentinel()
    server = _KimiServer(lc)
    try:
        server.start()
        result = server.call("POST", "/api/v1/plugins", "install", {"source": str(lc.source)})
        lc.check_sentinel()
        if not isinstance(result, dict) or result.get("id") != lc.plugin:
            raise Failed("install_not_recorded")
        lc.check_bytes(lc.installed_root(result.get("root")), "installed_bytes_mismatch")
        record = _kimi_record(lc, server)
        if record is None:
            raise Failed("install_not_recorded")
        # Kimi lists commands apart from skills: it does not migrate commands into skills.
        lc.expect(record.get("skillCount") if isinstance(record.get("skillCount"), int) else -1, lc.skills)
        lc.expect(record.get("commandCount") if isinstance(record.get("commandCount"), int) else -1,
                  lc.commands, "command_discovery_mismatch")
        version = lc.refresh_source()
        result = server.call("POST", "/api/v1/plugins", "refresh", {"source": str(lc.source)})
        lc.check_sentinel()
        if not isinstance(result, dict) or result.get("version") != version:
            raise Failed("refresh_not_applied")
        lc.check_bytes(lc.installed_root(result.get("root"), "refresh_not_applied"), "refresh_not_applied")
        # Every POST carries a JSON object body: Kimi 2.1.1 rejects an empty one (code 50001).
        server.call("POST", "/api/v1/plugins/%s:remove" % urllib.parse.quote(lc.plugin, safe=""), "uninstall", {})
        lc.check_sentinel()
        if _kimi_record(lc, server) is not None:
            raise Failed("record_not_removed")
    finally:
        server.stop()
    lc.verify_isolation(lc.folder("KIMI_CODE_HOME") / "plugins" / "installed.json")


CHECKS = {"claude": check_claude, "codex": check_codex, "grok": check_grok, "kimi": check_kimi}


def run_platform(platform: str, package: Path, timeout: float, keep_temp: bool) -> tuple:
    if platform == "zcode":
        # ZCode ships no supported headless plugin installer: its desktop bundle's agent CLI manages
        # plugins only when the desktop executable runs in Electron's Node mode, which is not a
        # documented user path. A recipe belongs here, behind the same probe-first and allowlist
        # rules as the other platforms, once ZCode documents a CLI.
        return "not-run", "no_headless_installer"
    lc = None
    try:
        lc = Lifecycle(platform, package, timeout)
        CHECKS[platform](lc)
        return "passed", None
    except NotRun as exc:
        return "not-run", safe_reason(exc.reason)
    except Failed as exc:
        return "failed", safe_reason(exc.reason)
    except Exception:  # noqa: BLE001 - a crash is a failed platform, never a traceback with paths
        return "failed", "internal_error"
    finally:
        if lc is not None:
            lc.close(keep_temp)


def _positive_seconds(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("not a number: %r" % value) from None
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("must be a positive number of seconds: %r" % value)
    return seconds


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="No-model native plugin lifecycle check per platform.")
    parser.add_argument("--package", required=True, help="extracted package or checkout to install")
    parser.add_argument("--platform", choices=PLATFORMS + ("all",), default="all")
    parser.add_argument("--require", action="append", choices=PLATFORMS, default=[],
                        help="exit 1 unless this platform passed (repeatable)")
    parser.add_argument("--keep-temp", action="store_true", help="keep each temporary root (debugging)")
    parser.add_argument("--timeout", type=_positive_seconds, default=DEFAULT_TIMEOUT,
                        help="seconds allowed for each CLI step")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    selected = PLATFORMS if args.platform == "all" else (args.platform,)
    for name in args.require:
        if name not in selected:
            parser.error("--require %s is not selected by --platform %s" % (name, args.platform))
    package = Path(args.package).resolve()
    results = {}
    if not package.is_dir() or package_counts(package)[0] == 0:
        for name in selected:
            results[name] = ("failed", "package_invalid")
            print(format_line(name, "failed", "package_invalid"), flush=True)
        return exit_code(results, args.require)
    for name in selected:
        state, reason = run_platform(name, package, args.timeout, args.keep_temp)
        results[name] = (state, reason)
        print(format_line(name, state, reason), flush=True)
    return exit_code(results, args.require)


def _exit_on_signal(signum, _frame) -> None:
    raise SystemExit(128 + signum)


def install_signal_exits() -> None:
    """Turn SIGTERM/SIGHUP (and Windows Ctrl+Break, SIGBREAK) into SystemExit: their default action
    ends the process without running the `finally` blocks that stop vendor CLIs and remove the
    temporary root (and its Kimi token)."""
    for name in ("SIGTERM", "SIGHUP", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _exit_on_signal)


if __name__ == "__main__":
    install_signal_exits()
    sys.exit(main())
