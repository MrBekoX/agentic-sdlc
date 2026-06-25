"""AP2b - Codex flow-step guard (evidence-only Stop adapter). Covers AC1-AC32.

Reader-unit tests drive `hooks/codex-rollout.mjs:readRolloutSignals` via `node` over synthetic
rollout fixtures; derivation tests drive `hooks/codex-flow-evidence.mjs` (a real
`scripts/validate_artifacts.py --strict` subprocess runs over temp valid/stub artifacts); behavioral
tests drive the real Stop hook `hooks/flow-step-guard-codex.mjs` as a subprocess; wiring/byte-identity
tests assert the §10 regression surface. All text-mode subprocess calls pin encoding='utf-8'
(locale-independent, house rule from PR #10/#11).

Cross-cutting fixture rule (BR5): every "reported missing"/block fixture includes an in-session
NON-test production source patch (`_src_patch`, default src/app.py); without it `sourceEdited=false`
neutralizes the obligation and derivation is silent (AC14) regardless of stub artifacts.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROLLOUT = REPO / "hooks" / "codex-rollout.mjs"
EVID = REPO / "hooks" / "codex-flow-evidence.mjs"
HOOK = REPO / "hooks" / "flow-step-guard-codex.mjs"
CODEX_CFG = REPO / "hooks" / "hooks-codex.json"

MARKER = "<!-- agentic-sdlc:gate:completion-claim:verified -->"
FLOW_LABEL = "an artifact-bearing SDLC flow (spec/plan/tests)"

# ---- artifact bodies (must pass/fail validate_artifacts.py --strict for the RIGHT reason) ----
_VALID_SPEC = """# Spec {work_id}

## Problem
This describes the problem domain in enough descriptive detail to exceed the forty-character floor.

## Business rules
The domain rules are enumerated here with enough descriptive text to clear the thin-section gate.

## Acceptance criteria
- {ac_id}: Given a valid spec written this session, when derivation runs, then the spec step passes.

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


# ---- rollout fixture helpers ----------------------------------------------
def _line(type_, payload):
    return json.dumps({"type": type_, "payload": payload})


def _exec_fc(cmd_argv):
    """response_item function_call carrier: exec_command with {cmd: argv} (DP-E)."""
    return _line("response_item", {"type": "function_call", "name": "exec_command",
                                   "arguments": json.dumps({"cmd": cmd_argv})})


def _exec_begin(command, parsed_cmd=None):
    """event_msg carrier: exec_command_begin with {command, parsed_cmd} (DP-E)."""
    p = {"type": "exec_command_begin", "command": command}
    if parsed_cmd is not None:
        p["parsed_cmd"] = parsed_cmd
    return _line("event_msg", p)


def _exec_end(exit_code):
    """event_msg exec_command_end - proves BR3 (exit code is not inspected)."""
    return _line("event_msg", {"type": "exec_command_end", "exit_code": exit_code})


def _v4a_add(path, body_lines=("x = 1",)):
    out = ["*** Begin Patch", f"*** Add File: {path}"]
    out += ["+" + b for b in body_lines]
    out.append("*** End Patch")
    return "\n".join(out)


def _patch_fc(patch_text):
    """response_item function_call carrier: apply_patch with {input: patch_text}."""
    return _line("response_item", {"type": "function_call", "name": "apply_patch",
                                   "arguments": json.dumps({"input": patch_text})})


def _patch_begin(paths):
    """event_msg carrier: patch_apply_begin with {changes:{<path>:{}}} (DP-A/DP-D)."""
    return _line("event_msg", {"type": "patch_apply_begin", "changes": {p: {} for p in paths}})


def _src_patch(path="src/app.py"):
    """An in-session NON-test production source patch (ext in sourceGlobs, not test/artifact)."""
    return _patch_fc(_v4a_add(path))


def _redirect_cmd(path):
    """A Bash-mediated write that must NOT be read as an edit target (AC27)."""
    return _exec_fc(["bash", "-lc", f"printf x > {path}"])


def _write_rollout(lines):
    fd, path = tempfile.mkstemp(suffix=".jsonl", prefix="codex-flow-rollout-")
    os.close(fd)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_over_ceiling_rollout():
    fd, path = tempfile.mkstemp(suffix=".jsonl", prefix="codex-flow-big-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(_src_patch() + "\n")
        fh.write("x" * (8 * 1024 * 1024 + 16))
    return path


def _artifact(cwd, role, work_id, valid=True, ac_id="AC1"):
    """Write the real artifact FILE to disk for the validator. Returns its repo-relative path.

    DISTINCT from the in-session rollout signal: to mark this artifact as written THIS session, the
    fixture ALSO adds a `_mark_write(rel)` line. On-disk presence alone never activates a flow (BR4).
    """
    sub = "specs" if role == "spec" else "plans"
    d = Path(cwd) / "docs" / "agentic-sdlc" / sub
    d.mkdir(parents=True, exist_ok=True)
    if role == "spec":
        text = _VALID_SPEC.format(work_id=work_id, ac_id=ac_id) if valid else "# Spec\n(stub)\n"
    else:
        text = _VALID_PLAN.format(work_id=work_id, ac_id=ac_id) if valid else "## Task 1\n(todo)\n"
    (d / f"{work_id}.md").write_text(text, encoding="utf-8")
    return f"docs/agentic-sdlc/{sub}/{work_id}.md"


def _mark_write(rel):
    """Mark a path as written this session (an in-session edit signal)."""
    return _patch_begin([rel])


# ---- node drivers ----------------------------------------------------------
def _node(script, *args):
    r = subprocess.run(["node", "--input-type=module", "-e", script, *args],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout


def _signals(rollout_path):
    script = ("const m = await import(%s);"
              "process.stdout.write(JSON.stringify(m.readRolloutSignals(process.argv[1])));"
              % json.dumps(ROLLOUT.as_uri()))
    return json.loads(_node(script, rollout_path))


def _derive(rollout_path, cwd):
    script = ("const m = await import(%s);"
              "process.stdout.write(JSON.stringify(m.deriveFlowEvidence(process.argv[1], process.argv[2])));"
              % json.dumps(EVID.as_uri()))
    return json.loads(_node(script, rollout_path, str(cwd)))


def _derive_with(rollout_path, req_obj, cwd):
    script = ("const r = await import(%s); const e = await import(%s);"
              "const sig = r.readRolloutSignals(process.argv[1]);"
              "const req = JSON.parse(process.argv[2]);"
              "process.stdout.write(JSON.stringify(e.deriveFlowEvidenceWith(sig, req, process.argv[3])));"
              % (json.dumps(ROLLOUT.as_uri()), json.dumps(EVID.as_uri())))
    return json.loads(_node(script, rollout_path, json.dumps(req_obj), str(cwd)))


def _run_hook(stop_input, env_extra=None):
    env = dict(os.environ)
    env.pop("AGENTIC_FLOW_GATE_BLOCK", None)
    if env_extra:
        env.update(env_extra)
    payload = stop_input if isinstance(stop_input, str) else json.dumps(stop_input)
    r = subprocess.run(["node", str(HOOK)], input=payload,
                       capture_output=True, text=True, encoding="utf-8", env=env)
    assert r.returncode == 0, r.stderr  # fail-open: always exit 0
    return r.stdout


def _git_show(rel):
    r = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=str(REPO),
                       capture_output=True, text=True, encoding="utf-8")
    return r.stdout if r.returncode == 0 else None


class _Tmp(unittest.TestCase):
    def _cwd(self):
        d = tempfile.mkdtemp(prefix="codex-flow-cwd-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d


# ---- AC9, AC16, AC27, AC32: the rollout-signal reader ----------------------
class TestRolloutSignals(unittest.TestCase):
    def test_command_union_function_call_carrier(self):  # AC32
        sig = _signals(_write_rollout([_exec_fc(["python3", "-m", "pytest"])]))
        self.assertIn("python3 -m pytest", sig["commands"])

    def test_command_union_event_message_carrier(self):  # AC32
        sig = _signals(_write_rollout([_exec_begin("python3 -m pytest")]))
        self.assertIn("python3 -m pytest", sig["commands"])

    def test_event_message_parsed_cmd_surfaced(self):  # AC32 (parsed_cmd token join)
        sig = _signals(_write_rollout([_exec_begin("", parsed_cmd=["python3", "-m", "pytest"])]))
        self.assertTrue(any("python3 -m pytest" in c for c in sig["commands"]))

    def test_patch_targets_from_function_call_and_begin(self):  # DP-A/DP-D
        sig = _signals(_write_rollout([
            _patch_fc(_v4a_add("src/x.py")),
            _patch_begin(["docs/agentic-sdlc/specs/W.md"]),
        ]))
        self.assertIn("src/x.py", sig["editTargets"])
        self.assertIn("docs/agentic-sdlc/specs/W.md", sig["editTargets"])

    def test_redirect_is_not_an_edit_target(self):  # AC27
        sig = _signals(_write_rollout([_redirect_cmd("src/app.py")]))
        self.assertEqual(sig["editTargets"], [])

    def test_over_ceiling_unreadable(self):  # AC16
        path = _write_over_ceiling_rollout()
        sig = _signals(path)
        self.assertFalse(sig["readable"])
        self.assertEqual(sig["commands"], [])
        self.assertEqual(sig["editTargets"], [])
        os.unlink(path)

    def test_unreadable_fail_open(self):  # AC9
        sig = _signals("/no/such/rollout.jsonl")
        self.assertFalse(sig["readable"])
        self.assertEqual(sig["commands"], [])
        self.assertEqual(sig["editTargets"], [])


# ---- AC1..AC3, AC10..AC14, AC24, AC26, AC30..AC32: pure derivation ----------
class TestFlowEvidenceDerivation(_Tmp):
    def test_valid_spec_plan_only_tests_missing(self):  # AC1
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=True)
        p = _artifact(cwd, "plan", "W", valid=True)
        roll = _write_rollout([_mark_write(s), _mark_write(p), _src_patch()])
        self.assertEqual(_derive(roll, cwd)["missingBlockSteps"], ["tests"])

    def test_command_satisfies_tests_ignoring_nonzero_exit(self):  # AC2
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=True)
        p = _artifact(cwd, "plan", "W", valid=True)
        roll = _write_rollout([_mark_write(s), _mark_write(p), _src_patch(),
                               _exec_fc(["python3", "-m", "pytest"]), _exec_end(1)])
        self.assertEqual(_derive(roll, cwd)["missingBlockSteps"], [])

    def test_active_flow_missing_reported(self):  # AC3
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=False)
        p = _artifact(cwd, "plan", "W", valid=False)
        roll = _write_rollout([_mark_write(s), _mark_write(p), _src_patch()])
        self.assertEqual(set(_derive(roll, cwd)["missingBlockSteps"]), {"spec", "plan", "tests"})

    def test_empty_requirements_inactive(self):  # AC10 (real corrupt loader shape)
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=True)
        roll = _write_rollout([_mark_write(s), _src_patch()])
        out = _derive_with(roll, {"version": 0, "flows": {}}, cwd)
        self.assertEqual(out, {"flow": False, "workIds": [], "missingBlockSteps": []})

    def test_stub_plan_reported_missing(self):  # AC11
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=True)
        p = _artifact(cwd, "plan", "W", valid=False)
        roll = _write_rollout([_mark_write(s), _mark_write(p), _src_patch()])
        missing = _derive(roll, cwd)["missingBlockSteps"]
        self.assertIn("plan", missing)
        self.assertNotIn("spec", missing)

    def test_active_only_on_in_session_write(self):  # AC12
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=True)
        active = _derive(_write_rollout([_mark_write(s), _src_patch()]), cwd)
        self.assertTrue(active["flow"])
        self.assertIn("W", active["workIds"])
        inactive = _derive(_write_rollout([_src_patch()]), cwd)
        self.assertFalse(inactive["flow"])
        self.assertEqual(inactive["missingBlockSteps"], [])

    def test_tooluse_only_steps_not_reported(self):  # AC13
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=True)
        p = _artifact(cwd, "plan", "W", valid=True)
        roll = _write_rollout([_mark_write(s), _mark_write(p), _src_patch(),
                               _exec_fc(["python3", "-m", "pytest"])])
        self.assertEqual(_derive(roll, cwd)["missingBlockSteps"], [])

    def test_no_source_edit_is_silent(self):  # AC14
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=True)
        p = _artifact(cwd, "plan", "W", valid=True)
        roll = _write_rollout([_mark_write(s), _mark_write(p)])
        out = _derive(roll, cwd)
        self.assertTrue(out["flow"])
        self.assertEqual(out["missingBlockSteps"], [])

    def test_workid_pairing_disambiguates_among_decoys(self):  # AC24
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=True, ac_id="AC1")
        p = _artifact(cwd, "plan", "W", valid=True, ac_id="AC1")
        _artifact(cwd, "spec", "AAA-decoy", valid=True, ac_id="AC9")  # sorts first; on disk only
        _artifact(cwd, "spec", "OTHER", valid=True, ac_id="AC1")      # on disk only
        roll = _write_rollout([_mark_write(s), _mark_write(p), _src_patch()])
        self.assertEqual(_derive(roll, cwd)["missingBlockSteps"], ["tests"])

    def test_stub_spec_reported_missing(self):  # AC26
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=False)
        roll = _write_rollout([_mark_write(s), _src_patch()])
        self.assertIn("spec", _derive(roll, cwd)["missingBlockSteps"])

    def test_multi_workid_union(self):  # AC25 dedup / AC30 union
        cwd = self._cwd()
        sa = _artifact(cwd, "spec", "A", valid=True)
        pa = _artifact(cwd, "plan", "A", valid=True)
        pb = _artifact(cwd, "plan", "B", valid=False)  # no B spec on disk
        roll = _write_rollout([_mark_write(sa), _mark_write(pa), _mark_write(pb), _src_patch()])
        self.assertEqual(_derive(roll, cwd)["missingBlockSteps"], ["spec", "plan", "tests"])

    def test_plan_without_same_workid_spec_no_fallback(self):  # AC31
        cwd = self._cwd()
        p = _artifact(cwd, "plan", "W", valid=True)
        _artifact(cwd, "spec", "OTHER", valid=True)  # unrelated spec on disk
        roll = _write_rollout([_mark_write(p), _src_patch()])
        missing = _derive(roll, cwd)["missingBlockSteps"]
        self.assertIn("plan", missing)
        self.assertIn("spec", missing)

    def test_command_carrier_union(self):  # AC32 (both carriers satisfy tests)
        for cmd_line in (_exec_fc(["python3", "-m", "pytest"]), _exec_begin("python3 -m pytest")):
            cwd = self._cwd()
            s = _artifact(cwd, "spec", "W", valid=True)
            p = _artifact(cwd, "plan", "W", valid=True)
            roll = _write_rollout([_mark_write(s), _mark_write(p), _src_patch(), cmd_line])
            self.assertEqual(_derive(roll, cwd)["missingBlockSteps"], [])

    def test_traversing_workid_selects_no_file(self):  # Sink B
        cwd = self._cwd()
        roll = _write_rollout([
            _patch_fc(_v4a_add("docs/agentic-sdlc/specs/../../etc/passwd")),
            _src_patch(),
        ])
        missing = _derive(roll, cwd)["missingBlockSteps"]
        self.assertIn("spec", missing)
        self.assertIn("plan", missing)


# ---- AC4..AC9, AC13..AC17, AC23, AC25, AC27..AC29: behavioral Stop hook -----
class TestFlowStepGuardBehavior(_Tmp):
    def _stop(self, cwd, lines, **kw):
        inp = {"transcript_path": _write_rollout(lines), "cwd": str(cwd)}
        inp.update(kw)
        return inp

    def _missing_tests_fixture(self, cwd, extra=()):
        s = _artifact(cwd, "spec", "W", valid=True)
        p = _artifact(cwd, "plan", "W", valid=True)
        return [_mark_write(s), _mark_write(p), _src_patch(), *extra]

    def test_blocks_missing_step_under_env(self):  # AC4
        cwd = self._cwd()
        out = _run_hook(self._stop(cwd, self._missing_tests_fixture(cwd)),
                        {"AGENTIC_FLOW_GATE_BLOCK": "true"})
        self.assertIn('"decision":"block"', out.replace(" ", ""))

    def test_warns_without_env(self):  # AC5
        cwd = self._cwd()
        out = _run_hook(self._stop(cwd, self._missing_tests_fixture(cwd)))
        self.assertIn("systemMessage", out)
        self.assertNotIn('"decision"', out.replace(" ", ""))

    def test_silent_no_active_flow(self):  # AC6 (also guard-level AC10 inactive path)
        cwd = self._cwd()
        out = _run_hook(self._stop(cwd, [_src_patch()]), {"AGENTIC_FLOW_GATE_BLOCK": "true"})
        self.assertEqual(out.strip(), "")

    def test_silent_all_satisfied(self):  # AC7
        cwd = self._cwd()
        lines = self._missing_tests_fixture(cwd, extra=[_exec_fc(["python3", "-m", "pytest"])])
        out = _run_hook(self._stop(cwd, lines), {"AGENTIC_FLOW_GATE_BLOCK": "true"})
        self.assertEqual(out.strip(), "")

    def test_silent_stop_hook_active(self):  # AC8
        cwd = self._cwd()
        out = _run_hook(self._stop(cwd, self._missing_tests_fixture(cwd), stop_hook_active=True),
                        {"AGENTIC_FLOW_GATE_BLOCK": "true"})
        self.assertEqual(out.strip(), "")

    def test_silent_missing_transcript(self):  # AC9
        cwd = self._cwd()
        out = _run_hook({"transcript_path": "/no/such.jsonl", "cwd": str(cwd)},
                        {"AGENTIC_FLOW_GATE_BLOCK": "true"})
        self.assertEqual(out.strip(), "")

    def test_silent_tooluse_only_steps_under_both_env(self):  # AC13 (guard-level)
        cwd = self._cwd()
        lines = self._missing_tests_fixture(cwd, extra=[_exec_fc(["python3", "-m", "pytest"])])
        self.assertEqual(_run_hook(self._stop(cwd, lines),
                                   {"AGENTIC_FLOW_GATE_BLOCK": "true"}).strip(), "")
        self.assertEqual(_run_hook(self._stop(cwd, lines)).strip(), "")

    def test_silent_spec_plan_no_source_edit_under_env(self):  # AC14 (guard-level)
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=True)
        p = _artifact(cwd, "plan", "W", valid=True)
        out = _run_hook(self._stop(cwd, [_mark_write(s), _mark_write(p)]),
                        {"AGENTIC_FLOW_GATE_BLOCK": "true"})
        self.assertEqual(out.strip(), "")

    def test_silent_over_ceiling(self):  # AC16
        cwd = self._cwd()
        path = _write_over_ceiling_rollout()
        out = _run_hook({"transcript_path": path, "cwd": str(cwd)},
                        {"AGENTIC_FLOW_GATE_BLOCK": "true"})
        self.assertEqual(out.strip(), "")
        os.unlink(path)

    def test_silent_malformed_stdin(self):  # AC17
        out = _run_hook("this is not json", {"AGENTIC_FLOW_GATE_BLOCK": "true"})
        self.assertEqual(out.strip(), "")

    def test_silent_cross_session_under_both_envs(self):  # AC23
        cwd = self._cwd()
        _artifact(cwd, "spec", "X", valid=True)  # committed prior session, on disk only
        _artifact(cwd, "plan", "X", valid=True)
        inp = self._stop(cwd, [_src_patch("src/unrelated.py")])
        self.assertEqual(_run_hook(inp, {"AGENTIC_FLOW_GATE_BLOCK": "true"}).strip(), "")
        self.assertEqual(_run_hook(inp).strip(), "")

    def test_block_reason_omits_rollout_sentinel(self):  # AC15
        cwd = self._cwd()
        lines = self._missing_tests_fixture(cwd, extra=[_exec_fc(["echo", "SENTINEL_LEAK_XYZ"])])
        out = _run_hook(self._stop(cwd, lines), {"AGENTIC_FLOW_GATE_BLOCK": "true"})
        self.assertIn('"decision":"block"', out.replace(" ", ""))
        self.assertNotIn("SENTINEL_LEAK_XYZ", out)

    def test_block_reason_omits_workid_and_filename(self):  # AC25/AC30
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "SENTINELWORKID", valid=True)
        p = _artifact(cwd, "plan", "SENTINELWORKID", valid=True)
        out = _run_hook(self._stop(cwd, [_mark_write(s), _mark_write(p), _src_patch()]),
                        {"AGENTIC_FLOW_GATE_BLOCK": "true"})
        self.assertIn(FLOW_LABEL, out)
        self.assertNotIn("SENTINELWORKID", out)
        self.assertNotIn("root-cause-fix", out)
        ids = out[out.index("[") + 1:out.index("]")].split(", ")
        self.assertEqual(ids, ["tests"])  # dedup: a single 'tests' id, not duplicated per flow

    def test_silent_bash_mediated_edit(self):  # AC27
        cwd = self._cwd()
        out = _run_hook(self._stop(cwd, [_redirect_cmd("src/app.py")]),
                        {"AGENTIC_FLOW_GATE_BLOCK": "true"})
        self.assertEqual(out.strip(), "")

    def test_independent_of_completion_guard(self):  # AC28
        cwd = self._cwd()
        lines = self._missing_tests_fixture(cwd) + [
            _line("event_msg", {"type": "task_complete",
                                "last_agent_message": "All tests passing, done and verified. " + MARKER}),
        ]
        out = _run_hook(self._stop(cwd, lines), {"AGENTIC_FLOW_GATE_BLOCK": "true"})
        self.assertIn('"decision":"block"', out.replace(" ", ""))

    def test_within_session_implement_blocks_under_env(self):  # AC29
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=True)
        p = _artifact(cwd, "plan", "W", valid=True)
        lines = [_mark_write(s), _mark_write(p), _src_patch("src/later.py")]  # edit after authoring
        out = _run_hook(self._stop(cwd, lines), {"AGENTIC_FLOW_GATE_BLOCK": "true"})
        self.assertIn('"decision":"block"', out.replace(" ", ""))


# ---- AC19: additive Stop wiring, substring-safe filename --------------------
class TestStopWiring(unittest.TestCase):
    def setUp(self):
        self.cfg_text = CODEX_CFG.read_text(encoding="utf-8")
        self.cfg = json.loads(self.cfg_text)

    def _stop_commands(self):
        return [h["command"] for blk in self.cfg["hooks"]["Stop"] for h in blk["hooks"]]

    def test_stop_array_has_both_guards_shell_string_plugin_root(self):  # AC19
        cmds = self._stop_commands()
        new = [c for c in cmds if "flow-step-guard-codex.mjs" in c]
        old = [c for c in cmds if "completion-claim-guard-codex.mjs" in c]
        self.assertEqual(len(new), 1)
        self.assertEqual(len(old), 1)
        self.assertIsInstance(new[0], str)  # shell-string form (args-array does not run on Codex)
        self.assertIn("${PLUGIN_ROOT}", new[0])
        self.assertNotIn("flow-step-guard.mjs", new[0])  # -codex infix keeps the deferred lock intact
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", self.cfg_text)
        self.assertFalse((REPO / "hooks" / "hooks.json").exists())


# ---- AC18: §10 regression surface untouched --------------------------------
class TestRegressionSurfaceUntouched(unittest.TestCase):
    BYTE_LOCKED = [
        "hooks/flow-step-guard.mjs",
        "hooks/flow-evidence.mjs",
        "hooks/flow-requirements.json",
        "hooks/hooks-claude.json",
        "hooks/completion-claim-guard.mjs",
        "hooks/completion-claim-guard-codex.mjs",
    ]

    def test_locked_files_byte_identical_to_head(self):  # AC18
        for rel in self.BYTE_LOCKED:
            with self.subTest(file=rel):
                head = _git_show(rel)
                self.assertIsNotNone(head, f"{rel} not in HEAD")
                self.assertEqual((REPO / rel).read_text(encoding="utf-8"), head)

    def test_codex_pretooluse_sessionstart_unchanged(self):  # AC18
        cur = json.loads(CODEX_CFG.read_text(encoding="utf-8"))
        head = json.loads(_git_show("hooks/hooks-codex.json"))
        self.assertEqual(cur["hooks"]["PreToolUse"], head["hooks"]["PreToolUse"])
        self.assertEqual(cur["hooks"]["SessionStart"], head["hooks"]["SessionStart"])

    def test_existing_completion_claim_stop_handler_unchanged(self):  # AC18
        cur = json.loads(CODEX_CFG.read_text(encoding="utf-8"))
        head = json.loads(_git_show("hooks/hooks-codex.json"))
        head_handlers = [h for blk in head["hooks"]["Stop"] for h in blk["hooks"]]
        cur_handlers = [h for blk in cur["hooks"]["Stop"] for h in blk["hooks"]]
        head_cc = [h for h in head_handlers if "completion-claim-guard-codex.mjs" in h["command"]]
        cur_cc = [h for h in cur_handlers if "completion-claim-guard-codex.mjs" in h["command"]]
        self.assertEqual(cur_cc, head_cc)


if __name__ == "__main__":
    unittest.main()
