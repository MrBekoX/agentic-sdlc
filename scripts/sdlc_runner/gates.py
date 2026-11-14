"""Gates, questions and notes (contract §11, design §5.10).

- `approve <gate> --fingerprint F (--quote Q | --quote-file P) --source reply|original-request`
  records the user's approval in approvals.jsonl. Refused (exit 4) when the flow has no such gate,
  the gate is not where `next` waits (its artifacts fail their checks), F is not the current gate
  fingerprint, a `reply` has no recorded wait at this fingerprint, or an `original-request` quote
  is not in the stored request, the gate was approved before (the original quote cannot re-approve
  a changed draft), a decision point has no recommendation, or a residual critic note is critical
  or high or a contradiction or blocker. A degraded critic does not block a pre-approval; the
  record says `critic=degraded`.
- `reject <gate> --quote ...` appends the user's change request to feedback.jsonl and reopens
  the step that drafted the gated artifacts (it re-enters with cause `reject`).
- `ask --kind consent|design --question T` (the kind must be in the current step's `may_ask`)
  makes `next` wait (`state=wait-answer`) until `answer --quote ...` records the reply.
- `note --degraded <capability> --reason missing|denied|unavailable [--step S]` and
  `note --awaiting <task id>` record a fallback and a background task in notes.jsonl and state.

Every quote is masked before it is stored. Each handler takes the package lock itself.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

from . import checks, engine, logs, manifest, mask
from . import state as state_mod
from .lock import PackageLock
from .textio import SdlcError, now_iso, read_json, read_text

APPROVALS_LOG = "approvals.jsonl"
FEEDBACK_LOG = "feedback.jsonl"
QUESTIONS_LOG = "questions.jsonl"
NOTES_LOG = "notes.jsonl"
SOURCES = ("reply", "original-request")
ASK_KINDS = ("consent", "design")
CAPABILITIES = ("workflow", "subagent", "team")
DEGRADED_REASONS = ("missing", "denied", "unavailable")
BLOCKING_SEVERITIES = ("critical", "high")
BLOCKING_KINDS = ("contradiction", "blocker")
_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_VALIDATOR = []


def normalise_quote(text) -> str:
    """NFC, whitespace runs collapsed to one space, stripped, case-folded (contract §11)."""
    return " ".join(unicodedata.normalize("NFC", str(text or "")).split()).casefold()


def _quote(args) -> str:
    """The masked quote from --quote or --quote-file (UTF-8; SdlcError(2, not_utf8:...))."""
    if getattr(args, "quote_file", None):
        try:
            text = read_text(args.quote_file)
        except OSError:
            raise SdlcError(2, "quote_file_unreadable") from None
    else:
        text = args.quote or ""
    text = mask.mask_text(text).strip()
    if not text:
        raise SdlcError(4, "quote_empty")
    return text


# --- plan task hashes (D10) --------------------------------------------------------------------

def _validator():
    if not _VALIDATOR:
        _VALIDATOR.append(checks._validator())
    return _VALIDATOR[0]


def plan_tasks(path) -> tuple:
    """(head hash, [(task title, task hash)]) of a plan body: the text before the first task, then
    each task block as validate_artifacts splits it."""
    try:
        text = read_text(path, errors="surrogateescape")
    except (OSError, SdlcError):
        return None, []
    va = _validator()
    body = va._body(text).rstrip("\n")
    blocks = va._iter_task_blocks(body)
    lines = body.splitlines()
    starts = va._task_starts(lines)
    head = "\n".join(lines[:starts[0][0]]) if starts else body
    digest = lambda s: hashlib.sha256(s.rstrip("\n").encode("utf-8", "surrogateescape")).hexdigest()  # noqa: E731
    return digest(head), [(block.splitlines()[0].strip(), digest(block)) for _number, block in blocks]


def _plan_rel(ctx, step):
    plan = checks.artifact_rel(ctx, "plan")
    return plan if plan in checks.gated_artifacts(ctx, step) else None


def bodies(ctx, step) -> dict:
    from . import fingerprint

    return {rel: fingerprint.body_fp(Path(ctx.pkg).joinpath(*rel.split("/")))
            for rel in checks.gated_artifacts(ctx, step)}


# --- helpers -----------------------------------------------------------------------------------

def _gate_step(ctx, gate):
    for step in ctx.flow.get("steps", []):
        if step.get("gate") == gate:
            return step
    raise SdlcError(4, "unknown_gate:%s" % gate)


def _waiting_at(ctx, step):
    """Refuse unless `next` would wait at `step`'s gate now (its artifacts pass, the gate is current)."""
    preview = engine.advance(ctx, write=False)
    if preview.state != "wait-gate" or preview.step != step["id"]:
        raise SdlcError(4, "gate_not_waiting:%s:%s (run sdlc next)" % (preview.state, preview.step or "none"))


def _sidecars(ctx, step) -> list:
    found = []
    for rel in checks.gated_artifacts(ctx, step):
        path = Path(ctx.pkg).joinpath(*rel.split("/")).with_suffix(".review.json")
        try:
            data = read_json(path)
        except (OSError, ValueError, SdlcError):
            continue
        if isinstance(data, dict):
            found.append(data)
    return found


def _critic(sidecars) -> str:
    if not sidecars:
        return "none"
    return "degraded" if any(s.get("critic") == "degraded" for s in sidecars) else "fresh"


def _preapproval_problem(sidecars):
    for data in sidecars:
        for point in data.get("decisionPoints") or []:
            if isinstance(point, dict) and not str(point.get("recommendation") or "").strip():
                return "decision_without_recommendation:%s" % point.get("id")
        for note in data.get("residualCriticNotes") or []:
            if isinstance(note, dict) and (note.get("severity") in BLOCKING_SEVERITIES
                                           or note.get("kind") in BLOCKING_KINDS):
                return "blocking_residual_note:%s:%s" % (note.get("target"), note.get("category"))
    return None


def _locked_context(ctx):
    held = PackageLock(Path(ctx.pkg) / ".lock")
    held.acquire()
    try:
        fresh = engine.load_context(ctx.project, ctx.root, ctx.state["slug"])
    except BaseException:
        held.release()
        raise
    if fresh.state["status"] != "active":
        held.release()
        raise SdlcError(4, "not_active:" + fresh.state["status"])
    return fresh, held


def _finish(ctx, out, head: str) -> int:
    state_mod.save(ctx.pkg, ctx.state)
    outcome = engine.advance(ctx, write=False)
    if out is not None:
        out.write(head + "\n")
        out.write(outcome.card)
    return 0


# --- approve / reject --------------------------------------------------------------------------

def approve(ctx, gate, fingerprint, quote, source, out=None) -> int:
    """Record an approval of `gate` (caller holds the lock; ctx loaded under it)."""
    if source not in SOURCES:
        raise SdlcError(2, "bad_source:%s" % source)
    step = _gate_step(ctx, gate)
    _waiting_at(ctx, step)
    current = checks.gate_fingerprint(ctx, step)
    if fingerprint != current:
        raise SdlcError(4, "fingerprint_mismatch (run sdlc card and show the user the current gate message)")
    transitions = logs.read(Path(ctx.pkg) / engine.TRANSITIONS_LOG)
    sidecars = _sidecars(ctx, step)
    if source == "reply":
        if not any(r.get("kind") == "wait" and r.get("gate") == gate and r.get("fingerprint") == fingerprint
                   for r in transitions):
            raise SdlcError(4, "reply_without_wait (run sdlc next, show the user the gate message, then record "
                               "their reply)")
    else:
        if any(r.get("kind") == "approve" and r.get("gate") == gate
               for r in logs.read(Path(ctx.pkg) / APPROVALS_LOG)):
            raise SdlcError(4, "preapproval_used (the gate was approved before; record the user's reply)")
        try:
            request = read_text(Path(ctx.pkg) / "request.md")
        except (OSError, SdlcError):
            raise SdlcError(2, "request_unreadable") from None
        if normalise_quote(quote) not in normalise_quote(request):
            raise SdlcError(4, "quote_not_in_request")
        problem = _preapproval_problem(sidecars)
        if problem:
            raise SdlcError(4, problem)
    plan_rel = _plan_rel(ctx, step)
    head, tasks = plan_tasks(Path(ctx.pkg).joinpath(*plan_rel.split("/"))) if plan_rel else (None, [])
    critic = _critic(sidecars)
    logs.append(Path(ctx.pkg) / APPROVALS_LOG, {
        "kind": "approve", "gate": gate, "fingerprint": fingerprint, "quote": quote, "source": source,
        "critic": critic, "task_hashes": [h for _t, h in tasks], "plan_head": head, "bodies": bodies(ctx, step),
    })
    ctx.log({"kind": "approve", "gate": gate, "fingerprint": fingerprint, "source": source, "critic": critic})
    return _finish(ctx, out, "approved=%s" % gate)


def _drafting_step(ctx, step):
    """The latest step before the gate whose outputs hold a gated artifact (else the one before it)."""
    gated = set(checks.gated_artifacts(ctx, step))
    steps = ctx.flow["steps"]
    earlier = steps[:steps.index(step)]
    for candidate in reversed(earlier):
        outputs = set()
        for entry in candidate.get("outputs") or []:
            parsed = manifest.parse_ref(entry)
            if parsed["path"] is not None:
                outputs.add(manifest.expand(parsed["path"], ctx.state))
        if outputs & gated:
            return candidate
    return earlier[-1] if earlier else None


def reject(ctx, gate, quote, out=None) -> int:
    step = _gate_step(ctx, gate)
    _waiting_at(ctx, step)
    fingerprint = checks.gate_fingerprint(ctx, step)
    logs.append(Path(ctx.pkg) / FEEDBACK_LOG, {"kind": "reject", "gate": gate, "quote": quote,
                                                "fingerprint": fingerprint})
    drafting = _drafting_step(ctx, step)
    if drafting is not None:
        entry = engine._entry(ctx, drafting)
        entry.update({"state": "stale", "stale_cause": "reject", "reenter": "reject",
                      "stale_fps": engine._evidence_fps(ctx, drafting)})
    ctx.state["waiting"] = None
    ctx.log({"kind": "reject", "gate": gate, "fingerprint": fingerprint,
             "step": drafting["id"] if drafting else None})
    return _finish(ctx, out, "rejected=%s" % gate)


# --- ask / answer ------------------------------------------------------------------------------

def ask(ctx, kind, question, out=None) -> int:
    current = ctx.flow_step(ctx.state.get("current"))
    if current is None:
        raise SdlcError(4, "no_current_step")
    if kind not in (current.get("may_ask") or []):
        raise SdlcError(4, "ask_kind_not_allowed:%s:%s" % (kind, current["id"]))
    if ctx.state.get("waiting"):
        raise SdlcError(4, "already_waiting:%s" % ctx.state["waiting"].get("kind"))
    text = mask.mask_text(str(question or "")).strip()
    if not text:
        raise SdlcError(4, "question_empty")
    record = logs.append(Path(ctx.pkg) / QUESTIONS_LOG, {"kind": "ask", "ask_kind": kind, "question": text,
                                                          "step": current["id"]})
    ctx.state["waiting"] = {"kind": "answer", "question_id": record["seq"], "step": current["id"], "since": now_iso()}
    ctx.log({"kind": "ask", "ask_kind": kind, "question_id": record["seq"], "step": current["id"]})
    return _finish(ctx, out, "asked=%d" % record["seq"])


def answer(ctx, quote, out=None) -> int:
    waiting = ctx.state.get("waiting") or {}
    if waiting.get("kind") != "answer":
        raise SdlcError(4, "no_pending_question")
    logs.append(Path(ctx.pkg) / QUESTIONS_LOG, {"kind": "answer", "question_id": waiting.get("question_id"),
                                                 "quote": quote})
    ctx.state["waiting"] = None
    ctx.log({"kind": "answer", "question_id": waiting.get("question_id")})
    return _finish(ctx, out, "answered=%s" % waiting.get("question_id"))


# --- notes -------------------------------------------------------------------------------------

def note_degraded(ctx, capability, reason, step, out=None) -> int:
    if capability not in CAPABILITIES:
        raise SdlcError(2, "bad_capability:%s" % capability)
    if reason not in DEGRADED_REASONS:
        raise SdlcError(2, "bad_reason:%s (missing, denied or unavailable)" % reason)
    step_id = step or ctx.state.get("current")
    if ctx.flow_step(step_id) is None:
        raise SdlcError(2, "unknown_step:%s" % step_id)
    item = {"step": step_id, "capability": capability, "reason": reason}
    logs.append(Path(ctx.pkg) / NOTES_LOG, dict(item, kind="degraded"))
    degraded = ctx.state.setdefault("degraded", [])
    if item not in degraded:
        degraded.append(item)
    ctx.log(dict(item, kind="note", note="degraded"))
    return _finish(ctx, out, "noted=degraded")


def note_awaiting(ctx, task_id, out=None) -> int:
    if not _TASK_ID.match(str(task_id or "")):
        raise SdlcError(2, "bad_task_id")
    step_id = ctx.state.get("current")
    logs.append(Path(ctx.pkg) / NOTES_LOG, {"kind": "awaiting", "task_id": task_id, "step": step_id})
    ctx.state["awaiting"] = {"task_id": task_id, "step": step_id, "since": now_iso()}
    ctx.log({"kind": "note", "note": "awaiting", "task_id": task_id, "step": step_id})
    return _finish(ctx, out, "noted=awaiting")


# --- command line ------------------------------------------------------------------------------

def _run(ctx, out, call):
    fresh, held = _locked_context(ctx)
    try:
        return call(fresh)
    finally:
        held.release()


def cli_approve(ctx, args, out=None, save_state=None) -> int:
    quote = _quote(args)
    return _run(ctx, out, lambda c: approve(c, args.gate, args.fingerprint, quote, args.source, out=out))


def cli_reject(ctx, args, out=None, save_state=None) -> int:
    quote = _quote(args)
    return _run(ctx, out, lambda c: reject(c, args.gate, quote, out=out))


def cli_ask(ctx, args, out=None, save_state=None) -> int:
    return _run(ctx, out, lambda c: ask(c, args.kind, args.question, out=out))


def cli_answer(ctx, args, out=None, save_state=None) -> int:
    quote = _quote(args)
    return _run(ctx, out, lambda c: answer(c, quote, out=out))


def cli_note(ctx, args, out=None, save_state=None) -> int:
    if args.degraded:
        if not args.reason:
            raise SdlcError(2, "note_degraded_needs_reason")
        return _run(ctx, out, lambda c: note_degraded(c, args.degraded, args.reason, args.step, out=out))
    return _run(ctx, out, lambda c: note_awaiting(c, args.awaiting, out=out))


def _quote_options(parser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--quote", default=None, help="the user's own words")
    group.add_argument("--quote-file", default=None, help="a UTF-8 file holding the user's own words")


def register_cli(subparsers) -> None:
    parser = subparsers.add_parser("approve", help="record the user's approval of a gate")
    parser.add_argument("gate")
    parser.add_argument("--fingerprint", required=True)
    _quote_options(parser)
    parser.add_argument("--source", required=True, choices=SOURCES)
    parser.set_defaults(handler=cli_approve, needs_ctx=True)

    parser = subparsers.add_parser("reject", help="record the user's change request at a gate")
    parser.add_argument("gate")
    _quote_options(parser)
    parser.set_defaults(handler=cli_reject, needs_ctx=True)

    parser = subparsers.add_parser("ask", help="ask the user a consent or design question outside a gate")
    parser.add_argument("--kind", required=True, choices=ASK_KINDS)
    parser.add_argument("--question", required=True)
    parser.set_defaults(handler=cli_ask, needs_ctx=True)

    parser = subparsers.add_parser("answer", help="record the user's answer to the pending question")
    _quote_options(parser)
    parser.set_defaults(handler=cli_answer, needs_ctx=True)

    parser = subparsers.add_parser("note", help="record a degraded fallback or a background task")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--degraded", default=None, metavar="CAPABILITY", choices=CAPABILITIES)
    group.add_argument("--awaiting", default=None, metavar="TASK_ID")
    parser.add_argument("--reason", default=None, choices=DEGRADED_REASONS)
    parser.add_argument("--step", default=None)
    parser.set_defaults(handler=cli_note, needs_ctx=True)
