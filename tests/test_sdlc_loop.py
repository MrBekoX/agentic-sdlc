"""The runner-driven spec/plan loop (plan Task 8): scripts/sdlc_runner/loop.py.

Contract: docs/agentic-sdlc/notes/2026-10-22-runner-contract.md §10 (round numbering, staging,
native engine launches, machine card, loop-record, draft-check, stop rules, ingest); design §5.8
(loop definition, result schema) and §5.9 (one engine contract; the runner is the engine where a
runtime has none).

Each test drives the real `feature` or `bugfix` flow to its draft step on the harness of
tests/test_sdlc_engine.py (temp plugin root with the real flows, the two role files and the
contracts; temp git project) and then plays the roles by writing their files or calling
`sdlc loop-record`, the way a sub-agent or an engine driver would. No model and no paid CLI runs.
"""
import hashlib
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"
for folder in (REPO / "scripts", TESTS):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from test_sdlc_engine import CHAIN_LINE, PLAN_BODY, SPEC_BODY, EngineCase, card_fields, card_value  # noqa: E402
from sdlc_runner import fingerprint, frontmatter, logs, loop, manifest, schema, textio  # noqa: E402
from sdlc_runner.textio import SdlcError  # noqa: E402

CLEAN = json.dumps({"verdict": "clean", "issues": []})
NO_SUBAGENTS = ("draft=runner-loop-inline:no sub-agent tool", "draft.critic=runner-loop-inline:no sub-agent tool",
                "security=inline-degraded:no sub-agent tool", "audit=inline-degraded:no sub-agent tool")


def _issues(category="scope", where="Business Rules", text="the export file name", severity="high"):
    return json.dumps({"verdict": "issues", "issues": [{
        "target": "spec", "category": category, "severity": severity, "kind": "gap",
        "whatsMissing": text, "where": where, "fix": "name it"}]})


def _result(**changes):
    result = {
        "schema": "agentic-sdlc/draft-result@1", "mode": "spec+plan", "engine": "runner-loop",
        "spec": {"markdown": SPEC_BODY}, "plan": {"markdown": PLAN_BODY},
        "decisionPoints": [{"id": "DP1", "question": "CSV only?", "options": ["CSV", "CSV and JSON"],
                            "recommendation": "CSV"}],
        "residualCriticNotes": [], "rounds": 1, "finalVerdict": "clean", "stopReason": "clean", "critic": "fresh",
    }
    result.update(changes)
    return result


class LoopCase(EngineCase):
    def to_draft(self, flow="feature", work_type="feature", runtime="codex",
                 capabilities="workflow=no,subagent=yes,team=no", overrides=(), slug="demo"):
        """Start `flow`, confirm the strategy, write the context; return the first draft card."""
        self.start(flow=flow, work_type=work_type, runtime=runtime, work_id=slug)
        self.confirm_strategy(slug, capabilities, *overrides)
        code, text = self.next(slug)
        self.satisfy("context", text, slug)
        code, text = self.next(slug)
        self.assertEqual(card_fields(text)["step"], "draft", text)
        return text

    def record(self, role, round_no, text, slug="demo", expect=0):
        code, out = self.sdlc("loop-record", "--slug", slug, "--role", role, "--round", str(round_no), "--text", text)
        if expect is not None:
            self.assertEqual(code, expect, out)
        return out

    def role(self, text) -> tuple:
        fields = card_fields(text)
        return fields.get("role"), fields.get("round")

    def draft(self, rel, slug="demo") -> Path:
        return self.pkg(slug) / "draft" / rel

    def authors(self, round_no, slug="demo", spec=SPEC_BODY, plan=PLAN_BODY):
        """Both author roles of a spec+plan round, each followed by `next`."""
        self.record("author-spec", round_no, spec, slug)
        self.next(slug)
        self.record("author-plan", round_no, plan, slug)
        return self.next(slug)[1]

    def clean_loop(self, slug="demo"):
        self.authors(0, slug)
        self.record("critic", 1, CLEAN, slug)
        return self.next(slug)[1]


class TestStaging(LoopCase):
    def test_stage_writes_brief_and_prompt_files_inside_package(self):
        self.start(flow="feature")
        self.confirm_strategy()
        code, text = self.next()
        self.satisfy("context", text, "demo")
        before = {p for p in self.project.rglob("*") if ".git" not in p.parts}
        code, text = self.next()
        created = {p for p in self.project.rglob("*") if ".git" not in p.parts} - before
        self.assertTrue(created)
        self.assertTrue(all(self.pkg() in p.parents for p in created), sorted(map(str, created)))
        brief = self.draft("brief.md").read_text(encoding="utf-8")
        self.assertIn("Add a CSV export to the report page", brief)
        self.assertIn("Only the report page.", brief)
        self.assertIn("02-spec-driven-development", brief)
        prompt = self.draft("prompts/author-spec.r0.md").read_text(encoding="utf-8")
        role_body = frontmatter.split((REPO / "agents" / "spec-plan-author.md").read_text(encoding="utf-8"))[1]
        self.assertFalse(prompt.startswith("---"))
        self.assertIn(role_body.strip().splitlines()[0], prompt)
        self.assertIn(str(self.draft("brief.md")), prompt)
        self.assertIn(str(self.draft("spec.r0.md")), prompt)

    def test_role_path_falls_back_to_public_layout(self):
        self.assertEqual(loop.role_path(REPO, "spec-plan-critic"), REPO / "agents" / "spec-plan-critic.md")
        public = self.tmp / "public"
        role = public / "skills" / "using-agentic-sdlc" / "references" / "roles" / "spec-plan-critic.md"
        role.parent.mkdir(parents=True)
        role.write_bytes(b"---\nname: spec-plan-critic\n---\nYou are the critic.\n")
        self.assertEqual(loop.role_path(public, "spec-plan-critic"), role)
        with self.assertRaises(SdlcError) as raised:
            loop.role_path(self.tmp / "empty", "spec-plan-critic")
        self.assertEqual((raised.exception.code, raised.exception.message), (2, "role_file_missing:spec-plan-critic"))


class TestCards(LoopCase):
    def test_card_launch_line_per_runtime(self):
        with self.subTest(runtime="claude"):
            text = self.to_draft(runtime="claude", capabilities="workflow=yes,subagent=yes,team=no", slug="cl")
            launch = card_value(text, "launch")
            self.assertTrue(launch.startswith("Workflow "), text)
            call = json.loads(launch[len("Workflow "):])
            self.assertEqual(call["name"], "agentic-sdlc:spec-plan-draft")
            self.assertEqual(set(call["args"]), {"slug", "workId", "mode", "maxRounds", "packageDir", "pluginRoot", "python"})
            self.assertEqual((call["args"]["python"], call["args"]["packageDir"], call["args"]["mode"]),
                             (sys.executable, str(self.pkg("cl")), "spec+plan"))
            self.assertEqual(self.state("cl")["loop"]["engine"], "claude-workflow")
        with self.subTest(runtime="grok"):
            source = self.root / "workflows" / "grok" / "spec-plan-draft.rhai"
            source.parent.mkdir(parents=True)
            source.write_bytes(b'let meta = #{ name: "spec-plan-draft" };\n')
            text = self.to_draft(runtime="grok", capabilities="workflow=yes,subagent=yes,team=no", slug="gk")
            launch = card_value(text, "launch")
            self.assertTrue(launch.startswith("workflow "), text)
            call = json.loads(launch[len("workflow "):])
            staged = self.draft("engine/spec-plan-draft.rhai", "gk")
            self.assertEqual(call["source"], {"type": "script_path", "script_path": str(staged)})
            self.assertEqual(staged.read_bytes(), source.read_bytes())
            self.assertEqual(call["agent_budget"], 3 * 3 + 3)
            self.assertEqual(self.state("gk")["loop"]["engine_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        with self.subTest(runtime="zcode"):
            text = self.to_draft(runtime="zcode", capabilities="workflow=yes,subagent=yes,team=no", slug="zc",
                                 overrides=("draft=workflow:the user asked for a ZCode workflow",
                                            "draft.critic=workflow:the user asked for a ZCode workflow"))
            launch = card_value(text, "launch")
            self.assertTrue(launch.startswith("CreateWorkflow "), text)
            call = json.loads(launch[len("CreateWorkflow "):])
            self.assertEqual(call["path"], str(self.root / "workflows" / "zcode" / "spec-plan-draft.dwf.ts"))
            self.assertEqual(set(call["args"]), {"slug", "pluginRoot", "python"})
        for runtime, needle in (("codex", "spawn_agent"), ("kimi", "Agent(subagent_type"), ("cursor", "Task tool")):
            with self.subTest(runtime=runtime):
                text = self.to_draft(runtime=runtime, slug=runtime)
                self.assertEqual(self.role(text), ("author-spec", "0/3"))
                self.assertIn(needle, card_fields(text)["delegate"])
                self.assertIsNone(card_value(text, "launch"))

    def test_machine_card_json_shape(self):
        self.to_draft()
        code, out = self.sdlc("next", "--slug", "demo", "--json")
        self.assertEqual(code, 0, out)
        data = json.loads(out.splitlines()[0])
        self.assertEqual(set(data), {"state", "step", "role", "round", "max_rounds", "prompt_path", "write", "schema", "then"})
        self.assertEqual((data["state"], data["step"], data["role"], data["round"], data["max_rounds"]),
                         ("do", "draft", "author-spec", 0, 3))
        self.assertEqual(data["prompt_path"], str(self.draft("prompts/author-spec.r0.md")))
        self.assertEqual(data["write"], str(self.draft("spec.r0.md")))
        self.assertIsNone(data["schema"])
        self.assertIn("next --slug demo", data["then"])
        self.assertRegex(out.splitlines()[-1], CHAIN_LINE)

    def test_role_card_names_role_file_paths_and_write_target(self):
        text = self.to_draft()
        fields = card_fields(text)
        self.assertEqual(fields["role_file"], str(self.root / "agents" / "spec-plan-author.md"))
        self.assertEqual(fields["write"], "docs/agentic-sdlc/demo/draft/spec.r0.md")
        self.assertEqual(fields["prompt"], "docs/agentic-sdlc/demo/draft/prompts/author-spec.r0.md")
        text = self.authors(0)
        self.assertEqual(self.role(text), ("critic", "1/3"))
        fields = card_fields(text)
        reads = [json.loads(line[len("read="):]) for line in text.splitlines() if line.startswith("read=")]
        # The brief comes first: the critic checks the drafts against the request, the gate feedback and,
        # in plan mode, the approved spec, which only the brief carries.
        self.assertEqual(reads, [str(self.draft("brief.md")), str(self.draft("spec.r0.md")),
                                 str(self.draft("plan.r0.md")), str(self.draft("validator.r1.json"))])
        self.assertTrue(self.draft("validator.r1.json").is_file())  # draft-check ran before the critic card
        self.assertEqual(fields["role_file"], str(self.root / "agents" / "spec-plan-critic.md"))
        self.assertEqual(fields["write"], "docs/agentic-sdlc/demo/draft/critic.r1.json")
        self.assertEqual(fields["schema"], str(self.root / "flows" / "schemas" / "critic.schema.json"))
        self.assertEqual(fields["mechanism"], "runner-loop")


class TestRecordAndCheck(LoopCase):
    def test_loop_record_validates_critic_json(self):
        self.to_draft()
        self.authors(0)
        out = self.record("critic", 1, "{bad", expect=4)
        self.assertIn("error=critic_invalid:", out)
        out = self.record("critic", 1, json.dumps({"verdict": "maybe", "issues": []}), expect=4)
        self.assertIn("error=critic_invalid:/verdict", out)
        out = self.record("critic", 2, CLEAN, expect=4)
        self.assertIn("error=not_current_role:critic.r1", out)
        out = self.record("author-spec", 0, SPEC_BODY, expect=4)
        self.assertIn("error=not_current_role:critic.r1", out)
        self.assertFalse(self.draft("critic.r1.json").exists())
        self.record("critic", 1, CLEAN)
        self.assertEqual(json.loads(self.draft("critic.r1.json").read_text(encoding="utf-8")), json.loads(CLEAN))

    def test_spec_plan_mode_role_order(self):
        seen = [self.role(self.to_draft())]
        self.record("author-spec", 0, SPEC_BODY)
        seen.append(self.role(self.next()[1]))
        self.record("author-plan", 0, PLAN_BODY)
        seen.append(self.role(self.next()[1]))
        self.record("critic", 1, _issues())
        seen.append(self.role(self.next()[1]))
        prompt = self.draft("prompts/author-spec.r1.md").read_text(encoding="utf-8")
        for name in ("spec.r0.md", "critic.r1.json", "validator.r1.json"):
            self.assertIn(str(self.draft(name)), prompt)
        self.record("author-spec", 1, SPEC_BODY.replace("every week", "every Monday"))
        seen.append(self.role(self.next()[1]))
        self.record("author-plan", 1, PLAN_BODY)
        seen.append(self.role(self.next()[1]))
        self.assertEqual(seen, [("author-spec", "0/3"), ("author-plan", "0/3"), ("critic", "1/3"),
                                ("author-spec", "1/3"), ("author-plan", "1/3"), ("critic", "2/3")])
        self.assertEqual([r["role"] for r in self.records("role")],
                         ["author-spec", "author-plan", "critic", "author-spec", "author-plan", "critic"])

    def test_bugfix_plan_mode_skips_author_spec(self):
        text = self.to_draft(flow="bugfix", work_type="bugfix")
        self.assertEqual(self.role(text), ("author-plan", "0/3"))
        self.assertEqual(self.state()["loop"]["mode"], "bugfix-plan")
        prompt = self.draft("prompts/author-plan.r0.md").read_text(encoding="utf-8")
        self.assertIn("## Bug", prompt)
        self.assertIn("## Acceptance Criteria", prompt)


class TestStopRules(LoopCase):
    def test_clean_critic_and_clean_validator_stops_clean(self):
        self.to_draft()
        text = self.clean_loop()
        self.assertEqual(card_fields(text)["state"], "wait-gate", text)
        result = textio.read_json(self.draft("result.json"))
        self.assertEqual((result["stopReason"], result["rounds"], result["finalVerdict"], result["critic"]),
                         ("clean", 1, "clean", "fresh"))
        self.assertEqual(frontmatter.split((self.pkg() / "spec" / "demo.md").read_text(encoding="utf-8"))[1], SPEC_BODY)
        self.assertEqual(textio.read_json(self.draft("loop.json"))["critic"], ["fresh"])
        self.assertEqual(self.state()["loop"]["stop_reason"], "clean")
        self.assertEqual(self.records("round")[-1]["stop"], "clean")
        # Each status of the lifecycle reaches the file in the call that reaches it.
        self.assertEqual(frontmatter.split((self.pkg() / "spec" / "demo.md").read_text(encoding="utf-8"))[0]["status"],
                         "reviewed")
        self.approve(text)
        code, text = self.next()
        self.assertEqual(card_fields(text)["step"], "branch")
        for name in ("spec", "plan"):
            meta = frontmatter.split((self.pkg() / name / "demo.md").read_text(encoding="utf-8"))[0]
            self.assertEqual(meta["status"], "approved", name)

    def test_clean_critic_but_validator_errors_continues(self):
        self.to_draft()
        uncovered = PLAN_BODY.replace(" (AC1)", "").replace(" for AC1", "")
        self.authors(0, plan=uncovered)
        validator = textio.read_json(self.draft("validator.r1.json"))
        self.assertIn("plan:ac_not_covered:AC1", validator["warnings"])
        self.record("critic", 1, CLEAN)
        code, text = self.next()
        self.assertEqual(self.role(text), ("author-spec", "1/3"))
        self.assertIsNone(self.state()["loop"]["stop_reason"])

    def test_repeated_issue_keys_stop_no_progress(self):
        self.to_draft()
        self.authors(0)
        self.record("critic", 1, _issues(text="the export file name"))
        self.next()
        self.authors(1, spec=SPEC_BODY.replace("every week", "every Monday"))
        self.record("critic", 2, _issues(text="still no file name", severity="medium"))
        code, text = self.next()
        self.assertEqual(card_fields(text)["state"], "wait-gate", text)
        result = textio.read_json(self.draft("result.json"))
        self.assertEqual((result["stopReason"], result["rounds"], result["finalVerdict"]), ("no-progress", 2, "issues"))
        self.assertEqual([n["whatsMissing"] for n in result["residualCriticNotes"]], ["still no file name"])
        self.assertIn("every Monday", result["spec"]["markdown"])  # the round-1 drafts are final
        sidecar = textio.read_json(self.pkg() / "spec" / "demo.review.json")
        self.assertEqual([n["whatsMissing"] for n in sidecar["residualCriticNotes"]], ["still no file name"])

    def test_max_rounds_runs_final_critic_then_stops(self):
        loop_file = self.root / "flows" / "loops" / "spec-plan.json"
        definition = textio.read_json(loop_file)
        definition["caps"]["max_rounds"] = 2
        textio.write_json_atomic(loop_file, definition)
        self.to_draft()
        self.assertEqual(self.state()["loop"]["max_rounds"], 2)
        self.authors(0)
        self.record("critic", 1, _issues(category="scope"))
        self.next()
        self.authors(1, spec=SPEC_BODY.replace("every week", "every Monday"))
        self.record("critic", 2, _issues(category="edge-cases", where="Edge Cases", text="a huge report"))
        code, text = self.next()
        self.assertEqual(card_fields(text)["state"], "wait-gate", text)
        result = textio.read_json(self.draft("result.json"))
        self.assertEqual((result["stopReason"], result["rounds"]), ("max-rounds", 2))
        self.assertEqual([n["category"] for n in result["residualCriticNotes"]], ["edge-cases"])
        self.assertFalse(self.draft("spec.r2.md").exists())  # no revision after the final critic

    def test_malformed_critic_json_keeps_role_then_halts_after_two(self):
        self.to_draft()
        self.authors(0)
        self.draft("critic.r1.json").write_bytes(b"this is not JSON\n")
        code, text = self.next()
        self.assertEqual(self.role(text), ("critic", "1/3"))
        self.assertFalse(self.draft("critic.r1.json").exists())  # set aside so the next attempt is a fresh write
        self.assertEqual(len(list(self.draft("").glob("critic.r1.rejected-*.json"))), 1)
        self.assertEqual(self.state()["loop"]["role_visits"], 1)
        self.draft("critic.r1.json").write_bytes(json.dumps({"verdict": "clean"}).encode("utf-8"))
        code, text = self.next(expect=3)
        self.assertIn("loop role cap: critic r1", text)

    def test_inline_degraded_records_critic_degraded(self):
        text = self.to_draft(capabilities="workflow=no,subagent=no,team=no", overrides=NO_SUBAGENTS)
        self.assertEqual(card_fields(text)["mechanism"], "runner-loop-inline")
        self.assertIn("yourself", card_fields(text)["delegate"])
        text = self.clean_loop()
        self.assertEqual(card_fields(text)["state"], "wait-gate", text)
        self.assertEqual(textio.read_json(self.draft("loop.json"))["critic"], ["degraded"])
        for name in ("spec", "plan"):
            self.assertEqual(textio.read_json(self.pkg() / name / "demo.review.json")["critic"], "degraded")


class TestIngest(LoopCase):
    def back_result(self, critic=CLEAN):
        """The round files a clean one-round loop leaves (what a result.json must be backed by)."""
        self.draft("spec.r0.md").write_bytes(SPEC_BODY.encode("utf-8"))
        self.draft("plan.r0.md").write_bytes(PLAN_BODY.encode("utf-8"))
        self.draft("critic.r1.json").write_bytes(critic.encode("utf-8"))

    def test_ingest_writes_frontmatter_body_and_sidecar(self):
        import resolve_work_package

        self.to_draft()
        self.back_result()
        textio.write_json_atomic(self.draft("result.json"), _result())
        code, out = self.sdlc("ingest-draft")
        self.assertEqual(code, 0, out)
        spec, plan = self.pkg() / "spec" / "demo.md", self.pkg() / "plan" / "demo.md"
        meta, body, _had = frontmatter.split(spec.read_text(encoding="utf-8"))
        self.assertEqual((meta["work_id"], body), ("demo", SPEC_BODY))
        plan_meta, plan_body, _had = frontmatter.split(plan.read_text(encoding="utf-8"))
        self.assertEqual((plan_meta["spec"], plan_meta["flow"], plan_body), ("../spec/demo.md", "feature", PLAN_BODY))
        for name, path in (("spec", spec), ("plan", plan)):
            sidecar = textio.read_json(self.pkg() / name / "demo.review.json")
            self.assertEqual(schema.validate(sidecar, manifest.load_schema("sidecar")), [])
            self.assertEqual(sidecar["body_fingerprint"], fingerprint.body_fp(path))
            self.assertEqual(sidecar["artifact"], "%s/demo.md" % name)
        self.assertEqual([p["id"] for p in textio.read_json(self.pkg() / "spec" / "demo.review.json")["decisionPoints"]],
                         ["DP1"])
        resolution = resolve_work_package.resolve(self.project, plan_path=str(plan))
        self.assertTrue(resolution.ok, resolution.errors)
        code, text = self.next()
        self.assertEqual(card_fields(text)["state"], "wait-gate", text)

    def test_ingest_rejects_schema_violation(self):
        self.to_draft()
        self.back_result()
        broken = _result()
        del broken["critic"]
        for name, result, needle in (("schema", broken, "error=result_invalid:"),
                                     ("pairing", _result(spec=None), "error=result_pairing:spec+plan"),
                                     ("mode", _result(mode="bugfix-plan", spec=None), "error=result_mode:bugfix-plan"),
                                     ("rounds", _result(rounds=2), "error=result_unbacked:"),
                                     ("body", _result(spec={"markdown": SPEC_BODY + "\nExtra.\n"}), "error=result_unbacked:")):
            with self.subTest(case=name):
                textio.write_json_atomic(self.draft("result.json"), result)
                code, out = self.sdlc("ingest-draft")
                self.assertEqual(code, 4, out)
                self.assertIn(needle, out)
                self.assertFalse((self.pkg() / "spec" / "demo.md").exists())
                self.assertFalse((self.pkg() / "plan" / "demo.md").exists())

    def test_ingest_refuses_a_fresh_claim_for_an_inline_critic(self):
        # The runner knows how its critic ran: a hand-written result cannot relabel an inline critic.
        self.to_draft(capabilities="workflow=no,subagent=no,team=no", overrides=NO_SUBAGENTS)
        self.back_result()
        textio.write_json_atomic(self.draft("result.json"), _result(engine="runner-loop-inline"))
        code, out = self.sdlc("ingest-draft")
        self.assertEqual(code, 4, out)
        self.assertIn("error=result_critic:fresh (the loop's critic ran degraded)", out)
        self.assertFalse((self.pkg() / "spec" / "demo.md").exists())
        textio.write_json_atomic(self.draft("result.json"), _result(engine="runner-loop-inline", critic="degraded"))
        code, out = self.sdlc("ingest-draft")
        self.assertEqual(code, 0, out)
        for name in ("spec", "plan"):
            self.assertEqual(textio.read_json(self.pkg() / name / "demo.review.json")["critic"], "degraded", name)
        self.assertEqual(self.state()["loop"]["critic"], ["degraded"])

    def test_ingest_refuses_an_engine_the_loop_does_not_run(self):
        self.to_draft()
        self.back_result()
        textio.write_json_atomic(self.draft("result.json"), _result(engine="claude-workflow"))
        code, out = self.sdlc("ingest-draft")
        self.assertEqual(code, 4, out)
        self.assertIn("error=result_engine:claude-workflow (the loop runs runner-loop)", out)
        self.assertFalse((self.pkg() / "spec" / "demo.md").exists())

    def test_ingest_keeps_an_honest_degraded_critic(self):
        self.to_draft()
        self.back_result()
        textio.write_json_atomic(self.draft("result.json"), _result(critic="degraded"))
        code, out = self.sdlc("ingest-draft")
        self.assertEqual(code, 0, out)
        self.assertEqual(textio.read_json(self.pkg() / "spec" / "demo.review.json")["critic"], "degraded")
        self.assertEqual(self.state()["loop"]["critic"], ["fresh"])  # the runner's own record of the round

    def test_ingest_needs_the_loop_step_and_one_ingest_per_visit(self):
        self.to_draft()
        code, out = self.sdlc("ingest-draft")  # the loop has not stopped: nothing backs a result
        self.assertEqual(code, 4, out)
        self.assertIn("error=result_unbacked:", out)
        self.back_result()
        textio.write_json_atomic(self.draft("result.json"), _result())
        self.assertEqual(self.sdlc("ingest-draft")[0], 0)
        code, out = self.sdlc("ingest-draft")
        self.assertEqual(code, 4, out)
        self.assertIn("error=already_ingested", out)
        self.sdlc("halt", "--reason", "pause")
        for argv in (["ingest-draft"], ["draft-check", "--round", "1"],
                     ["loop-record", "--role", "critic", "--round", "1", "--text", CLEAN]):
            with self.subTest(command=argv[0]):
                code, out = self.sdlc(*argv)
                self.assertEqual(code, 4, out)
                self.assertIn("error=not_active:halted", out)

    def test_assemble_needs_the_critic_files(self):
        self.to_draft(runtime="claude", capabilities="workflow=yes,subagent=yes,team=no")
        self.draft("spec.r0.md").write_bytes(SPEC_BODY.encode("utf-8"))
        self.draft("plan.r0.md").write_bytes(PLAN_BODY.encode("utf-8"))
        claim = {"schema": "agentic-sdlc/loop@1", "engine": "claude-workflow", "mode": "spec+plan", "rounds": 1,
                 "stopReason": "clean", "critic": ["fresh"]}
        textio.write_json_atomic(self.draft("loop.json"), claim)
        code, out = self.sdlc("ingest-draft", "--assemble")  # no critic ever ran
        self.assertEqual(code, 4, out)
        self.assertIn("error=loop_json_invalid:", out)
        self.draft("critic.r1.json").write_bytes(_issues().encode("utf-8"))
        code, out = self.sdlc("ingest-draft", "--assemble")  # the critic found issues: not a clean stop
        self.assertEqual(code, 4, out)
        self.assertIn("error=loop_json_invalid:", out)
        self.draft("critic.r1.json").write_bytes(CLEAN.encode("utf-8"))
        textio.write_json_atomic(self.draft("loop.json"), dict(claim, stopReason="max-rounds"))
        code, out = self.sdlc("ingest-draft", "--assemble")  # the files stop clean, the claim says otherwise
        self.assertEqual(code, 4, out)
        self.assertIn("error=loop_json_invalid:the round files say clean after round 1", out)
        self.assertFalse((self.pkg() / "spec" / "demo.md").exists())

    def test_assemble_from_engine_files(self):
        self.to_draft(runtime="claude", capabilities="workflow=yes,subagent=yes,team=no")
        self.draft("spec.r0.md").write_bytes(SPEC_BODY.encode("utf-8"))
        self.draft("plan.r0.md").write_bytes(PLAN_BODY.encode("utf-8"))
        self.draft("critic.r1.json").write_bytes(CLEAN.encode("utf-8"))
        textio.write_json_atomic(self.draft("loop.json"), {
            "schema": "agentic-sdlc/loop@1", "engine": "claude-workflow", "mode": "spec+plan", "rounds": 1,
            "stopReason": "clean", "critic": ["fresh"]})
        self.assertFalse(self.draft("result.json").exists())
        code, out = self.sdlc("ingest-draft", "--assemble")
        self.assertEqual(code, 0, out)
        result = textio.read_json(self.draft("result.json"))
        self.assertEqual((result["engine"], result["stopReason"], result["spec"]["markdown"]),
                         ("claude-workflow", "clean", SPEC_BODY))
        code, text = self.next()
        self.assertEqual(card_fields(text)["state"], "wait-gate", text)

    @unittest.skipIf(sys.platform == "win32", "symlinks need extra rights on Windows")
    def test_linked_draft_folder_is_refused(self):
        self.to_draft()
        self.authors(0)
        outside = self.tmp / "outside-draft"
        self.draft("").rename(outside)
        self.draft("").symlink_to(outside, target_is_directory=True)
        (outside / "critic.r1.json").write_bytes(b"not JSON\n")
        code, out = self.next(expect=2)  # setting the malformed critic aside would move a file outside the package
        self.assertIn("error=linked_path:draft", out)
        self.assertTrue((outside / "critic.r1.json").is_file())
        self.assertEqual(list(outside.glob("critic.r1.rejected-*.json")), [])

    def test_reject_feedback_starts_new_loop_visit(self):
        self.to_draft()
        self.clean_loop()
        code, out = self.sdlc("reject", "review", "--quote", "Add a JSON export too.")
        self.assertEqual(code, 0, out)
        code, text = self.next()
        fields = card_fields(text)
        self.assertEqual((fields["step"], fields["visit"]), ("draft", "2/3"))
        self.assertEqual(self.role(text), ("author-spec", "0/3"))
        self.assertTrue(self.draft("visit-1/spec.r0.md").is_file())
        self.assertFalse(self.draft("spec.r0.md").exists())
        self.assertIn("Add a JSON export too.", self.draft("brief.md").read_text(encoding="utf-8"))
        st = self.state()
        self.assertEqual((st["loop"]["stop_reason"], st["loop"]["visit"], st["loop"]["round"]), (None, 2, 0))
        self.assertEqual(logs.verify(self.pkg() / "transitions.jsonl")[0], True)


if __name__ == "__main__":
    unittest.main()
