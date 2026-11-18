"""End-to-end flows of the sdlc runner (plan Task 9, the end-to-end half).

Contract: docs/agentic-sdlc/notes/2026-10-22-runner-contract.md §3 (state.json), §5 (named sets),
§8 (`next`, fix rounds), §9 (strategy, mandated fresh keys), §10 (the spec/plan loop, ingest),
§12 (`sdlc run`), §13 (the CLI's last line), §14 (cards), §15 (every flow end to end).

Each test drives a real flow (flows/*.json) from `start` to its end through the in-process CLI,
on the harness of tests/test_sdlc_engine.py and tests/test_sdlc_loop.py
(a temp plugin root with the real flows, the role files and the contracts; a temp git project).
The test plays the model: it does what each card asks (the context report, design.md, the spec and the
plan the main loop writes, the spec reader's answer at the card's write path, each loop role's output
under `--option loop`, the reports), records RED and GREEN runs through `sdlc run` with the
guarded fake test runner, creates the work branch in the temp repo, and records the user's reply at
the gate. The assertions read only what the runner wrote: the cards' `state=` and `chain=` lines,
state.json, the hash-chained logs and the package files.

No model and no paid CLI runs. PATH holds only the fake `pytest` launcher and git, runexec._spawn
starts only that launcher (EngineCase), and every subprocess the runner or the test starts must be
git or that launcher (a guard on subprocess.Popen fails the test on anything else).

Packaging (plan Task 9, the packaging half; SdlcPackagingTests). Every archive kind ships the runner
entry `scripts/sdlc.py`, its package `scripts/sdlc_runner/` and `flows/` byte for byte (contract §1:
"shipped by every release target and adapter package"). The public skills-only package has no
`agents/`, so `loop.role_path` must find each loop role under the projected
`skills/using-agentic-sdlc/references/roles/` there (contract §10), while the release archive keeps
`agents/`. Archives are built from the committed HEAD tree, the way a release is. The public
projection rewrites `<runtime-root>/<path>` references to source-only paths as "(source checkout
only)"; the runner's paths are shipped, so they must come through unchanged. Those tests start only
git (through build_release) and the current Python interpreter on the extracted runner.
"""
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"
for folder in (REPO / "scripts", TESTS):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
if str(REPO) not in sys.path:  # for `scripts.build_release`; appended so it shadows nothing above
    sys.path.append(str(REPO))

from test_sdlc_engine import (CHAIN_LINE, DESIGN_BODY, GIT, PLAN_BODY, SPEC_BODY, SPECLESS_PLAN_BODY,  # noqa: E402
                              TWOGATE_SPEC, WINDOWS, card_fields, card_value)
from test_sdlc_loop import CLEAN, NO_SUBAGENTS, LoopCase, _result  # noqa: E402
from sdlc_runner import frontmatter, logs, textio  # noqa: E402
from sdlc_runner import state as sdlc_state  # noqa: E402
from scripts import build_release  # noqa: E402

def default_steps(flow_id, form="gated", options=(), imported=False) -> list:
    """The steps a finished run of a real flow records, in order (hybrid spec/plan design §3), read from
    flows/<id>.json: a step applies when its `form`, `option`, `not_option` and `imported` conditions hold.
    A probe-gated step (docs-check, quality-gates) is left out: the temp project has no dependency to
    document and no toolchain to gate."""
    flow = json.loads((REPO / "flows" / (flow_id + ".json")).read_text(encoding="utf-8"))
    found = []
    for step in flow["steps"]:
        when = step.get("applies_when") or {}
        holds = (when.get("form", form) == form and when.get("option", "any") in tuple(options) + ("any",)
                 and when.get("not_option") not in options and when.get("imported", imported) == imported
                 and "probe" not in when)
        if holds:
            found.append(step["id"])
    return found


# The steps a finished run did: the default shape of each real flow, and the opt-in loop variants.
FLOW_STEPS = {flow_id: default_steps(flow_id) for flow_id in ("feature", "full", "spec", "plan", "bugfix")}
LOOP_STEPS = default_steps("feature", options=("loop",))
BUGFIX_LOOP_STEPS = default_steps("bugfix", options=("loop",))
SCOPE = "# Context\n\n## Scope Lock\n\nOnly the report page and its new export.\n"
RUN_LINE = r"run_seq=\d+ exit=%d valid=yes reason=\S+ chain=[0-9a-f]{12}$"
DECISION = {"id": "DP1", "question": "CSV only?", "options": ["CSV", "CSV and JSON"], "recommendation": "CSV"}
# runexec._windows_command_line: `"<comspec>" /d /s /c ""<shim>" <args>"` for a Windows .cmd launcher.
CMD_LINE = re.compile(r'"([^"]+)" /d /s /c ""([^"]+)"')


def _taskkill():
    """The exact taskkill.exe runexec._kill_tree starts on Windows to end a timed-out run's tree."""
    root = os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT")
    if not WINDOWS or not root:
        return None
    return os.path.normcase(os.path.join(root, "System32", "taskkill.exe"))
BUGFIX_REQUEST = "Fix add: it drops the sign of a negative first number.\n"
# A spec-less bugfix plan (design §5.19): its bug and its criteria come before the first task.
BUGFIX_PLAN_BODY = (
    "# Bugfix plan: add drops the sign of the first number\n\n"
    "## Bug\n\n"
    "Expected: add(-2, 3) returns 1. Actual: it returns 5, because the sign of the first number is dropped.\n"
    "Reproduction: call add(-2, 3) from a Python shell and compare the result with the true sum.\n\n"
    "## Acceptance Criteria\n\n"
    "- AC1: Given a negative first number, when add runs, then it returns the true sum of both numbers.\n\n"
    "## Task 1: Keep the sign of the first number (AC1)\n\n"
    "Modify `src/app.py` and its test `tests/test_app.py`.\n\n"
    "- RED: write the failing test for AC1 first.\n- Run: `pytest tests/test_app.py`\n"
)
# What the user's pre-approval covers: the request holds it, so nobody is there to ask and every decision of
# the design is an author's call (hybrid design §4.1).
PREAPPROVED_REQUEST = "Add a CSV export to the report page. Go ahead without asking me again.\n"
PREAPPROVAL_QUOTE = "Go ahead without asking me again"
UNATTENDED_DESIGN = DESIGN_BODY.replace("(user)", "(author's call: nobody was there to ask)")
# A reader question the user's answer settled becomes a criterion of its own, sourced from that question.
ANSWERED_AC = ("\n- AC2: Given a report with hidden rows, when the user exports it, then the CSV file skips them. "
               "(source: Q1)")
TWO_AC_SPEC = TWOGATE_SPEC.replace("every visible row. (source: D1)", "every visible row. (source: D1)" + ANSWERED_AC)
TWO_AC_PLAN = PLAN_BODY.replace("(AC1)", "(AC1, AC2)")
# With the intent given to another plugin there is no design.md, so a criterion can cite only the request
# or a reader question.
REQUEST_SOURCED_SPEC = SPEC_BODY.replace("every visible row.", "every visible row. (source: request)")
DEFAULT_CAPABILITIES = "workflow=no,subagent=yes,team=no"
# A runtime with no sub-agent tool runs each fresh role inline and says so (hybrid design §4.3).
NO_SUBAGENT_STRATEGY = ("spec-check=inline-degraded:no sub-agent tool", "security=inline-degraded:no sub-agent tool",
                        "audit=inline-degraded:no sub-agent tool")


class FlowCase(LoopCase):
    """LoopCase plus a fail-closed guard on every subprocess and the model's side of each card."""

    def setUp(self):
        super().setUp()
        self.cards = {}
        real = subprocess.Popen
        case = self

        class GuardedPopen(real):
            def __init__(self, args, *rest, **kwargs):
                case.check_program(args)
                super().__init__(args, *rest, **kwargs)

        patcher = mock.patch.object(subprocess, "Popen", GuardedPopen)
        patcher.start()
        self.addCleanup(patcher.stop)

    def check_program(self, args):
        """Only git, the fake test runner's launchers and runexec's Windows tree kill may start."""
        if isinstance(args, (list, tuple)) and args:
            program = os.path.normcase(str(args[0]))
            if program in self.allowed or program == os.path.normcase(GIT) or program == _taskkill():
                return
        elif WINDOWS and isinstance(args, str):  # runexec hands cmd.exe one line for a .cmd launcher
            match = CMD_LINE.match(args)
            if (match and os.path.basename(os.path.normcase(match.group(1))) == "cmd.exe"
                    and os.path.normcase(match.group(2)) in self.allowed):
                return
        raise AssertionError("unexpected subprocess: %r" % (args,))

    # -- cards ---------------------------------------------------------------------------------

    def expect(self, text, state, step=None) -> dict:
        """The card's fields, after checking its state, its step and its last line (contract §13)."""
        fields = card_fields(text)
        self.assertEqual(fields.get("state"), state, text)
        if step is not None:
            self.assertEqual(fields.get("step"), step, text)
        last = text.splitlines()[-1]
        self.assertRegex(last, CHAIN_LINE)
        self.assertTrue(last.startswith("state=%s chain=" % state), last)
        return fields

    def step(self, slug, state="do", step=None, expect=0) -> tuple:
        """`sdlc next` and its card's fields."""
        code, text = self.next(slug, expect=expect)
        return text, self.expect(text, state, step)

    def role_is(self, fields, role, round_text):
        self.assertEqual((fields.get("step"), fields.get("role"), fields.get("round")), ("draft", role, round_text),
                         fields)

    def write_role(self, fields, text) -> Path:
        """What a role's sub-agent (or the model, inline) does: write its result at the card's write path."""
        target = self.project.joinpath(*fields["write"].split("/"))
        target.write_bytes(text.encode("utf-8"))
        return target

    # -- the model's work ----------------------------------------------------------------------

    def begin(self, slug, flow="feature", work_type="feature", capabilities="workflow=no,subagent=yes,team=no",
              overrides=()) -> tuple:
        """start --option loop -> strategy confirm -> context report (-> the design, where the flow has an
        intent step); returns the first draft card."""
        code, text = self.start("--option", "loop", flow=flow, work_type=work_type, runtime="codex", work_id=slug)
        self.expect(text, "do", "strategy")
        self.confirm_strategy(slug, capabilities, *overrides)
        text, fields = self.step(slug, step="context")
        self.assertEqual(fields["pending"], "report", text)
        self.put("context.md", SCOPE, slug)
        if flow == "bugfix":
            return self.step(slug, step="draft")
        return self.design(slug)

    def design(self, slug, then="draft") -> tuple:
        """The intent card's work: design.md with its four sections and owned decisions."""
        text, fields = self.step(slug, step="intent")
        self.assertEqual((fields["pending"], fields["may_ask"]), ("validator", "design"), text)
        self.put("design.md", DESIGN_BODY, slug)
        return self.step(slug, step=then)

    def spec_plan_authors(self, text, slug) -> tuple:
        """Round 0 of spec+plan, each role written at its card's write path; returns the critic card."""
        fields = card_fields(text)
        self.role_is(fields, "author-spec", "0/3")
        self.write_role(fields, SPEC_BODY)
        text, fields = self.step(slug, step="draft")
        self.role_is(fields, "author-plan", "0/3")
        self.write_role(fields, PLAN_BODY)
        text, fields = self.step(slug, step="draft")
        self.role_is(fields, "critic", "1/3")
        return text, fields

    def approve_at_gate(self, text, slug):
        fields = self.expect(text, "wait-gate", "review")
        self.approve(text, slug)
        return fields

    def make_branch(self, slug, branch):
        """The branch card on main, then a work branch created in the temp repo."""
        text, fields = self.step(slug, step="branch")
        self.assertEqual((fields["pending"], fields["may_ask"]), ("branch_ok", "consent"), text)
        self.git("checkout", "-q", "-b", branch)
        return self.step(slug, step="implement")

    def sdlc_ok(self, *argv) -> str:
        code, out = self.sdlc(*argv)
        self.assertEqual(code, 0, out)
        self.assertRegex(out.splitlines()[-1], CHAIN_LINE)
        return out

    def record_run(self, slug, expect, *argv) -> str:
        """`sdlc run` of the fake test runner: RED (`--expect fail`) or GREEN (`--expect pass`)."""
        code, out = self.sdlc("run", "--slug", slug, "--expect", expect, "--label", "red" if expect == "fail" else "green",
                              "--", "pytest", *argv)
        self.assertEqual(code, 1 if expect == "fail" else 0, out)
        self.assertRegex(out.splitlines()[-1], RUN_LINE % (1 if expect == "fail" else 0))
        return out

    def red_then_green(self, slug, test_rel, test_text, source_rel, source_text):
        """The implement card's work: a failing test (RED), the source change, the passing run (GREEN)."""
        self.write(test_rel, test_text.encode("utf-8"))
        self.record_run(slug, "fail", "--say=pytest-fail", "--exit=1")
        self.assertEqual(self.state(slug)["red"], {"recorded": True, "order": "ok"})
        self.write(source_rel, source_text.encode("utf-8"))
        self.record_run(slug, "pass", "--say=pytest-pass")
        self.put("evidence/%s.tdd.md" % slug, "# TDD evidence\n\nRED: %s failed first. GREEN: it passes.\n" % test_rel,
                 slug)

    def security_pass(self, slug):
        self.put("evidence/%s.security.md" % slug, "# Security review\n\nNo finding.\nVerdict: pass\n", slug)

    def audit_and_claim(self, slug):
        """The audit report (its resolver_ok and GREEN checks are the runner's), then the claim."""
        self.put("evidence/%s.audit.md" % slug, "# Implementation audit\n\nEvery task is done.\n", slug)
        text, fields = self.step(slug, step="claim")
        self.put("evidence/%s.claim.md" % slug, "# Completion claim\n\nDone, with the evidence above.\n", slug)
        return self.step(slug, state="complete")

    def feature_to_security(self, slug):
        """The feature flow on codex with sub-agents (the default path: intent, plan, one gate), from
        start to the security card."""
        code, text = self.start(flow="feature", work_type="feature", runtime="codex", work_id=slug)
        return self.play(slug, text=text, stop="security")

    # -- the main loop's side of the default path (hybrid design §4) ---------------------------

    def play(self, slug, text=None, stop=None, capabilities=DEFAULT_CAPABILITIES, overrides=(), reader=(),
             quote=None, design=DESIGN_BODY, plan=None, branch=None):
        """The model's work from the current card (`text`, else `sdlc card`) to the end of the flow, or to
        the card of step `stop`, returned as (text, fields) before that step's work is done (a gate's card
        before it is approved).

        `reader` is the spec reader's questions, one `(pile, extra check-resolve args)` each; `quote`
        approves every gate as the original request's pre-approval; `plan` is the plan body, else the one
        the package calls for. Every `do` card is kept in `self.cards[(slug, step)]`."""
        if text is None:
            code, text = self.card(slug)
        for _ in range(80):
            fields = card_fields(text)
            step = fields.get("step")
            if fields.get("state") == "complete":
                return text, fields
            if step == stop:
                return text, fields
            if fields["state"] == "wait-gate":
                if quote is None:
                    self.approve(text, slug, gate=step)
                else:
                    self.approve(text, slug, gate=step, source="original-request", quote=quote)
            else:
                self.expect(text, "do", step)
                self.cards[(slug, step)] = text
                if fields.get("mechanism") == "inline-degraded":
                    self.sdlc_ok("note", "--slug", slug, "--degraded", "subagent", "--reason", "missing")
                self.work(slug, step, fields, capabilities, overrides, reader, design, plan, branch)
            code, text = self.next(slug)
        self.fail("the flow did not end: %s" % text)

    def work(self, slug, step, fields, capabilities, overrides, reader, design, plan, branch):
        """What the model does for one `do` card of the main-loop path."""
        pkg = self.pkg(slug)
        if step == "strategy":
            self.confirm_strategy(slug, capabilities, *overrides)
        elif step == "context":
            self.put("context.md", SCOPE, slug)
        elif step == "intent":
            self.put("design.md", design, slug)
        elif step == "spec":
            self.put("spec/%s.md" % slug, TWOGATE_SPEC, slug)
        elif step == "spec-check":
            self.read_spec(slug, fields, ["Question %d?" % n for n in range(1, len(reader) + 1)])
            for n, (pile, extra) in enumerate(reader, 1):
                self.sdlc_ok("check-resolve", "--slug", slug, "--id", "Q%d" % n, "--pile", pile,
                             "--resolution", "Settled as %s." % pile, *extra)
        elif step == "plan":
            if plan is None:
                has_spec = (pkg / "spec" / ("%s.md" % slug)).is_file()
                plan = BUGFIX_PLAN_BODY if self.state(slug)["flow"] == "bugfix" else (
                    PLAN_BODY if has_spec else SPECLESS_PLAN_BODY)
            self.put("plan/%s.md" % slug, plan, slug)
        elif step == "branch":
            self.git("checkout", "-q", "-b", branch or "work/" + slug)
        elif step == "implement":
            self.red_then_green(slug, "tests/test_export.py", "def test_export():\n    assert False\n",
                                "src/export.py", "def export(rows):\n    return rows\n")
        elif step == "diff-review":
            self.put("evidence/%s.diff.md" % slug, "# Diff review\n\nThe diff holds only the planned files.\n", slug)
        elif step == "security":
            self.security_pass(slug)
        elif step == "audit":
            self.put("evidence/%s.audit.md" % slug, "# Implementation audit\n\nEvery task is done.\n", slug)
        elif step == "claim":
            self.put("evidence/%s.claim.md" % slug, "# Completion claim\n\nDone, with the evidence above.\n", slug)
        else:
            self.fail("no work for step %r: %s" % (step, fields))

    def read_spec(self, slug, fields, questions):
        """The spec reader's part: its answer at the card's write path, recorded with `check-record`."""
        self.assertEqual(fields["role"], "spec-builder-check", fields)
        answer = {"questions": [{"question": q, "why": "the plan depends on the answer"} for q in questions]}
        self.write_role(fields, json.dumps(answer))
        return self.sdlc_ok("check-record", "--slug", slug)

    def ask_the_user(self, slug, question, quote) -> int:
        """A design question and the user's reply (`sdlc ask`, the run waits, `sdlc answer`); returns the
        answer record's seq."""
        self.sdlc_ok("ask", "--slug", slug, "--kind", "design", "--question", question)
        text, fields = self.step(slug, state="wait-answer")
        self.sdlc_ok("answer", "--slug", slug, "--quote", quote)
        return [r for r in logs.read(self.pkg(slug) / "questions.jsonl") if r["kind"] == "answer"][-1]["seq"]

    def approvals(self, slug) -> list:
        """(gate, source, critic) of each approval the runner recorded."""
        return [(r["gate"], r["source"], r["critic"]) for r in logs.read(self.pkg(slug) / "approvals.jsonl")
                if r["kind"] == "approve"]

    def author_calls(self, text) -> list:
        """(id, file) of each `author_call=` line of a claim card."""
        calls = [json.loads(line[len("author_call="):]) for line in text.splitlines() if line.startswith("author_call=")]
        return [(c["id"], c["from"]) for c in calls]

    # -- what the runner left behind -----------------------------------------------------------

    def meta(self, rel, slug) -> dict:
        return frontmatter.split((self.pkg(slug) / rel).read_text(encoding="utf-8"))[0]

    def runs(self, slug) -> list:
        return [r for r in logs.read(self.pkg(slug) / "runs.jsonl") if r["kind"] == "finished"]

    def assert_completed(self, text, slug, steps):
        """A finished flow: every step done once and in order, the chains intact, nothing active."""
        st = self.state(slug)
        self.assertEqual((st["status"], st["current"], st["waiting"]), ("complete", None, None))
        self.assertEqual([r["step"] for r in self.records("done", slug)], steps)
        self.assertEqual([r["step"] for r in self.records("enter", slug)], steps)
        self.assertEqual({sid: st["steps"][sid]["visits"] for sid in steps}, {sid: 1 for sid in steps})
        self.assertEqual(self.transitions(slug)[-1]["kind"], "complete")
        for name in ("transitions.jsonl", "runs.jsonl", "approvals.jsonl"):
            self.assertTrue(logs.verify(self.pkg(slug) / name)[0], name)
        self.assertEqual(text.splitlines()[-1], "state=complete chain=%s" % logs.head12(self.pkg(slug) / "transitions.jsonl"))
        runs = self.runs(slug)
        if "implement" in steps:
            self.assertEqual([(r["label"], r["expect"], r["exit"], r["valid"]) for r in runs],
                             [("red", "fail", 1, True), ("green", "pass", 0, True)])
            self.assertEqual(runs[0]["changed_source_count"], 0)  # RED ran before any source change
        else:
            self.assertEqual(runs, [])
        self.assertEqual(sdlc_state.find_active(self.project), [])
        code, again = self.next(slug)
        self.expect(again, "complete")


class TestFlowsEndToEnd(FlowCase):
    def test_subprocess_guard_refuses_other_programs(self):
        # The guard is live: a program that is not git or a launcher never starts, and a command line
        # that names a launcher but is not cmd.exe running it is refused too.
        launcher = sorted(self.allowed)[0]
        for args in ([sys.executable, "-c", "pass"], '"%s" /d /s /c ""%s""' % (sys.executable, launcher)):
            with self.subTest(args=args):
                with self.assertRaises(AssertionError) as raised:
                    subprocess.Popen(args)
                self.assertIn("unexpected subprocess", str(raised.exception))

    def test_loop_option_runs_the_old_loop_end_to_end(self):
        import resolve_work_package

        slug = "demo"
        code, text = self.start("--option", "loop", flow="feature", work_type="feature", runtime="codex", work_id=slug)
        fields = self.expect(text, "do", "strategy")
        self.assertIn("draft:runner-loop", fields["default"])
        self.confirm_strategy(slug)
        text, fields = self.step(slug, step="context")
        self.put("context.md", SCOPE, slug)
        text, fields = self.design(slug)
        self.assertEqual(fields["mechanism"], "runner-loop")
        self.assertIn("spawn_agent", fields["delegate"])  # codex: each role a fresh sub-agent
        # The runner-loop roles: the test writes each role's output at its card's write path, and the
        # spec author also leaves a decision point for the gate (the role's `decisions` output).
        textio.write_json_atomic(self.draft("decisions.author-spec.r0.json", slug), [DECISION])
        text, fields = self.spec_plan_authors(text, slug)
        self.assertTrue(self.draft("validator.r1.json", slug).is_file())  # draft-check ran before the critic card
        self.write_role(fields, CLEAN)
        # The clean critic stops the loop: in this `next` the runner writes loop.json and result.json
        # itself, ingests them as the spec and the plan, and the gate waits for the user's reply.
        text, fields = self.step(slug, state="wait-gate", step="review")
        self.assertEqual(textio.read_json(self.draft("loop.json", slug)),
                         {"schema": "agentic-sdlc/loop@1", "engine": "runner-loop", "mode": "spec+plan", "rounds": 1,
                          "stopReason": "clean", "critic": ["fresh"]})
        result = textio.read_json(self.draft("result.json", slug))
        self.assertEqual((result["engine"], result["rounds"], result["stopReason"], result["critic"]),
                         ("runner-loop", 1, "clean", "fresh"))
        self.assertEqual((result["spec"]["markdown"], result["plan"]["markdown"]), (SPEC_BODY, PLAN_BODY))
        self.assertEqual(result["decisionPoints"], [DECISION])
        self.assertIn('decision_point={"id": "DP1"', text)
        self.assertEqual(self.state(slug)["loop"]["critic"], ["fresh"])
        self.assertEqual(self.records("round", slug)[-1]["ingested"], ["spec/demo.md", "plan/demo.md"])
        self.assertEqual(self.meta("plan/demo.md", slug)["spec"], "../spec/demo.md")
        for name in ("spec", "plan"):
            sidecar = textio.read_json(self.pkg(slug) / name / "demo.review.json")
            self.assertEqual((sidecar["stopReason"], sidecar["critic"], sidecar["engine"]), ("clean", "fresh", "runner-loop"))
        # A hand-written result cannot replace the ingested one: the flow has left the loop step.
        textio.write_json_atomic(self.draft("result.json", slug), _result())
        code, out = self.sdlc("ingest-draft", "--slug", slug)
        self.assertEqual(code, 4, out)
        self.assertIn("error=not_current_step:review", out)
        self.assertEqual(card_value(text, "artifacts"), "spec/demo.md,plan/demo.md")
        self.assertEqual(self.meta("spec/demo.md", slug)["status"], "reviewed")
        self.approve_at_gate(text, slug)
        text, fields = self.make_branch(slug, "work/demo")
        self.assertEqual(fields["pending"], "run_recorded,report")
        plan_meta = self.meta("plan/demo.md", slug)
        self.assertEqual((plan_meta["branch"], plan_meta["status"]), ("work/demo", "in_progress"))
        # RED, the source edit, GREEN; the runner judges the order from the git sets.
        self.red_then_green(slug, "tests/test_export.py", "def test_export():\n    assert False\n",
                            "src/export.py", "def export(rows):\n    return rows\n")
        text, fields = self.step(slug, step="security")
        self.assertEqual(fields["mechanism"], "subagent")
        self.security_pass(slug)
        # resolver_ok runs the real resolver on the package: a second plan in it is a malformed
        # package the resolver refuses, and the audit waits on resolver_ok until it is gone.
        stray = self.pkg(slug) / "plan" / "stray.md"
        stray.write_bytes(b"---\nwork_id: stray\n---\n# Stray plan\n")
        text, fields = self.step(slug, step="audit")
        self.assertEqual(fields["mechanism"], "subagent")
        self.assertIn("resolver_ok", fields["pending"].split(","), text)
        self.assertIn("malformed_package", text)
        stray.unlink()
        text, fields = self.step(slug, step="audit")
        self.assertEqual(fields["pending"], "report")  # resolver_ok and the GREEN run pass again
        text, fields = self.audit_and_claim(slug)
        self.assert_completed(text, slug, LOOP_STEPS)
        for name in ("spec", "plan"):
            self.assertEqual(self.meta("%s/demo.md" % name, slug)["status"], "complete", name)
        approval = [r for r in logs.read(self.pkg(slug) / "approvals.jsonl") if r["kind"] == "approve"]
        self.assertEqual([(r["gate"], r["source"], r["critic"]) for r in approval], [("review", "reply", "fresh")])
        resolution = resolve_work_package.resolve(self.project, branch="work/demo")
        self.assertTrue(resolution.ok, resolution.errors)
        self.assertEqual((resolution.source, resolution.plan, resolution.spec),
                         ("branch", self.pkg(slug) / "plan" / "demo.md", self.pkg(slug) / "spec" / "demo.md"))

    def test_feature_flow_end_to_end(self):
        import resolve_work_package

        slug = "demo"
        code, text = self.start(flow="feature", work_type="feature", runtime="codex", work_id=slug)
        fields = self.expect(text, "do", "strategy")
        self.assertEqual(FLOW_STEPS["feature"], ["strategy", "context", "intent", "plan", "plan-review", "branch",
                                                 "implement", "security", "audit", "claim"])
        self.assertNotIn("draft", fields["default"])  # the main loop writes: no loop, no reader
        self.assertNotIn("spec-check", fields["default"])
        text, fields = self.play(slug, text=text, stop="intent")
        self.assertEqual((fields["pending"], fields["may_ask"]), ("validator", "design"), text)
        # One design question, asked and answered through the runner; design.md is the record of the answer.
        seq = self.ask_the_user(slug, "Stream the rows or build the file first?", "Stream them.")
        asked = [r for r in logs.read(self.pkg(slug) / "questions.jsonl") if r["kind"] == "ask"]
        self.assertEqual([(r["ask_kind"], r["step"]) for r in asked], [("design", "intent")])
        self.assertEqual(seq, 2)
        text, fields = self.play(slug, stop="plan")
        self.assertEqual((self.pkg(slug) / "design.md").read_text(encoding="utf-8"), DESIGN_BODY)
        text, fields = self.play(slug, text=text, stop="plan-review")
        self.assertEqual((fields["state"], card_value(text, "artifacts")), ("wait-gate", "plan/demo.md"))
        self.assertFalse((self.pkg(slug) / "spec").exists())
        self.assertEqual(self.meta("plan/demo.md", slug),
                         {"work_id": slug, "spec": "none", "branch": "main", "flow": "feature", "status": "reviewed"})
        text, fields = self.play(slug, text=text)
        self.assert_completed(text, slug, FLOW_STEPS["feature"])
        self.assertEqual(self.approvals(slug), [("plan-review", "reply", "none")])
        self.assertEqual(self.meta("plan/demo.md", slug),
                         {"work_id": slug, "spec": "none", "branch": "work/demo", "flow": "feature",
                          "status": "complete"})
        # The audit grades the plan's own criteria: the resolver finds no spec and says so.
        resolution = resolve_work_package.resolve(self.project, branch="work/demo")
        self.assertTrue(resolution.ok, resolution.errors)
        self.assertEqual((resolution.plan, resolution.spec), (self.pkg(slug) / "plan" / "demo.md", None))
        self.assertIn("spec=none", resolve_work_package.fields_for(resolution, self.project))
        audit = self.cards[(slug, "audit")]
        self.assertEqual(card_fields(audit)["inputs"], "@source,@tests,plan/demo.md")  # no spec to grade against
        step_file = (REPO / "skills" / "implementation-control" / "steps" / "audit.md").read_text(encoding="utf-8")
        self.assertIn("grade against the plan's own `## Acceptance Criteria`", step_file)
        calls = self.author_calls(self.cards[(slug, "claim")])
        self.assertEqual(calls, [("D2", "design.md")])  # the claim lists the design's author's call

    def test_feature_with_spec_option_end_to_end(self):
        import resolve_work_package

        slug = "withspec"
        steps = FLOW_STEPS["feature"][:3] + ["spec", "spec-check", "spec-review"] + FLOW_STEPS["feature"][3:]
        self.assertEqual(default_steps("feature", options=("spec",)), steps)
        code, text = self.start("--option", "spec", flow="feature", work_type="feature", runtime="codex", work_id=slug)
        fields = self.expect(text, "do", "strategy")
        self.assertIn("spec-check:subagent", fields["default"])
        text, fields = self.play(slug, text=text, stop="spec-check")
        # The reader's card: a role, its prompt, the path it writes its answer to, and the delegation text.
        self.assertEqual((fields["role"], fields["mechanism"], fields["inputs"]),
                         ("spec-builder-check", "subagent", "design.md"))
        self.assertTrue(fields["write"].endswith("/draft/check.answer.json"), fields)
        self.assertIn("spawn_agent", fields["delegate"])
        self.assertTrue(fields["prompt"].endswith("/draft/prompts/spec-builder-check.md"), fields)
        text, fields = self.play(slug, text=text, stop="spec-review", reader=[("minor", ())])
        self.assertEqual(self.meta("spec/%s.md" % slug, slug), {"work_id": slug, "status": "reviewed"})
        self.assertEqual(card_value(text, "artifacts"), "design.md,spec/%s.md" % slug)
        self.assertIn('settled_minor={"id": "Q1"', text)
        check = textio.read_json(self.pkg(slug) / "spec" / (slug + ".check.json"))
        self.assertEqual((check["reader"], [(q["id"], q["pile"], q["author_call"]) for q in check["questions"]]),
                         ("fresh", [("Q1", "minor", True)]))
        text, fields = self.play(slug, text=text, stop="plan")  # the spec gate approved by the user's reply
        self.assertEqual(self.meta("spec/%s.md" % slug, slug), {"work_id": slug, "status": "approved"})
        text, fields = self.play(slug, text=text, stop="plan-review")
        self.assertEqual(self.meta("plan/%s.md" % slug, slug),
                         {"work_id": slug, "spec": "../spec/%s.md" % slug, "branch": "main", "flow": "feature",
                          "status": "reviewed"})
        text, fields = self.play(slug, text=text)
        self.assert_completed(text, slug, steps)
        self.assertEqual(self.approvals(slug), [("spec-review", "reply", "fresh"), ("plan-review", "reply", "none")])
        self.assertEqual(self.author_calls(self.cards[(slug, "claim")]),
                         [("D2", "design.md"), ("Q1", "spec/%s.check.json" % slug)])
        for name in ("spec", "plan"):
            self.assertEqual(self.meta("%s/%s.md" % (name, slug), slug)["status"], "complete", name)
        resolution = resolve_work_package.resolve(self.project, branch="work/" + slug)
        self.assertTrue(resolution.ok, resolution.errors)
        self.assertEqual(resolution.spec, self.pkg(slug) / "spec" / (slug + ".md"))

    def test_feature_light_has_no_reader_and_no_gate(self):
        slug = "lite"
        steps = default_steps("feature", form="light", options=("spec",))
        self.assertEqual(steps, ["strategy", "context", "intent", "spec", "plan", "branch", "implement", "security",
                                 "audit", "claim"])
        code, text = self.start("--option", "spec", flow="feature", work_type="feature", form="light",
                                runtime="codex", work_id=slug)
        self.assertNotIn("spec-check", self.expect(text, "do", "strategy")["default"])
        text, fields = self.play(slug, text=text)  # no card waits at a gate on the way
        self.assert_completed(text, slug, steps)
        self.assertEqual(self.approvals(slug), [])
        self.assertFalse((self.pkg(slug) / "spec" / (slug + ".check.json")).exists())
        for sid in ("spec-check", "spec-review", "plan-review"):
            self.assertFalse(self.state(slug)["steps"][sid]["applies"], sid)
        self.assertEqual(self.meta("plan/%s.md" % slug, slug),
                         {"work_id": slug, "spec": "../spec/%s.md" % slug, "branch": "work/lite", "flow": "feature",
                          "status": "complete"})

    def test_full_flow_writes_the_spec_and_passes_both_gates(self):
        slug = "full"
        steps = ["strategy", "context", "intent", "spec", "spec-check", "spec-review", "plan", "plan-review",
                 "branch", "implement", "security", "diff-review", "audit", "claim"]
        self.assertEqual(FLOW_STEPS["full"], steps)
        code, text = self.start(flow="full", work_type="feature", runtime="codex", work_id=slug)
        text, fields = self.play(slug, text=text, stop="spec-check")
        # The reader asks three things: the answer goes into the spec (Q1), the user is asked (Q2), the
        # main loop decides (Q3).
        questions = ["Do hidden rows count?", "Which file name?", "Quote every cell?"]
        self.read_spec(slug, fields, questions)
        (self.pkg(slug) / "spec" / (slug + ".md")).write_bytes(TWO_AC_SPEC.encode("utf-8"))
        self.sdlc_ok("check-resolve", "--slug", slug, "--id", "Q1", "--pile", "answered",
                     "--resolution", "Hidden rows are skipped; AC2 says so.")
        seq = self.ask_the_user(slug, "Which file name?", "report.csv, please.")
        self.sdlc_ok("check-resolve", "--slug", slug, "--id", "Q2", "--pile", "theirs",
                     "--resolution", "The file is report.csv.", "--answer-seq", str(seq))
        self.sdlc_ok("check-resolve", "--slug", slug, "--id", "Q3", "--pile", "minor",
                     "--resolution", "Cells are quoted, as the CSV format says.")
        code, text = self.next(slug)
        fields = self.expect(text, "wait-gate", "spec-review")
        self.assertEqual(card_value(text, "artifacts"), "design.md,spec/%s.md" % slug)
        for pile, qid in (("answered", "Q1"), ("theirs", "Q2"), ("minor", "Q3")):
            self.assertIn('settled_%s={"id": "%s"' % (pile, qid), text)
        text, fields = self.play(slug, text=text, stop="plan")
        self.assertEqual(self.meta("spec/%s.md" % slug, slug), {"work_id": slug, "status": "approved"})
        text, fields = self.play(slug, text=text, plan=TWO_AC_PLAN)
        self.assert_completed(text, slug, steps)
        check = textio.read_json(self.pkg(slug) / "spec" / (slug + ".check.json"))
        self.assertEqual([(q["id"], q["pile"], q["answer_seq"], q["author_call"]) for q in check["questions"]],
                         [("Q1", "answered", None, False), ("Q2", "theirs", seq, False), ("Q3", "minor", None, True)])
        self.assertEqual(self.approvals(slug), [("spec-review", "reply", "fresh"), ("plan-review", "reply", "none")])
        self.assertEqual(self.author_calls(self.cards[(slug, "claim")]),
                         [("D2", "design.md"), ("Q3", "spec/%s.check.json" % slug)])
        self.assertEqual(self.meta("plan/%s.md" % slug, slug),
                         {"work_id": slug, "spec": "../spec/%s.md" % slug, "branch": "work/full", "flow": "full",
                          "status": "complete"})

    def test_spec_flow_ends_at_spec_review(self):
        slug = "specrun"
        self.assertEqual(FLOW_STEPS["spec"], ["strategy", "context", "intent", "spec", "spec-check", "spec-review",
                                              "claim"])
        code, text = self.start(flow="spec", work_type="feature", runtime="codex", work_id=slug)
        text, fields = self.play(slug, text=text, reader=[("minor", ())])
        self.assert_completed(text, slug, FLOW_STEPS["spec"])
        self.assertEqual(self.approvals(slug), [("spec-review", "reply", "fresh")])
        self.assertFalse((self.pkg(slug) / "plan").exists())  # a spec run plans nothing
        self.assertEqual(self.meta("spec/%s.md" % slug, slug)["status"], "complete")
        self.assertEqual(self.author_calls(self.cards[(slug, "claim")]),
                         [("D2", "design.md"), ("Q1", "spec/%s.check.json" % slug)])

    def test_external_intent_does_not_block_the_spec_gate(self):
        # The user gave the design to another plugin: `sdlc external intent` marks the step done and no
        # design.md is written. `approve` checks the spec again, not the intent step's design check on a
        # file the external path never writes.
        slug = "elsewhere"
        code, text = self.start(flow="spec", work_type="feature", runtime="codex", work_id=slug)
        text, fields = self.play(slug, text=text, stop="intent")
        self.write("notes/design-elsewhere.md", b"# A design another plugin wrote\n")
        self.sdlc_ok("external", "intent", "--slug", slug, "--owner", "superpowers:brainstorming",
                     "--artifact", "notes/design-elsewhere.md", "--quote", "Use superpowers for the design.")
        self.assertEqual(self.state(slug)["steps"]["intent"]["external"]["owner"], "superpowers:brainstorming")
        self.assertFalse((self.pkg(slug) / "design.md").exists())
        text, fields = self.step(slug, step="spec")
        self.put("spec/%s.md" % slug, REQUEST_SOURCED_SPEC, slug)
        text, fields = self.step(slug, step="spec-check")
        self.read_spec(slug, fields, [])
        text, fields = self.step(slug, state="wait-gate", step="spec-review")
        self.approve(text, slug, gate="spec-review")
        self.assertEqual(self.approvals(slug), [("spec-review", "reply", "fresh")])
        text, fields = self.play(slug, text=self.next(slug)[1])
        self.assert_completed(text, slug, FLOW_STEPS["spec"])
        self.assertEqual([r.get("cause") for r in self.records("done", slug, step="intent")], ["external"])

    def test_external_intent_gate_still_checks_the_spec(self):
        # Only the external writer is left out: the spec step's own check still runs at approve.
        slug = "elsewhere2"
        code, text = self.start(flow="spec", work_type="feature", runtime="codex", work_id=slug)
        text, fields = self.play(slug, text=text, stop="intent")
        self.write("notes/design-elsewhere.md", b"# A design another plugin wrote\n")
        self.sdlc_ok("external", "intent", "--slug", slug, "--owner", "superpowers:brainstorming",
                     "--artifact", "notes/design-elsewhere.md", "--quote", "Use superpowers for the design.")
        self.step(slug, step="spec")
        spec = self.put("spec/%s.md" % slug, REQUEST_SOURCED_SPEC, slug)
        text, fields = self.step(slug, step="spec-check")
        self.read_spec(slug, fields, [])
        spec.write_bytes(spec.read_bytes().replace(b" (source: request)", b""))
        text, fields = self.step(slug, state="wait-gate", step="spec-review")
        code, out = self.approve(text, slug, gate="spec-review", expect=4)
        self.assertIn("error=artifact_checks_failed:spec:", out)
        self.assertIn("ac_no_source:AC1", out)
        self.assertNotIn("artifact_checks_failed:intent", out)

    def test_intent_redone_in_the_package_after_external_is_checked_again(self):
        slug = "back"
        code, text = self.start(flow="spec", work_type="feature", runtime="codex", work_id=slug)
        text, fields = self.play(slug, text=text, stop="intent")
        self.write("notes/design-elsewhere.md", b"# A design another plugin wrote\n")
        self.sdlc_ok("external", "intent", "--slug", slug, "--owner", "superpowers:brainstorming",
                     "--artifact", "notes/design-elsewhere.md", "--quote", "Use superpowers for the design.")
        # The intent's input changes, so the step runs again in the package and writes design.md itself.
        self.put("context.md", SCOPE + "\nArchived reports export too.\n", slug)
        text, fields = self.step(slug, step="intent")
        self.assertEqual(fields["visit"], "2/3")
        self.put("design.md", DESIGN_BODY, slug)
        text, fields = self.play(slug, text=self.next(slug)[1], stop="spec-review")
        # design.md loses an owner after its step: the gate checks the intent step again.
        (self.pkg(slug) / "design.md").write_bytes(DESIGN_BODY.replace(" (user)", "").encode("utf-8"))
        text, fields = self.step(slug, step="spec")
        spec = self.pkg(slug) / "spec" / (slug + ".md")
        spec.write_bytes(spec.read_bytes() + b"\n- Archived reports keep their export button.\n")
        text, fields = self.step(slug, step="spec-check")
        self.read_spec(slug, fields, [])
        text, fields = self.step(slug, state="wait-gate", step="spec-review")
        code, out = self.approve(text, slug, gate="spec-review", expect=4)
        self.assertIn("error=artifact_checks_failed:intent:", out)
        self.assertIn("decision_missing_owner:D1", out)

    def reread_after_a_design_change(self, slug):
        """A changed design.md while the spec flow waits: the spec is written again (it keeps citing Q1),
        and its reader runs again; returns the spec-check card of the new visit."""
        design = self.pkg(slug) / "design.md"
        design.write_bytes(design.read_text(encoding="utf-8").replace("Rows are streamed.", "Rows are buffered.")
                           .encode("utf-8"))
        text, fields = self.step(slug, step="spec")
        spec = self.pkg(slug) / "spec" / (slug + ".md")
        spec.write_bytes(spec.read_text(encoding="utf-8").replace("(source: D1)", "(source: D1, D2)").encode("utf-8"))
        text, fields = self.step(slug, step="spec-check")
        self.assertEqual(fields["visit"], "2/3")
        return fields

    def test_a_cited_question_keeps_its_id_after_a_design_change(self):
        # The spec cites Q1, the user's answer to "Which file format?". The design changes and the new
        # reader asks something else: that question is Q2, and Q1 still names the answered one.
        slug = "keepq"
        code, text = self.start(flow="spec", work_type="feature", runtime="codex", work_id=slug)
        text, fields = self.play(slug, text=text, stop="spec-check")
        self.read_spec(slug, fields, ["Which file format?"])
        (self.pkg(slug) / "spec" / (slug + ".md")).write_bytes(TWO_AC_SPEC.encode("utf-8"))  # AC2 cites Q1
        seq = self.ask_the_user(slug, "Which file format?", "CSV, please.")
        self.sdlc_ok("check-resolve", "--slug", slug, "--id", "Q1", "--pile", "theirs",
                     "--resolution", "The file is CSV.", "--answer-seq", str(seq))
        text, fields = self.step(slug, state="wait-gate", step="spec-review")
        fields = self.reread_after_a_design_change(slug)
        self.read_spec(slug, fields, ["Which time zone?"])
        check = textio.read_json(self.pkg(slug) / "spec" / (slug + ".check.json"))
        self.assertEqual([(q["id"], q["question"], q["pile"], q["resolution"], q["answer_seq"])
                          for q in check["questions"]],
                         [("Q1", "Which file format?", "theirs", "The file is CSV.", seq),
                          ("Q2", "Which time zone?", None, None, None)])
        self.assertEqual([q.get("visit") for q in check["questions"]], [1, 2])
        self.sdlc_ok("check-resolve", "--slug", slug, "--id", "Q2", "--pile", "minor",
                     "--resolution", "Times are UTC.")
        text, fields = self.step(slug, state="wait-gate", step="spec-review")
        self.assertIn('settled_theirs={"id": "Q1", "question": "Which file format?"', text)
        self.assertIn('settled_minor={"id": "Q2", "question": "Which time zone?"', text)
        self.approve(text, slug, gate="spec-review")
        text, fields = self.play(slug, text=self.next(slug)[1])
        self.assertEqual(fields["state"], "complete", text)
        # The author's calls come from every visit's questions: here the minor Q2 (Q1 was the user's answer).
        self.assertEqual(self.author_calls(self.cards[(slug, "claim")]),
                         [("D2", "design.md"), ("Q2", "spec/%s.check.json" % slug)])

    def test_an_open_question_of_an_old_visit_is_dropped_and_its_id_not_reused(self):
        slug = "dropq"
        code, text = self.start(flow="spec", work_type="feature", runtime="codex", work_id=slug)
        text, fields = self.play(slug, text=text, stop="spec-check")
        self.read_spec(slug, fields, ["Which file format?", "Which delimiter?"])
        self.sdlc_ok("check-resolve", "--slug", slug, "--id", "Q1", "--pile", "minor", "--resolution", "CSV.")
        # Q2 is still open when the design changes: the new visit drops it, and its id stays unused.
        fields = self.reread_after_a_design_change(slug)
        self.read_spec(slug, fields, ["Which time zone?"])
        check = textio.read_json(self.pkg(slug) / "spec" / (slug + ".check.json"))
        self.assertEqual([(q["id"], q["question"], q["pile"]) for q in check["questions"]],
                         [("Q1", "Which file format?", "minor"), ("Q3", "Which time zone?", None)])
        self.assertEqual(check["issued"], 3)
        # A criterion citing the dropped Q2 names an unknown source.
        spec = self.pkg(slug) / "spec" / (slug + ".md")
        spec.write_bytes(spec.read_text(encoding="utf-8").replace("(source: D1, D2)", "(source: Q2)").encode("utf-8"))
        self.sdlc_ok("check-resolve", "--slug", slug, "--id", "Q3", "--pile", "minor", "--resolution", "UTC.")
        text, fields = self.step(slug, state="wait-gate", step="spec-review")
        code, out = self.approve(text, slug, gate="spec-review", expect=4)
        self.assertIn("ac_unknown_source:AC1:Q2", out)

    def approved_spec(self, slug) -> Path:
        source = self.tmp / ("approved-%s.md" % slug)
        source.write_bytes(("---\nwork_id: %s\nstatus: approved\n---\n" % slug + SPEC_BODY).encode("utf-8"))
        return source

    def test_plan_flow_from_an_imported_spec(self):
        slug = "given"
        steps = default_steps("plan", imported=True)
        self.assertEqual(steps, ["strategy", "context", "plan", "plan-review", "claim"])  # no intent
        code, text = self.start("--spec-file", str(self.approved_spec(slug)), flow="plan", work_type="feature",
                                runtime="codex", work_id=slug)
        text, fields = self.play(slug, text=text)
        self.assert_completed(text, slug, steps)
        self.assertFalse((self.pkg(slug) / "design.md").exists())
        self.assertEqual(self.meta("plan/%s.md" % slug, slug),
                         {"work_id": slug, "spec": "../spec/%s.md" % slug, "branch": "main", "flow": "plan",
                          "status": "complete"})
        self.assertEqual(self.approvals(slug), [("plan-review", "reply", "none")])
        # The plan cites the imported spec's criteria; the spec was kept as it came.
        self.assertIn("(AC1)", (self.pkg(slug) / "plan" / (slug + ".md")).read_text(encoding="utf-8"))
        self.assertEqual(self.meta("spec/%s.md" % slug, slug)["status"], "approved")

    def test_plan_flow_without_a_spec_writes_its_own_criteria(self):
        slug = "alone"
        self.assertEqual(FLOW_STEPS["plan"], ["strategy", "context", "intent", "plan", "plan-review", "claim"])
        code, text = self.start(flow="plan", work_type="feature", runtime="codex", work_id=slug)
        text, fields = self.play(slug, text=text)
        self.assert_completed(text, slug, FLOW_STEPS["plan"])
        self.assertTrue((self.pkg(slug) / "design.md").is_file())
        self.assertFalse((self.pkg(slug) / "spec").exists())
        self.assertEqual(self.meta("plan/%s.md" % slug, slug),
                         {"work_id": slug, "spec": "none", "branch": "main", "flow": "plan", "status": "complete"})
        body = frontmatter.split((self.pkg(slug) / "plan" / (slug + ".md")).read_text(encoding="utf-8"))[1]
        self.assertEqual(body, SPECLESS_PLAN_BODY)
        self.assertLess(body.index("## Acceptance Criteria"), body.index("## Task 1"))  # criteria come first

    def test_bugfix_flow_plan_gate_only(self):
        import resolve_work_package

        slug = "fix-add"
        self.assertEqual(FLOW_STEPS["bugfix"], ["strategy", "context", "plan", "plan-review", "branch", "implement",
                                                "security", "audit", "claim"])
        self.request.write_bytes(BUGFIX_REQUEST.encode("utf-8"))
        code, text = self.start(flow="bugfix", work_type="bugfix", runtime="codex", work_id=slug)
        text, fields = self.play(slug, text=text, stop="plan-review", branch="fix/add-sign")
        self.assertEqual(card_value(text, "artifacts"), "plan/fix-add.md")
        text, fields = self.play(slug, text=text, branch="fix/add-sign")
        self.assert_completed(text, slug, FLOW_STEPS["bugfix"])
        self.assertEqual(self.approvals(slug), [("plan-review", "reply", "none")])  # one gate, no reader
        self.assertEqual(self.meta("plan/fix-add.md", slug),
                         {"work_id": slug, "spec": "none", "branch": "fix/add-sign", "flow": "bugfix",
                          "status": "complete"})
        plan = self.pkg(slug) / "plan" / "fix-add.md"
        self.assertEqual(frontmatter.split(plan.read_text(encoding="utf-8"))[1], BUGFIX_PLAN_BODY)
        for absent in ("design.md", "spec", "draft", "plan/fix-add.review.json"):  # no intent, no loop, no critic
            self.assertFalse((self.pkg(slug) / absent).exists(), absent)
        resolution = resolve_work_package.resolve(self.project, branch="fix/add-sign")
        self.assertTrue(resolution.ok, resolution.errors)
        self.assertIn("spec=none", resolve_work_package.fields_for(resolution, self.project))

    def test_preapproved_feature_passes_its_one_gate(self):
        slug = "pre"
        self.request.write_bytes(PREAPPROVED_REQUEST.encode("utf-8"))
        code, text = self.start(flow="feature", work_type="feature", runtime="codex", work_id=slug)
        text, fields = self.play(slug, text=text, quote=PREAPPROVAL_QUOTE, design=UNATTENDED_DESIGN)
        self.assert_completed(text, slug, FLOW_STEPS["feature"])
        self.assertEqual(self.approvals(slug), [("plan-review", "original-request", "none")])
        record = logs.read(self.pkg(slug) / "approvals.jsonl")[0]
        self.assertEqual(record["quote"], PREAPPROVAL_QUOTE)
        # Nobody was asked, so every decision of the design is an author's call and the claim lists them.
        self.assertFalse((self.pkg(slug) / "questions.jsonl").exists())
        self.assertEqual(self.author_calls(self.cards[(slug, "claim")]), [("D1", "design.md"), ("D2", "design.md")])

    def test_preapproved_full_passes_both_gates_with_author_calls(self):
        slug = "prefull"
        self.request.write_bytes(PREAPPROVED_REQUEST.encode("utf-8"))
        code, text = self.start(flow="full", work_type="feature", runtime="codex", work_id=slug)
        reader = [("minor", ()), ("theirs", ("--author-call",))]  # a `theirs` question is an author's call here
        text, fields = self.play(slug, text=text, quote=PREAPPROVAL_QUOTE, design=UNATTENDED_DESIGN, reader=reader)
        self.assert_completed(text, slug, FLOW_STEPS["full"])
        self.assertEqual(self.approvals(slug), [("spec-review", "original-request", "fresh"),
                                                ("plan-review", "original-request", "none")])  # one use per gate
        check = textio.read_json(self.pkg(slug) / "spec" / (slug + ".check.json"))
        self.assertEqual([(q["id"], q["pile"], q["answer_seq"], q["author_call"]) for q in check["questions"]],
                         [("Q1", "minor", None, True), ("Q2", "theirs", None, True)])
        self.assertEqual(self.author_calls(self.cards[(slug, "claim")]),
                         [("D1", "design.md"), ("D2", "design.md"), ("Q1", "spec/%s.check.json" % slug),
                          ("Q2", "spec/%s.check.json" % slug)])

    def test_full_without_subagents_marks_the_reader_degraded(self):
        slug = "nosub"
        declared = "workflow=no,subagent=no,team=no"
        code, text = self.start(flow="full", work_type="feature", runtime="codex", work_id=slug)
        # The defaults need sub-agents: confirming them as they are is refused.
        code, out = self.sdlc("strategy", "confirm", "--slug", slug, "--capabilities", declared)
        self.assertEqual(code, 4, out)
        self.assertIn("error=strategy_refused:/entries/", out)
        self.assertIn("needs subagent=yes (declared no)", out)
        text, fields = self.play(slug, text=text, stop="spec-check", capabilities=declared,
                                 overrides=NO_SUBAGENT_STRATEGY)
        self.assertEqual((fields["mechanism"], fields["degraded"]), ("inline-degraded", "subagent:no"), text)
        self.assertIn("yourself", fields["delegate"])
        text, fields = self.play(slug, text=text, capabilities=declared)
        self.assert_completed(text, slug, FLOW_STEPS["full"])
        data = textio.read_json(self.pkg(slug) / "strategy.json")
        self.assertEqual(sorted((d["key"], d["reason"]) for d in data["degraded"]),
                         [(key, "subagent=no") for key in ("audit", "security", "spec-check")])
        self.assertEqual({key: data["entries"][key]["mechanism"] for key in ("spec-check", "security", "audit")},
                         {key: "inline-degraded" for key in ("spec-check", "security", "audit")})
        check = textio.read_json(self.pkg(slug) / "spec" / (slug + ".check.json"))
        self.assertEqual(check["reader"], "degraded")
        self.assertEqual(self.state(slug)["degraded"],
                         [{"step": sid, "capability": "subagent", "reason": "missing"}
                          for sid in ("spec-check", "security", "audit")])
        # The gate records the degraded reader; a user who approves sees it.
        self.assertEqual(self.approvals(slug), [("spec-review", "reply", "degraded"), ("plan-review", "reply", "none")])

    def test_spec_edit_after_the_reader_still_needs_sources_at_approve(self):
        slug = "late"
        code, text = self.start("--option", "spec", flow="feature", work_type="feature", runtime="codex", work_id=slug)
        text, fields = self.play(slug, text=text, stop="spec-review")
        self.assertEqual(self.state(slug)["steps"]["spec-check"]["state"], "done")
        spec = self.pkg(slug) / "spec" / (slug + ".md")
        sourced = spec.read_text(encoding="utf-8")
        # The main loop drops a criterion's source after the reader has read the spec.
        spec.write_bytes(sourced.replace(" (source: D1)", "").encode("utf-8"))
        text, fields = self.step(slug, state="wait-gate", step="spec-review")
        self.assertEqual(self.state(slug)["steps"]["spec-check"]["state"], "done")  # the reader does not run again
        code, out = self.approve(text, slug, gate="spec-review", expect=4)
        self.assertIn("error=artifact_checks_failed:spec:", out)
        self.assertIn("ac_no_source:AC1", out)
        self.assertEqual(self.approvals(slug), [])
        spec.write_bytes(sourced.encode("utf-8"))
        text, fields = self.step(slug, state="wait-gate", step="spec-review")
        self.approve(text, slug, gate="spec-review")
        self.assertEqual(self.approvals(slug), [("spec-review", "reply", "fresh")])

    def test_design_change_after_the_plan_restales_spec_and_plan(self):
        slug = "redo"
        code, text = self.start(flow="full", work_type="feature", runtime="codex", work_id=slug)
        text, fields = self.play(slug, text=text, stop="plan-review")  # the spec gate is approved, the plan written
        self.assertEqual(self.approvals(slug), [("spec-review", "reply", "fresh")])
        design = self.pkg(slug) / "design.md"
        design.write_bytes(design.read_text(encoding="utf-8").replace("Rows are streamed.", "Rows are buffered.")
                           .encode("utf-8"))
        code, text = self.next(slug)  # a changed design is a new intent: no `reapproval needed` halt
        fields = self.expect(text, "do", "spec")
        steps = self.state(slug)["steps"]
        self.assertEqual((steps["spec"]["state"], steps["spec"]["stale_cause"]), ("stale", "design.md"))
        self.assertEqual((self.state(slug)["status"], self.records("halt", slug)), ("active", []))
        # The spec is written again from the new design; its reader runs again; the spec gate waits again.
        spec = self.pkg(slug) / "spec" / (slug + ".md")
        spec.write_bytes(spec.read_text(encoding="utf-8").replace("(source: D1)", "(source: D1, D2)").encode("utf-8"))
        text, fields = self.step(slug, step="spec-check")
        self.assertEqual(fields["visit"], "2/3")
        self.read_spec(slug, fields, [])
        text, fields = self.step(slug, state="wait-gate", step="spec-review")
        self.assertEqual(self.state(slug)["status"], "active")
        self.approve(text, slug, gate="spec-review")  # the changed spec needs the user's yes again
        text, fields = self.step(slug, step="plan")  # the walk reaches the plan: its design and spec changed
        self.assertEqual(self.state(slug)["steps"]["plan"]["state"], "stale")
        self.assertEqual([r["step"] for r in self.records("stale", slug)], ["spec", "spec-check", "spec-review", "plan"])
        plan = self.pkg(slug) / "plan" / (slug + ".md")
        plan.write_bytes((plan.read_text(encoding="utf-8") + "\nThe rows are buffered first.\n").encode("utf-8"))
        text, fields = self.step(slug, state="wait-gate", step="plan-review")
        self.assertEqual(self.records("halt", slug), [])
        self.assertEqual([r["gate"] for r in self.records("approve", slug)], ["spec-review", "spec-review"])

    def test_bugfix_flow_end_to_end_plan_only(self):
        import resolve_work_package

        slug = "fix-add"
        self.request.write_bytes(BUGFIX_REQUEST.encode("utf-8"))
        text, fields = self.begin(slug, flow="bugfix", work_type="bugfix")
        self.assertEqual(self.state(slug)["loop"]["mode"], "bugfix-plan")
        self.role_is(fields, "author-plan", "0/3")  # plan-only: no author-spec role
        self.record("author-plan", 0, BUGFIX_PLAN_BODY, slug)
        text, fields = self.step(slug, step="draft")
        self.role_is(fields, "critic", "1/3")
        self.assertEqual(textio.read_json(self.draft("validator.r1.json", slug))["errors"], [])
        self.record("critic", 1, CLEAN, slug)
        text, fields = self.step(slug, state="wait-gate", step="review")  # stopped clean and ingested in this next
        self.assertEqual(card_value(text, "artifacts"), "plan/fix-add.md")
        self.assertEqual([r["role"] for r in self.records("role", slug)], ["author-plan", "critic"])
        self.assertFalse(self.draft("spec.r0.md", slug).exists())
        self.assertEqual(sorted(p.name for p in self.draft("prompts", slug).iterdir()),
                         ["author-plan.r0.md", "critic.r1.md"])
        self.assertFalse((self.pkg(slug) / "spec").exists())
        result = textio.read_json(self.draft("result.json", slug))
        self.assertEqual((result["mode"], result["spec"], result["stopReason"]), ("bugfix-plan", None, "clean"))
        self.approve_at_gate(text, slug)
        self.make_branch(slug, "fix/add-sign")
        self.red_then_green(slug, "tests/test_app.py",
                            "from src.app import add\n\n\ndef test_add_negative():\n    assert add(-2, 3) == 1\n",
                            "src/app.py", "def add(a, b):\n    return a + b  # keeps the sign of a\n")
        text, fields = self.step(slug, step="security")
        self.security_pass(slug)
        text, fields = self.step(slug, step="audit")
        self.assertEqual(fields["pending"], "report")  # the real resolver accepts the spec-less plan
        text, fields = self.audit_and_claim(slug)
        self.assert_completed(text, slug, BUGFIX_LOOP_STEPS)
        plan = self.pkg(slug) / "plan" / "fix-add.md"
        self.assertEqual(self.meta("plan/fix-add.md", slug),
                         {"work_id": "fix-add", "spec": "none", "branch": "fix/add-sign", "flow": "bugfix",
                          "status": "complete"})
        self.assertEqual(frontmatter.split(plan.read_text(encoding="utf-8"))[1], BUGFIX_PLAN_BODY)
        self.assertTrue((self.pkg(slug) / "plan" / "fix-add.review.json").is_file())
        resolution = resolve_work_package.resolve(self.project, branch="fix/add-sign")
        self.assertTrue(resolution.ok, resolution.errors)
        self.assertEqual((resolution.source, resolution.plan, resolution.spec), ("branch", plan, None))
        self.assertIn("spec=none", resolve_work_package.fields_for(resolution, self.project))

    def test_security_fix_rereview_cycle_capped(self):
        slug = "demo"
        text, fields = self.feature_to_security(slug)
        self.assertEqual(fields["visit"], "1/3")
        report = "evidence/demo.security.md"
        self.put(report, "# Security review\n\nFinding 1: the export writes a path taken from the request.\n"
                         "Verdict: fail\n", slug)
        text, fields = self.step(slug, step="security")
        self.assertEqual(fields["pending"], "report", text)
        self.assertEqual(self.state(slug).get("fix_rounds", 0), 0)
        # The same failing report read again is not a re-review: the counter does not move.
        text, fields = self.step(slug, step="security")
        self.assertEqual(self.state(slug).get("fix_rounds", 0), 0)
        for fix in (1, 2, 3):  # each fix of the source is followed by a re-review that fails again
            self.write("src/export.py", ("def export(rows):\n    return list(rows)  # fix %d\n" % fix).encode("utf-8"))
            self.put(report, "# Security review\n\nFinding %d: still open after fix %d.\nVerdict: fail\n"
                     % (fix + 1, fix), slug)
            text, fields = self.step(slug, step="security")
            self.assertEqual(self.state(slug)["fix_rounds"], fix)
        self.write("src/export.py", b"def export(rows):\n    return list(rows)  # fix 4\n")
        self.put(report, "# Security review\n\nFinding 5: still open after fix 4.\nVerdict: fail\n", slug)
        text, fields = self.step(slug, state="halted", step="security", expect=3)
        self.assertEqual(json.loads(card_value(text, "halt_reason")), "fix-round cap reached: security")
        st = self.state(slug)
        self.assertEqual((st["status"], st["halt"]["reason"], st["fix_rounds"], st["fix_round_cap"]),
                         ("halted", "fix-round cap reached: security", 4, 3))
        self.assertEqual(st["steps"]["security"]["visits"], 1)  # the re-reviews ran in one visit
        self.assertEqual([r["reason"] for r in self.records("halt", slug)], ["fix-round cap reached: security"])
        self.assertEqual(self.records("enter", slug, step="audit"), [])
        self.security_pass(slug)  # a passing review now changes nothing: only the user can resume
        text, fields = self.step(slug, state="halted", step="security", expect=3)
        self.assertEqual(len(self.records("halt", slug)), 1)
        self.assertTrue(logs.verify(self.pkg(slug) / "transitions.jsonl")[0])

    def test_codex_like_run_without_subagents_degrades_and_completes(self):
        slug = "demo"
        code, text = self.start("--option", "loop", flow="feature", work_type="feature", runtime="codex", work_id=slug)
        self.expect(text, "do", "strategy")
        declared = "workflow=no,subagent=no,team=no"
        # The codex defaults need sub-agents: confirming them as they are is refused.
        code, out = self.sdlc("strategy", "confirm", "--slug", slug, "--capabilities", declared)
        self.assertEqual(code, 4, out)
        self.assertIn("error=strategy_refused:/entries/draft: runner-loop needs subagent=yes (declared no)", out)
        self.assertFalse((self.pkg(slug) / "strategy.json").exists())
        # The inline fallbacks, each with its reason, are allowed and recorded.
        self.confirm_strategy(slug, declared, *NO_SUBAGENTS)
        data = textio.read_json(self.pkg(slug) / "strategy.json")
        self.assertEqual({key: data["entries"][key]["mechanism"] for key in ("draft", "draft.critic", "security", "audit")},
                         {"draft": "runner-loop-inline", "draft.critic": "runner-loop-inline",
                          "security": "inline-degraded", "audit": "inline-degraded"})
        self.assertEqual(sorted((d["key"], d["reason"]) for d in data["degraded"]),
                         [(key, "subagent=no") for key in ("audit", "draft", "draft.critic", "security")])
        self.assertEqual(self.records("strategy", slug)[0]["capabilities"], {"workflow": "no", "subagent": "no", "team": "no"})
        text, fields = self.step(slug, step="context")
        self.put("context.md", SCOPE, slug)
        text, fields = self.design(slug)
        self.assertEqual((fields["mechanism"], fields["degraded"]), ("runner-loop-inline", "subagent:no"))
        self.assertIn("yourself", fields["delegate"])
        self.sdlc_ok("note", "--slug", slug, "--degraded", "subagent", "--reason", "missing")
        self.record("author-spec", 0, SPEC_BODY, slug)
        text, fields = self.step(slug, step="draft")
        self.record("author-plan", 0, PLAN_BODY, slug)
        text, fields = self.step(slug, step="draft")
        self.role_is(fields, "critic", "1/3")
        self.assertIn("yourself", fields["delegate"])  # the critic runs inline too
        self.record("critic", 1, CLEAN, slug)
        # A hand-written result cannot relabel the inline critic as fresh.
        textio.write_json_atomic(self.draft("result.json", slug), _result(engine="runner-loop-inline"))
        code, out = self.sdlc("ingest-draft", "--slug", slug)
        self.assertEqual(code, 4, out)
        self.assertIn("error=result_critic:fresh (the loop's critic ran degraded)", out)
        self.assertFalse((self.pkg(slug) / "spec").exists())
        text, fields = self.step(slug, state="wait-gate", step="review")
        self.assertEqual(textio.read_json(self.draft("loop.json", slug))["critic"], ["degraded"])
        self.assertEqual(textio.read_json(self.draft("result.json", slug))["critic"], "degraded")
        for name in ("spec", "plan"):
            self.assertEqual(textio.read_json(self.pkg(slug) / name / "demo.review.json")["critic"], "degraded", name)
        self.assertIn('"critic": "degraded"', text)  # the gate shows the user the degraded critic
        self.approve_at_gate(text, slug)
        self.make_branch(slug, "work/demo")
        self.red_then_green(slug, "tests/test_export.py", "def test_export():\n    assert False\n",
                            "src/export.py", "def export(rows):\n    return rows\n")
        for gate in ("security", "audit"):
            text, fields = self.step(slug, step=gate)
            self.assertEqual((fields["mechanism"], fields["degraded"]), ("inline-degraded", "subagent:no"), text)
            out = self.sdlc_ok("note", "--slug", slug, "--degraded", "subagent", "--reason", "missing")
            self.assertEqual(card_fields(out)["degraded"], "subagent:missing")
            if gate == "security":
                self.security_pass(slug)
        text, fields = self.audit_and_claim(slug)
        self.assert_completed(text, slug, LOOP_STEPS)
        self.assertEqual(self.state(slug)["degraded"],
                         [{"step": sid, "capability": "subagent", "reason": "missing"} for sid in ("draft", "security", "audit")])
        notes = logs.read(self.pkg(slug) / "notes.jsonl")
        self.assertEqual([(n["kind"], n["step"]) for n in notes],
                         [("degraded", "draft"), ("degraded", "security"), ("degraded", "audit")])
        approval = [r for r in logs.read(self.pkg(slug) / "approvals.jsonl") if r["kind"] == "approve"]
        self.assertEqual([r["critic"] for r in approval], ["degraded"])


# -- packaging ------------------------------------------------------------------------------------

RUNNER_ENTRY = "scripts/sdlc.py"
RUNNER_PACKAGE = "scripts/sdlc_runner/"
FLOWS = "flows/"
PUBLIC_ROLE_DIR = "skills/using-agentic-sdlc/references/roles"
PUBLIC_GUIDE = "skills/using-agentic-sdlc/references/public-runtime.md"
# Read by path from the runner's own root (checks.py, paths.py, probes.py and loop staging).
RUNNER_READS = ("scripts/detect_context.py", "scripts/validate_artifacts.py", "scripts/resolve_work_package.py")
CONTRACT_EXCERPTS = ("contracts/skills/02-", "contracts/skills/03-")

# Run by the interpreter on the extracted package: the runner's own loaders resolve the plugin root,
# every flow and loop definition (schemas included) and each loop role's file from that package.
PROBE = r"""
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root / "scripts"))
from sdlc_runner import loop, manifest, paths
out = {"root": str(paths.plugin_root()), "flows": [], "loops": [], "roles": {}}
manifest.load_shared(root)
for flow_id in manifest.flow_ids(root):
    manifest.load_flow(root, flow_id)
    out["flows"].append(flow_id)
for loop_id in manifest.loop_ids(root):
    definition = manifest.load_loop(root, loop_id)
    out["loops"].append(loop_id)
    for role in definition["roles"].values():
        out["roles"][role["agent"]] = loop.role_path(root, role["agent"]).relative_to(root).as_posix()
print(json.dumps(out, sort_keys=True))
"""


def _runner_member(path: str) -> bool:
    return path == RUNNER_ENTRY or path.startswith((RUNNER_PACKAGE, FLOWS))


def _json_ids(paths, folder: str) -> list:
    """Ids of `<folder><id>.json` files, the names the runner's manifest loader lists."""
    pattern = re.compile(re.escape(folder) + r"([a-z][a-z0-9-]{0,63})\.json\Z")
    return sorted(m.group(1) for m in (pattern.match(p) for p in paths) if m)


def _loop_agents(members: dict) -> set:
    agents = set()
    for loop_id in _json_ids(members, "flows/loops/"):
        definition = json.loads(members["flows/loops/%s.json" % loop_id][1].decode("utf-8"))
        agents.update(role["agent"] for role in definition["roles"].values())
    return agents


class SdlcPackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True, encoding="utf-8"
        ).strip()
        cls.source = build_release._commit_members(cls.commit, cwd=REPO)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def build(self, kind: str):
        """Build one archive kind from HEAD; return its members and the folder it is extracted to."""
        out = self.tmp / (kind + ".zip")
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            result = build_release.build_archive(REPO, out, skills_only=kind == "skills-only")
        self.assertEqual(result.exit_code, 0, printed.getvalue())
        self.assertIn("archive_kind=" + kind, result.lines)
        root = self.tmp / kind
        with zipfile.ZipFile(out) as zf:
            members = {name: zf.read(name) for name in zf.namelist()}
        for name, data in members.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return members, root

    def run_python(self, *args):
        return subprocess.run([sys.executable, "-I", *args], cwd=self.tmp, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=120)

    def test_release_archive_contains_runner_and_flows(self):
        committed = {path: data for path, (_mode, data) in self.source.items() if _runner_member(path)}
        for path in (RUNNER_ENTRY, RUNNER_PACKAGE + "__init__.py", RUNNER_PACKAGE + "cli.py",
                     RUNNER_PACKAGE + "loop.py", "flows/_shared.json", "flows/feature.json",
                     "flows/loops/spec-plan.json", "flows/schemas/critic.schema.json",
                     "flows/schemas/draft-result.schema.json"):
            self.assertIn(path, committed, "HEAD does not carry the runner file " + path)
        agents = _loop_agents(self.source)
        self.assertTrue({"spec-plan-author", "spec-plan-critic"} <= agents, agents)
        flow_ids, loop_ids = _json_ids(committed, FLOWS), _json_ids(committed, "flows/loops/")

        for kind, role_dir in (("release", "agents"), ("skills-only", PUBLIC_ROLE_DIR)):
            with self.subTest(kind=kind):
                members, root = self.build(kind)
                shipped = {path: data for path, data in members.items() if _runner_member(path)}
                self.assertEqual(sorted(shipped), sorted(committed))
                for path, data in committed.items():
                    self.assertEqual(shipped[path], data, path + " is not the committed bytes")
                for path in RUNNER_READS:
                    self.assertIn(path, members)
                for prefix in CONTRACT_EXCERPTS:
                    self.assertTrue(any(p.startswith(prefix) and p.endswith(".md") for p in members), prefix)
                for agent in sorted(agents):
                    self.assertIn("%s/%s.md" % (role_dir, agent), members)
                if kind == "skills-only":
                    self.assertEqual([p for p in members if p.startswith("agents/")], [])

                probe = self.run_python("-c", PROBE, str(root))
                self.assertEqual(probe.returncode, 0, probe.stdout + probe.stderr)
                found = json.loads(probe.stdout.strip().splitlines()[-1])
                self.assertEqual(Path(found["root"]).resolve(), root.resolve())
                self.assertEqual(found["flows"], flow_ids)
                self.assertEqual(found["loops"], loop_ids)
                self.assertEqual(found["roles"], {agent: "%s/%s.md" % (role_dir, agent) for agent in agents})

                project = self.tmp / ("project-" + kind)
                project.mkdir()
                status = self.run_python(str(root / RUNNER_ENTRY), "--project", str(project), "status")
                self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
                self.assertEqual(status.stdout.strip().splitlines()[-1], "state=none chain=" + "0" * 12)

    def test_public_payload_keeps_flows_paths(self):
        step = "skills/agentic-sdlc-pipeline/steps/runner-probe.md"
        self.assertNotIn(step, self.source)
        rooted = ("<runtime-root>/flows/feature.json", "<runtime-root>/flows/loops/spec-plan.json",
                  "<runtime-root>/flows/schemas/critic.schema.json", "<runtime-root>/flows/",
                  "<runtime-root>/scripts/sdlc.py", "<runtime-root>/scripts/sdlc_runner/loop.py")
        link = "[the shared policy](../../../flows/_shared.json)"
        source_only = "<runtime-root>/workflows/spec-plan-draft.js"
        self.assertIn("workflows/spec-plan-draft.js", self.source)
        text = ("# Runner probe\n\n" + "".join("- Read `%s`.\n" % ref for ref in rooted)
                + "- See " + link + ".\n- Source port: `" + source_only + "`.\n")
        source = dict(self.source)
        source[step] = ("100644", text.encode("utf-8"))

        projected = build_release._select_skills_only(source)
        out = projected[step][1].decode("utf-8")
        for ref in rooted:
            with self.subTest(ref=ref):
                self.assertIn("`%s`" % ref, out)
                target = ref[len("<runtime-root>/"):].rstrip("/")
                self.assertTrue(target in projected or any(p.startswith(target + "/") for p in projected), ref)
        self.assertIn(link, out)
        # Control: a source-only path is still marked, so the rewrite itself is not switched off.
        self.assertIn("`workflows/spec-plan-draft.js (source checkout only)`", out)
        self.assertEqual(out.count("(source checkout only)"), 1, out)

        # The real payload: no runner or flows reference is marked source-only anywhere.
        marked = re.compile(r"(?<![\w./-])(?:flows/|scripts/sdlc)[A-Za-z0-9_./-]* \(source checkout only\)")
        self.assertTrue(marked.search("Read `flows/feature.json (source checkout only)`."))
        self.assertFalse(marked.search("Read `.grok/workflows/spec-plan-draft.rhai (source checkout only)`."))
        real = build_release._select_skills_only(self.source)
        hits = [path for path, (_mode, data) in real.items()
                if path.endswith(".md") and marked.search(data.decode("utf-8"))]
        self.assertEqual(hits, [])
        guide = real[PUBLIC_GUIDE][1].decode("utf-8")
        for name in ("`scripts/sdlc.py`", "`scripts/sdlc_runner/`", "`flows/`"):
            self.assertIn(name, guide)


if __name__ == "__main__":
    unittest.main()
