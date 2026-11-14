"""`next` and `card`: evaluate a flow against the package on disk (contract §8, design §5.6, §5.11).

`advance(ctx, write=True)` is `next`: it stamps the runner-owned frontmatter of the spec and plan,
walks the flow's steps in order, records skips, staleness, completions and step entries in
transitions.jsonl, enforces the caps (visits per step, transitions per run, no progress, fix
rounds) and returns the Outcome whose card the CLI prints. The caller holds the package lock.
`advance(ctx, write=False)` is `card`: the same evaluation on a copy of the state, with the
stamped frontmatter kept in memory (`ctx.overlay`), no log line, no counter saved and no file
written; a cap `next` would hit shows as a `halted` preview card.

Makefile semantics: a done step stays done while the fingerprint of its inputs matches the one
recorded when it was done; a changed input makes it stale and the walk stops there again (a
run_once step is never reopened). A stale step is done again only when its checks pass and its
evidence (the files its checks and outputs name) changed after it went stale. Waiting at a gate or
for an answer and the read-only `card` never count toward the no-progress halt.
"""
from __future__ import annotations

import collections
import copy
import hashlib
import json
import re
from pathlib import Path

from . import card as card_mod
from . import checks, fingerprint, frontmatter, logs, manifest, paths
from . import loop as loop_mod
from . import state as state_mod
from .textio import SdlcError, now_iso, read_text, write_text_atomic

Outcome = collections.namedtuple("Outcome", "state step card exit_code")

TRANSITIONS_LOG = "transitions.jsonl"
SECURITY_STEP = "security"
FRONTMATTER_KEYS = {"spec": ("work_id", "status"), "plan": ("work_id", "spec", "branch", "flow", "status")}
_ECHO_VALUE = re.compile(r"[^\W\d_](?:[^\W\d]|-){0,23}\Z")
# Keys whose change is no state change for `card`'s preview flag (the counter next would bump).
_PREVIEW_IGNORED = ("no_progress",)


class Context:
    """What every runner command works on: project, plugin root, package, state, flow, shared."""

    def __init__(self, project, root, pkg, state, flow, shared):
        self.project = Path(project)
        self.root = Path(root)
        self.pkg = Path(pkg)
        self.state = state
        self.flow = flow
        self.shared = shared
        self.write = True
        self.step = None
        self.overlay = {}
        self.foreign = {}
        self._sets = None

    @property
    def slug(self) -> str:
        return self.state["slug"]

    def flow_step(self, step_id):
        for step in self.flow.get("steps", []):
            if step.get("id") == step_id:
                return step
        return None

    def log(self, record: dict):
        """Append to transitions.jsonl (nothing in `card` mode)."""
        if self.write:
            return logs.append(self.pkg / TRANSITIONS_LOG, record)
        return None

    def caps(self) -> dict:
        return self.shared.get("caps") or {}


def load_context(project, root, slug) -> Context:
    """The Context of package `slug` (state, its flow and the shared policy from `root`)."""
    pkg = paths.package_dir(project, slug)
    st = state_mod.load(pkg)
    flow = manifest.load_flow(root, st["flow"])
    shared = manifest.load_shared(root)
    return Context(project, root, pkg, st, flow, shared)


def default_max_visits(step: dict, caps: dict) -> int:
    if isinstance(step.get("max_visits"), int):
        return step["max_visits"]
    if step.get("id") == manifest.IMPLEMENT_STEP:
        return int(caps.get("implement_max_visits", 5))
    return int(caps.get("max_visits", 3))


def _entry(ctx, step) -> dict:
    steps = ctx.state.setdefault("steps", {})
    if step["id"] not in steps:
        steps[step["id"]] = state_mod.new_step(default_max_visits(step, ctx.caps()))
    return steps[step["id"]]


# --- fingerprints ------------------------------------------------------------------------------

def _digest(pairs) -> str:
    digest = hashlib.sha256()
    for key, value in pairs:
        digest.update(str(key).encode("utf-8", "surrogateescape") + b"\0" + str(value).encode("utf-8") + b"\n")
    return digest.hexdigest()


def start_fp(st: dict) -> str:
    """The `@start` input: the facts fixed at start (form, risk, work type, runtime, options, probes)."""
    facts = {key: st.get(key) for key in ("form", "risk", "work_type", "runtime", "options")}
    probes = st.get("probes") or {}
    facts["probes"] = {key: probes.get(key) for key in ("explore_mode", "deps", "toolchain")}
    return hashlib.sha256(json.dumps(facts, sort_keys=True).encode("utf-8")).hexdigest()


def _set_fps(ctx):
    sets = checks.current_sets(ctx)
    if "error" in sets:
        marker = "error:" + sets["error"]
        return marker, marker
    return sets["source_fp"], sets["tests_fp"]


def _ref_fp(ctx, entry: str):
    """(name, fingerprint) of one inputs/outputs entry."""
    parsed = manifest.parse_ref(entry)
    if parsed["set"] is not None:
        source, tests = _set_fps(ctx)
        if parsed["set"] == "@source":
            return "@source", source
        if parsed["set"] == "@tests":
            return "@tests", tests
        if parsed["set"] == "@diff":
            return "@diff", _digest([("source", source), ("tests", tests)])
        return "@start", start_fp(ctx.state)
    rel = manifest.expand(parsed["path"], ctx.state)
    target = ctx.pkg.joinpath(*rel.split("/"))
    return rel, fingerprint.body_fp(target) if parsed["body"] else fingerprint.file_fp(target)


def step_inputs(ctx, step) -> "collections.OrderedDict":
    """{input name: fingerprint} in manifest order."""
    found = collections.OrderedDict()
    for entry in step.get("inputs") or []:
        name, fp = _ref_fp(ctx, entry)
        found[name] = fp
    return found


def inputs_fp(ctx, step) -> str:
    return _digest(step_inputs(ctx, step).items())


def world_fp(ctx, step) -> str:
    """Inputs and outputs of the current step plus the source and tests sets (contract §5)."""
    pairs = list(step_inputs(ctx, step).items())
    for entry in step.get("outputs") or []:
        pairs.append(_ref_fp(ctx, entry))
    source, tests = _set_fps(ctx)
    pairs += [("@source", source), ("@tests", tests)]
    return _digest(pairs)


def _check_paths(ctx, step) -> list:
    """Package paths named by the step's exists and report checks."""
    found = []
    for spec in step.get("done_when") or []:
        if spec.get("check") in ("exists", "report") and isinstance(spec.get("path"), str):
            found.append(manifest.expand(spec["path"], ctx.state))
    return found


def _evidence_fps(ctx, step) -> dict:
    """{path: fingerprint} of the files a stale step must change before it counts as done again.

    The spec and the plan count by their body: the runner restamps their frontmatter on its own,
    which must never pass for the model redoing the step.
    """
    rels = _check_paths(ctx, step)
    for entry in step.get("outputs") or []:
        parsed = manifest.parse_ref(entry)
        if parsed["path"] is not None and not parsed["optional"]:
            rels.append(manifest.expand(parsed["path"], ctx.state))
    stamped = {checks.artifact_rel(ctx, "spec"), checks.artifact_rel(ctx, "plan")}
    found = {}
    for rel in sorted(set(rels)):
        target = ctx.pkg.joinpath(*rel.split("/"))
        found[rel] = fingerprint.body_fp(target) if rel in stamped else fingerprint.file_fp(target)
    return found


def _report_fps(ctx, step) -> dict:
    found = {}
    for spec in step.get("done_when") or []:
        if spec.get("check") == "report" and isinstance(spec.get("path"), str):
            rel = manifest.expand(spec["path"], ctx.state)
            found[rel] = fingerprint.file_fp(ctx.pkg.joinpath(*rel.split("/")))
    return found


def _referenced(ctx, step) -> set:
    """Every package path the step names (inputs, outputs, check paths, validator/sidecar artifacts)."""
    rels = set(_check_paths(ctx, step))
    for key in ("inputs", "outputs"):
        for entry in step.get(key) or []:
            parsed = manifest.parse_ref(entry)
            if parsed["path"] is not None:
                rels.add(manifest.expand(parsed["path"], ctx.state))
    for spec in step.get("done_when") or []:
        if spec.get("check") == "validator" and spec.get("mode") in ("spec", "plan"):
            rels.add(checks.artifact_rel(ctx, spec["mode"]))
        if spec.get("check") == "sidecar_ok" and spec.get("artifact") in ("spec", "plan"):
            rels.add(checks.artifact_rel(ctx, spec["artifact"]))
    return rels


# --- runner-owned frontmatter ------------------------------------------------------------------

def lifecycle_status(ctx) -> str:
    """The status the runner stamps on the spec and plan (contract §8)."""
    steps = ctx.state.get("steps") or {}
    ids = [step.get("id") for step in ctx.flow.get("steps", [])]

    def done(step_id):
        return steps.get(step_id, {}).get("state") == "done"

    def entered(step_id):
        return steps.get(step_id, {}).get("visits", 0) > 0

    if "claim" in ids and done("claim"):
        return "complete"
    if "audit" in ids and entered("audit"):
        return "ready_for_audit"
    if manifest.IMPLEMENT_STEP in ids and entered(manifest.IMPLEMENT_STEP):
        return "in_progress"
    if any(step.get("gate") and done(step.get("id")) for step in ctx.flow.get("steps", [])):
        return "approved"
    if "draft" in ids and done("draft"):
        return "reviewed"
    return "draft"


def _plan_spec_value(ctx):
    spec = ctx.pkg / "spec" / ("%s.md" % ctx.state["work_id"])
    loop = ctx.state.get("loop") or {}
    if not spec.is_file() and (loop.get("mode") == "bugfix-plan" or ctx.state.get("flow") == "bugfix"):
        return "none"
    return "../spec/%s.md" % ctx.state["work_id"]


def _shown(value: str) -> str:
    return value if _ECHO_VALUE.match(value or "") else "***"


def stamp(ctx) -> None:
    """Write the runner's frontmatter on spec/<id>.md and plan/<id>.md (`card`: into ctx.overlay).

    A status that differs from the one the runner last stamped on that file is foreign: the file is
    left alone and ctx.foreign names it, which fails every check of a step that reads it. A file
    `start` imported (the plan flow's approved spec) keeps the status it was imported with.
    """
    status = lifecycle_status(ctx)
    branch = None
    imported = ctx.state.get("imported") or []
    for kind in ("spec", "plan"):
        rel = checks.artifact_rel(ctx, kind)
        path = ctx.pkg.joinpath(*rel.split("/"))
        if not path.is_file():
            continue
        try:
            text = read_text(path)
        except SdlcError:
            ctx.foreign[rel] = "not-utf8"
            continue
        except OSError:
            ctx.foreign[rel] = "unreadable"
            continue
        meta, body, _had = frontmatter.split(text)
        stamped = (ctx.state.get("stamps") or {}).get(rel)
        found = meta.get("status")
        if (stamped is not None and found and found != stamped) or (rel in imported and found != stamped):
            ctx.foreign[rel] = _shown(found or "none")
            continue
        if rel in imported:
            continue
        wanted = collections.OrderedDict([("work_id", ctx.state["work_id"])])
        if kind == "plan":
            if branch is None:
                branch = checks.current_branch(ctx) or ctx.state.get("base_branch") or "none"
            spec_value = _plan_spec_value(ctx)
            wanted["spec"] = spec_value
            wanted["branch"] = branch
            wanted["flow"] = "bugfix" if spec_value == "none" else ctx.state["flow"]
        wanted["status"] = status
        merged = collections.OrderedDict(wanted)
        for key, value in meta.items():
            if key not in merged:
                merged[key] = value
        try:
            new_text = frontmatter.render(merged, body)
        except ValueError:
            ctx.foreign[rel] = "unstampable"
            continue
        if new_text != text:
            if ctx.write:
                write_text_atomic(path, new_text, within=ctx.pkg)
            else:
                ctx.overlay[rel] = new_text
        ctx.state.setdefault("stamps", {})[rel] = status


# --- steps -------------------------------------------------------------------------------------

def applies(ctx, step):
    """(applies, reason when not): design §5.6; a probe error means "applies"."""
    cond = step.get("applies_when")
    if not cond:
        return True, None
    st = ctx.state
    reasons = []
    if "form" in cond and st.get("form") != cond["form"]:
        reasons.append("applies_when form=%s (the form is %s)" % (cond["form"], st.get("form")))
    if "option" in cond and cond["option"] not in (st.get("options") or []):
        reasons.append("applies_when option=%s (not given at start)" % cond["option"])
    if "work_type" in cond and st.get("work_type") not in cond["work_type"]:
        reasons.append("applies_when work_type in %s (the work type is %s)"
                       % (",".join(cond["work_type"]), st.get("work_type")))
    if "probe" in cond:
        value = (st.get("probes") or {}).get(cond["probe"])
        if value not in (None, "error") and value == cond.get("not"):
            reasons.append("applies_when probe %s is not %s (it is %s)" % (cond["probe"], cond["not"], value))
    return (not reasons), ("; ".join(reasons) or None)


def _run_checks(ctx, step) -> list:
    """[(check name, CheckResult)]; a foreign frontmatter status adds a failing `frontmatter` entry."""
    ctx.step = step
    results = []
    problems = sorted(rel for rel in _referenced(ctx, step) if rel in ctx.foreign)
    for rel in problems:
        results.append(("frontmatter", checks.CheckResult(
            False, "foreign_status:%s:%s (the runner owns the status; restore the value it wrote)"
            % (rel, ctx.foreign[rel]))))
    for spec in step.get("done_when") or []:
        results.append((str(spec.get("check")), checks.run_check(ctx, spec, step)))
    return results


def _changed_input(entry, current) -> object:
    old = entry.get("done_inputs")
    if not isinstance(old, dict):
        return None if entry.get("done_fp") == _digest(current.items()) else "inputs"
    for name, fp in current.items():
        if old.get(name) != fp:
            return name
    for name in old:
        if name not in current:
            return name
    return None


def _mark_stale(ctx, step, entry, changed, cause="stale"):
    entry["state"] = "stale"
    entry["stale_cause"] = changed
    entry["reenter"] = cause
    entry["stale_fps"] = _evidence_fps(ctx, step)
    ctx.log({"kind": "stale", "step": step["id"], "input": changed})


def _evidence_newer(ctx, step, entry) -> bool:
    before = entry.get("stale_fps") or {}
    now = _evidence_fps(ctx, step)
    if not now:
        return True
    return any(before.get(rel) != fp for rel, fp in now.items())


def mark_done(ctx, step, entry, cause=None) -> None:
    current = step_inputs(ctx, step)
    entry["state"] = "done"
    entry["done_fp"] = _digest(current.items())
    entry["done_inputs"] = dict(current)
    for key in ("reenter", "stale_fps", "stale_cause"):
        entry.pop(key, None)
    waiting = ctx.state.get("waiting")
    if isinstance(waiting, dict) and waiting.get("kind") == "gate" and waiting.get("id") == step.get("gate"):
        ctx.state["waiting"] = None
    record = {"kind": "done", "step": step["id"], "fp": entry["done_fp"]}
    if cause:
        record["cause"] = cause
    ctx.log(record)


def _security_review(ctx, step):
    """(fingerprint, passing) of the security report when one with its header exists, else None."""
    for spec in step.get("done_when") or []:
        if spec.get("check") != "report":
            continue
        rel = manifest.expand(spec["path"], ctx.state)
        target = ctx.pkg.joinpath(*rel.split("/"))
        try:
            lines = [line.strip() for line in read_text(target).splitlines()]
        except (OSError, SdlcError):
            return None
        if spec.get("header", "").strip() not in lines:
            return None
        verdict = spec.get("verdict")
        passing = verdict is None or any(verdict in line for line in lines)
        return fingerprint.file_fp(target), passing
    return None


# --- the walk ----------------------------------------------------------------------------------

def _preview_changed(original: dict, now: dict) -> bool:
    strip = lambda st: {k: v for k, v in st.items() if k not in _PREVIEW_IGNORED}  # noqa: E731
    return strip(original) != strip(now)


def _finish(ctx, original, kind, step, extra, code) -> Outcome:
    if ctx.write:
        if ctx.state != original:
            state_mod.save(ctx.pkg, ctx.state)
    else:
        extra = dict(extra or {})
        extra["preview"] = bool(ctx.overlay) or _preview_changed(original, ctx.state)
    return Outcome(kind, step["id"] if step else None, card_mod.render(ctx, kind, step, extra), code)


def halt(ctx, original, reason: str, step, by: str = "runner") -> Outcome:
    ctx.state["status"] = "halted"
    ctx.state["halt"] = {"reason": reason, "step": step["id"] if step else None, "by": by, "ts": now_iso()}
    ctx.state["waiting"] = None
    ctx.log({"kind": "halt", "step": step["id"] if step else None, "reason": reason, "by": by})
    return _finish(ctx, original, "halted", step, {}, 3)


def advance(ctx, write: bool) -> Outcome:
    """`next` (write=True, caller holds the lock) or `card` (write=False: nothing is written)."""
    if not write:
        ctx = Context(ctx.project, ctx.root, ctx.pkg, copy.deepcopy(ctx.state), ctx.flow, ctx.shared)
    ctx.write = write
    ctx.overlay, ctx.foreign, ctx._sets = {}, {}, None
    original = copy.deepcopy(ctx.state)
    st = ctx.state
    if st["status"] in state_mod.TERMINAL:
        return _finish(ctx, original, st["status"], None, {}, 0)
    if st["status"] == "halted":
        step = ctx.flow_step((st.get("halt") or {}).get("step"))
        return _finish(ctx, original, "halted", step, {}, 3)
    stamp(ctx)
    caps = ctx.caps()
    for step in ctx.flow["steps"]:
        sid = step["id"]
        entry = _entry(ctx, step)
        ctx.step = step
        if entry.get("applies") is None:
            does, reason = applies(ctx, step)
            entry["applies"] = does
            entry["skip_reason"] = reason
        if not entry["applies"]:
            if entry["state"] != "skipped":
                entry["state"] = "skipped"
                ctx.log({"kind": "skip", "step": sid, "reason": entry["skip_reason"]})
            continue
        if entry["state"] == "done":
            if step.get("run_once"):
                continue
            changed = _changed_input(entry, step_inputs(ctx, step))
            if changed is None:
                continue
            _mark_stale(ctx, step, entry, changed)
        results = _run_checks(ctx, step)
        passed = all(result.ok for _name, result in results)
        if passed and entry["state"] == "stale" and not _evidence_newer(ctx, step, entry):
            passed = False
            results.append(("stale", checks.CheckResult(
                False, "the step went stale (%s changed) and its outputs were not changed after that"
                % entry.get("stale_cause"))))
        if passed:
            if sid == SECURITY_STEP and entry.pop("review_fp", None) is not None:
                st["fix_rounds"] = st.get("fix_rounds", 0) + 1  # the re-review that passed
            mark_done(ctx, step, entry)
            continue
        return _current(ctx, original, step, entry, results, caps)
    st["status"] = "complete"
    st["current"] = None
    st["waiting"] = None
    ctx.log({"kind": "complete"})
    stamp(ctx)
    return _finish(ctx, original, "complete", None, {}, 0)


def _current(ctx, original, step, entry, results, caps) -> Outcome:
    """`step` is the first step that is not done: enter it, wait at it, or print its card.

    The caps run in `card` mode too (on the copy, with nothing logged or saved), so `card` shows
    the halt `next` would make.
    """
    st = ctx.state
    sid = step["id"]
    entering = st.get("current") != sid or bool(entry.get("reenter")) or entry.get("visits", 0) == 0
    if entering:
        cause = entry.get("reenter") or ("first" if entry.get("visits", 0) == 0 else "return")
        if entry["visits"] + 1 > entry["max_visits"]:
            return halt(ctx, original, "loop cap reached: %s" % sid, step)
        if st["transitions"] + 1 > st["transition_cap"]:
            return halt(ctx, original, "transition cap reached", step)
        if sid == SECURITY_STEP and cause == "stale":
            st["fix_rounds"] = st.get("fix_rounds", 0) + 1
            if st["fix_rounds"] > st.get("fix_round_cap", caps.get("fix_rounds", 3)):
                return halt(ctx, original, "fix-round cap reached: %s" % sid, step)
        entry.pop("reenter", None)
        entry["visits"] += 1
        st["transitions"] += 1
        entry["visit_started"] = now_iso()
        entry["visit_cause"] = cause
        entry["visit_fps"] = _report_fps(ctx, step)
        entry.pop("review_fp", None)
        st["current"] = sid
        st["waiting"] = None
        st["no_progress"] = {"step": sid, "world": world_fp(ctx, step), "count": 1}
        ctx.log({"kind": "enter", "step": sid, "visit": entry["visits"], "cause": cause})
    foreign = [name for name, result in results if name == "frontmatter" and not result.ok]
    if step.get("gate") and not foreign:
        fingerprint_now = checks.gate_fingerprint(ctx, step)
        waiting = st.get("waiting") or {}
        if not (waiting.get("kind") == "gate" and waiting.get("id") == step["gate"]
                and waiting.get("fingerprint") == fingerprint_now):
            st["waiting"] = {"kind": "gate", "id": step["gate"], "fingerprint": fingerprint_now, "since": now_iso()}
            ctx.log({"kind": "wait", "wait": "gate", "gate": step["gate"], "fingerprint": fingerprint_now})
        return _finish(ctx, original, "wait-gate", step, {"fingerprint": fingerprint_now}, 0)
    waiting = st.get("waiting")
    if isinstance(waiting, dict) and waiting.get("kind") == "answer":
        return _finish(ctx, original, "wait-answer", step, {}, 0)
    if not entering:
        world = world_fp(ctx, step)
        progress = st.get("no_progress") or {}
        if progress.get("step") == sid and progress.get("world") == world:
            progress = {"step": sid, "world": world, "count": int(progress.get("count", 0)) + 1}
        else:
            progress = {"step": sid, "world": world, "count": 1}
        st["no_progress"] = progress
        if progress["count"] >= int(caps.get("no_progress_k", 3)):
            return halt(ctx, original, "no progress: %s" % sid, step)
    if sid == SECURITY_STEP:
        review = _security_review(ctx, step)
        if review is not None and not review[1]:
            seen = entry.get("review_fp")
            if seen is not None and seen != review[0]:
                st["fix_rounds"] = st.get("fix_rounds", 0) + 1  # a re-review that failed again
                if st["fix_rounds"] > st.get("fix_round_cap", caps.get("fix_rounds", 3)):
                    return halt(ctx, original, "fix-round cap reached: %s" % sid, step)
            entry["review_fp"] = review[0]
    # loop delegation point: plan Task 8 makes loop.next_role print the role card of a loop step.
    if step.get("loop"):
        role = loop_mod.next_role(ctx, step, ctx.write)
        if role is not None:
            return role
    return _finish(ctx, original, "do", step, {"results": results, "entering": entering}, 0)
