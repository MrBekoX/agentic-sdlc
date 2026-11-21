"""Lock Grok project-catalog Rhai ports of the Claude JS orchestration loops.

Reads the shipped `.grok/workflows/*.rhai` files and the Grok invocation
column in skill bodies. Does not re-implement the orchestrator.
"""
import json
import re
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
GROK_WF = REPO / ".grok" / "workflows"
SKILLS = REPO / "skills"

NAMED = ("spec-plan-draft", "multi-lens-review", "skill-draft")

GROK_HOST = (
    "agent(",
    "parallel(",
    "phase(",
    "complete(",
    "pause(",
    "agent_type",
    "output_schema",
    "capability_mode",
)
CLAUDE_JS = (
    "export const meta",
    "await ",
    "agentType",
)

GROK_SKILLS = (
    "agentic-sdlc-pipeline",
    "dispatch-strategy",
    "spec-authoring",
    "plan-authoring",
    "security-audit",
    "code-quality-review",
)


def _read(path):
    return path.read_text(encoding="utf-8")


class TestGrokRhaiCatalog(unittest.TestCase):
    def test_three_scripts_exist_with_matching_meta_name(self):
        for name in NAMED:
            path = GROK_WF / f"{name}.rhai"
            self.assertTrue(path.is_file(), f"missing {path.relative_to(REPO)}")
            text = _read(path)
            self.assertTrue(
                text.lstrip().startswith("let meta"),
                f"{name}: first statement is not let meta",
            )
            self.assertIn(f'name: "{name}"', text)

    def test_grok_host_tokens_present_claude_js_tokens_absent(self):
        for name in NAMED:
            text = _read(GROK_WF / f"{name}.rhai")
            for tok in GROK_HOST:
                if tok == "parallel(" and name in ("spec-plan-draft", "skill-draft"):
                    continue
                if tok == "agent(" and name == "multi-lens-review":
                    continue
                if tok == "agent_type" and name == "skill-draft":
                    continue
                self.assertIn(tok, text, f"{name} missing Grok token {tok!r}")
            for tok in CLAUDE_JS:
                self.assertNotIn(tok, text, f"{name} still has Claude JS token {tok!r}")
            self.assertIsNone(
                re.search(r"(?<![A-Za-z_])schema:", text),
                f"{name} still has Claude JS schema: option",
            )

    def test_fail_closed_pause_on_empty_required_args(self):
        spec = _read(GROK_WF / "spec-plan-draft.rhai")
        multi = _read(GROK_WF / "multi-lens-review.rhai")
        skill = _read(GROK_WF / "skill-draft.rhai")
        self.assertIn('pause("verification"', spec)
        self.assertIn("empty/missing `context`", spec)
        self.assertIn('pause("verification"', multi)
        self.assertIn("empty/missing `scope`", multi)
        self.assertIn('pause("verification"', skill)
        self.assertIn("empty/missing `context`", skill)

    def test_spec_plan_smoke_completes_without_agent(self):
        text = _read(GROK_WF / "spec-plan-draft.rhai")
        idx = text.find('if depth == "smoke"')
        self.assertGreaterEqual(idx, 0, "missing depth smoke branch")
        end = text.find("let ctx_block", idx)
        self.assertGreater(end, idx)
        chunk = text[idx:end]
        self.assertIn("complete(", chunk)
        self.assertNotIn("agent(", chunk)
        self.assertIn("Smoke Eval Draft", text)

    def test_spec_plan_dispatches_plugin_qualified_agent_types(self):
        text = _read(GROK_WF / "spec-plan-draft.rhai")
        self.assertIn('agent_type: "agentic-sdlc:spec-plan-author"', text)
        self.assertIn('agent_type: "agentic-sdlc:spec-plan-critic"', text)

    def test_multi_lens_presets_and_unverified_not_dropped(self):
        text = _read(GROK_WF / "multi-lens-review.rhai")
        self.assertIn('"security"', text)
        self.assertIn('"quality"', text)
        self.assertIn("agentic-sdlc:security-reviewer", text)
        self.assertIn("agentic-sdlc:code-reviewer", text)
        self.assertIn("agentic-sdlc:software-architect", text)
        self.assertIn("unverified, not dropped", text)

    def test_multi_lens_missing_answers_are_not_a_clean_or_confirmed_review(self):
        """Parity with workflows/multi-lens-review.js (behaviour tested in
        test_multi_lens_review_workflow.py). Rhai cannot run here, so the structure is pinned."""
        text = _read(GROK_WF / "multi-lens-review.rhai")
        # Every lens silent: pause, never a clean `complete(...)` with zero findings.
        self.assertIn(
            'pause("verification", "multi-lens-review: no lens returned an answer (" + incomplete_names', text,
        )
        self.assertLess(
            text.index("no lens returned an answer"), text.index("if findings.len() == 0"),
            "the all-lenses-silent pause must come before the no-findings result",
        )
        # A lens without an answer is reported, and the result says whether the review is complete.
        self.assertIn("incompleteLenses: incomplete", text)
        self.assertIn("complete: incomplete.len() == 0 && unverified.len() == 0", text)
        # Zero verifier votes: unverified, decided before anything can be confirmed.
        tail = text.split("let verdicts = parallel(vjobs);", 1)[1]
        self.assertIsNone(re.search(r"total_votes\s*>\s*0\s*&&", tail), "zero votes must not be a pass")
        self.assertLess(tail.index("if total_votes == 0"), tail.index("confirmed.push("))
        self.assertIn("no verifier answered", tail)
        # A drop needs a strict majority of the REQUESTED skeptics, never of those that answered.
        self.assertIn("refuted_votes * 2 > votes", tail)
        self.assertIsNone(re.search(r"refuted_votes\s*\*\s*2\s*>\s*total_votes", tail))
        self.assertIn("refuted_votes > 0 && total_votes < votes", tail)
        # Only a boolean verdict is a vote, and only an array is a lens answer.
        self.assertIn('type_of(v.output.refuted) == "bool"', tail)
        self.assertIn('type_of(r.output.findings) == "array"', text)

    def test_spec_plan_final_critic_receives_the_fenced_context(self):
        """Parity with workflows/spec-plan-draft.js: the last audit sees the same context."""
        text = _read(GROK_WF / "spec-plan-draft.rhai")
        final = text.split("let final_prompt =", 1)[1].split("let final_critique", 1)[0]
        self.assertIn("final_prompt += ctx_block;", final)
        self.assertIn("final_prompt += draft_md;", final)

    def test_multi_lens_short_votes_are_counted_before_any_classification(self):
        """Structural parity: dropped results cannot conceal a missing requested vote."""
        tail = _read(GROK_WF / "multi-lens-review.rhai").split("let verdicts = parallel(vjobs);", 1)[1]
        self.assertLess(tail.index("short_votes += 1"), tail.index("if total_votes == 0"),
                        "short-vote coverage must include dropped, unverified and confirmed partitions")
        self.assertEqual(tail.count("short_votes += 1"), 1, "do not double-count confirmed partial votes")

    def test_multi_lens_find_splices_each_lens_key_into_the_stem(self):
        """The Find loop must build each lens prompt via splice_marker, not str.replace.

        Recorded rationale corrected 2026-09-20: xAI's own create-workflow reference states that
        Rhai string mutators such as `trim()` and `replace()` change the receiver IN PLACE and
        return `()`. The earlier note here claimed the opposite. The real defect was that
        `prompt.replace(...)` was used as an EXPRESSION whose value was assigned, so the assigned
        value was `()` and every Find job kept a literal {lens}. splice_marker is a pure function
        and is the right shape; banning `.replace(` keeps the in-place/expression confusion out.
        """
        text = _read(GROK_WF / "multi-lens-review.rhai")
        self.assertIsNone(
            re.search(r"\.replace\s*\(", text),
            "shipped Rhai still calls replace(); it mutates in place and returns (), so its value "
            "must never be assigned - use the pure splice_marker helper instead",
        )
        find_loop = text.split('phase("Find")', 1)[1].split("let results = parallel(jobs)", 1)[0]
        self.assertRegex(
            find_loop,
            r'let prompt = splice_marker\(\s*find_stem\s*,\s*"\{lens\}"\s*,\s*k\s*\)',
            "Find loop must assign prompt from splice_marker(find_stem, \"{lens}\", k)",
        )
        self.assertIn("jobs.push", find_loop)
        helper = text.split("fn splice_marker", 1)[1].split("\n}", 1)[0]
        self.assertIn("index_of", helper)
        self.assertIn("sub_string", helper)
        self.assertIn("piece", helper)

    def test_untrusted_fence_or_json_encode(self):
        for name in NAMED:
            text = _read(GROK_WF / f"{name}.rhai")
            self.assertIn("json_encode", text, f"{name} missing json_encode")
            self.assertIn("[UNTRUSTED", text, f"{name} missing untrusted delimiter")

    def test_plugin_manifest_does_not_claim_workflow_component(self):
        manifest = _read(REPO / ".grok-plugin" / "plugin.json")
        self.assertNotIn("workflows", manifest)


def _runtime_adapter_section(heading_prefix):
    text = _read(REPO / "docs" / "runtime-adapter.md")
    start = text.index("\n## " + heading_prefix)
    end = text.find("\n## ", start + 1)
    return text[start:end if end >= 0 else len(text)]


class TestGrokSpecPlanDraftHasTwoPrograms(unittest.TestCase):
    """Two spec-plan-draft.rhai files exist on purpose: different programs, different consumers.

    .grok/workflows/spec-plan-draft.rhai is the 0.6.0 project-catalog script reached by
    `/workflow spec-plan-draft`; workflows/grok/spec-plan-draft.rhai is the 0.7.0 runner
    engine that scripts/sdlc_runner/loop.py stages byte for byte with its sha256. Merging
    them breaks the engine pins in TestGrokRunnerEngine and the catalog behaviour above.
    """

    CATALOG = GROK_WF / "spec-plan-draft.rhai"
    ENGINE = REPO / "workflows" / "grok" / "spec-plan-draft.rhai"

    def test_both_files_exist_and_are_different_programs(self):
        self.assertTrue(self.CATALOG.is_file())
        self.assertTrue(self.ENGINE.is_file())
        self.assertNotEqual(_read(self.CATALOG), _read(self.ENGINE))

    def test_each_file_has_its_own_consumer(self):
        loop = _read(REPO / "scripts" / "sdlc_runner" / "loop.py")
        # The runner stages only the engine; it never reads the project catalog.
        self.assertIn('"workflows" / "grok" / "spec-plan-draft.rhai"', loop)
        self.assertNotIn(".grok", loop)
        # The catalog script is named for `/workflow spec-plan-draft` by its meta name.
        self.assertRegex(_read(self.CATALOG), r'name:\s*"spec-plan-draft"')

    def test_docs_record_both_roles_and_the_follow_up(self):
        docs = {
            ".grok-plugin/README.md": _read(REPO / ".grok-plugin" / "README.md"),
            "docs/runtime-adapter.md#Grok": _runtime_adapter_section("Grok CLI adapter"),
        }
        for name, text in docs.items():
            flat = " ".join(text.split())
            for marker in (
                "Two `spec-plan-draft.rhai` files",
                "`.grok/workflows/spec-plan-draft.rhai` is the 0.6.0 project-catalog script",
                "`/workflow spec-plan-draft`",
                "not delivered by `grok plugin install`",
                "`workflows/grok/spec-plan-draft.rhai` is the 0.7.0 runner engine",
                "sha256",
                "byte for byte",
                "follow-up",
            ):
                self.assertIn(marker, flat, f"{name} missing {marker}")


class TestGrokSkillInvocationColumn(unittest.TestCase):
    def test_named_skills_instruct_grok_workflow_tool(self):
        for skill in GROK_SKILLS:
            text = _read(SKILLS / skill / "SKILL.md")
            with self.subTest(skill=skill):
                self.assertRegex(
                    text,
                    r"/workflow |workflow` tool",
                    f"{skill} does not name Grok /workflow or the workflow tool",
                )
                self.assertIn("do not call claude js `workflow`", text.lower())

    def test_pipeline_and_playbook_name_spec_plan_draft(self):
        skill = _read(SKILLS / "agentic-sdlc-pipeline" / "SKILL.md")
        playbook = _read(SKILLS / "agentic-sdlc-pipeline" / "playbook.md")
        for text in (skill, playbook):
            self.assertIn("/workflow spec-plan-draft", text)
            self.assertIn("spawn_subagent", text)
            self.assertIn(".grok/workflows/spec-plan-draft.rhai", text)

    def test_dispatch_maps_dynamic_workflow_to_rhai(self):
        text = _read(SKILLS / "dispatch-strategy" / "SKILL.md")
        self.assertIn("Grok CLI", text)
        self.assertIn("Rhai", text)
        self.assertIn(".grok/workflows", text)
        self.assertIn("spawn_subagent", text)

    def test_review_skills_name_multi_lens_review(self):
        security = _read(SKILLS / "security-audit" / "SKILL.md")
        quality = _read(SKILLS / "code-quality-review" / "SKILL.md")
        self.assertIn("/workflow multi-lens-review", security)
        self.assertIn('preset:"security"', security)
        self.assertIn("/workflow multi-lens-review", quality)
        self.assertIn('preset:"quality"', quality)

    def test_adapter_docs_describe_catalog_not_plugin_shipped(self):
        adapter = _read(REPO / "docs" / "runtime-adapter.md")
        readme = _read(REPO / ".grok-plugin" / "README.md")
        plugin = _read(REPO / "docs" / "plugin-readme.md")
        for text in (adapter, readme, plugin):
            self.assertIn(".grok/workflows", text)
        self.assertIn("not a 0.4.3 release target", adapter)
        self.assertIn("experimental", adapter.lower())
        blob = adapter.lower() + readme.lower() + plugin.lower()
        self.assertTrue(
            "not a plugin component" in blob or "not from the plugin package" in blob,
            "docs must say catalog Rhai is not a plugin component",
        )
        self.assertNotIn("this plugin does not convert `workflows/*.js`", adapter)
        self.assertNotIn("no Rhai conversion of `workflows/*.js`", plugin)



ENGINE = REPO / "workflows" / "grok" / "spec-plan-draft.rhai"
LOOP = json.loads((REPO / "flows" / "loops" / "spec-plan.json").read_text(encoding="utf-8"))


def _agent_calls(text):
    """Each `agent(` call of a Rhai script, from the call to its closing `});`."""
    calls, start = [], text.find("agent(")
    while start >= 0:
        end = text.find("});", start)
        calls.append(text[start:end + 3])
        start = text.find("agent(", end)
    return calls


class TestGrokRunnerEngine(unittest.TestCase):
    """The Grok Build engine of the spec/plan loop (plan Task 12): workflows/grok/spec-plan-draft.rhai,
    which the runner stages in the package and launches by path. Rhai cannot run here, so its
    structure is pinned; the semantics it mirrors are the Claude engine's (test_spec_plan_draft_workflow)."""

    def setUp(self):
        self.text = _read(ENGINE)
        self.code = "\n".join(line for line in self.text.splitlines() if not line.lstrip().startswith("//"))

    def test_first_statement_is_meta_named_like_the_file(self):
        self.assertTrue(self.text.startswith("let meta = #{"), self.text[:40])
        name = re.search(r'let meta = #\{\s*name: "([^"]+)"', self.text).group(1)
        self.assertEqual(name, ENGINE.stem)

    def test_reads_every_launch_arg(self):
        for key in ("slug", "workId", "mode", "maxRounds", "packageDir", "pluginRoot", "python"):
            with self.subTest(arg=key):
                self.assertIn("a.%s" % key, self.code)

    def test_role_agents_are_read_only_and_the_scribe_executes(self):
        calls = _agent_calls(self.code)
        kinds = {}
        for call in calls:
            agent_type = re.search(r'agent_type: "([^"]+)"', call).group(1)
            mode = re.search(r'capability_mode: "([^"]+)"', call).group(1)
            kinds.setdefault(agent_type, set()).add(mode)
            self.assertIn("output_schema:", call)
            self.assertRegex(call, r"label: (?:call_)?label,")
        self.assertEqual(kinds, {"agentic-sdlc:spec-plan-author": {"read-only"},
                                 "agentic-sdlc:spec-plan-critic": {"read-only"},
                                 "agentic-sdlc:draft-scribe": {"execute"}})

    def test_every_agent_result_is_checked_for_success(self):
        for var in ("r", "out", "answer"):
            with self.subTest(result=var):
                self.assertRegex(self.code, r"type_of\(%s\) != \"map\" \|\| %s\.success != true" % (var, var))
        self.assertNotIn("== ()", self.code)
        self.assertNotIn("!= ()", self.code)

    def test_draft_check_runs_before_the_critic_and_assemble_ends_it(self):
        loop_body = self.code.split("while n <= max_rounds {", 1)[1]
        self.assertLess(loop_body.index('"draft-check", ["--round", n.to_string()]'),
                        loop_body.index("agentic-sdlc:spec-plan-critic"))
        self.assertIn('run_command(run, "ingest-draft", ["--assemble"], "scribe:ingest-draft")', self.code)
        self.assertIn('let engine_id = "grok-workflow";', self.code)
        caps = LOOP["caps"]
        self.assertIn("let max_rounds = %d;" % caps["max_rounds"], self.code)
        self.assertIn("let hard_max_rounds = %d;" % caps["hard_max_rounds"], self.code)

    def test_stop_rules_follow_the_runner(self):
        self.assertIn('critique.verdict == "clean" && !any_blocking && validator == "clean"', self.code)
        self.assertIn('stop_reason = "no-progress"', self.code)
        self.assertIn("else if n >= max_rounds {", self.code)
        blocking = self.code.split("fn is_blocking(issue) {", 1)[1].split("\n}", 1)[0]
        for value in ("critical", "high", "contradiction", "blocker"):
            self.assertIn('"%s"' % value, blocking)
        self.assertIn('norm_key(issue.target) + "|" + norm_key(issue.category) + "|" + norm_key(issue.where)',
                      self.code)

    def test_modes_table_matches_the_loop_definition(self):
        def rhai(value):
            return json.dumps(value, separators=(", ", ": "))
        for name, mode in LOOP["modes"].items():
            first = [[i["role"], i["author_mode"]] for i in mode["first_round"]]
            revise = [[i["role"], i["author_mode"]] for i in mode["revise"]]
            line = '"%s": #{ artifacts: %s, first: %s, revise: %s },' % (name, rhai(mode["artifacts"]), rhai(first),
                                                                         rhai(revise))
            with self.subTest(mode=name):
                self.assertIn(line, self.code)

    def test_file_names_and_labels(self):
        for fragment in ('"draft/prompts/" + role + ".r" + n.to_string() + ".md"', '"draft/" + artifact + ".r"',
                         '"draft/critic.r" + n.to_string() + ".json"', '"draft/loop.json"', '"author:"',
                         '"author-revise:"', '"critic:" + mode + ":r"', 'label += ":final";'):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.code)

    def test_result_is_small_and_names_the_stop(self):
        self.assertIn("complete(#{ ingested: true, stopReason: stop_reason, rounds: rounds });", self.code)
        self.assertIn("error: short(", self.code)
        short = self.code.split("fn short(text) {", 1)[1].split("\n}", 1)[0]
        self.assertIn("400", short)

    def test_no_claude_js_tokens_and_no_replace(self):
        for token in CLAUDE_JS:
            self.assertNotIn(token, self.text)
        # loop.json's own `schema:` key is data; an agent call takes `output_schema:`, never `schema:`.
        for call in _agent_calls(self.code):
            self.assertIsNone(re.search(r"(?<![A-Za-z_])schema:", call), call[:80])
        self.assertIsNone(re.search(r"\.replace\s*\(", self.code))

    def test_no_reserved_word_is_used_as_a_name(self):
        # Rhai reserves these for future use; as a variable, parameter or property they fail to parse.
        names = re.sub(r'"(?:[^"\\]|\\.)*"', '""', self.code)
        for word in ("package", "module", "default", "exit", "match", "case", "static", "var", "new", "use",
                     "with", "shared", "sync", "spawn", "thread", "go", "await", "async", "yield", "void",
                     "null", "nil", "public", "protected", "super", "goto"):
            with self.subTest(word=word):
                self.assertIsNone(re.search(r"\b%s\b" % word, names))

    def test_follows_the_runner_where_the_claude_engine_review_found_gaps(self):
        # The same rules the Claude engine's tests run (test_spec_plan_draft_workflow): the resolver's
        # slug rule, paths refused only for what ends or expands a double-quoted word, a drive root as
        # `D:/`, Python's whitespace and casefold for issue keys, one more ask for a refused critic
        # answer, and the ingest decided by its exit code.
        slug = self.code.split("fn is_slug(s) {", 1)[1].split("\n}", 1)[0]
        self.assertIn('s.sub_string(0, 1) == "-"', slug)
        self.assertNotIn("s.len() - 1", slug)
        path = self.code.split("fn runner_path(p) {", 1)[1].split("\n}", 1)[0]
        self.assertIn('["\\r", "\\n", "\\"", "`", "$", "\\u0000", "\\u201C", "\\u201D", "\\u201E"]', path)
        self.assertIn('project += "/";', self.code)
        space = self.code.split("fn py_space(piece) {", 1)[1].split("\n}", 1)[0]
        for escape in ("\\u001C", "\\u001F", "\\u0085", "\\u00A0", "\\u1680", "\\u2000", "\\u200A", "\\u2028",
                       "\\u3000"):
            self.assertIn(escape, space)
        self.assertNotIn("\\uFEFF", space)
        self.assertNotIn("to_upper", self.code)
        fold = self.code.split("fn fold_char(piece) {", 1)[1].split("\n}", 1)[0]
        self.assertIn('piece == "ß" || piece == "ẞ"', fold)
        self.assertIn("piece.to_lower()", fold)
        problem = self.code.split("fn critic_problem(c) {", 1)[1].split("\n}", 1)[0]
        for field in ("target", "severity", "kind", "category", "whatsMissing", "where", "fix"):
            self.assertIn('"issue %s"' % field, problem)
        self.assertIn("while attempt <= 2 && !have_critique {", self.code)
        self.assertIn('call_label += ":retry";', self.code)
        self.assertIn("if ingest.report.exitCode == 0 {", self.code)
        self.assertNotIn('index_of("ingested=")', self.code)

    def test_parity_fixes_from_the_rhai_review(self):
        # Found by running this script under Rhai 1.27 beside the Claude engine (2026-11-16):
        # a null coverageCheck is refused like JS refuses it, a critic answer that is not a map is
        # asked again rather than ending the run, a refused scribe call reports its output when it
        # gives no reason, the round number on draft-check's line is whole (round=1 is not
        # round=12), one trailing separator on packageDir is allowed, and the round log names the stop.
        problem = self.code.split("fn critic_problem(c) {", 1)[1].split("\n}", 1)[0]
        self.assertIn('if "coverageCheck" in c && type_of(c.coverageCheck) != "string" {', problem)
        self.assertIn('if type_of(answer) != "map" || answer.success != true {', self.code)
        self.assertNotIn("type_of(answer.output)", self.code)
        self.assertEqual(self.code.count("short(reason_of(r.report))"), 2)
        self.assertEqual(self.code.count("has_round_line(check.report.output,"), 2)
        line = self.code.split("fn has_round_line(output, prefix, n) {", 1)[1].split("\n}", 1)[0]
        self.assertIn('"0123456789".index_of(output.sub_string(next, 1)) < 0', line)
        self.assertIn("let project = project_of(pkg_one, slug);", self.code)
        self.assertIn('stopped = ", stop " + stop_reason;', self.code)

    def test_complete_is_called_only_at_the_top_level(self):
        # complete() inside a function ends the script only on some host models; at the top level
        # it ends it on every one, so helpers return the result map instead.
        for name, body in re.findall(r"^fn (\w+)\([^)]*\) \{\n(.*?)^\}", self.code, re.M | re.S):
            with self.subTest(fn=name):
                self.assertNotIn("complete(", body)
        self.assertIn("fn failure(message) {", self.code)
        self.assertGreater(self.code.count("complete(failure("), 15)


if __name__ == "__main__":
    unittest.main()
