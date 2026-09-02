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
FLOW_EVID = REPO / "hooks" / "flow-evidence.mjs"
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


def _exec_fc_id(cmd_argv, call_id):
    """response_item function_call exec_command carrying a call_id (A2: correlates to its output)."""
    return _line("response_item", {"type": "function_call", "name": "exec_command",
                                   "arguments": json.dumps({"cmd": cmd_argv}), "call_id": call_id})


def _fc_output(call_id, exit_code, body=""):
    """response_item function_call_output: codex-added `Exit code: N` line + (truncated) combined output.
    OFFICIAL-SOURCE (openai/codex rust-v0.142.x): the rollout persists function_call_output {call_id,
    output}; codex prepends an `Exit code: N` line. Fixture models that shape (LIVE capture pending)."""
    text = f"Exit code: {exit_code}" + (f"\n{body}" if body else "")
    return _line("response_item", {"type": "function_call_output", "call_id": call_id, "output": text})


def _exec_end_id(call_id, exit_code, aggregated_output=""):
    """event_msg exec_command_end DEFENSIVE secondary exit carrier (correlated by call_id)."""
    p = {"type": "exec_command_end", "call_id": call_id, "exit_code": exit_code}
    if aggregated_output:
        p["aggregated_output"] = aggregated_output
    return _line("event_msg", p)


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


def _patch_end(paths, success=True):
    """event_msg carrier: patch_apply_end — the shape codex-cli 0.142.0 ACTUALLY persists for a native
    apply_patch (verified live: no patch_apply_begin / function_call apply_patch is emitted)."""
    return _line("event_msg", {"type": "patch_apply_end", "success": success,
                               "changes": {p: {"type": "add", "content": ""} for p in paths}})


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


def _pp_artifact(cwd, slug, role, work_id, valid=True, ac_id="AC1"):
    """Write a per-package <slug>/<role>/<work_id>.md FILE to disk. Returns its repo-relative path."""
    d = Path(cwd) / "docs" / "agentic-sdlc" / slug / role
    d.mkdir(parents=True, exist_ok=True)
    if role == "spec":
        text = _VALID_SPEC.format(work_id=work_id, ac_id=ac_id) if valid else "# Spec\n(stub)\n"
    else:
        text = _VALID_PLAN.format(work_id=work_id, ac_id=ac_id) if valid else "## Task 1\n(todo)\n"
    (d / f"{work_id}.md").write_text(text, encoding="utf-8")
    return f"docs/agentic-sdlc/{slug}/{role}/{work_id}.md"


def _mark_write(rel):
    """Mark a path as written this session (an in-session edit signal)."""
    return _patch_begin([rel])


# ---- node drivers ----------------------------------------------------------
# Large payloads go through STDIN, not argv. The ReDoS-linearity tests build 76-110 KB commands;
# the surrounding comments assume the POSIX ~128 KB single-argv limit, but Windows CreateProcess
# caps the WHOLE command line at 32767 characters, so those tests died with
# "WinError 206: filename or extension is too long" and the ReDoS guards silently did not run on
# Windows at all. Above the threshold the args are shipped as one JSON array on stdin and
# process.argv is rebuilt inside node, so every script body below keeps using process.argv[N].
_ARGV_SAFE = 4000


def _node_argv_or_stdin(script, args):
    if sum(len(a) for a in args) <= _ARGV_SAFE:
        return ["node", "--input-type=module", "-e", script, *args], None
    wrapped = (
        "let _b='';process.stdin.setEncoding('utf8');"
        # async: the wrapped script bodies use top-level `await import(...)`.
        "process.stdin.on('data',d=>_b+=d).on('end',async()=>{"
        "process.argv=['node',...JSON.parse(_b)];"
        + script +
        "});"
    )
    return ["node", "--input-type=module", "-e", wrapped], json.dumps(list(args))


def _node(script, *args):
    argv, payload = _node_argv_or_stdin(script, args)
    r = subprocess.run(argv, input=payload,
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout


def _signals(rollout_path):
    script = ("const m = await import(%s);"
              "process.stdout.write(JSON.stringify(m.readRolloutSignals(process.argv[1])));"
              % json.dumps(ROLLOUT.as_uri()))
    return json.loads(_node(script, rollout_path))


def _is_real_run(command):
    """Drive the exported SHAPE helper isRealRunnerInvocation over the real testCommand allowlist."""
    script = ("const f = await import(%s);"
              "const re = new RegExp(f.loadRequirements().testCommand, 'i');"
              "process.stdout.write(JSON.stringify(f.isRealRunnerInvocation(process.argv[1], re)));"
              % json.dumps(FLOW_EVID.as_uri()))
    return json.loads(_node(script, command))


def _has_sig(text):
    """Drive the exported advisory test-result signature scanner outputHasTestSignature."""
    script = ("const f = await import(%s);"
              "process.stdout.write(JSON.stringify(f.outputHasTestSignature(process.argv[1])));"
              % json.dumps(FLOW_EVID.as_uri()))
    return json.loads(_node(script, text))


def _derive(rollout_path, cwd):
    script = ("const m = await import(%s);"
              "process.stdout.write(JSON.stringify(m.deriveFlowEvidence(process.argv[1], process.argv[2])));"
              % json.dumps(EVID.as_uri()))
    return json.loads(_node(script, rollout_path, str(cwd)))


def _find_artifact(cwd, role, work_id):
    """Drive the exported codex findArtifactFile over the real loaded requirements."""
    script = ("const e = await import(%s); const f = await import(%s);"
              "const r = e.findArtifactFile(process.argv[1], process.argv[2], f.loadRequirements(), process.argv[3]);"
              "process.stdout.write(JSON.stringify(r === null || r === undefined ? null : r));"
              % (json.dumps(EVID.as_uri()), json.dumps(FLOW_EVID.as_uri())))
    return json.loads(_node(script, str(cwd), role, work_id))


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

    def test_function_call_output_exit0_correlated_by_call_id(self):  # A2 substrate (OFFICIAL-SOURCE)
        sig = _signals(_write_rollout([
            _exec_fc_id(["pytest", "-q"], "call_1"),
            _fc_output("call_1", 0, "5 passed in 0.12s"),
        ]))
        run = next(r for r in sig["commandRuns"] if "pytest" in r["command"])
        self.assertEqual(run["exitCode"], 0)
        self.assertIn("5 passed", run["output"])

    def test_function_call_output_nonzero_exit_correlated(self):  # A2 substrate: exit1 parsed
        sig = _signals(_write_rollout([_exec_fc_id(["pytest"], "call_2"), _fc_output("call_2", 1, "1 failed")]))
        run = next(r for r in sig["commandRuns"] if r["command"] == "pytest")
        self.assertEqual(run["exitCode"], 1)

    def test_exec_command_end_defensive_exit_carrier(self):  # A2: exec_command_end fallback (no fc_output)
        sig = _signals(_write_rollout([_exec_fc_id(["pytest", "-q"], "call_3"), _exec_end_id("call_3", 0, "3 passed")]))
        run = next(r for r in sig["commandRuns"] if "pytest" in r["command"])
        self.assertEqual(run["exitCode"], 0)

    def test_uncorrelated_run_has_null_exit(self):  # A2: no call_id -> substrate absent (fail-open path)
        sig = _signals(_write_rollout([_exec_fc(["pytest", "-q"])]))
        run = next(r for r in sig["commandRuns"] if "pytest" in r["command"])
        self.assertIsNone(run["exitCode"])

    def test_testcommand_recognizes_common_runners(self):  # B1 — broadened testCommand allowlist
        import re
        pat = re.compile(json.loads((REPO / "hooks" / "flow-requirements.json")
                                    .read_text(encoding="utf-8"))["testCommand"])
        for cmd in ("pytest -q", "go test ./...", "make test", "npm test", "npm run test",
                    "yarn test", "pnpm test", "pnpm run test", "tox", "nox -s tests"):
            self.assertTrue(pat.search(cmd), f"testCommand should match a real test run: {cmd!r}")
        for cmd in ("make build", "npm run lint", "echo testing"):
            self.assertIsNone(pat.search(cmd), f"testCommand must not match a non-test command: {cmd!r}")

    def test_patch_targets_from_function_call_and_begin(self):  # DP-A/DP-D
        sig = _signals(_write_rollout([
            _patch_fc(_v4a_add("src/x.py")),
            _patch_begin(["docs/agentic-sdlc/specs/W.md"]),
        ]))
        self.assertIn("src/x.py", sig["editTargets"])
        self.assertIn("docs/agentic-sdlc/specs/W.md", sig["editTargets"])

    def test_patch_targets_from_patch_apply_end(self):  # DP-LIVE carrier fix (the real codex shape)
        # codex-cli 0.142.0 persists a native apply_patch as event_msg patch_apply_end (no _begin / no
        # function_call). A successful end's changes ARE in-session edit targets; a failed one is NOT.
        sig = _signals(_write_rollout([
            _patch_end(["docs/agentic-sdlc/specs/W.md", "src/app.py"]),
            _patch_end(["src/never.py"], success=False),
        ]))
        self.assertIn("docs/agentic-sdlc/specs/W.md", sig["editTargets"])
        self.assertIn("src/app.py", sig["editTargets"])
        self.assertNotIn("src/never.py", sig["editTargets"])  # failed apply wrote nothing

    def test_sed_flood_is_linear_not_redos(self):  # security: the sed scan is linear, not O(n^2) ReDoS
        import time
        path = _write_rollout([_exec_fc("sed " * 200000)])  # ~1 MB 'sed ' flood; old lookahead was ~30s+
        t = time.time()
        _signals(path)
        self.assertLess(time.time() - t, 5.0, "sed scan should be linear, not quadratic")

    def test_sed_inplace_and_tee_are_edit_targets(self):  # B3 (in-place / pipe writes, no `>` redirect)
        self.assertIn("src/app.py", _signals(_write_rollout([_exec_fc("sed -i 's/x/y/' src/app.py")]))["editTargets"])
        self.assertIn("docs/agentic-sdlc/specs/W.md",
                      _signals(_write_rollout([_exec_fc("sed -i.bak -e 'a' docs/agentic-sdlc/specs/W.md")]))["editTargets"])
        self.assertIn("out.txt", _signals(_write_rollout([_exec_fc("cat x | tee -a out.txt")]))["editTargets"])
        # a READ-ONLY sed (no -i) is NOT a write; cp/base64 stay the documented residual
        self.assertEqual(_signals(_write_rollout([_exec_fc("sed 's/x/y/' src/app.py")]))["editTargets"], [])
        self.assertEqual(_signals(_write_rollout([_exec_fc("cp a.py src/app.py")]))["editTargets"], [])

    def test_raw_redirect_write_is_an_edit_target(self):  # A1/BR4a closure (the real raw-command shape)
        # codex records a shell-redirect write as a RAW command string ({"cmd":"printf x > path"}) and
        # often BUNDLES several writes in one exec_command separated by newlines — every `>`/`>>` target
        # is surfaced as an in-session edit (so a redirect-written spec/plan is no longer invisible).
        single = _signals(_write_rollout([_exec_fc("printf '# spec' > docs/agentic-sdlc/specs/W.md")]))
        self.assertIn("docs/agentic-sdlc/specs/W.md", single["editTargets"])  # flow now activates on it
        bundled = _signals(_write_rollout([
            _exec_fc("printf a > docs/agentic-sdlc/specs/W.md\nprintf b > src/app.py"),  # two writes, one cmd
        ]))
        self.assertIn("docs/agentic-sdlc/specs/W.md", bundled["editTargets"])  # NOT just the last target
        self.assertIn("src/app.py", bundled["editTargets"])
        self.assertNotIn("err.txt", _signals(_write_rollout([_exec_fc("pytest 2> err.txt")]))["editTargets"])

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


# ---- A2: SHAPE gate + advisory result-signature (pure, cross-runtime helpers) ----
class TestShapeAndSignatureHelpers(unittest.TestCase):
    def test_shape_rejects_noop_printers(self):  # `echo pytest` / `echo "...5 passed..."` are not real runs
        for cmd in ("echo pytest", 'echo "pytest: 5 passed"', "printf 'pytest'", "cat pytest",
                    ": pytest", "true && echo pytest", "# pytest"):
            self.assertFalse(_is_real_run(cmd), f"forged run must not qualify: {cmd!r}")

    def test_shape_rejects_assignment_and_quoted_and_substitution_forgeries(self):  # A2 security fix (Loop B)
        # A no-op that merely MENTIONS a runner must not qualify: a bare assignment named after a runner,
        # a runner name hidden in a command-substitution value, or a runner in quoted DATA a printer emits.
        for cmd in ("pytest=1", "tox=1", "pytest=echo",
                    "x=$(echo pytest)", "x=`echo pytest`",
                    "echo ';pytest'", 'echo "see |pytest docs"'):
            self.assertFalse(_is_real_run(cmd), f"forged run must not qualify: {cmd!r}")

    def test_shape_accepts_real_runner_invocations(self):  # a segment that actually STARTS with a runner
        for cmd in ("pytest -q", "cd repo && pytest", "python -m pytest -q", "python3 -m unittest",
                    "py -3 -m unittest tests.test_app", "VENV=1 python -m pytest",
                    "go test ./...", "make test", "npm test", "pytest --version"):
            self.assertTrue(_is_real_run(cmd), f"real runner invocation must qualify: {cmd!r}")

    def test_shape_python_m_runner_recognized(self):  # HB7: python -m <runner> is not a bare `python`
        self.assertTrue(_is_real_run("python -m pytest"))
        self.assertFalse(_is_real_run("python -m pip install x"))  # a non-runner module

    def test_shape_is_linear_not_redos(self):  # AC8: shape strip/split is linear
        # ~100 KB (under the 128 KB single-argv limit); a catastrophic-backtracking pattern would hang
        # on far fewer repeats, so this still guards ReDoS while staying well under argv size limits.
        import time
        t = time.time()
        _is_real_run(("echo " * 20000) + "pytest")
        self.assertLess(time.time() - t, 5.0)

    def test_signature_matches_common_frameworks(self):
        for out in ("5 passed in 0.1s", "1 failed, 2 passed", "OK", "FAILED (failures=1)",
                    "test result: ok. 3 passed", "3 passing", "ok  \texample 0.01s"):
            self.assertTrue(_has_sig(out), f"should recognize a result signature: {out!r}")
        for out in ("pytest 8.0.0", "hello world", "usage: pytest [options]"):
            self.assertFalse(_has_sig(out), f"non-result text must not match: {out!r}")

    def test_signature_is_linear_not_redos(self):  # AC8
        import time
        t = time.time()
        _has_sig(("a " * 40000) + "passed")  # ~80 KB, under the 128 KB single-argv limit
        self.assertLess(time.time() - t, 5.0)


# ---- AC1..AC3, AC10..AC14, AC24, AC26, AC30..AC32: pure derivation ----------
class TestFlowEvidenceDerivation(_Tmp):
    def test_valid_spec_plan_only_tests_missing(self):  # AC1
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=True)
        p = _artifact(cwd, "plan", "W", valid=True)
        roll = _write_rollout([_mark_write(s), _mark_write(p), _src_patch()])
        self.assertEqual(_derive(roll, cwd)["missingBlockSteps"], ["tests"])

    def test_correlated_nonzero_exit_no_longer_satisfies_tests(self):  # A2/HB2: DELIBERATELY reverses AP2b
        # AP2b's contract was "exit code never inspected" (a matched test command satisfied regardless of
        # exit; the old test asserted a nonzero-exit run STILL satisfied). A2 flow-STEP now correlates the
        # run's codex `Exit code:` line by call_id: a real runner that exited NONZERO is a RED run and no
        # longer satisfies the tests step (GREEN is the obligation). flow-ORDER stays exit-agnostic
        # (a TDD RED run still counts for ordering) — asserted in test_codex_flow_order_guard.
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=True)
        p = _artifact(cwd, "plan", "W", valid=True)
        roll = _write_rollout([_mark_write(s), _mark_write(p), _src_patch(),
                               _exec_fc_id(["python3", "-m", "pytest"], "c1"), _fc_output("c1", 1, "1 failed")])
        self.assertEqual(_derive(roll, cwd)["missingBlockSteps"], ["tests"])

    def test_real_green_run_satisfies_tests(self):  # A2 AC2: exit0 + result signature -> satisfied
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=True)
        p = _artifact(cwd, "plan", "W", valid=True)
        roll = _write_rollout([_mark_write(s), _mark_write(p), _src_patch(),
                               _exec_fc_id("python -m pytest -q", "c1"), _fc_output("c1", 0, "5 passed in 0.10s")])
        self.assertEqual(_derive(roll, cwd)["missingBlockSteps"], [])

    def test_cd_prefixed_real_green_run_satisfies_tests(self):  # A2 edge: `cd repo && pytest`
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=True)
        p = _artifact(cwd, "plan", "W", valid=True)
        roll = _write_rollout([_mark_write(s), _mark_write(p), _src_patch(),
                               _exec_fc_id("cd repo && pytest", "c1"), _fc_output("c1", 0, "3 passed")])
        self.assertEqual(_derive(roll, cwd)["missingBlockSteps"], [])

    def test_echo_pytest_does_not_satisfy_tests_shape(self):  # A2 AC1: `echo pytest` (exit0) closed by SHAPE
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=True)
        p = _artifact(cwd, "plan", "W", valid=True)
        roll = _write_rollout([_mark_write(s), _mark_write(p), _src_patch(),
                               _exec_fc_id(["echo", "pytest"], "c1"), _fc_output("c1", 0, "pytest")])
        self.assertEqual(_derive(roll, cwd)["missingBlockSteps"], ["tests"])

    def test_echo_faked_result_line_does_not_satisfy_shape_before_output(self):  # A2: SHAPE gates before OUTPUT
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=True)
        p = _artifact(cwd, "plan", "W", valid=True)
        roll = _write_rollout([_mark_write(s), _mark_write(p), _src_patch(),
                               _exec_fc_id(["echo", "pytest: 5 passed"], "c1"), _fc_output("c1", 0, "pytest: 5 passed")])
        self.assertEqual(_derive(roll, cwd)["missingBlockSteps"], ["tests"])

    def test_version_invocation_satisfies_fail_open_signature(self):  # A2 DP-A2-SIG residual: --version accepted
        # Accepted tradeoff: shape+exit0 satisfy; a missing result-signature does NOT block (truncation-safe).
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=True)
        p = _artifact(cwd, "plan", "W", valid=True)
        roll = _write_rollout([_mark_write(s), _mark_write(p), _src_patch(),
                               _exec_fc_id("pytest --version", "c1"), _fc_output("c1", 0, "pytest 8.0.0")])
        self.assertEqual(_derive(roll, cwd)["missingBlockSteps"], [])

    def test_substrate_absent_shape_only_satisfies(self):  # A2 AC5: no function_call_output -> fail-open
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=True)
        p = _artifact(cwd, "plan", "W", valid=True)
        roll = _write_rollout([_mark_write(s), _mark_write(p), _src_patch(), _exec_fc_id("pytest -q", "c1")])
        self.assertEqual(_derive(roll, cwd)["missingBlockSteps"], [])

    def test_correlation_faked_echo_plus_real_failing_run_not_satisfied(self):  # A2 AC6: no borrowing exit codes
        cwd = self._cwd()
        s = _artifact(cwd, "spec", "W", valid=True)
        p = _artifact(cwd, "plan", "W", valid=True)
        roll = _write_rollout([_mark_write(s), _mark_write(p), _src_patch(),
                               _exec_fc_id(["echo", "pytest"], "A"), _fc_output("A", 0, "pytest"),
                               _exec_fc_id("pytest", "B"), _fc_output("B", 1, "1 failed")])
        self.assertEqual(_derive(roll, cwd)["missingBlockSteps"], ["tests"])

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

    # ---- per-package layout (work-package-artifact-resolution: AC12/AC14/AC15) ----
    def test_per_package_spec_plan_detected_codex(self):  # AC15
        cwd = self._cwd()
        s = _pp_artifact(cwd, "work-x", "spec", "work-x", valid=True)
        p = _pp_artifact(cwd, "work-x", "plan", "work-x", valid=True)
        roll = _write_rollout([_mark_write(s), _mark_write(p), _src_patch()])
        self.assertEqual(_derive(roll, cwd)["missingBlockSteps"], ["tests"])

    def test_per_package_reserved_slug_not_detected_codex(self):  # AC14/BR11
        cwd = self._cwd()
        # slug 'plan' is reserved -> docs/agentic-sdlc/plan/spec/x.md does NOT activate.
        roll = _write_rollout([_mark_write("docs/agentic-sdlc/plan/spec/x.md"), _src_patch()])
        out = _derive(roll, cwd)
        self.assertFalse(out["flow"])
        self.assertEqual(out["missingBlockSteps"], [])

    def test_per_package_evidence_not_activating_codex(self):  # AC12
        cwd = self._cwd()
        # an evidence write is never a trigger (perPackageRole -> null for the evidence subdir).
        roll = _write_rollout([_mark_write("docs/agentic-sdlc/work-x/evidence/work-x.md"), _src_patch()])
        out = _derive(roll, cwd)
        self.assertFalse(out["flow"])
        self.assertEqual(out["missingBlockSteps"], [])

    def test_per_package_findartifact_deterministic_across_duplicate_slugs_codex(self):  # Finding-4
        cwd = self._cwd()
        _pp_artifact(cwd, "a-pkg", "spec", "work-x", valid=True)
        _pp_artifact(cwd, "b-pkg", "spec", "work-x", valid=True)  # both hold work-x.md
        first = _find_artifact(cwd, "spec", "work-x")
        self.assertIsNotNone(first)
        self.assertTrue(first.replace("\\", "/").endswith("a-pkg/spec/work-x.md"), first)  # sorted-first
        for _ in range(3):
            self.assertEqual(_find_artifact(cwd, "spec", "work-x"), first)  # deterministic

    def test_missing_per_package_still_reported_codex(self):
        cwd = self._cwd()
        s = _pp_artifact(cwd, "work-x", "spec", "work-x", valid=False)  # stub fails strict
        roll = _write_rollout([_mark_write(s), _src_patch()])
        self.assertIn("spec", _derive(roll, cwd)["missingBlockSteps"])


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

    def test_blocks_when_tests_only_echoed_under_env(self):  # A2: `echo pytest` does not satisfy -> block
        cwd = self._cwd()
        lines = self._missing_tests_fixture(cwd, extra=[_exec_fc_id(["echo", "pytest"], "c1"),
                                                        _fc_output("c1", 0, "pytest")])
        out = _run_hook(self._stop(cwd, lines), {"AGENTIC_FLOW_GATE_BLOCK": "true"})
        self.assertIn('"decision":"block"', out.replace(" ", ""))

    def test_silent_when_real_green_run_under_env(self):  # A2: exit0 real run -> satisfied -> silent
        cwd = self._cwd()
        lines = self._missing_tests_fixture(cwd, extra=[_exec_fc_id("python -m pytest -q", "c1"),
                                                        _fc_output("c1", 0, "7 passed")])
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
        # hooks/flow-evidence.mjs is NOT locked here — the AP2 "regression surface untouched"
        # guarantee is intentionally SUPERSEDED for it by work-package-artifact-resolution
        # (per-package recognition + Claude Stop co-located pairing); its new behavior is covered by
        # test_flow_guards / test_codex_flow_step_guard.
        # hooks/flow-requirements.json is NOT locked here — B1 deliberately broadened its testCommand
        # allowlist (a shared Claude+Codex config change, covered by its own recognition test).
        # hooks/hooks-claude.json RELEASED by the 2026-08-22 guard-bypass fix: its Bash-only matcher
        # left every command guard inert on a Windows host without Git Bash, and its
        # `if: Bash(git commit*)` filters never started the hook for a git alias. Covered by
        # tests/test_secret_guard_bypasses.py::TestGuardWiring.
        "hooks/completion-claim-guard.mjs",
        "hooks/completion-claim-guard-codex.mjs",
    ]

    def test_locked_files_byte_identical_to_head(self):  # AC18
        for rel in self.BYTE_LOCKED:
            with self.subTest(file=rel):
                head = _git_show(rel)
                self.assertIsNotNone(head, f"{rel} not in HEAD")
                # The public skill-ID migration is the only permitted delta. After the rename is
                # committed, the replacement is a no-op and this returns to an exact HEAD lock.
                expected = head.replace("implementasyon-control", "implementation-control")
                self.assertEqual((REPO / rel).read_text(encoding="utf-8"), expected)

    def test_codex_pretooluse_sessionstart_unchanged(self):  # AC18 (additive-only since AP2c)
        # AP2c additively appends flow-order-guard-codex.mjs to the Bash|apply_patch PreToolUse
        # block, so strict PreToolUse == HEAD is no longer the contract. Relaxed to additive-only:
        # SessionStart unchanged, the Bash command-guard block unchanged, and the scan-write-codex
        # handler dict unchanged (the new flow-order handler is the only permitted addition, asserted
        # positively by tests/test_codex_flow_order_guard.py::test_pretooluse_array_has_both_guards).
        cur = json.loads(CODEX_CFG.read_text(encoding="utf-8"))
        head = json.loads(_git_show("hooks/hooks-codex.json"))
        self.assertEqual(cur["hooks"]["SessionStart"], head["hooks"]["SessionStart"])
        cur_bash = [b for b in cur["hooks"]["PreToolUse"] if b.get("matcher") == "Bash"]
        head_bash = [b for b in head["hooks"]["PreToolUse"] if b.get("matcher") == "Bash"]
        self.assertEqual(cur_bash, head_bash)

        def _scan_handler(cfg):
            for b in cfg["hooks"]["PreToolUse"]:
                if b.get("matcher") == "Bash|apply_patch":
                    return [h for h in b["hooks"] if "scan-write-codex.mjs" in h["command"]]
            return []

        self.assertEqual(_scan_handler(cur), _scan_handler(head))

    def test_existing_completion_claim_stop_handler_unchanged(self):  # AC18
        cur = json.loads(CODEX_CFG.read_text(encoding="utf-8"))
        head = json.loads(_git_show("hooks/hooks-codex.json"))
        head_handlers = [h for blk in head["hooks"]["Stop"] for h in blk["hooks"]]
        cur_handlers = [h for blk in cur["hooks"]["Stop"] for h in blk["hooks"]]
        head_cc = [h for h in head_handlers if "completion-claim-guard-codex.mjs" in h["command"]]
        cur_cc = [h for h in cur_handlers if "completion-claim-guard-codex.mjs" in h["command"]]
        self.assertEqual(cur_cc, head_cc)


# ---- B5-AC18 (DP-XCONSUMER): the multi-file completeness fix's cross-consumer effect ----
class TestB5CrossConsumer(_Tmp):
    """B5-AC18 (spec codex-flow-order-writeform-symmetry): the multi-file `sed`/`tee` completeness
    fix widens the SHARED readRolloutSignals().editTargets, which flow-STEP also reads. A single
    command writing BOTH an artifact and source now activates the flow-step block where HEAD (last-
    operand-only) was silent. This is an ACCEPTED correctness improvement (DP-XCONSUMER option a); the
    flow-step guard's own bytes are unchanged (byte-lock holds)."""

    def test_multifile_sed_activates_flowstep_block(self):  # B5-AC18
        cwd = self._cwd()
        # One `sed -i` writing an artifact (specs/W.md) AND source (src/app.py). At HEAD only the LAST
        # token (src/app.py) surfaced -> no artifact workId -> flow:false. After the fix both operands
        # surface -> work W active + a source edit -> BLOCK with spec/plan/tests missing (no on-disk W).
        roll = _write_rollout([_exec_fc(["bash", "-lc",
                                         "sed -i 's/x/y/' docs/agentic-sdlc/specs/W.md src/app.py"])])
        out = _derive(roll, cwd)
        self.assertTrue(out["flow"])
        self.assertIn("W", out["workIds"])
        self.assertTrue({"spec", "plan", "tests"}.issubset(set(out["missingBlockSteps"])),
                        out["missingBlockSteps"])

    def test_single_file_sed_flowstep_unchanged(self):  # B5-AC18 (containment: non-multi-file case unchanged)
        # A single-file `sed -i` on source alone must behave exactly as HEAD: a source edit with no
        # active workId -> flow:false (this is the containment guard proving only the multi-file
        # artifact+source case flips, not ordinary single-file sed).
        cwd = self._cwd()
        roll = _write_rollout([_exec_fc(["bash", "-lc", "sed -i 's/x/y/' src/app.py"])])
        out = _derive(roll, cwd)
        self.assertFalse(out["flow"])
        self.assertEqual(out["missingBlockSteps"], [])


if __name__ == "__main__":
    unittest.main()
