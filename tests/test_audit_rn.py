"""Regression tests for the runner and loop-engine findings of the f430715 bug audit (slice `rn`).

Audit: session-reports/2026-11-18-bug-audit-f430715.md, findings RN-1 to RN-10, SK-5 and SK-11.
Each test drives the real runner (scripts/sdlc_runner) through its in-process CLI on the harness of
tests/test_sdlc_engine.py, tests/test_sdlc_loop.py and tests/test_sdlc_flows.py (a temp plugin root
with the real flows, a temp git project, the guarded fake `pytest`), or runs an engine script under
`node` with stubbed agents. No model and no paid CLI runs.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"
for folder in (REPO / "scripts", TESTS):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from test_sdlc_engine import GIT, PLAN_BODY, SPEC_BODY, EngineCase, card_fields, card_value  # noqa: E402
from test_sdlc_loop import CLEAN, NO_SUBAGENTS, LoopCase, _issues  # noqa: E402
from test_sdlc_flows import FlowCase  # noqa: E402
from sdlc_runner import fingerprint, lock, textio  # noqa: E402
from sdlc_runner.textio import SdlcError  # noqa: E402

import resolve_work_package  # noqa: E402

NODE = shutil.which("node")
NO_NODE = "node not available - engine script check skipped (not passed)"
JS_ENGINE = REPO / "workflows" / "spec-plan-draft.js"
GROK_LEGACY = REPO / ".grok" / "workflows" / "spec-plan-draft.rhai"
ZCODE = REPO / "workflows" / "zcode" / "spec-plan-draft.dwf.ts"
# A plan that fails the strict plan gate: its task names no RED or failing test (task_missing_tdd).
NO_RED_PLAN = PLAN_BODY.replace("- RED: write the failing test for AC1 first.\n", "")


def pending_details(text) -> str:
    """Every `pending_detail=` line of a card, joined (the data section lists one per failing check)."""
    return "\n".join(line for line in text.splitlines() if line.startswith("pending_detail="))


AUDIT_REPORT = ("# Implementation audit\n\nAuditor: fresh sub-agent\nResolver: exit 0\n\n## Overall Status\n%s\n\n"
                "## Missing Steps\n\n## Risky Changes\n\n## Required Fixes Before Final\n%s\n\n## Final Decision\n%s\n")


# ---------------------------------------------------------------------------------------------
# RN-1: the security verdict line
# ---------------------------------------------------------------------------------------------

class TestRN1SecurityVerdict(EngineCase):
    REPORT = "evidence/demo.security.md"

    def test_rn1_a_fail_verdict_with_a_per_lens_pass_does_not_complete_security(self):
        self.start()
        self.advance_to("security")
        self.put(self.REPORT, "# Security review\n\nReviewer: fresh sub-agents\nVerdict: fail\n\n"
                              "| High | injection | src/app.py:2 | SQL built from input | parameterize |\n\n"
                              "## Lenses\n- secrets: Verdict: pass\n")
        code, text = self.next()
        self.assertEqual(card_fields(text)["step"], "security", text)
        entry = self.state()["steps"]["security"]
        self.assertNotEqual(entry["state"], "done")
        self.assertIsNotNone(entry.get("review_fp"), "the runner must count this report as a failed review")

    def test_rn1_two_verdict_lines_do_not_complete_security(self):
        self.start()
        self.advance_to("security")
        self.put(self.REPORT, "# Security review\n\nVerdict: pass\nVerdict: fail\n")
        code, text = self.next()
        self.assertEqual(card_fields(text)["step"], "security", text)
        self.assertIn("Verdict:", pending_details(text), text)

    def test_rn1_a_lowercase_fail_line_is_still_a_verdict_line(self):
        self.start()
        self.advance_to("security")
        self.put(self.REPORT, "# Security review\n\nverdict: fail\n\nVerdict: pass\n")
        code, text = self.next()
        self.assertEqual(card_fields(text)["step"], "security", text)

    def test_rn1_the_one_pass_line_still_completes_security(self):
        self.start()
        self.advance_to("security")
        self.put(self.REPORT, "# Security review\n\nReviewer: fresh sub-agents\n  Verdict: pass  \n\n"
                              "| None | - | - | - | No finding |\n")
        code, text = self.next()
        self.assertEqual(card_fields(text)["step"], "claim", text)


# ---------------------------------------------------------------------------------------------
# RN-2: a loop that stops with failing validator findings
# ---------------------------------------------------------------------------------------------

class TestRN2LoopStopWithFailingDrafts(LoopCase):
    def _assert_halt_then_resume_opens_a_new_visit(self, text, stop_reason):
        fields = card_fields(text)
        self.assertEqual((fields["state"], fields["step"]), ("halted", "draft"), text)
        reason = card_value(text, "halt_reason") or ""
        self.assertIn(stop_reason, reason)
        self.assertIn("task_missing_tdd", reason)
        code, out = self.sdlc("resume", "--slug", "demo")
        self.assertEqual(code, 0, out)
        code, text = self.next()
        fields = card_fields(text)
        self.assertEqual((fields["state"], fields["step"], fields["visit"]), ("do", "draft", "2/3"), text)
        role, round_text = self.role(text)
        self.assertEqual((role, round_text.split("/")[0]), ("author-spec", "0"), text)
        self.assertTrue(self.draft("visit-1/plan.r0.md").is_file())
        brief = self.draft("brief.md").read_text(encoding="utf-8")
        self.assertIn("task_missing_tdd", brief)
        # The new visit is a working path: clean drafts reach the review gate.
        self.clean_loop()
        code, text = self.next()
        self.assertEqual(card_fields(text)["state"], "wait-gate", text)

    def test_rn2_no_progress_stop_with_a_failing_plan_halts_and_resume_opens_a_new_visit(self):
        self.to_draft()
        self.authors(0, plan=NO_RED_PLAN)
        self.record("critic", 1, _issues())
        self.next()
        self.authors(1, plan=NO_RED_PLAN)
        self.record("critic", 2, _issues())  # the same issue keys: no progress
        code, text = self.next(expect=None)
        self.assertEqual(code, 3, text)
        self.assertEqual(self.state()["loop"]["stop_reason"], "no-progress")
        self._assert_halt_then_resume_opens_a_new_visit(text, "no-progress")

    def test_rn2_max_rounds_stop_with_a_failing_plan_halts_and_resume_opens_a_new_visit(self):
        self.to_draft()
        self.edit_state(lambda st: st["loop"].update(max_rounds=1))
        self.authors(0, plan=NO_RED_PLAN)
        self.record("critic", 1, _issues())
        code, text = self.next(expect=None)
        self.assertEqual(code, 3, text)
        self.assertEqual(self.state()["loop"]["stop_reason"], "max-rounds")
        self._assert_halt_then_resume_opens_a_new_visit(text, "max-rounds")


# ---------------------------------------------------------------------------------------------
# RN-3: assemble keeps the runner's engine and critic freshness
# ---------------------------------------------------------------------------------------------

class TestRN3AssembleKeepsRunnerRecord(LoopCase):
    def _inline_clean_round(self):
        self.to_draft(capabilities="workflow=no,subagent=no,team=no", overrides=NO_SUBAGENTS)
        self.assertEqual(self.state()["loop"]["engine"], "runner-loop-inline")
        self.authors(0)
        self.record("critic", 1, CLEAN)

    def _loop_json(self, **changes):
        claim = {"schema": "agentic-sdlc/loop@1", "engine": "runner-loop-inline", "mode": "spec+plan", "rounds": 1,
                 "stopReason": "clean", "critic": ["fresh"]}
        claim.update(changes)
        textio.write_json_atomic(self.draft("loop.json"), claim)

    def test_rn3_assemble_refuses_another_engine(self):
        self._inline_clean_round()
        self._loop_json(engine="claude-workflow")
        code, out = self.sdlc("ingest-draft", "--assemble")
        self.assertEqual(code, 4, out)
        self.assertIn("loop_json_invalid", out)
        self.assertEqual(self.state()["loop"]["engine"], "runner-loop-inline")
        self.assertFalse((self.pkg() / "spec" / "demo.review.json").exists())

    def test_rn3_assemble_never_upgrades_a_degraded_critic(self):
        self._inline_clean_round()
        self._loop_json()  # the right engine, but it calls the inline critic fresh
        code, out = self.sdlc("ingest-draft", "--assemble")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.state()["loop"]["critic"], ["degraded"])
        for name in ("spec", "plan"):
            self.assertEqual(textio.read_json(self.pkg() / name / "demo.review.json")["critic"], "degraded", name)


# ---------------------------------------------------------------------------------------------
# RN-4: malformed author decision points
# ---------------------------------------------------------------------------------------------

class TestRN4MalformedDecisionPoints(LoopCase):
    def _clean_loop_with_points(self, points):
        self.to_draft()
        self.record("author-spec", 0, SPEC_BODY)
        textio.write_json_atomic(self.draft("decisions.author-spec.r0.json"), points)
        self.next()
        self.record("author-plan", 0, PLAN_BODY)
        self.next()
        self.record("critic", 1, CLEAN)
        return self.next(expect=None)

    def test_rn4_a_non_string_option_is_dropped_not_fatal(self):
        code, text = self._clean_loop_with_points(
            [{"id": "DP1", "question": "CSV only?", "options": ["CSV", 2], "recommendation": "CSV"}])
        self.assertEqual(code, 0, text)
        self.assertEqual(card_fields(text)["state"], "wait-gate", text)
        points = textio.read_json(self.pkg() / "spec" / "demo.review.json")["decisionPoints"]
        self.assertEqual(points, [{"id": "DP1", "question": "CSV only?", "options": ["CSV"], "recommendation": "CSV"}])

    def test_rn4_a_point_with_a_non_string_id_is_skipped_not_a_crash(self):
        code, text = self._clean_loop_with_points(
            [{"id": ["DP1"], "question": "CSV only?", "options": ["CSV"], "recommendation": "CSV"},
             {"id": "DP2", "question": "  ", "options": [], "recommendation": "x"},
             {"id": "DP3", "question": "JSON too?", "options": [], "recommendation": 7},
             {"id": "DP4", "question": "Header row?", "options": ["yes", "no"], "recommendation": "yes"}])
        self.assertEqual(code, 0, text)
        self.assertEqual(card_fields(text)["state"], "wait-gate", text)
        points = textio.read_json(self.pkg() / "spec" / "demo.review.json")["decisionPoints"]
        self.assertEqual([p["id"] for p in points], ["DP4"])


# ---------------------------------------------------------------------------------------------
# RN-5 and RN-9: `sdlc external`
# ---------------------------------------------------------------------------------------------

class TestRN5ExternalDraftNeedsItsArtifacts(LoopCase):
    def test_rn5_external_draft_is_refused_while_the_spec_and_plan_are_absent(self):
        self.to_draft()
        self.write("notes/superpowers-plan.md", b"# A plan written by another plugin\n")
        argv = ("external", "draft", "--slug", "demo", "--owner", "superpowers:writing-plans",
                "--artifact", "notes/superpowers-plan.md", "--quote", "Use superpowers for the plan.")
        code, out = self.sdlc(*argv)
        self.assertEqual(code, 4, out)
        self.assertIn("external_artifacts_missing:", out)
        self.assertIn("spec/demo.md", out)
        self.assertIn("plan/demo.md", out)
        self.assertNotEqual(self.state()["steps"]["draft"]["state"], "done")
        # With the other plugin's spec and plan saved in the package, the gate reviews real bodies.
        self.put("spec/demo.md", SPEC_BODY)
        self.put("plan/demo.md", PLAN_BODY)
        code, out = self.sdlc(*argv)
        self.assertEqual(code, 0, out)
        code, text = self.next()
        self.assertEqual(card_fields(text)["state"], "wait-gate", text)
        self.approve(text)
        record = [r for r in self._approvals() if r.get("gate") == "review"][-1]
        self.assertNotIn(fingerprint.ABSENT, record["bodies"].values())

    def _approvals(self):
        from sdlc_runner import logs
        return logs.read(self.pkg() / "approvals.jsonl")


class TestRN9ExternalRefusalNamesTheAllowedSteps(EngineCase):
    def test_rn9_the_refusal_names_intent_and_draft(self):
        self.start()
        self.advance_to("draft")
        self.write("notes/x.md", b"# x\n")
        code, out = self.sdlc("external", "context", "--owner", "superpowers:brainstorming",
                              "--artifact", "notes/x.md", "--quote", "Use superpowers.")
        self.assertEqual(code, 4, out)
        self.assertIn("error=external_not_allowed:context (intent or draft only)", out)


# ---------------------------------------------------------------------------------------------
# RN-6: a commit with no content change; RN-7: detached HEAD; SK-5: the audit decision
# ---------------------------------------------------------------------------------------------

class TestRN6CommitWithoutContentChange(FlowCase):
    def test_rn6_committing_the_work_keeps_security_done(self):
        slug = "rn6"
        self.feature_to_security(slug)
        self.security_pass(slug)
        self.step(slug, step="audit")
        before = self.state(slug)
        # `card` between the commits: `next` with nothing changed counts toward the no-progress halt.
        self.git("add", "src", "tests")
        self.git("commit", "-q", "-m", "the work so far")
        code, text = self.card(slug)
        self.assertEqual(card_fields(text)["step"], "audit", text)
        self.git("commit", "-q", "--allow-empty", "-m", "nothing")
        code, text = self.next(slug)
        self.assertEqual(card_fields(text)["step"], "audit", text)
        st = self.state(slug)
        self.assertEqual(st["steps"]["security"]["state"], "done")
        self.assertEqual(st.get("fix_rounds", 0), before.get("fix_rounds", 0))
        # The twin: a real source change still reopens the security review.
        self.write("src/export.py", b"def export(rows):\n    return list(rows)\n")
        code, text = self.next(slug)
        self.assertEqual(card_fields(text)["step"], "security", text)


class TestRN7DetachedHead(FlowCase):
    def test_rn7_branch_ok_fails_on_a_detached_head(self):
        slug = "rn7"
        code, text = self.start(flow="feature", work_type="feature", runtime="codex", work_id=slug)
        text, fields = self.play(slug, text=text, stop="branch")
        self.git("checkout", "-q", "--detach")
        code, text = self.next(slug)
        fields = card_fields(text)
        self.assertEqual((fields["step"], fields["pending"]), ("branch", "branch_ok"), text)
        self.assertIn("detached", pending_details(text), text)
        self.git("switch", "-q", "-c", "work/" + slug)
        code, text = self.next(slug)
        self.assertEqual(card_fields(text)["step"], "implement", text)


class TestSK5AuditDecision(FlowCase):
    def _to_audit(self, slug):
        self.feature_to_security(slug)
        self.security_pass(slug)
        return self.step(slug, step="audit")

    def test_sk5_block_final_does_not_complete_the_implement_flow_audit(self):
        slug = "sk5"
        self._to_audit(slug)
        report = "evidence/%s.audit.md" % slug
        self.put(report, AUDIT_REPORT % ("PARTIAL", "- the security evidence is lost", "block-final: evidence lost"),
                 slug)
        code, text = self.next(slug)
        self.assertEqual(card_fields(text)["step"], "audit", text)
        self.assertIn("allow-final", pending_details(text), text)
        # allow-final mentioned elsewhere does not count; only the line under ## Final Decision does.
        self.put(report, AUDIT_REPORT % ("PARTIAL", "- fix it, then allow-final\nallow-final", "block-final"), slug)
        code, text = self.next(slug)
        self.assertEqual(card_fields(text)["step"], "audit", text)
        self.put(report, AUDIT_REPORT % ("PASS", "- none", "allow-final"), slug)
        code, text = self.next(slug)
        self.assertEqual(card_fields(text)["step"], "claim", text)

    def test_sk5_the_audit_only_flow_still_accepts_block_final(self):
        slug = "sk5-audit"
        code, text = self.start(flow="audit", work_type="refactor", runtime="codex", work_id=slug)
        text, fields = self.play(slug, text=text, stop="audit")
        self.put("evidence/%s.audit.md" % slug,
                 AUDIT_REPORT % ("FAIL", "- no failing run before the first edit", "block-final: no RED run"), slug)
        code, text = self.next(slug)
        self.assertEqual(card_fields(text)["step"], "claim", text)


class TestSK5AuditVerdictManifest(unittest.TestCase):
    def test_sk5_every_implement_flow_audit_needs_allow_final_and_under_needs_a_verdict(self):
        from sdlc_runner import manifest

        for flow_id in ("full", "feature", "bugfix", "refactor"):
            audit = [s for s in manifest.load_flow(REPO, flow_id)["steps"] if s["id"] == "audit"][0]
            report = [c for c in audit["done_when"] if c["check"] == "report"][0]
            with self.subTest(flow=flow_id):
                self.assertEqual((report.get("verdict"), report.get("under")), ("allow-final", "## Final Decision"))
        flow = json.loads((REPO / "flows" / "feature.json").read_text(encoding="utf-8"))
        audit = [s for s in flow["steps"] if s["id"] == "audit"][0]
        audit["done_when"][-1].pop("verdict")
        errors = manifest.validate_flow(flow, REPO, True)
        self.assertTrue(any(e.endswith("under: under names where the verdict is: it needs a verdict") for e in errors),
                        errors)


# ---------------------------------------------------------------------------------------------
# RN-8: the ZCode driver's slug rule
# ---------------------------------------------------------------------------------------------

class TestRN8ZcodeSlug(unittest.TestCase):
    def test_rn8_the_driver_slug_rule_is_the_resolvers(self):
        source = ZCODE.read_text(encoding="utf-8")
        match = re.search(r"if \(!/(.+?)/\.test\(slug\)\)", source)
        self.assertIsNotNone(match, "the driver's slug check moved")
        driver = re.compile(match.group(1))
        for slug in ("demo", "demo-", "a", "fix-1-", "x" * 64, "Demo", "-demo", "a/b", "", "x" * 65, "demo\n"):
            with self.subTest(slug=slug):
                self.assertEqual(bool(driver.fullmatch(slug)), bool(resolve_work_package.SLUG_RE.fullmatch(slug)))

    @unittest.skipUnless(NODE, NO_NODE)
    def test_rn8_the_driver_takes_a_trailing_hyphen_slug_to_the_runner(self):
        from test_zcode_driver import TS, NO_TS, run_driver
        if not TS:
            self.skipTest(NO_TS)
        with tempfile.TemporaryDirectory() as td:  # the runner's project is the driver's cwd: no package there
            payload = run_driver({"slug": "demo-", "pluginRoot": str(REPO), "python": sys.executable}, {}, cwd=td)
        self.assertNotIn("slug must be", payload.get("message", ""), payload)
        self.assertTrue(payload["calls"], payload)


# ---------------------------------------------------------------------------------------------
# RN-10: a lock whose holder died on this host
# ---------------------------------------------------------------------------------------------

class TestRN10DeadHolderLock(unittest.TestCase):
    def _hold(self, **fields):
        """A lock as a runner in this same PID space writes it (round 2: the dead-pid shortcut needs the
        lock's `space` to be this runner's)."""
        meta = {"host": lock._host_id(), "nonce": "n" * 32, "pid": os.getpid(), "ts": textio.now_iso()}
        if lock._pid_space() is not None:
            meta["space"] = lock._pid_space()
        meta.update(fields)
        self.path.write_bytes(json.dumps(meta, sort_keys=True).encode("utf-8"))

    def setUp(self):
        if lock._pid_space() is None:
            self.skipTest("this platform gives no PID space: the age rule decides")
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.path = Path(self._td.name) / ".lock"

    @staticmethod
    def _dead_pid():
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        return proc.pid

    def _acquire(self, timeout=0.5):
        held = lock.PackageLock(self.path)
        started = time.monotonic()
        held.acquire(timeout=timeout)
        elapsed = time.monotonic() - started
        held.release()
        return elapsed

    def test_rn10_a_fresh_lock_of_a_dead_pid_on_this_host_is_broken_at_once(self):
        self._hold(pid=self._dead_pid())
        self.assertLess(self._acquire(timeout=5), 2.0)

    def test_rn10_a_fresh_lock_whose_pid_now_names_another_process_is_broken_at_once(self):
        parent = os.getppid()
        if lock._process_start(parent) is None:
            self.skipTest("this platform gives no process start time")
        self._hold(pid=parent, start="linux:not-this-boot:1")
        self.assertLess(self._acquire(timeout=5), 2.0)

    def test_rn10_a_live_holder_on_this_host_still_blocks(self):
        parent = os.getppid()
        start = lock._process_start(parent)
        self._hold(pid=parent, **({"start": start} if start else {}))
        with self.assertRaises(SdlcError) as caught:
            self._acquire(timeout=0.3)
        self.assertTrue(caught.exception.message.startswith("locked:"), caught.exception.message)

    def test_rn10_another_hosts_fresh_lock_still_waits_for_the_age_rule(self):
        self._hold(host="0" * 16, pid=self._dead_pid())
        with self.assertRaises(SdlcError) as caught:
            self._acquire(timeout=0.3)
        self.assertTrue(caught.exception.message.startswith("locked:"), caught.exception.message)
        old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
        self._hold(host="0" * 16, pid=self._dead_pid(), ts=old)
        self.assertLess(self._acquire(timeout=5), 2.0)


class TestR2RN1LockPidSpace(unittest.TestCase):
    """Round 2: the RN-10 dead-pid shortcut must not break a live lock held from another PID space that
    shares the host name (WSL2 and Windows on /mnt/<drive>, a host-network container with a bind mount,
    two machines of the same name over NFS). Only a holder in this runner's own PID space is judged by
    its pid at once; any other keeps the age rule."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.path = Path(self._td.name) / ".lock"

    def _hold(self, **fields):
        meta = {"host": lock._host_id(), "nonce": "n" * 32, "pid": os.getpid(), "ts": textio.now_iso()}
        meta.update(fields)
        self.path.write_bytes(json.dumps(meta, sort_keys=True).encode("utf-8"))

    def _acquire(self, timeout):
        held = lock.PackageLock(self.path)
        held.acquire(timeout=timeout)
        held.release()

    def _assert_kept(self):
        with self.assertRaises(SdlcError) as caught:
            self._acquire(timeout=0.3)
        self.assertTrue(caught.exception.message.startswith("locked:"), caught.exception.message)

    def test_r2_rn1_a_fresh_lock_from_another_pid_space_is_kept_though_its_pid_is_dead_here(self):
        for space in ("win:29000000", "linux:another-boot:4026531836"):
            with self.subTest(space=space):
                self._hold(pid=TestRN10DeadHolderLock._dead_pid(), space=space)
                self._assert_kept()

    def test_r2_rn1_a_fresh_lock_that_names_no_pid_space_is_kept(self):
        # A runner that records no PID space (an older one, or a platform without one) may hold it
        # from the other side of WSL: its pid means nothing here.
        self._hold(pid=TestRN10DeadHolderLock._dead_pid())
        self._assert_kept()

    def test_r2_rn1_an_old_lock_from_another_pid_space_is_broken_by_its_age(self):
        old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
        self._hold(pid=os.getppid(), space="win:29000000", ts=old)  # that pid is alive here, by chance
        self._acquire(timeout=5)

    def test_r2_rn1_an_old_lock_naming_a_pid_space_is_broken_where_the_platform_gives_none(self):
        # macOS records no PID space: a lock that names one came from another PID space, so its age
        # frees it even though its pid happens to be alive here.
        old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
        with mock.patch.object(lock, "_pid_space", return_value=None):
            for space in ("win:29000000", "linux:another-boot:4026531836"):
                with self.subTest(space=space):
                    self._hold(pid=os.getppid(), space=space, ts=old)
                    self._acquire(timeout=5)

    def test_r2_rn1_an_old_live_lock_naming_no_space_is_kept_where_the_platform_gives_none(self):
        # Two runners of a platform without PID spaces: the old lock's live holder still holds it.
        old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
        with mock.patch.object(lock, "_pid_space", return_value=None):
            self._hold(pid=os.getppid(), ts=old)
            self._assert_kept()

    def test_r2_rn1_the_lock_records_this_runners_pid_space(self):
        space = lock._pid_space()
        with lock.PackageLock(self.path):
            meta = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(meta.get("space"), space)
        if sys.platform.startswith("linux") and os.path.exists("/proc/self/ns/pid"):
            self.assertRegex(space or "", r"^linux:[0-9a-f-]+:[0-9]+$")


# ---------------------------------------------------------------------------------------------
# R2-RN-2: a submodule (gitlink) in the change set fingerprints by its checked-out commit
# ---------------------------------------------------------------------------------------------

class TestR2RN2GitlinkFingerprint(EngineCase):
    def _lib_git(self, *args):
        proc = subprocess.run(
            [GIT, "-c", "core.hooksPath=" + str(self.tmp / "no-hooks"), "-c", "commit.gpgsign=false",
             "-c", "init.defaultBranch=main", *args],
            cwd=str(self.project / "vendor" / "lib"), stdin=subprocess.DEVNULL, capture_output=True,
            encoding="utf-8", errors="replace", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc

    def _sets(self, base):
        from sdlc_runner import manifest, runexec
        ctx = types.SimpleNamespace(project=self.project, pkg=self.tmp / "pkg", shared=manifest.load_shared(self.root),
                                    state={"git": {"repo": True}, "base_commit": base})
        return runexec.current_sets(ctx)

    def test_r2_rn2_moving_a_submodule_changes_the_source_fingerprint(self):
        lib = self.project / "vendor" / "lib"
        lib.mkdir(parents=True)
        (lib / "lib.py").write_text("VALUE = 1\n", encoding="utf-8")
        self._lib_git("init", "-q")
        self._lib_git("add", "-A")
        self._lib_git("commit", "-q", "-m", "one")
        self.git("add", "vendor/lib")  # an embedded repository: git records a gitlink
        self.git("commit", "-q", "-m", "vendor the lib")
        base = self.git("rev-parse", "HEAD").stdout.strip()
        (lib / "lib.py").write_text("VALUE = 2\n", encoding="utf-8")
        self._lib_git("commit", "-q", "-am", "two")
        moved = self._sets(base)
        self.assertIn("vendor/lib", moved["source"])
        self.assertEqual(self._sets(base)["source_fp"], moved["source_fp"])  # the same checkout is stable
        (lib / "lib.py").write_text("VALUE = 3\n", encoding="utf-8")
        self._lib_git("commit", "-q", "-am", "three")
        self.assertNotEqual(self._sets(base)["source_fp"], moved["source_fp"])
        # Recording the move in the superproject changes no member, so no step goes stale (RN-6).
        before = self._sets(base)["source_fp"]
        self.git("add", "vendor/lib")
        self.git("commit", "-q", "-m", "bump the lib")
        self.assertEqual(self._sets(base)["source_fp"], before)


# ---------------------------------------------------------------------------------------------
# SK-11: the smoke-depth canned plan passes the strict plan gate
# ---------------------------------------------------------------------------------------------

def _rhai_function_text(source, name):
    """The markdown a Rhai `fn <name>() { let md = "..."; md += "..."; ... md }` builds."""
    body = source.split("fn %s() {" % name, 1)[1].split("\n}", 1)[0]
    parts = re.findall(r'(?:let md =|md \+=) "((?:[^"\\]|\\.)*)";', body)
    return "".join(json.loads('"%s"' % part) for part in parts)


def _js_smoke(mode):
    src = JS_ENGINE.read_text(encoding="utf-8").replace("export const meta", "const meta", 1)
    args = {"mode": mode, "depth": "smoke", "context": {"scope": "the smoke eval"}}
    driver = ("async function __wf(args, agent) {\n" + src + "\n}\n"
              "__wf(%s, async () => { throw new Error('no agent at smoke depth') })"
              ".then((r) => process.stdout.write(JSON.stringify(r)))"
              ".catch((e) => { process.stdout.write(JSON.stringify({error: String(e)})); });\n" % json.dumps(args))
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "smoke.mjs"
        path.write_text(driver, encoding="utf-8", newline="\n")
        proc = subprocess.run([NODE, str(path)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    result = json.loads(proc.stdout or "{}")
    if "draftMarkdown" not in result:
        raise AssertionError("no smoke draft: %r %s" % (result, proc.stderr))
    return result["draftMarkdown"]


class TestSK11SmokePlanPassesStrictGate(unittest.TestCase):
    def _validate(self, spec_body, plan_body):
        """validate_artifacts.py --strict on the canned spec and plan, with the frontmatter a caller writes."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "spec").mkdir()
            (root / "plan").mkdir()
            spec = root / "spec" / "smoke.md"
            plan = root / "plan" / "smoke.md"
            spec.write_text("---\nwork_id: smoke\nstatus: draft\n---\n" + spec_body + "\n", encoding="utf-8")
            plan.write_text("---\nwork_id: smoke\nspec: ../spec/smoke.md\nbranch: feature/smoke\nstatus: draft\n---\n"
                            + plan_body + "\n", encoding="utf-8")
            out = []
            for argv in (["--mode", "spec", "--file", str(spec)],
                         ["--mode", "plan", "--file", str(plan), "--spec", str(spec)]):
                proc = subprocess.run([sys.executable, "-B", str(REPO / "scripts" / "validate_artifacts.py")] + argv
                                      + ["--strict"], capture_output=True, text=True, encoding="utf-8", timeout=60)
                out.append((proc.returncode, proc.stdout))
            return out

    @unittest.skipUnless(NODE, NO_NODE)
    def test_sk11_the_claude_engine_smoke_plan_passes_strict(self):
        results = self._validate(_js_smoke("spec"), _js_smoke("plan"))
        for code, stdout in results:
            self.assertEqual(code, 0, stdout)
            self.assertIn("artifacts_validation=passed", stdout)

    def test_sk11_the_grok_engine_smoke_plan_passes_strict(self):
        source = GROK_LEGACY.read_text(encoding="utf-8")
        spec, plan = _rhai_function_text(source, "smoke_spec"), _rhai_function_text(source, "smoke_plan")
        self.assertIn("## Task T1", plan)
        results = self._validate(spec, plan)
        for code, stdout in results:
            self.assertEqual(code, 0, stdout)
            self.assertIn("artifacts_validation=passed", stdout)


if __name__ == "__main__":
    unittest.main()
