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
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
STEP_GUARD = REPO / "hooks" / "flow-step-guard.mjs"
ORDER_GUARD = REPO / "hooks" / "flow-order-guard.mjs"
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


BR6_TABLE = REPO / "tests" / "fixtures" / "transcripts" / "br6-attribution-cases.json"

# Exact stdout captured on this tree before the branch and review-result steps existed (the 5801cb9
# flow engine), for AC33, AC34 and AC40.
PINNED_STEP_BLOCK_MAIN = (
    '{"decision":"block","reason":"root-cause-fix: required step(s) [spec, plan, tests, control] have no '
    'evidence this turn. Produce them before finishing - write+validate the spec/plan, run the tests, and '
    'invoke implementation-control. Evidence is re-derived, not taken from text.","systemMessage":'
    '"flow-step-guard: blocked - required flow steps lack evidence."}'
)
PINNED_ORDER_BLOCK_MAIN = (
    '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":'
    '"root-cause-fix: produce spec and plan before editing source (missing: spec, plan). Externalize them as '
    'validated artifacts first."},"systemMessage":"flow-order-guard: spec/plan required before source edits."}'
)
PINNED_PIPE_CORE_BLOCK = (
    '{"decision":"block","reason":"agentic-sdlc-pipeline: required step(s) [core] have no evidence this turn. '
    'Produce them before finishing - write+validate the spec/plan, run the tests, and invoke '
    'implementation-control. Evidence is re-derived, not taken from text.","systemMessage":'
    '"flow-step-guard: blocked - required flow steps lack evidence."}'
)
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


@unittest.skipIf(NODE is None, "node not available")
class TestFlowStepGuard(unittest.TestCase):
    def run_guard(self, events, *, block=False, stop_active=False, cwd=None, env_extra=None):
        with tempfile.TemporaryDirectory() as td:
            run_cwd = cwd or td
            tpath = Path(td) / "transcript.jsonl"
            tpath.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
            env = os.environ.copy()
            env.pop("AGENTIC_FLOW_STRICT_EVIDENCE", None)
            # A temp cwd must never resolve an enclosing repository's branch (the branch step).
            env["GIT_CEILING_DIRECTORIES"] = str(Path(run_cwd).resolve().parent)
            if block:
                env["AGENTIC_FLOW_GATE_BLOCK"] = "true"
            if env_extra:
                env.update(env_extra)
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

    def test_pipeline_blocks_missing_delegation_and_spec(self):
        out = self.run_guard([skill(PIPE), edit("src/app.py"), ev_text("Shipped.")], block=True)
        self.assertEqual(out.get("decision"), "block")
        self.assertTrue(any(k in out.get("reason", "").lower() for k in ("dispatch", "spec")))

    def test_pipeline_satisfied_is_silent(self):
        events = with_results([
            skill(PIPE),
            skill("agentic-sdlc:dispatch-strategy"),
            workflow("agentic-sdlc:spec-plan-draft"),
            skill("agentic-sdlc:feature-build"),  # core handoff
            edit("src/app.py"),
            bash("py -3 -m unittest tests.test_app"),
            skill("agentic-sdlc:security-audit"),
            skill("agentic-sdlc:implementation-control"),
            ev_text("Done."),
        ])
        self.assertEqual(self.run_guard(events, block=True), {})

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
        # core delegation through test-authoring: a core member that activates no second flow
        PIPE: [skill("agentic-sdlc:dispatch-strategy"), workflow("agentic-sdlc:spec-plan-draft"),
               skill("agentic-sdlc:test-authoring"), bash("py -3 -m unittest tests.test_app"),
               skill("agentic-sdlc:security-audit"), skill("agentic-sdlc:implementation-control")],
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
        events = with_results([skill(PIPE), skill(FB), edit("src/app.py"), skill("agentic-sdlc:dispatch-strategy"),
                               workflow("agentic-sdlc:spec-plan-draft"), bash("py -3 -m unittest tests.test_app"),
                               skill("agentic-sdlc:security-audit"), skill("agentic-sdlc:implementation-control"),
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
    def test_errored_control_dispatch_lists_review_result_once(self):  # AC37
        events = _review_transcript(FB, [(CONTROL_AGENT, "error"), (SECURITY_AGENT, "ok")])
        self.assertEqual(self.ids(events), ["review-result"])

    def test_missing_result_lists_review_result(self):  # AC37
        events = _review_transcript(FB, [(CONTROL_AGENT, "missing"), (SECURITY_AGENT, "ok")])
        self.assertEqual(self.ids(events), ["review-result"])

    def test_security_cleared_control_errored_listed_once(self):  # AC37
        events = _review_transcript(FB, [(SECURITY_SKILL, "ok"), (SECURITY_AGENT, "ok"),
                                         (CONTROL_SKILL, "error"), (CONTROL_AGENT, "error")])
        self.assertEqual(self.ids(events), ["review-result"])

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

    def test_block_flag_errored_control_no_block_decision(self):  # AC38
        errored = self.run_guard(_review_transcript(FB, [(CONTROL_AGENT, "error"), (SECURITY_AGENT, "ok")]), block=True)
        self.assertNotEqual(errored.get("decision"), "block")
        self.assertEqual(_reminder_ids(errored), ["review-result"])
        cleared = _review_transcript(FB, [(CONTROL_AGENT, "ok"), (SECURITY_AGENT, "ok")])
        self.assertEqual(self.run_guard(cleared, block=True), {})

    def test_existing_control_security_outcomes_unchanged(self):  # AC37
        def step_ids(dispatches):
            return [i for i in self.ids(_review_transcript(FB, dispatches)) if i in ("security", "control")]

        self.assertEqual(step_ids([(CONTROL_AGENT, "error"), (SECURITY_AGENT, "missing")]), [])
        self.assertEqual(step_ids([(SECURITY_AGENT, "error")]), ["control"])
        self.assertEqual(step_ids([(CONTROL_SKILL, "missing")]), ["security"])

    def test_pipeline_missing_core_reported_as_before(self):  # AC40
        events = [skill(PIPE), skill("agentic-sdlc:dispatch-strategy"), workflow("agentic-sdlc:spec-plan-draft"),
                  edit("src/app.py"), bash("py -3 -m unittest tests.test_app"), skill("agentic-sdlc:security-audit"),
                  skill("agentic-sdlc:implementation-control"), ev_text("Done.")]
        self.assertEqual(self.run_guard(events, block=True), json.loads(PINNED_PIPE_CORE_BLOCK))


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

    def test_safe_refactor_echoed_characterization_still_denies_claude(self):  # A2 Claude SHAPE gate (order)
        events = [skill(SR), bash("echo pytest")]  # a printer, not a real characterization run
        out = self.run_guard("src/app.py", events, block=True)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

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
