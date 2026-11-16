"""Engine parity for the spec/plan loop (plan Task 15).

Contract: docs/agentic-sdlc/notes/2026-10-22-runner-contract.md §10 and design §5.9.2. One loop
definition (`flows/loops/spec-plan.json`) and three native engines:
- `workflows/spec-plan-draft.js` (Claude Code) and `workflows/grok/spec-plan-draft.rhai` (Grok
  Build) run the rounds themselves: same modes, default 3 and hard cap 5 rounds, the runner's file
  names, `draft-check` before each critic, the no-progress key target|category|where, and
  `ingest-draft --assemble` at the end;
- `workflows/zcode/spec-plan-draft.dwf.ts` (ZCode) is a driver: the runner holds the rounds, so the
  script asks `next --engine zcode-dwf --json` for each card, records with `loop-record`, and never
  runs `draft-check` or `ingest-draft` (the runner's `next` checks and ingests).
Each engine id is one the runner knows. Behaviour is tested per engine in
test_spec_plan_draft_workflow.py (Claude), test_grok_rhai_workflows.py (Grok) and
test_zcode_driver.py (ZCode); this file pins what all three must agree on.
"""
import json
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests" / "skills"))

from sdlc_runner import loop  # noqa: E402
import harness as h  # noqa: E402

LOOP = json.loads((REPO / "flows" / "loops" / "spec-plan.json").read_text(encoding="utf-8"))
CLAUDE = REPO / "workflows" / "spec-plan-draft.js"
GROK = REPO / "workflows" / "grok" / "spec-plan-draft.rhai"
ZCODE = REPO / "workflows" / "zcode" / "spec-plan-draft.dwf.ts"
ROUND_ENGINES = {"claude": CLAUDE, "grok": GROK}


def code_of(path):
    """The script without whole-line comments, and for the Claude file without its legacy path."""
    text = path.read_text(encoding="utf-8")
    if path == CLAUDE:
        text = text.split("// --- legacy", 1)[0]
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//"))


class TestRoundEngines(unittest.TestCase):
    """The two engines that run the rounds themselves."""

    def test_every_mode_and_its_roles(self):
        for name, path in ROUND_ENGINES.items():
            code = code_of(path)
            for mode, spec in LOOP["modes"].items():
                with self.subTest(engine=name, mode=mode):
                    self.assertIn("'%s'" % mode if name == "claude" else '"%s"' % mode, code)
                    for item in spec["first_round"] + spec["revise"]:
                        pair = "['%s', '%s']" % (item["role"], item["author_mode"]) if name == "claude" \
                            else '["%s", "%s"]' % (item["role"], item["author_mode"])
                        self.assertIn(pair, code)

    def test_round_caps(self):
        caps = LOOP["caps"]
        self.assertIn("const CAPS = { maxRounds: %d, hardMaxRounds: %d }" % (caps["max_rounds"], caps["hard_max_rounds"]),
                      code_of(CLAUDE))
        grok = code_of(GROK)
        self.assertIn("let max_rounds = %d;" % caps["max_rounds"], grok)
        self.assertIn("let hard_max_rounds = %d;" % caps["hard_max_rounds"], grok)

    def test_the_runner_file_names(self):
        files = LOOP["files"]
        self.assertEqual((files["prompt"], files["spec"], files["plan"], files["critic"], files["loop"]),
                         ("draft/prompts/{role}.r{round}.md", "draft/spec.r{round}.md", "draft/plan.r{round}.md",
                          "draft/critic.r{round}.json", "draft/loop.json"))
        fragments = {
            "claude": ["'draft/prompts/' + role + '.r' + n + '.md'", "'draft/spec.r' + n + '.md'",
                       "'draft/plan.r' + n + '.md'", "'draft/critic.r' + n + '.json'", "'draft/loop.json'"],
            "grok": ['"draft/prompts/" + role + ".r" + n.to_string() + ".md"',
                     '"draft/" + artifact + ".r" + n.to_string() + ".md"',
                     '"draft/critic.r" + n.to_string() + ".json"', '"draft/loop.json"'],
        }
        for name, path in ROUND_ENGINES.items():
            code = code_of(path)
            for fragment in fragments[name]:
                with self.subTest(engine=name, fragment=fragment):
                    self.assertIn(fragment, code)

    def test_draft_check_before_each_critic_and_assemble_at_the_end(self):
        for name, path in ROUND_ENGINES.items():
            code = code_of(path)
            with self.subTest(engine=name):
                check = code.index("'draft-check'" if name == "claude" else '"draft-check"')
                critic = code.index("agentic-sdlc:spec-plan-critic", check)
                ingest = code.rindex("'ingest-draft'" if name == "claude" else '"ingest-draft"')
                self.assertLess(check, critic)
                self.assertLess(critic, ingest)
                self.assertIn("--assemble", code[ingest:ingest + 60])
                self.assertEqual(LOOP["finish"], "ingest-draft --assemble")
                self.assertEqual(LOOP["draft_check"]["before"], "critic")

    def test_the_no_progress_key(self):
        self.assertEqual(LOOP["issue_key"], ["target", "category", "where"])
        self.assertIn("norm(issue.target) + '|' + norm(issue.category) + '|' + norm(issue.where)", code_of(CLAUDE))
        self.assertIn('norm_key(issue.target) + "|" + norm_key(issue.category) + "|" + norm_key(issue.where)',
                      code_of(GROK))

    def test_engine_ids_are_the_runners(self):
        self.assertIn("const ENGINE_ID = 'claude-workflow'", code_of(CLAUDE))
        self.assertIn('let engine_id = "grok-workflow";', code_of(GROK))
        for engine in ("claude-workflow", "grok-workflow", "zcode-dwf"):
            self.assertIn(engine, loop.ENGINES)
        self.assertEqual(loop.WORKFLOW_ENGINES, {"claude": "claude-workflow", "grok": "grok-workflow",
                                                 "zcode": "zcode-workflow"})


class TestZcodeDriver(unittest.TestCase):
    """The ZCode script drives the runner's own loop."""

    def setUp(self):
        self.code = code_of(ZCODE)

    def test_asks_the_runner_for_every_card(self):
        self.assertIn('"next", "--slug", slug, "--engine", "zcode-dwf", "--json"', self.code)
        self.assertIn('"loop-record"', self.code)

    def test_leaves_the_rounds_and_the_ingest_to_the_runner(self):
        for token in ("draft-check", "ingest-draft", "draft/", "issueKey", "stopReason"):
            with self.subTest(token=token):
                self.assertNotIn(token, self.code)
        self.assertEqual(LOOP["roles"]["critic"]["fresh"], True)  # hence a new actor per card


class TestAgentTypes(unittest.TestCase):
    def test_the_harness_resolves_every_engine_role(self):
        types = h.workflow_agent_types()
        self.assertEqual(types["spec-plan-draft.js"] >= {"agentic-sdlc:spec-plan-author", "agentic-sdlc:spec-plan-critic",
                                                        "agentic-sdlc:draft-scribe"}, True, types)
        self.assertEqual(types["grok/spec-plan-draft.rhai"], {"agentic-sdlc:spec-plan-author",
                                                              "agentic-sdlc:spec-plan-critic",
                                                              "agentic-sdlc:draft-scribe"})
        errors, _ = h.validate_workflow_agent_types(h.registries())
        self.assertEqual(errors, [])
        for role in LOOP["roles"].values():
            self.assertTrue((REPO / role["role_file"]).is_file(), role["role_file"])


if __name__ == "__main__":
    unittest.main()
