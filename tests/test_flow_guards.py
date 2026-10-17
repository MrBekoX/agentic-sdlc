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
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
STEP_GUARD = REPO / "hooks" / "flow-step-guard.mjs"
ORDER_GUARD = REPO / "hooks" / "flow-order-guard.mjs"
CLAIM_GUARD = REPO / "hooks" / "completion-claim-guard.mjs"
FLOW_EVID = REPO / "hooks" / "flow-evidence.mjs"
GIT = shutil.which("git")
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


def powershell(c):
    return ev_tool("PowerShell", {"command": c})


def edit(fp):
    return ev_tool("Edit", {"file_path": fp})


def tool_with_id(name, inp, tool_id):
    """A native Claude 2.1.x assistant tool_use that carries its id."""
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tool_id, "name": name, "input": inp}]}}


def tool_result(tool_id, is_error, include_flag=True):
    """The native Claude 2.1.x user record carrying a tool_result for tool_id."""
    item = {"type": "tool_result", "tool_use_id": tool_id, "content": "done"}
    if include_flag:
        item["is_error"] = is_error
    return {"type": "user", "message": {"content": [item]}}


def with_results(events):
    """Give every tool_use an id and follow it with a correlated non-error tool_result, the way a real
    Claude transcript records a completed call."""
    out = []
    for n, event in enumerate(events):
        content = event.get("message", {}).get("content")
        if event.get("type") == "assistant" and isinstance(content, list) and content and content[0].get("type") == "tool_use":
            tool_id = f"toolu_{n:03d}"
            out.append(tool_with_id(content[0]["name"], content[0]["input"], tool_id))
            out.append(tool_result(tool_id, False))
        else:
            out.append(event)
    return out


def _write_stub_spec(cwd):
    specs = Path(cwd) / "docs" / "agentic-sdlc" / "specs"
    specs.mkdir(parents=True, exist_ok=True)
    # A stub: passes "file exists" but fails validate_artifacts --strict (no sections).
    (specs / "stub.md").write_text("---\nwork_id: stub\nstatus: draft\n---\n\n# Stub\n\nspec\n", encoding="utf-8")


# ---- per-package artifact bodies (deep enough to pass validate_artifacts.py --strict) ----
_VALID_SPEC = """---
work_id: {work_id}
status: draft
---

# Spec {work_id}

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

_VALID_PLAN = """---
work_id: {work_id}
spec: ../specs/{work_id}.md
branch: feat/{work_id}
status: draft
---

# Plan {work_id}

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


BR6_TABLE = REPO / "tests" / "fixtures" / "transcripts" / "br6-attribution-cases.json"

# Exact flow-step-guard block stdout, for AC33, AC34 and AC40. The step list is the 5801cb9 engine's;
# the reason text is the flow-neutral C6 sentence (pipeline v2.1 D7), which replaced the old
# "invoke implementation-control" wording when the hooks/flow-step-guard.mjs byte lock was released.
# These pins are that file's behavioural lock now - see the release comment in the lock suites.
FLOW_STEP_BLOCK_TAIL = (
    "have no evidence this turn. Produce them before finishing - for example write and validate the "
    "spec/plan, run the tests, and run the required reviewer or audit step. Evidence is re-derived, not "
    "taken from text."
)
PINNED_STEP_BLOCK_MAIN = (
    '{"decision":"block","reason":"root-cause-fix: required step(s) [spec, plan, tests, control] have no '
    'evidence this turn. Produce them before finishing - for example write and validate the spec/plan, run '
    'the tests, and run the required reviewer or audit step. Evidence is re-derived, not taken from text.",'
    '"systemMessage":"flow-step-guard: blocked - required flow steps lack evidence."}'
)
# C14: the flow-step-guard.mjs branches the C6 edit does NOT change stay byte-identical to 4262a19.
# Each literal below was captured by running the unmodified hooks/flow-step-guard.mjs at 4262a19
# (2026-10-16) over the event set named in its test, then pasted here - the expected value is fixed,
# not recomputed. With the digest lock released, these pins are what notices a drift in those branches.
PINNED_STEP_WARN_RCF = (
    '{"systemMessage":"flow-step-guard: missing evidence for step(s): spec, plan, tests, security, control"}'
)
PINNED_STEP_WARN_ONLY_UNDER_BLOCK_FLAG = (
    '{"systemMessage":"flow-step-guard: missing evidence for step(s): security, review-result"}'
)
PINNED_STEP_NO_FLOW_HEURISTIC = (
    '{"systemMessage":"flow-step-guard: implementation edits and a completion claim, but no flow skill was '
    'invoked - did you skip root-cause-fix?"}'
)
PINNED_ORDER_BLOCK_MAIN = (
    '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":'
    '"root-cause-fix: produce spec and plan before editing source (missing: spec, plan). Externalize them as '
    'validated artifacts first."},"systemMessage":"flow-order-guard: spec/plan required before source edits."}'
)
# The pipeline block pin (C6): every pipeline step satisfied except `control`, which only the
# implementation-auditor agent clears now.
PINNED_PIPE_CONTROL_BLOCK = (
    '{"decision":"block","reason":"agentic-sdlc-pipeline: required step(s) [control] have no evidence this '
    'turn. Produce them before finishing - for example write and validate the spec/plan, run the tests, and '
    'run the required reviewer or audit step. Evidence is re-derived, not taken from text.","systemMessage":'
    '"flow-step-guard: blocked - required flow steps lack evidence."}'
)
DS = "agentic-sdlc:dispatch-strategy"
# The O4 dispatch-terminal Stop message (C6), verbatim.
DISPATCH_TERMINAL_MESSAGE = ("agentic-sdlc-pipeline: the turn ended on the dispatch-strategy decision. "
                             "Continue with the pipeline's next step in the same turn.")
# The pipeline's flow-order deny reason for a missing red-first. The sentence is the locked
# flow-order-guard.mjs text ("produce spec and plan..."), which D7 accepts as a limitation; the
# part that carries the C6 behaviour is "(missing: red-first)".
PIPE_RED_FIRST_DENY_REASON = ("agentic-sdlc-pipeline: produce spec and plan before editing source (missing: "
                              "red-first). Externalize them as validated artifacts first.")
BRANCH_GIT_ARGV = {
    "symbolicRef": ["-c", "core.fsmonitor=false", "-c", "core.hooksPath=", "--no-pager",
                    "symbolic-ref", "--quiet", "--short", "HEAD"],
    "verifyHead": ["-c", "core.fsmonitor=false", "-c", "core.hooksPath=", "--no-pager",
                   "rev-parse", "--verify", "--quiet", "HEAD"],
}


def _reminder_ids(out):
    """Step ids named by a flow-step-guard reminder ('missing evidence for step(s): a, b'), or []."""
    message = out.get("systemMessage", "")
    marker = "missing evidence for step(s): "
    if marker not in message:
        return []
    return message.split(marker, 1)[1].split(", ")


def _block_ids(out):
    """Extract the bracketed missing-step id list from a flow-step-guard block reason (or [])."""
    reason = out.get("reason", "")
    if "[" in reason and "]" in reason:
        return reason[reason.index("[") + 1:reason.index("]")].split(", ")
    return []


# A transcript where every block/warn step of root-cause-fix is satisfied by a real
# tool_use or command (no files needed): spec+plan via the workflow, tests via a real
# command, security + control via real agent dispatches.
# Each call carries its correlated non-error tool_result, as a real transcript does (review-result step).
SATISFIED = with_results([
    skill(RCF),
    edit("src/app.py"),
    workflow("agentic-sdlc:spec-plan-draft"),
    bash("py -3 -m unittest tests.test_app"),
    agent("agentic-sdlc:security-reviewer"),
    agent("agentic-sdlc:implementation-auditor"),
    ev_text("Done."),
])


def _run_step_guard_raw(test, events, *, block=False, stop_active=False, cwd=None, env_extra=None,
                       last_assistant_message=None, background_tasks=None):
    """Run flow-step-guard.mjs over `events` and return its raw stdout (exit code asserted 0)."""
    with tempfile.TemporaryDirectory() as td:
        run_cwd = cwd or td
        tpath = Path(td) / "transcript.jsonl"
        tpath.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
        env = os.environ.copy()
        env.pop("AGENTIC_FLOW_STRICT_EVIDENCE", None)
        env.pop("AGENTIC_FLOW_GATE_BLOCK", None)  # the warn path must not inherit an ambient flag
        # A temp cwd must never resolve an enclosing repository's branch (the branch step).
        env["GIT_CEILING_DIRECTORIES"] = str(Path(run_cwd).resolve().parent)
        if block:
            env["AGENTIC_FLOW_GATE_BLOCK"] = "true"
        if env_extra:
            env.update(env_extra)
        payload = {"transcript_path": str(tpath), "stop_hook_active": stop_active}
        if last_assistant_message is not None:
            payload["last_assistant_message"] = last_assistant_message
        if background_tasks is not None:
            payload["background_tasks"] = background_tasks
        proc = subprocess.run(
            [NODE, str(STEP_GUARD)],
            input=json.dumps(payload),
            capture_output=True, text=True, encoding="utf-8", cwd=run_cwd, env=env,
        )
        test.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout or ""


@unittest.skipIf(NODE is None, "node not available")
class TestFlowStepGuard(unittest.TestCase):
    def run_guard(self, events, **kw):
        out = _run_step_guard_raw(self, events, **kw).strip()
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
            ev_text("I ran implementation-control and the implementation-auditor agent; all good."),
            edit("src/app.py"),
        ]
        out = self.run_guard(events, block=True)
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("control", out.get("reason", "").lower())

    def test_echoed_test_command_does_not_satisfy_tests_claude(self):  # A2 Claude SHAPE gate (command text only)
        # `echo pytest` matches the testCommand regex as TEXT but is not a real runner invocation; the A2
        # shape gate closes it on Claude too. (Claude exit/output substrate is unverified, so only the
        # command-text SHAPE is enforced here — the Codex engine additionally checks exit0.)
        events = [
            skill(RCF), edit("src/app.py"), workflow("agentic-sdlc:spec-plan-draft"),
            bash("echo pytest"),  # forged: prints the word, runs nothing
            agent("agentic-sdlc:security-reviewer"),
            agent("agentic-sdlc:implementation-auditor"), ev_text("Done."),
        ]
        out = self.run_guard(events, block=True)
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("tests", _block_ids(out))

    def test_real_runner_still_satisfies_tests_claude(self):  # A2: a genuine runner invocation still counts
        events = with_results([
            skill(RCF), edit("src/app.py"), workflow("agentic-sdlc:spec-plan-draft"),
            bash("python -m pytest -q"),
            agent("agentic-sdlc:security-reviewer"),
            agent("agentic-sdlc:implementation-auditor"), ev_text("Done."),
        ])
        self.assertEqual(self.run_guard(events, block=True), {})

    # ---- C14: exact-stdout pins for the unchanged branches (released digest lock) ----
    def test_warn_reminder_stdout_pinned(self):  # C14: byte-identical to 4262a19
        out = _run_step_guard_raw(self, [skill(RCF), edit("src/app.py"), ev_text("Fixed.")])
        self.assertEqual(out, PINNED_STEP_WARN_RCF)

    def test_warn_only_steps_under_block_flag_stdout_pinned(self):  # C14: warn steps never block
        events = [skill(RCF), edit("src/app.py"), workflow("agentic-sdlc:spec-plan-draft"),
                  bash("python -m pytest -q"), agent("agentic-sdlc:implementation-auditor"), ev_text("Done.")]
        self.assertEqual(_run_step_guard_raw(self, events, block=True), PINNED_STEP_WARN_ONLY_UNDER_BLOCK_FLAG)

    def test_no_flow_heuristic_stdout_pinned(self):  # C14: the line-78 heuristic text, flag on or off
        events = [edit("src/app.py"), edit("src/two.py"), ev_text("All tests passing, feature complete.")]
        for block in (False, True):
            with self.subTest(block=block):
                self.assertEqual(_run_step_guard_raw(self, events, block=block), PINNED_STEP_NO_FLOW_HEURISTIC)

    # ---- C14: `contains` items keep substring matching (unchanged behaviour, green before and after C6) ----
    def test_contains_items_still_match_by_substring(self):  # C14
        # One general-purpose agent whose prompt names both reviewers satisfies the substring
        # security and control steps of the focused flows - exact matching is pipeline-only.
        reviewer = ev_tool("Agent", {"subagent_type": "general-purpose",
                                     "prompt": "Act as security-reviewer, then as implementation-auditor."})
        for flow in (RCF, FB):
            with self.subTest(flow=flow):
                events = with_results([skill(flow), edit("src/app.py"), workflow("agentic-sdlc:spec-plan-draft"),
                                       bash("python -m pytest -q"), reviewer, ev_text("Done.")])
                self.assertEqual(self.run_guard(events, block=True), {})

    def test_feature_build_blocks_missing_spec(self):
        out = self.run_guard([skill(FB), edit("src/app.py"), ev_text("Built.")], block=True)
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("spec", out.get("reason", "").lower())

    def test_feature_build_satisfied_is_silent(self):
        events = with_results([
            skill(FB), edit("src/app.py"), workflow("agentic-sdlc:spec-plan-draft"),
            bash("py -3 -m unittest tests.test_app"),
            agent("agentic-sdlc:security-reviewer"),
            agent("agentic-sdlc:implementation-auditor"), ev_text("Done."),
        ])
        self.assertEqual(self.run_guard(events, block=True), {})

    def test_safe_refactor_blocks_missing_characterization(self):
        out = self.run_guard([skill(SR), edit("src/app.py"), ev_text("Refactored.")], block=True)
        self.assertEqual(out.get("decision"), "block")
        self.assertTrue(any(k in out.get("reason", "").lower() for k in ("character", "test", "control")))

    def test_safe_refactor_satisfied_is_silent(self):
        events = with_results([
            skill(SR), bash("py -3 -m unittest tests.test_characterization"),
            edit("src/app.py"),
            agent("agentic-sdlc:implementation-auditor"), ev_text("Done."),
        ])
        self.assertEqual(self.run_guard(events, block=True), {})

    def test_pipeline_blocks_missing_dispatch_and_spec(self):  # C6: no `core` step; red-first has no stop
        out = self.run_guard([skill(PIPE), edit("src/app.py"), ev_text("Shipped.")], block=True)
        self.assertEqual(out.get("decision"), "block")
        self.assertEqual(_block_ids(out), ["dispatch", "spec", "plan", "tests", "security", "control"])
        self.assertTrue(out.get("reason", "").endswith(FLOW_STEP_BLOCK_TAIL), out.get("reason"))

    def test_pipeline_satisfied_is_silent(self):  # C6: Agent reviewers, no focused Skill call
        events = with_results([
            skill(PIPE),
            skill(DS),
            workflow("agentic-sdlc:spec-plan-draft"),
            bash("py -3 -m unittest tests.test_app"),  # RED run before the first production edit
            edit("src/app.py"),
            bash("py -3 -m unittest tests.test_app"),
            agent("agentic-sdlc:security-reviewer"),
            agent("agentic-sdlc:implementation-auditor"),
            ev_text("Done."),
        ])
        self.assertEqual(self.run_guard(events, block=True), {})

    def test_pipeline_focused_skill_calls_do_not_satisfy_reviewer_steps(self):  # C6: Agent-only security/control
        # The old satisfiers - a Skill call to security-audit / implementation-control - no longer count
        # inside the pipeline: the pipeline dispatches the agents directly (D5).
        events = with_results([
            skill(PIPE), skill(DS), workflow("agentic-sdlc:spec-plan-draft"),
            bash("py -3 -m unittest tests.test_app"), edit("src/app.py"),
            skill("agentic-sdlc:security-audit"), skill("agentic-sdlc:implementation-control"),
            ev_text("Done."),
        ])
        out = self.run_guard(events, block=True)
        self.assertEqual(out.get("decision"), "block")
        self.assertEqual(_block_ids(out), ["security", "control"])

    # ---- per-package layout (work-package-artifact-resolution: AC11/AC12/AC14/AC15/BR10) ----
    # These all run an active flow (root-cause-fix) plus a real source edit so the Stop
    # obligations bite, then satisfy tests + control so the PLAN step is the only variable.
    def _pp_satisfied_tail(self):
        return with_results([
            edit("src/app.py"),
            bash("py -3 -m unittest tests.test_app"),
            agent("agentic-sdlc:security-reviewer"),
            agent("agentic-sdlc:implementation-auditor"),
            ev_text("Done."),
        ])

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

    # ---- AC130: the Codex-only BR6 closure leaves the live Claude Stop tests outcome unchanged ----
    def test_trailing_shapes_claude_stop_tests_outcome_unchanged(self):  # AC130
        rows = [r for r in json.loads(BR6_TABLE.read_text(encoding="utf-8"))["rows"] if "AC130" in r["specRefs"]]
        self.assertTrue(rows)
        for row in rows:
            with self.subTest(id=row["id"]):
                events = [skill(RCF), edit("src/app.py"), workflow("agentic-sdlc:spec-plan-draft"),
                          bash(row["command"]), agent("agentic-sdlc:security-reviewer"),
                          agent("agentic-sdlc:implementation-auditor"), ev_text("Done.")]
                listed = "tests" in _reminder_ids(self.run_guard(events))
                self.assertEqual(not listed, row["baseline5801cb9"]["claudeStopTests"] == "satisfied")

    # ---- AC42: AGENTIC_FLOW_STRICT_EVIDENCE is Codex-only; Claude output is identical under it ----
    def test_strict_flag_does_not_change_claude_tests_outcome(self):  # AC42
        # Shapes the Codex strict path rejects (version-only, pipeline, trailing echo) plus a missing run.
        for command in ("pytest --version", "pytest | tee log.txt", "pytest; echo EXIT=$?", "echo pytest"):
            events = [skill(RCF), edit("src/app.py"), workflow("agentic-sdlc:spec-plan-draft"), bash(command),
                      agent("agentic-sdlc:security-reviewer"), agent("agentic-sdlc:implementation-auditor"),
                      ev_text("Done.")]
            for block in (False, True):
                with self.subTest(command=command, block=block):
                    strict = self.run_guard(events, block=block, env_extra={"AGENTIC_FLOW_STRICT_EVIDENCE": "true"})
                    self.assertEqual(strict, self.run_guard(events, block=block))


def _git(repo, *args):
    subprocess.run([GIT, *args], cwd=repo, check=True, capture_output=True)


def _satisfied_events(flow):
    """Every existing step of `flow` satisfied by real tool_use evidence with correlated non-error results."""
    implement = [workflow("agentic-sdlc:spec-plan-draft"), bash("py -3 -m unittest tests.test_app"),
                 agent("agentic-sdlc:security-reviewer"), agent("agentic-sdlc:implementation-auditor")]
    tails = {
        RCF: implement,
        FB: implement,
        SR: [bash("py -3 -m unittest tests.test_characterization"), agent("agentic-sdlc:implementation-auditor")],
        # C6: the pipeline invokes no focused skill; its reviewers are the two agents.
        PIPE: [skill(DS), workflow("agentic-sdlc:spec-plan-draft"), bash("py -3 -m unittest tests.test_app"),
               agent("agentic-sdlc:security-reviewer"), agent("agentic-sdlc:implementation-auditor")],
    }
    return with_results([skill(flow), edit("src/app.py"), *tails[flow], ev_text("Done.")])


# ---- AC32-AC36: warn-level branch step (Task 19) ------------------------------
@unittest.skipIf(NODE is None or GIT is None, "node or git not available")
class TestBranchStep(unittest.TestCase):
    FLOWS = (RCF, FB, SR, PIPE)

    def _root(self):
        root = Path(tempfile.mkdtemp(prefix="flow-branch-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return root

    def make_repo(self, branch="main", commit=True, detached=False):
        repo = self._root() / "repo"
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        if commit:
            _git(repo, "-c", "user.email=slice-b@invalid", "-c", "user.name=slice-b",
                 "commit", "--allow-empty", "-m", "init")
            if branch != "main":
                _git(repo, "checkout", "-b", branch)
            if detached:
                _git(repo, "checkout", "--detach")
        return repo

    def run_hook(self, script, stdin, cwd, *, block=False):
        env = os.environ.copy()
        for name in ("AGENTIC_FLOW_GATE_BLOCK", "AGENTIC_FLOW_STRICT_EVIDENCE"):
            env.pop(name, None)
        env["GIT_CEILING_DIRECTORIES"] = str(Path(cwd).resolve().parent)
        if block:
            env["AGENTIC_FLOW_GATE_BLOCK"] = "true"
        proc = subprocess.run([NODE, str(script)], input=json.dumps(stdin), capture_output=True,
                              text=True, encoding="utf-8", cwd=cwd, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def _transcript(self, events):
        tpath = self._root() / "transcript.jsonl"
        tpath.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
        return str(tpath)

    def stop_raw(self, events, cwd, *, block=False):
        return self.run_hook(STEP_GUARD, {"transcript_path": self._transcript(events)}, cwd, block=block)

    def stop(self, events, cwd, *, block=False):
        raw = self.stop_raw(events, cwd, block=block).strip()
        return json.loads(raw) if raw else {}

    # ---- RED ----
    def test_protected_branch_source_edit_lists_branch_once_per_flow(self):  # AC32
        for branch in ("main", "master"):
            repo = self.make_repo(branch)
            for flow in self.FLOWS:
                with self.subTest(branch=branch, flow=flow):
                    raw = self.stop_raw(_satisfied_events(flow), repo)
                    self.assertEqual(_reminder_ids(json.loads(raw) if raw.strip() else {}), ["branch"])
                    self.assertNotIn(branch, raw)  # no branch name outside the fixed step text

    def test_two_active_flows_branch_listed_per_flow(self):  # AC32
        # Two genuinely separate standalone activations in one session (root-cause-fix, then
        # feature-build). The pipeline no longer invokes a focused skill (C6/D1), so it is not used
        # to stand up the second flow.
        events = with_results([skill(RCF), skill(FB), edit("src/app.py"),
                               workflow("agentic-sdlc:spec-plan-draft"), bash("py -3 -m unittest tests.test_app"),
                               agent("agentic-sdlc:security-reviewer"), agent("agentic-sdlc:implementation-auditor"),
                               ev_text("Done.")])
        self.assertEqual(_reminder_ids(self.stop(events, self.make_repo("main"))), ["branch", "branch"])

    def test_branch_git_argv_pinned(self):  # S10 static half
        script = ("const m = await import(%s);"
                  "process.stdout.write(JSON.stringify({argv: m.BRANCH_GIT_ARGV ?? null,"
                  " frozen: Object.isFrozen(m.BRANCH_GIT_ARGV) && m.BRANCH_GIT_ARGV !== undefined}));"
                  % json.dumps(FLOW_EVID.as_uri()))
        proc = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        got = json.loads(proc.stdout)
        self.assertEqual(got["argv"], BRANCH_GIT_ARGV)
        self.assertTrue(got["frozen"])
        source = FLOW_EVID.read_text(encoding="utf-8")
        start = source.index("export function resolveBranchState")
        end = source.find("\nexport ", start + 1)
        self.assertNotIn("shell", source[start:end if end != -1 else len(source)])

    @unittest.skipIf(sys.platform == "win32", "libuv PATH lookup does not execute non-.exe stubs")
    def test_resolver_invokes_git_with_fixed_hardened_argv(self):  # S10 discriminating half
        repo = self.make_repo("main")
        root = self._root()
        log, sentinel = root / "argv.log", root / "sentinel"
        writer = root / "write-sentinel.sh"
        writer.write_text(f"#!/bin/sh\ntouch '{sentinel}'\n", encoding="utf-8")
        writer.chmod(0o755)
        _git(repo, "config", "core.fsmonitor", str(writer))
        _git(repo, "config", "core.pager", f"{writer}; cat")
        bin_dir = root / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "git"
        stub.write_text("#!/bin/sh\n"
                        f"for a in \"$@\"; do printf '%s\\t' \"$a\"; done >> '{log}'\n"
                        f"printf '\\n' >> '{log}'\n"
                        f"exec '{GIT}' \"$@\"\n", encoding="utf-8")
        stub.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
        env["GIT_CEILING_DIRECTORIES"] = str(repo.parent)
        script = ("const m = await import(%s); process.stdout.write(String(m.resolveBranchState(process.argv[1])));"
                  % json.dumps(FLOW_EVID.as_uri()))
        proc = subprocess.run([NODE, "--input-type=module", "-e", script, str(repo)], capture_output=True,
                              text=True, encoding="utf-8", env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        calls = [line.split("\t")[:-1] for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
        self.assertEqual(calls, [BRANCH_GIT_ARGV["symbolicRef"], BRANCH_GIT_ARGV["verifyHead"]])
        self.assertEqual(proc.stdout, "protected")
        self.assertFalse(sentinel.exists())

    # ---- D25 model (5): git is started only from an absolute PATH entry (SEC-6) ----
    def _resolve_in(self, repo, env):
        """resolveBranchState(process.cwd()) run by node with its cwd set to `repo`."""
        script = ("const m = await import(%s); process.stdout.write(String(m.resolveBranchState(process.cwd())));"
                  % json.dumps(FLOW_EVID.as_uri()))
        env["GIT_CEILING_DIRECTORIES"] = str(repo.parent)
        proc = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True,
                              text=True, encoding="utf-8", cwd=repo, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def _plant_git(self, repo):
        """A program named git in `repo`. POSIX: a sentinel writer that exits 1. win32: a whoami.exe copy,
        which rejects git's argv (exit 1) and cannot write a sentinel. Returns the sentinel path."""
        sentinel = repo.parent / "planted-git-ran"
        if sys.platform == "win32":
            whoami = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "whoami.exe"
            if not whoami.is_file():
                self.skipTest("whoami.exe is not available to stand in for a planted git.exe")
            shutil.copyfile(whoami, repo / "git.exe")
        else:
            fake = repo / "git"
            fake.write_text(f"#!/bin/sh\ntouch '{sentinel}'\nexit 1\n", encoding="utf-8")
            fake.chmod(0o755)
        return sentinel

    def test_repository_environment_does_not_redirect_the_branch_probe(self):  # SEC-5
        # The probe hardens the program, the argv and the cwd, then forwards the whole ambient
        # environment. GIT_DIR and friends override the cwd for symbolic-ref/rev-parse, so a repo
        # genuinely on `main` reported 'ok' and a protected-branch edit went unreported. The sibling
        # added in the same change set (scripts/build_release.py `_GIT_ENV_DROP`) drops these keys.
        protected = self.make_repo("main")
        other = self.make_repo("feature/elsewhere")
        for name, overrides in (
            ("git-dir", {"GIT_DIR": str(other / ".git")}),
            ("git-dir+work-tree", {"GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other)}),
            ("index-file", {"GIT_INDEX_FILE": str(other / ".git" / "index")}),
        ):
            with self.subTest(override=name):
                env = os.environ.copy()
                env.update(overrides)
                self.assertEqual(self._resolve_in(protected, env), "protected")

    def test_git_behind_relative_path_entry_is_not_run(self):  # AC32, AC120
        # Mutation: resolveBranchState spawning a bare `git`, so the lookup walks the relative `.` entry.
        repo = self.make_repo("main")
        sentinel = self._plant_git(repo)
        env = os.environ.copy()
        env["PATH"] = "." + os.pathsep + env.get("PATH", "")
        self.assertEqual(self._resolve_in(repo, env), "protected")
        self.assertFalse(sentinel.exists(), "the planted git ran")

    @unittest.skipUnless(sys.platform == "win32", "the cwd-first program lookup exists only on win32")
    def test_planted_git_exe_in_cwd_is_not_run(self):  # AC32, AC120
        # Mutation: a bare `git` spawn; with NoDefaultCurrentDirectoryInExePath unset, win32 searches the cwd first.
        repo = self.make_repo("main")
        self._plant_git(repo)
        env = os.environ.copy()
        for name in [k for k in env if k.lower() == "nodefaultcurrentdirectoryinexepath"]:
            del env[name]
        self.assertEqual(self._resolve_in(repo, env), "protected")

    # ---- guards: pass before and after the branch step ----
    def test_feature_branch_no_branch_id(self):  # AC32
        self.assertEqual(self.stop(_satisfied_events(RCF), self.make_repo("feature/x")), {})

    def test_branch_name_lookalikes_not_protected(self):
        for branch in ("main-feature", "release/main"):
            with self.subTest(branch=branch):
                self.assertEqual(self.stop(_satisfied_events(RCF), self.make_repo(branch)), {})

    def test_detached_head_no_commits_and_non_git_no_finding(self):
        for name, cwd in (("detached", self.make_repo("main", detached=True)),
                          ("no-commits", self.make_repo("main", commit=False)),
                          ("non-git", self._root())):
            with self.subTest(state=name):
                self.assertEqual(self.stop(_satisfied_events(RCF), cwd), {})

    def test_block_flag_branch_only_no_block_decision(self):  # AC33
        out = self.stop(_satisfied_events(RCF), self.make_repo("main"), block=True)
        self.assertNotEqual(out.get("decision"), "block")
        self.assertEqual(_reminder_ids(out), ["branch"])

    def test_block_flag_block_step_also_missing_lists_only_block_ids(self):  # AC33
        raw = self.stop_raw([skill(RCF), edit("src/app.py"), ev_text("Fixed.")], self.make_repo("main"), block=True)
        self.assertEqual(raw, PINNED_STEP_BLOCK_MAIN)

    def test_order_guard_output_unchanged_on_main_never_names_new_steps(self):  # AC34
        repo = self.make_repo("main")
        for flow in self.FLOWS:
            with self.subTest(flow=flow):
                stdin = {"tool_input": {"file_path": "src/app.py"},
                         "transcript_path": self._transcript([skill(flow), edit("src/app.py"), ev_text("Fixed.")])}
                raw = self.run_hook(ORDER_GUARD, stdin, repo, block=True)
                self.assertNotIn("branch", raw)
                self.assertNotIn("review-result", raw)
                if flow == RCF:
                    self.assertEqual(raw, PINNED_ORDER_BLOCK_MAIN)

    def test_plan_only_on_main_no_branch_finding(self):  # AC36
        events = [skill(RCF), edit("docs/agentic-sdlc/plans/x.md"), ev_text("Planned.")]
        self.assertEqual(self.stop(events, self.make_repo("main")), {})

    def test_fsmonitor_config_characterization(self):  # S10 end-to-end (characterization)
        """Characterization only: with core.fsmonitor set to a sentinel-writing command, the Stop reminder
        equals the unconfigured run and the sentinel never appears. The discriminating proof that the
        resolver disables it is test_resolver_invokes_git_with_fixed_hardened_argv."""
        plain = self.make_repo("main")
        configured = self.make_repo("main")
        sentinel = configured.parent / "fsmonitor-sentinel"
        writer = configured.parent / "fsmonitor.sh"
        writer.write_text(f"#!/bin/sh\ntouch '{sentinel.as_posix()}'\n", encoding="utf-8")
        writer.chmod(0o755)
        _git(configured, "config", "core.fsmonitor", writer.as_posix())
        events = _satisfied_events(RCF)
        self.assertEqual(self.stop(events, configured), self.stop(events, plain))
        self.assertFalse(sentinel.exists())


CONTROL_SKILL = ("Skill", {"skill": "agentic-sdlc:implementation-control"})
CONTROL_AGENT = ("Agent", {"subagent_type": "agentic-sdlc:implementation-auditor", "prompt": "do the audit"})
SECURITY_SKILL = ("Skill", {"skill": "agentic-sdlc:security-audit"})
SECURITY_AGENT = ("Agent", {"subagent_type": "agentic-sdlc:security-reviewer", "prompt": "do the audit"})


def _review_transcript(flow, dispatches, *, source_edit=True):
    """`flow` with its non-reviewer steps satisfied (with results), then each (member, result) reviewer
    dispatch. result is 'ok', 'error', 'absent' (a result without is_error) or 'missing' (no result)."""
    base = [skill(flow)] + ([edit("src/app.py")] if source_edit else [])
    if flow == SR:
        base.append(bash("py -3 -m unittest tests.test_characterization"))
    else:
        base += [workflow("agentic-sdlc:spec-plan-draft"), bash("py -3 -m unittest tests.test_app")]
    events = with_results(base)
    for n, ((name, inp), result) in enumerate(dispatches):
        tool_id = f"toolu_review_{n}"
        events.append(tool_with_id(name, inp, tool_id))
        if result != "missing":
            events.append(tool_result(tool_id, result == "error", include_flag=result != "absent"))
    return events + [ev_text("Done.")]


# ---- AC36-AC38, AC40: warn-level review-result step (Task 20) -----------------
@unittest.skipIf(NODE is None, "node not available")
class TestReviewResultStep(unittest.TestCase):
    run_guard = TestFlowStepGuard.run_guard  # the same non-git temp-cwd driver, not its tests

    def ids(self, events, **kw):
        return _reminder_ids(self.run_guard(events, **kw))

    # ---- RED ----
    # C17 item 6: a dispatch whose every tool_result has is_error true no longer satisfies its toolUse
    # step, so an errored control dispatch lists `control` as well; review-result is still listed once.
    def test_errored_control_dispatch_lists_control_and_review_result_once(self):  # AC37 + C17 item 6
        events = _review_transcript(FB, [(CONTROL_AGENT, "error"), (SECURITY_AGENT, "ok")])
        self.assertEqual(self.ids(events), ["control", "review-result"])

    def test_missing_result_lists_review_result(self):  # AC37
        events = _review_transcript(FB, [(CONTROL_AGENT, "missing"), (SECURITY_AGENT, "ok")])
        self.assertEqual(self.ids(events), ["review-result"])

    def test_security_cleared_control_errored_listed_once(self):  # AC37 + C17 item 6
        events = _review_transcript(FB, [(SECURITY_SKILL, "ok"), (SECURITY_AGENT, "ok"),
                                         (CONTROL_SKILL, "error"), (CONTROL_AGENT, "error")])
        self.assertEqual(self.ids(events), ["control", "review-result"])

    # ---- guards: pass before and after the review-result step ----
    def test_mixed_member_results_clear_step(self):  # AC37: any member's non-error result clears its step
        cases = {
            "control skill error, agent ok": [(CONTROL_SKILL, "error"), (CONTROL_AGENT, "ok"), (SECURITY_AGENT, "ok")],
            "control skill ok, agent error": [(CONTROL_SKILL, "ok"), (CONTROL_AGENT, "error"), (SECURITY_AGENT, "ok")],
            "security skill error, agent ok": [(CONTROL_AGENT, "ok"), (SECURITY_SKILL, "error"), (SECURITY_AGENT, "ok")],
            "security skill ok, agent error": [(CONTROL_AGENT, "ok"), (SECURITY_SKILL, "ok"), (SECURITY_AGENT, "error")],
        }
        for name, dispatches in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.run_guard(_review_transcript(FB, dispatches)), {})

    def test_is_error_absent_is_non_error(self):
        events = _review_transcript(FB, [(CONTROL_AGENT, "absent"), (SECURITY_AGENT, "absent")])
        self.assertEqual(self.run_guard(events), {})

    def test_safe_refactor_security_error_not_listed(self):  # AC37: safe-refactor is control-only
        events = _review_transcript(SR, [(CONTROL_AGENT, "ok"), (SECURITY_AGENT, "error")])
        self.assertEqual(self.run_guard(events), {})

    def test_no_dispatch_not_listed_and_control_security_unchanged(self):
        self.assertEqual(self.ids(_review_transcript(FB, [])), ["security", "control"])

    def test_no_source_edit_errored_auditor_not_listed(self):  # AC36
        events = _review_transcript(FB, [(CONTROL_AGENT, "error")], source_edit=False)
        self.assertEqual(self.run_guard(events), {})

    def test_block_flag_review_result_never_blocks(self):  # AC38 + C17 item 6
        # A control dispatch with no result yet still satisfies `control` (no result counts), so only the
        # warn-level review-result step is open: the block flag adds no block decision.
        pending = self.run_guard(_review_transcript(FB, [(CONTROL_AGENT, "missing"), (SECURITY_AGENT, "ok")]), block=True)
        self.assertNotEqual(pending.get("decision"), "block")
        self.assertEqual(_reminder_ids(pending), ["review-result"])
        # C17 item 6: an errored control dispatch fails the block-level `control` step. The block reason
        # names `control` only; review-result never joins a block decision.
        errored = self.run_guard(_review_transcript(FB, [(CONTROL_AGENT, "error"), (SECURITY_AGENT, "ok")]), block=True)
        self.assertEqual(errored.get("decision"), "block")
        self.assertEqual(_block_ids(errored), ["control"])
        cleared = _review_transcript(FB, [(CONTROL_AGENT, "ok"), (SECURITY_AGENT, "ok")])
        self.assertEqual(self.run_guard(cleared, block=True), {})

    def test_control_security_outcomes_for_errored_and_missing_dispatches(self):  # AC37 + C17 item 6
        def step_ids(dispatches):
            return [i for i in self.ids(_review_transcript(FB, dispatches)) if i in ("security", "control")]

        # C17 item 6: an errored dispatch (every tool_result is_error) no longer satisfies its step; a
        # dispatch with no result still does.
        self.assertEqual(step_ids([(CONTROL_AGENT, "error"), (SECURITY_AGENT, "missing")]), ["control"])
        self.assertEqual(step_ids([(SECURITY_AGENT, "error")]), ["security", "control"])
        self.assertEqual(step_ids([(CONTROL_SKILL, "missing")]), ["security"])

    def test_pipeline_missing_control_block_pinned(self):  # AC40, C6 pipeline block pin
        events = [skill(PIPE), skill(DS), workflow("agentic-sdlc:spec-plan-draft"),
                  edit("src/app.py"), bash("py -3 -m unittest tests.test_app"),
                  agent("agentic-sdlc:security-reviewer"), ev_text("Done.")]
        self.assertEqual(self.run_guard(events, block=True), json.loads(PINNED_PIPE_CONTROL_BLOCK))

    def test_pipeline_block_stdout_bytes_pinned(self):  # C6: exact bytes, not just the parsed object
        events = [skill(PIPE), skill(DS), workflow("agentic-sdlc:spec-plan-draft"),
                  edit("src/app.py"), bash("py -3 -m unittest tests.test_app"),
                  agent("agentic-sdlc:security-reviewer"), ev_text("Done.")]
        self.assertEqual(_run_step_guard_raw(self, events, block=True), PINNED_PIPE_CONTROL_BLOCK)


@unittest.skipIf(NODE is None, "node not available")
class TestFlowOrderGuard(unittest.TestCase):
    def run_guard(self, file_path, events, *, block=False, cwd=None):
        with tempfile.TemporaryDirectory() as td:
            run_cwd = cwd or td
            tpath = Path(td) / "transcript.jsonl"
            tpath.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
            env = os.environ.copy()
            env.pop("AGENTIC_FLOW_GATE_BLOCK", None)  # the warn path must not inherit an ambient flag
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

    def test_safe_refactor_echoed_characterization_still_denies_claude(self):  # A2 Claude SHAPE gate (order)
        events = [skill(SR), bash("echo pytest")]  # a printer, not a real characterization run
        out = self.run_guard("src/app.py", events, block=True)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_pipeline_denies_source_edit_before_dispatch_spec_plan_and_red_first(self):  # C6
        out = self.run_guard("src/app.py", [skill(PIPE)], block=True)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(out["hookSpecificOutput"]["permissionDecisionReason"],
                         "agentic-sdlc-pipeline: produce spec and plan before editing source (missing: dispatch, "
                         "spec, plan, red-first). Externalize them as validated artifacts first.")

    # ---- C6 red-first: a test command must run before the first production edit (pipeline) ----
    def _pipe_ready(self):
        """Pipeline active with dispatch, spec and plan satisfied - red-first is the only open
        beforeSourceEdit step."""
        return [skill(PIPE), skill(DS), workflow("agentic-sdlc:spec-plan-draft")]

    def test_pipeline_source_edit_before_test_command_warns_red_first(self):  # C6, warn by default
        out = self.run_guard("src/app.py", self._pipe_ready())
        self.assertNotIn("hookSpecificOutput", out)
        self.assertEqual(out, {"systemMessage": "flow-order-guard: spec/plan not present before a source edit "
                                                "(missing: red-first)."})

    def test_pipeline_source_edit_before_test_command_denied_under_block_flag(self):  # C6
        # The deny sentence is the locked flow-order-guard.mjs text (D7 accepted limitation); the
        # C6 behaviour is the `missing: red-first` part.
        out = self.run_guard("src/app.py", self._pipe_ready(), block=True)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("missing: red-first)", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(out["hookSpecificOutput"]["permissionDecisionReason"], PIPE_RED_FIRST_DENY_REASON)

    def test_pipeline_test_command_before_edit_clears_red_first(self):  # C6
        for command in ("python -m pytest -q", "py -3 -m unittest tests.test_app"):
            with self.subTest(command=command):
                events = self._pipe_ready() + [bash(command)]
                self.assertEqual(self.run_guard("src/app.py", events, block=True), {})
                self.assertEqual(self.run_guard("src/app.py", events), {})

    def test_pipeline_powershell_test_command_clears_red_first(self):  # C6 + AC1 (PowerShell parity)
        events = self._pipe_ready() + [powershell("python -m pytest -q")]
        self.assertEqual(self.run_guard("src/app.py", events, block=True), {})

    def test_pipeline_echoed_test_command_does_not_clear_red_first(self):  # C6 + A2 shape gate
        events = self._pipe_ready() + [bash("echo pytest")]
        out = self.run_guard("src/app.py", events, block=True)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecisionReason"], PIPE_RED_FIRST_DENY_REASON)

    def test_pipeline_test_file_edit_is_not_a_source_edit(self):  # C6: writing the RED test comes first
        for path in ("tests/test_app.py", "src/app_test.py", "src/app.test.ts", "web/app.spec.js"):
            with self.subTest(path=path):
                self.assertEqual(self.run_guard(path, self._pipe_ready(), block=True), {})

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


CLAIM_TEXT = "Feature complete. All tests passing."
CLAIM_SPLIT_A = "Feature complete. "
CLAIM_SPLIT_B = "All tests passing."
AUDITOR_ID = "toolu_async_auditor"
WORKFLOW_ID = "toolu_wf_error"


def launch_receipt(tool_id, status="async_launched", *, include_tool_result=True, error=None):
    """A native launch receipt. include_tool_result=True is today's satisfier; False is pending-only."""
    rec = {"type": "user", "toolUseResult": {"status": status}}
    if error is not None:
        rec["toolUseResult"]["error"] = error
    if include_tool_result:
        rec["message"] = {"content": [{
            "type": "tool_result", "tool_use_id": tool_id, "content": "launched", "is_error": False,
        }]}
    return rec


def task_notification(tool_use_id, status="completed", *, body="", origin=True, subkind=None,
                      as_blocks=False, extra_header_tag=None, omit_terminator=False,
                      tags_only_in_body=False, pad_bytes=0):
    """A user record whose body may carry a BR8 task-notification header."""
    header = (
        f"<task-notification><task-id>task_1</task-id><tool-use-id>{tool_use_id}</tool-use-id>"
        f"<output-file>/tmp/out.txt</output-file>"
    )
    if extra_header_tag:
        header += extra_header_tag
    header += f"<status>{status}</status>"
    if not omit_terminator:
        header += "<summary>"
    if tags_only_in_body:
        text = (
            f"notes only\n<tool-use-id>{tool_use_id}</tool-use-id>"
            f"<status>{status}</status><summary>\n{body}"
        )
    else:
        text = header + body
    if pad_bytes:
        text += "X" * pad_bytes
    content = [{"type": "text", "text": text}] if as_blocks else text
    rec = {"type": "user", "message": {"content": content}}
    if origin:
        rec["origin"] = {"kind": "task-notification"}
        if subkind is not None:
            rec["origin"]["subkind"] = subkind
    return rec


def _async_control_events(*, receipt_result=True, receipt_status="async_launched", notification=None):
    """RCF with every block step satisfied except the auditor, which is a launch receipt."""
    events = with_results([
        skill(RCF), edit("src/app.py"), workflow("agentic-sdlc:spec-plan-draft"),
        bash("python -m pytest -q"), agent("agentic-sdlc:security-reviewer"),
    ])
    events.append(tool_with_id(
        "Agent", {"subagent_type": "agentic-sdlc:implementation-auditor", "prompt": "do the audit"},
        AUDITOR_ID,
    ))
    events.append(launch_receipt(AUDITOR_ID, receipt_status, include_tool_result=receipt_result))
    if notification is not None:
        events.append(notification)
    events.append(ev_text("Done."))
    return events


@unittest.skipIf(NODE is None, "node not available")
class TestPowerShellCommandEvidence(unittest.TestCase):
    """AC1: a PowerShell runner invocation satisfies tests / characterization exactly as Bash does."""

    run_step = TestFlowStepGuard.run_guard
    run_order = TestFlowOrderGuard.run_guard

    def test_ac1_powershell_pytest_satisfies_tests_stop(self):
        events = with_results([
            skill(RCF), edit("src/app.py"), workflow("agentic-sdlc:spec-plan-draft"),
            powershell("python -m pytest -q"),
            agent("agentic-sdlc:security-reviewer"),
            agent("agentic-sdlc:implementation-auditor"), ev_text("Done."),
        ])
        self.assertEqual(self.run_step(events, block=True), {})

    def test_ac1_powershell_characterization_allows_safe_refactor_edit(self):
        events = [skill(SR), powershell("py -3 -m unittest tests.test_characterization")]
        self.assertEqual(self.run_order("src/app.py", events, block=True), {})

    def test_ac1_powershell_echoed_pytest_does_not_satisfy(self):
        events = with_results([
            skill(RCF), edit("src/app.py"), workflow("agentic-sdlc:spec-plan-draft"),
            powershell("echo pytest"),
            agent("agentic-sdlc:security-reviewer"),
            agent("agentic-sdlc:implementation-auditor"), ev_text("Done."),
        ])
        out = self.run_step(events, block=True)
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("tests", _block_ids(out))


@unittest.skipIf(NODE is None, "node not available")
class TestCompletionClaimGuard(unittest.TestCase):
    """AC2-AC4: prefer last_assistant_message; block only when the transcript has caught up (BR11)."""

    def run_hook(self, lines, *, block=False, last_assistant_message=None):
        with tempfile.TemporaryDirectory() as td:
            tpath = Path(td) / "transcript.jsonl"
            tpath.write_text("\n".join(json.dumps(o) for o in lines), encoding="utf-8")
            env = os.environ.copy()
            if block:
                env["AGENTIC_COMPLETION_GATE_BLOCK"] = "true"
            payload = {"transcript_path": str(tpath)}
            if last_assistant_message is not None:
                payload["last_assistant_message"] = last_assistant_message
            proc = subprocess.run(
                [NODE, str(CLAIM_GUARD)], env=env, input=json.dumps(payload),
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = (proc.stdout or "").strip()
            return json.loads(out) if out else {}

    @staticmethod
    def _assistant(text, message_id=None):
        message = {"content": [{"type": "text", "text": text}]}
        if message_id is not None:
            message["id"] = message_id
        return {"type": "assistant", "message": message}

    def test_ac2_last_assistant_message_caught_up_warns_and_blocks(self):
        lines = [self._assistant(CLAIM_TEXT)]
        warn = self.run_hook(lines, last_assistant_message=CLAIM_TEXT)
        self.assertIn("systemMessage", warn)
        self.assertNotIn("decision", warn)
        blocked = self.run_hook(lines, block=True, last_assistant_message=CLAIM_TEXT)
        self.assertEqual(blocked.get("decision"), "block")

    def test_ac3_lagging_transcript_warns_never_blocks(self):
        out = self.run_hook(
            [self._assistant("Still working through the remaining cases.")],
            block=True, last_assistant_message=CLAIM_TEXT,
        )
        self.assertIn("systemMessage", out)
        self.assertNotEqual(out.get("decision"), "block")

    def test_ac3_split_records_sharing_message_id_block(self):
        lines = [self._assistant(CLAIM_SPLIT_A, "msg_split"), self._assistant(CLAIM_SPLIT_B, "msg_split")]
        out = self.run_hook(lines, block=True, last_assistant_message=CLAIM_SPLIT_A + CLAIM_SPLIT_B)
        self.assertEqual(out.get("decision"), "block")

    def test_ac3_whitespace_only_difference_still_blocks(self):
        out = self.run_hook(
            [self._assistant(CLAIM_TEXT)],
            block=True, last_assistant_message="  Feature   complete.   All   tests passing.  ",
        )
        self.assertEqual(out.get("decision"), "block")

    def test_ac4_field_without_claim_overrides_old_transcript_claim(self):
        out = self.run_hook(
            [self._assistant(CLAIM_TEXT)],
            block=True, last_assistant_message="Still investigating the remaining failures.",
        )
        self.assertEqual(out, {})

    def test_ac4_absent_field_keeps_transcript_decision(self):
        blocked = self.run_hook([self._assistant(CLAIM_TEXT)], block=True)
        self.assertEqual(blocked.get("decision"), "block")
        silent = self.run_hook([self._assistant("A couple of tests still fail.")], block=True)
        self.assertEqual(silent, {})


@unittest.skipIf(NODE is None, "node not available")
class TestFlowStepLastAssistantMessage(unittest.TestCase):
    """AC5: skipped-flow heuristic driven only by last_assistant_message when the field is a string."""

    run_guard = TestFlowStepGuard.run_guard

    def test_ac5_claim_only_in_last_assistant_message_warns(self):
        events = [edit("src/app.py"), edit("src/two.py"), ev_text("Investigating the remaining cases.")]
        out = self.run_guard(events, block=True, last_assistant_message=CLAIM_TEXT)
        self.assertIn("systemMessage", out)
        self.assertNotEqual(out.get("decision"), "block")
        self.assertIn("skip", out.get("systemMessage", "").lower())

    def test_ac5_absent_field_uses_transcript_text(self):
        claimed = [edit("src/app.py"), edit("src/two.py"), ev_text(CLAIM_TEXT)]
        out = self.run_guard(claimed, block=True)
        self.assertIn("systemMessage", out)
        self.assertNotEqual(out.get("decision"), "block")
        silent = self.run_guard([edit("src/app.py"), ev_text("Investigating.")], block=True)
        self.assertEqual(silent, {})


@unittest.skipIf(NODE is None, "node not available")
class TestReviewResultAsyncReceipts(unittest.TestCase):
    """AC6-AC9: launch receipts are pending; only a BR8 notification or in-flight reviewer clears."""

    run_guard = TestFlowStepGuard.run_guard

    def ids(self, events, **kw):
        return _reminder_ids(self.run_guard(events, **kw))

    def test_ac6_async_launched_receipt_lists_review_result(self):
        events = _async_control_events(receipt_result=True, receipt_status="async_launched")
        self.assertEqual(self.ids(events), ["review-result"])

    def test_ac6_remote_launched_receipt_lists_review_result(self):
        events = _async_control_events(receipt_result=True, receipt_status="remote_launched")
        self.assertEqual(self.ids(events), ["review-result"])

    def test_ac7_completed_notification_clears_review_result(self):
        note = task_notification(AUDITOR_ID, "completed")
        events = _async_control_events(receipt_result=False, notification=note)
        self.assertNotIn("review-result", self.ids(events))

    def test_ac7_completed_notification_as_text_blocks_clears(self):
        note = task_notification(AUDITOR_ID, "completed", as_blocks=True)
        events = _async_control_events(receipt_result=False, notification=note)
        self.assertNotIn("review-result", self.ids(events))

    def test_ac7_failed_killed_stopped_stay_missing(self):
        for status in ("failed", "killed", "stopped"):
            with self.subTest(status=status):
                note = task_notification(AUDITOR_ID, status)
                events = _async_control_events(receipt_result=False, notification=note)
                self.assertEqual(self.ids(events), ["review-result"])

    def test_ac7_spoofed_or_malformed_headers_do_not_clear(self):
        cases = {
            "tags-in-body": task_notification(AUDITOR_ID, tags_only_in_body=True),
            "no-terminator": task_notification(AUDITOR_ID, omit_terminator=True),
            "repeated-tag": task_notification(
                AUDITOR_ID, extra_header_tag=f"<tool-use-id>{AUDITOR_ID}</tool-use-id>",
            ),
            "subkind": task_notification(AUDITOR_ID, subkind="user"),
            "no-origin": task_notification(AUDITOR_ID, origin=False),
        }
        for name, note in cases.items():
            with self.subTest(case=name):
                events = _async_control_events(receipt_result=False, notification=note)
                self.assertEqual(self.ids(events), ["review-result"])

    def test_ac8_in_flight_background_reviewer_not_missing(self):
        events = _async_control_events(receipt_result=False)
        tasks = [{"type": "subagent", "agent_type": "agentic-sdlc:implementation-auditor"}]
        self.assertNotIn("review-result", self.ids(events, background_tasks=tasks))

    def test_ac9_one_megabyte_notification_matches_unpadded_and_is_bounded(self):
        bare = task_notification(AUDITOR_ID, "completed")
        padded = task_notification(AUDITOR_ID, "completed", pad_bytes=1024 * 1024)
        t0 = time.perf_counter()
        bare_ids = self.ids(_async_control_events(receipt_result=False, notification=bare))
        baseline = time.perf_counter() - t0
        t1 = time.perf_counter()
        padded_ids = self.ids(_async_control_events(receipt_result=False, notification=padded))
        padded_elapsed = time.perf_counter() - t1
        self.assertEqual(padded_ids, bare_ids)
        self.assertNotIn("review-result", padded_ids)
        self.assertLess(padded_elapsed - baseline, 2.0)


@unittest.skipIf(NODE is None, "node not available")
class TestWorkflowLaunchError(unittest.TestCase):
    """AC10: a Workflow receipt with error does not satisfy spec/plan when no artifact exists."""

    run_guard = TestFlowStepGuard.run_guard

    def test_ac10_workflow_error_receipt_does_not_satisfy_spec_plan(self):
        events = with_results([skill(RCF), edit("src/app.py")])
        events.append(tool_with_id(
            "Workflow", {"name": "agentic-sdlc:spec-plan-draft", "args": {"mode": "spec"}}, WORKFLOW_ID,
        ))
        events.append(launch_receipt(WORKFLOW_ID, include_tool_result=True, error="stopped"))
        events.extend(with_results([
            bash("python -m pytest -q"),
            agent("agentic-sdlc:security-reviewer"),
            agent("agentic-sdlc:implementation-auditor"),
            ev_text("Done."),
        ]))
        out = self.run_guard(events, block=True)
        self.assertEqual(out.get("decision"), "block")
        missing = _block_ids(out)
        self.assertIn("spec", missing)
        self.assertIn("plan", missing)


# ---- C6 / D3 / D7: exact-name evidence (`exactName`) and exact flow activation -------------
def _pipe_events(*, dispatch=DS, security="agentic-sdlc:security-reviewer",
                 control="agentic-sdlc:implementation-auditor"):
    """A pipeline run with every Stop step satisfied, each reviewer/dispatch name swappable. A name
    set to None leaves that call out. Every call carries a correlated non-error tool_result."""
    events = [skill(PIPE)]
    if dispatch is not None:
        events.append(skill(dispatch))
    events += [workflow("agentic-sdlc:spec-plan-draft"), bash("py -3 -m unittest tests.test_app"),
               edit("src/app.py"), bash("py -3 -m unittest tests.test_app")]
    if security is not None:
        events.append(agent(security))
    if control is not None:
        events.append(agent(control))
    return with_results(events) + [ev_text("Done.")]


@unittest.skipIf(NODE is None, "node not available")
class TestExactNameEvidence(unittest.TestCase):
    """C6: an `exactName` toolUse item is satisfied only when `input.skill` (Skill) or
    `input.subagent_type` (Agent) equals X or agentic-sdlc:X - never by a substring of the
    serialized input. The receiptHasError rule applies to it (C17 item 6 extends that rule; see
    TestRealErrorShape)."""

    run_guard = TestFlowStepGuard.run_guard

    def test_prefixed_and_bare_names_both_satisfy(self):
        cases = {
            "prefixed": {},
            "bare dispatch": {"dispatch": "dispatch-strategy"},
            "bare security": {"security": "security-reviewer"},
            "bare control": {"control": "implementation-auditor"},
            "all bare": {"dispatch": "dispatch-strategy", "security": "security-reviewer",
                         "control": "implementation-auditor"},
        }
        for name, kw in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.run_guard(_pipe_events(**kw), block=True), {})

    def test_lookalike_names_do_not_satisfy(self):
        cases = {
            "dispatch": {"dispatch": "agentic-sdlc:dispatch-strategy-extra"},
            "security": {"security": "agentic-sdlc:security-reviewer-extra"},
            "control": {"control": "agentic-sdlc:implementation-auditor-extra"},
            "foreign prefix security": {"security": "other-plugin:security-reviewer"},
        }
        for step, kw in cases.items():
            with self.subTest(case=step):
                out = self.run_guard(_pipe_events(**kw), block=True)
                self.assertEqual(out.get("decision"), "block")
                self.assertEqual(_block_ids(out), [step.split()[-1]])

    def test_name_only_in_args_or_prompt_does_not_satisfy(self):
        # The marker appears in the serialized input, but not as the skill / subagent_type itself.
        dispatch_in_args = ev_tool("Skill", {"skill": "agentic-sdlc:mind-spark",
                                             "args": "then run dispatch-strategy"})
        security_in_prompt = ev_tool("Agent", {"subagent_type": "general-purpose",
                                               "prompt": "act as security-reviewer and review the diff"})
        control_in_prompt = ev_tool("Agent", {"subagent_type": "general-purpose",
                                              "prompt": "run the implementation-auditor checklist"})
        events = with_results([skill(PIPE), dispatch_in_args, workflow("agentic-sdlc:spec-plan-draft"),
                               bash("py -3 -m unittest tests.test_app"), edit("src/app.py"),
                               security_in_prompt, control_in_prompt]) + [ev_text("Done.")]
        out = self.run_guard(events, block=True)
        self.assertEqual(out.get("decision"), "block")
        self.assertEqual(_block_ids(out), ["dispatch", "security", "control"])

    def test_event_without_id_or_result_still_counts(self):  # receiptHasError rule retained
        # No id and no result on any call (the bare helpers): every block step still counts, so the
        # only finding is the warn-level review-result step, whose reviewers returned nothing.
        events = [skill(PIPE), skill(DS), workflow("agentic-sdlc:spec-plan-draft"),
                  bash("py -3 -m unittest tests.test_app"), edit("src/app.py"),
                  agent("agentic-sdlc:security-reviewer"), agent("agentic-sdlc:implementation-auditor"),
                  ev_text("Done.")]
        out = self.run_guard(events, block=True)
        self.assertNotEqual(out.get("decision"), "block", out)
        self.assertEqual(_reminder_ids(out), ["review-result"])

    def test_errored_receipt_does_not_count(self):  # receiptHasError rule retained for exactName items
        events = with_results([skill(PIPE), skill(DS), workflow("agentic-sdlc:spec-plan-draft"),
                               bash("py -3 -m unittest tests.test_app"), edit("src/app.py"),
                               agent("agentic-sdlc:implementation-auditor")])
        events.append(tool_with_id("Agent", {"subagent_type": "agentic-sdlc:security-reviewer",
                                             "prompt": "do the audit"}, "toolu_sec_err"))
        events.append(launch_receipt("toolu_sec_err", include_tool_result=True, error="stopped"))
        events.append(ev_text("Done."))
        out = self.run_guard(events, block=True)
        self.assertEqual(out.get("decision"), "block")
        self.assertEqual(_block_ids(out), ["security"])

    def test_review_result_reviewer_membership_is_exact(self):  # C6: same rule for reviewResult reviewers
        # The real security-reviewer was dispatched and returned nothing; a lookalike returned a clean
        # result. Under substring membership the lookalike's result would clear the security group.
        events = with_results([skill(PIPE), skill(DS), workflow("agentic-sdlc:spec-plan-draft"),
                               bash("py -3 -m unittest tests.test_app"), edit("src/app.py"),
                               agent("agentic-sdlc:implementation-auditor"),
                               agent("agentic-sdlc:security-reviewer-extra")])
        events.append(tool_with_id("Agent", {"subagent_type": "agentic-sdlc:security-reviewer",
                                             "prompt": "do the audit"}, "toolu_sec_pending"))
        events.append(ev_text("Done."))
        self.assertEqual(_reminder_ids(self.run_guard(events)), ["review-result"])


@unittest.skipIf(NODE is None, "node not available")
class TestExactFlowActivation(unittest.TestCase):
    """C6: a Skill tool_use activates a flow only when it is non-errored and its input.skill equals the
    marker or agentic-sdlc:<marker>. (A slash-command start is the other activation path; see
    TestSlashCommandFlowActivation.)"""

    run_step = TestFlowStepGuard.run_guard
    run_order = TestFlowOrderGuard.run_guard

    def test_dispatch_strategy_args_naming_a_flow_do_not_activate_it(self):
        mention = ev_tool("Skill", {"skill": DS, "args": "route this feature-build work; consider root-cause-fix"})
        events = [mention, ev_text("Mechanism: single session for the feature-build."), edit("src/app.py"),
                  ev_text("Edited.")]
        self.assertEqual(self.run_step(events, block=True), {})
        self.assertEqual(self.run_order("src/app.py", [mention], block=True), {})

    def test_lookalike_or_foreign_skill_names_do_not_activate(self):
        for name in ("agentic-sdlc:root-cause-fix-lite", "other-plugin:feature-build",
                     "agentic-sdlc:agentic-sdlc-pipeline-v2"):
            with self.subTest(skill=name):
                self.assertEqual(self.run_order("src/app.py", [skill(name)], block=True), {})
                self.assertEqual(self.run_step([skill(name), edit("src/app.py"), ev_text("Edited.")],
                                               block=True), {})

    def test_errored_pipeline_skill_call_activates_nothing(self):  # C6: receiptHasError still excludes
        def errored_pipe(error):
            call = tool_with_id("Skill", {"skill": PIPE}, "toolu_pipe")
            result = {"type": "user", "toolUseResult": {"error": error} if error else {},
                      "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_pipe",
                                               "content": "result", "is_error": bool(error)}]}}
            return [call, result]
        self.assertEqual(self.run_order("src/app.py", errored_pipe("Unknown skill"), block=True), {})
        # Control: the same call without the error receipt activates the pipeline and the edit is denied.
        order = self.run_order("src/app.py", errored_pipe(None), block=True)
        self.assertEqual(order["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_prefixed_and_bare_flow_skill_still_activate(self):
        for name in (FB, "feature-build", PIPE, "agentic-sdlc-pipeline"):
            with self.subTest(skill=name):
                out = self.run_step([skill(name), edit("src/app.py"), ev_text("Built.")], block=True)
                self.assertEqual(out.get("decision"), "block")
                self.assertIn("spec", _block_ids(out))
                order = self.run_order("src/app.py", [skill(name)], block=True)
                self.assertEqual(order["hookSpecificOutput"]["permissionDecision"], "deny")


SLASH_FIXTURE = REPO / "tests" / "fixtures" / "transcripts" / "claude-2.1.302-slash-pipeline-start.jsonl"


def slash_records():
    """The two records Claude Code 2.1.302 wrote for `/agentic-sdlc-pipeline add a greeting helper`
    (captured 2026-10-17 with no model call; the bare and the namespaced form record the same thing):
    the user's slash-command start, then the isMeta skill-body record."""
    return [json.loads(line) for line in SLASH_FIXTURE.read_text(encoding="utf-8").splitlines() if line]


def slash_start(command_name, args="add a greeting helper", *, blocks=False):
    """A slash-command start record in the captured shape, for `/<command_name> <args>`."""
    text = (f"<command-message>{command_name}</command-message>\n<command-name>/{command_name}</command-name>\n"
            f"<command-args>{args}</command-args>")
    return user_prompt(text, blocks=blocks)


@unittest.skipIf(NODE is None, "node not available")
class TestSlashCommandFlowActivation(unittest.TestCase):
    """D7: a flow started by a slash command is active like one started by a Skill tool call. The start
    is the top-level user record whose content opens with <command-message> and names
    <command-name>/X</command-name>, where X is the marker or agentic-sdlc:<marker>."""

    run_step = TestFlowStepGuard.run_guard
    run_order = TestFlowOrderGuard.run_guard

    def stop(self, events, final_text, **kw):
        return self.run_step(events + [ev_text(final_text)], last_assistant_message=final_text, **kw)

    @staticmethod
    def _call(skill_name, tool_id):
        return [tool_with_id("Skill", {"skill": skill_name}, tool_id), tool_result(tool_id, False)]

    def test_captured_slash_start_activates_the_pipeline_for_flow_order(self):
        out = self.run_order("src/app.py", slash_records(), block=True)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(out["hookSpecificOutput"]["permissionDecisionReason"],
                         "agentic-sdlc-pipeline: produce spec and plan before editing source (missing: dispatch, "
                         "spec, plan, red-first). Externalize them as validated artifacts first.")
        warn = self.run_order("src/app.py", slash_records())
        self.assertEqual(warn, {"systemMessage": "flow-order-guard: spec/plan not present before a source edit "
                                                 "(missing: dispatch, spec, plan, red-first)."})

    def test_captured_slash_start_activates_the_pipeline_for_flow_step(self):
        out = self.run_step(slash_records() + [edit("src/app.py"), ev_text("Shipped.")], block=True)
        self.assertEqual(out.get("decision"), "block")
        self.assertEqual(_block_ids(out), ["dispatch", "spec", "plan", "tests", "security", "control"])

    def test_bare_and_prefixed_command_names_activate(self):
        # 2.1.302 records the namespaced name for both typed forms; a skill installed without the plugin
        # namespace would record the bare name (not captured).
        for name in ("agentic-sdlc:agentic-sdlc-pipeline", "agentic-sdlc-pipeline"):
            for blocks in (False, True):
                with self.subTest(name=name, blocks=blocks):
                    out = self.run_order("src/app.py", [slash_start(name, blocks=blocks)], block=True)
                    self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_slash_start_of_a_focused_flow_activates_that_flow(self):
        out = self.run_step([slash_start("agentic-sdlc:feature-build"), edit("src/app.py"), ev_text("Built.")],
                            block=True)
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("spec", _block_ids(out))

    def test_records_that_are_not_a_slash_start_activate_nothing(self):
        start = slash_start("agentic-sdlc:agentic-sdlc-pipeline")
        sidechain = dict(start, isSidechain=True)
        child = dict(start, parent_tool_use_id="toolu_agent_1")
        meta = dict(start, isMeta=True)
        quoted = tool_result("toolu_grep", False)
        quoted["message"]["content"][0]["content"] = start["message"]["content"]
        cases = {
            "prose mention of the command": PROMPT,
            "tags after prose": user_prompt("Run this: " + start["message"]["content"]),
            "lookalike name": slash_start("agentic-sdlc:agentic-sdlc-pipeline-v2"),
            "foreign prefix": slash_start("other-plugin:agentic-sdlc-pipeline"),
            "sidechain record": sidechain,
            "sub-agent record": child,
            "isMeta record": meta,
            "tool_result text": quoted,
        }
        for name, record in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.run_order("src/app.py", [record], block=True), {})
                self.assertEqual(self.run_step([record, edit("src/app.py"), ev_text("Edited.")], block=True), {})

    def test_recorded_variants_of_the_start_activate(self):
        canon = slash_start(PIPE)["message"]["content"]
        variants = {
            "crlf": canon.replace("\n", "\r\n"),
            "leading whitespace": " \r\n" + canon,
            "name tag first": (f"<command-name>/{PIPE}</command-name>\n<command-message>{PIPE}</command-message>\n"
                               "<command-args></command-args>"),
            "running message": ("<command-message>agentic-sdlc-pipeline is running…</command-message>\n"
                                "<command-name>/agentic-sdlc-pipeline</command-name>"),
        }
        for name, text in variants.items():
            with self.subTest(variant=name):
                out = self.run_order("src/app.py", [user_prompt(text)], block=True)
                self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_more_records_that_are_not_a_slash_start(self):
        start = slash_start(PIPE)
        cases = {
            "args name the flow, the command does not": user_prompt(
                "<command-message>other:cmd</command-message>\n<command-name>/other:cmd</command-name>\n"
                f"<command-args><command-name>/{PIPE}</command-name></command-args>"),
            "name without the slash": user_prompt(
                f"<command-message>{PIPE}</command-message>\n<command-name>{PIPE}</command-name>\n"
                "<skill-format>true</skill-format>"),
            "local_command system record": {"type": "system", "subtype": "local_command",
                                            "content": start["message"]["content"]},
            "compaction summary": dict(start, isCompactSummary=True),
            "task notification": dict(start, origin={"kind": "task-notification"}),
            "tag after 4 KiB": user_prompt("<command-message>x</command-message>" + " " * 5000
                                           + f"<command-name>/{PIPE}</command-name>"),
        }
        for name, record in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.run_order("src/app.py", [record], block=True), {})

    def test_a_slash_start_keeps_the_flow_active_in_later_turns(self):
        out = self.run_order("src/app.py", slash_records() + [user_prompt("Continue.")], block=True)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_slash_detection_grows_linearly(self):  # lessons 2026-07-01 / 2026-10-16: assert a RATIO
        sizes = [125000 * 2 ** step for step in range(5)]
        script = (
            "const m = await import(%s); const fs = await import('node:fs'); const path = await import('node:path');"
            "const [dir, sizes] = [process.argv[1], JSON.parse(process.argv[2])]; const out = [];"
            "for (const n of sizes) { const p = path.join(dir, 't' + n + '.jsonl');"
            "  const content = ' '.repeat(n) + '<command-message>' + '<command-name>/a'.repeat(n / 16);"
            "  fs.writeFileSync(p, JSON.stringify({type: 'user', message: {content}}));"
            "  let best = Infinity; for (let i = 0; i < 3; i++) { const t0 = process.hrtime.bigint();"
            "    if (m.parseTranscript(p).slashCommands.length) throw new Error('activated');"
            "    best = Math.min(best, Number(process.hrtime.bigint() - t0)); } out.push(best); }"
            "process.stdout.write(JSON.stringify(out));" % json.dumps(FLOW_EVID.as_uri()))
        with tempfile.TemporaryDirectory() as td:
            proc = subprocess.run([NODE, "--input-type=module", "-e", script, td, json.dumps(sizes)],
                                  capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr[-400:])
        timings = json.loads(proc.stdout)
        # Linear is about 16x over 4 doublings; a scan that retried from every whitespace position would be
        # quadratic (about 256x).
        self.assertLess(timings[-1] / max(timings[0], 1), 48, timings)

    def test_dispatch_terminal_fires_after_a_slash_start_in_the_same_turn(self):  # O4
        events = slash_records() + self._call(DS, "t1")
        self.assertEqual(self.stop(events, NO_QUESTION), {"systemMessage": DISPATCH_TERMINAL_MESSAGE})
        blocked = self.stop(events, NO_QUESTION, block=True)
        self.assertEqual((blocked.get("decision"), blocked.get("reason")), ("block", DISPATCH_TERMINAL_MESSAGE))

    def test_dispatch_terminal_ignores_a_slash_start_from_an_earlier_turn(self):  # O4 turn rule (C16 item 8)
        events = slash_records() + self._call(DS, "t1") + [
            ev_text("Spec Review gate: approve the spec or ask for changes?"),
            user_prompt("Separate topic: workflow or sub-agents for the docs audit? Just pick."),
        ] + self._call(DS, "t2")
        for block in (False, True):
            with self.subTest(block=block):
                self.assertEqual(self.stop(events, "Use parallel sub-agents.", block=block), {})


@unittest.skipIf(NODE is None, "node not available")
class TestPipelineInFlightReviewer(unittest.TestCase):
    """C6: inFlightReviewer for the pipeline - background_tasks agent_type equals X or agentic-sdlc:X."""

    run_guard = TestFlowStepGuard.run_guard

    def ids(self, events, **kw):
        return _reminder_ids(self.run_guard(events, **kw))

    @staticmethod
    def _events():
        """Pipeline with every step satisfied; the auditor is a launch receipt with no result yet."""
        events = with_results([skill(PIPE), skill(DS), workflow("agentic-sdlc:spec-plan-draft"),
                               bash("py -3 -m unittest tests.test_app"), edit("src/app.py"),
                               agent("agentic-sdlc:security-reviewer")])
        events.append(tool_with_id("Agent", {"subagent_type": "agentic-sdlc:implementation-auditor",
                                             "prompt": "do the audit"}, AUDITOR_ID))
        events.append(launch_receipt(AUDITOR_ID, include_tool_result=False))
        return events + [ev_text("Done.")]

    def test_pending_auditor_without_in_flight_task_lists_review_result(self):
        self.assertEqual(self.ids(self._events()), ["review-result"])

    def test_in_flight_auditor_clears_review_result(self):
        for agent_type in ("agentic-sdlc:implementation-auditor", "implementation-auditor"):
            with self.subTest(agent_type=agent_type):
                tasks = [{"type": "subagent", "agent_type": agent_type}]
                self.assertEqual(self.ids(self._events(), background_tasks=tasks), [])

    def test_in_flight_lookalike_does_not_clear_review_result(self):
        for agent_type in ("agentic-sdlc:implementation-auditor-extra", "general-purpose implementation-auditor"):
            with self.subTest(agent_type=agent_type):
                tasks = [{"type": "subagent", "agent_type": agent_type}]
                self.assertEqual(self.ids(self._events(), background_tasks=tasks), ["review-result"])


@unittest.skipIf(NODE is None, "node not available")
class TestContainsInFlightReviewer(unittest.TestCase):
    """C14: for a `contains` reviewer (the focused flows), in-flight matching stays a substring match.
    Green before and after C6 - it guards the unchanged behaviour."""

    run_guard = TestFlowStepGuard.run_guard

    def ids(self, events, **kw):
        return _reminder_ids(self.run_guard(events, **kw))

    @staticmethod
    def _events(flow):
        """`flow` satisfied, with the control reviewer a pending general-purpose agent whose prompt names
        implementation-auditor (no result yet)."""
        events = with_results([skill(flow), edit("src/app.py"), workflow("agentic-sdlc:spec-plan-draft"),
                               bash("python -m pytest -q"), agent("agentic-sdlc:security-reviewer")])
        events.append(tool_with_id("Agent", {"subagent_type": "general-purpose",
                                             "prompt": "run the implementation-auditor checklist"}, AUDITOR_ID))
        events.append(launch_receipt(AUDITOR_ID, include_tool_result=False))
        return events + [ev_text("Done.")]

    def test_substring_agent_type_clears_review_result(self):
        tasks = [{"type": "subagent", "agent_type": "general-purpose implementation-auditor"}]
        for flow in (RCF, FB):
            with self.subTest(flow=flow):
                self.assertEqual(self.ids(self._events(flow), background_tasks=tasks), [])

    def test_without_in_flight_task_review_result_is_listed(self):  # control for the case above
        for flow in (RCF, FB):
            with self.subTest(flow=flow):
                self.assertEqual(self.ids(self._events(flow)), ["review-result"])


# ---- C6 / O4 + C14: dispatch-terminal Stop check -----------------------------------------
# C14 scope, as these tests encode it:
#   - turn: everything after the last genuine user prompt record (type "user", content a string or
#     text blocks, not a tool_result); only tool_uses after it count. Not genuine: a record with
#     isMeta true, with origin.kind "task-notification", or whose string content starts with
#     "<task-notification>" (system-generated, amended C14);
#   - top-level: a record with no parent_tool_use_id that is not a sidechain record;
#   - question: the final assistant text contains an ASCII "?" anywhere; the final text is
#     last_assistant_message when it is a string, otherwise the transcript's last assistant text;
#   - precedence: when a missing-step finding fires too, only the missing-step output is emitted.
def user_prompt(text, *, blocks=False):
    """A genuine user prompt record: string content, or a list of text blocks (never a tool_result)."""
    content = [{"type": "text", "text": text}] if blocks else text
    return {"type": "user", "message": {"content": content}}


PROMPT = user_prompt("Use /agentic-sdlc-pipeline to add a greeting suffix to greeting.py.")
NO_QUESTION = "Mechanism: single session; the steps are tightly coupled."


@unittest.skipIf(NODE is None, "node not available")
class TestDispatchTerminalStop(unittest.TestCase):
    run_guard = TestFlowStepGuard.run_guard

    def stop(self, events, final_text, **kw):
        return self.run_guard(events + [ev_text(final_text)], last_assistant_message=final_text, **kw)

    @staticmethod
    def _ended_on_dispatch(dispatch=DS):
        return [PROMPT] + with_results([skill(PIPE), skill(dispatch)])

    def test_warns_when_turn_ends_on_dispatch_without_question(self):
        for dispatch in (DS, "dispatch-strategy"):
            with self.subTest(dispatch=dispatch):
                out = self.stop(self._ended_on_dispatch(dispatch),
                                "Mechanism: single session; the steps are tightly coupled.")
                self.assertEqual(out, {"systemMessage": DISPATCH_TERMINAL_MESSAGE})

    def test_blocks_under_block_flag(self):
        out = self.stop(self._ended_on_dispatch(), "Mechanism: single session; the steps are tightly coupled.",
                        block=True)
        self.assertEqual(out.get("decision"), "block")
        self.assertEqual(out.get("reason"), DISPATCH_TERMINAL_MESSAGE)

    def test_silent_when_another_tool_follows_dispatch(self):
        for follow in (workflow("agentic-sdlc:spec-plan-draft"), bash("python3 scripts/detect_context.py")):
            with self.subTest(follow=follow["message"]["content"][0]["name"]):
                events = with_results([skill(PIPE), skill(DS), follow])
                self.assertEqual(self.stop(events, "Mechanism: single session. Spec drafted.", block=True), {})

    def test_silent_when_final_text_asks_the_user_a_question(self):
        out = self.stop(self._ended_on_dispatch(), "Mechanism: single session. Should I draft the spec now?",
                        block=True)
        self.assertEqual(out, {})

    def test_silent_when_no_pipeline_flow_is_active(self):
        cases = {
            "dispatch alone": with_results([skill(DS)]),
            "feature-build flow": with_results([skill(FB), skill(DS)]),
        }
        for name, events in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.stop(events, "Mechanism: single session.", block=True), {})

    def test_silent_when_last_skill_is_a_lookalike(self):  # exactName dispatch-strategy
        out = self.stop(self._ended_on_dispatch("agentic-sdlc:dispatch-strategy-extra"),
                        "Mechanism: single session.", block=True)
        self.assertEqual(out, {})

    def test_silent_when_stop_hook_active(self):  # the existing loop guard still runs first
        out = self.stop(self._ended_on_dispatch(), "Mechanism: single session.", block=True, stop_active=True)
        self.assertEqual(out, {})

    # ---- C14 turn boundary ----
    def test_silent_when_a_later_user_prompt_opened_a_new_turn(self):  # C14
        # Turn 1 ended on the dispatch decision with a question; the user answered; turn 2 has no
        # tool_use at all. The dispatch call belongs to the earlier turn, so O4 stays silent.
        for blocks in (False, True):
            with self.subTest(prompt_content="text blocks" if blocks else "string"):
                events = with_results([skill(PIPE), skill(DS)]) + [
                    ev_text("Mechanism: single session. Should I draft the spec now?"),
                    user_prompt("Before that, explain the mechanism choice.", blocks=blocks),
                ]
                out = self.stop(events, "Single session because the steps are tightly coupled.", block=True)
                self.assertEqual(out, {})

    def test_warns_when_dispatch_comes_after_the_last_user_prompt(self):  # C14
        events = [user_prompt("What does greeting.py do?"), ev_text("It builds greetings."),
                  PROMPT] + with_results([skill(PIPE), skill(DS)])
        self.assertEqual(self.stop(events, NO_QUESTION), {"systemMessage": DISPATCH_TERMINAL_MESSAGE})
        blocked = self.stop(events, NO_QUESTION, block=True)
        self.assertEqual((blocked.get("decision"), blocked.get("reason")), ("block", DISPATCH_TERMINAL_MESSAGE))

    def test_tool_results_do_not_open_a_new_turn(self):  # C14: a tool_result record is not a prompt
        # with_results already follows every call with a tool_result user record; an extra
        # is_error=false result after the dispatch call must not hide it either.
        events = self._ended_on_dispatch() + [tool_result("toolu_001", False)]
        self.assertEqual(self.stop(events, NO_QUESTION), {"systemMessage": DISPATCH_TERMINAL_MESSAGE})

    # ---- C14 top-level ----
    def test_sidechain_or_child_tool_use_after_dispatch_does_not_count(self):  # C14
        sidechain = ev_tool("Bash", {"command": "python3 scripts/detect_context.py"})
        sidechain["isSidechain"] = True
        child = ev_tool("Read", {"file_path": "greeting.py"})
        child["parent_tool_use_id"] = "toolu_agent_1"
        for name, record in (("sidechain", sidechain), ("parent_tool_use_id", child)):
            with self.subTest(record=name):
                out = self.stop(self._ended_on_dispatch() + [record], NO_QUESTION)
                self.assertEqual(out, {"systemMessage": DISPATCH_TERMINAL_MESSAGE})

    def test_sidechain_dispatch_after_a_top_level_tool_does_not_count(self):  # C14
        # The last TOP-LEVEL tool_use is the Workflow call; a sub-agent's later dispatch-strategy call
        # is not the main loop ending on the decision.
        nested = ev_tool("Skill", {"skill": DS})
        nested["isSidechain"] = True
        events = [PROMPT] + with_results([skill(PIPE), skill(DS), workflow("agentic-sdlc:spec-plan-draft")]) + [nested]
        self.assertEqual(self.stop(events, NO_QUESTION, block=True), {})

    # ---- C14 question rule and final-text source ----
    def test_question_mark_anywhere_counts(self):  # C14
        out = self.stop(self._ended_on_dispatch(),
                        "Mechanism: single session (is that fine with you?) - the spec comes next.", block=True)
        self.assertEqual(out, {})

    def test_last_assistant_message_wins_over_transcript_text(self):  # C14: mirrors completion-claim-guard
        events = self._ended_on_dispatch()
        # Field without "?", transcript with "?": the field decides -> warn.
        warn = self.run_guard(events + [ev_text("Should I draft the spec now?")],
                              last_assistant_message=NO_QUESTION)
        self.assertEqual(warn, {"systemMessage": DISPATCH_TERMINAL_MESSAGE})
        # Field with "?", transcript without: the field decides -> silent.
        silent = self.run_guard(events + [ev_text(NO_QUESTION)],
                                last_assistant_message="Should I draft the spec now?", block=True)
        self.assertEqual(silent, {})

    def test_transcript_text_used_when_field_absent(self):  # C14
        events = self._ended_on_dispatch()
        self.assertEqual(self.run_guard(events + [ev_text(NO_QUESTION)]),
                         {"systemMessage": DISPATCH_TERMINAL_MESSAGE})
        self.assertEqual(self.run_guard(events + [ev_text("Should I draft the spec now?")], block=True), {})

    # ---- C14 precedence ----
    def test_missing_step_output_wins_over_dispatch_terminal(self):  # C14
        events = [PROMPT] + with_results([skill(PIPE), edit("src/app.py"), skill(DS)])
        warn = self.stop(events, NO_QUESTION)
        self.assertEqual(warn, {"systemMessage": "flow-step-guard: missing evidence for step(s): spec, plan, tests, "
                                                 "security, control"})
        blocked = self.stop(events, NO_QUESTION, block=True)
        self.assertEqual(blocked, {
            "decision": "block",
            "reason": "agentic-sdlc-pipeline: required step(s) [spec, plan, tests, security, control] "
                      + FLOW_STEP_BLOCK_TAIL,
            "systemMessage": "flow-step-guard: blocked - required flow steps lack evidence.",
        })

    def test_skill_body_meta_record_does_not_open_a_new_turn(self):  # C14 (amended)
        # Shape observed in a local Claude Code session transcript (2026-10-16): after a Skill tool_use
        # and its tool_result, a type "user" record with isMeta true, text content (the skill body) and
        # a sourceToolUseID. It is tool output, not the user speaking. Without this exclusion every real
        # dispatch-strategy call would be followed by a "new turn" and O4 could never fire.
        for name, content in (("text blocks", [{"type": "text", "text": "# dispatch-strategy\n\nPick the mechanism."}]),
                              ("string", "# dispatch-strategy\n\nPick the mechanism.")):
            with self.subTest(content=name):
                meta = {"type": "user", "isMeta": True, "sourceToolUseID": "toolu_001", "message": {"content": content}}
                out = self.stop(self._ended_on_dispatch() + [meta], NO_QUESTION)
                self.assertEqual(out, {"systemMessage": DISPATCH_TERMINAL_MESSAGE})

    def test_task_notification_record_does_not_open_a_new_turn(self):  # C14 (amended)
        # A background-task notification is system-generated: by origin.kind, or by string content that
        # starts with <task-notification> when no origin is recorded.
        cases = {
            "origin + string": task_notification("toolu_bg_1"),
            "origin + text blocks": task_notification("toolu_bg_1", as_blocks=True),
            "string prefix, no origin": task_notification("toolu_bg_1", origin=False),
        }
        for name, note in cases.items():
            with self.subTest(record=name):
                out = self.stop(self._ended_on_dispatch() + [note], NO_QUESTION)
                self.assertEqual(out, {"systemMessage": DISPATCH_TERMINAL_MESSAGE})

    # ---- C16 items 8-10 (fix round after the Phase 2 reviews; probes h1-h4) ----
    @staticmethod
    def _call(skill_name, tool_id, *, result=True):
        """A Skill call with an explicit id, followed by its non-error tool_result unless result=False."""
        call = [tool_with_id("Skill", {"skill": skill_name}, tool_id)]
        return call + [tool_result(tool_id, False)] if result else call

    def test_silent_when_the_pipeline_was_activated_in_an_earlier_turn(self):  # C16 item 8 (probe h4)
        # The pipeline ran in an earlier turn and stopped at its Spec Review gate. In a later turn the user
        # asks only for a mechanism decision; the router calls dispatch-strategy and answers. The pipeline
        # activation is not inside this turn, so O4 stays silent (a false negative, never a false block).
        earlier = [PROMPT] + self._call(PIPE, "t1") + self._call(DS, "t2") + [
            ev_text("Spec Review gate: approve docs/agentic-sdlc/specs/x.md or ask for changes?"),
            user_prompt("Separate topic: for the docs audit next week, workflow or sub-agents? Just pick."),
        ]
        answer = "Use parallel sub-agents: the audit slices are independent."
        for block in (False, True):
            with self.subTest(block=block):
                self.assertEqual(self.stop(earlier + self._call(DS, "t3"), answer, block=block), {})
        # Control: a pipeline activation inside the later turn still makes O4 fire.
        again = earlier + self._call(PIPE, "t3") + self._call(DS, "t4")
        self.assertEqual(self.stop(again, NO_QUESTION), {"systemMessage": DISPATCH_TERMINAL_MESSAGE})

    def test_errored_pipeline_call_in_the_current_turn_is_not_an_activation(self):  # C16 item 8
        # The earlier turn's successful activation does not carry over, and this turn's pipeline call
        # failed (receiptHasError), so no pipeline activation is inside the current turn.
        errored = [tool_with_id("Skill", {"skill": PIPE}, "t3"),
                   {"type": "user", "toolUseResult": {"error": "Unknown skill"},
                    "message": {"content": [{"type": "tool_result", "tool_use_id": "t3", "content": "result",
                                             "is_error": True}]}}]
        events = [PROMPT] + self._call(PIPE, "t1") + self._call(DS, "t2") + [
            ev_text("Spec Review gate: approve docs/agentic-sdlc/specs/x.md or ask for changes?"),
            user_prompt("Run it again for the farewell suffix."),
        ] + errored + self._call(DS, "t4")
        self.assertEqual(self.stop(events, NO_QUESTION, block=True), {})

    def test_non_top_level_user_prompt_does_not_open_a_new_turn(self):  # C16 item 9 (probe h1)
        # Only a top-level genuine prompt opens a turn: a sidechain user record (the older in-file
        # sub-agent transcript shape) or one carrying parent_tool_use_id is a sub-agent's prompt.
        sidechain = user_prompt("Analyse the repo context.")
        sidechain["isSidechain"] = True
        child = user_prompt("Analyse the repo context.", blocks=True)
        child["parent_tool_use_id"] = "toolu_agent_1"
        for name, record in (("sidechain", sidechain), ("parent_tool_use_id", child)):
            with self.subTest(record=name):
                out = self.stop(self._ended_on_dispatch() + [record], NO_QUESTION)
                self.assertEqual(out, {"systemMessage": DISPATCH_TERMINAL_MESSAGE})

    def test_compact_summary_record_does_not_open_a_new_turn(self):  # C16 item 9 (probe h3)
        summary = "This session is being continued from a previous conversation..."
        for name, content in (("string", summary), ("text blocks", [{"type": "text", "text": summary}])):
            with self.subTest(content=name):
                compact = {"type": "user", "isCompactSummary": True, "message": {"content": content}}
                out = self.stop(self._ended_on_dispatch() + [compact], NO_QUESTION, block=True)
                self.assertEqual((out.get("decision"), out.get("reason")), ("block", DISPATCH_TERMINAL_MESSAGE))

    def test_silent_without_the_field_until_text_follows_the_dispatch_result(self):  # C16 item 10 (probe h2)
        # No last_assistant_message and the transcript has not caught up: the last assistant text on disk
        # predates the dispatch call, so it is not the turn's final text.
        lagging = [PROMPT] + self._call(PIPE, "t1") + [ev_text("Picking the mechanism first.")] + self._call(DS, "t2")
        no_result = ([PROMPT] + self._call(PIPE, "t1") + [ev_text("Picking the mechanism first.")]
                     + self._call(DS, "t2", result=False))
        for name, events in (("result, no text after it", lagging), ("no result yet", no_result)):
            for block in (False, True):
                with self.subTest(case=name, block=block):
                    self.assertEqual(self.run_guard(events, block=block), {})
        # Control: once an assistant text record lands after the result, O4 reads it and fires.
        self.assertEqual(self.run_guard(lagging + [ev_text(NO_QUESTION)]),
                         {"systemMessage": DISPATCH_TERMINAL_MESSAGE})
        # Control: a string last_assistant_message is the final text itself; the caught-up guard is not used.
        self.assertEqual(self.run_guard(lagging, last_assistant_message=NO_QUESTION),
                         {"systemMessage": DISPATCH_TERMINAL_MESSAGE})

    def test_sidechain_text_after_the_dispatch_result_is_not_caught_up(self):  # C16 item 10 + C14 top-level
        # A sub-agent's assistant text is not the main loop's final message, so it does not show that the
        # transcript has caught up.
        side = ev_text("Sub-agent: repository context gathered.")
        side["isSidechain"] = True
        lagging = [PROMPT] + self._call(PIPE, "t1") + self._call(DS, "t2") + [side]
        self.assertEqual(self.run_guard(lagging, block=True), {})


# ---- C17 item 6: the real Claude Code error shape --------------------------------------------
# Shape observed in local Claude Code session files (2026-10-16; keys and types only, no content copied):
# an errored call's result is a type "user" record whose `toolUseResult` is a STRING and whose single
# tool_result block carries `is_error: true` and string content. A successful Skill result has an object
# toolUseResult ({commandName, success}) or none; a successful Agent result has an object toolUseResult
# and list content; neither success block carries an is_error key. The text below is synthetic.
ERROR_TEXT = "Error: synthetic tool failure"


def errored_result(tool_id, *, string_result=True, is_error=True):
    """A failed call's result record. The defaults are the real shape; string_result=False or
    is_error=None isolates one of the two C17 rules."""
    item = {"type": "tool_result", "tool_use_id": tool_id, "content": ERROR_TEXT}
    if is_error is not None:
        item["is_error"] = is_error
    rec = {"type": "user", "message": {"content": [item]}}
    if string_result:
        rec["toolUseResult"] = ERROR_TEXT
    return rec


def skill_success(tool_id, name, *, with_tool_use_result=True):
    """A successful Skill result in the real shape: string content, no is_error key, and an object
    toolUseResult or none."""
    rec = {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tool_id, "content": "Launching skill: " + name}]}}
    if with_tool_use_result:
        rec["toolUseResult"] = {"commandName": name, "success": True}
    return rec


def agent_success(tool_id):
    """A successful synchronous Agent result in the real shape: list content, no is_error key, object
    toolUseResult."""
    return {"type": "user", "toolUseResult": {"status": "completed", "isAsync": False},
            "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id,
                                     "content": [{"type": "text", "text": "No finding."}]}]}}


ERROR_SHAPES = {
    "real shape: string toolUseResult + is_error": {},
    "string toolUseResult alone": {"is_error": None},
    "every tool_result is_error alone": {"string_result": False},
}
SECURITY_CALL = {"subagent_type": "agentic-sdlc:security-reviewer", "prompt": "do the audit"}


@unittest.skipIf(NODE is None, "node not available")
class TestRealErrorShape(unittest.TestCase):
    """C17 item 6: a Skill or Agent call counts as errored when its toolUseResult is a string or when
    every correlated tool_result has is_error true, beside the object toolUseResult.error rule. A
    successful call and a call with no result still count."""

    run_step = TestFlowStepGuard.run_guard
    run_order = TestFlowOrderGuard.run_guard

    @staticmethod
    def _pipe_call(result):
        return [tool_with_id("Skill", {"skill": PIPE}, "t_pipe")] + ([result] if result else [])

    @staticmethod
    def _rest_of_run(*, security=True):
        """Every other pipeline Stop step, each call with a correlated non-error result."""
        calls = [workflow("agentic-sdlc:spec-plan-draft"), bash("py -3 -m unittest tests.test_app"),
                 edit("src/app.py"), bash("py -3 -m unittest tests.test_app")]
        if security:
            calls.append(agent("agentic-sdlc:security-reviewer"))
        return with_results(calls + [agent("agentic-sdlc:implementation-auditor")])

    def test_errored_pipeline_skill_call_does_not_activate_the_flow(self):  # (a)
        for name, shape in ERROR_SHAPES.items():
            with self.subTest(shape=name):
                events = self._pipe_call(errored_result("t_pipe", **shape))
                self.assertEqual(self.run_order("src/app.py", events, block=True), {})
                self.assertEqual(self.run_step(events + [edit("src/app.py"), ev_text("Edited.")], block=True), {})
                # O4: no pipeline activation inside the turn, so a turn ending on dispatch stays silent.
                o4 = [PROMPT] + events + [tool_with_id("Skill", {"skill": DS}, "t_ds"), skill_success("t_ds", DS),
                                          ev_text(NO_QUESTION)]
                self.assertEqual(self.run_step(o4, block=True, last_assistant_message=NO_QUESTION), {})

    def test_errored_only_dispatch_call_does_not_satisfy_dispatch(self):  # (b)
        for name, shape in ERROR_SHAPES.items():
            with self.subTest(shape=name):
                events = (self._pipe_call(skill_success("t_pipe", PIPE))
                          + [tool_with_id("Skill", {"skill": DS}, "t_ds"), errored_result("t_ds", **shape)]
                          + self._rest_of_run() + [ev_text("Done.")])
                out = self.run_step(events, block=True)
                self.assertEqual(out.get("decision"), "block", out)
                self.assertEqual(_block_ids(out), ["dispatch"])

    def test_errored_security_reviewer_does_not_satisfy_security(self):  # (c)
        for name, shape in ERROR_SHAPES.items():
            with self.subTest(shape=name):
                events = (self._pipe_call(skill_success("t_pipe", PIPE))
                          + [tool_with_id("Skill", {"skill": DS}, "t_ds"), skill_success("t_ds", DS)]
                          + self._rest_of_run(security=False)
                          + [tool_with_id("Agent", SECURITY_CALL, "t_sec"), errored_result("t_sec", **shape),
                             ev_text("Done.")])
                out = self.run_step(events, block=True)
                self.assertEqual(out.get("decision"), "block", out)
                self.assertEqual(_block_ids(out), ["security"])

    def test_successful_calls_still_count(self):  # (d)
        for with_tur in (True, False):
            with self.subTest(skill_tool_use_result="object" if with_tur else "none"):
                pipe = self._pipe_call(skill_success("t_pipe", PIPE, with_tool_use_result=with_tur))
                order = self.run_order("src/app.py", pipe, block=True)
                self.assertEqual(order["hookSpecificOutput"]["permissionDecision"], "deny")
                events = (pipe + [tool_with_id("Skill", {"skill": DS}, "t_ds"),
                                  skill_success("t_ds", DS, with_tool_use_result=with_tur)]
                          + self._rest_of_run(security=False)
                          + [tool_with_id("Agent", SECURITY_CALL, "t_sec"), agent_success("t_sec"),
                             ev_text("Done.")])
                self.assertEqual(self.run_step(events, block=True), {})

    def test_calls_without_a_result_still_count(self):  # (e)
        pipe = self._pipe_call(None)
        order = self.run_order("src/app.py", pipe, block=True)
        self.assertEqual(order["hookSpecificOutput"]["permissionDecision"], "deny")
        events = (pipe + [tool_with_id("Skill", {"skill": DS}, "t_ds")] + self._rest_of_run(security=False)
                  + [tool_with_id("Agent", SECURITY_CALL, "t_sec"), ev_text("Done.")])
        out = self.run_step(events, block=True)
        # Every block step counts; only the warn-level review-result step notes the missing reviewer result.
        self.assertNotEqual(out.get("decision"), "block", out)
        self.assertEqual(_reminder_ids(out), ["review-result"])


@unittest.skipIf(NODE is None, "node not available")
class TestParseTranscriptKeepsOnlyExactNameFields(unittest.TestCase):
    """C16 item 11: parseTranscript keeps `inputStr`, `input.skill` and `input.subagent_type` for each
    tool_use and drops the rest of the parsed `input` object, so a large Write body is not held twice."""

    def test_tool_entries_keep_only_the_exact_name_fields(self):
        big = "x" * 20000
        inputs = [
            ("Skill", {"skill": PIPE, "args": "route this feature-build work"}),
            ("Agent", {"subagent_type": "agentic-sdlc:security-reviewer", "prompt": "review the diff",
                       "description": "security review"}),
            ("Write", {"file_path": "src/app.py", "content": big}),
            ("Bash", {"command": "python -m pytest -q", "description": "run the tests"}),
            ("Skill", {"skill": {"not": "a string"}}),
        ]
        events = [user_prompt("go")] + [tool_with_id(name, inp, "t%d" % n) for n, (name, inp) in enumerate(inputs)]
        with tempfile.TemporaryDirectory() as td:
            tpath = Path(td) / "transcript.jsonl"
            tpath.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
            script = ("const m = await import(%s); const tr = m.parseTranscript(process.argv[1]);"
                      "process.stdout.write(JSON.stringify({tools: tr.tools.map((t) => ({name: t.name, id: t.id,"
                      " input: t.input, inputStr: t.inputStr})), edits: tr.edits, commands: tr.commands}));"
                      % json.dumps(FLOW_EVID.as_uri()))
            proc = subprocess.run([NODE, "--input-type=module", "-e", script, str(tpath)], capture_output=True,
                                  text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        got = json.loads(proc.stdout)
        self.assertEqual([t["input"] for t in got["tools"]], [
            {"skill": PIPE},
            {"subagent_type": "agentic-sdlc:security-reviewer"},
            {},
            {},
            {},
        ])
        # The serialized input is unchanged, so `contains` items still match anywhere in it.
        self.assertEqual([t["inputStr"] for t in got["tools"]],
                         [json.dumps(inp, separators=(",", ":")) for _, inp in inputs])
        self.assertEqual([t["id"] for t in got["tools"]], ["t0", "t1", "t2", "t3", "t4"])
        self.assertEqual(got["edits"], ["src/app.py"])
        self.assertEqual(got["commands"], ["python -m pytest -q"])


if __name__ == "__main__":
    unittest.main()
