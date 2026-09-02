"""Run or analyze transcript-based Claude procedure evals.

This checks more than "did the skill trigger?". It inspects stream-json tool use
and optional filesystem artifacts to verify that a workflow used required skills,
commands, workflows, and did not run forbidden commands.

Dry/schema mode:
  python scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --dry-run

Analyze an existing transcript:
  python scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --transcript transcript.jsonl

Live mode:
  python scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --live
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from scripts.eval_safety import require_link_free_tree, require_relative_pattern, require_slug, resolve_under
    from scripts.sensitive_redaction import redact_text
except ModuleNotFoundError:
    from eval_safety import require_link_free_tree, require_relative_pattern, require_slug, resolve_under
    from sensitive_redaction import redact_text


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


def load_json_lines(path: Path) -> list[dict[str, Any]]:
    events = []
    raw_bytes = path.read_bytes()
    if raw_bytes.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw_bytes.decode("utf-16", errors="replace")
    elif raw_bytes.startswith(b"\xef\xbb\xbf"):
        text = raw_bytes.decode("utf-8-sig", errors="replace")
    else:
        text = raw_bytes.decode("utf-8", errors="replace")
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


def trace_events(events: list[dict[str, Any]]) -> Trace:
    trace = Trace()
    partial: dict[int, dict[str, Any]] = {}
    for event in events:
        etype = event.get("type")
        if etype == "assistant":
            for item in event.get("message", {}).get("content", []):
                if item.get("type") == "text":
                    trace.text += "\n" + item.get("text", "")
                elif item.get("type") == "tool_use":
                    _record_tool(trace, item.get("name", ""), item.get("input", {}))
        elif etype == "stream_event":
            se = event.get("event", {})
            stype = se.get("type")
            index = int(se.get("index", 0))
            if stype == "content_block_start":
                block = se.get("content_block", {})
                if block.get("type") == "tool_use":
                    partial[index] = {"name": block.get("name", ""), "json": ""}
                elif block.get("type") == "text":
                    partial[index] = {"name": "__text__", "json": ""}
            elif stype == "content_block_delta":
                delta = se.get("delta", {})
                if delta.get("type") == "text_delta":
                    trace.text += delta.get("text", "")
                elif delta.get("type") == "input_json_delta" and index in partial:
                    partial[index]["json"] += delta.get("partial_json", "")
            elif stype == "content_block_stop" and index in partial:
                pending = partial.pop(index)
                if pending["name"] and pending["name"] != "__text__":
                    try:
                        input_obj = json.loads(pending["json"] or "{}")
                    except json.JSONDecodeError:
                        input_obj = {"_raw": pending["json"]}
                    _record_tool(trace, pending["name"], input_obj)
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
            item = event.get("item")
            if isinstance(item, dict):
                _record_codex_item(trace, item)
        elif etype in {"turn.failed", "error"}:
            message = event.get("message") or event.get("error")
            trace.runtime_errors.append(str(message or etype))
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
    return cases


def regex_present(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text, re.IGNORECASE | re.MULTILINE))


def artifact_present(pattern: str, trace: Trace, cwd: Path) -> bool:
    if any(pattern.replace("\\", "/") in w.replace("\\", "/") for w in trace.writes):
        return True
    require_relative_pattern(pattern, "required artifact")
    candidates = list(cwd.glob(pattern)) if any(ch in pattern for ch in "*?[]") else [resolve_under(cwd, pattern, "required artifact")]
    return any(p.exists() for p in candidates)


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


def evaluate_case(case: dict[str, Any], trace: Trace, cwd: Path) -> list[str]:
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
        if not artifact_present(artifact, trace, cwd):
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
    return errors


def copy_fixture(case: dict[str, Any], tmp_root: Path) -> Path:
    fixture = case.get("fixture_dir")
    if not fixture:
        raise ValueError(f"live case {case['id']} requires fixture_dir")
    src = resolve_under(REPO, fixture, "fixture_dir", must_exist=True)
    if not src.is_dir():
        raise ValueError(f"fixture_dir must be a directory: {fixture}")
    require_link_free_tree(src, "fixture_dir")
    dst = resolve_under(tmp_root, require_slug(case["id"], "case id"), "fixture destination")
    shutil.copytree(src, dst)
    subprocess.run(["git", "init", "-b", "main"], cwd=dst, capture_output=True, text=True, encoding="utf-8")
    subprocess.run(["git", "config", "user.email", "eval@example.invalid"], cwd=dst, capture_output=True, text=True, encoding="utf-8")
    subprocess.run(["git", "config", "user.name", "Agentic SDLC Eval"], cwd=dst, capture_output=True, text=True, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=dst, capture_output=True, text=True, encoding="utf-8")
    subprocess.run(["git", "commit", "-m", "fixture baseline"], cwd=dst, capture_output=True, text=True, encoding="utf-8")
    return dst


def run_live_case(case: dict[str, Any], args: argparse.Namespace, tmp_root: Path) -> tuple[Trace, Path, Path]:
    if shutil.which("claude") is None:
        raise RuntimeError("claude CLI missing")
    cwd = copy_fixture(case, tmp_root)
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
    return trace_events(load_json_lines(transcript_path)), cwd, transcript_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-set", required=True, type=Path)
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
    args = parser.parse_args(argv)

    try:
        cases = load_eval(args.eval_set)
    except (OSError, ValueError, json.JSONDecodeError, re.error) as exc:
        print(f"error={type(exc).__name__}:{exc}")
        print("procedure_eval=failed")
        return 1

    if args.dry_run:
        print(f"cases={len(cases)}")
        print("procedure_eval=dry-run-passed")
        return 0

    all_errors: list[str] = []
    outputs: list[str] = []
    with tempfile.TemporaryDirectory(prefix="agentic-sdlc-procedure-", ignore_cleanup_errors=True) as td:
        tmp_root = Path(td)
        for case in cases:
            if args.transcript:
                trace = trace_events(load_json_lines(args.transcript))
                cwd = REPO
                transcript_path = args.transcript
            elif args.live:
                trace, cwd, transcript_path = run_live_case(case, args, tmp_root)
            else:
                print("error=use --dry-run, --transcript, or --live")
                print("procedure_eval=failed")
                return 2
            errors = evaluate_case(case, trace, cwd)
            outputs.append(f"case_{case['id']}={'failed' if errors else 'passed'}")
            outputs.append(f"case_{case['id']}_tools={len(trace.tools)}")
            outputs.append(f"case_{case['id']}_transcript={transcript_path}")
            all_errors += [f"{case['id']}:{e}" for e in errors]

    for line in sorted(outputs + [f"error={e}" for e in all_errors]):
        print(line)
    print("procedure_eval=failed" if all_errors else "procedure_eval=passed")
    return 1 if all_errors else 0


if __name__ == "__main__":
    sys.exit(main())
