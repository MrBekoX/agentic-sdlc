"""Regression tests for the 2026-11-18 bug audit, slice FH (flow, evidence and completion-claim hooks).

Each test is named after the audited finding it pins (session-reports/2026-11-18-bug-audit-f430715.md):
FH-1 .. FH-10, SW-7, SW-9 (wiring only) and SK-10. The hooks run as real subprocesses over synthetic
Claude transcripts or Codex rollouts. Every credential-shaped value is assembled at runtime. If node is
missing the tests SKIP (never silently pass).
"""
import json
import os
import random
import shutil
import string
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
HOOKS = REPO / "hooks"
STEP_GUARD = HOOKS / "flow-step-guard.mjs"
ORDER_GUARD = HOOKS / "flow-order-guard.mjs"
ORDER_GUARD_CODEX = HOOKS / "flow-order-guard-codex.mjs"
CLAIM_GUARD = HOOKS / "completion-claim-guard.mjs"
CLAIM_GUARD_CODEX = HOOKS / "completion-claim-guard-codex.mjs"
SCAN_WRITE_CODEX = HOOKS / "scan-write-codex.mjs"
FLOW_EVID = HOOKS / "flow-evidence.mjs"
ROLLOUT = HOOKS / "codex-rollout.mjs"
WRITE_SIGNAL = HOOKS / "codex-write-signal.mjs"
CLAUDE_WIRING = HOOKS / "hooks-claude.json"

PIPE = "agentic-sdlc:agentic-sdlc-pipeline"
RCF = "agentic-sdlc:root-cause-fix"
DS = "agentic-sdlc:dispatch-strategy"
GATE = "agentic-sdlc:completion-claim-gate"
ENV_KEYS = ("AGENTIC_FLOW_GATE_BLOCK", "AGENTIC_FLOW_ORDER_BLOCK", "AGENTIC_COMPLETION_GATE_BLOCK",
            "AGENTIC_FLOW_STRICT_EVIDENCE")

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

_STUB = "---\nwork_id: {work_id}\nstatus: draft\n---\n\n# Stub\n\n{role}\n"


def _write_artifact(cwd, role, work_id, *, ac_id="AC1", valid=True):
    sub = "specs" if role == "spec" else "plans"
    d = Path(cwd) / "docs" / "agentic-sdlc" / sub
    d.mkdir(parents=True, exist_ok=True)
    if valid:
        body = (_VALID_SPEC if role == "spec" else _VALID_PLAN).format(work_id=work_id, ac_id=ac_id)
    else:
        body = _STUB.format(work_id=work_id, role=role)
    (d / f"{work_id}.md").write_text(body, encoding="utf-8")
    return f"docs/agentic-sdlc/{sub}/{work_id}.md"


# ---- Claude transcript records ---------------------------------------------------------------
def _prompt(text="go"):
    return {"type": "user", "message": {"role": "user", "content": text}}


def _text(text):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def _use(name, inp, tool_id, **extra):
    record = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tool_id, "name": name, "input": inp}]}}
    record.update(extra)
    return record


def _result(tool_id, *, is_error=False, content="ok", **extra):
    record = {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tool_id, "is_error": is_error, "content": content}]}}
    record.update(extra)
    return record


class _Calls:
    """Builds a transcript in which every call has an id and a correlated non-error result."""

    def __init__(self):
        self.events = [_prompt("build the greeting feature")]
        self.n = 0

    def call(self, name, inp):
        self.n += 1
        tool_id = "toolu_%03d" % self.n
        self.events += [_use(name, inp, tool_id), _result(tool_id)]
        return self

    def skill(self, name):
        return self.call("Skill", {"skill": name})

    def bash(self, command):
        return self.call("Bash", {"command": command})

    def powershell(self, command):
        return self.call("PowerShell", {"command": command})

    def edit(self, path):
        return self.call("Edit", {"file_path": path, "old_string": "a", "new_string": "b"})

    def write(self, path, content="x"):
        return self.call("Write", {"file_path": path, "content": content})

    def agent(self, kind):
        return self.call("Agent", {"subagent_type": kind, "prompt": "review"})

    def workflow(self):
        return self.call("Workflow", {"name": "agentic-sdlc:spec-plan-draft"})

    def text(self, text):
        self.events.append(_text(text))
        return self


def _env(extra=None, cwd=None):
    env = os.environ.copy()
    for key in ENV_KEYS:
        env.pop(key, None)
    if cwd is not None:
        env["GIT_CEILING_DIRECTORIES"] = str(Path(cwd).resolve().parent)
    if extra:
        env.update(extra)
    return env


def _run_hook(hook, payload, *, cwd=None, env_extra=None):
    proc = subprocess.run([NODE, str(hook)], input=json.dumps(payload), capture_output=True, text=True,
                          encoding="utf-8", cwd=cwd, env=_env(env_extra, cwd), timeout=120)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    out = (proc.stdout or "").strip()
    return json.loads(out) if out else {}


def _node_json(script, *args, timeout=120):
    proc = subprocess.run([NODE, "--input-type=module", "-e", script, *args], capture_output=True, text=True,
                          encoding="utf-8", timeout=timeout)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


def _node_timed(module, body, inputs, timeout=120):
    """Run `body` (JS using `m` and `s`) over each input read from a temp file; return elapsed ms.
    The inputs travel through a file because one long argv element would exceed the kernel cap.
    A run that outlives `timeout` seconds returns timeout*1000 (too slow)."""
    with tempfile.TemporaryDirectory() as td:
        data = Path(td) / "inputs.json"
        data.write_text(json.dumps(inputs), encoding="utf-8")
        script = ("import { readFileSync } from 'node:fs'; const m = await import(%s);"
                  "const inputs = JSON.parse(readFileSync(process.argv[1], 'utf8')); const t = Date.now();"
                  "for (const s of inputs) { %s }"
                  "process.stdout.write(JSON.stringify(Date.now() - t));" % (json.dumps(module.as_uri()), body))
        try:
            return _node_json(script, str(data), timeout=timeout)
        except subprocess.TimeoutExpired:
            return timeout * 1000


def _is_real_run(commands):
    script = ("const f = await import(%s); const re = new RegExp(f.loadRequirements().testCommand, 'i');"
              "process.stdout.write(JSON.stringify(JSON.parse(process.argv[1]).map("
              "(c) => f.isRealRunnerInvocation(c, re))));" % json.dumps(FLOW_EVID.as_uri()))
    return dict(zip(commands, _node_json(script, json.dumps(commands))))


def _block_ids(out):
    reason = out.get("reason", "")
    if "[" in reason and "]" in reason:
        return reason[reason.index("[") + 1:reason.index("]")].split(", ")
    return []


def _deny_reason(out):
    return out.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")


def _is_deny(out):
    return out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


def _fake_github_token():
    alphabet = string.ascii_letters + string.digits
    return "gh" + "p_" + "".join(random.choice(alphabet) for _ in range(36))


# ---- Codex rollout records ---------------------------------------------------------------------
def _rl(type_, payload):
    return json.dumps({"type": type_, "payload": payload})


def _exec_call(cmd, call_id):
    return _rl("response_item", {"type": "function_call", "name": "exec_command",
                                 "arguments": json.dumps({"cmd": cmd}), "call_id": call_id})


def _exec_out(call_id, code=0, text=""):
    return _rl("response_item", {"type": "function_call_output", "call_id": call_id,
                                 "output": f"Exit code: {code}\nWall time: 0.1 seconds\nOutput:\n{text}"})


def _patch_call(patch, call_id):
    return _rl("response_item", {"type": "function_call", "name": "apply_patch",
                                 "arguments": json.dumps({"input": patch}), "call_id": call_id})


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)

    def transcript(self, events, name="transcript.jsonl"):
        path = self.tmp / name
        path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
        return str(path)

    def rollout(self, lines, name="rollout.jsonl"):
        path = self.tmp / name
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(path)

    def project(self, *parts):
        d = self.tmp.joinpath("proj", *parts)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def step(self, events, *, cwd=None, block=True, last=None):
        cwd = cwd or self.project()
        payload = {"transcript_path": self.transcript(events), "stop_hook_active": False}
        if last is not None:
            payload["last_assistant_message"] = last
        return _run_hook(STEP_GUARD, payload, cwd=str(cwd),
                         env_extra={"AGENTIC_FLOW_GATE_BLOCK": "true"} if block else None)

    def order(self, events, tool_input, *, tool_name=None, tool_use_id=None, cwd=None, block=True):
        cwd = cwd or self.project()
        payload = {"tool_input": tool_input, "transcript_path": self.transcript(events), "cwd": str(cwd)}
        if tool_name:
            payload["tool_name"] = tool_name
        if tool_use_id:
            payload["tool_use_id"] = tool_use_id
        return _run_hook(ORDER_GUARD, payload, cwd=str(cwd),
                         env_extra={"AGENTIC_FLOW_GATE_BLOCK": "true"} if block else None)

    def codex_order(self, command, lines=None, *, tool_name="Bash", tool_use_id=None):
        cwd = self.project()
        payload = {"tool_name": tool_name, "tool_input": {"command": command}, "cwd": str(cwd),
                   "transcript_path": self.rollout(lines or [_rl("event_msg", {"type": "task_started"})])}
        if tool_use_id:
            payload["tool_use_id"] = tool_use_id
        return _run_hook(ORDER_GUARD_CODEX, payload, cwd=str(cwd), env_extra={"AGENTIC_FLOW_ORDER_BLOCK": "true"})


def _pipe_ready():
    """Pipeline active; dispatch, spec and plan satisfied, so red-first is the only open pre-edit step."""
    return _Calls().skill(PIPE).skill(DS).workflow()


def _pipe_done(c):
    """Every Stop step of the pipeline except spec and plan."""
    return c.bash("pytest -q").agent("security-reviewer").agent("implementation-auditor").text("Done.")


# ================================================================================================
@unittest.skipIf(NODE is None, "node not available")
class TestFH1ShellWritesReachClaudeFlowGuards(_Tmp):
    """FH-1: a source edit made through Bash or PowerShell is an edit for both Claude flow guards."""

    def test_fh1_stop_sees_bash_sed_source_edit(self):
        events = _Calls().skill(PIPE).bash("sed -i 's/a/b/' src/app.py").text("Done.").events
        out = self.step(events)
        self.assertEqual(out.get("decision"), "block", out)
        self.assertEqual(_block_ids(out), ["dispatch", "spec", "plan", "tests", "security", "control"])

    def test_fh1_stop_sees_bash_heredoc_source_edit(self):
        events = _Calls().skill(PIPE).bash("cat > src/app.py <<'EOF'\nprint('hi')\nEOF").text("Done.").events
        self.assertEqual(self.step(events).get("decision"), "block")

    def test_fh1_stop_sees_powershell_redirect_source_edit(self):
        events = _Calls().skill(PIPE).powershell("'print(1)' > src/app.py").text("Done.").events
        self.assertEqual(self.step(events).get("decision"), "block")

    def test_fh1_stop_stays_silent_for_shell_without_source_write(self):
        for command in ("ls -la src", "echo notes > notes.md", "grep 'a > b.py' README.md", "pytest -q"):
            with self.subTest(command=command):
                events = _Calls().skill(PIPE).bash(command).text("Done.").events
                self.assertEqual(self.step(events), {})

    def test_fh1_order_guard_denies_bash_source_write(self):
        events = _Calls().skill(RCF).events
        for command in ("sed -i 's/a/b/' src/app.py", "cat > src/app.py <<'EOF'\nx = 1\nEOF",
                        "printf 'x' | tee src/app.py", "echo x >> src/app.py"):
            with self.subTest(command=command):
                out = self.order(events, {"command": command}, tool_name="Bash")
                self.assertTrue(_is_deny(out), out)
                self.assertIn("(missing: spec, plan)", _deny_reason(out))

    def test_fh1_order_guard_denies_powershell_source_write(self):
        out = self.order(_Calls().skill(RCF).events, {"command": "'x' > src/app.py"}, tool_name="PowerShell")
        self.assertTrue(_is_deny(out), out)

    def test_fh1_order_guard_silent_for_shell_without_source_write(self):
        events = _Calls().skill(RCF).events
        for command in ("ls -la", "git status", "pytest -q", "echo x > notes.md", 'echo "x > src/app.py"',
                        "sed -i 's/a/b/' README.md", "cat src/app.py"):
            with self.subTest(command=command):
                self.assertEqual(self.order(events, {"command": command}, tool_name="Bash"), {})

    def test_fh1_order_guard_silent_outside_a_flow(self):
        out = self.order(_Calls().events, {"command": "sed -i 's/a/b/' src/app.py"}, tool_name="Bash")
        self.assertEqual(out, {})

    def test_fh1_shell_written_spec_and_plan_count_before_source_edit(self):
        events = (_Calls().skill(RCF)
                  .bash("cat > docs/agentic-sdlc/specs/w.md <<'EOF'\n# spec\nEOF")
                  .bash("cat > docs/agentic-sdlc/plans/w.md <<'EOF'\n# plan\nEOF")).events
        self.assertEqual(self.order(events, {"file_path": "src/app.py"}), {})

    def test_fh1_current_call_is_not_its_own_red_first_evidence(self):
        # The current Bash call may already sit in the transcript at PreToolUse. Its own `&& pytest`
        # runs AFTER the edit, so it must not clear red-first.
        command = "sed -i 's/a/b/' src/app.py && pytest -q"
        events = _pipe_ready().events + [_use("Bash", {"command": command}, "toolu_cur")]
        out = self.order(events, {"command": command}, tool_name="Bash", tool_use_id="toolu_cur")
        self.assertTrue(_is_deny(out), out)
        self.assertIn("(missing: red-first)", _deny_reason(out))
        # Without a tool_use_id the unresolved identical call is still not counted.
        out = self.order(events, {"command": command}, tool_name="Bash")
        self.assertTrue(_is_deny(out), out)

    def test_fh1_completed_earlier_test_run_still_clears_red_first(self):
        command = "sed -i 's/a/b/' src/app.py"
        events = _pipe_ready().bash("pytest -q").events + [_use("Bash", {"command": command}, "toolu_cur")]
        self.assertEqual(self.order(events, {"command": command}, tool_name="Bash", tool_use_id="toolu_cur"), {})

    def test_fh1_wiring_runs_flow_order_on_bash_and_powershell_without_if(self):
        wiring = json.loads(CLAUDE_WIRING.read_text(encoding="utf-8"))
        groups = [g for g in wiring["hooks"]["PreToolUse"]
                  if any("flow-order-guard.mjs" in json.dumps(h) for h in g.get("hooks", []))]
        self.assertTrue(groups, "flow-order-guard.mjs is not wired on PreToolUse")
        tokens = set()
        for group in groups:
            tokens |= set(group.get("matcher", "").split("|"))
            for hook in group["hooks"]:
                self.assertNotIn("if", hook)
        self.assertLessEqual({"Write", "Edit", "Bash", "PowerShell"}, tokens)


# ================================================================================================
@unittest.skipIf(NODE is None, "node not available")
class TestFH2TestPathIsRelativeToProject(_Tmp):
    """FH-2: test-path classification runs on the path relative to the project, not the absolute path."""

    def test_fh2_project_under_a_tests_folder_is_gated_pre_edit(self):
        cwd = self.project("tests", "myapp")
        out = self.order(_Calls().skill(RCF).events, {"file_path": str(cwd / "src" / "app.py")}, cwd=cwd)
        self.assertTrue(_is_deny(out), out)

    def test_fh2_project_under_a_test_prefixed_folder_is_gated_pre_edit(self):
        cwd = self.project("test_area", "myapp")
        out = self.order(_Calls().skill(RCF).events, {"file_path": str(cwd / "src" / "app.py")}, cwd=cwd)
        self.assertTrue(_is_deny(out), out)

    def test_fh2_project_under_a_tests_folder_is_gated_at_stop(self):
        cwd = self.project("tests", "myapp")
        events = _Calls().skill(PIPE).edit(str(cwd / "src" / "app.py")).text("Done.").events
        self.assertEqual(self.step(events, cwd=cwd).get("decision"), "block")

    def test_fh2_real_test_files_stay_exempt(self):
        cwd = self.project("tests", "myapp")
        events = _Calls().skill(RCF).events
        for path in (str(cwd / "tests" / "test_app.py"), str(cwd / "src" / "app_test.py"), "tests/test_app.py"):
            with self.subTest(path=path):
                self.assertEqual(self.order(events, {"file_path": path}, cwd=cwd), {})


# ================================================================================================
@unittest.skipIf(NODE is None, "node not available")
class TestFH3HeredocAndCommentAreNotTestRuns(_Tmp):
    """FH-3: a heredoc body or a shell comment never counts as a test run."""

    def test_fh3_heredoc_body_and_comment_are_not_runs(self):
        got = _is_real_run([
            "cat > Makefile <<'EOF'\ntest:\n\tpytest -q\nEOF",
            "cat > Makefile <<EOF\npytest -q\nEOF",
            "cat > Makefile <<-EOF\npytest -q\nEOF",
            "ls src # && pytest",
            "ls # ; pytest",
            "git commit -m 'x' # && pytest",
        ])
        self.assertEqual([c for c, real in got.items() if real], [])

    def test_fh3_real_runs_around_heredocs_and_comments_still_count(self):
        got = _is_real_run([
            "pytest -q",
            "pytest\n# done",
            "cat > notes.md <<'EOF'\nnotes\nEOF\npytest -q",
            "cat <<'EOF' > notes.md && pytest -q\nnotes\nEOF",
            "cd repo && pytest # run the suite",
        ])
        self.assertEqual([c for c, real in got.items() if not real], [])

    def test_fh3_claude_heredoc_does_not_clear_red_first(self):
        events = _pipe_ready().bash("cat > Makefile <<'EOF'\ntest:\n\tpytest -q\nEOF").events
        out = self.order(events, {"file_path": "src/app.py"})
        self.assertIn("(missing: red-first)", _deny_reason(out))

    def test_fh3_claude_comment_does_not_satisfy_tests_at_stop(self):
        c = _Calls().skill(PIPE).skill(DS).workflow().edit("src/app.py").bash("ls src # && pytest")
        out = self.step(c.agent("security-reviewer").agent("implementation-auditor").text("Done.").events)
        self.assertEqual(_block_ids(out), ["tests"])

    def test_fh3_codex_heredoc_is_not_prior_test_evidence(self):
        lines = [_exec_call("cat > Makefile <<'EOF'\ntest:\n\tpytest -q\nEOF", "c1"), _exec_out("c1")]
        self.assertTrue(_is_deny(self.codex_order("sed -i 's/a/b/' src/app.py", lines)))

    def test_fh3_codex_comment_is_not_prior_test_evidence(self):
        lines = [_exec_call("ls src # ; pytest", "c1"), _exec_out("c1")]
        self.assertTrue(_is_deny(self.codex_order("sed -i 's/a/b/' src/app.py", lines)))


# ================================================================================================
@unittest.skipIf(NODE is None, "node not available")
class TestFH4StopIsScopedToThisSessionsWork(_Tmp):
    """FH-4: the Claude Stop spec/plan steps validate this session's work ids, not any file on disk."""

    def _done(self, c):
        return c.skill(DS).bash("pytest -q").edit("src/app.py").bash("pytest -q") \
            .agent("security-reviewer").agent("implementation-auditor").text("Done.").events

    def test_fh4_old_valid_artifacts_do_not_satisfy_a_session_that_wrote_none(self):
        cwd = self.project()
        _write_artifact(cwd, "spec", "old-unrelated-work")
        _write_artifact(cwd, "plan", "old-unrelated-work")
        out = self.step(self._done(_Calls().skill(PIPE)), cwd=cwd)
        self.assertEqual(_block_ids(out), ["spec", "plan"], out)

    def test_fh4_old_valid_artifacts_do_not_hide_this_sessions_stubs(self):
        cwd = self.project()
        _write_artifact(cwd, "spec", "old-unrelated-work")
        _write_artifact(cwd, "plan", "old-unrelated-work")
        spec = _write_artifact(cwd, "spec", "new", valid=False)
        plan = _write_artifact(cwd, "plan", "new", valid=False)
        out = self.step(self._done(_Calls().skill(PIPE).write(spec).write(plan)), cwd=cwd)
        self.assertEqual(_block_ids(out), ["spec", "plan"], out)

    def test_fh4_flat_plan_pairs_with_its_own_spec(self):
        cwd = self.project()
        _write_artifact(cwd, "spec", "aaa-old", ac_id="AC9")  # sorts first, covers an AC the plan does not
        spec = _write_artifact(cwd, "spec", "zzz-new", ac_id="AC1")
        plan = _write_artifact(cwd, "plan", "zzz-new", ac_id="AC1")
        out = self.step(self._done(_Calls().skill(PIPE).write(spec).write(plan)), cwd=cwd)
        self.assertEqual(out, {})

    def test_fh4_valid_artifacts_written_this_session_satisfy(self):
        cwd = self.project()
        spec = _write_artifact(cwd, "spec", "w1")
        plan = _write_artifact(cwd, "plan", "w1")
        out = self.step(self._done(_Calls().skill(PIPE).write(spec).write(plan)), cwd=cwd)
        self.assertEqual(out, {})

    def test_fh4_session_plan_uses_on_disk_spec_of_the_same_work_id(self):
        cwd = self.project()
        _write_artifact(cwd, "spec", "w2")  # written in an earlier session
        plan = _write_artifact(cwd, "plan", "w2")
        out = self.step(self._done(_Calls().skill(PIPE).write(plan)), cwd=cwd)
        self.assertEqual(out, {})


# ================================================================================================
@unittest.skipIf(NODE is None, "node not available")
class TestFH5CodexWriteFormsBothReaders(_Tmp):
    """FH-5: the shared recognizer sees quoted and leading redirects, `*** Move to:`, Bash
    `apply_patch <<'PATCH'` and quoted/escaped/CRLF heredocs, for the current edit and prior evidence."""

    PATCH = ("*** Begin Patch\n*** Update File: src/app.py\n@@\n-a = 1\n+a = 2\n*** End Patch")

    def test_fh5_current_edit_forms_deny(self):
        for command in ("printf 'x' > \"src/app.py\"", "echo x >> \"src/app.py\"", "echo x > 'src/app.py'",
                        ">src/app.py", ": >src/app.py",
                        "cat > \"src/app.py\" <<'EOF'\nprint(1)\nEOF",
                        "cat > src/app.py <<\"EOF\"\nprint(1)\nEOF",
                        "cat <<\\EOF > src/app.py\nprint(1)\nEOF",
                        "cat > src/app.py <<'EOF'\r\nprint(1)\r\nEOF\r\n",
                        "cat <<EOF > src/app.py\n$X\nEOF",
                        "apply_patch <<'PATCH'\n" + self.PATCH + "\nPATCH"):
            with self.subTest(command=command):
                self.assertTrue(_is_deny(self.codex_order(command)), command)

    def test_fh5_move_to_target_denies(self):
        patch = ("*** Begin Patch\n*** Update File: docs/notes.md\n*** Move to: src/app.py\n@@\n-a\n+b\n"
                 "*** End Patch")
        self.assertTrue(_is_deny(self.codex_order(patch, tool_name="apply_patch")))

    def test_fh5_quoted_or_heredoc_mentions_still_allow(self):
        for command in ('echo "x > src/app.py"', 'git commit -m "wrote > app.py"',
                        "cat <<'EOF' > notes.md\nsee > evil.py\nEOF\n",
                        "printf 'see > backup.py' > README.md", "cat x > $F.py"):
            with self.subTest(command=command):
                self.assertEqual(self.codex_order(command), {})

    def _signals(self, lines):
        script = ("const r = await import(%s);"
                  "process.stdout.write(JSON.stringify(r.readRolloutSignals(process.argv[1])));"
                  % json.dumps(ROLLOUT.as_uri()))
        return _node_json(script, self.rollout(lines))

    def test_fh5_prior_evidence_sees_the_same_forms(self):
        spec = "docs/agentic-sdlc/specs/W.md"
        add = "*** Begin Patch\n*** Add File: %s\n+# spec\n*** End Patch" % spec
        cases = {
            "bash apply_patch heredoc": [_exec_call("apply_patch <<'PATCH'\n" + add + "\nPATCH", "c1")],
            "leading redirect": [_exec_call(">" + spec, "c1")],
            "quoted redirect": [_exec_call("printf x > \"%s\"" % spec, "c1")],
            "move to": [_patch_call("*** Begin Patch\n*** Update File: notes.md\n*** Move to: %s\n@@\n-a\n+b\n"
                                    "*** End Patch" % spec, "c1")],
        }
        for name, lines in cases.items():
            with self.subTest(form=name):
                self.assertIn(spec, self._signals(lines)["editTargets"])

    def test_fh5_recognizer_is_linear_on_long_single_line_input(self):
        body = ("m.writeTargetsOf(s); m.preciseWriteTargetsOf(s); m.currentEditTargets('Bash', s);"
                "m.currentEditTargets('apply_patch', s);")
        inputs = [chunk * (400000 // len(chunk)) for chunk in
                  ("> ", "<<\\", "'a' ", '>"', "<<'E' ", "a <<E\n", "*** Move to: ", "apply_patch <<P ")]
        self.assertLess(_node_timed(ROLLOUT, body, inputs), 3000)


# ================================================================================================
@unittest.skipIf(NODE is None, "node not available")
class TestSW7CodexHeredocForms(_Tmp):
    """SW-7: `<<"EOF"`, `<<\\EOF` and CRLF heredocs are literal writes the Codex write guard scans."""

    def _scan(self, command):
        return _run_hook(SCAN_WRITE_CODEX, {"tool_name": "Bash", "tool_input": {"command": command}})

    def test_sw7_quoted_escaped_and_crlf_heredocs_are_scanned(self):
        token = _fake_github_token()
        forms = {
            "double-quoted": 'cat > .env <<"EOF"\nGITHUB_TOKEN=' + token + "\nDATA_DIR=$HOME/data\nEOF",
            "backslash": "cat > .env <<\\EOF\nGITHUB_TOKEN=" + token + "\nEOF",
            "crlf": "cat > .env <<'EOF'\r\nGITHUB_TOKEN=" + token + "\r\nEOF\r\n",
        }
        for name, command in forms.items():
            with self.subTest(form=name):
                self.assertTrue(_is_deny(self._scan(command)), name)

    def test_sw7_controls_unchanged(self):
        token = _fake_github_token()
        self.assertTrue(_is_deny(self._scan("cat > .env <<'EOF'\nGITHUB_TOKEN=" + token + "\nEOF")))
        self.assertEqual(self._scan("cat > .env <<'EOF'\nDATA_DIR=/srv/data\nEOF"), {})
        # An unquoted delimiter still expands, so its body stays unread (bounded posture, unchanged).
        script = ("const m = await import(%s);"
                  "process.stdout.write(JSON.stringify(m.extractWrittenContent('Bash', process.argv[1])));"
                  % json.dumps(WRITE_SIGNAL.as_uri()))
        got = _node_json(script, "cat > .env <<EOF\nA=$HOME\nEOF")
        self.assertEqual((got["addedContent"], got["parsed"]), ("", False))


# ================================================================================================
@unittest.skipIf(NODE is None, "node not available")
class TestFH6CodexCurrentCallIsNotPriorEvidence(_Tmp):
    """FH-6: the Codex flow-order gate never counts the edit command's own `&& pytest` as a prior run."""

    COMMAND = "sed -i 's/a/b/' src/app.py && pytest -q"

    def test_fh6_current_call_by_id_is_excluded(self):
        lines = [_exec_call(self.COMMAND, "call_cur")]
        self.assertTrue(_is_deny(self.codex_order(self.COMMAND, lines, tool_use_id="call_cur")))

    def test_fh6_unresolved_identical_call_is_excluded_without_an_id(self):
        lines = [_exec_call(self.COMMAND, "call_cur")]
        self.assertTrue(_is_deny(self.codex_order(self.COMMAND, lines)))

    def test_fh6_completed_earlier_run_still_counts(self):
        lines = [_exec_call("pytest -q", "c1"), _exec_out("c1", 1, "1 failed"), _exec_call(self.COMMAND, "call_cur")]
        self.assertEqual(self.codex_order(self.COMMAND, lines, tool_use_id="call_cur"), {})


# ================================================================================================
@unittest.skipIf(NODE is None, "node not available")
class TestFH7GateEvidenceIsAnExactSkillCall(_Tmp):
    """FH-7: only a non-errored Skill call to completion-claim-gate (exact name) counts as the gate."""

    CLAIM = "All tests pass and it is ready to merge."

    def _claim(self, middle):
        events = [_prompt("fix it")] + middle + [_text(self.CLAIM)]
        return _run_hook(CLAIM_GUARD, {"transcript_path": self.transcript(events)},
                         env_extra={"AGENTIC_COMPLETION_GATE_BLOCK": "true"})

    def test_fh7_lookalikes_and_errors_do_not_count(self):
        cases = {
            "args mention": [_use("Skill", {"skill": "agentic-sdlc:implementation-control",
                                            "args": "do not run completion-claim-gate yet"}, "s1"), _result("s1")],
            "errored call": [_use("Skill", {"skill": GATE}, "s1"),
                             _result("s1", is_error=True, content="Unknown skill", toolUseResult="Error: Unknown skill")],
            "lookalike": [_use("Skill", {"skill": "other-plugin:no-completion-claim-gate"}, "s1"), _result("s1")],
            "prompt mention": [_use("Agent", {"subagent_type": "general-purpose",
                                              "prompt": "Skill completion-claim-gate later"}, "a1"), _result("a1")],
        }
        for name, middle in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self._claim(middle).get("decision"), "block")

    def test_fh7_real_gate_call_still_counts(self):
        for name in (GATE, "completion-claim-gate"):
            with self.subTest(skill=name):
                self.assertEqual(self._claim([_use("Skill", {"skill": name}, "s1"), _result("s1")]), {})


# ================================================================================================
CLAIMS = (
    "All tests passed.",
    "All 42 tests pass.",
    "All the tests are passing now.",
    "The implementation is completed.",
    "Fixed the incomplete UTF-8 handling. All tests pass and it is ready to merge.",
    "Done and verified; the feature is ready for review.",
    "Tüm testler geçti.",
    "Bütün testler başarıyla geçiyor.",
    "Uygulama tamamlandı.",
    "Görev tamamlandı ve doğrulandı.",
    "Değişiklik birleştirmeye hazır.",
)
NON_CLAIMS = (
    "Is this ready to merge?",
    "Ready to merge, or should I add docs first?",
    "If all tests pass, it will be ready to merge.",
    "It will be ready to merge once CI is green.",
    "Once CI is green it is ready to merge.",
    'The checklist item "all tests pass" is still open.',
    "The script prints `All tests passed` on success.",
    "Not all tests pass yet.",
    "It isn't ready to merge.",
    "All tests pass, but the implementation is not yet complete.",
    "Birleştirmeye hazır mı?",
    "Değişiklik henüz birleştirmeye hazır değil.",
    "Testler henüz geçmedi.",
    "Uygulama tamamlanmadı.",
    "Eğer tüm testler geçerse birleştirmeye hazır olur.",
)


@unittest.skipIf(NODE is None, "node not available")
class TestFH8ClaimPatterns(_Tmp):
    """FH-8: inflected and Turkish claims are caught; questions, conditionals, quotes and scoped
    negations are not claims. Claude guard, Codex guard and the offline strict reader agree."""

    def _claude(self, text):
        events = [_prompt("fix it"), _text(text)]
        return _run_hook(CLAIM_GUARD, {"transcript_path": self.transcript(events), "last_assistant_message": text},
                         env_extra={"AGENTIC_COMPLETION_GATE_BLOCK": "true"})

    def _codex(self, text):
        lines = [_rl("event_msg", {"type": "task_complete", "last_agent_message": text})]
        return _run_hook(CLAIM_GUARD_CODEX, {"transcript_path": self.rollout(lines), "last_assistant_message": text,
                                             "cwd": str(self.project())},
                         env_extra={"AGENTIC_COMPLETION_GATE_BLOCK": "true"})

    def test_fh8_claims_are_caught_by_both_guards(self):
        for text in CLAIMS:
            with self.subTest(text=text):
                self.assertEqual(self._claude(text).get("decision"), "block", "claude")
                self.assertEqual(self._codex(text).get("decision"), "block", "codex")

    def test_fh8_non_claims_stay_silent_in_both_guards(self):
        for text in NON_CLAIMS:
            with self.subTest(text=text):
                self.assertEqual(self._claude(text), {}, "claude")
                self.assertEqual(self._codex(text), {}, "codex")

    def test_fh8_offline_reader_agrees(self):
        script = ("const r = await import(%s);"
                  "process.stdout.write(JSON.stringify(JSON.parse(process.argv[1]).map((t) => r.completionClaimed(t))));"
                  % json.dumps(ROLLOUT.as_uri()))
        texts = list(CLAIMS) + list(NON_CLAIMS)
        got = _node_json(script, json.dumps(texts))
        self.assertEqual(got, [True] * len(CLAIMS) + [False] * len(NON_CLAIMS))

    def test_fh8_claim_reader_is_linear_on_long_input(self):
        long_inputs = ["all green " * 40000, " 'a" * 130000, '"' + "x " * 200000, "if all green, " * 30000,
                       "Tüm testler " * 30000, "`" + "a" * 400000, "all tests " * 40000 + "x",
                       "will " * 80000 + "all green", "all green, " * 36000 + "once", "> " * 200000]
        self.assertLess(_node_timed(ROLLOUT, "m.completionClaimed(s);", long_inputs), 3000)


# ================================================================================================
RUNS = (
    "/bin/bash -lc 'pytest -q'", 'bash -lc "npm test"', "sh -c 'pytest'", 'powershell -Command "pytest"',
    "pwsh -NoProfile -Command pytest", "cmd /c npm test", ".venv/bin/pytest -q", "./node_modules/.bin/jest",
    "uv run pytest", "poetry run pytest -q", "pipenv run pytest", "npx jest", "npx vitest run", "pnpm exec vitest",
    "bunx vitest", "timeout 600 pytest", "time pytest", "time -p pytest", "env CI=1 pytest", "nice -n 10 pytest",
    "CI=1 timeout 60 python -m pytest", "python -I -m pytest", "python3 -X dev -m pytest", "python -B -W error -m pytest",
    "node --test", "node --test tests/", "bun test", "dotnet test", "./gradlew test", "gradlew.bat test",
    ".venv\\Scripts\\pytest.exe",
)
NOT_RUNS = (
    "echo pytest", "bash -c 'echo pytest'", "timeout 5 echo pytest", "env pytest=1", "uv run python app.py",
    "npx eslint .", "node app.js --test", "node --version", "python -c 'import pytest'", "time echo pytest",
    "bash script.sh pytest", "powershell -File run.ps1 pytest", "nice ls pytest", "dotnet build",
    "pytest.ini", "tox.ini",
)


@unittest.skipIf(NODE is None, "node not available")
class TestFH9SK10RunnerRecognition(_Tmp):
    """FH-9 / SK-10: test runs behind common prefixes, wrappers and launchers are recognised; printers and
    other programs are not."""

    def test_fh9_wrapped_and_launched_runners_count(self):
        got = _is_real_run(list(RUNS))
        self.assertEqual([c for c, real in got.items() if not real], [])

    def test_fh9_non_runners_do_not_count(self):
        got = _is_real_run(list(NOT_RUNS))
        self.assertEqual([c for c, real in got.items() if real], [])

    def test_sk10_node_test_clears_red_first(self):
        events = _pipe_ready().bash("node --test").events
        self.assertEqual(self.order(events, {"file_path": "src/app.py"}), {})

    def test_fh9_shape_check_is_linear_on_long_single_line_input(self):
        body = "m.isRealRunnerInvocation(s, new RegExp(m.loadRequirements().testCommand, 'i'));"
        long_inputs = ["bash -c " * 50000, "env " * 100000 + "pytest", "timeout " * 50000, "'a " * 130000,
                       "<<'E' " * 60000, "x\\" * 200000, "pwsh -c " * 50000, "a=b " * 100000 + "x",
                       "nice -n " * 50000, "uv run " * 60000, "python -X " * 40000 + "-m pytest",
                       "sh -c '" * 60000, "cmd /c " * 60000]
        self.assertLess(_node_timed(FLOW_EVID, body, long_inputs), 3000)


# ================================================================================================
@unittest.skipIf(NODE is None, "node not available")
class TestFH10SidechainSkillDoesNotActivate(_Tmp):
    """FH-10: a sub-agent's (sidechain) Skill call does not activate the parent's flow."""

    def _sidechain(self):
        return [
            _prompt("tweak the greeting"),
            _use("Agent", {"subagent_type": "general-purpose", "prompt": "investigate"}, "a1"),
            _use("Skill", {"skill": PIPE}, "s1", isSidechain=True),
            _result("s1", isSidechain=True),
            _result("a1"),
        ]

    def test_fh10_sidechain_skill_does_not_activate_order_gate(self):
        self.assertEqual(self.order(self._sidechain(), {"file_path": "src/app.py"}), {})

    def test_fh10_sidechain_skill_does_not_activate_stop_gate(self):
        events = self._sidechain() + [_use("Edit", {"file_path": "src/app.py"}, "e1"), _result("e1"), _text("Done.")]
        self.assertEqual(self.step(events), {})

    def test_fh10_top_level_skill_still_activates(self):
        out = self.order(_Calls().skill(PIPE).events, {"file_path": "src/app.py"})
        self.assertTrue(_is_deny(out), out)


# ================================================================================================
class TestSW9NotebookEditWiring(unittest.TestCase):
    """SW-9 (wiring): the Claude write scan is wired on NotebookEdit too."""

    def test_sw9_scan_write_matcher_covers_notebook_edit(self):
        wiring = json.loads(CLAUDE_WIRING.read_text(encoding="utf-8"))
        matchers = [g.get("matcher", "") for g in wiring["hooks"]["PostToolUse"]
                    if any("scan-write.mjs" in json.dumps(h) for h in g.get("hooks", []))]
        self.assertTrue(matchers)
        self.assertTrue(any("NotebookEdit" in m.split("|") for m in matchers), matchers)


# ================================================================================================
# Round 2 (security review of the integrated fix diff): R2-FH-1 .. R2-FH-5.
def _timed_run(hook, payload, cwd, env_extra=None, limit=40):
    """Run a hook; return (parsed stdout or None on timeout, elapsed seconds)."""
    start = time.monotonic()
    try:
        proc = subprocess.run([NODE, str(hook)], input=json.dumps(payload), capture_output=True, text=True,
                              encoding="utf-8", cwd=str(cwd), env=_env(env_extra, cwd), timeout=limit)
    except subprocess.TimeoutExpired:
        return None, limit
    out = (proc.stdout or "").strip()
    return (json.loads(out) if out else {}), time.monotonic() - start


@unittest.skipIf(NODE is None, "node not available")
class TestR2FH1ShellAnalysisIsLinear(_Tmp):
    """R2-FH-1: one pathological Bash command in the transcript must not push a Claude flow hook past its
    timeout (where it fails open for the rest of the session). Driven through the real hook entry points."""

    GT = "echo '" + ">" * 100000 + " y'"
    HEREDOC_WORD = "true <<" + "a" * 100000

    def test_r2_fh1_redirect_run_in_transcript_keeps_order_guard_fast(self):
        events = _Calls().skill(PIPE).bash(self.GT).events
        cwd = self.project()
        out, took = _timed_run(ORDER_GUARD, {"tool_input": {"file_path": "src/app.py"}, "cwd": str(cwd),
                                             "transcript_path": self.transcript(events)},
                               cwd, {"AGENTIC_FLOW_GATE_BLOCK": "true"})
        self.assertLess(took, 15, "flow-order-guard outlived its 15 s hook timeout (fails open)")
        self.assertTrue(_is_deny(out), out)

    def test_r2_fh1_heredoc_word_in_transcript_keeps_stop_guard_fast(self):
        events = _Calls().skill(PIPE).bash(self.HEREDOC_WORD).edit("src/app.py").text("Done.").events
        cwd = self.project()
        out, took = _timed_run(STEP_GUARD, {"transcript_path": self.transcript(events), "stop_hook_active": False},
                               cwd, {"AGENTIC_FLOW_GATE_BLOCK": "true"})
        self.assertLess(took, 15, "flow-step-guard outlived a 15 s budget")
        self.assertEqual((out or {}).get("decision"), "block", out)

    def test_r2_fh1_current_pathological_command_is_fast(self):
        cwd = self.project()
        for command in (self.GT, self.HEREDOC_WORD):
            with self.subTest(command=command[:12]):
                out, took = _timed_run(ORDER_GUARD, {"tool_name": "Bash", "tool_input": {"command": command},
                                                     "cwd": str(cwd), "transcript_path": self.transcript(
                                                         _Calls().skill(PIPE).events)},
                                       cwd, {"AGENTIC_FLOW_GATE_BLOCK": "true"})
                self.assertLess(took, 15)
                self.assertEqual(out, {})

    def test_r2_fh1_shell_readers_are_linear(self):
        inputs = ["echo '" + ">" * 200000 + " y'", "true <<" + "a" * 200000, "echo " + ">a" * 100000 + " b",
                  "printf x" + " >" * 100000 + " y z", "cat <<" + "a" * 200000 + "\nx\n"]
        took = _node_timed(WRITE_SIGNAL, "m.extractWrittenContent('Bash', s); m.blankHeredocBodies(s);", inputs,
                           timeout=60)
        self.assertLess(took, 3000)
        took = _node_timed(FLOW_EVID, "m.shellWriteTargets(s); "
                                      "m.isRealRunnerInvocation(s, new RegExp(m.loadRequirements().testCommand, 'i'));",
                           inputs, timeout=60)
        self.assertLess(took, 3000)

    def test_r2_fh1_oversized_prior_command_is_never_evidence(self):
        # Beyond the per-command analysis cap a transcript command is not read at all: it is never test-run
        # evidence (nor an artifact write), whatever it looks like.
        events = _pipe_ready().bash("pytest -q # " + "x" * 140000).events
        out = self.order(events, {"file_path": "src/app.py"})
        self.assertIn("(missing: red-first)", _deny_reason(out))


@unittest.skipIf(NODE is None, "node not available")
class TestR2FH2ApplyPatchPipeScanIsLinear(unittest.TestCase):
    """R2-FH-2: a flood of `|` on a heredoc opener line must not make the apply_patch pipe check quadratic."""

    def test_r2_fh2_pipe_flood_on_heredoc_opener_is_linear(self):
        inputs = ["cat <<'EOF' " + "|" * 100000 + "\nx\nEOF", "cat <<'EOF' " + "| " * 100000 + "\nx\nEOF"]
        took = _node_timed(WRITE_SIGNAL, "m.extractWrittenContent('Bash', s);", inputs, timeout=30)
        self.assertLess(took, 3000)

    def test_r2_fh2_piped_apply_patch_still_read(self):
        patch = "*** Begin Patch\n*** Add File: src/new.py\n+x\n*** End Patch"
        script = ("const m = await import(%s);"
                  "process.stdout.write(JSON.stringify(JSON.parse(process.argv[1]).map("
                  "(c) => m.extractWrittenContent('Bash', c).targets)));" % json.dumps(WRITE_SIGNAL.as_uri()))
        got = _node_json(script, json.dumps(["cat <<'P' | apply_patch\n" + patch + "\nP",
                                             "cat <<'P' | /usr/local/bin/apply_patch\n" + patch + "\nP",
                                             "cat <<'P' | grep apply_patch\n" + patch + "\nP"]))
        self.assertEqual(got, [["src/new.py"], ["src/new.py"], []])


@unittest.skipIf(NODE is None, "node not available")
class TestR2FH3HeredocCrTerminator(unittest.TestCase):
    """R2-FH-3: a delimiter line ending in CR ends the heredoc only when bash would: when the opener's
    delimiter word itself is followed by CR. Otherwise the lines after it are still heredoc body."""

    def _scan(self, command):
        return _run_hook(SCAN_WRITE_CODEX, {"tool_name": "Bash", "tool_input": {"command": command}})

    def test_r2_fh3_cr_line_does_not_end_an_lf_heredoc(self):
        token = _fake_github_token()
        self.assertTrue(_is_deny(self._scan("cat > f <<'EOF'\nok\nEOF\r\nGITHUB_TOKEN=" + token + "\nEOF")))

    def test_r2_fh3_plain_line_does_not_end_a_crlf_heredoc(self):
        token = _fake_github_token()
        command = "cat > f <<'EOF'\r\nok\r\nEOF\nGITHUB_TOKEN=" + token + "\r\nEOF\r\n"
        self.assertTrue(_is_deny(self._scan(command)))

    def test_r2_fh3_crlf_heredoc_still_read(self):
        token = _fake_github_token()
        self.assertTrue(_is_deny(self._scan("cat > f <<'EOF'\r\nGITHUB_TOKEN=" + token + "\r\nEOF\r\n")))


@unittest.skipIf(NODE is None, "node not available")
class TestR2FH4DotSegments(_Tmp):
    """R2-FH-4: `..` segments are resolved before a path is classified, so `tests/../src/app.py` and a path
    that walks out of an artifact root are source edits."""

    def test_r2_fh4_dot_dot_paths_are_gated(self):
        events = _Calls().skill(RCF).events
        for path in ("tests/../src/app.py", "docs/agentic-sdlc/specs/../../../src/app.py", "./src/./app.py"):
            with self.subTest(path=path):
                self.assertTrue(_is_deny(self.order(events, {"file_path": path})), path)

    def test_r2_fh4_dot_dot_into_tests_stays_exempt(self):
        events = _Calls().skill(RCF).events
        for path in ("src/../tests/test_app.py", "docs/agentic-sdlc/specs/../specs/w.md"):
            with self.subTest(path=path):
                self.assertEqual(self.order(events, {"file_path": path}), {})


R2_CLAIMS = (
    "Once again, all tests pass and the feature is complete.",
    "Until today the suite was flaky; all tests pass now.",
    "I checked whether the cache works, and all tests pass.",
    "We may refactor later, but all tests pass.",
    "> All tests pass and it is ready to merge.",
)
R2_NON_CLAIMS = (
    "If CI is green, it is ready to merge.",
    "It is ready to merge if the reviewer agrees.",
    "Once CI is green it is ready to merge.",
    "Unless the cache breaks, all tests pass.",
)


@unittest.skipIf(NODE is None, "node not available")
class TestR2FH5ClaimClauseScope(_Tmp):
    """R2-FH-5: a conditional, temporal or modal word cancels a claim only inside the claim's own clause (or as
    the `If ..., <claim>` opener); a `>` line is not a quotation of someone else."""

    def test_r2_fh5_reader(self):
        script = ("const r = await import(%s);"
                  "process.stdout.write(JSON.stringify(JSON.parse(process.argv[1]).map((t) => r.completionClaimed(t))));"
                  % json.dumps(ROLLOUT.as_uri()))
        texts = list(R2_CLAIMS) + list(R2_NON_CLAIMS)
        got = dict(zip(texts, _node_json(script, json.dumps(texts))))
        self.assertEqual({t: got[t] for t in texts}, {**{t: True for t in R2_CLAIMS}, **{t: False for t in R2_NON_CLAIMS}})

    def test_r2_fh5_claude_guard_flags_once_again(self):
        text = R2_CLAIMS[0]
        out = _run_hook(CLAIM_GUARD, {"transcript_path": self.transcript([_prompt("fix it"), _text(text)]),
                                      "last_assistant_message": text},
                        env_extra={"AGENTIC_COMPLETION_GATE_BLOCK": "true"})
        self.assertEqual(out.get("decision"), "block")


# ================================================================================================
# Round 3 (second-pass review): R3-FH-1, R3-FH-2.
@unittest.skipIf(NODE is None, "node not available")
class TestR3FH1ConditionOpenerStopsAtSemicolonAndColon(_Tmp):
    """R3-FH-1: an `If ...` opening clause makes only the claims after a comma hypothetical; a `;` or `:` starts
    an independent clause, so "If you want a PR, say so; all tests pass ..." is a claim again."""

    CLAIMS = ("If you want a PR, say so; all tests pass and the task is complete.",
              "If anything is unclear, ask: all tests pass.")
    NON_CLAIMS = ("If CI is green, it is ready to merge.", "If you want, all tests pass.")

    def test_r3_fh1_reader(self):
        script = ("const r = await import(%s);"
                  "process.stdout.write(JSON.stringify(JSON.parse(process.argv[1]).map((t) => r.completionClaimed(t))));"
                  % json.dumps(ROLLOUT.as_uri()))
        texts = list(self.CLAIMS) + list(self.NON_CLAIMS)
        got = dict(zip(texts, _node_json(script, json.dumps(texts))))
        self.assertEqual(got, {**{t: True for t in self.CLAIMS}, **{t: False for t in self.NON_CLAIMS}})

    def test_r3_fh1_claude_guard_flags_after_semicolon(self):
        text = self.CLAIMS[0]
        out = _run_hook(CLAIM_GUARD, {"transcript_path": self.transcript([_prompt("fix it"), _text(text)]),
                                      "last_assistant_message": text},
                        env_extra={"AGENTIC_COMPLETION_GATE_BLOCK": "true"})
        self.assertEqual(out.get("decision"), "block")


@unittest.skipIf(NODE is None, "node not available")
class TestR3FH2OverCapShellCommandIsAPossibleEdit(_Tmp):
    """R3-FH-2: a transcript shell command over the analysis cap is not read, so it may have written a source
    file: Stop keeps the flow obligations. It still never counts as evidence."""

    BIG_WRITE = "cat > src/app.py <<'EOF'\n" + "x = 1\n" * 25000 + "EOF"  # ~150 KB, over the 128 KiB cap

    def test_r3_fh2_over_cap_write_keeps_stop_obligations(self):
        events = _Calls().skill(PIPE).bash(self.BIG_WRITE).text("Done.").events
        out = self.step(events)
        self.assertEqual(out.get("decision"), "block", out)
        self.assertEqual(_block_ids(out), ["dispatch", "spec", "plan", "tests", "security", "control"])

    def test_r3_fh2_over_cap_command_is_still_not_test_evidence(self):
        c = _Calls().skill(PIPE).skill(DS).workflow().bash("pytest -q # " + "x" * 140000)
        out = self.step(c.agent("security-reviewer").agent("implementation-auditor").text("Done.").events)
        self.assertEqual(_block_ids(out), ["tests"])

    def test_r3_fh2_under_cap_non_writing_command_stays_silent(self):
        events = _Calls().skill(PIPE).bash("ls -la src").text("Done.").events
        self.assertEqual(self.step(events), {})


if __name__ == "__main__":
    unittest.main()
