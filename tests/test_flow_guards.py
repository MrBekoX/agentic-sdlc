"""Tests for the flow-step enforcement hooks (flow-step-guard, flow-order-guard).

These drive the .mjs hooks via node with crafted transcripts, mirroring
test_hooks_policy.py. They assert that evidence is RE-DERIVED (a stub spec that
fails validate_artifacts is NOT accepted; a real tool_use IS) and that the
warn/block/deny outcomes follow AGENTIC_FLOW_GATE_BLOCK. If node is missing the
tests SKIP (never silently pass).
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
STEP_GUARD = REPO / "hooks" / "flow-step-guard.mjs"
ORDER_GUARD = REPO / "hooks" / "flow-order-guard.mjs"
RCF = "agentic-sdlc:root-cause-fix"
FB = "agentic-sdlc:feature-build"
SR = "agentic-sdlc:safe-refactor"
PIPE = "agentic-sdlc:agentic-sdlc-pipeline"


def ev_text(t):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": t}]}}


def ev_tool(name, inp):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}


def skill(s):
    return ev_tool("Skill", {"skill": s})


def agent(a):
    return ev_tool("Agent", {"subagent_type": a, "prompt": "do the audit"})


def workflow(n):
    return ev_tool("Workflow", {"name": n, "args": {"mode": "spec"}})


def bash(c):
    return ev_tool("Bash", {"command": c})


def edit(fp):
    return ev_tool("Edit", {"file_path": fp})


def _write_stub_spec(cwd):
    specs = Path(cwd) / "docs" / "agentic-sdlc" / "specs"
    specs.mkdir(parents=True, exist_ok=True)
    # A stub: passes "file exists" but fails validate_artifacts --strict (no sections).
    (specs / "stub.md").write_text("---\nwork_id: stub\nstatus: draft\n---\n\n# Stub\n\nspec\n", encoding="utf-8")


# ---- per-package artifact bodies (deep enough to pass validate_artifacts.py --strict) ----
_VALID_SPEC = """# Spec {work_id}

## Problem
This describes the problem domain in enough descriptive detail to exceed the forty-character floor.

## Business rules
The domain rules are enumerated here with enough descriptive text to clear the thin-section gate.

## Acceptance criteria
- {ac_id}: Given a valid spec written this session, when the guard runs, then the spec step passes.

## Edge cases
Boundary inputs and unusual scenarios are covered here with sufficient length for the strict gate.

## Definition of done
The work is done when every acceptance criterion is met and the validator reports a passing artifact.

## Must-not-change
The regression surface that stays byte-identical is described here with enough text for the floor.
"""

_VALID_PLAN = """# Plan {work_id}

## Task 1
Create hooks/example.mjs to implement the behavior for this work item.
RED test: add a failing test first, then make it pass.
Covers {ac_id}.
Verify: python3 -m pytest tests/test_example.py
"""


def _write_flat_artifact(cwd, role, work_id, ac_id="AC1"):
    """Write a VALID flat spec/plan to disk; return its repo-relative path."""
    sub = "specs" if role == "spec" else "plans"
    d = Path(cwd) / "docs" / "agentic-sdlc" / sub
    d.mkdir(parents=True, exist_ok=True)
    body = (_VALID_SPEC if role == "spec" else _VALID_PLAN).format(work_id=work_id, ac_id=ac_id)
    (d / f"{work_id}.md").write_text(body, encoding="utf-8")
    return f"docs/agentic-sdlc/{sub}/{work_id}.md"


def _write_pp_artifact(cwd, slug, role, work_id, ac_id="AC1"):
    """Write a VALID per-package <slug>/<role>/<work_id>.md to disk; return its repo-relative path."""
    d = Path(cwd) / "docs" / "agentic-sdlc" / slug / role
    d.mkdir(parents=True, exist_ok=True)
    body = (_VALID_SPEC if role == "spec" else _VALID_PLAN).format(work_id=work_id, ac_id=ac_id)
    (d / f"{work_id}.md").write_text(body, encoding="utf-8")
    return f"docs/agentic-sdlc/{slug}/{role}/{work_id}.md"


def _block_ids(out):
    """Extract the bracketed missing-step id list from a flow-step-guard block reason (or [])."""
    reason = out.get("reason", "")
    if "[" in reason and "]" in reason:
        return reason[reason.index("[") + 1:reason.index("]")].split(", ")
    return []


# A transcript where every block/warn step of root-cause-fix is satisfied by a real
# tool_use or command (no files needed): spec+plan via the workflow, tests via a real
# command, security + control via real agent dispatches.
SATISFIED = [
    skill(RCF),
    edit("src/app.py"),
    workflow("agentic-sdlc:spec-plan-draft"),
    bash("py -3 -m unittest tests.test_app"),
    agent("agentic-sdlc:security-reviewer"),
    agent("agentic-sdlc:implementation-auditor"),
    ev_text("Done."),
]


@unittest.skipIf(NODE is None, "node not available")
class TestFlowStepGuard(unittest.TestCase):
    def run_guard(self, events, *, block=False, stop_active=False, cwd=None):
        with tempfile.TemporaryDirectory() as td:
            run_cwd = cwd or td
            tpath = Path(td) / "transcript.jsonl"
            tpath.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
            env = os.environ.copy()
            if block:
                env["AGENTIC_FLOW_GATE_BLOCK"] = "true"
            proc = subprocess.run(
                [NODE, str(STEP_GUARD)],
                input=json.dumps({"transcript_path": str(tpath), "stop_hook_active": stop_active}),
                capture_output=True, text=True, encoding="utf-8", cwd=run_cwd, env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = (proc.stdout or "").strip()
            return json.loads(out) if out else {}

    def test_blocks_missing_spec_when_flag_set(self):  # AC1
        out = self.run_guard([skill(RCF), edit("src/app.py"), ev_text("Fixed.")], block=True)
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("spec", out.get("reason", "").lower())

    def test_warns_not_blocks_without_flag(self):  # AC2
        out = self.run_guard([skill(RCF), edit("src/app.py"), ev_text("Fixed.")], block=False)
        self.assertIn("systemMessage", out)
        self.assertNotEqual(out.get("decision"), "block")

    def test_stub_spec_is_rederived_as_unsatisfied(self):  # AC3
        with tempfile.TemporaryDirectory() as cwd:
            _write_stub_spec(cwd)
            out = self.run_guard([skill(RCF), edit("src/app.py")], block=True, cwd=cwd)
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("spec", out.get("reason", "").lower())

    def test_all_evidence_present_is_silent(self):  # AC4 (tool_use evidence counts)
        out = self.run_guard(SATISFIED, block=True)
        self.assertEqual(out, {})

    def test_diagnose_only_no_source_edit_is_silent(self):  # regression: report-only run, no false positive
        # root-cause-fix invoked for investigation only ("no changes, just a report").
        # No production source file edited -> no implementation obligations to enforce.
        events = [skill(RCF), bash("git commit --dry-run"),
                  ev_text("Root cause report: wiring is intact.")]
        self.assertEqual(self.run_guard(events, block=True), {})

    def test_no_flow_heuristic_warns_never_blocks(self):  # AC6
        events = [edit("src/app.py"), edit("src/two.py"), ev_text("All tests passing, feature complete.")]
        out = self.run_guard(events, block=True)
        self.assertIn("systemMessage", out)
        self.assertNotEqual(out.get("decision"), "block")

    def test_silent_when_stop_hook_active(self):  # AC7
        out = self.run_guard([skill(RCF), edit("src/app.py")], block=True, stop_active=True)
        self.assertEqual(out, {})

    def test_prose_marker_does_not_satisfy_a_step(self):  # re-derivation: prose is not evidence
        # Everything satisfied by real events EXCEPT control, which is only CLAIMED in prose text.
        events = [
            skill(RCF),
            workflow("agentic-sdlc:spec-plan-draft"),
            bash("py -3 -m unittest tests.test_app"),
            agent("agentic-sdlc:security-reviewer"),
            ev_text("I ran implementasyon-control and the implementation-auditor agent; all good."),
            edit("src/app.py"),
        ]
        out = self.run_guard(events, block=True)
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("control", out.get("reason", "").lower())

    def test_feature_build_blocks_missing_spec(self):
        out = self.run_guard([skill(FB), edit("src/app.py"), ev_text("Built.")], block=True)
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("spec", out.get("reason", "").lower())

    def test_feature_build_satisfied_is_silent(self):
        events = [
            skill(FB), edit("src/app.py"), workflow("agentic-sdlc:spec-plan-draft"),
            bash("py -3 -m unittest tests.test_app"),
            agent("agentic-sdlc:security-reviewer"),
            agent("agentic-sdlc:implementation-auditor"), ev_text("Done."),
        ]
        self.assertEqual(self.run_guard(events, block=True), {})

    def test_safe_refactor_blocks_missing_characterization(self):
        out = self.run_guard([skill(SR), edit("src/app.py"), ev_text("Refactored.")], block=True)
        self.assertEqual(out.get("decision"), "block")
        self.assertTrue(any(k in out.get("reason", "").lower() for k in ("character", "test", "control")))

    def test_safe_refactor_satisfied_is_silent(self):
        events = [
            skill(SR), bash("py -3 -m unittest tests.test_characterization"),
            edit("src/app.py"),
            agent("agentic-sdlc:implementation-auditor"), ev_text("Done."),
        ]
        self.assertEqual(self.run_guard(events, block=True), {})

    def test_pipeline_blocks_missing_delegation_and_spec(self):
        out = self.run_guard([skill(PIPE), edit("src/app.py"), ev_text("Shipped.")], block=True)
        self.assertEqual(out.get("decision"), "block")
        self.assertTrue(any(k in out.get("reason", "").lower() for k in ("dispatch", "spec")))

    def test_pipeline_satisfied_is_silent(self):
        events = [
            skill(PIPE),
            skill("agentic-sdlc:dispatch-strategy"),
            workflow("agentic-sdlc:spec-plan-draft"),
            skill("agentic-sdlc:feature-build"),  # core handoff
            edit("src/app.py"),
            bash("py -3 -m unittest tests.test_app"),
            skill("agentic-sdlc:security-audit"),
            skill("agentic-sdlc:implementasyon-control"),
            ev_text("Done."),
        ]
        self.assertEqual(self.run_guard(events, block=True), {})

    # ---- per-package layout (work-package-artifact-resolution: AC11/AC12/AC14/AC15/BR10) ----
    # These all run an active flow (root-cause-fix) plus a real source edit so the Stop
    # obligations bite, then satisfy tests + control so the PLAN step is the only variable.
    def _pp_satisfied_tail(self):
        return [
            edit("src/app.py"),
            bash("py -3 -m unittest tests.test_app"),
            agent("agentic-sdlc:security-reviewer"),
            agent("agentic-sdlc:implementation-auditor"),
            ev_text("Done."),
        ]

    def test_per_package_spec_plan_recognized_claude(self):  # AC15 (Stop listing + re-validation)
        with tempfile.TemporaryDirectory() as cwd:
            _write_pp_artifact(cwd, "work-x", "spec", "work-x", ac_id="AC1")
            _write_pp_artifact(cwd, "work-x", "plan", "work-x", ac_id="AC1")
            out = self.run_guard([skill(RCF)] + self._pp_satisfied_tail(), block=True, cwd=cwd)
        self.assertEqual(out, {})  # per-package spec+plan listed AND re-validated -> all satisfied

    def test_per_package_plan_paired_with_colocated_spec_on_stop_claude(self):  # BR10 (co-located pairing)
        # A per-package plan is the SOLE plan; a FOREIGN flat spec (different AC) sorts first as
        # listArtifacts('spec')[0]. Pairing the plan with that foreign spec fails AC-coverage
        # (validate_artifacts has no work_id check - RC2), so without the co-located specForPlan fix
        # the plan step is FALSELY reported missing. With the fix it pairs with its own-package spec.
        with tempfile.TemporaryDirectory() as cwd:
            _write_pp_artifact(cwd, "work-x", "spec", "work-x", ac_id="AC2")
            _write_pp_artifact(cwd, "work-x", "plan", "work-x", ac_id="AC2")
            _write_flat_artifact(cwd, "spec", "flat-other", ac_id="AC1")  # foreign spec, sorts first
            out = self.run_guard([skill(RCF)] + self._pp_satisfied_tail(), block=True, cwd=cwd)
        self.assertNotIn("plan", _block_ids(out))  # plan satisfied against its OWN-package spec

    def test_per_package_plan_without_colocated_spec_unsatisfied_claude(self):  # BR10 negative
        # A per-package plan with NO co-located spec must stay unsatisfied - it must NOT be falsely
        # paired with the unrelated flat spec that happens to exist on disk.
        with tempfile.TemporaryDirectory() as cwd:
            _write_pp_artifact(cwd, "work-x", "plan", "work-x", ac_id="AC2")
            _write_flat_artifact(cwd, "spec", "flat-other", ac_id="AC1")  # exists, but not co-located
            out = self.run_guard([skill(RCF)] + self._pp_satisfied_tail(), block=True, cwd=cwd)
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("plan", _block_ids(out))  # no false pairing -> plan correctly missing

    def test_per_package_reserved_slug_not_recognized_claude(self):  # AC14/BR11
        # slug 'spec' is reserved -> docs/agentic-sdlc/spec/spec/x.md is NOT a per-package spec.
        with tempfile.TemporaryDirectory() as cwd:
            d = Path(cwd) / "docs" / "agentic-sdlc" / "spec" / "spec"
            d.mkdir(parents=True, exist_ok=True)
            (d / "x.md").write_text(_VALID_SPEC.format(work_id="x", ac_id="AC1"), encoding="utf-8")
            out = self.run_guard([skill(RCF), edit("src/app.py"), ev_text("x")], block=True, cwd=cwd)
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("spec", _block_ids(out))  # reserved slug never counts as a spec artifact

    def test_per_package_evidence_not_recognized_claude(self):  # AC12
        # A per-package EVIDENCE file is never a spec/plan satisfier nor listed as one.
        with tempfile.TemporaryDirectory() as cwd:
            d = Path(cwd) / "docs" / "agentic-sdlc" / "work-x" / "evidence"
            d.mkdir(parents=True, exist_ok=True)
            (d / "work-x.md").write_text(_VALID_SPEC.format(work_id="work-x", ac_id="AC1"), encoding="utf-8")
            out = self.run_guard([skill(RCF), edit("src/app.py"), ev_text("x")], block=True, cwd=cwd)
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("spec", _block_ids(out))  # evidence subdir -> perPackageRole null -> not a spec

    def test_missing_per_package_still_blocks(self):  # guard still bites with no artifacts at all
        with tempfile.TemporaryDirectory() as cwd:
            out = self.run_guard([skill(RCF), edit("src/app.py"), ev_text("x")], block=True, cwd=cwd)
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("spec", _block_ids(out))


@unittest.skipIf(NODE is None, "node not available")
class TestFlowOrderGuard(unittest.TestCase):
    def run_guard(self, file_path, events, *, block=False, cwd=None):
        with tempfile.TemporaryDirectory() as td:
            run_cwd = cwd or td
            tpath = Path(td) / "transcript.jsonl"
            tpath.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
            env = os.environ.copy()
            if block:
                env["AGENTIC_FLOW_GATE_BLOCK"] = "true"
            proc = subprocess.run(
                [NODE, str(ORDER_GUARD)],
                input=json.dumps({"tool_input": {"file_path": file_path}, "transcript_path": str(tpath)}),
                capture_output=True, text=True, encoding="utf-8", cwd=run_cwd, env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = (proc.stdout or "").strip()
            return json.loads(out) if out else {}

    def test_denies_source_edit_without_spec(self):  # AC5
        out = self.run_guard("src/app.py", [skill(RCF)], block=True)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_allows_editing_the_spec_file(self):  # AC5
        out = self.run_guard("docs/agentic-sdlc/specs/x.md", [skill(RCF)], block=True)
        self.assertEqual(out, {})

    def test_allows_editing_a_test_file(self):  # AC5 boundary
        out = self.run_guard("tests/test_app.py", [skill(RCF)], block=True)
        self.assertEqual(out, {})

    def test_allows_when_no_active_flow(self):
        out = self.run_guard("src/app.py", [ev_text("just editing")], block=True)
        self.assertEqual(out, {})

    def test_denies_when_only_preexisting_spec_not_written_this_turn(self):  # session-scoped ordering
        # cwd = the real repo (which already holds spec/plan files), but NO spec/plan was written or
        # drafted in THIS transcript -> a pre-existing artifact must NOT satisfy the order gate.
        out = self.run_guard("src/app.py", [skill(RCF)], block=True, cwd=str(REPO))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_allows_source_edit_after_spec_plan_drafted_this_turn(self):
        out = self.run_guard("src/app.py", [skill(RCF), workflow("agentic-sdlc:spec-plan-draft")], block=True)
        self.assertEqual(out, {})

    def test_safe_refactor_denies_source_edit_before_characterization(self):
        out = self.run_guard("src/app.py", [skill(SR)], block=True)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_safe_refactor_allows_source_edit_after_characterization(self):
        events = [skill(SR), bash("py -3 -m unittest tests.test_characterization")]
        out = self.run_guard("src/app.py", events, block=True)
        self.assertEqual(out, {})

    def test_pipeline_denies_source_edit_before_delegation(self):
        out = self.run_guard("src/app.py", [skill(PIPE)], block=True)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    # ---- per-package session-scoped (PreToolUse) recognition (AC12/AC14/AC15) ----
    def test_allows_source_edit_after_per_package_spec_plan_drafted_claude(self):  # AC15
        events = [skill(RCF),
                  edit("docs/agentic-sdlc/work-x/spec/work-x.md"),
                  edit("docs/agentic-sdlc/work-x/plan/work-x.md")]
        out = self.run_guard("src/app.py", events, block=True)
        self.assertEqual(out, {})  # per-package spec+plan written this turn satisfy the order gate

    def test_per_package_evidence_edit_does_not_satisfy_order_claude(self):  # AC12
        events = [skill(RCF), edit("docs/agentic-sdlc/work-x/evidence/work-x.md")]
        out = self.run_guard("src/app.py", events, block=True)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")  # evidence is no satisfier

    def test_per_package_reserved_slug_edit_does_not_satisfy_order_claude(self):  # AC14/BR11
        events = [skill(RCF),
                  edit("docs/agentic-sdlc/spec/spec/x.md"),
                  edit("docs/agentic-sdlc/plan/plan/x.md")]  # reserved slugs -> not recognized
        out = self.run_guard("src/app.py", events, block=True)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()
