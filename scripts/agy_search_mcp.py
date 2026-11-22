#!/usr/bin/env python3
"""Read-only workspace search for Google Antigravity (agy) roles: a stdio MCP server with `grep` and `glob`.

agy's runtime tools have no grep or glob (agy 1.5.14). The agy package registers this server in its
root `mcp_config.json`; agy starts it with the plugin root as its working directory and answers the
MCP `roots/list` request with the workspace folders (live probe, agy 1.5.14, 2026-11-22). Every
search is confined to those roots:

* paths come from walking the roots without following directory links; a file whose resolved path
  leaves every root (a link out of the workspace) is skipped, never read;
* `path` and `pattern` globs are relative, with no `..` segment and no drive or leading slash;
* binary files (a NUL byte in the first 8 KiB) and files over MAX_FILE_BYTES are skipped, `.git`
  and `node_modules` are not entered, and at most MAX_FILES files are looked at per call;
* a regex runs in a child process (`--worker`) that is killed after the deadline, so a pattern
  with catastrophic backtracking cannot hang the server; each line is matched on its own and only
  its first MAX_LINE_CHARS characters are searched;
* results are capped by `max_results` (at most MAX_RESULTS) and the reply by MAX_OUTPUT_CHARS.

Nothing is written. Without a root (a client that sends none and no `--root`), every call fails.

Usage:
  python3 scripts/agy_search_mcp.py [--root <dir>]... [--timeout <seconds>]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "agentic-sdlc-search", "version": "1"}
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_FILES = 20000
MAX_RESULTS = 500
DEFAULT_RESULTS = 100
MAX_LINE_CHARS = 4000
SHOWN_LINE_CHARS = 300
MAX_OUTPUT_CHARS = 60000
MAX_PATTERN_CHARS = 1000
DEFAULT_TIMEOUT_SECONDS = 10.0
SKIPPED_DIRS = frozenset({".git", "node_modules"})

TOOLS = [
    {
        "name": "grep",
        "description": (
            "Search the text files of the workspace for a pattern, read-only. Returns `path:line: text` "
            "lines with absolute paths that read_file accepts. `pattern` is a Python regular expression "
            "unless `literal` is true; each line is matched on its own. `path` is an optional glob relative "
            "to the workspace (for example `src/**/*.py`). Binary files, files over 2 MiB, .git and "
            "node_modules are skipped."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Text or regular expression to find."},
                "literal": {"type": "boolean", "description": "Match the pattern as plain text.", "default": False},
                "ignore_case": {"type": "boolean", "description": "Case-insensitive match.", "default": False},
                "path": {"type": "string", "description": "Optional workspace-relative glob of files to search."},
                "max_results": {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS,
                                "default": DEFAULT_RESULTS},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    },
    {
        "name": "glob",
        "description": (
            "List workspace files whose workspace-relative path matches a glob, read-only (for example "
            "`**/*.md` or `docs/*.txt`; `**` spans folders). Returns absolute paths that read_file accepts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Workspace-relative glob."},
                "max_results": {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS,
                                "default": DEFAULT_RESULTS},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    },
]


class ToolError(Exception):
    """A call the server refuses; the message is shown to the agent."""


# ---------------------------------------------------------------------------------------------- paths

def glob_regex(pattern: str) -> re.Pattern:
    """A workspace-relative glob as a regex over `/`-separated paths (`**/` spans zero or more folders)."""
    if not isinstance(pattern, str) or not pattern or len(pattern) > MAX_PATTERN_CHARS:
        raise ToolError("the glob must be a non-empty string of at most 1000 characters")
    pattern = pattern.replace("\\", "/")
    if pattern.startswith("/") or re.match(r"^[A-Za-z]:", pattern) or ".." in pattern.split("/"):
        raise ToolError("the glob must be relative to the workspace and must not contain '..'")
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:[^/]*/)*")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        elif pattern[i] == "[":
            end = pattern.find("]", i + 2)
            if end < 0:
                out.append(re.escape("["))
                i += 1
                continue
            body = pattern[i + 1:end]
            negate = body.startswith("!")
            body = body[1:] if negate else body
            out.append("[" + ("^" if negate else "") + body.replace("\\", "\\\\").replace("/", "") + "]")
            i = end + 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z", re.S)


def real_roots(roots) -> list:
    out = []
    for root in roots:
        try:
            real = os.path.realpath(root)
        except (OSError, ValueError):
            continue
        if os.path.isdir(real) and real not in out:
            out.append(real)
    return out


def inside(path: str, roots: list) -> bool:
    for root in roots:
        try:
            if os.path.commonpath([path, root]) == root:
                return True
        except ValueError:
            continue
    return False


def walk_files(roots: list):
    """(root, relative `/` path, absolute path) of each regular file in the roots, links resolved and confined."""
    seen = 0
    for root in roots:
        for folder, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in SKIPPED_DIRS)
            for name in sorted(files):
                seen += 1
                if seen > MAX_FILES:
                    return
                full = os.path.join(folder, name)
                try:
                    real = os.path.realpath(full)
                    if not inside(real, roots) or not os.path.isfile(real):
                        continue
                except (OSError, ValueError):
                    continue
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                yield root, rel, full


def text_lines(path: str):
    """The lines of a text file, or None for a binary, huge or unreadable one."""
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return None
        with open(path, "rb") as handle:
            data = handle.read(MAX_FILE_BYTES + 1)
    except OSError:
        return None
    if len(data) > MAX_FILE_BYTES or b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", "replace").splitlines()


# ------------------------------------------------------------------------------------------- searches

def _limit(args: dict) -> int:
    value = args.get("max_results", DEFAULT_RESULTS)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ToolError("max_results must be a positive integer")
    return min(value, MAX_RESULTS)


def _flag(args: dict, key: str) -> bool:
    value = args.get(key, False)
    if not isinstance(value, bool):
        raise ToolError(f"{key} must be true or false")
    return value


def run_glob(args: dict, roots: list) -> str:
    matcher = glob_regex(args.get("pattern"))
    limit = _limit(args)
    found = []
    for _root, rel, full in walk_files(roots):
        if matcher.match(rel):
            found.append(full)
            if len(found) >= limit:
                break
    return render(found, limit, "files")


def compile_grep(args: dict) -> re.Pattern:
    pattern = args.get("pattern")
    if not isinstance(pattern, str) or not pattern or len(pattern) > MAX_PATTERN_CHARS:
        raise ToolError("pattern must be a non-empty string of at most 1000 characters")
    flags = re.IGNORECASE if _flag(args, "ignore_case") else 0
    try:
        return re.compile(re.escape(pattern) if _flag(args, "literal") else pattern, flags)
    except re.error as exc:
        raise ToolError(f"pattern is not a valid regular expression: {exc}") from None


def run_grep(args: dict, roots: list) -> str:
    regex = compile_grep(args)
    limit = _limit(args)
    path_glob = args.get("path")
    matcher = glob_regex(path_glob) if path_glob not in (None, "") else None
    found = []
    for _root, rel, full in walk_files(roots):
        if matcher is not None and not matcher.match(rel):
            continue
        lines = text_lines(full)
        if lines is None:
            continue
        for number, line in enumerate(lines, 1):
            if regex.search(line[:MAX_LINE_CHARS]):
                shown = line.strip()
                if len(shown) > SHOWN_LINE_CHARS:
                    shown = shown[:SHOWN_LINE_CHARS] + "..."
                found.append(f"{full}:{number}: {shown}")
                if len(found) >= limit:
                    return render(found, limit, "matches")
    return render(found, limit, "matches")


def render(found: list, limit: int, noun: str) -> str:
    if not found:
        return f"No {noun}."
    out, size = [], 0
    for line in found:
        if size + len(line) + 1 > MAX_OUTPUT_CHARS:
            out.append(f"[output cut at {MAX_OUTPUT_CHARS} characters; narrow the search]")
            break
        out.append(line)
        size += len(line) + 1
    else:
        if len(found) >= limit:
            out.append(f"[stopped at max_results={limit}; narrow the search]")
    return "\n".join(out)


SEARCHES = {"grep": run_grep, "glob": run_glob}


def worker() -> int:
    """`--worker`: one search from stdin JSON {tool, args, roots}; stdout JSON {text} or {error}."""
    request = json.loads(sys.stdin.read())
    try:
        text = SEARCHES[request["tool"]](request["args"], request["roots"])
        sys.stdout.write(json.dumps({"text": text}))
    except ToolError as exc:
        sys.stdout.write(json.dumps({"error": str(exc)}))
    return 0


def call_tool(name: str, args, roots: list, timeout: float) -> str:
    if name not in SEARCHES:
        raise ToolError(f"unknown tool {name!r}")
    if not isinstance(args, dict):
        raise ToolError("arguments must be an object")
    allowed = set(TOOLS[0 if name == "grep" else 1]["inputSchema"]["properties"])
    extra = sorted(set(args) - allowed)
    if extra:
        raise ToolError("unknown argument(s): " + ", ".join(extra))
    if not roots:
        raise ToolError("no workspace root is known, so nothing can be searched")
    # Cheap checks in this process, so a bad call answers at once.
    if name == "grep":
        compile_grep(args)
        if args.get("path") not in (None, ""):
            glob_regex(args.get("path"))
    else:
        glob_regex(args.get("pattern"))
    _limit(args)
    request = json.dumps({"tool": name, "args": args, "roots": roots})
    try:
        proc = subprocess.run([sys.executable, "-I", os.path.abspath(__file__), "--worker"], input=request,
                              capture_output=True, text=True, encoding="utf-8", timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise ToolError(f"the search took longer than {timeout:g} seconds and was stopped; narrow it") from None
    try:
        answer = json.loads(proc.stdout)
    except ValueError:
        raise ToolError("the search failed") from None
    if "error" in answer:
        raise ToolError(answer["error"])
    return answer["text"]


# ------------------------------------------------------------------------------------------ transport

def uri_to_path(uri) -> str:
    if not isinstance(uri, str):
        return ""
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme != "file":
        return ""
    if parsed.netloc not in ("", "localhost"):
        return ""
    return urllib.request.url2pathname(parsed.path)


class Server:
    def __init__(self, stdin, stdout, roots, timeout: float):
        self.stdin, self.stdout = stdin, stdout
        self.fixed_roots = real_roots(roots)
        self.client_roots = None
        self.client_has_roots = False
        self.timeout = timeout
        self.next_id = 0
        self.waiting = None
        self.backlog = []

    def send(self, message: dict) -> None:
        self.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.stdout.flush()

    def request_roots(self) -> None:
        self.next_id += 1
        self.waiting = f"agentic-sdlc-roots-{self.next_id}"
        self.send({"jsonrpc": "2.0", "id": self.waiting, "method": "roots/list"})

    def roots(self) -> list:
        if self.fixed_roots:
            return self.fixed_roots
        if self.client_has_roots and self.client_roots is None:
            if self.waiting is None:
                self.request_roots()
            # Wait for the answer, keeping any other message for later.
            while self.waiting is not None:
                line = self.stdin.readline()
                if not line:
                    break
                message = self.parse(line)
                if message is not None and not self.take_roots(message):
                    self.backlog.append(message)
        return self.client_roots or []

    def take_roots(self, message: dict) -> bool:
        if "method" in message or message.get("id") != self.waiting:
            return False
        self.waiting = None
        roots = message.get("result", {}).get("roots") if isinstance(message.get("result"), dict) else None
        paths = [uri_to_path(root.get("uri")) for root in roots if isinstance(root, dict)] \
            if isinstance(roots, list) else []
        self.client_roots = real_roots([p for p in paths if p])
        return True

    def parse(self, line: str):
        try:
            message = json.loads(line)
        except ValueError:
            self.send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            return None
        if not isinstance(message, dict):
            self.send({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}})
            return None
        return message

    def handle(self, message: dict) -> None:
        if self.take_roots(message):
            return
        method = message.get("method")
        has_id = "id" in message
        if method is None:
            return  # a response this server did not wait for
        if method == "notifications/initialized":
            if self.client_has_roots and not self.fixed_roots:
                self.request_roots()
            return
        if method == "notifications/roots/list_changed":
            self.client_roots = None
            if not self.fixed_roots and self.waiting is None:
                self.request_roots()
            return
        if not has_id:
            return
        reply = {"jsonrpc": "2.0", "id": message["id"]}
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        if method == "initialize":
            capabilities = params.get("capabilities") if isinstance(params.get("capabilities"), dict) else {}
            self.client_has_roots = isinstance(capabilities.get("roots"), dict)
            asked = params.get("protocolVersion")
            reply["result"] = {
                "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[1],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            }
        elif method == "ping":
            reply["result"] = {}
        elif method == "tools/list":
            reply["result"] = {"tools": TOOLS}
        elif method == "tools/call":
            try:
                text = call_tool(params.get("name"), params.get("arguments", {}), self.roots(), self.timeout)
                reply["result"] = {"content": [{"type": "text", "text": text}], "isError": False}
            except ToolError as exc:
                reply["result"] = {"content": [{"type": "text", "text": f"error: {exc}"}], "isError": True}
        else:
            reply["error"] = {"code": -32601, "message": f"method not found: {method}"}
        self.send(reply)

    def serve(self) -> int:
        while True:
            if self.backlog:
                self.handle(self.backlog.pop(0))
                continue
            line = self.stdin.readline()
            if not line:
                return 0
            if not line.strip():
                continue
            message = self.parse(line)
            if message is not None:
                self.handle(message)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", action="append", default=[], help="search root (default: the client's MCP roots)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="seconds per search")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        return worker()
    sys.stdin.reconfigure(encoding="utf-8", newline="\n")
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    return Server(sys.stdin, sys.stdout, args.root, args.timeout).serve()


if __name__ == "__main__":
    sys.exit(main())
