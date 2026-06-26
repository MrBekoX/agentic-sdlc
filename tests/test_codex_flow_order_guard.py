"""AP2c - Codex flow-order guard (env-gated PreToolUse pre-edit ordering gate). Covers AC1-AC20.

The pre-edit gate denies a source-file edit attempted before THIS session produced a validated
spec AND a matching plan (same work id, BOTH written this session via a recognized artifact write,
each re-validating). Default-silent; only active under AGENTIC_FLOW_ORDER_BLOCK.

Behavioral/fail-open tests drive the real hook `hooks/flow-order-guard-codex.mjs` as a subprocess.
The pure `orderDecision(signals, req, cwd)` is exported and driven by an `_order_decision` node
driver (the entrypoint guard keeps `main()` from firing on import). A real
`scripts/validate_artifacts.py --strict` subprocess runs over temp valid/stub/mixed-origin fixtures.
Wiring/byte-lock tests assert the §7 regression surface. All text-mode subprocess calls pin
encoding='utf-8' (locale-independent, house rule from PR #10/#11).

Key divergence under test (DP-EVID/AC17): the gate must NOT reuse AP2b deriveFlowEvidence, which
validates a partner role from on-disk presence; the mixed-origin case (in-session spec write +
committed-only plan) must DENY naming the half not written this session.
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
HOOK = REPO / "hooks" / "flow-order-guard-codex.mjs"
CODEX_CFG = REPO / "hooks" / "hooks-codex.json"

# ---- artifact bodies (must pass/fail validate_artifacts.py --strict for the RIGHT reason) ----
# Reused from the AP2b harness, calibrated so a valid body clears --strict and a stub fails it.
_VALID_SPEC = """# Spec {work_id}

## Problem
This describes the problem domain in enough descriptive detail to exceed the forty-character floor.

## Business rules
The domain rules are enumerated here with enough descriptive text to clear the thin-section gate.

## Acceptance criteria
- {ac_id}: Given a valid spec written this session, when the gate runs, then the spec step passes.

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
    """response_item function_call carrier: exec_command with {cmd: argv}."""
    return _line("response_item", {"type": "function_call", "name": "exec_command",
                                   "arguments": json.dumps({"cmd": cmd_argv})})


def _v4a_add(path, body_lines=("x = 1",)):
    out = ["*** Begin Patch", f"*** Add File: {path}"]
    out += ["+" + b for b in body_lines]
    out.append("*** End Patch")
    return "\n".join(out)


def _v4a_multi(paths, body_lines=("x = 1",)):
    """One apply_patch bundling several *** Add File: entries (DP-ATOMIC fixture)."""
    out = ["*** Begin Patch"]
    for p in paths:
        out.append(f"*** Add File: {p}")
        out += ["+" + b for b in body_lines]
    out.append("*** End Patch")
    return "\n".join(out)


def _patch_fc(patch_text):
    """response_item function_call carrier: apply_patch with {input: patch_text}."""
    return _line("response_item", {"type": "function_call", "name": "apply_patch",
                                   "arguments": json.dumps({"input": patch_text})})


def _patch_begin(paths):
    """event_msg carrier: patch_apply_begin with {changes:{<path>:{}}} (the in-session write signal)."""
    return _line("event_msg", {"type": "patch_apply_begin", "changes": {p: {} for p in paths}})


def _src_patch(path="src/app.py"):
    """An in-session NON-test production source patch (ext in sourceGlobs, not test/artifact)."""
    return _patch_fc(_v4a_add(path))


def _redirect_cmd(path):
    """A Bash-mediated write recorded as a command (must NOT surface as an edit target)."""
    return _exec_fc(["bash", "-lc", f"printf x > {path}"])


def _patch_end(paths, success=True):
    """event_msg carrier: patch_apply_end — the shape codex-cli 0.142.0 ACTUALLY persists for a native
    apply_patch (verified live: no patch_apply_begin / function_call apply_patch is emitted)."""
    return _line("event_msg", {"type": "patch_apply_end", "success": success,
                               "changes": {p: {"type": "add", "content": ""} for p in paths}})


def _mark_write(rel):
    """Mark a path as written this session (an in-session apply_patch edit signal). Uses the REAL
    codex-cli 0.142.0 carrier (patch_apply_end), so the whole AP2c in-session-write suite exercises
    the shape Codex actually emits (DP-LIVE), not just the begin/function_call forms."""
    return _patch_end([rel])


def _write_rollout(lines):
    fd, path = tempfile.mkstemp(suffix=".jsonl", prefix="codex-order-rollout-")
    os.close(fd)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_over_ceiling_rollout():
    fd, path = tempfile.mkstemp(suffix=".jsonl", prefix="codex-order-big-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(_src_patch() + "\n")
        fh.write("x" * (8 * 1024 * 1024 + 16))
    return path


def _artifact(cwd, role, work_id, valid=True, ac_id="AC1"):
    """Write the real artifact FILE to disk for the validator. Returns its repo-relative path.

    DISTINCT from the in-session rollout signal: to mark this artifact as written THIS session, the
    fixture ALSO adds a `_mark_write(rel)` line. On-disk presence alone never counts (BR3).
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


# ---- current-edit command builders (the pending edit, in tool_input.command) ----
def _src_redirect_cmd(path="src/app.py"):
    return f"printf x > {path}"


def _src_heredoc_cmd(path="src/app.py"):
    """A single-quoted literal heredoc in the recognized delimiter-then-redirect ordering."""
    return f"cat <<'EOF' > {path}\nx = 1\nEOF\n"


def _mixed_targets_cmd():
    """One source + one test target in a compound command."""
    return "printf x > src/app.py; printf y > tests/test_x.py"


def _atomic_bundle_cmd(work_id="W"):
    return _v4a_multi([f"docs/agentic-sdlc/specs/{work_id}.md",
                       f"docs/agentic-sdlc/plans/{work_id}.md", "src/app.py"])


# ---- node / subprocess drivers ---------------------------------------------
def _node(script, *args):
    r = subprocess.run(["node", "--input-type=module", "-e", script, *args],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout


def _order_decision(rollout_lines, req_obj, cwd):
    """Drive the exported pure orderDecision over a synthetic rollout + hand-built req."""
    rollout = _write_rollout(rollout_lines)
    script = ("const r = await import(%s); const h = await import(%s);"
              "const sig = r.readRolloutSignals(process.argv[1]);"
              "const req = JSON.parse(process.argv[2]);"
              "process.stdout.write(JSON.stringify(h.orderDecision(sig, req, process.argv[3])));"
              % (json.dumps(ROLLOUT.as_uri()), json.dumps(HOOK.as_uri())))
    return json.loads(_node(script, rollout, json.dumps(req_obj), str(cwd)))


def _run_hook(stdin, env_extra=None):
    env = dict(os.environ)
    env.pop("AGENTIC_FLOW_ORDER_BLOCK", None)
    if env_extra:
        env.update(env_extra)
    payload = stdin if isinstance(stdin, str) else json.dumps(stdin)
    r = subprocess.run(["node", str(HOOK)], input=payload,
                       capture_output=True, text=True, encoding="utf-8", env=env)
    assert r.returncode == 0, r.stderr  # fail-open: always exit 0
    return r.stdout


def _git_show(rel):
    r = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=str(REPO),
                       capture_output=True, text=True, encoding="utf-8")
    return r.stdout if r.returncode == 0 else None


def _deny_reason(stdout):
    return json.loads(stdout)["hookSpecificOutput"]["permissionDecisionReason"]


def _missing_list(stdout):
    """Parse the single bracketed Missing list (the ONLY place dynamic roles appear)."""
    reason = _deny_reason(stdout)
    return reason[reason.index("[") + 1:reason.index("]")].split(", ")


def _is_deny(stdout):
    return '"permissionDecision":"deny"' in stdout.replace(" ", "")


ENV_ON = {"AGENTIC_FLOW_ORDER_BLOCK": "true"}


class _Tmp(unittest.TestCase):
    def _cwd(self):
        d = tempfile.mkdtemp(prefix="codex-order-cwd-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d

    def _pre(self, cwd, command, tool_name="Bash", rollout_lines=None, **kw):
        inp = {"tool_name": tool_name, "tool_input": {"command": command},
               "transcript_path": _write_rollout(rollout_lines or []), "cwd": str(cwd)}
        inp.update(kw)
        return inp


# ---- AC1..AC11, AC13, AC17..AC20: behavioral + fail-open --------------------
class TestFlowOrderGuard(_Tmp):
    def test_env_off_silent(self):  # AC2/BR1
        cwd = self._cwd()
        out = _run_hook(self._pre(cwd, _src_redirect_cmd()))  # env unset
        self.assertEqual(out.strip(), "")

    def test_flow_gate_block_alone_does_not_activate_order(self):  # A2/DP-ENV decouple
        # The flow-step switch must NOT turn the flow-order pre-gate on (independent switches).
        cwd = self._cwd()
        out = _run_hook(self._pre(cwd, _src_redirect_cmd()),
                        {"AGENTIC_FLOW_GATE_BLOCK": "true"})  # only the flow-STEP switch
        self.assertEqual(out.strip(), "")  # flow-order stays silent

    def test_env_truthy_boundary(self):  # BR1/DP-TRUTHY
        cwd = self._cwd()
        for val in ("1", "yes", "TRUE"):
            with self.subTest(env=val):
                out = _run_hook(self._pre(cwd, _src_redirect_cmd()),
                                {"AGENTIC_FLOW_ORDER_BLOCK": val})
                self.assertTrue(_is_deny(out))
        for val in ("0", "no", "maybe", ""):
            with self.subTest(env=val):
                out = _run_hook(self._pre(cwd, _src_redirect_cmd()),
                                {"AGENTIC_FLOW_ORDER_BLOCK": val})
                self.assertEqual(out.strip(), "")

    def test_bash_redirect_source_edit_no_pair_denies(self):  # AC1/AC3 redirect form
        cwd = self._cwd()
        out = _run_hook(self._pre(cwd, _src_redirect_cmd()), ENV_ON)
        self.assertEqual(_missing_list(out), ["spec", "plan"])

    def test_bash_heredoc_source_edit_no_pair_denies(self):  # AC3 heredoc form
        cwd = self._cwd()
        out = _run_hook(self._pre(cwd, _src_heredoc_cmd()), ENV_ON)
        self.assertEqual(_missing_list(out), ["spec", "plan"])

    def test_mixed_source_and_test_target_denies(self):  # §5 mixed-target edge
        cwd = self._cwd()
        out = _run_hook(self._pre(cwd, _mixed_targets_cmd()), ENV_ON)
        self.assertTrue(_is_deny(out))

    def test_apply_patch_source_edit_no_pair_denies(self):  # AC4
        cwd = self._cwd()
        out = _run_hook(self._pre(cwd, _v4a_add("src/app.py"), tool_name="apply_patch"), ENV_ON)
        self.assertEqual(_missing_list(out), ["spec", "plan"])

    def test_order_respected_allows(self):  # AC5
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=True)
        p = _artifact(cwd, "plan", "W", valid=True)
        out = _run_hook(self._pre(cwd, _src_redirect_cmd(),
                                  rollout_lines=[_mark_write(s), _mark_write(p)]), ENV_ON)
        self.assertEqual(out.strip(), "")

    def test_mixed_origin_disk_only_plan_denies_plan(self):  # AC17 (DP-EVID load-bearing)
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=True)
        _artifact(cwd, "plan", "W", valid=True)  # on disk only, NO _mark_write
        out = _run_hook(self._pre(cwd, _src_redirect_cmd(),
                                  rollout_lines=[_mark_write(s)]), ENV_ON)
        self.assertEqual(_missing_list(out), ["plan"])

    def test_partial_spec_only_denies_plan(self):  # AC10
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=True)
        out = _run_hook(self._pre(cwd, _src_redirect_cmd(),
                                  rollout_lines=[_mark_write(s)]), ENV_ON)
        self.assertEqual(_missing_list(out), ["plan"])

    def test_partial_plan_only_denies_spec(self):  # AC10 mirror
        cwd = self._cwd()
        _artifact(cwd, "spec", "W", valid=True)  # on disk for pairing, NOT in-session-written
        p = _artifact(cwd, "plan", "W", valid=True)
        out = _run_hook(self._pre(cwd, _src_redirect_cmd(),
                                  rollout_lines=[_mark_write(p)]), ENV_ON)
        self.assertEqual(_missing_list(out), ["spec"])

    def test_cross_session_committed_pair_denies(self):  # AC11
        cwd = self._cwd()
        _artifact(cwd, "spec", "W", valid=True)
        _artifact(cwd, "plan", "W", valid=True)
        out = _run_hook(self._pre(cwd, _src_redirect_cmd(), rollout_lines=[]), ENV_ON)
        self.assertEqual(_missing_list(out), ["spec", "plan"])

    def test_prior_redirect_written_spec_plan_is_now_evidence_allows(self):  # A1/BR4a closure (was a false-DENY)
        # Before A1 a redirect-written spec/plan was invisible as prior evidence, so flow-order
        # FALSE-DENIED a correctly-ordered following source edit. Now the `>`/`>>` redirect writes are
        # detected, the in-session spec+plan pair counts, and ordering is respected -> ALLOW.
        cwd = self._cwd()
        _artifact(cwd, "spec", "W", valid=True)
        _artifact(cwd, "plan", "W", valid=True)
        roll = [_redirect_cmd("docs/agentic-sdlc/specs/W.md"),
                _redirect_cmd("docs/agentic-sdlc/plans/W.md")]
        out = _run_hook(self._pre(cwd, _src_redirect_cmd(), rollout_lines=roll), ENV_ON)
        self.assertEqual(out.strip(), "")  # no more false block

    def test_atomic_bundle_patch_denies(self):  # DP-ATOMIC
        cwd = self._cwd()
        out = _run_hook(self._pre(cwd, _atomic_bundle_cmd("W"),
                                  tool_name="apply_patch", rollout_lines=[]), ENV_ON)
        self.assertEqual(_missing_list(out), ["spec", "plan"])

    def test_stub_in_session_spec_denies(self):  # AC18
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=False)  # stub fails strict
        p = _artifact(cwd, "plan", "W", valid=True)
        out = _run_hook(self._pre(cwd, _src_redirect_cmd(),
                                  rollout_lines=[_mark_write(s), _mark_write(p)]), ENV_ON)
        self.assertIn("spec", _missing_list(out))

    def test_non_source_target_silent(self):  # AC6/BR2
        cwd = self._cwd()
        cases = [("printf x > tests/test_x.py", "Bash"),
                 (_v4a_add("docs/agentic-sdlc/specs/W.md"), "apply_patch"),
                 ("printf x > README.md", "Bash")]
        for command, tool_name in cases:
            with self.subTest(target=command[:30]):
                out = _run_hook(self._pre(cwd, command, tool_name=tool_name), ENV_ON)
                self.assertEqual(out.strip(), "")

    def test_source_delete_silent(self):  # AC9/DP-DELETE
        cwd = self._cwd()
        patch = "*** Begin Patch\n*** Delete File: src/app.py\n*** End Patch"
        out = _run_hook(self._pre(cwd, patch, tool_name="apply_patch"), ENV_ON)
        self.assertEqual(out.strip(), "")

    def test_unrecognized_form_silent(self):  # AC9
        cwd = self._cwd()
        out = _run_hook(self._pre(cwd, "sed -i s/a/b/ src/app.py"), ENV_ON)
        self.assertEqual(out.strip(), "")

    def test_unreadable_transcript_fail_open(self):  # AC7
        cwd = self._cwd()
        inp = {"tool_name": "Bash", "tool_input": {"command": _src_redirect_cmd()},
               "transcript_path": "/no/such/rollout.jsonl", "cwd": str(cwd)}
        self.assertEqual(_run_hook(inp, ENV_ON).strip(), "")

    def test_oversized_transcript_fail_open(self):  # AC7
        cwd = self._cwd()
        path = _write_over_ceiling_rollout()
        inp = {"tool_name": "Bash", "tool_input": {"command": _src_redirect_cmd()},
               "transcript_path": path, "cwd": str(cwd)}
        self.assertEqual(_run_hook(inp, ENV_ON).strip(), "")
        os.unlink(path)

    def test_malformed_stdin_fail_open(self):  # AC8
        self.assertEqual(_run_hook("this is not json", ENV_ON).strip(), "")

    def test_absent_command_field_fail_open(self):  # AC8
        cwd = self._cwd()
        omitted = {"tool_name": "Bash", "tool_input": {},
                   "transcript_path": _write_rollout([]), "cwd": str(cwd)}
        self.assertEqual(_run_hook(omitted, ENV_ON).strip(), "")
        non_string = {"tool_name": "Bash", "tool_input": {"command": 123},
                      "transcript_path": _write_rollout([]), "cwd": str(cwd)}
        self.assertEqual(_run_hook(non_string, ENV_ON).strip(), "")

    def test_corrupt_requirements_fail_open(self):  # finding-3: config absence fails OPEN
        cwd = self._cwd()
        out = _order_decision([_src_patch()], {"testCommand": "pytest", "flows": {}}, cwd)
        self.assertEqual(out, {"unconfirmable": True})
        self.assertNotIn("missing", out)

    def test_validator_unavailable_allows(self):  # AC19
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=True)
        p = _artifact(cwd, "plan", "W", valid=True)
        inp = self._pre(cwd, _src_redirect_cmd(), rollout_lines=[_mark_write(s), _mark_write(p)])
        node_bin = shutil.which("node")
        empty = self._cwd()  # an empty dir; PATH-empty removes every interpreter launcher
        env = dict(os.environ)
        env.pop("AGENTIC_FLOW_ORDER_BLOCK", None)
        env["AGENTIC_FLOW_ORDER_BLOCK"] = "true"
        env["PATH"] = empty
        r = subprocess.run([node_bin, str(HOOK)], input=json.dumps(inp),
                           capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "")

    def test_multi_workid_one_complete_pair_allows(self):  # DP-MULTI
        cwd = self._cwd()
        s1 = _artifact(cwd, "spec", "W1", valid=True)
        p1 = _artifact(cwd, "plan", "W1", valid=True)
        p2 = _artifact(cwd, "plan", "W2", valid=True)  # incomplete: no spec W2
        roll = [_mark_write(s1), _mark_write(p1), _mark_write(p2)]
        out = _run_hook(self._pre(cwd, _src_redirect_cmd(), rollout_lines=roll), ENV_ON)
        self.assertEqual(out.strip(), "")

    def test_wrong_cwd_unresolvable_root_denies(self):  # BR4b/DP-CWD
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=True)
        p = _artifact(cwd, "plan", "W", valid=True)
        other = self._cwd()  # empty: artifact roots resolve nowhere
        inp = self._pre(cwd, _src_redirect_cmd(),
                        rollout_lines=[_mark_write(s), _mark_write(p)])
        inp["cwd"] = str(other)
        out = _run_hook(inp, ENV_ON)
        self.assertTrue(_is_deny(out))  # deny, NOT fail-open silence

    def test_safe_refactor_source_edit_denies(self):  # AC20 accepted false-block
        cwd = self._cwd()
        roll = [_exec_fc(["python3", "-m", "pytest"])]  # characterization test, no spec/plan
        out = _run_hook(self._pre(cwd, _src_redirect_cmd(), rollout_lines=roll), ENV_ON)
        self.assertTrue(_is_deny(out))

    def test_deny_payload_shape(self):  # AC13 shape
        cwd = self._cwd()
        out = _run_hook(self._pre(cwd, _src_redirect_cmd()), ENV_ON)
        d = json.loads(out)
        self.assertEqual(d["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(d["hookSpecificOutput"]["hookEventName"], "PreToolUse")


# ---- AC12 + §6 security: untrusted input -> sink ---------------------------
class TestSecurity(_Tmp):
    def test_traversing_workid_selects_no_file_denies(self):  # Sink-B membership, no traversal
        cwd = self._cwd()
        roll = [_mark_write("docs/agentic-sdlc/specs/../../etc/passwd"),
                _mark_write("docs/agentic-sdlc/plans/../../etc/passwd")]
        out = _run_hook(self._pre(cwd, _src_redirect_cmd(), rollout_lines=roll), ENV_ON)
        self.assertTrue(_is_deny(out))

    def test_source_looking_traversal_target_classified_not_opened(self):  # source target not a sink
        cwd = self._cwd()
        out = _run_hook(self._pre(cwd, _v4a_add("../../../x.py"), tool_name="apply_patch"), ENV_ON)
        self.assertTrue(_is_deny(out))

    def test_deny_reason_omits_sensitive_bytes(self):  # AC12/BR6
        cwd = self._cwd()
        roll = [_exec_fc(["echo", "SENTINEL_LEAK_XYZ"]),
                _mark_write("docs/agentic-sdlc/specs/SENTINELWORKID.md")]
        out = _run_hook(self._pre(cwd, _src_redirect_cmd(), rollout_lines=roll), ENV_ON)
        reason = _deny_reason(out)
        self.assertIn("spec", reason)   # fixed preamble legitimately names both roles
        self.assertIn("plan", reason)
        self.assertNotIn("SENTINEL_LEAK_XYZ", reason)
        self.assertNotIn("SENTINELWORKID", reason)
        self.assertNotIn("docs/agentic-sdlc/", reason)
        self.assertNotIn("tests", _missing_list(out))  # bracket only ever draws from {spec, plan}


# ---- AC14: additive PreToolUse wiring, substring-safe filename --------------
class TestOrderWiring(unittest.TestCase):
    def setUp(self):
        self.cfg_text = CODEX_CFG.read_text(encoding="utf-8")
        self.cfg = json.loads(self.cfg_text)

    def _block(self, matcher):
        for blk in self.cfg["hooks"]["PreToolUse"]:
            if blk.get("matcher") == matcher:
                return blk
        return None

    def test_pretooluse_array_has_both_guards(self):  # AC14
        block = self._block("Bash|apply_patch")
        self.assertIsNotNone(block, "Bash|apply_patch PreToolUse block missing")
        cmds = [h["command"] for h in block["hooks"]]
        scan = [c for c in cmds if "scan-write-codex.mjs" in c]
        order = [c for c in cmds if "flow-order-guard-codex.mjs" in c]
        self.assertEqual(len(scan), 1)
        self.assertEqual(len(order), 1)
        # EXACTLY the scan-write + flow-order pair — a future third entry must be a deliberate change
        # (closes the slight widening from relaxing the old strict PreToolUse == HEAD assertion).
        self.assertEqual(len(block["hooks"]), 2, "Bash|apply_patch block must hold exactly scan-write + flow-order")
        self.assertIsInstance(order[0], str)  # shell-string form (args-array does not run on Codex)
        self.assertIn("${PLUGIN_ROOT}", order[0])
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", order[0])
        # the deferred Claude flow-order-guard.mjs is NOT a substring of -codex.mjs
        self.assertNotIn('"flow-order-guard.mjs"', self.cfg_text)
        for h in block["hooks"]:
            self.assertNotIn("args", h, "Codex must use the shell-string form")
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", self.cfg_text)
        self.assertFalse((REPO / "hooks" / "hooks.json").exists())

    def test_command_block_and_stop_unchanged_vs_head(self):  # additive-regression guarantee
        head = json.loads(_git_show("hooks/hooks-codex.json"))
        cur = self.cfg
        head_first = [b for b in head["hooks"]["PreToolUse"] if b.get("matcher") == "Bash"][0]
        cur_first = [b for b in cur["hooks"]["PreToolUse"] if b.get("matcher") == "Bash"][0]
        self.assertEqual(cur_first, head_first)
        self.assertEqual(cur["hooks"]["SessionStart"], head["hooks"]["SessionStart"])
        self.assertEqual(cur["hooks"]["Stop"], head["hooks"]["Stop"])


# ---- BR8/§7: the FULL regression surface stays byte-identical ---------------
class TestRegressionSurfaceUntouched(unittest.TestCase):
    BYTE_LOCKED = [
        # Claude flow files (spec §7).
        "hooks/flow-order-guard.mjs",
        "hooks/flow-step-guard.mjs",
        "hooks/flow-evidence.mjs",
        # hooks/flow-requirements.json is NOT locked here — B1 broadened its testCommand allowlist
        # (a shared config change, covered by the AP2b recognition test).
        "hooks/hooks-claude.json",
        "hooks/completion-claim-guard.mjs",
        # AP2a/AP2b Codex modules (reused read-only).
        # NOTE: hooks/codex-rollout.mjs is intentionally NOT locked here — a DP-LIVE follow-up fix
        # corrected readRolloutSignals to read the real `patch_apply_end` carrier; that file is the
        # fix target, covered by its own regression test (test_patch_targets_from_patch_apply_end).
        "hooks/completion-claim-guard-codex.mjs",
        "hooks/flow-step-guard-codex.mjs",
        "hooks/codex-flow-evidence.mjs",
        "hooks/codex-write-signal.mjs",
        # AP1 command/write guards + reused pattern source (this slice edits the very
        # Bash|apply_patch block scan-write-codex.mjs lives in, so its bytes must be locked).
        "hooks/scan-write-codex.mjs",
        "hooks/scan-commit.mjs",
        "hooks/destructive-command-guard.mjs",
        "hooks/branch-guard.mjs",
        "hooks/secret-patterns.mjs",
    ]

    def test_locked_files_byte_identical_to_head(self):  # BR8
        for rel in self.BYTE_LOCKED:
            with self.subTest(file=rel):
                head = _git_show(rel)
                self.assertIsNotNone(head, f"{rel} not in HEAD")
                self.assertEqual((REPO / rel).read_text(encoding="utf-8"), head)


if __name__ == "__main__":
    unittest.main()
