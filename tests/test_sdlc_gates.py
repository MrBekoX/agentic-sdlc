"""Gates, questions and notes of the sdlc runner (plan Task 7): scripts/sdlc_runner/gates.py.

Contract: docs/agentic-sdlc/notes/2026-10-22-runner-contract.md §11 (approve, reject, ask,
answer, note); design §5.10 (one review gate, fingerprint + quote, pre-approval checked against
request.md and the sidecars, D10 changes after approval) and §5.5 (commands).

Runs the in-process CLI on the harness of tests/test_sdlc_engine.py: the fixture flow's `review`
gate after its `draft` step (which may ask `design` questions), a temp git project, no paid CLI.
"""
import json
import re
import shlex
import sys
import unicodedata
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"
for folder in (REPO / "scripts", TESTS):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from test_sdlc_engine import (DESIGN_BODY, SPECLESS_PLAN, TWOGATE_SPEC, WINDOWS, EngineCase,  # noqa: E402
                              RealFlowCase, TwoGateCase, card_fields, card_value)
from sdlc_runner import gates, logs  # noqa: E402

PREAPPROVAL = "Add a CSV export to the report page. Go ahead without asking me again.\n"
PREAPPROVAL_QUOTE = "Go ahead without asking me again"


def _sidecar(artifact="spec/demo.md", critic="fresh", notes=(), points=()):
    return {
        "schema": "agentic-sdlc/sidecar@1", "artifact": artifact, "body_fingerprint": "0" * 64,
        "mode": "spec+plan", "engine": "runner-loop", "rounds": 2, "finalVerdict": "issues" if notes else "clean",
        "stopReason": "max-rounds" if notes else "clean", "critic": critic,
        "decisionPoints": list(points), "residualCriticNotes": list(notes),
    }


def _note(severity="medium", kind="gap"):
    return {"target": "spec", "category": "scope", "severity": severity, "kind": kind,
            "whatsMissing": "the export file name", "where": "Business Rules", "fix": "name it"}


def _command_args(line: str) -> list:
    """The runner arguments of a printed reply command (what follows the sdlc.py path)."""
    command = line.split("=", 1)[1]
    if WINDOWS:
        argv = [a or b for a, b in re.findall(r'"([^"]*)"|(\S+)', command)]
    else:
        argv = shlex.split(command)
    return argv[3:]


class GateCase(EngineCase):
    def gate(self, slug="demo"):
        code, text = self.advance_to("review", slug=slug)
        self.assertEqual(card_fields(text)["state"], "wait-gate", text)
        return text

    def sidecar(self, data, slug="demo", kind="spec"):
        self.put("%s/%s.review.json" % (kind, slug), json.dumps(data) + "\n", slug)

    def approvals(self, slug="demo"):
        return logs.read(self.pkg(slug) / "approvals.jsonl")


class TestApprove(GateCase):
    def test_gate_wait_card_prints_fingerprint_and_reply_commands(self):
        self.start()
        text = self.gate()
        fingerprint = card_value(text, "fingerprint")
        self.assertRegex(fingerprint, r"^[0-9a-f]{16}$")
        approve = _command_args("reply_approve=" + card_value(text, "reply_approve"))
        reject = _command_args("reply_reject=" + card_value(text, "reply_reject"))
        self.assertEqual(approve[:5], ["approve", "review", "--slug", "demo", "--fingerprint"])
        self.assertEqual(approve[5], fingerprint)
        self.assertIn("--source", approve)
        self.assertEqual(approve[approve.index("--source") + 1], "reply")
        self.assertEqual(reject[:4], ["reject", "review", "--slug", "demo"])
        # The printed command runs once the placeholder holds the user's words.
        approve[approve.index("--quote") + 1] = "Looks good, go ahead."
        code, out = self.sdlc(*approve)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.approvals()[0]["quote"], "Looks good, go ahead.")
        code, out = self.next()
        self.assertEqual(card_fields(out)["step"], "implement")

    def test_approve_wrong_fingerprint_refused(self):
        self.start()
        self.gate()
        code, out = self.sdlc("approve", "review", "--fingerprint", "0" * 16, "--quote", "Yes.", "--source", "reply")
        self.assertEqual(code, 4, out)
        self.assertIn("error=fingerprint_mismatch", out)
        self.assertEqual(self.approvals(), [])
        code, out = self.sdlc("approve", "nosuch", "--fingerprint", "0" * 16, "--quote", "Yes.", "--source", "reply")
        self.assertEqual(code, 4, out)
        self.assertIn("error=unknown_gate:nosuch", out)

    def test_approve_reply_needs_prior_wait(self):
        self.start()
        self.gate()
        self.put("spec/demo.md", (self.pkg() / "spec" / "demo.md").read_text(encoding="utf-8").replace(
            "every week", "every Monday"))
        code, preview = self.card()  # shows the new fingerprint, records no wait
        code, out = self.approve(preview, expect=4)
        self.assertIn("error=reply_without_wait", out)
        code, waited = self.next()
        self.assertEqual(card_value(waited, "fingerprint"), card_value(preview, "fingerprint"))
        self.approve(waited)
        self.assertEqual(self.approvals()[-1]["fingerprint"], card_value(waited, "fingerprint"))

    def test_original_request_quote_must_be_in_request(self):
        self.request.write_bytes(PREAPPROVAL.encode("utf-8"))
        self.start()
        text = self.gate()
        code, out = self.approve(text, source="original-request", quote="Ship it now.", expect=4)
        self.assertIn("error=quote_not_in_request", out)
        self.approve(text, source="original-request", quote="go ahead   WITHOUT asking me again")
        record = self.approvals()[0]
        self.assertEqual((record["source"], record["gate"]), ("original-request", "review"))
        self.assertEqual(record["critic"], "none")

    def test_original_request_quote_needs_whole_words(self):
        self.request.write_bytes(PREAPPROVAL.encode("utf-8"))
        self.start()
        text = self.gate()
        for quote, needle in (("e", "error=quote_too_short"), ("ahead", "error=quote_too_short"),
                              ("head without ask", "error=quote_not_in_request"),
                              ("go ahead withou", "error=quote_not_in_request")):
            with self.subTest(quote=quote):
                code, out = self.approve(text, source="original-request", quote=quote, expect=4)
                self.assertIn(needle, out)
        self.assertEqual(self.approvals(), [])
        self.approve(text, source="original-request", quote="Go ahead")

    def test_original_request_quote_nfc_casefold(self):
        request = unicodedata.normalize("NFD", "Raporu dışa aktar. ĞÜŞİ dosyasını onaylıyorum, devam et.\n")
        self.request.write_bytes(request.encode("utf-8"))
        self.start()
        text = self.gate()
        # NFC against NFD, lower case against upper case, extra spaces. Casefold is not
        # locale-aware, so the quote keeps the dotless ı and the dotted İ as the user typed them.
        quote = unicodedata.normalize("NFC", "  ğüşİ   dosyasını onaylıyorum ")
        self.assertNotEqual(gates.normalise_quote(quote), quote)
        self.assertIn(gates.normalise_quote(quote), gates.normalise_quote(request))
        self.approve(text, source="original-request", quote=quote)

    def test_quote_file_utf8(self):
        self.start()
        text = self.gate()
        quote_file = self.tmp / "quote.txt"
        quote_file.write_bytes(b"\xef\xbb\xbf" + "Evet, onaylıyorum: ğüşİ\r\n".encode("utf-8"))
        fingerprint = card_value(text, "fingerprint")
        code, out = self.sdlc("approve", "review", "--fingerprint", fingerprint, "--quote-file", str(quote_file),
                              "--source", "reply")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.approvals()[0]["quote"], "Evet, onaylıyorum: ğüşİ")
        bad = self.tmp / "bad.txt"
        bad.write_bytes(b"\xff\xfe not utf-8")
        code, out = self.sdlc("reject", "review", "--quote-file", str(bad))
        self.assertEqual(code, 2, out)
        self.assertIn("error=not_utf8:", out)


class TestPreapproval(GateCase):
    def setUp(self):
        super().setUp()
        self.request.write_bytes(PREAPPROVAL.encode("utf-8"))
        self.start()
        self.text = self.gate()

    def preapprove(self, expect=0):
        return self.approve(self.text, source="original-request", quote="Go ahead without asking me again",
                            expect=expect)

    def test_preapproval_refused_on_blocking_residual_note(self):
        for severity, kind in (("high", "gap"), ("critical", "style"), ("low", "contradiction"), ("low", "blocker")):
            with self.subTest(severity=severity, kind=kind):
                self.sidecar(_sidecar(notes=[_note(severity, kind)]))
                code, out = self.preapprove(expect=4)
                self.assertIn("error=blocking_residual_note:spec:scope", out)
        self.assertEqual(self.approvals(), [])
        self.approve(self.text)  # the user's own reply after seeing the notes is allowed

    def test_preapproval_refused_on_decision_without_recommendation(self):
        point = {"id": "DP1", "question": "CSV or JSON?", "options": ["CSV", "JSON"], "recommendation": ""}
        self.sidecar(_sidecar(points=[point]))
        code, out = self.preapprove(expect=4)
        self.assertIn("error=decision_without_recommendation:DP1", out)
        point["recommendation"] = "CSV"
        self.sidecar(_sidecar(points=[point]))
        self.preapprove()

    def test_preapproval_allowed_with_degraded_critic_and_recorded(self):
        self.sidecar(_sidecar(critic="degraded", notes=[_note("medium")]))
        self.sidecar(_sidecar(artifact="plan/demo.md"), kind="plan")
        self.preapprove()
        record = self.approvals()[0]
        self.assertEqual((record["critic"], record["source"]), ("degraded", "original-request"))
        self.assertEqual([r["critic"] for r in self.records("approve")], ["degraded"])


class TestChangesAfterApproval(GateCase):
    def test_edited_approved_spec_reopens_gate(self):
        self.request.write_bytes(PREAPPROVAL.encode("utf-8"))
        self.start()
        text = self.gate()
        self.approve(text)
        spec = self.pkg() / "spec" / "demo.md"
        spec.write_bytes(spec.read_text(encoding="utf-8").replace("every week", "every day").encode("utf-8"))
        code, out = self.next()
        self.assertEqual(card_fields(out)["state"], "wait-gate")
        self.assertNotEqual(card_value(out, "fingerprint"), card_value(text, "fingerprint"))
        code, refused = self.approve(out, source="original-request", quote="Go ahead without asking me again",
                                     expect=4)
        self.assertIn("error=preapproval_used", refused)
        # After implement started, a reopened gate halts instead of waiting.
        self.start(work_id="late")
        text = self.gate(slug="late")
        self.approve(text, slug="late")
        code, out = self.next("late")
        self.assertEqual(card_fields(out)["step"], "implement")
        spec = self.pkg("late") / "spec" / "late.md"
        spec.write_bytes(spec.read_text(encoding="utf-8").replace("every week", "every day").encode("utf-8"))
        code, out = self.next("late", expect=3)
        self.assertIn("reapproval needed: spec/late.md", out)

    def test_appended_plan_task_continues_under_preapproval_only(self):
        task2 = ("\n## Task 2: Empty report (AC1)\n\nModify `src/export.py`.\n\n"
                 "- RED: the failing test for the empty report.\n- Run: `pytest tests/test_export.py`\n")
        self.request.write_bytes(PREAPPROVAL.encode("utf-8"))
        for slug, source in (("pre", "original-request"), ("reply", "reply")):
            with self.subTest(source=source):
                self.start(work_id=slug)
                text = self.gate(slug=slug)
                self.approve(text, slug=slug, source=source, quote="Go ahead without asking me again")
                code, out = self.next(slug)
                self.assertEqual(card_fields(out)["step"], "implement")
                plan = self.pkg(slug) / "plan" / ("%s.md" % slug)
                plan.write_bytes((plan.read_text(encoding="utf-8") + task2).encode("utf-8"))
                code, out = self.next(slug, expect=None)
                if source == "original-request":
                    self.assertEqual(code, 0, out)
                    fields = card_fields(out)
                    self.assertEqual((fields["step"], fields["visit"]), ("implement", "1/5"))
                    appended = self.state(slug)["appended_tasks"]
                    self.assertEqual([t["title"] for t in appended], ["## Task 2: Empty report (AC1)"])
                else:
                    self.assertEqual(code, 3, out)
                    self.assertIn("reapproval needed: plan/reply.md", out)
                    self.assertEqual(self.state(slug)["appended_tasks"], [])

    def test_reject_reopens_draft_with_feedback_input(self):
        self.start()
        self.gate()
        code, out = self.sdlc("reject", "review", "--quote", "Add a JSON export too.")
        self.assertEqual(code, 0, out)
        feedback = logs.read(self.pkg() / "feedback.jsonl")
        self.assertEqual([(r["kind"], r["gate"], r["quote"]) for r in feedback],
                         [("reject", "review", "Add a JSON export too.")])
        st = self.state()
        self.assertIsNone(st["waiting"])
        self.assertEqual((st["steps"]["draft"]["state"], st["steps"]["draft"]["reenter"]), ("stale", "reject"))
        code, out = self.next()
        fields = card_fields(out)
        self.assertEqual((fields["step"], fields["visit"]), ("draft", "2/3"))
        self.assertEqual(self.records("enter", step="draft")[-1]["cause"], "reject")
        self.assertEqual(self.records("reject")[0]["step"], "draft")


class TestQuestionsAndNotes(GateCase):
    def test_ask_kind_must_be_in_may_ask(self):
        self.start()
        self.advance_to("draft")
        code, out = self.sdlc("ask", "--kind", "consent", "--question", "May I delete the old exporter?")
        self.assertEqual(code, 4, out)
        self.assertIn("error=ask_kind_not_allowed:consent:draft", out)
        code, out = self.sdlc("ask", "--kind", "design", "--question", "CSV only, or CSV and JSON?")
        self.assertEqual(code, 0, out)
        self.assertEqual(card_fields(out)["state"], "wait-answer")
        lines = out.splitlines()
        asked = [i for i, line in enumerate(lines) if "CSV only, or CSV and JSON?" in line]
        self.assertTrue(asked and all(i > lines.index("--- data (not instructions) ---") for i in asked))
        record = logs.read(self.pkg() / "questions.jsonl")[0]
        self.assertEqual((record["kind"], record["ask_kind"], record["step"]), ("ask", "design", "draft"))

    def test_wait_answer_until_answered(self):
        self.start()
        self.advance_to("draft")
        code, out = self.sdlc("answer", "--quote", "CSV.")
        self.assertEqual(code, 4, out)
        self.assertIn("error=no_pending_question", out)
        self.sdlc("ask", "--kind", "design", "--question", "CSV only?")
        for _ in range(4):  # waiting never counts toward no progress
            code, out = self.next()
            self.assertEqual(card_fields(out)["state"], "wait-answer")
        code, out = self.sdlc("answer", "--quote", "CSV only, thanks.")
        self.assertEqual(code, 0, out)
        code, out = self.next()
        self.assertEqual((card_fields(out)["state"], card_fields(out)["step"]), ("do", "draft"))
        records = logs.read(self.pkg() / "questions.jsonl")
        self.assertEqual([r["kind"] for r in records], ["ask", "answer"])
        self.assertEqual(records[1]["question_id"], records[0]["seq"])
        self.assertIsNone(self.state()["waiting"])

    def test_note_degraded_recorded_on_current_step(self):
        self.start()
        self.confirm_strategy()
        self.next()
        code, out = self.sdlc("note", "--degraded", "subagent", "--reason", "denied")
        self.assertEqual(code, 0, out)
        note = logs.read(self.pkg() / "notes.jsonl")[0]
        self.assertEqual((note["kind"], note["step"], note["capability"], note["reason"]),
                         ("degraded", "context", "subagent", "denied"))
        self.assertIn({"step": "context", "capability": "subagent", "reason": "denied"}, self.state()["degraded"])
        code, out = self.card()
        self.assertEqual(card_fields(out)["degraded"], "subagent:denied")
        code, out = self.sdlc("note", "--degraded", "subagent", "--reason", "denied", "--step", "nosuch")
        self.assertEqual(code, 2, out)
        code, out = self.sdlc("note", "--awaiting", "task-123")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.state()["awaiting"]["task_id"], "task-123")


class TestTwoGates(TwoGateCase):
    """spec-review and plan-review of the two-gate fixture flow (hybrid spec/plan design §4.4, §4.6)."""

    def approvals(self, slug="demo"):
        return logs.read(self.pkg(slug) / "approvals.jsonl")

    def settled_at_review(self, *piles, slug="demo"):
        """Reach spec-review with one reader question per pile, each settled into that pile."""
        self.advance_to("spec-check", slug=slug)
        self.check_record(*["Question %d?" % n for n in range(1, len(piles) + 1)], slug=slug)
        for number, pile in enumerate(piles, 1):
            extra = ("--author-call",) if pile == "theirs" else ()
            self.check_resolve("Q%d" % number, pile, *extra, slug=slug)
        code, text = self.next(slug)
        self.assertEqual((card_fields(text)["state"], card_fields(text)["step"]), ("wait-gate", "spec-review"), text)
        return text

    def test_approve_rechecks_the_drafting_steps(self):
        self.start()
        self.advance_to("spec-review")
        # The main loop edits the spec after the reader ran: spec-check stays done, the criterion loses its source.
        self.edit("spec/demo.md", " (source: D1)", "")
        code, text = self.next()
        self.assertEqual((card_fields(text)["state"], card_fields(text)["step"]), ("wait-gate", "spec-review"), text)
        self.assertEqual(self.state()["steps"]["spec-check"]["visits"], 1)
        code, out = self.approve(text, gate="spec-review", expect=4)
        self.assertIn("error=artifact_checks_failed:spec:spec/demo.md fails validate_artifacts: ac_no_source:AC1", out)
        self.assertEqual(self.approvals(), [])
        self.edit("spec/demo.md", "every visible row.\n", "every visible row. (source: D1)\n")
        code, text = self.next()
        self.approve(text, gate="spec-review")
        self.assertEqual([r["gate"] for r in self.approvals()], ["spec-review"])

    def test_preapproval_refused_while_a_reader_question_is_unsettled(self):
        self.request.write_bytes(PREAPPROVAL.encode("utf-8"))
        self.start()
        self.settled_at_review("answered", "minor")
        check = self.pkg() / "spec" / "demo.check.json"
        settled = check.read_bytes()
        # A hand edit after the reader's step puts Q2 back among the open questions; spec-check stays done.
        data = json.loads(settled.decode("utf-8"))
        data["questions"][1].update({"pile": None, "resolution": None, "author_call": False})
        check.write_bytes(json.dumps(data).encode("utf-8"))
        code, text = self.next()
        self.assertEqual(card_fields(text)["state"], "wait-gate", text)
        code, out = self.approve(text, gate="spec-review", source="original-request", quote=PREAPPROVAL_QUOTE,
                                 expect=4)
        self.assertIn("error=unsettled_question:Q2", out)
        # A check file that no longer validates is refused too, not read as having no questions.
        del data["reader"]
        check.write_bytes(json.dumps(data).encode("utf-8"))
        code, out = self.approve(text, gate="spec-review", source="original-request", quote=PREAPPROVAL_QUOTE,
                                 expect=4)
        self.assertIn("error=check_invalid:spec/demo.check.json:", out)
        self.assertEqual(self.approvals(), [])
        check.write_bytes(settled)
        self.approve(text, gate="spec-review", source="original-request", quote=PREAPPROVAL_QUOTE)
        self.assertEqual([(r["gate"], r["source"]) for r in self.approvals()], [("spec-review", "original-request")])

    def test_preapproval_allowed_with_author_calls(self):
        self.request.write_bytes(PREAPPROVAL.encode("utf-8"))
        self.start()
        text = self.settled_at_review("minor", "theirs")
        self.approve(text, gate="spec-review", source="original-request", quote=PREAPPROVAL_QUOTE)
        record = self.approvals()[0]
        # No review sidecar on this gate: the record names the spec reader's freshness.
        self.assertEqual((record["gate"], record["source"], record["critic"]), ("spec-review", "original-request", "fresh"))
        self.assertEqual(self.records("approve")[0]["critic"], "fresh")
        # A degraded reader does not block a pre-approval either; the record says so.
        self.start(work_id="inline")
        self.confirm_strategy("inline", "workflow=no,subagent=no,team=no",
                              "spec-check=inline-degraded:no sub-agent tool in this session")
        text = self.settled_at_review("minor", slug="inline")
        self.approve(text, slug="inline", gate="spec-review", source="original-request", quote=PREAPPROVAL_QUOTE)
        self.assertEqual(self.approvals("inline")[0]["critic"], "degraded")
        # plan-review covers only the plan: no sidecar and no reader.
        code, text = self.advance_to("plan-review", slug="inline")
        self.approve(text, slug="inline", gate="plan-review", source="original-request", quote=PREAPPROVAL_QUOTE)
        self.assertEqual(self.approvals("inline")[-1]["critic"], "none")

    def test_original_request_quote_approves_each_gate_once(self):
        self.request.write_bytes(PREAPPROVAL.encode("utf-8"))
        self.start()
        code, text = self.advance_to("spec-review")
        self.approve(text, gate="spec-review", source="original-request", quote=PREAPPROVAL_QUOTE)
        code, text = self.advance_to("plan-review")
        self.assertEqual(card_fields(text)["state"], "wait-gate", text)
        # The approved spec changes while the plan waits: spec-review reopens, and its pre-approval is used.
        self.edit("spec/demo.md", "every week", "every Monday")
        code, text = self.next()
        self.assertEqual((card_fields(text)["state"], card_fields(text)["step"]), ("wait-gate", "spec-review"), text)
        code, out = self.approve(text, gate="spec-review", source="original-request", quote=PREAPPROVAL_QUOTE,
                                 expect=4)
        self.assertIn("error=preapproval_used", out)
        self.approve(text, gate="spec-review")  # the user's own reply
        code, text = self.next()
        self.assertEqual(card_fields(text)["step"], "plan")  # the changed spec makes the plan stale
        self.edit("plan/demo.md", "# Plan: report export\n", "# Plan: report export\n\nRows go out every Monday.\n")
        code, text = self.next()
        self.assertEqual((card_fields(text)["state"], card_fields(text)["step"]), ("wait-gate", "plan-review"), text)
        # plan-review's own pre-approval is still unused.
        self.approve(text, gate="plan-review", source="original-request", quote=PREAPPROVAL_QUOTE)
        code, text = self.next()
        self.assertEqual(card_fields(text)["step"], "branch")
        self.assertEqual([(r["gate"], r["source"]) for r in self.approvals()],
                         [("spec-review", "original-request"), ("spec-review", "reply"),
                          ("plan-review", "original-request")])

    def test_reject_at_spec_review_reopens_spec_not_spec_check(self):
        self.start()
        self.settled_at_review("answered")
        recorded = (self.pkg() / "spec" / "demo.check.json").read_bytes()
        code, out = self.sdlc("reject", "spec-review", "--quote", "Name the export file too.")
        self.assertEqual(code, 0, out)
        steps = self.state()["steps"]
        self.assertEqual((steps["spec"]["state"], steps["spec"]["reenter"]), ("stale", "reject"))
        self.assertEqual(steps["spec-check"]["state"], "done")
        self.assertEqual(self.records("reject")[0]["step"], "spec")
        code, text = self.next()
        self.assertEqual((card_fields(text)["step"], card_fields(text)["visit"]), ("spec", "2/3"))
        self.edit("spec/demo.md", "## Edge Cases\n", "## Edge Cases\n\n- The file is named after the report.\n")
        code, text = self.next()
        self.assertEqual((card_fields(text)["state"], card_fields(text)["step"]), ("wait-gate", "spec-review"), text)
        self.assertEqual(self.state()["steps"]["spec-check"]["visits"], 1)  # the reader does not run again
        self.assertEqual((self.pkg() / "spec" / "demo.check.json").read_bytes(), recorded)


# A criterion the user's change request at a gate asks for, sourced from that request's feedback record.
FEEDBACK_AC = "\n- AC%d: Given a report, when the user exports it, then the file is named after it. (source: %s)"
SPEC_AC1 = "every visible row. (source: D1)"
PLAN_AC1 = "every row. (source: D2)"


class TestFeedbackSources(RealFlowCase):
    """`F<n>` on the real flows: `reject` prints the feedback record it wrote, and a criterion added on that
    change request cites it; the spec and plan checks know only the reject records of the gates over
    their file (hybrid design, gate feedback as a source)."""

    def reject(self, gate, quote, slug="demo"):
        code, out = self.sdlc("reject", gate, "--slug", slug, "--quote", quote)
        self.assertEqual(code, 0, out)
        return out

    def at(self, text, state, step):
        fields = card_fields(text)
        self.assertEqual((fields["state"], fields["step"]), (state, step), text)
        return fields

    def test_reject_prints_its_feedback_record_and_the_spec_cites_it(self):
        self.start("--option", "spec")
        code, text = self.advance_to("spec-review")
        out = self.reject("spec-review", "Name the export file too.")
        self.assertEqual(out.splitlines()[:2], ["rejected=spec-review", "feedback=F1"])
        code, text = self.next()
        self.at(text, "do", "spec")
        self.assertEqual(self.steps()["spec"]["visit_cause"], "reject")
        self.edit("spec/demo.md", SPEC_AC1, SPEC_AC1 + FEEDBACK_AC % (2, "F1"))
        code, text = self.next()
        self.at(text, "wait-gate", "spec-review")
        # A second change request is the next record of the log.
        out = self.reject("spec-review", "And say where the file goes.")
        self.assertEqual(out.splitlines()[:2], ["rejected=spec-review", "feedback=F2"])
        self.assertEqual([(r["seq"], r["gate"]) for r in logs.read(self.pkg() / "feedback.jsonl")],
                         [(1, "spec-review"), (2, "spec-review")])
        self.next()
        self.edit("spec/demo.md", SPEC_AC1, SPEC_AC1 + FEEDBACK_AC % (3, "F2"))
        code, text = self.next()
        self.at(text, "wait-gate", "spec-review")
        self.approve(text, gate="spec-review")
        code, text = self.next()
        self.at(text, "do", "plan")

    def test_an_unknown_feedback_record_fails_the_spec_and_its_approval(self):
        self.start("--option", "spec")
        self.advance_to("spec-review")
        self.reject("spec-review", "Name the export file too.")
        self.next()
        self.edit("spec/demo.md", SPEC_AC1, SPEC_AC1 + FEEDBACK_AC % (2, "F9"))
        code, text = self.next()
        self.assertEqual(self.at(text, "do", "spec")["pending"], "validator")
        self.assertIn("ac_unknown_source:AC2:F9", text)
        self.edit("spec/demo.md", "(source: F9)", "(source: F1)")
        code, text = self.next()
        self.at(text, "wait-gate", "spec-review")
        # Edited at the gate: it waits at the new fingerprint, and approve runs the spec's check again.
        self.edit("spec/demo.md", "(source: F1)", "(source: F9)")
        code, text = self.next()
        self.at(text, "wait-gate", "spec-review")
        code, out = self.approve(text, gate="spec-review", expect=4)
        self.assertIn("error=artifact_checks_failed:spec:spec/demo.md fails validate_artifacts: "
                      "ac_unknown_source:AC2:F9", out)
        self.assertEqual(logs.read(self.pkg() / "approvals.jsonl"), [])

    def test_specless_plan_criterion_cites_the_reject_at_plan_review(self):
        self.start(flow="plan")
        code, text = self.advance_to("plan-review")
        out = self.reject("plan-review", "Export the hidden rows too.")
        self.assertEqual(out.splitlines()[:2], ["rejected=plan-review", "feedback=F1"])
        code, text = self.next()
        self.at(text, "do", "plan")
        self.assertEqual(self.steps()["plan"]["visit_cause"], "reject")
        self.edit("plan/demo.md", PLAN_AC1, PLAN_AC1 + FEEDBACK_AC % (2, "F9"))
        self.edit("plan/demo.md", "## Task 1: CSV export (AC1)", "## Task 1: CSV export (AC1, AC2)")
        code, text = self.next()
        self.assertEqual(self.at(text, "do", "plan")["pending"], "validator")
        self.assertIn("ac_unknown_source:AC2:F9", text)
        self.edit("plan/demo.md", "(source: F9)", "(source: F1)")
        code, text = self.next()
        self.at(text, "wait-gate", "plan-review")
        self.approve(text, gate="plan-review")
        code, text = self.next()
        self.at(text, "do", "claim")

    def test_the_checks_know_only_the_reject_records_of_the_gates_over_their_file(self):
        from sdlc_runner import checks, engine

        self.start()
        ctx = engine.load_context(self.project, self.root, "demo")
        self.assertEqual(checks.feedback_gates(ctx, "spec/demo.md"), ["review", "spec-review"])
        self.assertEqual(checks.feedback_gates(ctx, "plan/demo.md"), ["review", "plan-review"])
        self.assertEqual(checks.feedback_gates(ctx, "context.md"), [])
        self.put("design.md", DESIGN_BODY)
        spec_check = {"check": "validator", "mode": "spec", "sources": True}
        plan_check = {"check": "validator", "mode": "plan", "strict": True, "sources": True}

        def spec_cites(token):
            self.put("spec/demo.md", "---\nwork_id: demo\nstatus: draft\n---\n" +
                     TWOGATE_SPEC.replace(SPEC_AC1, SPEC_AC1 + FEEDBACK_AC % (2, token)))
            return checks.run_check(ctx, spec_check)

        def plan_cites(token):
            self.put("plan/demo.md", SPECLESS_PLAN.replace(PLAN_AC1, "every row. (source: D2, %s)" % token))
            return checks.run_check(ctx, plan_check)

        # No feedback.jsonl: no record is known.
        self.assertIn("ac_unknown_source:AC2:F1", spec_cites("F1").detail)
        for record in ({"kind": "reject", "gate": "plan-review", "quote": "Split the task."},
                       {"kind": "reject", "gate": "spec-review", "quote": "Name the file."},
                       {"kind": "note", "gate": "spec-review", "quote": "Not a change request."}):
            logs.append(self.pkg() / "feedback.jsonl", record)
        result = spec_cites("F2")
        self.assertTrue(result.ok, result.detail)
        for token in ("F1", "F3", "F4"):
            with self.subTest(artifact="spec", token=token):
                self.assertIn("ac_unknown_source:AC2:%s" % token, spec_cites(token).detail)
        (self.pkg() / "spec" / "demo.md").unlink()
        result = plan_cites("F1")
        self.assertTrue(result.ok, result.detail)
        for token in ("F2", "F3"):
            with self.subTest(artifact="plan", token=token):
                self.assertIn("ac_unknown_source:AC1:%s" % token, plan_cites(token).detail)


if __name__ == "__main__":
    unittest.main()
