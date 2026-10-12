"""safe-refactor ends with `implementation-control`, which used to demand a spec and a plan.

safe-refactor is a light flow: it has a Goal Lock and characterization tests, and by design no
spec or plan artifact. `resolve_work_package.py` then reports `error=no_plan`, and
implementation-control's procedure told the auditor to block the final answer on exactly that, so
the flow could not finish. The two instructions must agree, without weakening the audit for any
other flow. These are static text checks (the behaviour is an instruction, not code).
"""

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def read(rel):
    return (REPO / rel).read_text(encoding="utf-8")


def section(text, start, end):
    """Text from the line that contains `start` up to the line that contains `end`."""
    begin = text.index(start)
    return text[begin:text.index(end, begin)]


class TestSafeRefactorAuditPath(unittest.TestCase):
    def setUp(self):
        self.control = read("skills/implementation-control/SKILL.md")
        self.refactor = read("skills/safe-refactor/SKILL.md")
        self.auditor = read("agents/implementation-auditor.md")
        self.procedure = section(self.control, "## Procedure", "## Output")

    def test_the_procedure_has_an_explicit_safe_refactor_path(self):
        self.assertRegex(self.procedure, r"safe-refactor")
        self.assertIn("Goal Lock", self.procedure)
        self.assertIn("N/A (light flow: safe-refactor)", self.procedure)

    def test_the_path_is_bounded_to_safe_refactor_and_keeps_the_other_gates(self):
        # Only safe-refactor is excused from a spec/plan; any other flow without one still blocks.
        self.assertRegex(self.procedure, r"(?i)any other flow[^.\n]*keeps? the block")
        # Every non-spec/plan row stays mandatory, and a missing Goal Lock is a FAIL, not an N/A.
        self.assertRegex(self.procedure, r"(?i)every other row stays mandatory")
        self.assertRegex(self.procedure, r"(?i)missing Goal Lock[^.\n]*FAIL")

    def test_the_original_block_for_a_missing_spec_or_plan_is_still_there(self):
        self.assertIn("spec/plan artifact ambiguous or missing", self.procedure)
        self.assertRegex(self.procedure, r"(?i)block the final answer")

    def test_safe_refactor_tells_the_auditor_which_path_it_is_on(self):
        step = [line for line in self.refactor.splitlines() if "Implementation control" in line]
        self.assertEqual(len(step), 1, step)
        self.assertIn("implementation-control", step[0])
        self.assertIn("Goal Lock", step[0])
        self.assertIn("no spec or plan", step[0])

    def test_safe_refactor_does_not_claim_the_light_path_when_a_spec_or_plan_exists(self):
        # agentic-sdlc-pipeline delegates a step to safe-refactor AFTER a real spec and plan exist.
        step = [line for line in self.refactor.splitlines() if "Implementation control" in line][0]
        self.assertIn("When a spec or plan already exists", step)
        self.assertIn("agentic-sdlc-pipeline", step)
        self.assertRegex(step, r"do not claim the light path")

    def test_the_flow_line_is_a_claim_not_evidence_in_both_contracts(self):
        for name, text in (("implementation-control", self.procedure), ("implementation-auditor", self.auditor)):
            with self.subTest(contract=name):
                self.assertRegex(text, r"(?i)caller's (?:`Flow: safe-refactor` line is a )?claim, not evidence")
                self.assertRegex(text, r"exactly `no_plan`")
                self.assertRegex(text, r"(?i)if a spec or plan resolves|resolver returns a spec or a plan")

    def test_the_resolution_row_and_task_checks_are_covered_by_the_light_path(self):
        self.assertIn("N/A (light flow: no_plan)", self.procedure)
        self.assertIn("N/A (light flow: no_plan)", self.auditor)
        self.assertRegex(self.auditor, r"every task complete[^.]*do not apply")

    def test_the_auditor_contract_knows_the_goal_lock_substitute(self):
        self.assertIn("safe-refactor", self.auditor)
        self.assertIn("Goal Lock", self.auditor)

    def test_the_flow_still_ends_with_implementation_control(self):
        self.assertRegex(self.refactor, r"\*\*Implementation control\*\* — run \*\*`implementation-control`\*\*")


if __name__ == "__main__":
    unittest.main()
