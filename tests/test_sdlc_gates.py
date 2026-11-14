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

from test_sdlc_engine import WINDOWS, EngineCase, card_fields, card_value  # noqa: E402
from sdlc_runner import gates, logs  # noqa: E402

PREAPPROVAL = "Add a CSV export to the report page. Go ahead without asking me again.\n"


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


if __name__ == "__main__":
    unittest.main()
