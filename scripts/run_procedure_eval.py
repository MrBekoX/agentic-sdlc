"""Run or analyze transcript-based Claude procedure evals.

This checks more than "did the skill trigger?". It inspects stream-json tool use
and optional filesystem artifacts to verify that a workflow used required skills,
commands, workflows, and did not run forbidden commands.

Dry/schema mode:
  python scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --dry-run

Analyze an existing transcript:
  python scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --transcript transcript.jsonl

Live mode (consent required: the harness commits a baseline inside each isolated fixture copy):
  python scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --live --allow-fixture-commit

Strict grading of a captured transcript or rollout, with masked evidence packets:
  python scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json \
    --transcript <file> --strict-evidence --evidence-dir <dir> --fixture-root <fixture copy>
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from scripts.eval_safety import require_link_free_tree, require_relative_pattern, require_slug, resolve_under
    from scripts.sensitive_redaction import redact_json, redact_text
except ModuleNotFoundError:
    from eval_safety import require_link_free_tree, require_relative_pattern, require_slug, resolve_under
    from sensitive_redaction import redact_json, redact_text


REPO = Path(__file__).resolve().parents[1]

# A required gate skill can also be satisfied by dispatching its specialist agent
# (the fresh-context delegation path the pipeline prefers, e.g. security-audit -> the
# security-reviewer agent). Without this, a model strong enough to delegate the gate to a
# sub-agent is wrongly scored as "missing_skill". Map: skill short-name -> agent short-names.
SKILL_AGENT_EQUIVALENTS: dict[str, list[str]] = {
    "security-audit": ["security-reviewer"],
    "implementation-control": ["implementation-auditor"],
    "code-quality-review": ["code-reviewer"],
    "test-authoring": ["test-engineer"],
}

# Decision skills whose intent (choosing the execution mechanism) is satisfied by actually
# dispatching a sub-agent — dispatch-strategy decides "main loop vs sub-agent vs workflow vs team",
# so a real Agent/Task dispatch IS that decision exercised. A model that does everything inline with
# no dispatch still fails the gate (no Agent call), so this credits delegation without trivializing it.
DELEGATION_SATISFIES: set[str] = {"dispatch-strategy"}

# Per-package layout (BR1/BR2/BR11): docs/agentic-sdlc/<slug>/{spec,plan}/<work_id>.md.
# The slug rule is triplicated by design across the resolver (scripts/resolve_work_package.py),
# the flow-guard config (hooks/flow-requirements.json), and this offline gate; the three copies
# are kept byte-identical by tests.test_procedure_eval.test_slug_rule_parity_across_sources.
RESERVED_SLUGS = {"specs", "plans", "evidence", "notes", "spec", "plan"}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_PER_PACKAGE_PATH_RE = re.compile(r"(?:^|/)docs/agentic-sdlc/([^/]+)/(spec|plan)/([^/]+)\.md$")


def per_package_layout(norm: str) -> tuple[str, str, str] | None:
    """Classify a per-package spec/plan write path -> (mode, slug, work_id) | None.

    Matches docs/agentic-sdlc/<slug>/spec|plan/<id>.md via the SINGULAR /spec/ and /plan/
    path SEGMENT — never the flat plural /specs/,/plans/ roots — so the flat-substring
    classification in evaluate_artifact_depth stays byte-identical. The slug is validated
    against the shared kebab regex + reserved-name set (parity-pinned with the resolver and
    flow-guard config). A reserved or malformed slug (e.g. docs/agentic-sdlc/spec/spec/x.md)
    returns None, leaving the path to the flat classifier (which also rejects it).
    """
    norm = norm.replace("\\", "/")
    m = _PER_PACKAGE_PATH_RE.search(norm)
    if not m:
        return None
    slug, mode, work_id = m.group(1), m.group(2), m.group(3)
    if not SLUG_RE.match(slug) or slug in RESERVED_SLUGS:
        return None
    return (mode, slug, work_id)


@dataclass
class Trace:
    tools: list[str] = field(default_factory=list)
    tool_inputs: list[dict[str, Any]] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    artifact_writes: list[tuple[str, str]] = field(default_factory=list)
    runtime_errors: list[str] = field(default_factory=list)
    permission_denials: list[str] = field(default_factory=list)
    text: str = ""
    # Additive strict-grading fields. haystack() excludes them, so its payload keys stay unchanged.
    timeline: list[dict[str, Any]] = field(default_factory=list)
    final_assistant_text: str = ""
    runtime: str = "unknown"  # claude | codex-exec | codex-rollout | unknown
    meta: dict[str, str] = field(default_factory=dict)
    strict_errors: list[str] = field(default_factory=list)
    # Per call id: full blocks, streamed reconstructions and output records.
    call_event_counts: dict[str, dict[str, int]] = field(default_factory=dict)

    def haystack(self) -> str:
        payload = {
            "tools": self.tools,
            "tool_inputs": self.tool_inputs,
            "commands": self.commands,
            "writes": self.writes,
            "runtime_errors": self.runtime_errors,
            "permission_denials": self.permission_denials,
            "text": self.text,
        }
        return json.dumps(payload, ensure_ascii=False)


def read_transcript_text(path: Path) -> str:
    """Decode a transcript as the parser reads it: UTF-16 with a BOM, UTF-8 with or without a BOM."""
    raw_bytes = Path(path).read_bytes()
    if raw_bytes.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw_bytes.decode("utf-16", errors="replace")
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        return raw_bytes.decode("utf-8-sig", errors="replace")
    return raw_bytes.decode("utf-8", errors="replace")


def load_json_lines(path: Path) -> list[dict[str, Any]]:
    events = []
    text = read_transcript_text(path)
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            events.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return events


def _record_tool(trace: Trace, name: str, input_obj: Any) -> None:
    payload = input_obj if isinstance(input_obj, dict) else {}
    trace.tools.append(name)
    trace.tool_inputs.append({"name": name, "input": payload})
    command = payload.get("command") if isinstance(payload, dict) else None
    if isinstance(command, str):
        trace.commands.append(command)
    file_path = payload.get("file_path") if isinstance(payload, dict) else None
    if isinstance(file_path, str):
        trace.writes.append(file_path)
    content = payload.get("content") if isinstance(payload, dict) else None
    if isinstance(file_path, str) and isinstance(content, str):
        trace.artifact_writes.append((file_path, content))


def _record_codex_item(trace: Trace, item: dict[str, Any]) -> None:
    """Record current `codex exec --json` item events.

    Codex does not emit Claude-style `tool_use` blocks. Its transcript uses
    `item.completed` / `item.started` envelopes with typed items such as
    `command_execution`, `file_change`, `todo_list`, and `agent_message`.
    """
    item_type = item.get("type")
    if item_type == "agent_message":
        text = item.get("text")
        if isinstance(text, str):
            trace.text += "\n" + text
        return

    if item_type == "command_execution":
        command = item.get("command")
        output = item.get("aggregated_output")
        payload = {
            "command": command,
            "status": item.get("status"),
            "exit_code": item.get("exit_code"),
        }
        _record_tool(trace, "command_execution", payload)
        if isinstance(output, str) and output:
            trace.text += "\n" + output
        if item.get("status") == "declined":
            detail = f"command_execution:{command}" if isinstance(command, str) else "command_execution"
            trace.permission_denials.append(detail)
        return

    if item_type == "file_change":
        trace.tools.append("file_change")
        changes = item.get("changes", [])
        if not isinstance(changes, list):
            return
        for change in changes:
            if not isinstance(change, dict):
                continue
            path = change.get("path")
            if isinstance(path, str):
                trace.writes.append(path)
                trace.tool_inputs.append({"name": "file_change", "input": change})
        return

    if item_type == "todo_list":
        trace.tools.append("todo_list")
        items = item.get("items", [])
        if not isinstance(items, list):
            return
        todo_text: list[str] = []
        for todo in items:
            if not isinstance(todo, dict):
                continue
            trace.tool_inputs.append({"name": "todo_list", "input": todo})
            text = todo.get("text")
            if isinstance(text, str):
                todo_text.append(text)
        if todo_text:
            trace.text += "\n" + "\n".join(todo_text)
        return

    if item_type == "error":
        message = item.get("message")
        if isinstance(message, str):
            trace.text += "\n" + message


# One node process (fixed argv, no shell) reuses the hook exports instead of re-implementing them:
# parseCodexExitCode (hooks/codex-rollout.mjs) and isRealRunnerInvocation (hooks/flow-evidence.mjs).
NODE_HELPERS_JS = (
    "import { pathToFileURL } from 'node:url';"
    "let s='';process.stdin.on('data',d=>s+=d).on('end',async()=>{"
    "const q=JSON.parse(s);const out={exits:[],real:[]};"
    "if(q.texts.length){const r=await import(pathToFileURL(q.rollout).href);"
    "out.exits=q.texts.map(t=>r.parseCodexExitCode(t));}"
    "if(q.commands.length){const f=await import(pathToFileURL(q.flow).href);"
    "const re=new RegExp(q.testCommand,'i');out.real=q.commands.map(c=>f.isRealRunnerInvocation(c,re));}"
    "process.stdout.write(JSON.stringify(out));});"
)


def run_node_helpers(*, texts: list[str] | None = None, commands: list[str] | None = None,
                     test_command: str = "") -> dict[str, list[Any]] | None:
    """Batch Codex exit parsing and real-runner classification; None (fail closed) if node is unusable."""
    request = {
        "rollout": str(REPO / "hooks" / "codex-rollout.mjs"),
        "flow": str(REPO / "hooks" / "flow-evidence.mjs"),
        "testCommand": test_command,
        "texts": list(texts or []),
        "commands": list(commands or []),
    }
    node = shutil.which("node")
    if not node:
        return None
    try:
        proc = subprocess.run(
            [node, "--input-type=module", "-e", NODE_HELPERS_JS],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        if proc.returncode != 0:
            return None
        out = json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    exits, real = out.get("exits"), out.get("real")
    if not (isinstance(exits, list) and len(exits) == len(request["texts"])
            and isinstance(real, list) and len(real) == len(request["commands"])):
        return None
    return {"exits": [e if type(e) is int else None for e in exits], "real": [r is True for r in real]}


def _call_counts(trace: Trace, call_id: str) -> dict[str, int]:
    return trace.call_event_counts.setdefault(call_id, {"full": 0, "streamed": 0, "outputs": 0})


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part["text"] for part in content if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return ""


def _assistant_text(trace: Trace, text: str) -> None:
    trace.text += "\n" + text
    trace.timeline.append({"kind": "assistant_text", "text": text})


def _record_claude_user(trace: Trace, event: dict[str, Any]) -> None:
    """Claude `user` events: tool_result blocks and user text fill the timeline only."""
    message = event.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        trace.timeline.append({"kind": "user_text", "text": content})
        return
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_result":
            tool_id = block.get("tool_use_id")
            tool_id = tool_id if isinstance(tool_id, str) and tool_id else None
            is_error = block.get("is_error") is True
            if tool_id:
                _call_counts(trace, tool_id)["outputs"] += 1
            trace.timeline.append({
                "kind": "tool_result", "id": tool_id, "is_error": is_error,
                "text": _text_of(block.get("content")), "exit": 1 if is_error else 0,
            })
        elif block.get("type") == "text" and isinstance(block.get("text"), str):
            trace.timeline.append({"kind": "user_text", "text": block["text"]})


def _record_strict_exec_item(trace: Trace, etype: str, item: dict[str, Any], completed_ids: set[str]) -> None:
    """Strict `codex exec --json`: only item.completed counts; a repeated completed id is counted, not re-recorded."""
    if etype != "item.completed":
        return
    item_id = item.get("id")
    item_id = item_id if isinstance(item_id, str) and item_id else None
    item_type = item.get("type")
    if item_type == "command_execution" and item_id:
        # One completed command_execution is both the call event and its output record.
        counts = _call_counts(trace, item_id)
        counts["full"] += 1
        counts["outputs"] += 1
    if item_id:
        if item_id in completed_ids:
            return
        completed_ids.add(item_id)
    _record_codex_item(trace, item)
    if item_type == "agent_message" and isinstance(item.get("text"), str):
        trace.timeline.append({"kind": "assistant_text", "text": item["text"]})
    elif item_type == "command_execution":
        exit_code = item.get("exit_code") if type(item.get("exit_code")) is int else None
        output = item.get("aggregated_output")
        trace.timeline.append({"kind": "tool_call", "id": item_id, "name": "command_execution",
                               "input": {"command": item.get("command")}})
        trace.timeline.append({"kind": "tool_result", "id": item_id, "is_error": exit_code not in (0, None),
                               "text": output if isinstance(output, str) else "", "exit": exit_code})
    elif item_type == "file_change":
        for change in item.get("changes") if isinstance(item.get("changes"), list) else []:
            if isinstance(change, dict) and isinstance(change.get("path"), str):
                trace.timeline.append({"kind": "write", "path": change["path"]})


ROLLOUT_TYPES = {"response_item", "event_msg", "session_meta", "turn_context"}
APPLY_PATCH_SUCCESS = "Success. Updated the following files"


def _rollout_payload(event: dict[str, Any]) -> dict[str, Any] | None:
    payload = event.get("payload")
    return payload if event.get("type") in ROLLOUT_TYPES and isinstance(payload, dict) else None


def _rollout_output_text(output: Any) -> str:
    """A tool output persisted as a bare string or as {content: string | text parts}."""
    if isinstance(output, dict):
        return _text_of(output.get("content"))
    return _text_of(output)


def _native_output_body(text: str) -> str | None:
    """The text after the first `Output:` line, the line that ends the native leading metadata."""
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if line.strip() == "Output:":
            return "\n".join(lines[index + 1:])
    return None


def _exec_command_text(arguments: Any) -> str | None:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return None
    cmd = arguments.get("cmd") if isinstance(arguments, dict) else None
    if isinstance(cmd, str):
        return cmd
    if isinstance(cmd, list) and all(isinstance(part, str) for part in cmd):
        return " ".join(cmd)
    return None


def _patch_writes(patch: str) -> list[tuple[str, str]]:
    """Add File targets with content rebuilt from `+` lines; Update File targets with empty content."""
    targets: list[tuple[str, list[str] | None]] = []
    current: list[str] | None = None
    for line in patch.split("\n"):
        if line.startswith("*** Add File: "):
            current = []
            targets.append((line[len("*** Add File: "):].strip(), current))
        elif line.startswith("*** Update File: "):
            current = None
            targets.append((line[len("*** Update File: "):].strip(), None))
        elif line.startswith("*** "):
            current = None
        elif current is not None and line.startswith("+"):
            current.append(line[1:])
    # An empty Update content lets the on-disk file win in evaluate_artifact_depth.
    return [(path, "\n".join(lines) + "\n" if lines else "") for path, lines in targets]


def _rollout_exit_codes(events: list[dict[str, Any]], trace: Trace) -> dict[int, int | None]:
    """Parse every rollout tool output's exit code in one node process, keyed by event position."""
    positions: list[int] = []
    texts: list[str] = []
    for position, event in enumerate(events):
        payload = _rollout_payload(event)
        if payload is not None and payload.get("type") in ("function_call_output", "custom_tool_call_output"):
            positions.append(position)
            texts.append(_rollout_output_text(payload.get("output")))
    if not texts:
        return {}
    parsed = run_node_helpers(texts=texts)
    if parsed is None:
        trace.strict_errors.append("strict_codex_exit_parser_unavailable")
        return {}  # fail closed: every exit stays None
    return dict(zip(positions, parsed["exits"]))


def _record_rollout(trace: Trace, rtype: str, payload: dict[str, Any], exit_code: int | None,
                    pending_patches: dict[str, str]) -> None:
    """Strict-only Codex rollout carriers (D10: absent protocol keys leave meta unset, never raise)."""
    ptype = payload.get("type")
    call_id = payload.get("call_id") if isinstance(payload.get("call_id"), str) and payload.get("call_id") else None
    if rtype == "session_meta":
        if isinstance(payload.get("cli_version"), str):
            trace.meta["cli_version"] = payload["cli_version"]
    elif rtype == "turn_context":
        for key in ("model", "effort"):
            if isinstance(payload.get(key), str):
                trace.meta[key] = payload[key]
    elif ptype == "function_call" and payload.get("name") == "exec_command":
        command = _exec_command_text(payload.get("arguments"))
        if call_id:
            _call_counts(trace, call_id)["full"] += 1
        _record_tool(trace, "exec_command", {"command": command, "call_id": call_id})
        trace.timeline.append({"kind": "tool_call", "id": call_id, "name": "exec_command",
                               "input": {"command": command}})
    elif ptype == "function_call_output":
        if call_id:
            _call_counts(trace, call_id)["outputs"] += 1
        trace.timeline.append({"kind": "tool_result", "id": call_id, "is_error": exit_code not in (0, None),
                               "text": _rollout_output_text(payload.get("output")), "exit": exit_code})
    elif ptype == "custom_tool_call" and payload.get("name") == "apply_patch":
        if call_id and isinstance(payload.get("input"), str):
            pending_patches[call_id] = payload["input"]
    elif ptype == "custom_tool_call_output":
        patch = pending_patches.pop(call_id, None) if call_id else None
        body = _native_output_body(_rollout_output_text(payload.get("output")))
        # A patch counts as a write only after its correlated output confirms success (a blocked or
        # failed attempt is not a write).
        if patch is not None and exit_code == 0 and body is not None and body.startswith(APPLY_PATCH_SUCCESS):
            for path, content in _patch_writes(patch):
                trace.writes.append(path)
                trace.artifact_writes.append((path, content))
                trace.timeline.append({"kind": "write", "path": path})
    elif rtype == "response_item" and ptype == "message":
        parts = payload.get("content") if isinstance(payload.get("content"), list) else []
        text = "\n".join(
            part["text"] for part in parts
            if isinstance(part, dict) and part.get("type") in ("output_text", "input_text", "text")
            and isinstance(part.get("text"), str)
        )
        if text and payload.get("role") == "assistant":
            _assistant_text(trace, text)
        elif text and payload.get("role") == "user":
            trace.timeline.append({"kind": "user_text", "text": text})
    elif rtype == "event_msg" and ptype == "agent_message" and isinstance(payload.get("message"), str):
        _assistant_text(trace, payload["message"])
    elif rtype == "event_msg" and ptype == "user_message" and isinstance(payload.get("message"), str):
        trace.timeline.append({"kind": "user_text", "text": payload["message"]})
    elif rtype == "event_msg" and ptype in ("task_complete", "turn_complete"):
        last = payload.get("last_agent_message")
        if isinstance(last, str):
            trace.final_assistant_text = last
            _assistant_text(trace, last)
        if payload.get("error"):
            trace.runtime_errors.append("turn_error")


def trace_events(events: list[dict[str, Any]], *, strict: bool = False) -> Trace:
    trace = Trace()
    partial: dict[int, dict[str, Any]] = {}
    # AC63: a streamed tool_use reconstruction and its full assistant block share one id; record the
    # call once. The full block is authoritative: when it follows a streamed record (possibly unparseable
    # or empty), it replaces that record in place. Blocks without an id keep the 5801cb9 behavior.
    recorded_ids: set[str] = set()
    streamed_records: dict[str, dict[str, Any]] = {}
    tool_lists = ("tools", "tool_inputs", "commands", "writes", "artifact_writes")  # every list _record_tool fills

    def set_runtime(name: str) -> None:
        if trace.runtime == "unknown":
            trace.runtime = name

    def tool_record(tool_id: Any, name: str, input_obj: Any) -> tuple[Trace, list[dict[str, Any]]]:
        record = Trace()
        _record_tool(record, name, input_obj)
        entries = [{
            "kind": "tool_call",
            "id": tool_id if isinstance(tool_id, str) and tool_id else None,
            "name": name,
            "input": input_obj if isinstance(input_obj, dict) else {},
        }]
        file_path = input_obj.get("file_path") if isinstance(input_obj, dict) else None
        if name in ("Write", "Edit", "MultiEdit", "NotebookEdit") and isinstance(file_path, str):
            entries.append({"kind": "write", "path": file_path})
        return record, entries

    def replace_streamed(old: dict[str, Any], record: Trace, entries: list[dict[str, Any]]) -> None:
        for key in tool_lists:
            start, old_len, new = old["starts"][key], len(getattr(old["record"], key)), getattr(record, key)
            getattr(trace, key)[start:start + old_len] = new
            for later in streamed_records.values():  # streamed after `old`, so positioned after it
                if later["seq"] > old["seq"]:
                    later["starts"][key] += len(new) - old_len
        at = next(i for i, entry in enumerate(trace.timeline) if entry is old["entries"][0])
        trace.timeline[at:at + len(old["entries"])] = entries

    def record_once(tool_id: Any, name: str, input_obj: Any, carrier: str) -> None:
        has_id = isinstance(tool_id, str) and bool(tool_id)
        if has_id:
            _call_counts(trace, tool_id)[carrier] += 1
        record, entries = tool_record(tool_id, name, input_obj)
        if has_id and tool_id in recorded_ids:
            if carrier == "full" and tool_id in streamed_records:
                replace_streamed(streamed_records.pop(tool_id), record, entries)
            return
        starts = {key: len(getattr(trace, key)) for key in tool_lists}
        for key in tool_lists:
            getattr(trace, key).extend(getattr(record, key))
        trace.timeline.extend(entries)
        if has_id:
            recorded_ids.add(tool_id)
            if carrier == "streamed":
                streamed_records[tool_id] = {"seq": len(recorded_ids), "starts": starts, "record": record,
                                             "entries": entries}

    # Default mode (strict False) ignores rollout records exactly as at 5801cb9.
    rollout_exits = _rollout_exit_codes(events, trace) if strict else {}
    pending_patches: dict[str, str] = {}
    completed_exec_ids: set[str] = set()

    for position, event in enumerate(events):
        etype = event.get("type")
        if etype == "assistant":
            set_runtime("claude")
            for item in event.get("message", {}).get("content", []):
                if item.get("type") == "text":
                    trace.text += "\n" + item.get("text", "")
                    trace.timeline.append({"kind": "assistant_text", "text": item.get("text", "")})
                elif item.get("type") == "tool_use":
                    record_once(item.get("id"), item.get("name", ""), item.get("input", {}), "full")
        elif etype == "user":
            set_runtime("claude")
            _record_claude_user(trace, event)
        elif etype == "system":
            if event.get("subtype") == "init":
                set_runtime("claude")
                for source, key in (("model", "model"), ("claude_code_version", "cli_version")):
                    if isinstance(event.get(source), str):
                        trace.meta[key] = event[source]
        elif etype == "stream_event":
            se = event.get("event", {})
            stype = se.get("type")
            index = int(se.get("index", 0))
            if stype == "content_block_start":
                block = se.get("content_block", {})
                if block.get("type") == "tool_use":
                    partial[index] = {"name": block.get("name", ""), "json": "", "id": block.get("id")}
                elif block.get("type") == "text":
                    partial[index] = {"name": "__text__", "json": ""}
            elif stype == "content_block_delta":
                delta = se.get("delta", {})
                if delta.get("type") == "text_delta":
                    trace.text += delta.get("text", "")
                    if index in partial and partial[index]["name"] == "__text__":
                        partial[index]["json"] += delta.get("text", "")
                elif delta.get("type") == "input_json_delta" and index in partial:
                    partial[index]["json"] += delta.get("partial_json", "")
            elif stype == "content_block_stop" and index in partial:
                pending = partial.pop(index)
                if pending["name"] == "__text__":
                    if pending["json"]:
                        trace.timeline.append({"kind": "assistant_text", "text": pending["json"]})
                elif pending["name"]:
                    try:
                        input_obj = json.loads(pending["json"] or "{}")
                    except json.JSONDecodeError:
                        input_obj = {"_raw": pending["json"]}
                    record_once(pending.get("id"), pending["name"], input_obj, "streamed")
        elif etype == "result":
            result = event.get("result")
            if isinstance(result, str):
                trace.text += "\n" + result
            subtype = event.get("subtype")
            if event.get("is_error") or (isinstance(subtype, str) and subtype.startswith("error")):
                trace.runtime_errors.append(str(subtype or "result_error"))
            for error in event.get("errors") or []:
                trace.runtime_errors.append(str(error))
            for denial in event.get("permission_denials") or []:
                if not isinstance(denial, dict):
                    trace.permission_denials.append(str(denial))
                    continue
                tool_name = denial.get("tool_name") or "unknown"
                tool_input = denial.get("tool_input") or {}
                command = tool_input.get("command") if isinstance(tool_input, dict) else None
                detail = f"{tool_name}:{command}" if command else str(tool_name)
                trace.permission_denials.append(detail)
        elif etype in {"item.started", "item.completed", "item.updated"}:
            set_runtime("codex-exec")
            item = event.get("item")
            if isinstance(item, dict):
                if strict:
                    _record_strict_exec_item(trace, etype, item, completed_exec_ids)
                else:
                    _record_codex_item(trace, item)
        elif etype in {"turn.failed", "error"}:
            message = event.get("message") or event.get("error")
            trace.runtime_errors.append(str(message or etype))
        elif strict and (payload := _rollout_payload(event)) is not None:
            set_runtime("codex-rollout")
            _record_rollout(trace, event.get("type"), payload, rollout_exits.get(position), pending_patches)
    return trace


def load_eval(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("eval set must contain non-empty 'cases'")
    for case in cases:
        if not isinstance(case.get("id"), str) or not case["id"].strip():
            raise ValueError("case missing id")
        require_slug(case["id"], "case id")
        if not isinstance(case.get("prompt"), str) or not case["prompt"].strip():
            raise ValueError(f"case {case['id']} missing prompt")
        for key in (
            "required_skills",
            "required_workflows",
            "required_commands",
            "required_artifacts",
            "forbidden_commands",
            "required_patterns",
            "forbidden_patterns",
        ):
            values = case.get(key, [])
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                raise ValueError(f"case {case['id']} invalid {key}")
            if key.endswith("patterns") or key.endswith("commands"):
                for value in values:
                    re.compile(value)
            if key == "required_artifacts":
                for value in values:
                    require_relative_pattern(value, f"case {case['id']} required artifact")
        fixture = case.get("fixture_dir")
        if fixture is not None:
            if not isinstance(fixture, str) or not fixture.strip():
                raise ValueError(f"case {case['id']} invalid fixture_dir")
            src = resolve_under(REPO, fixture, f"case {case['id']} fixture_dir", must_exist=True)
            if not src.is_dir():
                raise ValueError(f"case {case['id']} fixture_dir is not a directory: {fixture}")
        adapters = case.get("required_runtime_adapters", [])
        if not isinstance(adapters, list):
            raise ValueError(f"case {case['id']} invalid required_runtime_adapters")
        for adapter in adapters:
            if not isinstance(adapter, dict):
                raise ValueError(f"case {case['id']} invalid required_runtime_adapters")
            patterns = adapter.get("required_patterns", [])
            if not isinstance(patterns, list) or not all(isinstance(v, str) for v in patterns):
                raise ValueError(f"case {case['id']} invalid required_runtime_adapters.required_patterns")
            for pattern in patterns:
                re.compile(pattern)
            satisfies = adapter.get("satisfies", [])
            if not isinstance(satisfies, list) or not all(isinstance(v, str) for v in satisfies):
                raise ValueError(f"case {case['id']} invalid required_runtime_adapters.satisfies")
        if "strict" in case:
            validate_strict_config(case["id"], case["strict"])
    return cases


def regex_present(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text, re.IGNORECASE | re.MULTILINE))


def artifact_present(pattern: str, trace: Trace, cwd: Path) -> bool:
    if any(pattern.replace("\\", "/") in w.replace("\\", "/") for w in trace.writes):
        return True
    require_relative_pattern(pattern, "required artifact")
    candidates = list(cwd.glob(pattern)) if any(ch in pattern for ch in "*?[]") else [resolve_under(cwd, pattern, "required artifact")]
    return any(p.exists() for p in candidates)


def artifact_escapes(pattern: str, cwd: Path, contained_root: Path) -> bool:
    """AC124: an absolute or `..` pattern, or any candidate resolving (through links) outside the root."""
    raw = Path(pattern)
    if raw.is_absolute() or ".." in raw.parts:
        return True
    root = Path(contained_root).resolve()
    candidates = list(cwd.glob(pattern)) if any(ch in pattern for ch in "*?[]") else [cwd / pattern]
    # Only existence and resolution are evaluated here, never file content.
    return any(not path_within(candidate.resolve(), root) for candidate in candidates)


def expected_aliases(expected: str) -> list[str]:
    aliases = [expected]
    if ":" in expected:
        aliases.append(expected.rsplit(":", 1)[-1])
    return aliases


def tool_invoked(trace: Trace, tool_name: str, expected: str) -> bool:
    aliases = expected_aliases(expected)
    for item in trace.tool_inputs:
        if item.get("name", "").lower() != tool_name.lower():
            continue
        payload = item.get("input", {})
        payload_text = json.dumps(payload, ensure_ascii=False)
        if any(alias in payload_text for alias in aliases):
            return True
    return False


def required_skill_satisfied(trace: Trace, expected: str) -> bool:
    """A required gate is met by a `Skill` call OR a dispatch to its specialist agent.

    The pipeline lets review/audit gates run as fresh-context sub-agents (e.g. security-audit
    via the security-reviewer agent); credit that as satisfying the gate.
    """
    if tool_invoked(trace, "Skill", expected):
        return True
    short = expected.rsplit(":", 1)[-1]
    for agent in SKILL_AGENT_EQUIVALENTS.get(short, []):
        if tool_invoked(trace, "Agent", agent) or tool_invoked(trace, "Task", agent):
            return True
    if short in DELEGATION_SATISFIES and ("Agent" in trace.tools or "Task" in trace.tools):
        return True
    return False


def runtime_adapter_satisfied(trace: Trace, adapter: dict[str, Any]) -> bool:
    patterns = adapter.get("required_patterns", [])
    if not isinstance(patterns, list):
        return False
    haystack = trace.haystack()
    return all(isinstance(pattern, str) and regex_present(pattern, haystack) for pattern in patterns)


def runtime_adapter_satisfies(trace: Trace, case: dict[str, Any], kind: str, expected: str) -> bool:
    adapters = case.get("required_runtime_adapters", [])
    aliases = [f"{kind}:{alias}" for alias in expected_aliases(expected)]
    for adapter in adapters:
        if not isinstance(adapter, dict):
            continue
        satisfies = adapter.get("satisfies")
        if isinstance(satisfies, list):
            if not any(isinstance(item, str) and item in aliases for item in satisfies):
                continue
        elif kind != "workflow":
            continue
        if runtime_adapter_satisfied(trace, adapter):
            return True
    return False


def _load_validator():
    spec = importlib.util.spec_from_file_location("validate_artifacts", REPO / "scripts" / "validate_artifacts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def evaluate_artifact_depth(trace: Trace, cwd: Path) -> list[str]:
    """For each canonical spec/plan artifact written, validate its CONTENT in strict mode.

    Content is taken from the transcript write (transcript mode) or the on-disk file
    (live mode). A literal stub like "spec" fails validation -> shallow_artifact error.
    """
    validator = _load_validator()
    errors: list[str] = []
    # latest content wins if the same path is written more than once
    latest: dict[str, str] = {}
    for path, content in trace.artifact_writes:
        norm = path.replace("\\", "/")
        # Additive: keep the flat plural-substring gate, also admit per-package
        # (singular /spec/, /plan/ segment) writes. Flat detection is unchanged.
        if (
            "docs/agentic-sdlc/specs/" in norm
            or "docs/agentic-sdlc/plans/" in norm
            or per_package_layout(norm) is not None
        ):
            latest[norm] = content
    for norm, content in sorted(latest.items()):
        try:
            disk = resolve_under(cwd, norm, "artifact write path")
        except ValueError:
            errors.append(f"unsafe_artifact_path:{norm}")
            continue
        text = disk.read_text(encoding="utf-8") if disk.exists() else content
        # Per-package mode comes from the singular-segment classifier; flat falls back
        # to the existing plural-substring test verbatim (provably unchanged for flat).
        pp = per_package_layout(norm)
        mode = pp[0] if pp is not None else ("spec" if "/specs/" in norm else "plan")
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as tf:
            tf.write(text)
            tmp = Path(tf.name)
        spec_arg = None
        try:
            if mode == "plan":
                if pp is not None:
                    # per-package plan pairs with its same-slug per-package spec written in the run
                    spec_path = next(
                        (
                            p
                            for p in latest
                            if (cand := per_package_layout(p)) is not None
                            and cand[0] == "spec"
                            and cand[1] == pp[1]
                        ),
                        None,
                    )
                else:
                    # flat plan pairing unchanged: pair with any flat spec written in the run
                    spec_path = next((p for p in latest if "/specs/" in p), None)
                if spec_path:
                    try:
                        sp = resolve_under(cwd, spec_path, "paired spec path")
                    except ValueError:
                        errors.append(f"unsafe_artifact_path:{spec_path}")
                        continue
                    spec_text = sp.read_text(encoding="utf-8") if sp.exists() else latest[spec_path]
                    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as sf:
                        sf.write(spec_text)
                    spec_arg = sf.name
            code, _fields = validator.run(mode, str(tmp), spec_arg, strict=True)
            if code != 0:
                errors.append(f"shallow_artifact:{norm}")
        finally:
            tmp.unlink(missing_ok=True)
            # The paired-spec temp (delete=False) was never cleaned up -> untrusted spec bodies
            # accumulated in the system temp dir across runs. Unlink it in the same finally.
            if spec_arg is not None:
                Path(spec_arg).unlink(missing_ok=True)
    return errors


# --- BR6 strict attribution (matches the strict column of tests/fixtures/transcripts/br6-attribution-cases.json).
# Statement splitting and version/help detection are Python here and JS in slice B; the shared table and the
# parity test keep them in step. The "real runner invocation" decision is NOT re-implemented: it is the
# exported isRealRunnerInvocation from hooks/flow-evidence.mjs, called through run_node_helpers.
FLOW_REQUIREMENTS = REPO / "hooks" / "flow-requirements.json"
VERSION_HELP_FLAGS = frozenset({"--version", "-V", "--help", "-h"})


def load_test_re() -> re.Pattern[str]:
    """The flow-guard `testCommand` regex (read-only reuse), compiled like the table's 'i' flag."""
    return re.compile(json.loads(FLOW_REQUIREMENTS.read_text(encoding="utf-8"))["testCommand"], re.IGNORECASE)


def _unquoted_mask(text: str) -> list[bool]:
    """True for each character outside quotes and not backslash-escaped. Single linear pass."""
    mask = [False] * len(text)
    quote = ""
    index = 0
    while index < len(text):
        ch = text[index]
        if quote:
            if ch == quote:
                quote = ""
            elif ch == "\\" and quote == '"':
                index += 1  # the escaped character inside double quotes stays data
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "\\":
            index += 1  # the escaped next character is literal
        else:
            mask[index] = True
        index += 1
    return mask


def br6_statements(command: str) -> list[str]:
    """Split on unquoted `;`, newline and `||` (never `&&`, `|` or `&`) after joining backslash-newlines."""
    text = command.replace("\\\n", "")
    mask = _unquoted_mask(text)
    pieces: list[str] = []
    start = index = 0
    while index < len(text):
        if mask[index] and text[index] in ";\n":
            pieces.append(text[start:index])
            start = index + 1
        elif mask[index] and text.startswith("||", index) and mask[index + 1]:
            pieces.append(text[start:index])
            start = index + 2
            index += 1
        index += 1
    pieces.append(text[start:])
    return [piece.strip() for piece in pieces if piece.strip() and not piece.strip().startswith("#")]


def has_unquoted_pipe(statement: str) -> bool:
    """An unquoted `|` or `|&`; `||` is not a pipe."""
    mask = _unquoted_mask(statement)
    index = 0
    while index < len(statement):
        if mask[index] and statement[index] == "|":
            if index + 1 < len(statement) and statement[index + 1] == "|" and mask[index + 1]:
                index += 2
                continue
            return True
        index += 1
    return False


def _split_unquoted_andand(text: str) -> list[str]:
    mask = _unquoted_mask(text)
    parts: list[str] = []
    start = index = 0
    while index < len(text) - 1:
        if mask[index] and mask[index + 1] and text[index:index + 2] == "&&":
            parts.append(text[start:index])
            start = index + 2
            index += 2
            continue
        index += 1
    parts.append(text[start:])
    return parts


def _args_before_pipe(text: str) -> list[str]:
    """Quote-aware arguments (quotes stripped) up to the first unquoted `|`."""
    args: list[str] = []
    current: str | None = None
    quote = ""
    for ch in text:
        if quote:
            if ch == quote:
                quote = ""
            else:
                current = (current or "") + ch
        elif ch in ("'", '"'):
            quote = ch
            current = current or ""
        elif ch == "|":
            break
        elif ch.isspace():
            if current is not None:
                args.append(current)
                current = None
        else:
            current = (current or "") + ch
    if current is not None:
        args.append(current)
    return args


def is_version_or_help_only(statement: str, test_re: re.Pattern[str]) -> bool:
    """True only when every `&&` segment holding a runner match passes --version/-V/--help/-h after it.

    Arguments after `--` count (`npm test -- --help`); a statement with no runner segment is False.
    """
    runner_segments = 0
    for segment in _split_unquoted_andand(statement):
        match = test_re.search(segment)
        if match is None:
            continue
        runner_segments += 1
        if not VERSION_HELP_FLAGS.intersection(_args_before_pipe(segment[match.end():])):
            return False
    return runner_segments > 0


@dataclass(frozen=True)
class AttributableRun:
    call_id: str
    command: str
    exit: int
    index: int  # timeline index of the call record


def attributable_test_runs(trace: Trace, test_re: re.Pattern[str]) -> list[AttributableRun]:
    """BR6 strictAttributable runs in timeline order.

    A run needs: a real-runner last statement that is not version/help-only and has no pipe; exactly one call
    event and exactly one output record for its call id; and a numeric exit (Claude: 1 if is_error else 0;
    Codex exec: the completed exit_code; rollout: the parsed exit).
    """
    first_result: dict[str, dict[str, Any]] = {}
    for record in trace.timeline:
        if record["kind"] == "tool_result" and record.get("id"):
            first_result.setdefault(record["id"], record)
    candidates: list[tuple[int, str, str, str, int]] = []
    for index, record in enumerate(trace.timeline):
        call_id = record.get("id")
        command = record.get("input", {}).get("command") if record["kind"] == "tool_call" else None
        if not call_id or not isinstance(command, str):
            continue
        statements = br6_statements(command)
        if not statements:
            continue
        last = statements[-1]
        # isRealRunnerInvocation can only accept a statement the runner regex matches somewhere, so a
        # non-matching statement is decided here without spawning node.
        if test_re.search(last) is None or is_version_or_help_only(last, test_re) or has_unquoted_pipe(last):
            continue
        counts = trace.call_event_counts.get(call_id, {})
        if max(counts.get("full", 0), counts.get("streamed", 0)) != 1 or counts.get("outputs", 0) != 1:
            continue
        exit_code = first_result.get(call_id, {}).get("exit")
        if type(exit_code) is not int:
            continue
        candidates.append((index, call_id, command, last, exit_code))
    if not candidates:
        return []
    classified = run_node_helpers(commands=[candidate[3] for candidate in candidates], test_command=test_re.pattern)
    if classified is None:
        if "strict_runner_classifier_unavailable" not in trace.strict_errors:
            trace.strict_errors.append("strict_runner_classifier_unavailable")
        return []  # fail closed: no run is attributable
    return [
        AttributableRun(call_id, command, exit_code, index)
        for (index, call_id, command, _last, exit_code), real in zip(candidates, classified["real"])
        if real
    ]


def red_green_errors(trace: Trace, runs: list[AttributableRun], test_re: re.Pattern[str]) -> list[str]:
    errors: list[str] = []
    green = next((run for run in runs if run.exit == 0), None)
    if green is None:
        errors.append("strict_missing_green")
    elif not any(run.exit != 0 and run.index < green.index for run in runs):
        errors.append("strict_missing_red_before_green")
    if errors:
        attributed = {run.index for run in runs}
        runner_calls = [
            index for index, record in enumerate(trace.timeline)
            if record["kind"] == "tool_call"
            and isinstance(record.get("input", {}).get("command"), str)
            and test_re.search(record["input"]["command"])
        ]
        if any(index not in attributed for index in runner_calls):
            errors.append("strict_test_run_unattributable")
    return errors


# --- Implementation-auditor verdicts (AC68). Two documented shapes: the agents/implementation-auditor.md fields
# (`overallStatus`, `finalDecision`) and the skills/implementation-control/SKILL.md report headings. Every
# pattern is linear (disjoint classes, no nested quantifier); a generic "Overall: PASS" matches neither shape.
AUDITOR_NAMES = ("implementation-auditor", "implementation-control")
_VERDICT_DECOR = r"[`*\"']*"
OVERALL_STATUS_FIELD_RE = re.compile(
    r"overallStatus" + _VERDICT_DECOR + r"[ \t]*[:=][ \t]*" + _VERDICT_DECOR + r"(PASS|PARTIAL|FAIL)\b"
)
FINAL_DECISION_FIELD_RE = re.compile(
    r"finalDecision" + _VERDICT_DECOR + r"[ \t]*[:=][ \t]*" + _VERDICT_DECOR + r"(allow-final|block-final)\b"
)
REPORT_STATUS_HEADING_RE = re.compile(r"^#{1,6}[ \t]*[*_]*Overall Status[*_]*[ \t]*$")
REPORT_DECISION_HEADING_RE = re.compile(r"^#{1,6}[ \t]*[*_]*Final Decision[*_]*[ \t]*$")
REPORT_STATUS_VALUE_RE = re.compile(r"^[`*_]*(PASS|PARTIAL|FAIL)\b")
DECISION_VALUE_RE = re.compile(r"\b(allow-final|block-final)\b")


def auditor_verdict_occurrences(text: str) -> list[tuple[int, str, str]]:
    """(offset, 'status' | 'decision', value) for every documented verdict shape in text, in text order."""
    found = [(m.start(), "status", m.group(1)) for m in OVERALL_STATUS_FIELD_RE.finditer(text)]
    found += [(m.start(), "decision", m.group(1)) for m in FINAL_DECISION_FIELD_RE.finditer(text)]
    lines = text.split("\n")
    offsets: list[int] = []
    position = 0
    for line in lines:
        offsets.append(position)
        position += len(line) + 1
    for index, line in enumerate(lines):
        stripped = line.strip()
        if REPORT_STATUS_HEADING_RE.match(stripped):
            following = next((j for j in range(index + 1, len(lines)) if lines[j].strip()), None)
            match = REPORT_STATUS_VALUE_RE.match(lines[following].strip()) if following is not None else None
            if match:
                found.append((offsets[following], "status", match.group(1)))
        elif REPORT_DECISION_HEADING_RE.match(stripped):
            for j in range(index + 1, len(lines)):
                if lines[j].lstrip().startswith("#"):
                    break  # the section ends at the next heading
                match = DECISION_VALUE_RE.search(lines[j])
                if match:
                    found.append((offsets[j] + match.start(), "decision", match.group(1)))
                    break
    return sorted(found)


def latest_auditor_verdict(trace: Trace) -> tuple[str | None, str | None]:
    """The last overall status and the last final decision, in timeline order.

    Carriers: tool_result text correlated to an Agent/Task/Skill call naming implementation-auditor or
    implementation-control, and assistant_text. Write content, tool inputs and user text never count, so a
    verdict quoted inside spec text is ignored.
    """
    auditor_calls = {
        record["id"] for record in trace.timeline
        if record["kind"] == "tool_call" and record.get("id") and record.get("name") in ("Agent", "Task", "Skill")
        and any(name in json.dumps(record.get("input", {}), ensure_ascii=False) for name in AUDITOR_NAMES)
    }
    status: str | None = None
    decision: str | None = None
    for record in trace.timeline:
        is_carrier = record["kind"] == "assistant_text" or (
            record["kind"] == "tool_result" and record.get("id") in auditor_calls
        )
        if not is_carrier:
            continue
        for _offset, kind, value in auditor_verdict_occurrences(record.get("text") or ""):
            if kind == "status":
                status = value
            else:
                decision = value
    return status, decision


# --- Strict reviewer results and step order (AC70). The case `strict` object is inert without --strict-evidence.
STRICT_ORDER_IDS = frozenset({
    "dispatch-strategy", "spec-written", "plan-written", "core-skill", "red-run", "green-run",
    "security", "control", "completion-claim-gate",
})
CODEX_RESULT_KINDS = frozenset({"findings-table", "control-verdict"})
FINDINGS_TABLE_HEADER = "Severity | Category | File:Line | Risk | Recommendation"  # skills/security-audit/SKILL.md
CORE_WORKFLOW_SKILLS = ("feature-build", "root-cause-fix", "safe-refactor", "test-authoring")


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def validate_strict_config(case_id: str, strict: Any) -> None:
    """Raise ValueError `case <id> invalid strict.<key>` for anything outside the documented strict schema."""
    if not isinstance(strict, dict):
        raise ValueError(f"case {case_id} invalid strict")
    for key, value in strict.items():
        if key in ("require_red_green", "check_artifact_depth"):
            valid = isinstance(value, bool)
        elif key == "reviewers":
            valid = isinstance(value, list) and all(
                isinstance(entry, dict)
                and set(entry) <= {"step", "skills", "agents", "codex_result"}
                and isinstance(entry.get("step"), str)
                and _string_list(entry.get("skills", []))
                and _string_list(entry.get("agents", []))
                and entry.get("codex_result") in CODEX_RESULT_KINDS
                for entry in value
            )
        elif key == "required_order":
            valid = _string_list(value) and all(item in STRICT_ORDER_IDS for item in value)
        else:
            valid = False
        if not valid:
            raise ValueError(f"case {case_id} invalid strict.{key}")


def _is_codex_trace(trace: Trace) -> bool:
    return trace.runtime.startswith("codex")


def _names_reviewer_member(record: dict[str, Any], reviewer: dict[str, Any]) -> bool:
    payload = json.dumps(record.get("input", {}), ensure_ascii=False)
    name = str(record.get("name", "")).lower()
    if name == "skill":
        return any(alias in payload for skill in reviewer.get("skills", []) for alias in expected_aliases(skill))
    if name in ("agent", "task"):
        return any(agent in payload for agent in reviewer.get("agents", []))
    return False


def _codex_reviewer_output_index(trace: Trace, kind: Any) -> int | None:
    """First assistant_text holding the documented reviewer output (Codex has no reviewer result event, AC39)."""
    for index, record in enumerate(trace.timeline):
        if record["kind"] != "assistant_text":
            continue
        text = record.get("text") or ""
        if kind == "findings-table" and FINDINGS_TABLE_HEADER in text:
            return index
        if kind == "control-verdict" and auditor_verdict_occurrences(text):
            return index
    return None


def reviewer_step(trace: Trace, reviewer: dict[str, Any]) -> tuple[int | None, str]:
    """(timeline index of the first clearing result, 'cleared' | 'missing' | 'errored')."""
    if _is_codex_trace(trace):
        index = _codex_reviewer_output_index(trace, reviewer.get("codex_result"))
        return (index, "cleared") if index is not None else (None, "missing")  # errored is not observable on Codex
    members = {
        record["id"] for record in trace.timeline
        if record["kind"] == "tool_call" and record.get("id") and _names_reviewer_member(record, reviewer)
    }
    results: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for index, record in enumerate(trace.timeline):
        if record["kind"] == "tool_result" and record.get("id") in members:
            results.setdefault(record["id"], []).append((index, record))
    clearing = [entries[0][0] for entries in results.values() if len(entries) == 1 and not entries[0][1].get("is_error")]
    if clearing:
        return min(clearing), "cleared"
    correlated = [record for entries in results.values() for _index, record in entries]
    if correlated and all(record.get("is_error") for record in correlated):
        return None, "errored"
    return None, "missing"


def reviewer_result_errors(trace: Trace, reviewers: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for reviewer in reviewers:
        _index, state = reviewer_step(trace, reviewer)
        if state != "cleared":
            errors.append(f"strict_reviewer_result_{state}:{reviewer['step']}")
    return errors


def _gate_member_index(trace: Trace, expected: str) -> int | None:
    """First tool_call satisfying required_skill_satisfied's members for one gate skill."""
    short = expected.rsplit(":", 1)[-1]
    agents = SKILL_AGENT_EQUIVALENTS.get(short, [])
    for index, record in enumerate(trace.timeline):
        if record["kind"] != "tool_call":
            continue
        payload = json.dumps(record.get("input", {}), ensure_ascii=False)
        name = str(record.get("name", "")).lower()
        if name == "skill" and any(alias in payload for alias in expected_aliases(expected)):
            return index
        if name in ("agent", "task") and (any(agent in payload for agent in agents) or short in DELEGATION_SATISFIES):
            return index
    return None


def _codex_gate_text_index(trace: Trace, marker: str) -> int | None:
    return next(
        (index for index, record in enumerate(trace.timeline)
         if record["kind"] == "assistant_text" and marker in (record.get("text") or "")),
        None,
    )


def _artifact_write_index(trace: Trace, role: str) -> int | None:
    """First write to a flat docs/agentic-sdlc/<role>s/ path or a per-package <role> path."""
    for index, record in enumerate(trace.timeline):
        if record["kind"] != "write":
            continue
        norm = str(record.get("path", "")).replace("\\", "/")
        layout = per_package_layout(norm)
        if f"docs/agentic-sdlc/{role}s/" in norm or (layout is not None and layout[0] == role):
            return index
    return None


def step_order_errors(trace: Trace, strict_config: dict[str, Any], runs: list[AttributableRun]) -> list[str]:
    order = strict_config.get("required_order", [])
    reviewers = {entry["step"]: entry for entry in strict_config.get("reviewers", [])}
    codex = _is_codex_trace(trace)
    green = next((run for run in runs if run.exit == 0), None)
    red = next((run for run in runs if run.exit != 0 and (green is None or run.index < green.index)), None)

    def position(step: str) -> int | None:
        candidates: list[int | None] = []
        if step in ("dispatch-strategy", "completion-claim-gate"):
            candidates.append(_gate_member_index(trace, f"agentic-sdlc:{step}"))
            if codex:
                candidates.append(_codex_gate_text_index(trace, f"Codex Adapter Gate: {step}"))
        elif step in ("spec-written", "plan-written"):
            candidates.append(_artifact_write_index(trace, step.split("-", 1)[0]))
        elif step == "core-skill":
            candidates.append(next(
                (index for index, record in enumerate(trace.timeline)
                 if record["kind"] == "tool_call" and str(record.get("name", "")).lower() == "skill"
                 and any(core in json.dumps(record.get("input", {}), ensure_ascii=False) for core in CORE_WORKFLOW_SKILLS)),
                None,
            ))
            if codex:
                candidates += [_codex_gate_text_index(trace, f"Codex Adapter Gate: {core} activated")
                               for core in CORE_WORKFLOW_SKILLS]
        elif step == "red-run":
            candidates.append(red.index if red else None)
        elif step == "green-run":
            candidates.append(green.index if green else None)
        elif step in reviewers:
            candidates.append(reviewer_step(trace, reviewers[step])[0])
        found = [index for index in candidates if index is not None]
        return min(found) if found else None

    positions = {step: position(step) for step in order}
    errors = [f"strict_step_missing:{step}" for step in order if positions[step] is None]
    for offset, earlier in enumerate(order):
        for later in order[offset + 1:]:
            if positions[earlier] is not None and positions[later] is not None and positions[earlier] > positions[later]:
                errors.append(f"strict_order_violation:{earlier}->{later}")
    return errors


def evaluate_case(
    case: dict[str, Any], trace: Trace, cwd: Path, *, strict: bool = False, contained_root: Path | None = None
) -> list[str]:
    errors = []
    haystack = trace.haystack()
    if case.get("fail_on_runtime_errors", True):
        errors += [f"runtime_error:{error}" for error in trace.runtime_errors]
    if case.get("fail_on_permission_denials", True):
        errors += [f"permission_denied:{denial}" for denial in trace.permission_denials]
    for skill in case.get("required_skills", []):
        if not required_skill_satisfied(trace, skill) and not runtime_adapter_satisfies(trace, case, "skill", skill):
            errors.append(f"missing_skill:{skill}")
    for workflow in case.get("required_workflows", []):
        if not tool_invoked(trace, "Workflow", workflow) and not runtime_adapter_satisfies(trace, case, "workflow", workflow):
            errors.append(f"missing_workflow:{workflow}")
    for command in case.get("required_commands", []):
        if not any(regex_present(command, c) for c in trace.commands):
            errors.append(f"missing_command:{command}")
    for artifact in case.get("required_artifacts", []):
        # With contained_root None this is the 5801cb9 path unchanged.
        if contained_root is not None and artifact_escapes(artifact, cwd, contained_root):
            errors.append(f"artifact_escape:{artifact}")
        elif not artifact_present(artifact, trace, cwd):
            errors.append(f"missing_artifact:{artifact}")
    for command in case.get("forbidden_commands", []):
        if any(regex_present(command, c) for c in trace.commands):
            errors.append(f"forbidden_command:{command}")
    for pattern in case.get("required_patterns", []):
        if not regex_present(pattern, haystack):
            errors.append(f"missing_pattern:{pattern}")
    for pattern in case.get("forbidden_patterns", []):
        if regex_present(pattern, haystack):
            errors.append(f"forbidden_pattern:{pattern}")
    if case.get("check_artifact_depth", False):
        errors += evaluate_artifact_depth(trace, cwd)
    if strict:
        strict_config = case.get("strict") if isinstance(case.get("strict"), dict) else {}
        runs: list[AttributableRun] = []
        if strict_config.get("require_red_green") or strict_config.get("required_order"):
            test_re = load_test_re()
            runs = attributable_test_runs(trace, test_re)
            if strict_config.get("require_red_green"):
                errors += red_green_errors(trace, runs, test_re)
        errors += reviewer_result_errors(trace, strict_config.get("reviewers", []))
        if strict_config.get("required_order"):
            errors += step_order_errors(trace, strict_config, runs)
        # strict.check_artifact_depth runs the depth check whatever the case-level flag says (never twice).
        if strict_config.get("check_artifact_depth") and not case.get("check_artifact_depth", False):
            errors += evaluate_artifact_depth(trace, cwd)
        status, decision = latest_auditor_verdict(trace)
        if status in ("PARTIAL", "FAIL"):
            errors.append(f"strict_critical_audit:overallStatus={status}")
        if decision == "block-final":
            errors.append("strict_critical_audit:finalDecision=block-final")
        errors += list(trace.strict_errors)
    return errors


class FixtureGitError(RuntimeError):
    """A fixture Git preparation step failed; the message names the step (AC72)."""


def copy_fixture(case: dict[str, Any], tmp_root: Path, *, allow_commit: bool = False) -> Path:
    """Copy a case fixture into tmp_root and initialize it as its own Git repository.

    The baseline commit is made only with explicit consent (allow_commit, from --allow-fixture-commit);
    the default is the consent-safe value, so an in-process caller that omits it gets no commit.
    """
    fixture = case.get("fixture_dir")
    if not fixture:
        raise ValueError(f"live case {case['id']} requires fixture_dir")
    src = resolve_under(REPO, fixture, "fixture_dir", must_exist=True)
    if not src.is_dir():
        raise ValueError(f"fixture_dir must be a directory: {fixture}")
    require_link_free_tree(src, "fixture_dir")
    dst = resolve_under(tmp_root, require_slug(case["id"], "case id"), "fixture destination")
    shutil.copytree(src, dst)
    steps = [
        ("init", ["git", "init", "-b", "main"]),
        ("config-user-email", ["git", "config", "user.email", "eval@example.invalid"]),
        ("config-user-name", ["git", "config", "user.name", "Agentic SDLC Eval"]),
    ]
    if allow_commit:
        steps += [("add", ["git", "add", "."]), ("commit", ["git", "commit", "-m", "fixture baseline"])]
    for step, argv in steps:
        proc = subprocess.run(argv, cwd=dst, capture_output=True, text=True, encoding="utf-8")
        if proc.returncode != 0:
            # Git stderr is never echoed: it can carry local paths or configuration values.
            raise FixtureGitError(f"fixture_git_failed:{step}")
    return dst


def run_live_case(case: dict[str, Any], args: argparse.Namespace, tmp_root: Path) -> tuple[Trace, Path, Path]:
    if shutil.which("claude") is None:
        raise RuntimeError("claude CLI missing")
    cwd = copy_fixture(case, tmp_root, allow_commit=args.allow_fixture_commit)
    transcript_dir = args.transcript_dir.resolve() if args.transcript_dir else (tmp_root / "transcripts")
    transcript_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = resolve_under(transcript_dir, f"{case['id']}.jsonl", "transcript filename")
    cmd = [
        "claude",
        "-p",
        case["prompt"],
        "--plugin-dir",
        str(REPO),
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--include-hook-events",
        "--no-session-persistence",
        "--max-budget-usd",
        str(args.max_budget_usd),
    ]
    if args.model:
        cmd += ["--model", args.model]
    if args.permission_mode:
        cmd += ["--permission-mode", args.permission_mode]
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=args.timeout,
    )
    raw_transcript = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    transcript_path.write_text(redact_text(raw_transcript), encoding="utf-8")
    return trace_events(load_json_lines(transcript_path), strict=args.strict_evidence), cwd, transcript_path


# --- Evidence packets (AC65, AC66, AC67, AC124, AC128).
BUILD_RELEASE_SCRIPT = REPO / "scripts" / "build_release.py"
NO_GIT_CHECKOUT = "unavailable:no-git-checkout"
HEX_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
RUNTIME_PAYLOAD_IDENTITY_DEFINITION = (
    "BR20 runtime payload identity: scripts/build_release.py payload_identity(release_members(repo, git_commit), "
    "RUNTIME_PAYLOAD_EXCLUDE) over the BR13-filtered committed tree at git_commit"
)
PACKET_HELPER_PATHS = (
    "scripts/run_procedure_eval.py",
    "scripts/validate_artifacts.py",
    "scripts/eval_safety.py",
    "scripts/sensitive_redaction.py",
    "scripts/build_release.py",
    "hooks/redact-sensitive.mjs",
    "hooks/secret-patterns.mjs",
    "hooks/codex-rollout.mjs",
    "hooks/flow-evidence.mjs",
    "hooks/flow-requirements.json",
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def repository_commit() -> str:
    """The repository HEAD commit via a fixed argv (no shell, fsmonitor disabled), else a named marker."""
    try:
        proc = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "rev-parse", "--verify", "HEAD^{commit}"],
            cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except OSError:
        return NO_GIT_CHECKOUT
    commit = proc.stdout.strip()
    return commit if proc.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit) else NO_GIT_CHECKOUT


def _import_build_release() -> Any:
    try:
        from scripts import build_release
    except ModuleNotFoundError:
        import build_release
    return build_release


def _payload_identity(commit: str) -> str:
    if commit.startswith("unavailable:"):
        return NO_GIT_CHECKOUT
    if not BUILD_RELEASE_SCRIPT.exists():
        return "unavailable:build-release-absent"
    try:
        module = _import_build_release()
    except Exception:  # another slice's module failing to import is a named, visible fallback
        return "unavailable:build-release-failed"
    release_members = getattr(module, "release_members", None)
    payload_identity = getattr(module, "payload_identity", None)
    if not callable(release_members) or not callable(payload_identity) or not hasattr(module, "RUNTIME_PAYLOAD_EXCLUDE"):
        return "unavailable:build-release-api-missing"
    try:
        value = payload_identity(release_members(REPO, commit), module.RUNTIME_PAYLOAD_EXCLUDE)
    except Exception:  # e.g. a BR13 member violation raised by build_release: named fallback, never a crash
        return "unavailable:build-release-failed"
    return value if isinstance(value, str) and HEX_DIGEST_RE.match(value) else "unavailable:build-release-failed"


def runtime_payload_identity_for_commit(commit: str, cache: dict[str, str] | None = None) -> str:
    """BR20 identity of the committed tree at `commit` (D11).

    Not re-implemented: it calls scripts/build_release.py's release_members and payload_identity. No release
    ZIP is built, no file is written and no worktree bytes are read. Cached per eval run.
    """
    if cache is not None and commit in cache:
        return cache[commit]
    identity = _payload_identity(commit)
    if cache is not None:
        cache[commit] = identity
    return identity


def fixture_hash(root: Path | None) -> str:
    """SHA-256 over sorted (posix relpath, file SHA-256) of regular files; `.git` excluded, links never followed."""
    if root is None or not Path(root).is_dir():
        return "absent"
    root = Path(root)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    entries: list[tuple[str, str]] = []
    stack = [root]
    while stack:
        current = stack.pop()
        with os.scandir(current) as scanned:
            for entry in scanned:
                if entry.name == ".git":
                    continue
                info = entry.stat(follow_symlinks=False)
                if entry.is_symlink() or getattr(info, "st_file_attributes", 0) & reparse_flag:
                    return "unavailable:link-present"
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    relative = Path(entry.path).relative_to(root).as_posix()
                    entries.append((relative, _sha256_bytes(Path(entry.path).read_bytes())))
    digest = hashlib.sha256()
    for relative, file_digest in sorted(entries):
        digest.update(f"{relative}\0{file_digest}\n".encode("utf-8"))
    return digest.hexdigest()


def _latest_artifact_sha256(trace: Trace, cwd: Path, role: str) -> str:
    """SHA-256 of the latest spec/plan written (on-disk bytes win, as in evaluate_artifact_depth), else 'absent'."""
    latest: tuple[str, str] | None = None
    for path, content in trace.artifact_writes:
        norm = path.replace("\\", "/")
        layout = per_package_layout(norm)
        if f"docs/agentic-sdlc/{role}s/" in norm or (layout is not None and layout[0] == role):
            latest = (norm, content)
    if latest is None:
        return "absent"
    norm, content = latest
    try:
        disk: Path | None = resolve_under(cwd, norm, "artifact write path")
    except ValueError:
        disk = None
    return _sha256_bytes(disk.read_bytes() if disk is not None and disk.is_file() else content.encode("utf-8"))


def helper_paths(evidence_root: Path) -> list[dict[str, str]]:
    """Helper files relative to the evidence root, or `repo:<path>` when on another Windows volume."""
    helpers: list[dict[str, str]] = []
    for relative in PACKET_HELPER_PATHS:
        source = REPO / relative
        if not source.is_file():
            continue  # scripts/build_release.py is listed only when present
        try:
            path = os.path.relpath(source, evidence_root).replace(os.sep, "/")
        except ValueError:
            path = f"repo:{relative}"
        helpers.append({"path": path, "sha256": _sha256_bytes(source.read_bytes())})
    return helpers


def build_evidence_packet(case: dict[str, Any], trace: Trace, errors: list[str], *, cwd: Path,
                          fixture_root: Path | None, scoring_source: str, strict: bool, identity: str) -> dict[str, Any]:
    """The packet body; helper_paths are resolved by write_evidence_packet against the evidence root."""
    git_commit = repository_commit()
    root = fixture_root
    if root is None and case.get("fixture_dir"):
        root = resolve_under(REPO, case["fixture_dir"], f"case {case['id']} fixture_dir")
    runtime = "claude" if trace.runtime == "claude" else ("codex" if _is_codex_trace(trace) else "unknown")
    return {
        "schema_version": 1,
        "case_id": case["id"],
        "runtime": runtime,
        "cli_version": trace.meta.get("cli_version", "unrecorded"),
        "model": trace.meta.get("model", "unrecorded"),
        "effort": trace.meta.get("effort", "unrecorded"),
        "git_commit": git_commit,
        "runtime_payload_identity": {
            "definition": RUNTIME_PAYLOAD_IDENTITY_DEFINITION, "commit": git_commit, "sha256": identity,
        },
        "fixture_hash": fixture_hash(root),
        "spec_sha256": _latest_artifact_sha256(trace, cwd, "spec"),
        "plan_sha256": _latest_artifact_sha256(trace, cwd, "plan"),
        "terminal_status": "failed" if errors else "passed",
        "errors": list(errors),
        "scoring_source": scoring_source,
        # AC128: only a strict transcript replay is scorable; --live harness evidence never is.
        "procedure_row_scorable": scoring_source == "transcript-replay" and strict,
        "transcript_path": f"{case['id']}.transcript.jsonl",
        "helper_paths": [],
    }


def _write_text_atomically(target: Path, text: str) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temp_name, target)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def write_evidence_packet(packet: dict[str, Any], evidence_dir: Path, case_id: str, transcript_text: str, *,
                          fixture_roots: list[Path]) -> None:
    """Validate, redact in memory, then write `<case-id>.transcript.jsonl` and `<case-id>.json` (AC66, AC67).

    Every check runs before any filesystem write; each failure raises ValueError or RuntimeError named for it.
    """
    try:
        valid = require_slug(case_id, "evidence case id") == case_id
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("evidence_case_id_invalid")
    if case_id in RESERVED_SLUGS:
        raise ValueError("evidence_case_id_reserved")
    evidence_root = Path(evidence_dir).resolve(strict=False)
    if any(path_within(evidence_root, Path(root).resolve()) for root in fixture_roots):
        raise ValueError("evidence_dir_inside_fixture")
    if (evidence_root / f"{case_id}.json").exists():
        raise ValueError("evidence_packet_exists")
    try:
        clean_packet = redact_json(dict(packet, helper_paths=helper_paths(evidence_root)))
        clean_transcript = redact_text(transcript_text)
    except (RuntimeError, OSError, ValueError) as exc:  # redaction fails closed: nothing is written
        raise RuntimeError("evidence_redaction_failed") from exc
    try:
        evidence_root.mkdir(parents=True, exist_ok=True)
        transcript_target = resolve_under(evidence_root, f"{case_id}.transcript.jsonl", "evidence transcript")
        packet_target = resolve_under(evidence_root, f"{case_id}.json", "evidence packet")
        _write_text_atomically(transcript_target, clean_transcript)
        _write_text_atomically(packet_target, json.dumps(clean_packet, indent=2, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise RuntimeError("evidence_write_failed") from exc


def write_case_evidence(case: dict[str, Any], trace: Trace, errors: list[str], args: argparse.Namespace, *,
                        cwd: Path, fixture_root: Path | None, transcript_path: Path,
                        identity_cache: dict[str, str]) -> str | None:
    """Build and write one case's packet; return `<name>:<case-id>` on a named failure, else None."""
    live_copy = cwd if args.live else None
    roots = [root for root in (fixture_root, live_copy) if root is not None]
    if case.get("fixture_dir"):
        roots.append(resolve_under(REPO, case["fixture_dir"], f"case {case['id']} fixture_dir"))
    packet = build_evidence_packet(
        case, trace, errors, cwd=cwd,
        fixture_root=fixture_root if fixture_root is not None else live_copy,
        scoring_source="live-harness" if args.live else "transcript-replay",
        strict=args.strict_evidence,
        identity=runtime_payload_identity_for_commit(repository_commit(), identity_cache),
    )
    try:
        transcript_text = read_transcript_text(transcript_path)
    except OSError:
        return f"evidence_transcript_unreadable:{case['id']}"
    try:
        write_evidence_packet(packet, args.evidence_dir, case["id"], transcript_text, fixture_roots=roots)
    except (ValueError, RuntimeError) as exc:
        return f"{exc}:{case['id']}"
    return None


def path_within(path: Path, root: Path) -> bool:
    """True when resolved `path` equals or lies under resolved `root`.

    Compared on os.path.normcase strings, so a mixed-case spelling on Windows cannot escape the check.
    """
    try:
        Path(os.path.normcase(str(path))).relative_to(os.path.normcase(str(root)))
    except ValueError:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-set", required=True, type=Path)
    parser.add_argument("--case-id", action="append", dest="case_ids",
                        help="Restrict to these case ids (repeatable).")
    parser.add_argument("--transcript", type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--transcript-dir", type=Path)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--model")
    parser.add_argument("--permission-mode", default="auto")
    parser.add_argument(
        "--max-budget-usd",
        default="5.00",
        help="Per-run model-spend ceiling. Default 5.00: a full Full-mode pipeline on a strong "
        "model (sonnet/opus) routinely exceeds 2.00 and would otherwise be cut off mid-run, "
        "masking late gates (completion-claim-gate) as failures. Haiku typically finishes well "
        "under 2.00, so the higher ceiling does not change its cost.",
    )
    parser.add_argument(
        "--allow-fixture-commit",
        action="store_true",
        help="Consent for --live: the harness commits a baseline inside each isolated fixture copy.",
    )
    parser.add_argument("--strict-evidence", action="store_true",
                        help="Grade with strict evidence rules (ordered, attributable, reviewer results).")
    parser.add_argument("--evidence-dir", type=Path,
                        help="Write one masked evidence packet per case here (requires --strict-evidence).")
    parser.add_argument("--fixture-root", type=Path,
                        help="Replay only: resolve artifact checks under this fixture directory.")
    args = parser.parse_args(argv)

    # AC73: refuse --live without consent before any temp directory, Git call or model process.
    if args.live and not args.allow_fixture_commit:
        print("error=live_requires_allow_fixture_commit")
        print(
            "The live harness commits a baseline inside each isolated fixture copy; "
            "pass --allow-fixture-commit to consent."
        )
        print("procedure_eval=failed")
        return 2

    try:
        cases = load_eval(args.eval_set)
    except (OSError, ValueError, json.JSONDecodeError, re.error) as exc:
        print(f"error={type(exc).__name__}:{exc}")
        print("procedure_eval=failed")
        return 1

    if args.case_ids:
        wanted = set(args.case_ids)
        known = {case["id"] for case in cases}
        missing = sorted(wanted - known)
        if missing:
            print(f"error=unknown_case_id:{','.join(missing)}")
            print("procedure_eval=failed")
            return 1
        cases = [case for case in cases if case["id"] in wanted]

    # Static strict-flag checks (AC74, AC124, AC66): they create nothing and run before any case.
    fixture_root: Path | None = None
    if args.fixture_root is not None:
        fixture_root = args.fixture_root.resolve()
        if not fixture_root.is_dir():
            print("error=fixture_root_invalid")
            print("procedure_eval=failed")
            return 1
    if args.evidence_dir is not None and not args.strict_evidence:
        print("error=evidence_dir_requires_strict_evidence")
        print("procedure_eval=failed")
        return 2
    if fixture_root is not None and args.live:
        print("error=fixture_root_is_replay_only")
        print("procedure_eval=failed")
        return 2
    if args.evidence_dir is not None:
        evidence_root = args.evidence_dir.resolve(strict=False)
        protected = [fixture_root] if fixture_root is not None else []
        protected += [
            resolve_under(REPO, case["fixture_dir"], f"case {case['id']} fixture_dir")
            for case in cases
            if case.get("fixture_dir")
        ]
        if any(path_within(evidence_root, root) for root in protected):
            print("error=evidence_dir_inside_fixture")
            print("procedure_eval=failed")
            return 1

    if args.dry_run:
        print(f"cases={len(cases)}")
        print("procedure_eval=dry-run-passed")
        return 0

    all_errors: list[str] = []
    packet_errors: list[str] = []
    outputs: list[str] = []
    identity_cache: dict[str, str] = {}  # the BR20 identity is computed once per run for the recorded commit
    with tempfile.TemporaryDirectory(prefix="agentic-sdlc-procedure-", ignore_cleanup_errors=True) as td:
        tmp_root = Path(td)
        for case in cases:
            if args.transcript:
                trace = trace_events(load_json_lines(args.transcript), strict=args.strict_evidence)
                cwd = fixture_root if fixture_root is not None else REPO
                transcript_path = args.transcript
            elif args.live:
                try:
                    trace, cwd, transcript_path = run_live_case(case, args, tmp_root)
                except RuntimeError as exc:
                    print(f"error={exc}")
                    print("procedure_eval=failed")
                    return 1
            else:
                print("error=use --dry-run, --transcript, or --live")
                print("procedure_eval=failed")
                return 2
            # fixture_root is replay-only (the static checks reject it with --live).
            errors = evaluate_case(case, trace, cwd, strict=args.strict_evidence, contained_root=fixture_root)
            if args.strict_evidence and args.evidence_dir is not None:
                packet_error = write_case_evidence(case, trace, errors, args, cwd=cwd, fixture_root=fixture_root,
                                                   transcript_path=transcript_path, identity_cache=identity_cache)
                if packet_error:
                    packet_errors.append(packet_error)  # named, fails the run, next case continues
            outputs.append(f"case_{case['id']}={'failed' if errors else 'passed'}")
            outputs.append(f"case_{case['id']}_tools={len(trace.tools)}")
            outputs.append(f"case_{case['id']}_transcript={transcript_path}")
            all_errors += [f"{case['id']}:{e}" for e in errors]

    failures = [f"error={e}" for e in all_errors] + [f"error={e}" for e in packet_errors]
    for line in sorted(outputs + failures):
        print(line)
    failed = bool(all_errors or packet_errors)
    print("procedure_eval=failed" if failed else "procedure_eval=passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
