"""The fresh reader of a spec: its role card, `check-record`, `check-resolve` and the `settled` check.

Design (hybrid spec/plan) 4.3: the `spec-check` step hands `design.md` and the spec to one fresh
reader (the role `spec-builder-check`); the runner stages that card like a loop role card, records
the reader's questions in `spec/<work_id>.check.json` with the spec body fingerprint it read, and
the main loop settles every question with `check-resolve` (`answered`, `minor`, or `theirs` with
the user's answer or an author's call). The step is done when every question is settled; editing
the spec afterwards does not re-run the reader, a changed `design.md` does.

Runs the in-process CLI on the harness of tests/test_sdlc_engine.py with the fixture flow
tests/fixtures/sdlc/flows/speccheck.json; no paid CLI is ever started.
"""
import json
import shutil
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"
for folder in (REPO / "scripts", TESTS):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from test_sdlc_engine import SPEC_BODY, EngineCase, card_fields  # noqa: E402
from sdlc_runner import checks, engine, fingerprint, logs, manifest, schema, speccheck  # noqa: E402

FIXTURE_FLOW = REPO / "tests" / "fixtures" / "sdlc" / "flows" / "speccheck.json"
DESIGN = "# Design: report export\n\n## Intent\n\nLet a user export a report.\n"
ROLE = "spec-builder-check"


def reader(*questions):
    """A reader answer holding one question per argument."""
    return json.dumps({"questions": [{"question": q, "why": "a wrong guess changes %s" % q} for q in questions]})


class SpecCheckCase(EngineCase):
    def make_root(self, root, shared_edit=None):
        root = super().make_root(root, shared_edit)
        shutil.copyfile(str(FIXTURE_FLOW), str(root / "flows" / "speccheck.json"))
        shutil.copyfile(str(REPO / "agents" / (ROLE + ".md")), str(root / "agents" / (ROLE + ".md")))
        return root

    def satisfy(self, step, text, slug="demo"):
        if step == "intent":
            self.put("design.md", DESIGN, slug)
        elif step == "spec":
            self.put("spec/%s.md" % slug, SPEC_BODY, slug)
        else:
            super().satisfy(step, text, slug)

    def reach(self, *overrides, capabilities="workflow=no,subagent=yes,team=no", start=True):
        """A started package with its strategy confirmed, at the spec-check card."""
        if start:
            self.start(flow="speccheck")
        if self.state()["steps"].get("strategy", {}).get("state") != "done":
            self.confirm_strategy("demo", capabilities, *overrides)
        return self.advance_to("spec-check")

    def record(self, *questions, text=None, expect=0):
        code, out = self.sdlc("check-record", "--slug", "demo", "--text", text if text is not None else reader(*questions))
        self.assertEqual(code, expect, out)
        return out

    def resolve(self, qid, pile="answered", resolution="settled in the spec", *extra, expect=0):
        code, out = self.sdlc("check-resolve", "--slug", "demo", "--id", qid, "--pile", pile,
                              "--resolution", resolution, *extra)
        self.assertEqual(code, expect, out)
        return out

    def check_file(self):
        return json.loads((self.pkg() / "spec" / "demo.check.json").read_text(encoding="utf-8"))

    def context(self):
        return engine.load_context(self.project, self.root, "demo")

    def settled(self):
        ctx = self.context()
        return checks.run_check(ctx, {"check": "settled"}, ctx.flow_step("spec-check"))

    def answer_seq(self, text="Use the first option."):
        """Ask a design question in the current step, answer it, and return the answer record's seq."""
        code, out = self.sdlc("ask", "--kind", "design", "--question", "Which option?", "--slug", "demo")
        self.assertEqual(code, 0, out)
        code, out = self.sdlc("answer", "--quote", text, "--slug", "demo")
        self.assertEqual(code, 0, out)
        records = logs.read(self.pkg() / "questions.jsonl")
        return [r for r in records if r["kind"] == "answer"][-1]["seq"]


class TestRoleCard(SpecCheckCase):
    def test_card_for_a_role_step_names_role_prompt_write_and_delegate(self):
        _code, text = self.reach()
        fields = card_fields(text)
        self.assertEqual(fields["step"], "spec-check")
        self.assertEqual(fields["mechanism"], "subagent")
        self.assertEqual(fields["role"], ROLE)
        self.assertEqual(fields["role_file"], str(self.root / "agents" / (ROLE + ".md")))
        self.assertEqual(fields["prompt"], "docs/agentic-sdlc/demo/draft/prompts/%s.md" % ROLE)
        self.assertEqual(fields["write"], "docs/agentic-sdlc/demo/draft/check.answer.json")
        self.assertIn("spawn_agent", fields["delegate"])  # the codex row of loop.FRESHNESS
        self.assertLessEqual(len(text.encode("utf-8")), 8000)
        self.assertIn("done_when=", text)
        self.assertTrue((self.pkg() / "draft" / "prompts" / (ROLE + ".md")).is_file())

    def test_the_read_only_card_stages_nothing(self):
        self.reach()
        prompt = self.pkg() / "draft" / "prompts" / (ROLE + ".md")
        prompt.unlink()
        _code, text = self.card()
        self.assertEqual(card_fields(text)["prompt"], "docs/agentic-sdlc/demo/draft/prompts/%s.md" % ROLE)
        self.assertFalse(prompt.exists())

    def test_inline_mechanism_prints_the_degraded_delegate_text(self):
        _code, text = self.reach("spec-check=inline-degraded:no sub-agent tool in this session",
                                 capabilities="workflow=no,subagent=no,team=no")
        fields = card_fields(text)
        self.assertEqual(fields["mechanism"], "inline-degraded")
        self.assertIn("Play the role yourself (degraded)", fields["delegate"])
        self.assertTrue(fields["delegate"].endswith("the runner records the role as degraded."))

    def test_no_role_lines_once_the_reader_is_recorded(self):
        self.reach()
        self.record("Which format?")
        _code, text = self.card()
        self.assertEqual(card_fields(text)["step"], "spec-check")
        self.assertNotIn("\nrole=", text)
        self.assertIn("pending=settled", text)

    def test_stage_writes_the_prompt_with_the_role_reads(self):
        self.reach()
        ctx = self.context()
        step = ctx.flow_step("spec-check")
        prompt, write = speccheck.stage(ctx, step)
        self.assertEqual(prompt, self.pkg() / "draft" / "prompts" / (ROLE + ".md"))
        self.assertEqual(write, self.pkg() / "draft" / "check.answer.json")
        text = prompt.read_text(encoding="utf-8")
        self.assertNotIn("name: " + ROLE, text)  # the role body, without its frontmatter
        self.assertIn("builder who has to plan this work", text)
        self.assertIn("Read these files:", text)
        self.assertIn("- " + str(self.pkg() / "design.md"), text)
        self.assertIn("- " + str(self.pkg() / "spec" / "demo.md"), text)
        self.assertIn("Return only the JSON", text)
        self.assertIn("it is saved to %s" % write, text)
        self.assertNotIn("\r", text)


class TestRecord(SpecCheckCase):
    def test_record_writes_the_check_with_the_spec_fingerprint(self):
        self.reach()
        out = self.record("Which file format?", "Who may export?")
        self.assertIn("recorded=check", out)
        data = self.check_file()
        self.assertEqual(schema.validate(data, manifest.load_schema("check")), [])
        self.assertEqual((data["schema"], data["artifact"], data["reader"]), ("agentic-sdlc/check@1", "spec", "fresh"))
        self.assertEqual(data["body_fingerprint"], fingerprint.body_fp(self.pkg() / "spec" / "demo.md"))
        self.assertEqual([q["id"] for q in data["questions"]], ["Q1", "Q2"])
        first = data["questions"][0]
        self.assertEqual((first["question"], first["pile"], first["resolution"], first["answer_seq"],
                          first["author_call"]), ("Which file format?", None, None, None, False))
        self.assertIn("Which file format?", first["why"])

    def test_record_reads_the_write_path_by_default(self):
        self.reach()
        self.put("draft/check.answer.json", reader("Which file format?"))
        code, out = self.sdlc("check-record", "--slug", "demo")
        self.assertEqual(code, 0, out)
        self.assertEqual([q["id"] for q in self.check_file()["questions"]], ["Q1"])
        other = self.tmp / "other.json"
        other.write_text(reader("One", "Two"), encoding="utf-8")
        code, out = self.sdlc("check-record", "--slug", "demo", "--from", str(other))
        self.assertEqual(code, 0, out)
        # The replacing record goes on from the highest id the file held: Q1 never names another question.
        self.assertEqual([q["id"] for q in self.check_file()["questions"]], ["Q2", "Q3"])

    def test_record_refused_outside_the_spec_check_step(self):
        self.start(flow="speccheck")
        code, out = self.sdlc("check-record", "--slug", "demo", "--text", reader("A question?"))
        self.assertEqual(code, 4, out)
        self.assertIn("error=not_current_step", out)
        self.assertFalse((self.pkg() / "spec" / "demo.check.json").exists())
        self.reach(start=False)
        self.record("A question?")
        self.resolve("Q1")
        code, out = self.next()
        self.assertEqual(card_fields(out)["step"], "claim", out)
        code, out = self.sdlc("check-record", "--slug", "demo", "--text", reader("Another?"))
        self.assertEqual(code, 4, out)  # the flow moved on: spec-check is not the current step
        self.assertIn("error=not_current_step:claim", out)

    def test_record_rejects_a_malformed_reader_answer(self):
        self.reach()
        bad = {
            "not json": "the questions are: ...",
            "a list": "[]",
            "no questions key": '{"items": []}',
            "questions not a list": '{"questions": "none"}',
            "item not an object": '{"questions": ["Which?"]}',
            "missing why": '{"questions": [{"question": "Which?"}]}',
            "empty question": '{"questions": [{"question": " ", "why": "x"}]}',
            "empty why": '{"questions": [{"question": "Which?", "why": ""}]}',
            "duplicate key": '{"questions": [], "questions": []}',
        }
        for name, text in bad.items():
            with self.subTest(answer=name):
                code, out = self.sdlc("check-record", "--slug", "demo", "--text", text)
                self.assertEqual(code, 4, out)
                self.assertIn("error=check_answer_invalid:", out)
                self.assertFalse((self.pkg() / "spec" / "demo.check.json").exists())
        code, out = self.sdlc("check-record", "--slug", "demo", "--from", str(self.tmp / "absent.json"))
        self.assertEqual(code, 2, out)
        self.assertIn("error=record_unreadable", out)

    def test_degraded_strategy_marks_the_reader_degraded(self):
        self.reach("spec-check=inline-degraded:no sub-agent tool in this session",
                   capabilities="workflow=no,subagent=no,team=no")
        self.record("Which file format?")
        self.assertEqual(self.check_file()["reader"], "degraded")

    def test_a_degraded_note_on_the_step_marks_the_reader_degraded(self):
        self.reach()
        code, out = self.sdlc("note", "--degraded", "subagent", "--reason", "unavailable", "--step", "spec-check",
                              "--slug", "demo")
        self.assertEqual(code, 0, out)
        self.record("Which file format?")
        self.assertEqual(self.check_file()["reader"], "degraded")

    def test_replacing_the_record_is_allowed_until_the_first_resolve(self):
        self.reach()
        self.record("First?")
        self.record("Second?", "Third?")
        data = self.check_file()
        self.assertEqual([(q["id"], q["question"]) for q in data["questions"]], [("Q2", "Second?"), ("Q3", "Third?")])
        self.assertEqual(data["issued"], 3)
        self.resolve("Q2")
        out = self.record("Fourth?", expect=4)
        self.assertIn("error=check_already_resolving", out)
        self.assertEqual([q["question"] for q in self.check_file()["questions"]], ["Second?", "Third?"])

    def change_design(self, line):
        """A changed design.md after the check settled: the claim card, then spec-check again."""
        self.assertEqual(card_fields(self.next()[1])["step"], "claim")
        self.put("design.md", DESIGN + "\n## Non-goals\n\n%s\n" % line)
        code, text = self.next()
        fields = card_fields(text)
        self.assertEqual((fields["state"], fields["step"]), ("do", "spec-check"), text)
        return fields

    def test_a_changed_design_carries_the_settled_questions(self):
        self.reach()
        self.record("Which file format?")
        self.resolve("Q1", "answered", "CSV")
        fields = self.change_design("No scheduled exports.")
        self.assertEqual(fields["visit"], "2/3")
        self.record("Which time zone?")  # the new visit records its reader; the settled Q1 stays as it was
        data = self.check_file()
        self.assertEqual([(q["id"], q["question"], q["pile"], q["resolution"], q["visit"]) for q in data["questions"]],
                         [("Q1", "Which file format?", "answered", "CSV", 1), ("Q2", "Which time zone?", None, None, 2)])
        self.assertEqual((data["visit"], data["issued"]), (2, 2))
        result = self.settled()
        self.assertFalse(result.ok)
        self.assertIn("Q2", result.detail)
        self.assertNotIn("Q1", result.detail)  # the carried question is settled
        out = self.resolve("Q1", "minor", "XLSX", expect=4)
        self.assertIn("error=already_settled:Q1", out)
        self.resolve("Q2", "minor", "UTC")
        self.assertEqual(card_fields(self.next()[1])["step"], "claim")

    def test_a_new_visit_may_replace_its_own_record_but_keeps_the_carried_one(self):
        self.reach()
        self.record("Which file format?")
        self.resolve("Q1", "answered", "CSV")
        self.change_design("No scheduled exports.")
        self.record("Which time zone?")
        self.record("Which locale?", "Which encoding?")  # the carried, settled Q1 does not block a replace
        data = self.check_file()
        self.assertEqual([(q["id"], q["pile"]) for q in data["questions"]],
                         [("Q1", "answered"), ("Q3", None), ("Q4", None)])
        self.resolve("Q3", "minor", "en-GB")
        out = self.record("Anything else?", expect=4)
        self.assertIn("error=check_already_resolving", out)

    def test_an_empty_visit_keeps_the_issued_ids(self):
        self.reach()
        self.record("Which file format?", "Which delimiter?")
        self.resolve("Q1", "answered", "CSV")
        self.resolve("Q2", "minor", "comma")
        self.change_design("No scheduled exports.")
        self.record(text='{"questions": []}')
        self.assertEqual(self.check_file()["issued"], 2)
        fields = self.change_design("No scheduled exports, and no PDF.")
        self.assertEqual(fields["visit"], "3/3")
        self.record("Which time zone?")
        self.assertEqual([q["id"] for q in self.check_file()["questions"]], ["Q1", "Q2", "Q3"])

    def test_a_check_file_written_before_issued_and_visit_still_reads(self):
        # A file written before the question records carried `issued` and per-question `visit` has
        # neither: it validates, settles, and a new visit numbers after its highest id.
        self.reach()
        self.record("Which file format?", "Which delimiter?")
        self.resolve("Q1", "answered", "CSV")
        self.resolve("Q2", "minor", "comma")
        data = self.check_file()
        data.pop("issued", None)
        for question in data["questions"]:
            question.pop("visit", None)
        self.put("spec/demo.check.json", json.dumps(data))
        self.assertEqual(schema.validate(data, manifest.load_schema("check")), [])
        self.assertEqual(checks.read_check(self.context()), (data, None))
        self.assertTrue(self.settled().ok)
        self.change_design("No scheduled exports.")
        self.record("Which time zone?")
        data = self.check_file()
        self.assertEqual([(q["id"], q["pile"], q["visit"]) for q in data["questions"]],
                         [("Q1", "answered", 1), ("Q2", "minor", 1), ("Q3", None, 2)])
        self.assertEqual(data["issued"], 3)

    def test_a_new_visit_with_the_same_empty_answer_still_makes_progress(self):
        self.reach()
        self.record(text='{"questions": []}')
        self.assertEqual(card_fields(self.next()[1])["step"], "claim")
        self.put("design.md", DESIGN + "\n## Non-goals\n\nNo scheduled exports.\n")
        self.assertEqual(card_fields(self.next()[1])["step"], "spec-check")
        self.record(text='{"questions": []}')
        self.assertEqual(card_fields(self.next()[1])["step"], "claim")


class TestSettled(SpecCheckCase):
    def test_empty_question_list_is_settled(self):
        self.reach()
        self.assertFalse(self.settled().ok)  # nothing recorded yet
        self.record(text='{"questions": []}')
        result = self.settled()
        self.assertTrue(result.ok, result.detail)
        code, text = self.next()
        self.assertEqual(card_fields(text)["step"], "claim", text)

    def test_the_check_names_what_is_missing(self):
        self.reach()
        result = self.settled()
        self.assertEqual((result.ok, result.detail), (False, "spec/demo.check.json is missing"))
        self.put("spec/demo.check.json", "not json")
        self.assertIn("is not readable JSON", self.settled().detail)
        self.put("spec/demo.check.json", json.dumps({"schema": "agentic-sdlc/check@1"}))
        self.assertIn("spec/demo.check.json:", self.settled().detail)
        self.record("One?", "Two?")
        result = self.settled()
        self.assertFalse(result.ok)
        self.assertIn("Q1", result.detail)
        self.assertIn("Q2", result.detail)
        self.resolve("Q1")
        self.assertIn("Q2", self.settled().detail)
        self.assertNotIn("Q1", self.settled().detail)

    def test_the_check_wants_the_spec_artifact(self):
        self.reach()
        self.record("One?")
        data = self.check_file()
        data["artifact"] = "plan"
        self.put("spec/demo.check.json", json.dumps(data))
        result = self.settled()
        self.assertFalse(result.ok)
        self.assertIn("artifact", result.detail)

    def test_spec_edit_after_check_keeps_the_check_settled(self):
        self.reach()
        self.record("Which file format?")
        self.resolve("Q1")
        self.assertEqual(card_fields(self.next()[1])["step"], "claim")
        recorded = self.check_file()["body_fingerprint"]
        self.put("spec/demo.md", SPEC_BODY + "\n- The export also lists the report title.\n")
        self.assertNotEqual(fingerprint.body_fp(self.pkg() / "spec" / "demo.md"), recorded)
        result = self.settled()
        self.assertTrue(result.ok, result.detail)
        code, text = self.next()
        self.assertEqual(card_fields(text)["step"], "claim", text)
        self.assertEqual(self.state()["steps"]["spec-check"]["visits"], 1)  # the reader did not run again


class TestResolve(SpecCheckCase):
    def test_resolve_answered_and_minor(self):
        self.reach()
        self.record("Which file format?", "Which delimiter?")
        out = self.resolve("Q1", "answered", "CSV, as the criteria say")
        self.assertIn("resolved=Q1", out)
        self.resolve("Q2", "minor", "comma, an author's call")
        first, second = self.check_file()["questions"]
        self.assertEqual((first["pile"], first["resolution"], first["answer_seq"], first["author_call"]),
                         ("answered", "CSV, as the criteria say", None, False))
        self.assertEqual((second["pile"], second["resolution"], second["answer_seq"], second["author_call"]),
                         ("minor", "comma, an author's call", None, True))
        self.assertEqual(schema.validate(self.check_file(), manifest.load_schema("check")), [])
        self.assertTrue(self.settled().ok)
        self.assertEqual(card_fields(self.next()[1])["step"], "claim")

    def test_theirs_needs_an_answer_or_an_author_call(self):
        self.reach()
        self.record("Which file format?", "Which delimiter?", "Which encoding?")
        out = self.resolve("Q1", "theirs", "UTF-8", expect=4)
        self.assertIn("error=theirs_needs_answer_or_author_call", out)
        seq = self.answer_seq()
        out = self.resolve("Q1", "theirs", "UTF-8", "--answer-seq", str(seq), "--author-call", expect=4)
        self.assertIn("error=theirs_needs_answer_or_author_call", out)
        self.assertEqual(self.check_file()["questions"][0]["pile"], None)
        self.resolve("Q1", "theirs", "UTF-8, the user said so", "--answer-seq", str(seq))
        self.resolve("Q2", "theirs", "comma; nobody was there to ask", "--author-call")
        first, second, third = self.check_file()["questions"]
        self.assertEqual((first["pile"], first["answer_seq"], first["author_call"]), ("theirs", seq, False))
        self.assertEqual((second["pile"], second["answer_seq"], second["author_call"]), ("theirs", None, True))
        self.assertEqual(third["pile"], None)

    def test_the_flags_belong_to_theirs(self):
        self.reach()
        self.record("Which file format?")
        out = self.resolve("Q1", "answered", "CSV", "--author-call", expect=4)
        self.assertIn("error=flag_needs_theirs", out)
        out = self.resolve("Q1", "minor", "CSV", "--answer-seq", "1", expect=4)
        self.assertIn("error=flag_needs_theirs", out)

    def test_theirs_answer_must_come_from_the_spec_check_step(self):
        self.start(flow="speccheck")
        self.confirm_strategy()
        self.next()  # enters intent, which may ask
        self.assertEqual(self.state()["current"], "intent")
        elsewhere = self.answer_seq("An answer given during intent.")
        self.reach(start=False)
        self.record("Which file format?")
        out = self.resolve("Q1", "theirs", "UTF-8", "--answer-seq", str(elsewhere), expect=4)
        self.assertIn("error=answer_from_other_step:intent", out)
        here = self.answer_seq("An answer given during the check.")
        self.assertGreater(here, elsewhere)
        records = logs.read(self.pkg() / "questions.jsonl")
        ask_seq = [r for r in records if r["kind"] == "ask"][-1]["seq"]
        out = self.resolve("Q1", "theirs", "UTF-8", "--answer-seq", str(ask_seq), expect=4)  # an ask, not an answer
        self.assertIn("error=unknown_answer:%d" % ask_seq, out)
        out = self.resolve("Q1", "theirs", "UTF-8", "--answer-seq", "999", expect=4)
        self.assertIn("error=unknown_answer:999", out)
        self.resolve("Q1", "theirs", "UTF-8", "--answer-seq", str(here))
        self.assertEqual(self.check_file()["questions"][0]["answer_seq"], here)

    def test_resolve_refuses_unknown_or_settled_ids(self):
        self.reach()
        self.record("Which file format?")
        out = self.resolve("Q2", expect=4)
        self.assertIn("error=unknown_question:Q2", out)
        out = self.resolve("Q1", resolution="   ", expect=4)
        self.assertIn("error=resolution_empty", out)
        self.assertEqual(self.check_file()["questions"][0]["pile"], None)
        self.resolve("Q1", resolution="CSV")
        out = self.resolve("Q1", resolution="XLSX", expect=4)
        self.assertIn("error=already_settled:Q1", out)
        self.assertEqual(self.check_file()["questions"][0]["resolution"], "CSV")
        code, out = self.sdlc("check-resolve", "--slug", "demo", "--id", "Q1", "--pile", "maybe", "--resolution", "x")
        self.assertEqual(code, 2, out)  # usage: not one of the three piles

    def test_resolve_needs_a_record_and_the_spec_check_step(self):
        self.start(flow="speccheck")
        out = self.resolve("Q1", expect=4)
        self.assertIn("error=not_current_step", out)
        self.reach(start=False)
        out = self.resolve("Q1", expect=4)
        self.assertIn("error=check_missing", out)
        self.put("spec/demo.check.json", "not json")
        out = self.resolve("Q1", expect=4)
        self.assertIn("error=check_invalid", out)


class TestSettlementRules(SpecCheckCase):
    """A hand-edited check file must keep the settlement `check-resolve` records: a pile with its
    resolution, `theirs` with exactly one of an answer and an author's call, `minor` as an author's
    call. The schema subset cannot state these, so `checks.read_check` does (`check_invalid:<problem>`)."""

    BAD = {
        "a pile with no resolution": ({"pile": "answered", "resolution": None}, "needs a resolution"),
        "a pile with a blank resolution": ({"pile": "answered", "resolution": "  "}, "needs a resolution"),
        "theirs with neither": ({"pile": "theirs", "resolution": "UTF-8", "answer_seq": None, "author_call": False},
                                "exactly one of answer_seq and author_call"),
        "theirs with both": ({"pile": "theirs", "resolution": "UTF-8", "answer_seq": 3, "author_call": True},
                             "exactly one of answer_seq and author_call"),
        "minor that is no author's call": ({"pile": "minor", "resolution": "comma", "author_call": False},
                                           "minor is an author's call"),
    }

    def test_each_rule_is_a_check_invalid_problem(self):
        self.reach()
        self.record("Which encoding?", "Which delimiter?")
        good = self.check_file()
        for name, (change, problem) in self.BAD.items():
            with self.subTest(case=name):
                data = json.loads(json.dumps(good))
                data["questions"][0].update(change)
                self.assertEqual(schema.validate(data, manifest.load_schema("check")), [])  # the schema allows it
                self.put("spec/demo.check.json", json.dumps(data))
                found, why = checks.read_check(self.context())
                self.assertIsNone(found)
                self.assertIn("spec/demo.check.json: /questions/0: ", why)
                self.assertIn(problem, why)
                result = self.settled()
                self.assertFalse(result.ok)
                self.assertIn(problem, result.detail)
                out = self.resolve("Q2", "minor", "comma", expect=4)
                self.assertIn("error=check_invalid:", out)
                self.assertIn(problem, out)
        self.put("spec/demo.check.json", json.dumps(good))
        self.resolve("Q1", "theirs", "UTF-8", "--author-call")
        self.resolve("Q2", "minor", "comma")
        self.assertTrue(self.settled().ok)


# A secret-shaped value, built in pieces so the file itself holds none.
FAKE_TOKEN = "gh" + "p_" + "R8kLq2Wv9XmT4zNp7Hs3Jd6Fb1Yc5Ge0Ua8K"


class TestMasking(SpecCheckCase):
    def test_reader_text_and_resolution_are_masked(self):
        self.reach()
        out = self.record("Is %s the key to use?" % FAKE_TOKEN)
        self.assertNotIn(FAKE_TOKEN, out)
        question = self.check_file()["questions"][0]
        self.assertEqual(question["question"], "Is ***MASKED*** the key to use?")
        self.assertNotIn(FAKE_TOKEN, question["why"])
        self.assertIn("***MASKED***", question["why"])
        out = self.resolve("Q1", "minor", "Use %s for now." % FAKE_TOKEN)
        self.assertNotIn(FAKE_TOKEN, out)
        raw = (self.pkg() / "spec" / "demo.check.json").read_text(encoding="utf-8")
        self.assertNotIn(FAKE_TOKEN, raw)
        self.assertEqual(self.check_file()["questions"][0]["resolution"], "Use ***MASKED*** for now.")
        code, text = self.next()  # the claim card lists the author's call with its question and resolution
        self.assertEqual(card_fields(text)["step"], "claim", text)
        self.assertIn("author_call=", text)
        self.assertNotIn(FAKE_TOKEN, text)
        self.assertIn("***MASKED***", text)


class TestPackaging(SpecCheckCase):
    def test_the_check_check_and_schema_are_registered(self):
        self.assertIn("check", manifest.SCHEMA_NAMES)
        self.assertIn("settled", manifest.CHECK_PARAMS)
        self.assertEqual(manifest.CHECK_PARAMS["settled"], ((), ()))
        self.assertEqual(manifest.load_schema("check")["$id"], "agentic-sdlc/check@1")
        flow_schema = manifest.load_schema("flow")
        enum = flow_schema["properties"]["steps"]["items"]["properties"]["done_when"]["items"]["properties"]["check"]["enum"]
        self.assertIn("settled", enum)
        self.assertEqual(checks.describe({"check": "settled"}, {}),
                         "every question of the spec check is settled with `sdlc check-resolve`")

    def test_the_fixture_flow_validates_with_its_role_file(self):
        flow = manifest.load_flow(self.root, "speccheck")
        self.assertEqual(manifest.validate_flow(flow, self.root, check_files=True), [])
        (self.root / "agents" / (ROLE + ".md")).unlink()
        errors = manifest.validate_flow(manifest.load_flow(self.root, "speccheck"), self.root, check_files=True)
        self.assertTrue(any("role_file_missing:" + ROLE in e for e in errors), errors)

    def test_the_role_file_is_read_only_and_has_a_cursor_mirror(self):
        text = (REPO / "agents" / (ROLE + ".md")).read_text(encoding="utf-8")
        head, body = text[4:].split("\n---\n", 1)
        fields = dict(line.split(": ", 1) for line in head.splitlines())
        self.assertEqual(fields["name"], ROLE)
        self.assertEqual(fields["tools"], "Read")  # the reader reads only the files its card names
        self.assertIn('{"questions": [{"question"', body)
        self.assertIn('{"questions": []}', body)
        mirror = (REPO / "cursor" / "agents" / (ROLE + ".md")).read_text(encoding="utf-8")
        self.assertTrue(mirror.endswith(body))
        self.assertIn("readonly: true", mirror)
        self.assertIn("permissionMode: readonly", mirror)

    def test_the_mandated_fresh_pin_reads_only_the_real_flows(self):
        text = (TESTS / "test_sdlc_manifest.py").read_text(encoding="utf-8")
        self.assertIn("for flow_id in DESIGN_ORDER:", text)  # the pin walks the real flows by id
        self.assertIn("manifest.load_flow(REPO, flow_id)", text)  # from the repository, not a fixture root


if __name__ == "__main__":
    unittest.main()
