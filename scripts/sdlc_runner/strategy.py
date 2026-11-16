"""The strategy step (contract §9, design §5.7): the default map, strategy_ok, confirm, resolve.

`start` writes strategy.default.json from the rule table below and the runtime's capability row
in `_shared.runtimes`. The strategy card shows that map; the model declares what it really has in
this session and confirms or overrides each entry with a reason in one command:

    sdlc strategy confirm --capabilities workflow=yes|no|denied,subagent=...,team=...
                          [--set <key>=<mechanism>:<reason>]...

`confirm` writes strategy.json (`agentic-sdlc/strategy@1`) only when strategy_ok holds:
- every mechanism-bearing key of a step that applies is covered (a loop step adds its roles' keys,
  `draft` and `draft.critic`);
- every override has a reason;
- every mechanism is within the declared capabilities (`subagent` and `runner-loop` need
  subagent=yes, `workflow` workflow=yes and a runtime with an engine, `team` team=yes); the
  spec/plan keys (`draft`, `draft.critic`) get `workflow` only as an override, on every runtime;
- the mandated fresh-context keys (draft.critic, security, audit, quality-review) are never `main`
  (or `team`, `parallel-runs`): `workflow`, `subagent`, `runner-loop` (draft.critic only), or
  `inline-degraded`/`runner-loop-inline` with subagent declared no or denied;
- `runner-loop` and `runner-loop-inline` belong to the draft keys only, and the degraded list
  names exactly the entries that run inline.
The strategy step is run_once: `confirm` is refused once it is done, and re-entry (resume,
compaction, a new session) goes through the read-only card. `escalate` adds default entries for
the keys the new flow needs and keeps every existing entry (`amend_for_escalate`).
"""
from __future__ import annotations

import copy
import types
from pathlib import Path

from . import manifest, paths, schema
from .textio import SdlcError, read_json, write_json_atomic

STRATEGY_FILE = "strategy.json"
DEFAULT_FILE = "strategy.default.json"
STRATEGY_SCHEMA_ID = "agentic-sdlc/strategy@1"
CAPABILITIES = ("workflow", "subagent", "team")
DECLARED = ("yes", "no", "denied")
DEGRADED = ("inline-degraded", "runner-loop-inline")
DRAFT_KEYS = ("draft", "draft.critic")
LOOP_MECHANISMS = ("runner-loop", "runner-loop-inline")
NEEDS = {"subagent": "subagent", "runner-loop": "subagent", "workflow": "workflow", "team": "team"}
FRESH_ALLOWED = ("workflow", "subagent", "runner-loop") + DEGRADED


# --- applicability -----------------------------------------------------------------------------

def _facts(probes, options, form=None, work_type=None, imported=None) -> dict:
    return {"probes": dict(probes or {}), "options": list(options or []), "form": form, "work_type": work_type,
            "imported": list(imported or [])}


def _applies(step, facts) -> bool:
    """engine.applies over start facts; a fact that is not known yet (None) does not exclude."""
    from . import engine  # engine imports card, which imports this module

    known = {key: value for key, value in facts.items() if value is not None}
    cond = step.get("applies_when") or {}
    if "form" in cond and "form" not in known:
        cond = {k: v for k, v in cond.items() if k != "form"}
    if "work_type" in cond and "work_type" not in known:
        cond = {k: v for k, v in cond.items() if k != "work_type"}
    probe_step = dict(step, applies_when=cond or None)
    return engine.applies(types.SimpleNamespace(state=known), probe_step)[0]


def _loop_keys(loop_id) -> list:
    try:
        definition = manifest.load_loop(paths.plugin_root(), loop_id)
    except SdlcError:
        return list(DRAFT_KEYS)
    keys = []
    for role in definition.get("roles", {}).values():
        key = role.get("mechanism_key")
        if isinstance(key, str) and key not in keys:
            keys.append(key)
    return keys


def applicable_keys(flow, facts) -> list:
    """The mechanism-bearing keys of the steps that apply, in contract §9 order."""
    found = set()
    for step in flow.get("steps", []):
        if not _applies(step, facts):
            continue
        if isinstance(step.get("mechanism_key"), str):
            found.add(step["mechanism_key"])
        if isinstance(step.get("loop"), str):
            found.update(_loop_keys(step["loop"]))
    return [key for key in manifest.MECHANISM_KEYS if key in found]


def _state_facts(state) -> dict:
    return _facts(state.get("probes"), state.get("options"), state.get("form"), state.get("work_type"),
                  state.get("imported"))


# --- the rule table ----------------------------------------------------------------------------

def runtime_row(shared, runtime) -> dict:
    rows = shared.get("runtimes") or {}
    return dict(rows.get(runtime) or rows.get("other") or {"workflow": "none", "subagent": "no", "team": "no"})


def _rule(key, row, probes) -> tuple:
    """(mechanism, reason) of `key` under the runtime row and the probes (design §5.7)."""
    sub = row.get("subagent") == "yes"
    if key == "context":
        if probes.get("explore_mode") == "parallel" and sub:
            return "subagent", "explore mode parallel: one analyst sub-agent per layer"
        return "main", "one layer to explore: the main loop reads it"
    if key in DRAFT_KEYS:
        if sub:
            return "runner-loop", "the runner drives the loop, each role a fresh sub-agent"
        return "runner-loop-inline", "no sub-agents: the runner drives the loop inline"
    if key in manifest.MANDATED_FRESH_KEYS:
        if sub:
            return "subagent", "a fresh-context gate: a fresh sub-agent"
        return "inline-degraded", "a fresh-context gate, but the runtime has no sub-agents"
    if key == "implement":
        return "main", "the main loop implements; independent plan tasks may fan out"
    if key == "quality-gates":
        return "parallel-runs", "independent check commands run side by side through sdlc run"
    return "main", "the main loop does it"


def default_map(flow, shared, probes, runtime, options, *, form=None, work_type=None, imported=None) -> dict:
    """strategy.default.json: one default entry per applicable key, from the runtime's row."""
    row = runtime_row(shared, runtime)
    facts = _facts(probes, options, form, work_type, imported)
    entries = {}
    for key in applicable_keys(flow, facts):
        mechanism, reason = _rule(key, row, facts["probes"])
        entries[key] = {"mechanism": mechanism, "reason": reason, "source": "default"}
    return {"runtime": runtime, "flow": flow.get("id"), "row": row, "entries": entries}


def build_map(runtime, capabilities, entries) -> dict:
    """A strategy.json body: entries as given, the degraded list derived from them."""
    degraded = []
    for key in manifest.MECHANISM_KEYS:
        entry = entries.get(key)
        if isinstance(entry, dict) and entry.get("mechanism") in DEGRADED:
            declared = capabilities.get("subagent") if isinstance(capabilities, dict) else None
            degraded.append({"key": key, "capability": "subagent", "reason": "subagent=%s" % (declared or "unknown")})
    return {"schema": STRATEGY_SCHEMA_ID, "runtime": runtime, "capabilities": dict(capabilities),
            "entries": copy.deepcopy(entries), "degraded": degraded}


# --- strategy_ok -------------------------------------------------------------------------------

def _entry_errors(key, entry, capabilities, row) -> list:
    at = "/entries/" + key
    mechanism = entry.get("mechanism")
    errors = []
    if entry.get("source") == "override" and not str(entry.get("reason") or "").strip():
        errors.append("%s: an override needs a reason" % at)
    need = NEEDS.get(mechanism)
    if need and capabilities.get(need) != "yes":
        errors.append("%s: %s needs %s=yes (declared %s)" % (at, mechanism, need, capabilities.get(need)))
    if mechanism == "workflow":
        if row.get("workflow") == "none":
            errors.append("%s: no workflow engine on this runtime" % at)
        elif key in DRAFT_KEYS and entry.get("source") != "override":
            errors.append("%s: an engine runs only on the user's explicit request (an override with a reason)" % at)
    if mechanism in LOOP_MECHANISMS and key not in DRAFT_KEYS:
        errors.append("%s: %s drives the spec/plan loop only" % (at, mechanism))
    if mechanism in DEGRADED and capabilities.get("subagent") not in ("no", "denied"):
        errors.append("%s: %s needs subagent=no or denied (declared %s)" % (at, mechanism, capabilities.get("subagent")))
    if key in manifest.MANDATED_FRESH_KEYS:
        if mechanism not in FRESH_ALLOWED:
            errors.append("%s: a fresh-context gate is never main (%s)" % (at, mechanism))
        elif mechanism == "runner-loop" and key != "draft.critic":
            errors.append("%s: runner-loop is allowed for draft.critic only" % at)
    return errors


def validate(strategy_map, flow, state) -> list:
    """Errors for strategy.json (an empty list means strategy_ok)."""
    errors = schema.validate(strategy_map, manifest.load_schema("strategy"))
    if errors:
        return errors
    if strategy_map.get("runtime") != state.get("runtime"):
        errors.append("/runtime: %r, but the flow started with --runtime %r"
                      % (strategy_map.get("runtime"), state.get("runtime")))
    row = runtime_row(_runner_shared(), strategy_map.get("runtime"))
    capabilities = strategy_map["capabilities"]
    entries = strategy_map["entries"]
    for key in applicable_keys(flow, _state_facts(state)):
        if key not in entries:
            errors.append("/entries/%s: missing (a step that applies prints this entry)" % key)
    for key in manifest.MECHANISM_KEYS:
        if key in entries:
            errors.extend(_entry_errors(key, entries[key], capabilities, row))
    listed = {item["key"] for item in strategy_map["degraded"]}
    inline = {key for key, entry in entries.items() if entry.get("mechanism") in DEGRADED}
    for key in sorted(inline - listed):
        errors.append("/degraded: %s runs inline but is not listed" % key)
    for key in sorted(listed - inline):
        errors.append("/degraded: %s is listed but does not run inline" % key)
    return errors


_SHARED = []


def _runner_shared() -> dict:
    """flows/_shared.json of this runner's own root (the runtime rows are the runner's policy)."""
    if not _SHARED:
        _SHARED.append(manifest.load_shared(paths.plugin_root()))
    return _SHARED[0]


# --- files -------------------------------------------------------------------------------------

def load_map(pkg):
    """strategy.json of the package, or None when it is missing or unreadable."""
    try:
        data = read_json(Path(pkg) / STRATEGY_FILE)
    except (OSError, ValueError, SdlcError):
        return None
    return data if isinstance(data, dict) else None


def load_default(pkg):
    try:
        data = read_json(Path(pkg) / DEFAULT_FILE)
    except (OSError, ValueError, SdlcError):
        return None
    return data if isinstance(data, dict) else None


def resolve(ctx, key) -> tuple:
    """(mechanism, degraded text) of `key`: from strategy.json, `unset` without an entry. The degraded
    text is `<capability>:<declared>` for an inline entry, `<capability>:<reason>` for a recorded
    `note --degraded` on the step of that key, else `none`."""
    data = load_map(ctx.pkg)
    entries = data.get("entries") if isinstance(data, dict) else None
    entry = entries.get(key) if isinstance(entries, dict) else None
    mechanism = entry.get("mechanism") if isinstance(entry, dict) else None
    degraded = "none"
    for item in (data.get("degraded") or []) if isinstance(data, dict) else []:
        if isinstance(item, dict) and item.get("key") == key:
            declared = str(item.get("reason") or "").split("=", 1)[-1] or "no"
            degraded = "%s:%s" % (item.get("capability"), declared)
            break
    step_id = key if key != "draft.critic" else "draft"
    for note in ctx.state.get("degraded") or []:
        if isinstance(note, dict) and note.get("step") == step_id:
            degraded = "%s:%s" % (note.get("capability"), note.get("reason"))
    return (mechanism if isinstance(mechanism, str) else "unset"), degraded


def default_lines(ctx) -> list:
    """`default=` and `confirm=` lines for the strategy card."""
    from .card import runner_command

    data = load_default(ctx.pkg) or default_map(ctx.flow, ctx.shared, ctx.state.get("probes"), ctx.state.get("runtime"),
                                                ctx.state.get("options"), form=ctx.state.get("form"),
                                                work_type=ctx.state.get("work_type"),
                                                imported=ctx.state.get("imported"))
    shown = ",".join("%s:%s" % (key, entry.get("mechanism")) for key, entry in (data.get("entries") or {}).items())
    command = runner_command("strategy", "confirm", "--slug", ctx.state["slug"], "--capabilities")
    return ["default=" + (shown or "none"),
            "confirm=" + command + " workflow=<yes|no|denied>,subagent=<yes|no|denied>,team=<yes|no|denied>"
            ' [--set <key>=<mechanism>:"<reason>"]...']


# --- confirm -----------------------------------------------------------------------------------

def parse_capabilities(text) -> dict:
    """`workflow=yes,subagent=no,team=denied` -> dict; SdlcError(2) for anything else."""
    found = {}
    for part in str(text or "").split(","):
        name, sep, value = part.strip().partition("=")
        if not sep or name not in CAPABILITIES or value not in DECLARED or name in found:
            raise SdlcError(2, "bad_capabilities:%s (workflow=,subagent=,team= each yes|no|denied)" % part.strip()[:40])
        found[name] = value
    missing = [name for name in CAPABILITIES if name not in found]
    if missing:
        raise SdlcError(2, "bad_capabilities:missing %s" % ",".join(missing))
    return found


def parse_override(text) -> tuple:
    """`key=mechanism:reason` -> (key, mechanism, reason); SdlcError(2) when malformed."""
    key, sep, rest = str(text or "").partition("=")
    mechanism, _colon, reason = rest.partition(":")
    key, mechanism = key.strip(), mechanism.strip()
    if not sep or key not in manifest.MECHANISM_KEYS or mechanism not in manifest.MECHANISMS:
        raise SdlcError(2, "bad_override:%s (key=mechanism:reason)" % str(text)[:60])
    return key, mechanism, reason.strip()


def confirm(ctx, capabilities: dict, overrides: list) -> int:
    """Write strategy.json from the default map, the declaration and the overrides; the caller holds
    the package lock. SdlcError(4) when the step is done or strategy_ok would fail."""
    from . import logs, mask
    from . import state as state_mod

    entry = (ctx.state.get("steps") or {}).get(manifest.STRATEGY_STEP) or {}
    if entry.get("state") == "done":
        raise SdlcError(4, "strategy_already_confirmed (the strategy step runs once; the card is read-only)")
    st = ctx.state
    base = default_map(ctx.flow, ctx.shared, st.get("probes"), st.get("runtime"), st.get("options"),
                       form=st.get("form"), work_type=st.get("work_type"), imported=st.get("imported"))
    entries = copy.deepcopy(base["entries"])
    applied = []
    for key, mechanism, reason in overrides:
        if not reason:
            raise SdlcError(4, "override_needs_reason:%s" % key)
        if key not in entries:
            raise SdlcError(4, "not_applicable:%s (no step of this flow uses it)" % key)
        masked = mask.mask_text(reason)
        entries[key] = {"mechanism": mechanism, "reason": masked, "source": "override"}
        applied.append({"key": key, "mechanism": mechanism, "reason": masked})
    strategy_map = build_map(st.get("runtime"), capabilities, entries)
    errors = validate(strategy_map, ctx.flow, st)
    if errors:
        raise SdlcError(4, "strategy_refused:%s" % errors[0])
    write_json_atomic(Path(ctx.pkg) / STRATEGY_FILE, strategy_map, within=ctx.pkg)
    logs.append(Path(ctx.pkg) / "transitions.jsonl", {
        "kind": "strategy", "capabilities": strategy_map["capabilities"], "overrides": applied,
        "degraded": strategy_map["degraded"], "entries": {k: v["mechanism"] for k, v in entries.items()},
    })
    state_mod.save(ctx.pkg, st)
    return 0


def amend_for_escalate(ctx, target_flow, facts_state) -> list:
    """Add default entries for the keys `target_flow` needs and strategy.json lacks; keep the rest.

    A default that needs a capability the session declared no/denied is degraded instead (a fresh
    gate inline, anything else in the main loop). Returns the keys added (none without strategy.json).
    """
    data = load_map(ctx.pkg)
    if data is None:
        return []
    row = runtime_row(ctx.shared, data.get("runtime"))
    capabilities = data.get("capabilities") or {}
    entries = copy.deepcopy(data.get("entries") or {})
    added = []
    for key in applicable_keys(target_flow, _state_facts(facts_state)):
        if key in entries:
            continue
        mechanism, reason = _rule(key, row, (facts_state.get("probes") or {}))
        need = NEEDS.get(mechanism)
        if need and capabilities.get(need) != "yes":
            sub = capabilities.get("subagent") == "yes"
            if key in DRAFT_KEYS:
                mechanism = "runner-loop" if sub else "runner-loop-inline"
            elif key in manifest.MANDATED_FRESH_KEYS:
                mechanism = "subagent" if sub else "inline-degraded"
            else:
                mechanism = "main"
            reason = "%s=%s declared" % (need, capabilities.get(need))
        entries[key] = {"mechanism": mechanism, "source": "default",
                        "reason": "added at escalate %s->%s: %s" % (ctx.flow.get("id"), target_flow.get("id"), reason)}
        added.append(key)
    if added:
        amended = build_map(data.get("runtime"), capabilities, entries)
        errors = validate(amended, target_flow, facts_state)
        if errors:  # the strategy step is run_once: an invalid map would never be checked again
            raise SdlcError(4, "strategy_amend_refused:%s" % errors[0])
        write_json_atomic(Path(ctx.pkg) / STRATEGY_FILE, amended, within=ctx.pkg)
    return added


# --- command line ------------------------------------------------------------------------------

def cli_strategy(ctx, args, out=None, save_state=None) -> int:
    from . import engine
    from .lock import PackageLock

    capabilities = parse_capabilities(args.capabilities)
    overrides = [parse_override(item) for item in args.set or []]
    with PackageLock(Path(ctx.pkg) / ".lock"):
        fresh = engine.load_context(ctx.project, ctx.root, ctx.state["slug"])
        confirm(fresh, capabilities, overrides)
        outcome = engine.advance(fresh, write=False)
    if out is not None:
        out.write("strategy=confirmed\n")
        out.write(outcome.card)
    return 0


def register_cli(subparsers) -> None:
    parser = subparsers.add_parser(
        "strategy", help="confirm the strategy map: the declared capabilities and any override",
        description="sdlc strategy confirm --capabilities workflow=yes|no|denied,subagent=...,team=... "
                    "[--set <key>=<mechanism>:<reason>]...")
    parser.add_argument("action", choices=("confirm",))
    parser.add_argument("--capabilities", required=True)
    parser.add_argument("--set", action="append", default=None, metavar="KEY=MECHANISM:REASON")
    parser.set_defaults(handler=cli_strategy, needs_ctx=True)
