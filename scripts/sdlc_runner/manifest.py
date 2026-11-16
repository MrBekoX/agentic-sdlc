"""Flow manifests, shared policy and the spec/plan loop definition: load and validate.

Contract §6 (manifest schema), §7 (check names and parameters), §9 (runtime rows), §10 (loop) and
§12 (run allowlist). The JSON shapes live in flows/schemas/*.schema.json, read from this runner's
own plugin root (never from the root a manifest is loaded from: the schema is the runner's
contract). This module adds the rules a schema cannot state: step order, gates, check
parameters, reference syntax, input producers, mechanism keys, loop modes and file writers, the
glob dialect, allowlist reachability and the escalate lattice. File checks compare names exactly.

Validators return "<json-pointer>: <reason>" strings (the schema module's format; an empty list
means valid). Loaders raise SdlcError(2, ...) for a missing, unreadable or invalid file, so a
broken manifest never runs. Every reader refuses duplicate JSON keys and NaN/Infinity, which
json.loads would otherwise accept silently.
"""
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

from . import fingerprint, schema
from .paths import plugin_root, valid_work_id
from .textio import SdlcError, read_text

FLOW_SCHEMA_ID = "agentic-sdlc/flow@1"
SHARED_SCHEMA_ID = "agentic-sdlc/shared@1"
LOOP_SCHEMA_ID = "agentic-sdlc/loop-def@1"
SCHEMA_NAMES = ("flow", "shared", "loop", "critic", "draft-result", "sidecar", "strategy", "check")

# Contract §7: check name -> (required parameters, optional parameters).
CHECK_PARAMS = {
    "exists": (("path",), ()),
    "validator": (("mode",), ("strict", "sources")),
    "sidecar_ok": (("artifact",), ()),
    "report": (("path", "header"), ("verdict", "fresh")),
    "run_recorded": (("expect",), ("label",)),
    "approval": (("gate",), ()),
    "branch_ok": ((), ()),
    "resolver_ok": ((), ()),
    "strategy_ok": ((), ()),
    "unchanged": (("set",), ()),
    "loop_done": ((), ()),
    "settled": ((), ()),
}
CHECK_TYPES = frozenset(CHECK_PARAMS)
# Parameters every check may carry: work_types limits it to those work types (it passes for others).
GENERIC_CHECK_PARAMS = ("work_types",)
# Package files `start` writes before the first step, so a step may require them as inputs.
START_FILES = ("request.md",)
# Loop files the runner or an engine writes itself (every other files key is a role's or draft-check's).
LOOP_RUNNER_FILES = ("brief", "prompt", "loop", "result", "engine")

NAMED_SETS = ("@source", "@tests", "@diff", "@start")
PLACEHOLDERS = ("work_id",)
FORMS = ("gated", "light")
WORK_TYPES = ("feature", "bugfix", "refactor", "test")
OPTIONS = ("intent", "quality-review", "loop", "spec")
ASK_KINDS = ("consent", "design")
# start_probes() values (probes.py); "error" always means "the step applies" and is never listed.
PROBE_VALUES = {
    "explore_mode": ("parallel", "single", "greenfield_inline"),
    "deps": ("external", "stdlib_only"),
    "toolchain": ("present", "absent"),
}
# Contract §9.
MECHANISM_KEYS = ("context", "draft", "draft.critic", "spec-check", "implement", "security", "quality-gates",
                  "quality-review", "audit", "docs-check")
MANDATED_FRESH_KEYS = ("draft.critic", "spec-check", "security", "audit", "quality-review")
MECHANISMS = ("main", "subagent", "workflow", "team", "runner-loop", "runner-loop-inline",
              "inline-degraded", "parallel-runs")
RUNTIMES = ("claude", "codex", "kimi", "grok", "zcode", "cursor", "antigravity", "other")
LOOP_MODES = ("spec+plan", "spec", "plan", "bugfix-plan")
STRATEGY_STEP = "strategy"
IMPLEMENT_STEP = "implement"
# The steps that write, read or approve the spec and the plan (hybrid spec/plan design §5). A gate
# whose artifacts change while only these ran after it waits again; once a later step outside them
# started, it halts with `reapproval needed` (engine._reopened_after_start).
DRAFTING_STEPS = ("intent", "spec", "spec-check", "spec-review", "plan", "plan-review", "draft", "review")
# The flows whose plan may carry its own criteria (`spec: none`); the runner stamps `spec: none` on a
# plan of one of them whose package has no spec. Mirrors SPECLESS_FLOWS of scripts/validate_artifacts.py
# and scripts/resolve_work_package.py; tests/test_sdlc_engine.py pins the agreement.
SPECLESS_FLOWS = ("bugfix", "feature", "plan")

_ID_RE = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
_STEP_FILE_RE = re.compile(r"skills/[a-z0-9][a-z0-9-]*/steps/[a-z0-9][a-z0-9.-]*\.md\Z")
_ROLE_FILE_RE = re.compile(r"agents/[a-z0-9][a-z0-9-]*\.md\Z")
_SCHEMA_FILE_RE = re.compile(r"flows/schemas/[a-z0-9][a-z0-9-]*\.schema\.json\Z")
_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")
_REF_CHARS_RE = re.compile(r"[A-Za-z0-9_.{}/-]+\Z")
_GLOB_CHARS_RE = re.compile(r"[A-Za-z0-9_.*?{},/-]+\Z")
_BODY = "#body"
_SCHEMAS = {}


# --- reading -----------------------------------------------------------------------------------

def _show(value) -> str:
    """A value fit for a one-line error: control characters replaced, at most 80 characters."""
    text = value if isinstance(value, str) else repr(value)
    return "".join(c if c.isprintable() else "?" for c in text)[:80]


def _no_duplicates(pairs):
    found = {}
    for key, value in pairs:
        if key in found:
            raise ValueError("duplicate key %r" % key)
        found[key] = value
    return found


def _no_constant(name):
    raise ValueError("%s is not JSON" % name)


def _read_json(path: Path, rel: str, missing: str):
    """Parsed JSON at `path`; SdlcError(2, missing) when absent, manifest_invalid:<rel> otherwise."""
    try:
        text = read_text(path)
    except (FileNotFoundError, NotADirectoryError):
        raise SdlcError(2, missing) from None
    except SdlcError:
        raise SdlcError(2, "manifest_invalid:%s: not UTF-8" % rel) from None
    except OSError as exc:
        raise SdlcError(2, "manifest_invalid:%s: unreadable (%s)" % (rel, type(exc).__name__)) from None
    try:
        return json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
    except ValueError as exc:  # json.JSONDecodeError is a ValueError
        raise SdlcError(2, "manifest_invalid:%s: %s" % (rel, _show(str(exc)))) from None


def _invalid(rel: str, errors: list) -> SdlcError:
    more = "" if len(errors) == 1 else " (+%d more)" % (len(errors) - 1)
    return SdlcError(2, "manifest_invalid:%s: %s%s" % (rel, _show(errors[0]), more))


def _schema(name: str) -> dict:
    """The cached schema (callers must not change it)."""
    if name not in SCHEMA_NAMES:
        raise SdlcError(2, "unknown_schema:%s" % _show(name))
    if name not in _SCHEMAS:
        rel = "flows/schemas/%s.schema.json" % name
        loaded = _read_json(plugin_root() / "flows" / "schemas" / (name + ".schema.json"), rel,
                            "manifest_missing:" + rel)
        try:
            schema.check_schema(loaded)
        except ValueError as exc:
            raise SdlcError(2, "manifest_invalid:%s: %s" % (rel, _show(str(exc)))) from None
        _SCHEMAS[name] = loaded
    return _SCHEMAS[name]


def load_schema(name: str) -> dict:
    """A copy of flows/schemas/<name>.schema.json from this runner's plugin root (SCHEMA_NAMES)."""
    return copy.deepcopy(_schema(name))


def load_shared(root) -> dict:
    """flows/_shared.json under `root`, validated."""
    rel = "flows/_shared.json"
    shared = _read_json(Path(root) / "flows" / "_shared.json", rel, "manifest_missing:" + rel)
    errors = validate_shared(shared)
    if errors:
        raise _invalid(rel, errors)
    return shared


def load_flow(root, flow_id) -> dict:
    """flows/<flow_id>.json under `root`, validated without the step-file check.

    An id that is not a flow name, or names no manifest, is SdlcError(2, "unknown_flow:<id>").
    """
    if not isinstance(flow_id, str) or not _ID_RE.match(flow_id):
        raise SdlcError(2, "unknown_flow:%s" % _show(flow_id))
    rel = "flows/%s.json" % flow_id
    flow = _read_json(Path(root) / "flows" / (flow_id + ".json"), rel, "unknown_flow:" + flow_id)
    errors = []
    if isinstance(flow, dict) and flow.get("id") != flow_id:
        errors.append("/id: must equal the file name %r" % flow_id)
    errors.extend(validate_flow(flow, root, check_files=False))
    if errors:
        raise _invalid(rel, errors)
    return flow


def load_loop(root, loop_id) -> dict:
    """flows/loops/<loop_id>.json under `root`, validated without the role-file check."""
    if not isinstance(loop_id, str) or not _ID_RE.match(loop_id):
        raise SdlcError(2, "unknown_loop:%s" % _show(loop_id))
    rel = "flows/loops/%s.json" % loop_id
    loop = _read_json(Path(root) / "flows" / "loops" / (loop_id + ".json"), rel, "unknown_loop:" + loop_id)
    errors = []
    if isinstance(loop, dict) and loop.get("id") != loop_id:
        errors.append("/id: must equal the file name %r" % loop_id)
    errors.extend(validate_loop(loop, root, check_files=False))
    if errors:
        raise _invalid(rel, errors)
    return loop


def _ids_in(folder: Path) -> list:
    try:
        names = [entry.name for entry in folder.iterdir() if entry.is_file()]
    except OSError:
        return []
    return sorted(name[:-5] for name in names if name.endswith(".json") and _ID_RE.match(name[:-5]))


def flow_ids(root) -> list:
    """Sorted flow ids under <root>/flows (`_shared.json` and other non-flow names left out)."""
    return _ids_in(Path(root) / "flows")


def loop_ids(root) -> list:
    """Sorted loop ids under <root>/flows/loops."""
    return _ids_in(Path(root) / "flows" / "loops")


# --- references and placeholders ---------------------------------------------------------------

def _path_problem(text: str):
    if not text:
        return "an empty path"
    if not _REF_CHARS_RE.match(text):
        return "%r has a character outside letters, digits and _ . - / { }" % text
    for segment in text.split("/"):
        if segment in ("", ".", ".."):
            return "%r has an empty, '.' or '..' segment" % text
        if segment.startswith("."):
            return "%r has a segment starting with '.'" % text
    for name in _PLACEHOLDER_RE.findall(text):
        if name not in PLACEHOLDERS:
            return "unknown placeholder {%s} (only {work_id})" % name
    rest = _PLACEHOLDER_RE.sub("", text)
    if "{" in rest or "}" in rest:
        return "%r has an unbalanced brace" % text
    return None


def parse_ref(entry) -> dict:
    """Read one `inputs`/`outputs` entry (contract §6).

    Returns {"set": "@source"|"@tests"|"@diff"|"@start"|None, "path": <package-relative template>
    |None, "body": bool, "optional": bool}. A path is relative to the package, POSIX-style, with
    `{work_id}` as its only placeholder; `#body` (fingerprint the body after the frontmatter) comes
    before the optional marker `?`. Anything else raises ValueError.
    """
    if not isinstance(entry, str) or not entry:
        raise ValueError("a reference is a non-empty string")
    if entry.startswith("@"):
        if entry not in NAMED_SETS:
            raise ValueError("unknown named set %r (known: %s)" % (entry, ", ".join(NAMED_SETS)))
        return {"set": entry, "path": None, "body": False, "optional": False}
    text = entry
    optional = text.endswith("?")
    if optional:
        text = text[:-1]
    body = text.endswith(_BODY)
    if body:
        text = text[:-len(_BODY)]
    problem = _path_problem(text)
    if problem:
        raise ValueError(problem)
    return {"set": None, "path": text, "body": body, "optional": optional}


def expand(path_template, state) -> str:
    """The template with `{work_id}` replaced from `state` (strip `#body` and `?` first: parse_ref).

    An unknown or unbalanced placeholder is SdlcError(2, "unknown_placeholder:<name or template>");
    a missing or invalid work id is SdlcError(2, "invalid_work_id").
    """
    template = str(path_template)
    rest = _PLACEHOLDER_RE.sub("", template)
    if "{" in rest or "}" in rest:
        raise SdlcError(2, "unknown_placeholder:" + _show(template))

    def replace(match):
        name = match.group(1)
        if name not in PLACEHOLDERS:
            raise SdlcError(2, "unknown_placeholder:" + _show(name))
        work_id = state.get("work_id") if isinstance(state, dict) else None
        if not valid_work_id(work_id):
            raise SdlcError(2, "invalid_work_id")
        return work_id

    return _PLACEHOLDER_RE.sub(replace, template)


# --- validation helpers ------------------------------------------------------------------------

def _esc(token) -> str:
    return str(token).replace("~", "~0").replace("/", "~1")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class _Errors:
    """Schema errors first; a rule error at a pointer the schema already reported is dropped."""

    def __init__(self, errors):
        self.errors = list(errors)
        self._schema_pointers = {error.split(": ", 1)[0] for error in errors}

    def add(self, pointer: str, reason: str) -> None:
        if pointer not in self._schema_pointers:
            self.errors.append("%s: %s" % (pointer, reason))


def _str_list(value) -> list:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _unique(out: _Errors, pointer: str, values, what: str) -> None:
    seen = set()
    for index, value in enumerate(values):
        if not isinstance(value, str):
            continue
        if value in seen:
            out.add("%s/%d" % (pointer, index), "duplicate %s %r" % (what, value))
        seen.add(value)


def _exists_exact(root, rel: str) -> bool:
    """True when `rel` (POSIX, relative) names a regular file under `root`, every segment spelled as
    on disk. Path.is_file ignores case on Windows and default macOS; Linux and the release archives
    do not, so a file whose case differs from its manifest must fail on every host."""
    folder = Path(root)
    for part in rel.split("/"):
        try:
            names = os.listdir(str(folder))
        except OSError:
            return False
        if part not in names:
            return False
        folder = folder / part
    return folder.is_file()


# --- flows -------------------------------------------------------------------------------------

def validate_flow(flow, root, check_files: bool) -> list:
    """Errors for one flow manifest (contract §6); `check_files` also requires every step file."""
    out = _Errors(schema.validate(flow, _schema("flow")))
    if not isinstance(flow, dict):
        return out.errors
    forms = _str_list(flow.get("forms"))
    work_types = _str_list(flow.get("work_types"))
    for key in ("forms", "work_types"):
        values = flow.get(key)
        if isinstance(values, list):
            if not values:
                out.add("/" + key, "a flow needs at least one value")
            _unique(out, "/" + key, values, key[:-1])
    steps = flow.get("steps")
    if not isinstance(steps, list):
        return out.errors
    if not steps:
        out.add("/steps", "a flow needs at least one step")
        return out.errors
    first = steps[0] if isinstance(steps[0], dict) else {}
    if first.get("id") != STRATEGY_STEP:
        out.add("/steps/0/id", "the first step must be %r" % STRATEGY_STEP)
    elif first.get("run_once") is not True or first.get("max_visits") != 1:
        out.add("/steps/0", "the strategy step is run_once with max_visits 1")
    produced = set(START_FILES) | _check_imports(out, flow)
    seen_ids, gates = {}, {}
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        at = "/steps/%d" % index
        step_id = step.get("id")
        if isinstance(step_id, str):
            if step_id in seen_ids:
                out.add(at + "/id", "duplicate step id %r (first at /steps/%d)" % (step_id, seen_ids[step_id]))
            else:
                seen_ids[step_id] = index
        gate = step.get("gate")
        if isinstance(gate, str):
            if gate in gates:
                out.add(at + "/gate", "gate %r is already used by /steps/%d" % (gate, gates[gate]))
            else:
                gates[gate] = index
        _check_file(out, at, step, work_types, root, check_files)
        _check_role(out, at, step, root, check_files)
        _check_refs(out, at, step)
        _check_producers(out, at, step, produced)
        produced |= _ref_paths(step.get("outputs"))
        _check_done_when(out, at, step, work_types)
        _check_applies(out, at, step, forms, work_types)
        _check_mechanism(out, at, step)
        _unique(out, at + "/may_ask", step.get("may_ask") if isinstance(step.get("may_ask"), list) else [],
                "question kind")
    _check_loop(out, flow, steps, root)
    return out.errors


def _ref_paths(refs) -> set:
    """The package paths of the well-formed path entries in an inputs/outputs list."""
    found = set()
    for ref in refs if isinstance(refs, list) else []:
        try:
            parsed = parse_ref(ref)
        except ValueError:
            continue
        if parsed["path"] is not None:
            found.add(parsed["path"])
    return found


def _check_imports(out: _Errors, flow: dict) -> set:
    """The package paths `start` imports (flow `imports`); errors for a malformed entry."""
    imports = flow.get("imports")
    found = set()
    if not isinstance(imports, list):
        return found
    for index, item in enumerate(imports):
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        where = "/imports/%d/path" % index
        try:
            parsed = parse_ref(item["path"])
        except ValueError as exc:
            out.add(where, str(exc))
            continue
        if parsed["set"] or parsed["body"] or parsed["optional"]:
            out.add(where, "an import is a plain package path")
        elif parsed["path"] in START_FILES:
            out.add(where, "%r is written by start itself" % parsed["path"])
        else:
            found.add(parsed["path"])
    _unique(out, "/imports", [i.get("path") for i in imports if isinstance(i, dict)], "import path")
    return found


def _check_producers(out: _Errors, at: str, step: dict, produced: set) -> None:
    """A required package input must already exist when the step is reached: written by an earlier
    step, by start (START_FILES) or by an import. Named sets and optional inputs need no writer."""
    refs = step.get("inputs")
    for index, ref in enumerate(refs if isinstance(refs, list) else []):
        try:
            parsed = parse_ref(ref)
        except ValueError:
            continue  # _check_refs names the problem
        if parsed["set"] or parsed["optional"] or parsed["path"] in produced:
            continue
        out.add("%s/inputs/%d" % (at, index), "required input %r is written by no earlier step, by start (%s) "
                "or by an import" % (parsed["path"], ", ".join(START_FILES)))


def _check_mechanism(out: _Errors, at: str, step: dict) -> None:
    """Contract §9: a step whose id is a mechanism-bearing key prints that strategy entry; no step
    prints another's (a mandated fresh step without its key would have no entry to check)."""
    step_id, key = step.get("id"), step.get("mechanism_key")
    if not isinstance(step_id, str):
        return
    if step_id in MECHANISM_KEYS:
        if key != step_id:
            out.add(at + "/mechanism_key", "the %s step prints its own strategy entry %r" % (step_id, step_id))
    elif isinstance(key, str):
        out.add(at + "/mechanism_key", "%r is not this step's entry (a step prints the entry its id names)" % key)


def _check_file(out: _Errors, at: str, step: dict, work_types: list, root, check_files: bool) -> None:
    value = step.get("file")
    if isinstance(value, dict):
        if step.get("id") != IMPLEMENT_STEP:
            out.add(at + "/file", "only the implement step maps work types to step files")
        else:
            for work_type in work_types:
                if work_type not in value:
                    out.add(at + "/file", "no implement variant for work type %r" % work_type)
            for work_type in value:
                if work_type not in work_types:
                    out.add(at + "/file/" + _esc(work_type), "%r is not a work type of this flow" % work_type)
        files = [(at + "/file/" + _esc(k), v) for k, v in value.items() if isinstance(v, str)]
    elif isinstance(value, str):
        files = [(at + "/file", value)]
    else:
        files = []
    if not check_files:
        return
    for pointer, rel in files:
        if _STEP_FILE_RE.match(rel) and not _exists_exact(root, rel):
            out.add(pointer, "missing step file %s" % rel)


def _check_role(out: _Errors, at: str, step: dict, root, check_files: bool) -> None:
    """A step's `role` names an agent file; `role_reads` (package paths) belong to a role."""
    role, reads = step.get("role"), step.get("role_reads")
    if isinstance(reads, list):
        if "role" not in step:
            out.add(at + "/role_reads", "role_reads names what the step's role reads; the step has no role")
        _unique(out, at + "/role_reads", reads, "role read")
        for index, ref in enumerate(reads):
            if not isinstance(ref, str):
                continue
            try:
                parsed = parse_ref(ref)
            except ValueError as exc:
                out.add("%s/role_reads/%d" % (at, index), str(exc))
                continue
            if parsed["set"] or parsed["body"] or parsed["optional"]:
                out.add("%s/role_reads/%d" % (at, index), "a role reads plain package paths")
    if check_files and isinstance(role, str) and _ID_RE.match(role):
        if not _exists_exact(root, "agents/%s.md" % role):
            out.add(at + "/role", "role_file_missing:%s" % role)


def _check_refs(out: _Errors, at: str, step: dict) -> None:
    for key in ("inputs", "outputs"):
        refs = step.get(key)
        if not isinstance(refs, list):
            continue
        _unique(out, "%s/%s" % (at, key), refs, "reference")
        for index, ref in enumerate(refs):
            if not isinstance(ref, str):
                continue
            pointer = "%s/%s/%d" % (at, key, index)
            try:
                parsed = parse_ref(ref)
            except ValueError as exc:
                out.add(pointer, str(exc))
                continue
            if key == "outputs" and (parsed["set"] or parsed["body"]):
                out.add(pointer, "named sets and #body are for inputs only")


def _check_done_when(out: _Errors, at: str, step: dict, work_types: list) -> None:
    checks = step.get("done_when")
    if not isinstance(checks, list):
        return
    if not checks:
        out.add(at + "/done_when", "a step needs at least one check")
    approvals = []
    for index, check in enumerate(checks):
        if not isinstance(check, dict) or check.get("check") not in CHECK_PARAMS:
            continue  # the schema names the problem
        where = "%s/done_when/%d" % (at, index)
        name = check["check"]
        required, optional = CHECK_PARAMS[name]
        for param in required:
            if param not in check:
                out.add(where, "%s needs %r" % (name, param))
        for param in check:
            if param != "check" and param not in required + optional + GENERIC_CHECK_PARAMS:
                out.add(where + "/" + _esc(param), "%r is not a parameter of %s" % (param, name))
        listed = check.get("work_types")
        if isinstance(listed, list):
            if not listed:
                out.add(where + "/work_types", "an empty list never holds")
            for work_type in _str_list(listed):
                if work_type not in work_types:
                    out.add(where + "/work_types", "%r is not a work type of this flow" % work_type)
            _unique(out, where + "/work_types", listed, "work type")
        if isinstance(check.get("path"), str) and "path" in required:
            try:
                parsed = parse_ref(check["path"])
            except ValueError as exc:
                out.add(where + "/path", str(exc))
            else:
                if parsed["set"] or parsed["body"] or parsed["optional"]:
                    out.add(where + "/path", "a check path is a plain package path")
        if name == "approval":
            approvals.append((where, check.get("gate")))
    gate = step.get("gate")
    if approvals:
        if not isinstance(gate, str):
            out.add(at + "/gate", "a step with an approval check names its gate")
        for where, named in approvals:
            if isinstance(gate, str) and named != gate:
                out.add(where + "/gate", "approval names gate %r; the step's gate is %r" % (named, gate))
    elif isinstance(gate, str):
        out.add(at + "/gate", "a gate step needs an approval check for %r" % gate)


def _check_applies(out: _Errors, at: str, step: dict, forms: list, work_types: list) -> None:
    cond = step.get("applies_when")
    if not isinstance(cond, dict):
        return
    where = at + "/applies_when"
    if not cond:
        out.add(where, "an empty condition; leave applies_when out instead")
    form = cond.get("form")
    if isinstance(form, str) and form not in forms:
        out.add(where + "/form", "%r is not a form of this flow" % form)
    listed = cond.get("work_type")
    if isinstance(listed, list):
        if not listed:
            out.add(where + "/work_type", "an empty list never holds")
        for work_type in _str_list(listed):
            if work_type not in work_types:
                out.add(where + "/work_type", "%r is not a work type of this flow" % work_type)
    if ("probe" in cond) != ("not" in cond):
        out.add(where, "probe and not go together")
    elif "probe" in cond:
        probe, value = cond.get("probe"), cond.get("not")
        if probe in PROBE_VALUES and value not in PROBE_VALUES[probe]:
            out.add(where + "/not", "%r is not a value of the %s probe (%s)"
                    % (value, probe, ", ".join(PROBE_VALUES[probe])))


def _check_loop(out: _Errors, flow: dict, steps: list, root) -> None:
    loop_steps = [(index, step) for index, step in enumerate(steps)
                  if isinstance(step, dict) and isinstance(step.get("loop"), str)]
    mode = flow.get("loop_mode")
    for position, (index, step) in enumerate(loop_steps):
        where = "/steps/%d/loop" % index
        if position:
            out.add(where, "only one step runs a loop")
            continue
        try:
            loop = load_loop(root, step["loop"])
        except SdlcError as exc:
            if exc.message.startswith("unknown_loop:"):
                out.add(where, "unknown loop %r" % step["loop"])
            else:
                out.add(where, "loop %r does not load: %s" % (step["loop"], exc.message))
            continue
        if isinstance(mode, str) and mode not in loop["modes"]:
            out.add("/loop_mode", "%r is not a mode of loop %r" % (mode, step["loop"]))
    if loop_steps and mode is None:
        out.add("/loop_mode", "a flow with a loop step names its loop_mode")
    elif not loop_steps and mode is not None:
        out.add("/loop_mode", "no step runs a loop, so loop_mode is null")


# --- shared policy -----------------------------------------------------------------------------

def glob_problem(glob):
    """Why `glob` is outside the test-glob dialect fingerprint.py reads, or None when it is inside.

    The dialect: POSIX paths relative to the project root; `**` as a whole segment, `*` and `?`
    within one segment, `{a,b}` alternatives (two or more). Any other character (`[`, `!`, a
    backslash, a space) would be read literally there, so it is refused here instead.
    """
    if not isinstance(glob, str) or not glob:
        return "a glob is a non-empty string"
    if not _GLOB_CHARS_RE.match(glob):
        return "%r has a character the glob dialect does not support (letters, digits, _ . - / * ? { } ,)" % glob
    if glob.startswith("/") or glob.startswith("./"):
        return "%r: globs are relative to the project root, with no leading / or ./" % glob
    if glob.endswith("/"):
        return "%r ends with /" % glob
    for segment in glob.split("/"):
        if segment in ("", ".", ".."):
            return "%r has an empty, '.' or '..' segment" % glob
        if "**" in segment and segment != "**":
            return "%r: ** must be a whole path segment" % glob
    stack, groups = [], []
    for index, char in enumerate(glob):
        if char == "{":
            stack.append(index)
        elif char == "}":
            if not stack:
                return "%r has an unbalanced brace" % glob
            groups.append(glob[stack.pop() + 1:index])
        elif char == "," and not stack:
            return "%r has a comma outside braces" % glob
    if stack:
        return "%r has an unbalanced brace" % glob
    for group in groups:
        depth, options = 0, 1
        for char in group:
            depth += 1 if char == "{" else -1 if char == "}" else 0
            options += 1 if char == "," and depth == 0 else 0
        if options < 2:
            return "%r: {%s} has one option and would be read literally" % (glob, group)
    try:
        fingerprint.glob_match("", glob)
    except ValueError as exc:
        return str(exc)
    return None


def _runner_id(entry: dict) -> str:
    runner = entry.get("runner")
    if isinstance(runner, str):
        return runner
    program = entry["program"]
    return program[2:] if program.startswith("./") else program


def runner_ids(shared) -> list:
    """Sorted runner ids of the non-wrapping allowlist entries (the keys `exit_codes` may use)."""
    ids = set()
    allow = shared.get("run_allowlist") if isinstance(shared, dict) else None
    for entry in allow if isinstance(allow, list) else []:
        if isinstance(entry, dict) and isinstance(entry.get("program"), str) and not entry.get("wraps"):
            ids.add(_runner_id(entry))
    return sorted(ids)


def _tokens_prefix(earlier: str, later: str) -> bool:
    first, second = earlier.split(" "), later.split(" ")
    return second[:len(first)] == first


_WRAPPER_ONLY_KEYS = ("inner", "insert_args")
_INNER_ONLY_KEYS = ("module_only", "script_after", "deny_args", "deny_prefixes", "deny_vars", "path_flags", "runner")


def _check_allowlist(out: _Errors, allow) -> None:
    catch_all, claimed = set(), {}
    programs = {entry.get("program") for entry in allow if isinstance(entry, dict)}
    for index, entry in enumerate(allow):
        if not isinstance(entry, dict) or not isinstance(entry.get("program"), str):
            continue
        at = "/run_allowlist/%d" % index
        program = entry["program"]
        subs = _str_list(entry.get("subcommand")) if "subcommand" in entry else None
        if subs is not None and not subs:
            out.add(at + "/subcommand", "an empty list matches nothing; leave subcommand out to allow any arguments")
        if program in catch_all:
            out.add(at, "unreachable: an earlier %s entry takes every argument list" % program)
        elif subs is not None:
            for sub in subs:
                if any(_tokens_prefix(earlier, sub) for earlier in claimed.get(program, [])):
                    out.add(at + "/subcommand", "unreachable: %s %s is matched by an earlier entry" % (program, sub))
        if subs is None:
            catch_all.add(program)
        else:
            claimed.setdefault(program, []).extend(subs)
        for sub in _str_list(entry.get("script_after")):
            if subs is None or sub not in subs:
                out.add(at + "/script_after", "%r is not one of this entry's subcommands" % sub)
        if entry.get("wraps"):
            for key in _INNER_ONLY_KEYS:
                if key in entry:
                    out.add(at + "/" + key, "a wrapping entry checks its inner command; %s belongs there" % key)
            for position, name in enumerate(_str_list(entry.get("inner"))):
                if name not in programs:
                    out.add("%s/inner/%d" % (at, position), "%r is not a program of run_allowlist" % name)
        else:
            for key in _WRAPPER_ONLY_KEYS:
                if key in entry:
                    out.add(at + "/" + key, "only a wrapping entry names %s" % key)


def validate_shared(shared) -> list:
    """Errors for flows/_shared.json (risk lexicon, globs, run allowlist, caps, runtime rows)."""
    out = _Errors(schema.validate(shared, _schema("shared")))
    if not isinstance(shared, dict):
        return out.errors
    caps = shared.get("caps")
    if isinstance(caps, dict):
        rounds, hard = caps.get("loop_max_rounds"), caps.get("loop_hard_max_rounds")
        if _is_int(rounds) and _is_int(hard) and rounds > hard:
            out.add("/caps/loop_max_rounds", "greater than loop_hard_max_rounds (%d)" % hard)
    runtimes = shared.get("runtimes")
    if isinstance(runtimes, dict):
        for runtime in runtimes:
            if runtime not in RUNTIMES:
                out.add("/runtimes/" + _esc(runtime), "unknown runtime (known: %s)" % ", ".join(RUNTIMES))
    lexicon = shared.get("risk_lexicon")
    if isinstance(lexicon, dict):
        listed = {}
        for surface, terms in lexicon.items():
            for index, term in enumerate(_str_list(terms)):
                if term in listed:
                    out.add("/risk_lexicon/%s/%d" % (_esc(surface), index),
                            "%r is already listed under %s" % (term, listed[term]))
                else:
                    listed[term] = surface
    globs = shared.get("test_globs")
    if isinstance(globs, list):
        if not globs:
            out.add("/test_globs", "an empty list makes every changed file a source file")
    for key in ("test_globs", "ignore_globs"):
        listed = shared.get(key)
        if not isinstance(listed, list):
            continue
        _unique(out, "/" + key, listed, "glob")
        for index, glob in enumerate(listed):
            problem = glob_problem(glob)
            if problem:
                out.add("/%s/%d" % (key, index), problem)
    allow = shared.get("run_allowlist")
    if isinstance(allow, list):
        _check_allowlist(out, allow)
    scripts = shared.get("run_scripts")
    if isinstance(scripts, list):
        _unique(out, "/run_scripts", scripts, "script")
    codes = shared.get("exit_codes")
    if isinstance(codes, dict):
        known = set(runner_ids(shared))
        for runner, row in codes.items():
            where = "/exit_codes/" + _esc(runner)
            if runner not in known:
                out.add(where, "not a runner id of run_allowlist")
            if not isinstance(row, dict):
                continue
            fail = [c for c in row.get("fail", []) if _is_int(c)] if isinstance(row.get("fail"), list) else []
            invalid = [c for c in row.get("invalid", []) if _is_int(c)] if isinstance(row.get("invalid"), list) else []
            both = sorted(set(fail) & set(invalid))
            if both:
                out.add(where, "exit code(s) %s are both fail and invalid" % both)
            if 0 in fail or 0 in invalid:
                out.add(where, "0 is success, never fail or invalid")
    edges = shared.get("escalation")
    if isinstance(edges, list):
        seen = {}
        for index, edge in enumerate(edges):
            pair = (edge.get("from"), edge.get("to")) if isinstance(edge, dict) else (None, None)
            if not all(isinstance(flow_id, str) for flow_id in pair):
                continue
            where = "/escalation/%d" % index
            if pair[0] == pair[1]:
                out.add(where, "an edge leads to another flow (%s -> %s)" % pair)
            elif pair in seen:
                out.add(where, "duplicate edge %s -> %s (first at /escalation/%d)" % (pair + (seen[pair],)))
            else:
                seen[pair] = index
    return out.errors


def validate_lattice(root, shared) -> list:
    """Errors for `_shared.escalation` against the flow manifests under `root` (design §5.11).

    Every edge names two loadable flows; the work types the package carries into the target
    (its own for "keep", else the mapped one) are work types of the target flow, so the target's
    implement map has a variant for each; and the lattice has no cycle (an edge whose target
    already reaches its source is upward-only violated). start/escalate call this; the tests pin it.
    """
    edges = shared.get("escalation") if isinstance(shared, dict) else None
    if not isinstance(edges, list):
        return ["/escalation: missing (a list of edges)"]
    errors, flows, reach = [], {}, {}

    def flow(flow_id):
        if flow_id not in flows:
            try:
                flows[flow_id] = (load_flow(root, flow_id), None)
            except SdlcError as exc:
                flows[flow_id] = (None, exc.message)
        return flows[flow_id]

    def reaches(start, goal):
        stack, seen = [start], set()
        while stack:
            node = stack.pop()
            if node == goal:
                return True
            if node not in seen:
                seen.add(node)
                stack.extend(reach.get(node, ()))
        return False

    for index, edge in enumerate(edges):
        where = "/escalation/%d" % index
        if not isinstance(edge, dict):
            errors.append(where + ": an edge is an object")
            continue
        loaded = {}
        for side in ("from", "to"):
            flow_id = edge.get(side)
            found, problem = flow(flow_id) if isinstance(flow_id, str) else (None, "unknown_flow:")
            if found is None:
                if problem.startswith("unknown_flow:"):
                    errors.append("%s/%s: unknown flow %r" % (where, side, flow_id))
                else:
                    errors.append("%s/%s: flow %r does not load: %s" % (where, side, flow_id, problem))
            loaded[side] = found
        source, target = loaded["from"], loaded["to"]
        if source is None or target is None:
            continue
        mapped = edge.get("work_type")
        carried = list(source.get("work_types") or []) if mapped == "keep" else [mapped]
        for work_type in carried:
            if work_type not in target.get("work_types", []):
                errors.append("%s/work_type: %r is not a work type of flow %r" % (where, work_type, target["id"]))
        if reaches(target["id"], source["id"]):
            errors.append("%s: the lattice is upward only; %s -> %s closes a cycle" % (where, source["id"], target["id"]))
        else:
            reach.setdefault(source["id"], []).append(target["id"])
    return errors


# --- loop definition ---------------------------------------------------------------------------

def validate_loop(loop, root, check_files: bool) -> list:
    """Errors for a loop definition (flows/loops/<id>.json); `check_files` requires the role files."""
    out = _Errors(schema.validate(loop, _schema("loop")))
    if not isinstance(loop, dict):
        return out.errors
    caps = loop.get("caps")
    if isinstance(caps, dict):
        rounds, hard = caps.get("max_rounds"), caps.get("hard_max_rounds")
        if _is_int(rounds) and _is_int(hard) and rounds > hard:
            out.add("/caps/max_rounds", "greater than hard_max_rounds (%d)" % hard)
    roles = loop.get("roles") if isinstance(loop.get("roles"), dict) else {}
    files = loop.get("files") if isinstance(loop.get("files"), dict) else {}
    written = set()
    for name, role in roles.items():
        if not isinstance(role, dict):
            continue
        where = "/roles/" + _esc(name)
        writes = role.get("writes")
        written.add(writes)
        if isinstance(writes, str) and writes not in files:
            out.add(where + "/writes", "%r is not a key of files" % writes)
        also = role.get("also_writes")
        for index, key in enumerate(also if isinstance(also, list) else []):
            if not isinstance(key, str):
                continue
            written.add(key)
            if key not in files:
                out.add("%s/also_writes/%d" % (where, index), "%r is not a key of files" % key)
            elif key == writes:
                out.add("%s/also_writes/%d" % (where, index), "%r is already what the role writes" % key)
        if isinstance(also, list):
            _unique(out, where + "/also_writes", also, "file key")
        role_file = role.get("role_file")
        if check_files and isinstance(role_file, str) and _ROLE_FILE_RE.match(role_file):
            if not _exists_exact(root, role_file):
                out.add(where + "/role_file", "missing role file %s" % role_file)
        role_schema = role.get("schema")
        if check_files and isinstance(role_schema, str) and _SCHEMA_FILE_RE.match(role_schema):
            if not _exists_exact(root, role_schema):
                out.add(where + "/schema", "missing schema file %s" % role_schema)
    if "critic" not in roles:
        out.add("/roles", "the later rounds need a critic role")
    check = loop.get("draft_check")
    if isinstance(check, dict):
        written.add(check.get("writes"))
    for key in files:
        if key not in LOOP_RUNNER_FILES and key not in written:
            out.add("/files/" + _esc(key), "no role and no draft-check writes it")
    modes = loop.get("modes")
    for mode, spec in (modes.items() if isinstance(modes, dict) else []):
        if not isinstance(spec, dict):
            continue
        where = "/modes/" + _esc(mode)
        order = {}
        for part in ("first_round", "revise"):
            sequence = spec.get(part)
            order[part] = []
            for index, item in enumerate(sequence if isinstance(sequence, list) else []):
                role = item.get("role") if isinstance(item, dict) else None
                if not isinstance(role, str):
                    continue
                order[part].append(role)
                if role not in roles:
                    out.add("%s/%s/%d/role" % (where, part, index), "unknown role %r" % role)
        if order["revise"] != order["first_round"]:
            out.add(where + "/revise", "revise runs the first round's roles again (%s)" % ", ".join(order["first_round"]))
        expected = [roles[r].get("writes") for r in order["first_round"] if isinstance(roles.get(r), dict)]
        if isinstance(spec.get("artifacts"), list) and spec["artifacts"] != expected:
            out.add(where + "/artifacts", "%s, but the first round writes %s" % (spec["artifacts"], expected))
    if isinstance(check, dict) and isinstance(check.get("writes"), str) and check["writes"] not in files:
        out.add("/draft_check/writes", "%r is not a key of files" % check["writes"])
    result_schema = loop.get("result_schema")
    if check_files and isinstance(result_schema, str) and _SCHEMA_FILE_RE.match(result_schema):
        if not _exists_exact(root, result_schema):
            out.add("/result_schema", "missing schema file %s" % result_schema)
    return out.errors
