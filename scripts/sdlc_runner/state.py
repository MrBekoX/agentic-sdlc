"""The work package's state.json (contract §3, schema `agentic-sdlc/state@1`) and active-package lookup.

The runner is the only writer of state.json. A file it cannot read as a state object is
SdlcError(2, "state_corrupt"); transitions.jsonl is the audit trail, never a source to rebuild
from. Writes go through textio.write_json_atomic inside the package folder.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path

from . import RUNNER_VERSION
from .paths import AGENTIC_ROOT, package_dir, valid_slug
from .textio import SdlcError, now_iso, read_json, write_json_atomic

SCHEMA = "agentic-sdlc/state@1"
STATE_FILE = "state.json"
STATUSES = ("active", "complete", "halted", "abandoned")
TERMINAL = ("complete", "abandoned")
STEP_STATES = ("pending", "done", "stale", "skipped")


def _defaults() -> dict:
    return {
        "schema": SCHEMA,
        "runner_version": RUNNER_VERSION,
        "flow": None, "form": None, "risk": None, "risk_reason": None,
        "work_type": None, "work_id": None, "slug": None,
        "options": [], "runtime": None,
        "created": now_iso(),
        "base_commit": None, "base_branch": None,
        "git": {"repo": False, "writable": False, "unborn": False},
        "branch_policy": "work", "branch_policy_quote": None,
        "manifest_sha256": None, "request_sha256": None,
        "status": "active", "halt": None,
        "current": None, "waiting": None,
        "transitions": 0, "transition_cap": 60,
        "no_progress": {"step": None, "world": None, "count": 0},
        "steps": {},
        "loop": None,
        "fix_rounds": 0, "fix_round_cap": 3,
        "degraded": [],
        "red": {"recorded": False, "order": None},
        "appended_tasks": [],
        "probes": {},
        "stamps": {},
        "imported": [],
        "gate_order": None,
    }


def new_state(**facts) -> dict:
    """A fresh state with the contract §3 keys; `facts` override the defaults (unknown key: ValueError)."""
    state = _defaults()
    unknown = sorted(set(facts) - set(state))
    if unknown:
        raise ValueError("unknown state keys: %s" % ", ".join(unknown))
    for key, value in facts.items():
        state[key] = copy.deepcopy(value)
    return state


def new_step(max_visits: int) -> dict:
    """The entry of one step before it is first reached."""
    return {"state": "pending", "visits": 0, "max_visits": max_visits, "done_fp": None, "applies": None,
            "skip_reason": None, "visit_started": None, "visit_cause": None}


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_step(entry) -> bool:
    return (isinstance(entry, dict) and entry.get("state") in STEP_STATES
            and _is_int(entry.get("visits")) and _is_int(entry.get("max_visits")))


def _is_state(obj) -> bool:
    """The shape the engine relies on: a file that parses but lost a counter is corrupt, not a crash."""
    return (isinstance(obj, dict) and obj.get("schema") == SCHEMA and obj.get("status") in STATUSES
            and all(isinstance(obj.get(key), str) for key in ("flow", "slug", "work_id", "form", "risk", "work_type"))
            and all(_is_int(obj.get(key)) for key in ("transitions", "transition_cap", "fix_rounds"))
            and isinstance(obj.get("steps"), dict) and all(_is_step(v) for v in obj["steps"].values())
            and isinstance(obj.get("options"), list) and isinstance(obj.get("red"), dict)
            and isinstance(obj.get("no_progress"), dict) and isinstance(obj.get("stamps", {}), dict)
            and (obj.get("waiting") is None or isinstance(obj.get("waiting"), dict)))


def load(pkg) -> dict:
    """The package's state; SdlcError(2, "state_missing:<slug>") or (2, "state_corrupt")."""
    path = Path(pkg) / STATE_FILE
    try:
        obj = read_json(path)
    except (FileNotFoundError, NotADirectoryError):
        raise SdlcError(2, "state_missing:" + Path(pkg).name) from None
    except (OSError, ValueError, SdlcError):
        raise SdlcError(2, "state_corrupt") from None
    if not _is_state(obj):
        raise SdlcError(2, "state_corrupt")
    return obj


def save(pkg, st) -> None:
    write_json_atomic(Path(pkg) / STATE_FILE, st, within=pkg)


def red_saver(pkg):
    """The `save_state` runexec.execute calls while it holds the package lock after a run: it
    re-reads state.json (the lock was released while the child ran) and merges only `red`."""
    def save_red(snapshot: dict) -> None:
        current = load(pkg)
        current["red"] = copy.deepcopy(snapshot.get("red"))
        save(pkg, current)
    return save_red


def _package_root(project) -> Path:
    return Path(project).joinpath(*AGENTIC_ROOT.split("/"))


def find_active(project) -> list:
    """Sorted slugs of the packages whose state is not terminal (a corrupt state counts, so the
    user sees it instead of a silent `no active flow`)."""
    root = _package_root(project)
    try:
        names = sorted(os.listdir(str(root)))
    except OSError:
        return []
    found = []
    for name in names:
        if not valid_slug(name) or not (root / name / STATE_FILE).is_file():
            continue
        try:
            status = load(package_dir(project, name)).get("status")
        except SdlcError:
            status = None
        if status not in TERMINAL:
            found.append(name)
    return found


def resolve_slug(project, slug) -> str:
    """The package to act on: `slug` when given (it must hold a state.json), else the one active
    package. SdlcError(2, ...): bad_slug, no_package:<slug>, no_active_flow, several_active:<a,b>."""
    if slug is not None:
        pkg = package_dir(project, slug)  # bad_slug / linked_package_path
        if not (pkg / STATE_FILE).is_file():
            raise SdlcError(2, "no_package:" + slug)
        return slug
    active = find_active(project)
    if not active:
        raise SdlcError(2, "no_active_flow")
    if len(active) > 1:
        raise SdlcError(2, "several_active:" + ",".join(active))
    return active[0]
