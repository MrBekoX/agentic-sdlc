"""The strategy step (contract §9, design §5.7). STUB until plan Task 6 replaces this module.

What the stub already does, so plan Task 5's engine can run a flow end to end:
- `validate` checks strategy.json against flows/schemas/strategy.schema.json and the runtime
  recorded at `start`; the coverage, override-reason, capability and mandated-fresh rules of
  `strategy_ok` arrive with Task 6.
- `resolve` reads the mechanism a card prints from strategy.json (`unset` without one).
- `default_map` writes no rule table yet: strategy.default.json says so.
- `register_cli` registers `strategy ...`, whose handler raises SdlcError(2, "not_built:strategy")
  whatever arguments it gets (`accepts_extra`).
"""
from __future__ import annotations

from pathlib import Path

from . import manifest, schema
from .textio import SdlcError, read_json

STRATEGY_FILE = "strategy.json"
DEFAULT_FILE = "strategy.default.json"


def default_map(flow, shared, probes, runtime, options) -> dict:
    """strategy.default.json before the rule table exists (plan Task 6)."""
    return {"runtime": runtime, "flow": flow.get("id"), "entries": {}, "rule_table": "not_built"}


def validate(strategy_map, flow, state) -> list:
    """Errors for strategy.json (an empty list means strategy_ok). Stub rules: schema and runtime."""
    errors = schema.validate(strategy_map, manifest.load_schema("strategy"))
    if not errors and strategy_map.get("runtime") != state.get("runtime"):
        errors.append("/runtime: %r, but the flow started with --runtime %r"
                      % (strategy_map.get("runtime"), state.get("runtime")))
    return errors


def load_map(pkg):
    """strategy.json of the package, or None when it is missing or unreadable."""
    try:
        data = read_json(Path(pkg) / STRATEGY_FILE)
    except (OSError, ValueError, SdlcError):
        return None
    return data if isinstance(data, dict) else None


def resolve(ctx, key) -> tuple:
    """(mechanism, degraded text) of `key` from strategy.json: ("unset", "none") without an entry."""
    data = load_map(ctx.pkg)
    entries = data.get("entries") if isinstance(data, dict) else None
    entry = entries.get(key) if isinstance(entries, dict) else None
    mechanism = entry.get("mechanism") if isinstance(entry, dict) else None
    degraded = "none"
    for item in (data.get("degraded") or []) if isinstance(data, dict) else []:
        if isinstance(item, dict) and item.get("key") == key:
            degraded = "%s:%s" % (item.get("capability"), item.get("reason"))
            break
    return (mechanism if isinstance(mechanism, str) else "unset"), degraded


def _not_built(*_args, **_kwargs):
    raise SdlcError(2, "not_built:strategy")


def register_cli(subparsers) -> None:
    parser = subparsers.add_parser("strategy", help="confirm the strategy map (not built yet: plan Task 6)")
    parser.set_defaults(handler=_not_built, accepts_extra=True)
