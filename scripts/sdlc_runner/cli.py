"""The `sdlc` command line (contract §13): argparse, dispatch, exit codes.

Exit codes: 0 every normal state (the card says which with `state=`), 2 usage or state error, 3
halted, 4 refused; `run` returns its child's code. An error prints exactly one `error=<reason>`
line. Every command's last line is `state=<state> chain=<12 hex>` (a card's last line adds
` then=<command>`), except `run`, whose last line is its `run_seq=... chain=...` summary.
`status --json` and `next --json` print their JSON object on the first line, then that last line.

Global options `--project <dir>` and `--slug <slug>` are accepted before or after the command.
Handlers come in two kinds: a command whose parser sets `needs_ctx=True` (`run`, `strategy`, the
gate, question and note commands, `draft-check`, `loop-record`, `ingest-draft`, `check-record`,
`check-resolve`) is called as
`handler(ctx, args, out=<stdout>, save_state=<red merger>)` with an engine.Context of the
resolved package and must take the package lock itself; any other
handler is called as `handler(args)` with `args.out`, `args.root` and `args.project` set. A
`SystemExit` from a run that was signalled propagates; any other unexpected exception is one
`error=internal:<class>:<message>` line and exit 2.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import card as card_mod
from . import engine, flowops, gates, logs, loop, manifest, paths, runexec, speccheck, strategy
from . import state as state_mod
from .lock import PackageLock
from .textio import SdlcError, utf8_output

ZERO_CHAIN = "0" * 12
_STATE_FOR_CODE = {2: "error", 3: "halted", 4: "refused"}


class _UsageError(Exception):
    def __init__(self, message: str, usage: str):
        super().__init__(message)
        self.message = message
        self.usage = usage


class _Parser(argparse.ArgumentParser):
    """argparse that raises instead of printing to stderr and exiting."""

    def error(self, message):
        raise _UsageError(message, self.format_usage())


def _one_line(text) -> str:
    return " ".join(str(text).split())


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="sdlc", description="agentic-sdlc runner: one step card at a time.")
    parser.add_argument("--project", default=None, help="project directory (default: the git top of the cwd)")
    parser.add_argument("--slug", default=None, help="work package (default: the one active package)")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND", parser_class=_Parser)
    sub.required = True

    start = sub.add_parser("start", help="start a flow on a new work package")
    start.add_argument("flow")
    start.add_argument("--work-id", required=True)
    start.add_argument("--risk", required=True, choices=("high", "normal"))
    start.add_argument("--risk-reason", default=None)
    start.add_argument("--form", required=True, choices=manifest.FORMS)
    start.add_argument("--work-type", required=True, choices=manifest.WORK_TYPES)
    start.add_argument("--runtime", required=True, choices=manifest.RUNTIMES)
    start.add_argument("--request-file", required=True)
    start.add_argument("--option", action="append", default=None, choices=manifest.OPTIONS)
    start.add_argument("--branch-policy", default="work", choices=("work", "stay"))
    start.add_argument("--quote", default=None, help="the user's words for --branch-policy stay")
    start.add_argument("--spec-file", default=None, help="an approved spec to import (the plan flow)")
    start.set_defaults(handler=flowops.start)

    sub.add_parser("next", help="advance and print the next card").set_defaults(handler=_next)
    sub.add_parser("card", help="print the current card (read-only)").set_defaults(handler=_card)
    status = sub.add_parser("status", help="summarise the active packages (read-only)")
    shape = status.add_mutually_exclusive_group()
    shape.add_argument("--json", action="store_true")
    shape.add_argument("--brief", action="store_true")
    status.set_defaults(handler=_status)

    halt = sub.add_parser("halt", help="stop the flow (the user's call)")
    halt.add_argument("--reason", required=True)
    halt.set_defaults(handler=flowops.halt)
    resume = sub.add_parser("resume", help="resume a halted flow")
    resume.add_argument("--raise-cap", default=None, metavar="STEP|transitions|fix-rounds")
    resume.add_argument("--quote", default=None)
    resume.set_defaults(handler=flowops.resume)
    abandon = sub.add_parser("abandon", help="end the flow for good")
    abandon.add_argument("--quote", required=True)
    abandon.set_defaults(handler=flowops.abandon)
    escalate = sub.add_parser("escalate", help="move the package up the escalate lattice")
    escalate.add_argument("flow")
    escalate.add_argument("--reason", required=True)
    escalate.add_argument("--risk", default=None, choices=("high",))
    escalate.add_argument("--form", default=None, choices=("gated",))
    escalate.set_defaults(handler=flowops.escalate)
    external = sub.add_parser("external", help="record a phase the user gave to another plugin")
    external.add_argument("step")
    external.add_argument("--owner", required=True)
    external.add_argument("--artifact", required=True)
    external.add_argument("--quote", required=True)
    external.set_defaults(handler=flowops.external)

    runexec.register_cli(sub)
    sub.choices["run"].set_defaults(needs_ctx=True)
    for module in (strategy, gates, loop, speccheck):
        module.register_cli(sub)
    for child in sub.choices.values():
        for flag, help_text in (("--project", "project directory"), ("--slug", "work package")):
            if flag not in child._option_string_actions:
                child.add_argument(flag, default=argparse.SUPPRESS, help=help_text)
    return parser


# --- read and advance --------------------------------------------------------------------------

def _context(args) -> engine.Context:
    slug = state_mod.resolve_slug(args.project, args.slug)
    args._pkg = paths.package_dir(args.project, slug)
    return engine.load_context(args.project, args.root, slug)


def _next(args) -> int:
    slug = state_mod.resolve_slug(args.project, args.slug)
    pkg = paths.package_dir(args.project, slug)
    args._pkg = pkg
    with PackageLock(pkg / ".lock"):
        ctx = engine.load_context(args.project, args.root, slug)
        if getattr(args, "engine", None):  # an engine driver names itself (ZCode: zcode-dwf)
            if not isinstance(ctx.state.get("loop"), dict):
                raise SdlcError(4, "no_loop:%s" % ctx.state["flow"])
            ctx.state["loop"]["engine"] = args.engine
        outcome = engine.advance(ctx, write=True)
    if getattr(args, "json", False):  # the machine card (contract §10), then the usual last line
        args.out.write(json.dumps(loop.machine_card(ctx, outcome), ensure_ascii=False, sort_keys=True) + "\n")
        args.out.write("state=%s chain=%s\n" % (outcome.state, _chain(args)))
        return outcome.exit_code
    args.out.write(outcome.card)
    return outcome.exit_code


def _card(args) -> int:
    try:
        ctx = _context(args)
    except SdlcError as exc:
        if exc.message != "no_active_flow":
            raise
        args.out.write(card_mod.no_flow_card(args.project))
        return 0
    outcome = engine.advance(ctx, write=False)
    args.out.write(outcome.card)
    return outcome.exit_code


def _shown_state(st: dict) -> str:
    if st["status"] in ("complete", "abandoned", "halted"):
        return st["status"]
    waiting = st.get("waiting") or {}
    if waiting.get("kind") == "gate":
        return "wait-gate"
    if waiting.get("kind") == "answer":
        return "wait-answer"
    return "do"


def _summary(project, slug: str) -> dict:
    pkg = paths.package_dir(project, slug)
    st = state_mod.load(pkg)
    current = st.get("current")
    entry = (st.get("steps") or {}).get(current, {}) if current else {}
    return {
        "slug": slug, "flow": st["flow"], "form": st.get("form"), "risk": st.get("risk"),
        "work_type": st.get("work_type"), "work_id": st["work_id"], "status": st["status"],
        "state": _shown_state(st), "step": current, "visit": entry.get("visits"),
        "max_visits": entry.get("max_visits"), "transitions": st.get("transitions"),
        "transition_cap": st.get("transition_cap"), "waiting": st.get("waiting"), "halt": st.get("halt"),
        "chain": logs.head12(pkg / engine.TRANSITIONS_LOG), "degraded": st.get("degraded") or [],
    }


def _status(args) -> int:
    out = args.out
    slugs = [state_mod.resolve_slug(args.project, args.slug)] if args.slug else state_mod.find_active(args.project)
    summaries = []
    for slug in slugs:
        try:
            summaries.append(_summary(args.project, slug))
        except SdlcError as exc:
            if args.slug:
                raise
            summaries.append({"slug": slug, "error": exc.message})
    last = next((s for s in reversed(summaries) if "error" not in s), None)
    final = "state=%s chain=%s\n" % ((last["state"], last["chain"]) if last else ("none", ZERO_CHAIN))
    if args.json:
        out.write(json.dumps({"schema": "agentic-sdlc/status@1", "packages": summaries}, ensure_ascii=False,
                             sort_keys=True) + "\n")
    elif args.brief:
        for item in summaries:
            if "error" in item:
                out.write("sdlc package=%s error=%s\n" % (item["slug"], item["error"]))
                continue
            out.write("sdlc package=%s flow=%s state=%s step=%s visit=%s/%s chain=%s\n" % (
                item["slug"], item["flow"], item["state"], item["step"] or "none",
                item["visit"] if item["visit"] is not None else 0, item["max_visits"] or 0, item["chain"]))
    else:
        if not summaries:
            out.write("No active flow in this project.\n")
        for item in summaries:
            if "error" in item:
                out.write("package=%s error=%s\n" % (item["slug"], item["error"]))
                continue
            out.write("package=%s flow=%s form=%s risk=%s work_type=%s status=%s\n" % (
                item["slug"], item["flow"], item["form"], item["risk"], item["work_type"], item["status"]))
            out.write("  state=%s step=%s visit=%s/%s transitions=%s/%s\n" % (
                item["state"], item["step"] or "none", item["visit"] or 0, item["max_visits"] or 0,
                item["transitions"], item["transition_cap"]))
            if item["halt"]:
                out.write("  halted: %s\n" % json.dumps(item["halt"].get("reason"), ensure_ascii=False))
    out.write(final)
    return 0


# --- entry -------------------------------------------------------------------------------------

def _dispatch(args) -> int:
    handler = args.handler
    if getattr(args, "needs_ctx", False):
        ctx = _context(args)
        return handler(ctx, args, out=args.out, save_state=state_mod.red_saver(ctx.pkg))
    return handler(args)


def _chain(args) -> str:
    pkg = getattr(args, "_pkg", None)
    if pkg is None:
        return ZERO_CHAIN
    try:
        return logs.head12(Path(pkg) / engine.TRANSITIONS_LOG)
    except SdlcError:
        return ZERO_CHAIN


def main(argv=None, *, out=None, root=None) -> int:
    """Run one command. `out` (default stdout, reconfigured to UTF-8) receives everything printed;
    `root` (default: this runner's plugin root) is where the flows are read from (tests)."""
    if out is None:
        utf8_output()
        out = sys.stdout
    parser = build_parser()
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    except _UsageError as exc:
        out.write("error=usage:%s\n" % _one_line(exc.message))
        out.write(exc.usage if exc.usage.endswith("\n") else exc.usage + "\n")
        out.write("state=error chain=%s\n" % ZERO_CHAIN)
        return 2
    args.out = out
    args.root = Path(root) if root is not None else paths.plugin_root()
    args._pkg = None
    try:
        args.project = paths.project_root(Path.cwd(), override=args.project)
        return _dispatch(args)
    except SdlcError as exc:
        out.write("error=%s\n" % _one_line(exc.message))
        out.write("state=%s chain=%s\n" % (_STATE_FOR_CODE.get(exc.code, "error"), _chain(args)))
        return exc.code
    except Exception as exc:  # a runner bug: still one error line and exit 2, never a traceback
        out.write("error=internal:%s:%s\n" % (type(exc).__name__, _one_line(exc)[:200]))
        out.write("state=error chain=%s\n" % _chain(args))
        return 2
