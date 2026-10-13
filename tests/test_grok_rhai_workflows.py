"""Lock Grok project-catalog Rhai ports of the Claude JS orchestration loops.

Reads the shipped `.grok/workflows/*.rhai` files and the Grok invocation
column in skill bodies. Does not re-implement the orchestrator.
"""
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


if __name__ == "__main__":
    unittest.main()
