#!/usr/bin/env python3
"""Read-only post-install check that Codex trusts a plugin's hooks (spec DP36).

Usage:
  python3 scripts/check_codex_hook_trust.py [--plugin <name@marketplace>] [--codex <path>] [--cwd <dir>] [--timeout <seconds>]

It starts `<codex> app-server --stdio`, sends only `initialize`, the `initialized`
notification and `hooks/list` for `--cwd`, and counts the listed hooks whose `pluginId`
equals `--plugin`. It never asks the server to change trust, writes no file, and prints no
hook key, hash, source path or working directory. A timed-out server is killed together
with its whole process tree.

Every run that parses its arguments prints exactly five lines:
  codex_hook_trust_plugin=<plugin>
  codex_hook_trust_counts=hooks:<n> trusted:<n> managed:<n> untrusted:<n> modified:<n>
  codex_hook_trust_untrusted_events=<comma list of eventName:trustStatus, or none>
  codex_hook_trust=trusted|untrusted|no-hooks|error:<name>
  codex_hook_trust_next_step=<fixed text>

Exit codes: 0 when at least one plugin hook is listed and every one is trusted or managed;
1 when any is untrusted or modified; 2 for no-hooks, every error, and usage errors.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time

DEFAULT_PLUGIN = "agentic-sdlc@personal"
ACCEPTED = ('trusted', 'managed')
STATUSES = ("trusted", "managed", "untrusted", "modified")
CLIENT_INFO = {"name": "agentic_sdlc_trust_check", "version": "1"}
EXIT_GRACE_SECONDS = 5.0
KILL_WAIT_SECONDS = 10.0
READER_JOIN_SECONDS = 5.0
MAX_EVENT_NAME = 64
NEXT_STEPS = {
    "trusted": "none",
    "untrusted": "open the Codex /hooks view, review and trust the listed hooks of this plugin, then rerun this check",
    "no-hooks": "install and enable this plugin in this Codex profile, then rerun this check",
    "error": "fix the reported error, then rerun this check",
}
_EOF = object()


class TrustCheckError(Exception):
    """A named DP36 error; `name` is printed as `codex_hook_trust=error:<name>`."""

    def __init__(self, name: str):
        super().__init__(name)
        self.name = name


def _positive_seconds(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {value!r}") from None
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive number of seconds: {value!r}")
    return seconds


def _plugin_id(value: str) -> str:
    # The plugin id is echoed on line one; a control or space character would break the block.
    if not value or any(ch.isspace() or not ch.isprintable() for ch in value):
        raise argparse.ArgumentTypeError("must be a non-empty id without spaces or control characters")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Report whether Codex trusts the hooks of an installed plugin (read-only).")
    parser.add_argument("--plugin", type=_plugin_id, default=DEFAULT_PLUGIN, help="plugin id as name@marketplace")
    parser.add_argument("--codex", default="codex", help="codex executable (resolved on PATH)")
    parser.add_argument("--cwd", default=os.curdir, help="directory whose hooks are listed")
    parser.add_argument("--timeout", type=_positive_seconds, default=60, help="seconds before the server is killed")
    return parser


def _reader(stream, sink: queue.Queue) -> None:
    try:
        for line in stream:
            sink.put(line)
    except (OSError, ValueError):
        pass
    finally:
        sink.put(_EOF)


def _send(proc: subprocess.Popen, message: dict) -> None:
    try:
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()
    except (OSError, ValueError):
        raise TrustCheckError("server_exited") from None


def _await_response(sink: queue.Queue, request_id: int, deadline: float) -> dict:
    """Return the response message for `request_id`; notifications and other ids are skipped."""
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TrustCheckError("timeout")
        try:
            item = sink.get(timeout=remaining)
        except queue.Empty:
            raise TrustCheckError("timeout") from None
        if item is _EOF:
            raise TrustCheckError("server_exited")
        line = item.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            raise TrustCheckError("malformed_response") from None
        if not isinstance(message, dict):
            raise TrustCheckError("malformed_response")
        if "method" in message:
            continue
        msg_id = message.get("id")
        if type(msg_id) is not int or msg_id != request_id:
            continue
        if "error" in message:
            raise TrustCheckError("rpc_error")
        if "result" not in message:
            raise TrustCheckError("malformed_response")
        return message


def _terminate_tree(proc: subprocess.Popen) -> None:
    if sys.platform == "win32":
        if proc.poll() is None:
            try:
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=KILL_WAIT_SECONDS,
                )
            except (OSError, subprocess.SubprocessError):
                proc.kill()
    else:
        # The server leads its own session, so its group id is its pid.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        proc.wait(timeout=KILL_WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        pass


def query_hooks(command: str, cwd: str, timeout: float) -> dict:
    """Run the three-message exchange and return the `hooks/list` response message."""
    deadline = time.monotonic() + timeout
    if sys.platform == "win32":
        group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        group = {"start_new_session": True}
    try:
        proc = subprocess.Popen(
            [command, "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            **group,
        )
    except (OSError, ValueError):
        raise TrustCheckError("spawn_failed") from None
    sink: queue.Queue = queue.Queue()
    reader = threading.Thread(target=_reader, args=(proc.stdout, sink), daemon=True)
    reader.start()
    try:
        _send(proc, {"id": 1, "method": "initialize", "params": {"clientInfo": CLIENT_INFO, "capabilities": {"experimentalApi": False}}})
        _await_response(sink, 1, deadline)
        _send(proc, {"method": "initialized"})
        _send(proc, {"id": 2, "method": "hooks/list", "params": {"cwds": [cwd]}})
        response = _await_response(sink, 2, deadline)
        try:
            proc.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            proc.wait(timeout=max(0.0, min(deadline - time.monotonic(), EXIT_GRACE_SECONDS)))
        except subprocess.TimeoutExpired:
            pass
        return response
    finally:
        _terminate_tree(proc)
        # Closing a pipe another thread is reading can block on Windows: join first, bounded.
        reader.join(timeout=READER_JOIN_SECONDS)
        for stream in (proc.stdin, proc.stdout):
            if stream is proc.stdout and reader.is_alive():
                continue
            try:
                stream.close()
            except (OSError, ValueError):
                pass


def _valid_event_name(value) -> bool:
    return isinstance(value, str) and 0 < len(value) <= MAX_EVENT_NAME and value.isascii() and value.isalpha()


def evaluate(response: dict, plugin: str) -> tuple[int, dict, list]:
    """Count `result.data[].hooks[]` of `plugin`; any shape outside the schema is malformed."""
    result = response.get("result")
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, list):
        raise TrustCheckError("malformed_response")
    counts = dict.fromkeys(STATUSES, 0)
    events: list[str] = []
    total = 0
    for entry in data:
        if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
            raise TrustCheckError("malformed_response")
        for hook in entry["hooks"]:
            if not isinstance(hook, dict):
                raise TrustCheckError("malformed_response")
            if hook.get("pluginId") != plugin:
                continue
            status = hook.get("trustStatus")
            event = hook.get("eventName")
            if not isinstance(status, str) or status not in STATUSES or not _valid_event_name(event):
                raise TrustCheckError("malformed_response")
            total += 1
            counts[status] += 1
            if status not in ACCEPTED:
                events.append(f"{event}:{status}")
    return total, counts, events


def _block(plugin: str, total: int, counts: dict, events: list, state: str, step: str) -> str:
    count_text = " ".join([f"hooks:{total}"] + [f"{name}:{counts[name]}" for name in STATUSES])
    return "\n".join(
        [
            f"codex_hook_trust_plugin={plugin}",
            f"codex_hook_trust_counts={count_text}",
            f"codex_hook_trust_untrusted_events={','.join(events) if events else 'none'}",
            f"codex_hook_trust={state}",
            f"codex_hook_trust_next_step={step}",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    total, counts, events = 0, dict.fromkeys(STATUSES, 0), []
    try:
        command = shutil.which(args.codex)
        if command is None:
            raise TrustCheckError("codex_not_found")
        if not os.path.isdir(args.cwd):
            raise TrustCheckError("cwd_not_found")
        response = query_hooks(command, os.path.abspath(args.cwd), args.timeout)
        total, counts, events = evaluate(response, args.plugin)
    except TrustCheckError as exc:
        print(_block(args.plugin, 0, dict.fromkeys(STATUSES, 0), [], f"error:{exc.name}", NEXT_STEPS["error"]))
        return 2
    if total == 0:
        state, code = "no-hooks", 2
    elif not events:
        state, code = "trusted", 0
    else:
        state, code = "untrusted", 1
    print(_block(args.plugin, total, counts, events, state, NEXT_STEPS[state]))
    return code


if __name__ == "__main__":
    sys.exit(main())
