"""Done-checks of flow steps (contract §7) and the gate fingerprint.

`run_check(ctx, spec)` runs one `done_when` entry (`{"check": <name>, ...params}`) and returns
CheckResult(ok, detail); it never raises for a failing check (an SdlcError inside a check becomes
a failed result with its message). A check whose `work_types` list leaves out the package's work
type passes (contract §6, wave B). `ctx` is an engine.Context; the engine sets `ctx.step` (the
step being evaluated) and may set `ctx.overlay` ({package-relative path: text}) so the read-only
`card` judges a spec or plan with the frontmatter `next` would stamp, without writing it.
"""
from __future__ import annotations

import collections
import hashlib
import importlib.util
import shutil
import tempfile
from pathlib import Path

from . import fingerprint, gitinfo, logs, manifest, paths, runexec, schema
from . import strategy as strategy_mod
from .textio import SdlcError, read_json, read_text

CheckResult = collections.namedtuple("CheckResult", "ok detail")

APPROVALS_LOG = "approvals.jsonl"
RUNS_LOG = "runs.jsonl"
PROTECTED_BRANCHES = ("main", "master")
_VALIDATOR = []


def _validator():
    """scripts/validate_artifacts.py of this plugin, loaded once by path (never from the project)."""
    if not _VALIDATOR:
        source = paths.plugin_root() / "scripts" / "validate_artifacts.py"
        spec = importlib.util.spec_from_file_location("_sdlc_validate_artifacts", str(source))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _VALIDATOR.append(module)
    return _VALIDATOR[0]


def _rel(ctx, template: str) -> str:
    return manifest.expand(template, ctx.state)


def artifact_rel(ctx, kind: str) -> str:
    """`spec/<work_id>.md` or `plan/<work_id>.md`."""
    return "%s/%s.md" % (kind, ctx.state["work_id"])


def current_sets(ctx) -> dict:
    """runexec.current_sets once per engine evaluation (cached on ctx as `_sets`)."""
    cached = getattr(ctx, "_sets", None)
    if cached is None:
        try:
            cached = runexec.current_sets(ctx)
        except SdlcError as exc:
            cached = {"error": exc.message}
        ctx._sets = cached
    return cached


def _step_entry(ctx, step) -> dict:
    if not isinstance(step, dict):
        return {}
    return ctx.state.get("steps", {}).get(step.get("id"), {})


class _Materialised:
    """A real path for a package artifact; the overlay text in a temp folder when the card set one."""

    def __init__(self, ctx, rel: str):
        self.path = Path(ctx.pkg).joinpath(*rel.split("/"))
        self._tmp = None
        overlay = getattr(ctx, "overlay", None) or {}
        if rel in overlay:
            self._tmp = tempfile.mkdtemp(prefix="sdlc-card-")
            self.path = Path(self._tmp).joinpath(*rel.split("/"))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_bytes(overlay[rel].encode("utf-8"))

    def __enter__(self):
        return self.path

    def __exit__(self, *_exc):
        if self._tmp is not None:
            shutil.rmtree(self._tmp, ignore_errors=True)
        return False


def _foreign(ctx, rel: str):
    found = (getattr(ctx, "foreign", None) or {}).get(rel)
    return None if found is None else "foreign_status:%s:%s" % (rel, found)


# --- the checks --------------------------------------------------------------------------------

def check_exists(ctx, step, path):
    rel = _rel(ctx, path)
    target = Path(ctx.pkg).joinpath(*rel.split("/"))
    if not target.is_file():
        return CheckResult(False, "%s is missing" % rel)
    if target.stat().st_size == 0:
        return CheckResult(False, "%s is empty" % rel)
    return CheckResult(True, "%s exists" % rel)


def check_validator(ctx, step, mode, strict=False):
    if mode not in ("spec", "plan"):
        return CheckResult(False, "unknown_validator_mode:%s" % mode)
    rel = artifact_rel(ctx, mode)
    problem = _foreign(ctx, rel)
    if problem:
        return CheckResult(False, problem)
    if not Path(ctx.pkg).joinpath(*rel.split("/")).is_file():
        return CheckResult(False, "%s is missing" % rel)
    spec_rel = artifact_rel(ctx, "spec")
    has_spec = mode == "plan" and Path(ctx.pkg).joinpath(*spec_rel.split("/")).is_file()
    with _Materialised(ctx, rel) as artifact:
        if has_spec:
            with _Materialised(ctx, spec_rel) as spec_path:
                code, fields = _validator().run(mode, str(artifact), str(spec_path), bool(strict))
        else:
            code, fields = _validator().run(mode, str(artifact), None, bool(strict))
    if code == 0:
        return CheckResult(True, "%s passes validate_artifacts (%s%s)" % (rel, mode, ", strict" if strict else ""))
    errors = [key[len("error="):] for key in fields if key.startswith("error=")]
    if strict and not errors:
        errors = [key[len("warning="):] for key in fields if key.startswith("warning=")]
    return CheckResult(False, "%s fails validate_artifacts: %s" % (rel, ", ".join(errors[:4]) or "exit %d" % code))


def check_sidecar_ok(ctx, step, artifact):
    if artifact not in ("spec", "plan"):
        return CheckResult(False, "unknown_artifact:%s" % artifact)
    rel = artifact_rel(ctx, artifact)
    problem = _foreign(ctx, rel)
    if problem:
        return CheckResult(False, problem)
    sidecar_rel = "%s/%s.review.json" % (artifact, ctx.state["work_id"])
    try:
        data = read_json(Path(ctx.pkg).joinpath(*sidecar_rel.split("/")))
    except (FileNotFoundError, NotADirectoryError):
        return CheckResult(False, "%s is missing" % sidecar_rel)
    except (OSError, ValueError, SdlcError):
        return CheckResult(False, "%s is not readable JSON" % sidecar_rel)
    errors = schema.validate(data, manifest.load_schema("sidecar"))
    if errors:
        return CheckResult(False, "%s: %s" % (sidecar_rel, errors[0]))
    if data.get("artifact") != rel:
        return CheckResult(False, "%s names %r, not %s" % (sidecar_rel, data.get("artifact"), rel))
    body = fingerprint.body_fp(Path(ctx.pkg).joinpath(*rel.split("/")))
    if data.get("body_fingerprint") != body:
        return CheckResult(False, "%s does not match the body of %s (edited after review)" % (sidecar_rel, rel))
    return CheckResult(True, "%s matches %s" % (sidecar_rel, rel))


def check_report(ctx, step, path, header, verdict=None, fresh=True):
    rel = _rel(ctx, path)
    target = Path(ctx.pkg).joinpath(*rel.split("/"))
    if not target.is_file():
        return CheckResult(False, "%s is missing" % rel)
    try:
        text = read_text(target)
    except SdlcError as exc:
        return CheckResult(False, exc.message)
    lines = [line.strip() for line in text.splitlines()]
    if header.strip() not in lines:
        return CheckResult(False, "%s has no line %r" % (rel, header))
    if verdict is not None and not any(verdict in line for line in lines):
        return CheckResult(False, "%s has no %r" % (rel, verdict))
    if fresh:
        recorded = (_step_entry(ctx, step).get("visit_fps") or {}).get(rel)
        if recorded is None or recorded == fingerprint.file_fp(target):
            return CheckResult(False, "%s was not written in this visit" % rel)
    return CheckResult(True, "%s has %r" % (rel, header))


def _runs(ctx) -> list:
    """`finished` records paired with their `started` record by run_seq (an unpaired one is ignored)."""
    records = logs.read(Path(ctx.pkg) / RUNS_LOG)
    started = {r.get("seq") for r in records if r.get("kind") == "started"}
    return [r for r in records if r.get("kind") == "finished" and r.get("run_seq") in started]


def check_run_recorded(ctx, step, expect, label=None):
    runs = [r for r in _runs(ctx) if label is None or r.get("label") == label]
    what = "%s run%s" % ("RED" if expect == "fail" else "GREEN", " labelled %s" % label if label else "")
    if expect == "fail":
        valid = [r for r in runs if r.get("expect") == "fail" and r.get("valid") is True]
        order = (ctx.state.get("red") or {}).get("order")
        if not valid:
            reasons = sorted({str(r.get("validity_reason")) for r in runs if r.get("expect") == "fail"})
            return CheckResult(False, "no valid %s%s" % (what, " (" + ", ".join(reasons) + ")" if reasons else ""))
        if order not in ("ok", "unverifiable"):
            return CheckResult(False, "red_order_%s" % (order or "missing"))
        return CheckResult(True, "a valid %s (red_order=%s)" % (what, order))
    if expect != "pass":
        return CheckResult(False, "bad_expect:%s" % expect)
    sets = current_sets(ctx)
    if "error" in sets:
        return CheckResult(False, "named sets unreadable: %s" % sets["error"])
    passing = [r for r in runs if r.get("valid") is True and r.get("exit") == 0 and r.get("expect") != "fail"]
    if not passing:
        return CheckResult(False, "no valid passing %s" % what)
    for record in passing:
        if record.get("source_fp") == sets["source_fp"] and record.get("tests_fp") == sets["tests_fp"]:
            return CheckResult(True, "a valid passing %s at the current source" % what)
    return CheckResult(False, "the source or tests changed after the last passing %s" % what)


def gate_fingerprint(ctx, step) -> str:
    """16 hex: sha256 over the body fingerprint of each `#body` input of the gate step, in order."""
    digest = hashlib.sha256()
    for entry in step.get("inputs") or []:
        parsed = manifest.parse_ref(entry)
        if parsed["path"] is None or not parsed["body"]:
            continue
        rel = manifest.expand(parsed["path"], ctx.state)
        body = fingerprint.body_fp(Path(ctx.pkg).joinpath(*rel.split("/")))
        digest.update(rel.encode("utf-8") + b"\0" + body.encode("ascii") + b"\n")
    return digest.hexdigest()[:16]


def gated_artifacts(ctx, step) -> list:
    found = []
    for entry in step.get("inputs") or []:
        parsed = manifest.parse_ref(entry)
        if parsed["path"] is not None and parsed["body"]:
            found.append(manifest.expand(parsed["path"], ctx.state))
    return found


def _appended_under_preapproval(ctx, step, record):
    """The task blocks appended to the plan since a pre-approval, or None when anything else changed.

    Design §5.10 (D10): under an original-request approval, task blocks appended after the last
    approved task continue under that approval while every approved task, the plan's text before
    its first task and every other gated body stay byte-equal.
    """
    from . import gates

    if record.get("source") != "original-request" or not isinstance(record.get("bodies"), dict):
        return None
    plan_rel = gates._plan_rel(ctx, step)
    if plan_rel is None:
        return None
    current = gates.bodies(ctx, step)
    for rel, body in current.items():
        if rel != plan_rel and record["bodies"].get(rel) != body:
            return None
    head, tasks = gates.plan_tasks(Path(ctx.pkg).joinpath(*plan_rel.split("/")))
    approved = list(record.get("task_hashes") or [])
    if head != record.get("plan_head") or len(tasks) <= len(approved):
        return None
    if [h for _t, h in tasks[:len(approved)]] != approved:
        return None
    return [{"title": title, "hash": digest} for title, digest in tasks[len(approved):]]


def check_approval(ctx, step, gate):
    current = gate_fingerprint(ctx, step)
    records = [r for r in logs.read(Path(ctx.pkg) / APPROVALS_LOG)
               if r.get("kind") == "approve" and r.get("gate") == gate]
    for record in records:
        if record.get("fingerprint") == current:
            return CheckResult(True, "gate %s approved at %s" % (gate, current))
    if records:
        appended = _appended_under_preapproval(ctx, step, records[-1])
        if appended:
            ctx.state["appended_tasks"] = appended  # listed by the claim step (design §5.10)
            return CheckResult(True, "gate %s pre-approved; %d task(s) appended after the approved ones"
                               % (gate, len(appended)))
    return CheckResult(False, "gate %s is not approved at fingerprint %s" % (gate, current))


def current_branch(ctx):
    facts = gitinfo.facts(ctx.project)
    return facts.get("branch") if facts.get("repo") else None


def check_branch_ok(ctx, step):
    if ctx.state.get("branch_policy") == "stay":
        return CheckResult(True, "branch_policy=stay (recorded with the user's quote)")
    branch = current_branch(ctx)
    if branch in PROTECTED_BRANCHES:
        return CheckResult(False, "on %s: create a work branch, or record branch_policy=stay with the user's quote"
                           % branch)
    return CheckResult(True, "on %s" % (branch or "no branch"))


def check_resolver_ok(ctx, step):
    plan = Path(ctx.pkg) / "plan" / ("%s.md" % ctx.state["work_id"])
    resolver = paths._resolver()
    result = resolver.resolve(ctx.project, plan_path=str(plan) if plan.is_file() else None,
                              branch=current_branch(ctx))
    errors = list(getattr(result, "errors", None) or [])
    if getattr(result, "ok", False) and not errors:
        return CheckResult(True, "resolve_work_package resolves the package")
    return CheckResult(False, "resolve_work_package: %s" % (", ".join(str(e) for e in errors[:3]) or "no resolution"))


def check_strategy_ok(ctx, step):
    data = strategy_mod.load_map(ctx.pkg)
    if data is None:
        return CheckResult(False, "strategy.json is missing: run `sdlc strategy confirm`")
    errors = strategy_mod.validate(data, ctx.flow, ctx.state)
    if errors:
        return CheckResult(False, "strategy.json: %s" % errors[0])
    return CheckResult(True, "strategy.json is valid")


def check_unchanged(ctx, step, set):  # noqa: A002 - the manifest parameter is named `set`
    if set != "production":
        return CheckResult(False, "unknown_set:%s" % set)
    sets = current_sets(ctx)
    if "error" in sets:
        return CheckResult(False, "named sets unreadable: %s" % sets["error"])
    changed = runexec._since_start(ctx, sets["source"])
    if changed:
        return CheckResult(False, "production files changed since start: %s" % ", ".join(changed[:5]))
    return CheckResult(True, "no production file changed since start")


def check_loop_done(ctx, step):
    loop = ctx.state.get("loop") or {}
    if not loop.get("stop_reason"):
        return CheckResult(False, "the spec/plan loop has not stopped")
    if not (Path(ctx.pkg) / "draft" / "result.json").is_file():
        return CheckResult(False, "draft/result.json was not ingested")
    return CheckResult(True, "the loop stopped: %s" % loop["stop_reason"])


_CHECKS = {
    "exists": check_exists, "validator": check_validator, "sidecar_ok": check_sidecar_ok,
    "report": check_report, "run_recorded": check_run_recorded, "approval": check_approval,
    "branch_ok": check_branch_ok, "resolver_ok": check_resolver_ok, "strategy_ok": check_strategy_ok,
    "unchanged": check_unchanged, "loop_done": check_loop_done,
}


def run_check(ctx, spec: dict, step=None) -> CheckResult:
    """One done-check; `step` defaults to ctx.step (the step being evaluated)."""
    if step is None:
        step = getattr(ctx, "step", None)
    name = spec.get("check") if isinstance(spec, dict) else None
    func = _CHECKS.get(name)
    if func is None:
        return CheckResult(False, "unknown_check:%s" % name)
    work_types = spec.get("work_types")
    if isinstance(work_types, list) and ctx.state.get("work_type") not in work_types:
        return CheckResult(True, "%s does not apply to work type %s" % (name, ctx.state.get("work_type")))
    params = {k: v for k, v in spec.items() if k not in ("check",) + manifest.GENERIC_CHECK_PARAMS}
    try:
        return func(ctx, step, **params)
    except SdlcError as exc:
        return CheckResult(False, exc.message)


def describe(spec: dict, state: dict) -> str:
    """The plain-language `done_when` text a card prints for one check."""
    name = spec.get("check")
    try:
        path = manifest.expand(spec["path"], state) if "path" in spec else None
    except SdlcError:
        path = spec.get("path")
    if name == "exists":
        return "%s exists and is not empty" % path
    if name == "report":
        text = "%s has the line %r" % (path, spec.get("header"))
        if spec.get("verdict"):
            text += " and %r" % spec["verdict"]
        return text + (", written in this visit" if spec.get("fresh", True) else "")
    if name == "run_recorded":
        kind = "a failing (RED) run" if spec.get("expect") == "fail" else "a passing (GREEN) run at the current source"
        return "%s recorded with `sdlc run --expect %s%s -- <test command>`" % (
            kind, spec.get("expect"), " --label %s" % spec["label"] if spec.get("label") else "")
    if name == "validator":
        return "validate_artifacts.py passes on the %s%s" % (spec.get("mode"), " (strict)" if spec.get("strict") else "")
    if name == "sidecar_ok":
        return "the %s review sidecar matches its body" % spec.get("artifact")
    if name == "approval":
        return "the user approved gate %s" % spec.get("gate")
    if name == "branch_ok":
        return "you are on a work branch (not main/master), or branch_policy=stay was recorded"
    if name == "resolver_ok":
        return "resolve_work_package.py resolves the package"
    if name == "strategy_ok":
        return "strategy.json is confirmed (`sdlc strategy confirm`)"
    if name == "unchanged":
        return "no production file changed since start"
    if name == "loop_done":
        return "the spec/plan loop stopped and its result was ingested"
    return str(name)
