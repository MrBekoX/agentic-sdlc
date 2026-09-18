"""Offline strict flow evidence (publication-readiness Tasks 25 and 26; AC43, AC44).

The codex-strict-*.jsonl fixtures are SYNTHETIC rollouts, not native runs. Every record reuses the
record structure pinned by the native Codex 0.154.0 carriers in
tests/fixtures/transcripts/codex-0.154.0-native-tool-carriers.jsonl: custom_tool_call apply_patch with
an 'Exit code: 0 / Success. Updated the following files:' custom_tool_call_output, and function_call
exec_command with a string cmd and a 'Process exited with code N / Output:' function_call_output. They
hold relative paths only and no user or host identifiers.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_codex_flow_step_guard import _VALID_PLAN, _VALID_SPEC

REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
GIT = shutil.which("git")
FIXTURES = REPO / "tests" / "fixtures" / "transcripts"
ROLLOUT = REPO / "hooks" / "codex-rollout.mjs"
EVIDENCE = REPO / "hooks" / "codex-flow-evidence.mjs"
SCRIPT = REPO / "scripts" / "strict_flow_evidence.py"
MARKER = "<!-- agentic-sdlc:gate:completion-claim:verified -->"
CLAIM = "All tests passing, done and verified."
ERROR_LINES = ["strict_evidence=missing", "strict_completion=unsatisfied", "strict_branch=unknown"]
INSTALLED = "/home/u/.codex/plugins/cache/m/superpowers/1.0.0/skills/{skill}/SKILL.md"
NAMES = ("verified-green", "green-only", "fail-open", "no-runner", "duplicate-call", "lost-output", "quoted-marker")
EDIT_TARGETS = ["docs/agentic-sdlc/plans/strict-demo.md", "docs/agentic-sdlc/specs/strict-demo.md", "src/app.py"]
QUOTED_MARKER_FINAL = "All tests passing, done and verified."


def _fixture(name):
    return FIXTURES / f"codex-strict-{name}.jsonl"


def _read_all(path):
    """readRolloutSignals, readRolloutRuns and readRollout over one rollout, plus GATE_MARKER."""
    script = ("import * as m from %s; const p = process.argv[1];"
              "process.stdout.write(JSON.stringify({signals: m.readRolloutSignals(p), runs: m.readRolloutRuns(p),"
              " rollout: m.readRollout(p), marker: m.GATE_MARKER}));" % json.dumps(ROLLOUT.as_uri()))
    result = subprocess.run([NODE, "--input-type=module", "-e", script, str(path)],
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@unittest.skipIf(NODE is None, "node not available")
class TestCodexStrictFixtures(unittest.TestCase):
    def test_codex_strict_fixture_shapes(self):  # AC43, AC44
        got = {name: _read_all(_fixture(name)) for name in NAMES}
        marker = got["verified-green"]["marker"]

        def runs(name, command=None):
            return [r for r in got[name]["runs"]["runs"] if command is None or r["command"] == command]

        for name, data in got.items():
            with self.subTest(fixture=name):
                self.assertTrue(data["signals"]["readable"] and data["runs"]["readable"])
                self.assertEqual(sorted(set(data["signals"]["editTargets"])), EDIT_TARGETS)

        green = runs("verified-green", "pytest")
        self.assertEqual([(r["callEvents"], r["outputRecords"], r["exitCode"]) for r in green], [(1, 1, 1), (1, 1, 0)])
        self.assertLess(green[0]["seq"], green[1]["seq"])
        self.assertEqual([(r["command"], r["exitCode"]) for r in runs("green-only")], [("pytest", 0)])
        self.assertEqual([(r["outputRecords"], r["exitCode"]) for r in runs("fail-open", "pytest")], [(0, None)])
        self.assertEqual([(r["command"], r["exitCode"]) for r in runs("no-runner")], [("echo pytest", 0)])
        self.assertEqual([(r["callEvents"], r["exitCode"]) for r in runs("duplicate-call", "pytest")], [(1, 1), (2, 0)])
        self.assertEqual([(r["outputRecords"], r["exitCode"]) for r in runs("lost-output", "pytest")], [(1, 1), (0, None)])
        others = [r for r in runs("lost-output") if r["command"] != "pytest"]
        self.assertEqual([(r["outputRecords"], r["exitCode"]) for r in others], [(1, 0)])

        # quoted-marker: no RED run, one green pytest run, a claim-only final message, marker in tool output only
        quoted = got["quoted-marker"]
        self.assertEqual([r["exitCode"] for r in runs("quoted-marker")], [0, 0])
        self.assertEqual(len(runs("quoted-marker", "pytest")), 1)
        self.assertEqual((quoted["rollout"]["finalMessage"], quoted["rollout"]["gateMarkerPresent"]),
                         (QUOTED_MARKER_FINAL, False))
        records = [json.loads(line) for line in _fixture("quoted-marker").read_text(encoding="utf-8").splitlines() if line]
        carriers = [r for r in records if marker in json.dumps(r, ensure_ascii=False)]
        self.assertEqual(len(carriers), 1)
        self.assertEqual(carriers[0]["payload"]["type"], "function_call_output")
        self.assertIn(marker, carriers[0]["payload"]["output"])
        for name in NAMES:
            if name != "quoted-marker":
                with self.subTest(no_marker=name):
                    self.assertNotIn(marker, _fixture(name).read_text(encoding="utf-8"))
        self.assertEqual(sorted(p.name for p in FIXTURES.glob("codex-strict-*")),
                         sorted(_fixture(name).name for name in NAMES))


# ---- synthetic record builders (the same record structure as the codex-strict-* fixtures) ----
def _records(name):
    return [json.loads(line) for line in _fixture(name).read_text(encoding="utf-8").splitlines() if line]


def _patch_pair(call_id, path):
    return [{"type": "response_item", "payload": {"type": "custom_tool_call", "status": "completed", "call_id": call_id,
             "name": "apply_patch", "input": f"*** Begin Patch\n*** Add File: {path}\n+x\n*** End Patch\n"}},
            {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": call_id,
             "output": f"Exit code: 0\nWall time: 0.2 seconds\nOutput:\nSuccess. Updated the following files:\nA {path}\n"}}]


def _exec_pair(call_id, cmd, code, body):
    return [{"type": "response_item", "payload": {"type": "function_call", "name": "exec_command",
             "arguments": json.dumps({"cmd": cmd}), "call_id": call_id}},
            {"type": "response_item", "payload": {"type": "function_call_output", "call_id": call_id,
             "output": f"Process exited with code {code}\nOutput:\n{body}\n"}}]


def _user(text):
    return {"type": "response_item", "payload": {"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": text}]}}


def _final(text):
    return {"type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": text}}


SPEC_WRITE = _patch_pair("call_spec01", "docs/agentic-sdlc/specs/strict-demo.md")
PLAN_WRITE = _patch_pair("call_plan01", "docs/agentic-sdlc/plans/strict-demo.md")
SRC_WRITE = _patch_pair("call_src001", "src/app.py")
NO_CLAIM = "Implemented src/app.py for strict-demo; the test output is recorded above."


# ---- AC43, AC44, AC50, AC51, AC119, AC120: scripts/strict_flow_evidence.py (Task 26) ----
@unittest.skipIf(NODE is None, "node not available")
class TestStrictFlowEvidenceCli(unittest.TestCase):
    def _dir(self):
        path = Path(tempfile.mkdtemp(prefix="strict-evidence-"))
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def _git(self, repo, *args):
        subprocess.run([GIT, *args], cwd=repo, check=True, capture_output=True)

    def _tree(self, branch=None, name="work"):
        """A cwd holding a valid strict-demo spec/plan pair; a git repository on `branch` when given."""
        work = self._dir() / name
        work.mkdir()
        if branch is not None:
            self._git(work, "init", "-b", "main")
            self._git(work, "-c", "user.email=slice-b@invalid", "-c", "user.name=slice-b",
                      "commit", "--allow-empty", "-m", "init")
            if branch != "main":
                self._git(work, "checkout", "-b", branch)
        for sub, template in (("specs", _VALID_SPEC), ("plans", _VALID_PLAN)):
            target = work / "docs" / "agentic-sdlc" / sub
            target.mkdir(parents=True)
            (target / "strict-demo.md").write_text(template.format(work_id="strict-demo", ac_id="AC1"), encoding="utf-8")
        return work

    def _write(self, records, name="rollout.jsonl"):
        path = self._dir() / name
        path.write_bytes(("\n".join(json.dumps(r) for r in records) + "\n").encode("utf-8"))
        return path

    def _run(self, rollout, cwd, env=None):
        full = dict(os.environ)
        for key in ("AGENTIC_FLOW_STRICT_EVIDENCE", "AGENTIC_FLOW_GATE_BLOCK"):
            full.pop(key, None)
        full["GIT_CEILING_DIRECTORIES"] = str(Path(cwd).parent)
        full["CODEX_HOME"] = "/home/u/.codex"  # the home of INSTALLED, never the real Codex home (D25 model (3))
        if env:
            full.update(env)
        proc = subprocess.run([sys.executable, str(SCRIPT), "--rollout", str(rollout), "--cwd", str(cwd)],
                              capture_output=True, text=True, encoding="utf-8", env=full, timeout=300)
        lines = proc.stdout.splitlines()
        values = dict(line.split("=", 1) for line in lines if "=" in line)
        return proc.returncode, lines, values, proc.stderr

    def _claimed(self, extra, final_text):
        return self._write(_records("verified-green")[:-1] + list(extra) + [_final(final_text)])

    # ---- RED ----
    def test_fixture_matrix_green_partial_partial_missing(self):  # AC43
        cwd = self._tree()
        for name, (evidence, code) in {"verified-green": ("green", 0), "green-only": ("partial", 1),
                                       "fail-open": ("partial", 1), "no-runner": ("missing", 1)}.items():
            with self.subTest(fixture=name):
                rc, _, values, _ = self._run(_fixture(name), cwd)
                self.assertEqual((values.get("strict_evidence"), values.get("strict_completion"), rc),
                                 (evidence, "n/a", code))

    def test_duplicate_call_lost_output_quoted_marker_never_green_or_satisfied(self):  # AC44
        cwd = self._tree()
        rc, _, values, _ = self._run(_fixture("verified-green"), cwd)  # control: this cwd can yield green
        self.assertEqual((values.get("strict_evidence"), rc), ("green", 0))
        for name, (evidence, completion) in {"duplicate-call": ("partial", "n/a"), "lost-output": ("partial", "n/a"),
                                             "quoted-marker": ("partial", "unsatisfied")}.items():
            with self.subTest(fixture=name):
                rc, _, values, _ = self._run(_fixture(name), cwd)
                self.assertNotEqual(values.get("strict_evidence"), "green")
                self.assertNotEqual(values.get("strict_completion"), "satisfied")
                self.assertEqual((values.get("strict_evidence"), values.get("strict_completion"), rc), (evidence, completion, 1))
        # control: the marker in the FINAL message satisfies completion, so 'unsatisfied' came from its position
        records = _records("quoted-marker")
        records[-1]["payload"]["last_agent_message"] += " " + MARKER
        rc, _, values, _ = self._run(self._write(records), cwd)
        self.assertEqual((values.get("strict_completion"), rc), ("satisfied", 1))

    def test_error_paths_missing_unsatisfied_unknown_nonzero(self):  # AC119
        cwd = self._tree()
        scratch = self._dir()
        over = scratch / "over.jsonl"
        over.write_bytes(b"x" * (8 * 1024 * 1024 + 1))
        malformed = scratch / "malformed.jsonl"
        malformed.write_bytes(b'{"type": "event_msg", "payload": {}}\nnot json\n')
        cases = {"nonexistent": (scratch / "missing.jsonl", cwd), "directory": (scratch, cwd), "over-ceiling": (over, cwd),
                 "malformed": (malformed, cwd), "nonexistent-cwd": (_fixture("verified-green"), scratch / "no-such-dir")}
        for name, (rollout, where) in cases.items():
            with self.subTest(case=name):
                rc, lines, _, stderr = self._run(rollout, where)
                self.assertEqual((lines, rc), (ERROR_LINES, 2))
                self.assertRegex(stderr.strip(), r"^[a-z_]+$")

    def test_rollout_exactly_at_ceiling_is_evaluated(self):  # AC119 boundary
        prefix, suffix = b'{"type": "event_msg", "payload": {"type": "note", "pad": "', b'"}}\n'
        path = self._dir() / "ceiling.jsonl"
        path.write_bytes(prefix + b"x" * (8 * 1024 * 1024 - len(prefix) - len(suffix)) + suffix)
        self.assertEqual(path.stat().st_size, 8388608)
        rc, _, values, _ = self._run(path, self._tree())
        self.assertEqual((values.get("strict_branch"), rc), ("ok", 1))

    def test_raw_unicode_line_separators_inside_strings_are_not_malformed(self):  # plan Task 26 preflight
        # Mutation: splitting records with str.splitlines(), which also breaks on U+2028, U+2029 and U+0085
        # that JSON may carry raw inside a string (the Node readers split on \r?\n only).
        cwd = self._tree()
        _, want_lines, _, _ = self._run(_fixture("green-only"), cwd)
        note = {"type": "event_msg", "payload": {"type": "note", "text": "a\u2028b\u2029c\u0085d"}}
        path = self._dir() / "separators.jsonl"
        path.write_bytes(("\n".join(json.dumps(r, ensure_ascii=False) for r in [note] + _records("green-only"))
                          + "\n").encode("utf-8"))
        rc, lines, _, stderr = self._run(path, cwd)
        self.assertEqual((lines, rc, stderr), (want_lines, 1, ""))

    def test_no_active_flow_no_source_edit_missing_na_ok_exit1(self):  # AC119
        rollout = self._write(_exec_pair("call_ls0001", "ls", 0, "README.md") + [_final("Listed the files.")])
        rc, lines, _, _ = self._run(rollout, self._tree())
        self.assertEqual((lines, rc), (["strict_evidence=missing", "strict_completion=n/a", "strict_branch=ok"], 1))

    @unittest.skipIf(GIT is None, "git not available")
    def test_strict_branch_precedence_and_report_only(self):  # AC120
        flow_edit = _fixture("verified-green")
        flow_only = self._write(SPEC_WRITE + PLAN_WRITE + [_final(NO_CLAIM)])
        edit_only = self._write(SRC_WRITE + [_final(NO_CLAIM)])
        main, feature, plain = self._tree("main"), self._tree("feature/x"), self._tree()
        for label, rollout, cwd, branch in (("flow+edit main", flow_edit, main, "protected"),
                                            ("flow+edit feature", flow_edit, feature, "ok"),
                                            ("flow+edit non-git", flow_edit, plain, "unknown"),
                                            ("flow only main", flow_only, main, "ok"),
                                            ("edit only main", edit_only, main, "protected")):
            with self.subTest(case=label):
                rc, _, values, _ = self._run(rollout, cwd)
                self.assertEqual(values.get("strict_branch"), branch)
                ref_rc, _, ref, _ = self._run(rollout, feature)
                self.assertEqual((values.get("strict_evidence"), values.get("strict_completion"), rc),
                                 (ref.get("strict_evidence"), ref.get("strict_completion"), ref_rc))

    @unittest.skipIf(GIT is None, "git not available")
    def test_fsmonitor_config_characterization_strict(self):  # S10 end-to-end (characterization)
        """Characterization only: a sentinel-writing core.fsmonitor leaves strict_branch=protected and never
        runs. The discriminating argv proof is test_flow_guards TestBranchStep
        test_resolver_invokes_git_with_fixed_hardened_argv (the script reuses resolveBranchState)."""
        plain, configured = self._tree("main"), self._tree("main")
        sentinel = configured.parent / "fsmonitor-sentinel"
        writer = configured.parent / "fsmonitor.sh"
        writer.write_text(f"#!/bin/sh\ntouch '{sentinel.as_posix()}'\n", encoding="utf-8")
        writer.chmod(0o755)
        self._git(configured, "config", "core.fsmonitor", writer.as_posix())
        _, configured_lines, values, _ = self._run(_fixture("verified-green"), configured)
        _, plain_lines, _, _ = self._run(_fixture("verified-green"), plain)
        self.assertEqual(values.get("strict_branch"), "protected")
        self.assertEqual(configured_lines, plain_lines)
        self.assertFalse(sentinel.exists())

    def test_superpowers_owned_claim_satisfied_by_marker_or_verification(self):  # AC50 strict half
        cwd = self._tree()
        owned = [_user("Use superpowers:brainstorming"),
                 *_exec_pair("call_read01", "cat " + INSTALLED.format(skill="brainstorming"), 0, "---")]
        verified = owned + _exec_pair("call_read02", "cat " + INSTALLED.format(skill="verification-before-completion"), 0, "---")
        for label, extra, final_text, completion, code in (("marker", owned, CLAIM + " " + MARKER, "satisfied", 0),
                                                           ("verification", verified, CLAIM, "satisfied", 0),
                                                           ("neither", owned, CLAIM, "unsatisfied", 1)):
            with self.subTest(case=label):
                rc, _, values, _ = self._run(self._claimed(extra, final_text), cwd)
                self.assertEqual((values.get("strict_evidence"), values.get("strict_completion"), rc), ("green", completion, code))

    def test_unanchored_verification_read_leaves_claim_unsatisfied(self):  # D25 model (3)
        # Mutation: accepting a verification read outside the Codex home plugin cache as a delivery.
        cwd = self._tree()
        owned = [_user("Use superpowers:brainstorming"),
                 *_exec_pair("call_read01", "cat " + INSTALLED.format(skill="brainstorming"), 0, "---")]
        unanchored = "cat " + INSTALLED.format(skill="verification-before-completion").replace("/home/u/.codex", "/tmp")
        rc, _, values, _ = self._run(self._claimed(owned + _exec_pair("call_read02", unanchored, 0, "---"), CLAIM), cwd)
        self.assertEqual((values.get("strict_evidence"), values.get("strict_completion"), rc), ("green", "unsatisfied", 1))

    def test_ambiguous_foo_unsatisfied_nonzero_even_with_marker(self):  # AC51 strict half
        rc, _, values, _ = self._run(self._claimed([_user("Use superpowers:foo")], CLAIM + " " + MARKER), self._tree())
        self.assertEqual((values.get("strict_evidence"), values.get("strict_completion"), rc), ("green", "unsatisfied", 1))

    def test_negated_claim_is_na(self):
        rc, _, values, _ = self._run(self._claimed([], "All tests passing, but it's not done yet."), self._tree())
        self.assertEqual((values.get("strict_completion"), rc), ("n/a", 0))

    def test_flow_without_source_edit_green_exit0(self):
        rc, lines, _, _ = self._run(self._write(SPEC_WRITE + PLAN_WRITE + [_final(NO_CLAIM)]), self._tree())
        self.assertEqual((lines, rc), (["strict_evidence=green", "strict_completion=n/a", "strict_branch=ok"], 0))

    def test_traversal_write_target_partial_and_bare_target_no_flow(self):
        cwd = self._tree()
        traversal = self._claimed(_patch_pair("call_trav01", "docs/agentic-sdlc/specs/../../../etc/passwd"), NO_CLAIM)
        rc, _, values, _ = self._run(traversal, cwd)
        self.assertEqual((values.get("strict_evidence"), rc), ("partial", 1))
        bare = [r for r in _records("verified-green")[:-1]
                if "docs/agentic-sdlc" not in json.dumps(r)] + _patch_pair("call_bare01", "strict-demo.md") + [_final(NO_CLAIM)]
        rc, _, values, _ = self._run(self._write(bare), cwd)
        self.assertEqual((values.get("strict_evidence"), values.get("strict_completion"), rc), ("missing", "n/a", 1))

    def test_validator_unavailable_is_partial(self):
        env = dict(os.environ, PATH=str(Path(NODE).parent), AGENTIC_SDLC_PYTHON=str(self._dir() / "no-python"))
        script = ("const m = await import(%s);"
                  "process.stdout.write(JSON.stringify(m.deriveStrictEvidence(process.argv[1], process.argv[2])));"
                  % json.dumps(EVIDENCE.as_uri()))
        proc = subprocess.run([NODE, "--input-type=module", "-e", script, str(_fixture("verified-green")), str(self._tree())],
                              capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["evidence"], "partial")

    def test_node_missing_is_error_path(self):
        rc, lines, _, stderr = self._run(_fixture("verified-green"), self._tree(), env={"PATH": str(self._dir())})
        self.assertEqual((lines, rc, stderr.strip()), (ERROR_LINES, 2, "node_missing"))

    def test_node_behind_relative_path_entry_is_not_run(self):  # D25 model (5), SEC-7
        # Mutation: resolving node with shutil.which (a node planted in the process cwd would grade the rollout).
        from test_procedure_eval import plant_fake_program, relative_first_env
        planted = self._dir()
        program, sentinel = plant_fake_program(planted, "node")
        if program is None:
            self.skipTest("whoami.exe absent: no planted win32 program")
        env = relative_first_env()
        for key in ("AGENTIC_FLOW_STRICT_EVIDENCE", "AGENTIC_FLOW_GATE_BLOCK"):
            env.pop(key, None)
        tree = self._tree()
        env.update(GIT_CEILING_DIRECTORIES=str(tree.parent), CODEX_HOME="/home/u/.codex")
        proc = subprocess.run([sys.executable, str(SCRIPT), "--rollout", str(_fixture("verified-green")),
                               "--cwd", str(tree)], cwd=planted, env=env, capture_output=True, text=True,
                              encoding="utf-8", timeout=300)
        self.assertIn("strict_evidence=green", proc.stdout.splitlines(), proc.stderr)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertFalse(sentinel.exists(), "the planted node ran")

    def test_background_green_run_is_never_green(self):  # E3 gaming vector (D21)
        # Mutation: dropping the background-job check from isStrictlyAttributable prints green for each subTest.
        cwd = self._tree()
        red = _exec_pair("call_red001", "pytest", 1, "1 failed")
        for command in ("pytest & wait", "pytest \\&& wait"):
            with self.subTest(command=command):
                records = SPEC_WRITE + PLAN_WRITE + SRC_WRITE + red + _exec_pair("call_bg0001", command, 0, "1 failed")
                rc, _, values, _ = self._run(self._write(records + [_final(NO_CLAIM)]), cwd)
                self.assertEqual((values.get("strict_evidence"), values.get("strict_completion"), rc), ("partial", "n/a", 1))
        control = SPEC_WRITE + PLAN_WRITE + SRC_WRITE + red + _exec_pair("call_bg0001", "pytest", 0, "1 passed")
        rc, _, values, _ = self._run(self._write(control + [_final(NO_CLAIM)]), cwd)
        self.assertEqual((values.get("strict_evidence"), rc), ("green", 0))

    def test_grammar_forged_green_run_is_never_green(self):  # D23 safe grammar
        # Mutation: attributing a separator command outside the grammar, or judging only the last `||` operand.
        cwd = self._tree()
        red = _exec_pair("call_red001", "pytest", 1, "1 failed")
        for command in ("pytest; echo ${x:-; pytest #}", "pytest() { true; }; pytest", "pytest & wait || pytest",
                        "set -n; pytest"):
            with self.subTest(command=command):
                records = SPEC_WRITE + PLAN_WRITE + SRC_WRITE + red + _exec_pair("call_g0001", command, 0, "1 failed")
                rc, _, values, _ = self._run(self._write(records + [_final(NO_CLAIM)]), cwd)
                self.assertEqual((values.get("strict_evidence"), values.get("strict_completion"), rc), ("partial", "n/a", 1))
        control = SPEC_WRITE + PLAN_WRITE + SRC_WRITE + red + _exec_pair("call_g0001", "pytest -x || pytest --lf", 0, "1 passed")
        rc, _, values, _ = self._run(self._write(control + [_final(NO_CLAIM)]), cwd)
        self.assertEqual((values.get("strict_evidence"), rc), ("green", 0))

    def test_lexical_forged_runs_are_never_green(self):  # D27 (DP39)
        # Mutation: identifying the runner with the 5801cb9 text check (NAME+=, an escaped separator or an escaped
        # blank in an assignment value reads as a runner run), dropping the operand rule (a syntax error that runs
        # nothing counts as RED), or dropping the python -m module set (python -m jest counts as RED).
        cwd = self._tree()
        bs = chr(92)
        red = _exec_pair("call_red001", "pytest", 1, "1 failed")
        for command in ("pytest; pytest+=1", "echo " + bs + "; pytest", "pytest; X=a" + bs + " pytest"):
            with self.subTest(forged_green=command):
                records = SPEC_WRITE + PLAN_WRITE + SRC_WRITE + red + _exec_pair("call_l0001", command, 0, "1 failed")
                rc, _, values, _ = self._run(self._write(records + [_final(NO_CLAIM)]), cwd)
                self.assertEqual((values.get("strict_evidence"), values.get("strict_completion"), rc), ("partial", "n/a", 1))
        green = _exec_pair("call_green1", "pytest", 0, "1 passed")
        for command, code in (("pytest ||", 2), ("python -m jest", 1)):
            with self.subTest(forged_red=command):
                records = SPEC_WRITE + PLAN_WRITE + SRC_WRITE + _exec_pair("call_l0002", command, code, "x") + green
                rc, _, values, _ = self._run(self._write(records + [_final(NO_CLAIM)]), cwd)
                self.assertEqual((values.get("strict_evidence"), rc), ("partial", 1))
        control = SPEC_WRITE + PLAN_WRITE + SRC_WRITE + red + _exec_pair("call_l0003", "pytest; X=a pytest", 0, "1 passed")
        rc, _, values, _ = self._run(self._write(control + [_final(NO_CLAIM)]), cwd)
        self.assertEqual((values.get("strict_evidence"), rc), ("green", 0))

    def test_output_is_three_lines_without_input_bytes(self):
        cwd = self._tree(name="SENTINELCWDXYZ")
        rollout = self._write(_records("verified-green"), name="SENTINELROLLOUTXYZ.jsonl")
        rc, lines, _, stderr = self._run(rollout, cwd)
        self.assertEqual([line.split("=", 1)[0] for line in lines], ["strict_evidence", "strict_completion", "strict_branch"])
        for needle in ("SENTINELCWDXYZ", "SENTINELROLLOUTXYZ", "strict-demo", "pytest", "passed"):
            self.assertNotIn(needle, "\n".join(lines) + stderr)
        self.assertEqual((rc, stderr), (0, ""))


if __name__ == "__main__":
    unittest.main()
