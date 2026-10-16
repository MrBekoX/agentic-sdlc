"""Exercise delivered coexistence context, not model compliance or hook installation.

The regression is policy lost on direct bootstrap/focused entry. Execute each
SessionStart producer and inspect its public context; live coexistence transcripts
must separately prove that a model follows the owner selected by the user.
"""

import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest


REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
POLICY_TAG = "PROCESS_OWNER_POLICY"
COEXISTENCE_SCENARIOS = REPO / "tests" / "skills" / "evals" / "coexistence" / "scenarios.json"
# The Superpowers ref the coexistence matrix is pinned to (v6.3.0) and the skill ids verified to exist
# at that ref. Its Codex manifest declares `hooks: {}`, so no Superpowers SessionStart runs on Codex.
PINNED_SUPERPOWERS_REF = "b36e0829c6d0140e93cfef2ca599b1b07d4a7797"
PINNED_SUPERPOWERS_SKILLS = {"brainstorming", "writing-plans", "dispatching-parallel-agents",
                             "verification-before-completion"}
# Pipeline v2.1 C16 item 12 (maintainer-approved): both bootstraps state, right before the Intent
# table, that an active pipeline run owns its steps, and mark the dispatch-strategy row as once per run.
PIPELINE_OWNS_STEPS_LINE = (
    "Inside an active agentic-sdlc-pipeline run the pipeline owns every step: dispatch-strategy runs once at "
    "Step 1; its tests, security reviews and final audit use the work-type core file, security-reviewer and "
    "implementation-auditor - do not invoke or read the focused skills below for those steps."
)
DISPATCH_STRATEGY_ROW = (
    "  parallelism / delegation decision       -> agentic-sdlc:dispatch-strategy "
    "(before choosing a mechanism) (once per pipeline run)"
)


@unittest.skipIf(NODE is None, "node not available")
class TestDeliveredProcessOwnership(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contexts = {}
        for runtime, filename in (
            ("claude", "session-start.mjs"),
            ("codex", "session-start-codex.mjs"),
        ):
            result = subprocess.run(
                [NODE, str(REPO / "hooks" / filename)],
                cwd=REPO, capture_output=True, text=True, encoding="utf-8",
                timeout=30, check=True,
            )
            payload = json.loads(result.stdout)["hookSpecificOutput"]
            if payload["hookEventName"] != "SessionStart":
                raise AssertionError(payload)
            cls.contexts[runtime] = payload["additionalContext"]

    def test_owner_policy_reaches_both_focused_routes_before_dispatch(self):
        policies = []
        for runtime, context in self.contexts.items():
            with self.subTest(runtime=runtime):
                match = re.search(rf"<{POLICY_TAG}>(.*?)</{POLICY_TAG}>", context, re.S)
                self.assertIsNotNone(match, "Focused dispatch bypasses the router's owner policy")
                self.assertLess(match.end(), context.index("Intent -> skill"))
                policies.append(match.group(1))
        if len(policies) == 2:
            self.assertEqual(policies[0], policies[1], "The runtime must not change owner precedence")

    def test_policy_orders_user_choice_continuation_then_house_default(self):
        for runtime, context in self.contexts.items():
            with self.subTest(runtime=runtime):
                policy = context.split(f"<{POLICY_TAG}>")[-1].split(f"</{POLICY_TAG}>")[0]
                explicit = re.search(r"explicit .*choice wins.*superpowers:<skill>", policy)
                existing = re.search(r"Otherwise keep the established owner", policy)
                fallback = re.search(r"If no owner .*AGENTIC-SDLC", policy)
                self.assertIsNotNone(explicit, "Explicit Superpowers selection must survive bootstrap")
                self.assertIsNotNone(existing, "Re-loading a bootstrap must not steal an active phase")
                self.assertIsNotNone(fallback, "Unowned house entry needs a deterministic default")
                self.assertLess(explicit.start(), existing.start())
                self.assertLess(existing.start(), fallback.start())
                self.assertIn("Never stack both", policy)
                self.assertIn("Runtime security hooks still apply independently", policy)
                self.assertNotIn("never superpowers:brainstorming", context)

    def test_every_emitted_intent_target_is_runtime_qualified_and_exists(self):
        for runtime, context in self.contexts.items():
            with self.subTest(runtime=runtime):
                targets = re.findall(r"^\s{2}[^\n]+ -> (\S+)", context, re.M)
                self.assertGreaterEqual(len(targets), 13)
                prefix = "agentic-sdlc:"
                for target in targets:
                    self.assertTrue(target.startswith(prefix), (runtime, target))
                    skill = target.removeprefix(prefix)
                    self.assertTrue((REPO / "skills" / skill / "SKILL.md").is_file(), target)

    def test_pipeline_owns_its_steps_line_precedes_the_intent_table(self):  # pipeline v2.1 C16 item 12
        for runtime, context in self.contexts.items():
            with self.subTest(runtime=runtime):
                lines = context.split("\n")
                header = next(i for i, line in enumerate(lines) if line.startswith("Intent -> skill"))
                self.assertEqual(lines[header - 1], PIPELINE_OWNS_STEPS_LINE)
                self.assertEqual(lines.count(PIPELINE_OWNS_STEPS_LINE), 1)
                rows = [line for line in lines if "-> agentic-sdlc:dispatch-strategy" in line]
                self.assertEqual(rows, [DISPATCH_STRATEGY_ROW])
                self.assertTrue(rows[0].endswith(" (once per pipeline run)"), rows[0])


class TestDirectSkillOwnership(unittest.TestCase):
    def test_restored_owner_reload_is_explicit_and_keeps_progress(self):
        for name in ("mind-spark", "using-agentic-sdlc"):
            text = (REPO / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
            policy = text.split("## Process owner", 1)[1].split("\n## ", 1)[0]
            self.assertIn("reload", policy.lower(), name)
            self.assertIn("summar", policy.lower(), name)
            self.assertIn("saved progress", policy.lower(), name)
            self.assertIn("uninterrupted", policy.lower(), name)

    def test_owner_handoff_requires_actual_instructions_before_phase_content(self):
        paths = [REPO / "skills" / name / "SKILL.md" for name in ("mind-spark", "using-agentic-sdlc")]
        for path in paths:
            text = path.read_text(encoding="utf-8")
            policy = text.split("## Process owner", 1)[1].split("\n## ", 1)[0]
            self.assertIn("actual instructions", policy, str(path))
            self.assertIn("summary", policy, str(path))
            self.assertIn("before", policy, str(path))
            self.assertIn("already present", policy, str(path))

    @unittest.skipIf(NODE is None, "node not available")
    def test_both_bootstraps_require_loaded_procedure_not_an_owner_label(self):
        for script in ("session-start.mjs", "session-start-codex.mjs"):
            result = subprocess.run([NODE, str(REPO / "hooks" / script)], input="{}",
                capture_output=True, text=True, encoding="utf-8", check=True)
            context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
            policy = context.split("<PROCESS_OWNER_POLICY>", 1)[1].split("</PROCESS_OWNER_POLICY>", 1)[0]
            self.assertIn("actual instructions", policy, script)
            self.assertIn("summary", policy, script)
            self.assertIn("already present", policy, script)

    @unittest.skipIf(NODE is None, "node not available")
    def test_codex_bootstrap_describes_both_ordering_evidence_paths(self):
        context = json.loads(subprocess.run(
            [NODE, str(REPO / "hooks/session-start-codex.mjs")],
            input="{}", text=True, encoding="utf-8", capture_output=True, check=True,
        ).stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("earlier test run", context)
        self.assertIn("spec and matching plan", context)

    def test_router_and_direct_design_entry_resolve_owner_before_routing_or_design(self):
        for skill, next_gate in (
            ("using-agentic-sdlc", "## Routing Rule"),
            ("mind-spark", "## Depth contract"),
        ):
            with self.subTest(skill=skill):
                text = (REPO / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
                self.assertTrue("## Process owner" in text, f"{skill}: direct entry has no owner gate")
                policy = text.split("## Process owner", 1)[1].split("\n## ", 1)[0]
                self.assertLess(text.index("## Process owner"), text.index(next_gate))
                self.assertIn("explicit", policy)
                self.assertIn("superpowers:brainstorming", policy)
                self.assertIn("established owner", policy)
                self.assertIn("Never stack both", policy)
                self.assertIn("Runtime security hooks still apply independently", policy)
                self.assertIn("agentic-sdlc:mind-spark", policy)
                self.assertIn("/skills", policy)
                self.assertIn("SKILL.md", policy)
                self.assertNotIn("this house skill supersedes it", text)


class TestCoexistenceScenarioCoverage(unittest.TestCase):
    def test_live_matrix_is_separate_from_per_skill_trigger_sets(self):
        path = REPO / "tests" / "skills" / "evals" / "coexistence" / "scenarios.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], "process-owner-coexistence-v1")
        self.assertNotIn("queries", data, "Phase ownership requires transcript review, not trigger scoring")
        scenarios = data["scenarios"]
        self.assertEqual(len({case["id"] for case in scenarios}), len(scenarios))
        self.assertEqual({case["split"] for case in scenarios}, {"comparison", "held-out"})
        self.assertEqual(
            {case["entrypoint"] for case in scenarios}, {"bootstrap", "direct-mind-spark"}
        )
        owners = set()
        for case in scenarios:
            expected = case["expected_phase_skill"]
            owner, skill = expected.split(":", 1)
            owners.add(owner)
            self.assertNotIn(expected, case["competing_phase_skills"])
            self.assertTrue(case["prompt"].strip())
            if owner == "agentic-sdlc":
                self.assertTrue((REPO / "skills" / skill / "SKILL.md").is_file())
        self.assertEqual(owners, {"agentic-sdlc", "superpowers"})

    @staticmethod
    def _matrix():
        return json.loads(COEXISTENCE_SCENARIOS.read_text(encoding="utf-8"))

    def test_superpowers_owned_completion_scenario_present(self):  # AC60
        matching = [case["id"] for case in self._matrix()["scenarios"]
                    if case["expected_phase_skill"] == "superpowers:verification-before-completion"
                    and "agentic-sdlc:completion-claim-gate" in case["competing_phase_skills"]]
        self.assertTrue(matching, "no Superpowers-owned completion scenario competes with the house gate")

    def test_review_requirements_record_pinned_codex_manifest_hooks_empty(self):  # AC60
        entries = [entry for entry in self._matrix()["review_requirements"]
                   if PINNED_SUPERPOWERS_REF in entry and "hooks: {}" in entry and "SessionStart" in entry]
        self.assertTrue(entries, "no review requirement records the pinned Codex manifest's empty hooks")

    def test_all_superpowers_ids_in_pinned_set(self):  # AC60 guard: no fabricated skill id
        ids = set()
        for case in self._matrix()["scenarios"]:
            for skill_id in [case["expected_phase_skill"], *case["competing_phase_skills"]]:
                if skill_id.startswith("superpowers:"):
                    ids.add(skill_id.split(":", 1)[1])
        self.assertTrue(ids)
        self.assertEqual(ids - PINNED_SUPERPOWERS_SKILLS, set())

    def test_no_scenario_expects_superpowers_sessionstart(self):  # AC60 guard: no double SessionStart
        for case in self._matrix()["scenarios"]:
            with self.subTest(id=case["id"]):
                self.assertNotIn("superpowers", case["entrypoint"].lower())
                self.assertNotIn("SessionStart", case["prompt"])
                self.assertNotIn("SessionStart", case["prior_context"])


class TestConditionalDesignProcedure(unittest.TestCase):
    def test_incidental_entry_does_not_expose_the_house_design_procedure(self):
        skill = REPO / "skills/mind-spark"
        entrypoint = (skill / "SKILL.md").read_text(encoding="utf-8")
        reference = skill / "references/design-process.md"
        self.assertTrue(reference.is_file(), "House design steps need a conditionally loaded reference")
        procedure = reference.read_text(encoding="utf-8")
        self.assertIn("[references/design-process.md](references/design-process.md)", entrypoint)
        self.assertIn("Only when AGENTIC-SDLC owns", entrypoint)
        self.assertIn("before", entrypoint)
        for marker in ("## The flow", "### 3. Ask one question at a time", "## Output shape"):
            self.assertIn(marker, procedure)
            self.assertNotIn(marker, entrypoint, "Foreign-owner entry must not receive a competing procedure")
        self.assertLess(len(entrypoint), len(procedure) // 2)

    def test_conditional_reference_retains_the_complete_design_flow(self):
        reference = REPO / "skills/mind-spark/references/design-process.md"
        self.assertTrue(reference.is_file(), "Missing conditionally loaded design procedure")
        procedure = reference.read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"^### ([1-6])\. ", procedure, re.M), list("123456"))
        for invariant in ("the user has approved it", "## When to use", "## Depth contract", "## Excuse -> check",
                          "## No placeholders", "## Checklist", "critic pass is mandatory",
                          "Delegation Degraded: fresh-context critic unavailable",
                          "**Goal:**", "**Approach:**", "**Shape:**", "**Edges:**", "**Success looks like:**"):
            self.assertIn(invariant, procedure)


if __name__ == "__main__":
    unittest.main()
