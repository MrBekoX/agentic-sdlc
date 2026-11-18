"""The spec check (design 4.3): the fresh reader's card, `check-record` and `check-resolve`.

The `spec-check` step hands `design.md` and the spec to one fresh reader, a role that must plan from
those two files without talking to their author. This module:
- stages that reader's card like a loop role card: a prompt file (`draft/prompts/<role>.md`: the
  role body without its frontmatter, the files to read, the JSON to return), a write path
  (`draft/check.answer.json`) and the runtime's freshness rule (`loop.FRESHNESS`, or its inline rule
  when the step's mechanism is degraded). `card` computes the paths and writes nothing; `next` stages;
- `sdlc check-record [--from FILE | --text T]` validates the reader's JSON and writes
  `spec/<work_id>.check.json` (`agentic-sdlc/check@1`) with the spec body fingerprint the reader
  read and the reader's freshness. Within one visit of the step the record may be replaced until the
  first of its questions is settled. A new visit (a changed `design.md` re-opens the step) keeps the
  settled questions of the earlier visits with their settlement and drops the open ones. Every record
  numbers its questions after the highest id the file ever held (`issued`), so a `(source: Q<n>)` in
  the spec names the question it was written for, or none;
- `sdlc check-resolve --id Q<n> --pile answered|minor|theirs --resolution T [--answer-seq N |
  --author-call]` settles one question: `answered` (the answer went into the spec), `minor` (the
  main loop decided, an author's call) or `theirs` (the user's answer, an `answer` record of
  `questions.jsonl` for a question asked during the step, or an author's call when no user is there).

The reader's questions and every resolution are masked before they are stored, as `ask` and the
quotes are. Both commands take the package lock and are refused (exit 4) unless the step is the
current one. The `settled` check (checks.py) is done when every question has a pile.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import checks, fingerprint, frontmatter, logs, manifest, mask, paths
from . import loop as loop_mod
from . import strategy as strategy_mod
from .lock import PackageLock
from .textio import SdlcError, read_json, read_text, write_json_atomic, write_text_atomic

STEP_ID = "spec-check"
CHECK_SCHEMA_ID = "agentic-sdlc/check@1"
PILES = ("answered", "minor", "theirs")
PROMPT_REL = "draft/prompts/%s.md"
WRITE_REL = "draft/check.answer.json"
QUESTIONS_LOG = "questions.jsonl"
_QUESTION_ID = re.compile(r"Q([1-9][0-9]{0,5})\Z")  # the check schema's id pattern


# --- the card ----------------------------------------------------------------------------------

def _abs(ctx, rel) -> Path:
    return Path(ctx.pkg).joinpath(*rel.split("/"))


def _project_rel(ctx, rel) -> str:
    return "%s/%s/%s" % (paths.AGENTIC_ROOT, ctx.state["slug"], rel)


def _reads(ctx, step) -> list:
    """The absolute package paths the role reads (`role_reads` with {work_id} expanded)."""
    return [str(_abs(ctx, manifest.expand(ref, ctx.state))) for ref in step.get("role_reads") or []]


def _mechanism(ctx, step) -> tuple:
    key = step.get("mechanism_key")
    return strategy_mod.resolve(ctx, key) if key else ("unset", "none")


def _delegate(ctx, step) -> str:
    """The runtime's freshness rule for the step's resolved mechanism (the inline rule when degraded)."""
    mechanism, _degraded = _mechanism(ctx, step)
    if mechanism in strategy_mod.DEGRADED:
        return loop_mod.FRESHNESS["inline"]
    row = strategy_mod.runtime_row(ctx.shared, ctx.state.get("runtime"))
    return loop_mod.FRESHNESS.get(row.get("freshness"), loop_mod.FRESHNESS["inline"]).format(agent=step["role"])


def stage(ctx, step) -> tuple:
    """Write the reader's prompt; return (prompt path, write path), both absolute."""
    agent = step["role"]
    body = frontmatter.split(read_text(loop_mod.role_path(ctx.root, agent)))[1].strip()
    prompt = _abs(ctx, PROMPT_REL % agent)
    write = _abs(ctx, WRITE_REL)
    lines = [body, "", "---", "", "## This card: %s (step %s)" % (agent, step["id"]), "", "Read these files:", ""]
    lines += ["- %s" % path for path in _reads(ctx, step)]
    lines += ["", 'Return only the JSON object {"questions": [{"question": "...", "why": "..."}]}; it is saved to %s.'
              % write, "", "Your last message is the complete result."]
    write_text_atomic(prompt, "\n".join(lines) + "\n", within=ctx.pkg)
    return prompt, write


def _recorded(ctx, step) -> bool:
    """True when the check file was recorded in the current visit of the step."""
    data = _read_check(ctx)
    entry = (ctx.state.get("steps") or {}).get(step["id"], {})
    return isinstance(data, dict) and data.get("visit") == entry.get("visits")


def role_card(ctx, step, write):
    """The role lines of the step's card, or None once the reader's answer is recorded in this visit.

    `write` stages the prompt file (`next`); the read-only `card` only names the paths.
    """
    if _recorded(ctx, step):
        return None
    agent = step["role"]
    if write:
        stage(ctx, step)
    return {"role": agent, "role_file": str(loop_mod.role_path(ctx.root, agent)),
            "prompt": _project_rel(ctx, PROMPT_REL % agent), "write": _project_rel(ctx, WRITE_REL),
            "delegate": _delegate(ctx, step)}


# --- the check file ----------------------------------------------------------------------------

def _read_check(ctx):
    """The parsed check file, or None when it is missing or not a JSON object."""
    try:
        data = read_json(_abs(ctx, checks.check_file_rel(ctx)))
    except (OSError, ValueError, SdlcError):
        return None
    return data if isinstance(data, dict) else None


def _write_check(ctx, data) -> None:
    errors = checks.check_problems(data)
    if errors:
        raise SdlcError(2, "check_invalid:%s" % errors[0])
    write_json_atomic(_abs(ctx, checks.check_file_rel(ctx)), data, within=ctx.pkg)


def _reader_questions(text, issued=0, visit=None) -> list:
    """The reader's JSON as unsettled question records numbered after `issued` (Q1, Q2, ... for 0),
    each marked with `visit` and its text masked; SdlcError(4, check_answer_invalid:<why>)."""
    try:
        data = loop_mod._json_strict(text)
    except ValueError:
        raise SdlcError(4, "check_answer_invalid:not JSON") from None
    if not isinstance(data, dict):
        raise SdlcError(4, "check_answer_invalid:not a JSON object")
    items = data.get("questions")
    if not isinstance(items, list):
        raise SdlcError(4, "check_answer_invalid:questions is not a list")
    found = []
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise SdlcError(4, "check_answer_invalid:question %d is not an object" % index)
        for key in ("question", "why"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise SdlcError(4, "check_answer_invalid:question %d has no %s" % (index, key))
        question = {"id": "Q%d" % (issued + index), "question": mask.mask_text(item["question"]).strip(),
                    "why": mask.mask_text(item["why"]).strip(), "pile": None, "resolution": None,
                    "answer_seq": None, "author_call": False}
        if visit is not None:
            question["visit"] = visit
        found.append(question)
    return found


def _number(question_id) -> int:
    match = _QUESTION_ID.match(str(question_id or ""))
    return int(match.group(1)) if match else 0


def _earlier(ctx, visit) -> tuple:
    """(kept questions, issued) from the check file before a record in `visit`.

    Only a file that validates (checks.read_check) is built on; any other file is replaced, as before.
    A question belongs to its own `visit`, or to the file's when it has none (a file written before
    questions carried one). The settled questions of other visits are kept with their settlement;
    the open ones are dropped, so citing one is an unknown source. The current visit's questions are
    replaced, which is refused once one of them is settled. `issued` is the highest question number
    the file ever held: its `issued`, or its highest id when it has none.
    """
    data, _problem = checks.read_check(ctx)
    if data is None:
        return [], 0
    file_visit = data.get("visit")
    kept = []
    for question in data["questions"]:
        owner = question.get("visit", file_visit)
        if owner == visit:
            if question["pile"] is not None:
                raise SdlcError(4, "check_already_resolving (a new record starts with a new visit of %s)" % STEP_ID)
            continue
        if question["pile"] is not None:
            carried = dict(question)
            if owner is not None:
                carried["visit"] = owner
            kept.append(carried)
    issued = max([data.get("issued", 0)] + [_number(q["id"]) for q in data["questions"]])
    return kept, issued


def record(ctx, step, text) -> int:
    """Write the check file from the reader's answer (the caller holds the lock; the step is current).

    Returns the number of new questions; the settled questions of earlier visits stay in the file
    (`_earlier`).
    """
    if len(str(text).encode("utf-8", "replace")) > loop_mod.MAX_RECORD_BYTES:
        raise SdlcError(4, "record_too_large (at most %d bytes)" % loop_mod.MAX_RECORD_BYTES)
    _reader_questions(text)  # the reader's answer is judged before anything else
    spec_rel = checks.artifact_rel(ctx, "spec")
    spec = _abs(ctx, spec_rel)
    if not spec.is_file():
        raise SdlcError(4, "spec_missing:%s" % spec_rel)
    visit = ctx.state["steps"][step["id"]]["visits"]
    kept, issued = _earlier(ctx, visit)
    questions = _reader_questions(text, issued, visit)
    mechanism, degraded = _mechanism(ctx, step)
    reader = "degraded" if mechanism in strategy_mod.DEGRADED or degraded != "none" else "fresh"
    _write_check(ctx, {"schema": CHECK_SCHEMA_ID, "artifact": "spec", "body_fingerprint": fingerprint.body_fp(spec),
                       "reader": reader, "visit": visit, "issued": issued + len(questions),
                       "questions": kept + questions})
    ctx.log({"kind": "check", "step": step["id"], "visit": visit, "questions": len(questions), "kept": len(kept),
             "reader": reader})
    return len(questions)


def _answer_step(ctx, seq):
    """The step a question was asked in, for the `answer` record `seq`; SdlcError(4) when there is none."""
    records = logs.read(Path(ctx.pkg) / QUESTIONS_LOG)
    answer = next((r for r in records if r.get("seq") == seq and r.get("kind") == "answer"), None)
    asked = next((r for r in records if answer is not None and r.get("seq") == answer.get("question_id")
                  and r.get("kind") == "ask"), None)
    if asked is None:
        raise SdlcError(4, "unknown_answer:%s" % seq)
    return asked.get("step")


def resolve(ctx, step, qid, pile, resolution, answer_seq, author_call) -> None:
    """Settle one question of the check file (the caller holds the lock; the step is current)."""
    data = _read_check(ctx)
    if data is None:
        if (_abs(ctx, checks.check_file_rel(ctx))).exists():
            raise SdlcError(4, "check_invalid:%s is not a JSON object" % checks.check_file_rel(ctx))
        raise SdlcError(4, "check_missing:%s (run sdlc check-record first)" % checks.check_file_rel(ctx))
    errors = checks.check_problems(data)
    if errors:
        raise SdlcError(4, "check_invalid:%s" % errors[0])
    question = next((q for q in data["questions"] if q["id"] == qid), None)
    if question is None:
        raise SdlcError(4, "unknown_question:%s" % qid)
    if question["pile"] is not None:
        raise SdlcError(4, "already_settled:%s" % qid)
    text = mask.mask_text(str(resolution or "")).strip()
    if not text:
        raise SdlcError(4, "resolution_empty")
    if pile != "theirs" and (answer_seq is not None or author_call):
        raise SdlcError(4, "flag_needs_theirs (--answer-seq and --author-call belong to the theirs pile)")
    if pile == "theirs":
        if (answer_seq is None) == (not author_call):
            raise SdlcError(4, "theirs_needs_answer_or_author_call (exactly one of --answer-seq N, --author-call)")
        if answer_seq is not None:
            asked_in = _answer_step(ctx, answer_seq)
            if asked_in != step["id"]:
                raise SdlcError(4, "answer_from_other_step:%s (the question was asked in that step)" % asked_in)
    question.update({"pile": pile, "resolution": text, "answer_seq": answer_seq if pile == "theirs" else None,
                     "author_call": pile == "minor" or (pile == "theirs" and answer_seq is None)})
    _write_check(ctx, data)
    ctx.log({"kind": "check", "step": step["id"], "resolved": qid, "pile": pile})


# --- command line ------------------------------------------------------------------------------

def _locked(ctx):
    """The package lock and a context reloaded under it; refused unless the package is active and
    its current step is the spec-check step."""
    from . import engine

    held = PackageLock(Path(ctx.pkg) / ".lock")
    held.acquire()
    try:
        fresh = engine.load_context(ctx.project, ctx.root, ctx.state["slug"])
        if fresh.state["status"] != "active":
            raise SdlcError(4, "not_active:%s" % fresh.state["status"])
        step = fresh.flow_step(STEP_ID)
        if step is None or fresh.state.get("current") != STEP_ID:
            raise SdlcError(4, "not_current_step:%s (the spec reader runs in %s)"
                            % (fresh.state.get("current"), STEP_ID))
    except BaseException:
        held.release()
        raise
    return fresh, step, held


def cli_check_record(ctx, args, out=None, save_state=None) -> int:
    fresh, step, held = _locked(ctx)
    try:
        source = args.from_file or str(_abs(fresh, WRITE_REL))
        if args.text is not None:
            text = args.text
        else:
            try:
                text = read_text(source)
            except OSError:
                raise SdlcError(2, "record_unreadable") from None
        count = record(fresh, step, text)
        return loop_mod._card_after(fresh, out, "recorded=check questions=%d" % count)
    finally:
        held.release()


def cli_check_resolve(ctx, args, out=None, save_state=None) -> int:
    if not _QUESTION_ID.match(args.id):
        raise SdlcError(2, "bad_question_id:%s (Q1, Q2, ...)" % args.id)
    fresh, step, held = _locked(ctx)
    try:
        resolve(fresh, step, args.id, args.pile, args.resolution, args.answer_seq, args.author_call)
        return loop_mod._card_after(fresh, out, "resolved=%s pile=%s" % (args.id, args.pile))
    finally:
        held.release()


def register_cli(subparsers) -> None:
    parser = subparsers.add_parser("check-record", help="record the spec reader's questions (spec-check step)")
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--text", default=None)
    group.add_argument("--from", dest="from_file", default=None,
                       help="a file holding the reader's JSON (default: the card's write path)")
    parser.set_defaults(handler=cli_check_record, needs_ctx=True)

    parser = subparsers.add_parser("check-resolve", help="settle one question of the spec check")
    parser.add_argument("--id", required=True, help="the question id, Q1, Q2, ...")
    parser.add_argument("--pile", required=True, choices=PILES)
    parser.add_argument("--resolution", required=True)
    parser.add_argument("--answer-seq", type=int, default=None,
                        help="theirs: the answer record of questions.jsonl that settled it")
    parser.add_argument("--author-call", action="store_true", help="theirs: the author decided, there was no one to ask")
    parser.set_defaults(handler=cli_check_resolve, needs_ctx=True)
