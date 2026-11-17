"""Flow operations: start, halt, resume, abandon, escalate, external (design §5.3, §5.5, §5.11).

Each function takes the parsed argparse namespace with three attributes cli.py adds: `out` (the
stream to print to), `root` (the plugin root the flows are read from) and `project` (the project
root). It prints a card and returns the exit code (`start`: the first card's; `halt`: 3; the others
0 once the change is recorded, their card a preview of the next `next`); a refusal raises
SdlcError(4, ...), a usage or state error SdlcError(2, ...). Every state change happens under the package lock and is logged in
transitions.jsonl; quotes and reasons are masked before they are stored.
"""
from __future__ import annotations

import copy
import hashlib
import re
import types
from pathlib import Path

from . import RUNNER_VERSION, engine, fingerprint, frontmatter, gitinfo, logs, manifest, mask, paths, probes
from . import runexec
from . import state as state_mod
from . import strategy as strategy_mod
from .lock import PackageLock
from .textio import SdlcError, now_iso, read_text, write_json_atomic, write_text_atomic

_OWNER_RE = re.compile(r"[a-z0-9][a-z0-9-]*:[a-z0-9][a-z0-9-]*\Z")
EXTERNAL_STEPS = ("intent", "draft")
LEXICON_WORD = r"[^\W_]"
SPEC_STEP = "spec"
SPEC_OPTION = "spec"


def _masked(text) -> str:
    return mask.mask_text(str(text or "")).strip()


def _quote_needed(value, name: str) -> str:
    text = (value or "").strip()
    if not text:
        raise SdlcError(4, "%s_needs_quote" % name)
    return _masked(text)


def risk_matches(text: str, lexicon: dict) -> list:
    """[(surface, term)] of the risk lexicon terms the text holds as whole words (case-folded)."""
    folded = text.casefold()
    found = []
    for surface, terms in lexicon.items():
        for term in terms:
            words = [re.escape(word) for word in term.casefold().split()]
            pattern = r"(?<!%s)%s(?!%s)" % (LEXICON_WORD, r"\s+".join(words), LEXICON_WORD)
            if words and re.search(pattern, folded):
                found.append((surface, term))
                break
    return found


def _manifest_sha(root, flow: dict) -> str:
    digest = hashlib.sha256()
    names = ["flows/%s.json" % flow["id"], "flows/_shared.json"]
    names += ["flows/loops/%s.json" % step["loop"] for step in flow["steps"] if step.get("loop")]
    for rel in names:
        try:
            digest.update(Path(root).joinpath(*rel.split("/")).read_bytes())
        except OSError:
            digest.update(b"missing:" + rel.encode("utf-8"))
    return digest.hexdigest()


def _loop_state(root, flow: dict, shared: dict):
    loop_steps = [step for step in flow["steps"] if step.get("loop")]
    if not loop_steps:
        return None
    definition = manifest.load_loop(root, loop_steps[0]["loop"])
    return {"mode": flow.get("loop_mode"), "engine": None, "round": 0, "role": None, "role_visits": 0,
            "max_rounds": definition["caps"]["max_rounds"], "last_issue_keys": [], "stop_reason": None}


def _steps(flow: dict, shared: dict) -> dict:
    caps = shared.get("caps") or {}
    return {step["id"]: state_mod.new_step(engine.default_max_visits(step, caps)) for step in flow["steps"]}


def _print(args, text: str) -> None:
    args.out.write(text)


def _lattice_or_error(root, shared) -> None:
    errors = manifest.validate_lattice(root, shared)
    if errors:
        raise SdlcError(2, "manifest_invalid:flows/_shared.json: %s" % errors[0])


# --- start -------------------------------------------------------------------------------------

def _imports(args, flow: dict, st_facts: dict, start_state: dict) -> list:
    """[(package path, text, status)] for the flow's `imports`; refusal when a source's status differs.

    An import with `"required": false` whose option was not given is left out, unless a step that
    applies under `start_state` (the facts `start` is about to write) reads its path as a required
    input: that step could never run, so `start` refuses it as it refuses a missing required import.
    """
    found, left_out = [], []
    for item in flow.get("imports") or []:
        option = item["option"]
        source = getattr(args, option.lstrip("-").replace("-", "_"), None)
        if not source:
            if item.get("required", True):
                raise SdlcError(2, "import_missing:" + option)
            left_out.append(item)
            continue
        try:
            text = read_text(source)
        except OSError:
            raise SdlcError(2, "import_unreadable:" + option) from None
        status = frontmatter.split(text)[0].get("status")
        if status != item["status"]:
            raise SdlcError(4, "import_status:%s:%s (needs %s)" % (option, status or "none", item["status"]))
        found.append((manifest.expand(item["path"], st_facts), text, status))
    state = dict(start_state, imported=[rel for rel, _text, _status in found])
    for item in left_out:
        for step in flow["steps"]:
            if _reads_required(step, item["path"]) and engine.applies(types.SimpleNamespace(state=state), step)[0]:
                raise SdlcError(2, "import_missing:" + item["option"])
    return found


def _reads_required(step: dict, path: str) -> bool:
    """Whether `step` lists the package path `path` as a required input (`#body` allowed, `?` not)."""
    for ref in step.get("inputs") or []:
        parsed = manifest.parse_ref(ref)
        if parsed["path"] == path and not parsed["optional"]:
            return True
    return False


def start(args) -> int:
    root, project = args.root, args.project
    flow = manifest.load_flow(root, args.flow)
    shared = manifest.load_shared(root)
    if not paths.valid_work_id(args.work_id):
        raise SdlcError(2, "bad_work_id")
    slug = args.slug or paths.slug_from_work_id(args.work_id)
    if args.form == "light":
        if flow["id"] == "full":
            raise SdlcError(4, "light_refused:full")
        if args.risk == "high":
            raise SdlcError(4, "light_refused:risk_high")
    if args.form not in flow["forms"]:
        raise SdlcError(4, "form_not_in_flow:%s:%s" % (args.form, flow["id"]))
    if args.work_type not in flow["work_types"]:
        raise SdlcError(4, "work_type_not_in_flow:%s:%s" % (args.work_type, ",".join(flow["work_types"])))
    try:
        request = read_text(args.request_file)
    except OSError:
        raise SdlcError(2, "request_unreadable") from None
    if not request.strip():
        raise SdlcError(2, "request_empty")
    risk_reason = (args.risk_reason or "").strip() or None
    matches = risk_matches(request, shared.get("risk_lexicon") or {})
    if matches and args.risk == "normal" and risk_reason is None:
        raise SdlcError(4, "risk_reason_required:%s:%s" % matches[0])
    quote = (args.quote or "").strip() or None
    if args.branch_policy == "stay" and quote is None:
        raise SdlcError(4, "branch_policy_stay_needs_quote")
    _lattice_or_error(root, shared)
    options = []
    for option in args.option or []:
        if option not in options:
            options.append(option)
    found = probes.start_probes(project)
    start_probes = {key: found.get(key) for key in ("explore_mode", "deps", "toolchain", "errors")}
    imports = _imports(args, flow, {"work_id": args.work_id},
                       {"form": args.form, "work_type": args.work_type, "options": options, "probes": start_probes})
    pkg = paths.package_dir(project, slug)
    _refuse_existing(pkg, slug)
    pkg.mkdir(parents=True, exist_ok=True)
    with PackageLock(pkg / ".lock"):
        _refuse_existing(pkg, slug)
        git = found.get("git") or {}
        head = git.get("head") if git.get("repo") and not git.get("unborn") else None
        if head:
            dirty = {name: fingerprint.file_fp(Path(project).joinpath(*name.split("/")))
                     for name in gitinfo.changed_paths(project, head)}
            snapshot = None
        else:
            dirty, snapshot = None, fingerprint.walk_snapshot(project)
        masked_request = mask.mask_text(request)
        if not masked_request.endswith("\n"):
            masked_request += "\n"
        write_text_atomic(pkg / "request.md", masked_request, within=pkg)
        if dirty is not None:
            write_json_atomic(pkg / runexec.DIRTY_FILE, dirty, within=pkg)
        else:
            write_json_atomic(pkg / "baseline.json", snapshot, within=pkg)
        for rel, text, _status in imports:
            write_text_atomic(pkg.joinpath(*rel.split("/")), text, within=pkg)
        caps = shared.get("caps") or {}
        st = state_mod.new_state(
            flow=flow["id"], form=args.form, risk=args.risk, risk_reason=_masked(risk_reason) if risk_reason else None,
            work_type=args.work_type, work_id=args.work_id, slug=slug, options=options, runtime=args.runtime,
            base_commit=head, base_branch=git.get("branch"),
            git={"repo": bool(git.get("repo")), "writable": bool(git.get("writable")), "unborn": bool(git.get("unborn"))},
            branch_policy=args.branch_policy, branch_policy_quote=_masked(quote) if quote else None,
            manifest_sha256=_manifest_sha(root, flow),
            request_sha256=hashlib.sha256(masked_request.encode("utf-8")).hexdigest(),
            transition_cap=int(caps.get("transition_cap", 60)), fix_round_cap=int(caps.get("fix_rounds", 3)),
            steps=_steps(flow, shared), loop=_loop_state(root, flow, shared),
            probes=start_probes,
            imported=[rel for rel, _text, _status in imports],
            stamps={rel: status for rel, _text, status in imports},
        )
        state_mod.save(pkg, st)
        logs.append(pkg / engine.TRANSITIONS_LOG, {
            "kind": "start", "flow": flow["id"], "work_id": args.work_id, "slug": slug, "form": args.form,
            "risk": args.risk, "risk_reason": st["risk_reason"], "risk_matches": [s for s, _t in matches],
            "work_type": args.work_type, "runtime": args.runtime, "options": options,
            "base_commit": head, "git": st["git"], "manifest_sha256": st["manifest_sha256"],
            "request_sha256": st["request_sha256"], "runner_version": RUNNER_VERSION,
        })
        write_json_atomic(pkg / strategy_mod.DEFAULT_FILE,
                          strategy_mod.default_map(flow, shared, st["probes"], args.runtime, options,
                                                   form=args.form, work_type=args.work_type,
                                                   imported=st["imported"]), within=pkg)
        ctx = engine.Context(project, root, pkg, st, flow, shared)
        outcome = engine.advance(ctx, write=True)
    _print(args, outcome.card)
    return outcome.exit_code


def _refuse_existing(pkg: Path, slug: str) -> None:
    if not (pkg / state_mod.STATE_FILE).exists():
        return
    st = state_mod.load(pkg)
    if st["status"] not in state_mod.TERMINAL:
        raise SdlcError(4, "active_flow_on_slug:%s:%s" % (slug, st["flow"]))
    raise SdlcError(4, "package_finished:%s:%s (start a new work id)" % (slug, st["status"]))


# --- halt / resume / abandon -------------------------------------------------------------------

def _locked(args):
    slug = state_mod.resolve_slug(args.project, args.slug)
    pkg = paths.package_dir(args.project, slug)
    return pkg, PackageLock(pkg / ".lock")


def halt(args) -> int:
    pkg, held = _locked(args)
    with held:
        ctx = engine.load_context(args.project, args.root, pkg.name)
        status = ctx.state["status"]
        if status != "active":
            raise SdlcError(4, "not_active:" + status)
        original = copy.deepcopy(ctx.state)
        outcome = engine.halt(ctx, original, _masked(args.reason), ctx.flow_step(ctx.state.get("current")), by="user")
    _print(args, outcome.card)
    return outcome.exit_code


def resume(args) -> int:
    pkg, held = _locked(args)
    with held:
        ctx = engine.load_context(args.project, args.root, pkg.name)
        st = ctx.state
        if st["status"] != "halted":
            raise SdlcError(4, "not_halted:" + st["status"])
        record = {"kind": "resume", "raise_cap": None, "quote": None}
        if args.raise_cap:
            caps = ctx.caps()
            if args.raise_cap == "transitions":
                quote = _quote_needed(args.quote, "raise_cap")
                st["transition_cap"] += int(caps.get("transition_cap", 60))
            elif args.raise_cap == "fix-rounds":
                quote = _quote_needed(args.quote, "raise_cap")
                st["fix_round_cap"] = st.get("fix_round_cap", 3) + int(caps.get("fix_rounds", 3))
            else:
                step = ctx.flow_step(args.raise_cap)
                if step is None:
                    raise SdlcError(2, "unknown_step:" + args.raise_cap)
                quote = _quote_needed(args.quote, "raise_cap")
                entry = st["steps"].setdefault(step["id"], state_mod.new_step(engine.default_max_visits(step, caps)))
                entry["max_visits"] += engine.default_max_visits(step, caps)
            record.update({"raise_cap": args.raise_cap, "quote": quote})
        st["status"] = "active"
        st["halt"] = None
        st["no_progress"] = {"step": None, "world": None, "count": 0}
        ctx.log(record)
        state_mod.save(pkg, st)
        outcome = engine.advance(ctx, write=False)
    _print(args, outcome.card)
    return 0  # the operation succeeded; the card previews what `next` does now (a halt included)


def abandon(args) -> int:
    pkg, held = _locked(args)
    with held:
        ctx = engine.load_context(args.project, args.root, pkg.name)
        st = ctx.state
        if st["status"] in state_mod.TERMINAL:
            raise SdlcError(4, "not_active:" + st["status"])
        quote = _quote_needed(args.quote, "abandon")
        st["status"] = "abandoned"
        st["waiting"] = None
        ctx.log({"kind": "abandon", "quote": quote, "step": st.get("current")})
        state_mod.save(pkg, st)
        outcome = engine.advance(ctx, write=False)
    _print(args, outcome.card)
    return 0  # the operation succeeded; the card previews what `next` does now (a halt included)


# --- escalate ----------------------------------------------------------------------------------

def _changed_since_start(ctx) -> list:
    try:
        sets = runexec.current_sets(ctx)
        return runexec._since_start(ctx, sets["source"])
    except SdlcError:
        return []


def _escalated_options(st: dict) -> list:
    """The start options the escalated run keeps: its own, plus `spec` when its spec step is done.

    Hybrid design §5: a spec run escalated to feature keeps its approved spec, its check and its gate
    instead of re-deciding them as skipped (the feature flow writes a spec only under `--option spec`).
    """
    options = list(st.get("options") or [])
    spec = (st.get("steps") or {}).get(SPEC_STEP) or {}
    if spec.get("state") == "done" and SPEC_OPTION not in options:
        options.append(SPEC_OPTION)
    return options


def _names_option(step: dict, option: str) -> bool:
    """Whether `step` applies or not by `option` (applies_when option or not_option)."""
    cond = step.get("applies_when") or {}
    return option in (cond.get("option"), cond.get("not_option"))


def escalate(args) -> int:
    pkg, held = _locked(args)
    with held:
        ctx = engine.load_context(args.project, args.root, pkg.name)
        st = ctx.state
        if st["status"] != "active":
            raise SdlcError(4, "not_active:" + st["status"])
        _lattice_or_error(ctx.root, ctx.shared)
        source_id, target_id = st["flow"], args.flow
        raises_form = args.form == "gated" and st["form"] == "light"
        raises_risk = args.risk == "high" and st["risk"] != "high"
        if target_id == source_id:
            if not (raises_form or raises_risk):
                raise SdlcError(4, "escalate_sideways:%s" % source_id)
            edge = {"work_type": "keep"}
        else:
            edges = [e for e in ctx.shared.get("escalation") or [] if e.get("from") == source_id and e.get("to") == target_id]
            if not edges:
                raise SdlcError(4, "escalate_not_upward:%s->%s" % (source_id, target_id))
            edge = edges[0]
        target = manifest.load_flow(ctx.root, target_id)
        form = "gated" if args.form == "gated" else st["form"]
        risk = "high" if args.risk == "high" else st["risk"]
        if form == "light" and (target_id == "full" or "light" not in target["forms"]):
            raise SdlcError(4, "light_refused:%s (pass --form gated)" % target_id)
        if form == "light" and risk == "high":
            raise SdlcError(4, "light_refused:risk_high (pass --form gated)")
        work_type = st["work_type"] if edge.get("work_type") == "keep" else edge["work_type"]
        if work_type not in target["work_types"]:
            raise SdlcError(4, "work_type_not_in_flow:%s:%s" % (work_type, target_id))
        old_steps = {step["id"]: step for step in ctx.flow["steps"]}
        caps = ctx.caps()
        changed_source = _changed_since_start(ctx)
        options = _escalated_options(st)
        options_changed = options != list(st.get("options") or [])
        new_entries, added = {}, []
        for step in target["steps"]:
            entry = st["steps"].get(step["id"])
            if entry is None:
                added.append(step)
                new_entries[step["id"]] = state_mod.new_step(engine.default_max_visits(step, caps))
                continue
            entry = copy.deepcopy(entry)
            if entry.get("state") == "skipped":  # re-decided under the new form, risk and options
                entry.update({"state": "pending", "applies": None, "skip_reason": None})
            elif entry.get("applies") is not None and (
                    step.get("applies_when") != old_steps[step["id"]].get("applies_when")
                    or (options_changed and _names_option(step, SPEC_OPTION))):
                entry["applies"] = None
            if (entry.get("state") == "done" and not step.get("run_once")
                    and step.get("done_when") != old_steps[step["id"]].get("done_when")):
                entry.update({"state": "stale", "stale_cause": "escalate", "reenter": "escalate"})
                entry["stale_fps"] = engine._evidence_fps(ctx, step)
            new_entries[step["id"]] = entry
        st["steps"] = new_entries
        st["transition_cap"] += sum(engine.default_max_visits(step, caps) for step in added)
        if changed_source:
            red = st.get("red") or {"recorded": False, "order": None}
            if red.get("order") is None:
                st["red"] = {"recorded": bool(red.get("recorded")), "order": "unverifiable"}
            if any(step.get("gate") for step in added):
                st["gate_order"] = "after-source-edit"
        loop = _loop_state(ctx.root, target, ctx.shared)
        if loop is None:
            st["loop"] = None
        elif st.get("loop"):
            st["loop"]["mode"] = target.get("loop_mode")
        else:
            st["loop"] = loop
        st.update({"flow": target_id, "form": form, "risk": risk, "work_type": work_type, "options": options,
                   "manifest_sha256": _manifest_sha(ctx.root, target), "waiting": None})
        strategy_added = strategy_mod.amend_for_escalate(ctx, target, st)  # ctx.flow is still the source
        reason = _masked(args.reason)
        ctx.log({"kind": "escalate", "from": source_id, "to": target_id, "reason": reason, "form": form,
                 "risk": risk, "work_type": work_type, "options": options, "added": [step["id"] for step in added],
                 "transition_cap": st["transition_cap"], "red_order": st["red"].get("order"),
                 "gate_order": st.get("gate_order"), "strategy_added": strategy_added})
        state_mod.save(pkg, st)
        ctx.flow = target
        outcome = engine.advance(ctx, write=False)
    _print(args, outcome.card)
    return 0  # the operation succeeded; the card previews what `next` does now (a halt included)


# --- external ----------------------------------------------------------------------------------

def external(args) -> int:
    pkg, held = _locked(args)
    with held:
        ctx = engine.load_context(args.project, args.root, pkg.name)
        st = ctx.state
        if st["status"] != "active":
            raise SdlcError(4, "not_active:" + st["status"])
        step = ctx.flow_step(args.step)
        if step is None:
            raise SdlcError(2, "unknown_step:" + args.step)
        if args.step not in EXTERNAL_STEPS:
            raise SdlcError(4, "external_not_allowed:%s (design, spec or plan only)" % args.step)
        if not _OWNER_RE.match(args.owner or ""):
            raise SdlcError(2, "bad_owner (plugin:skill)")
        entry = engine._entry(ctx, step)
        if entry.get("state") == "done":
            raise SdlcError(4, "step_done:" + args.step)
        project = Path(ctx.project).resolve()
        artifact = Path(args.artifact)
        artifact = (artifact if artifact.is_absolute() else project / artifact).resolve()
        try:
            rel = artifact.relative_to(project).as_posix()
        except ValueError:
            raise SdlcError(2, "artifact_outside_project") from None
        if not artifact.is_file():
            raise SdlcError(2, "artifact_missing:" + rel)
        quote = _quote_needed(args.quote, "external")
        artifact_fp = fingerprint.file_fp(artifact)
        entry["external"] = {"owner": args.owner, "artifact": rel, "fp": artifact_fp, "ts": now_iso()}
        engine.mark_done(ctx, step, entry, cause="external")
        ctx.log({"kind": "external", "step": args.step, "owner": args.owner, "artifact": rel,
                 "artifact_fp": artifact_fp, "quote": quote})
        state_mod.save(pkg, st)
        outcome = engine.advance(ctx, write=False)
    _print(args, outcome.card)
    return 0  # the operation succeeded; the card previews what `next` does now (a halt included)


__all__ = ["start", "halt", "resume", "abandon", "escalate", "external", "risk_matches"]
