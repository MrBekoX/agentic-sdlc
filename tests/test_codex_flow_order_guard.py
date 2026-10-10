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
import hashlib
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

# LF-normalized sha256 of each locked file, as checked out from main when this lock was
# converted. A digest fails on ANY change to the file - committed or not - and its only escape
# is editing the literal below, which is greppable and shows up in review. What this replaces
# re-read its expected value from `git show HEAD:`, so on a clean checkout it compared the file
# against itself: commit c173b99 changed two of these four files and the lock never fired.
#
# Releasing a file: delete its entry here WITH the reason, and give the file its own
# behavioural regression test. That is the convention the comments in BYTE_LOCKED already
# describe; the digest is what makes skipping it visible.
LOCK_DIGESTS = {
    # The pre-edit ordering gate: whether required evidence exists before a source edit.
    "hooks/flow-order-guard.mjs":
        "f584b0c25d1b6a8a655b2bc37fbad37350ee9c80545b412d2bd49e30d6a3b646",
    # The Stop-time flow-step gate: whether a flow's required steps actually ran.
    # Rebased for Claude Code 2.1.293: last_assistant_message + background_tasks on Stop.
    "hooks/flow-step-guard.mjs":
        "e5f66136c69096748375ea1fb357b1f6282d478f9857ddca974a29853595e165",
    # The completion-claim backstop.
    # Rebased for Claude Code 2.1.293: prefer last_assistant_message; block only when caught up.
    "hooks/completion-claim-guard.mjs":
        "ad454dd5f68c2ba08583c283b444318c24892d9c3305161b913dea3bcf317c9b",
    # The Codex flow-step equivalent.
    "hooks/flow-step-guard-codex.mjs":
        "b6d05a7d8358647c2245386a8f98b19e99abcc3f0fb291d2b04b36c8317c446f",
}

# The Codex wiring this suite pins, as literals rather than as whatever HEAD happens to hold.
# Small enough to read, which is the point: a reviewer sees which guards are wired, in which
# order, with which timeouts. Removing a handler now fails - the shape these replace filtered
# two lists by name and compared the results, so deleting the guarded handler made both sides
# empty and the assertion passed.
PINNED_CODEX_BASH_BLOCK = {
    "matcher": "Bash",
    "hooks": [
        {"type": "command", "command": "node -e \"const p=require('node:path').join(process.env.PLUGIN_ROOT,'hooks','scan-commit.mjs');process.argv[1]=p;import(require('node:url').pathToFileURL(p).href)\"",
         "commandWindows": "node.exe -e \"const p=require('node:path').join(process.env.PLUGIN_ROOT,'hooks','scan-commit.mjs');process.argv[1]=p;import(require('node:url').pathToFileURL(p).href)\"",
         "timeout": 20, "statusMessage": "Secret scan (commit)..."},
        {"type": "command",
         "command": "node -e \"const p=require('node:path').join(process.env.PLUGIN_ROOT,'hooks','destructive-command-guard.mjs');process.argv[1]=p;import(require('node:url').pathToFileURL(p).href)\"",
         "commandWindows": "node.exe -e \"const p=require('node:path').join(process.env.PLUGIN_ROOT,'hooks','destructive-command-guard.mjs');process.argv[1]=p;import(require('node:url').pathToFileURL(p).href)\"",
         "timeout": 15, "statusMessage": "Destructive command guard..."},
        {"type": "command", "command": "node -e \"const p=require('node:path').join(process.env.PLUGIN_ROOT,'hooks','branch-guard.mjs');process.argv[1]=p;import(require('node:url').pathToFileURL(p).href)\"",
         "commandWindows": "node.exe -e \"const p=require('node:path').join(process.env.PLUGIN_ROOT,'hooks','branch-guard.mjs');process.argv[1]=p;import(require('node:url').pathToFileURL(p).href)\"",
         "timeout": 15, "statusMessage": "Branch guard (commit/push)..."},
    ],
}

PINNED_CODEX_SESSION_START = [
    {"matcher": "startup|resume|clear|compact",
     "hooks": [{"type": "command",
                "command": "node -e \"const p=require('node:path').join(process.env.PLUGIN_ROOT,'hooks','session-start-codex.mjs');process.argv[1]=p;import(require('node:url').pathToFileURL(p).href)\"",
                "commandWindows": "node.exe -e \"const p=require('node:path').join(process.env.PLUGIN_ROOT,'hooks','session-start-codex.mjs');process.argv[1]=p;import(require('node:url').pathToFileURL(p).href)\"",
                "timeout": 15, "statusMessage": "AGENTIC-SDLC startup context"}]},
]

PINNED_CODEX_STOP = [
    {"hooks": [
        {"type": "command",
         "command": "node -e \"const p=require('node:path').join(process.env.PLUGIN_ROOT,'hooks','completion-claim-guard-codex.mjs');process.argv[1]=p;import(require('node:url').pathToFileURL(p).href)\"",
         "commandWindows": "node.exe -e \"const p=require('node:path').join(process.env.PLUGIN_ROOT,'hooks','completion-claim-guard-codex.mjs');process.argv[1]=p;import(require('node:url').pathToFileURL(p).href)\"",
         "timeout": 20, "statusMessage": "Completion-claim gate (marker)..."},
        {"type": "command",
         "command": "node -e \"const p=require('node:path').join(process.env.PLUGIN_ROOT,'hooks','flow-step-guard-codex.mjs');process.argv[1]=p;import(require('node:url').pathToFileURL(p).href)\"",
         "commandWindows": "node.exe -e \"const p=require('node:path').join(process.env.PLUGIN_ROOT,'hooks','flow-step-guard-codex.mjs');process.argv[1]=p;import(require('node:url').pathToFileURL(p).href)\"",
         "timeout": 20, "statusMessage": "Flow-step evidence gate (codex)..."},
    ]},
]

# The Codex write guard the Codex suites pin by NAME and by VALUE, with presence asserted first.
PINNED_CODEX_SCAN_WRITE_HANDLER = {
    "type": "command",
    "command": "node -e \"const p=require('node:path').join(process.env.PLUGIN_ROOT,'hooks','scan-write-codex.mjs');process.argv[1]=p;import(require('node:url').pathToFileURL(p).href)\"",
    "commandWindows": "node.exe -e \"const p=require('node:path').join(process.env.PLUGIN_ROOT,'hooks','scan-write-codex.mjs');process.argv[1]=p;import(require('node:url').pathToFileURL(p).href)\"",
    "timeout": 20,
    "statusMessage": "Secret scan (write)...",
}


# ---- artifact bodies (must pass/fail validate_artifacts.py --strict for the RIGHT reason) ----
# Reused from the AP2b harness, calibrated so a valid body clears --strict and a stub fails it.
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
- {ac_id}: Given a valid spec written this session, when the gate runs, then the spec step passes.

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


# ---- rollout fixture helpers ----------------------------------------------
def _line(type_, payload):
    return json.dumps({"type": type_, "payload": payload})


def _exec_fc(cmd_argv):
    """response_item function_call carrier: exec_command with {cmd: argv}."""
    return _line("response_item", {"type": "function_call", "name": "exec_command",
                                   "arguments": json.dumps({"cmd": cmd_argv})})


def _exec_fc_id(cmd_argv, call_id):
    """response_item function_call exec_command carrying a call_id (A2: correlates to its output)."""
    return _line("response_item", {"type": "function_call", "name": "exec_command",
                                   "arguments": json.dumps({"cmd": cmd_argv}), "call_id": call_id})


def _fc_output(call_id, exit_code, body=""):
    """response_item function_call_output: codex-added `Exit code: N` line + (truncated) combined output."""
    text = f"Exit code: {exit_code}" + (f"\n{body}" if body else "")
    return _line("response_item", {"type": "function_call_output", "call_id": call_id, "output": text})


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


def _per_package_artifact(cwd, role, work_id, slug="work-package", valid=True, ac_id="AC1"):
    sub = "spec" if role == "spec" else "plan"
    d = Path(cwd) / "docs" / "agentic-sdlc" / slug / sub
    d.mkdir(parents=True, exist_ok=True)
    if role == "spec":
        text = _VALID_SPEC.format(work_id=work_id, ac_id=ac_id) if valid else "# Spec\n(stub)\n"
    else:
        text = _VALID_PLAN.format(work_id=work_id, ac_id=ac_id) if valid else "## Task 1\n(todo)\n"
    (d / f"{work_id}.md").write_text(text, encoding="utf-8")
    return f"docs/agentic-sdlc/{slug}/{sub}/{work_id}.md"


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

    def test_literal_patch_marker_in_bash_does_not_hide_source_redirect(self):
        cwd = self._cwd()
        command = "printf '*** Begin Patch' > note.txt; printf x > src/app.py"
        out = _run_hook(self._pre(cwd, command), ENV_ON)
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

    def test_per_package_order_respected_allows(self):
        cwd = self._cwd()
        s = _per_package_artifact(cwd, "spec", "W")
        p = _per_package_artifact(cwd, "plan", "W")
        out = _run_hook(self._pre(cwd, _src_redirect_cmd(),
                                  rollout_lines=[_mark_write(s), _mark_write(p)]), ENV_ON)
        self.assertEqual(out.strip(), "")

    def test_per_package_mismatched_work_id_denies(self):
        cwd = self._cwd()
        s = _per_package_artifact(cwd, "spec", "W1")
        p = _per_package_artifact(cwd, "plan", "W2")
        out = _run_hook(self._pre(cwd, _src_redirect_cmd(),
                                  rollout_lines=[_mark_write(s), _mark_write(p)]), ENV_ON)
        self.assertTrue(_is_deny(out))

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

    def test_sed_inplace_source_now_denies(self):  # B5-AC1/DP3 (was test_unrecognized_form_silent)
        # This exact command used to slip the gate (returned SILENT — the encoded #5 bypass); the
        # write-form symmetry fix now recognizes an in-place `sed` source write, so it DENIES.
        # Fail-open-on-truly-unmodeled forms (cp/dd) is repointed to
        # TestB5WriteformSymmetry.test_unmodeled_form_fail_open.
        cwd = self._cwd()
        out = _run_hook(self._pre(cwd, "sed -i s/a/b/ src/app.py"), ENV_ON)
        self.assertTrue(_is_deny(out))
        self.assertEqual(_missing_list(out), ["spec", "plan"])

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

    def test_characterization_tests_satisfy_order_allows(self):  # B2/DP-SCOPE-FLOW closure (was a false-block)
        # A characterization-test run before the source edit (safe-refactor's before-source-edit
        # obligation) — or a TDD red test — is now accepted as ordering evidence, so no spec/plan pair
        # is demanded and the edit is ALLOWED. (Before B2 this DENIED, the documented DP-SCOPE-FLOW gap.)
        cwd = self._cwd()
        roll = [_exec_fc(["python3", "-m", "pytest"])]  # a test ran before the edit; no spec/plan
        out = _run_hook(self._pre(cwd, _src_redirect_cmd(), rollout_lines=roll), ENV_ON)
        self.assertEqual(out.strip(), "")

    def test_echo_pytest_before_edit_not_accepted_shape(self):  # A2 SHAPE gate on flow-ORDER
        # `echo pytest` prints the word and runs nothing; the shape gate rejects it as before-edit
        # evidence, so a source edit with no real prior run is still DENIED.
        cwd = self._cwd()
        roll = [_exec_fc_id(["echo", "pytest"], "c1"), _fc_output("c1", 0, "pytest")]
        out = _run_hook(self._pre(cwd, _src_redirect_cmd(), rollout_lines=roll), ENV_ON)
        self.assertTrue(_is_deny(out))

    def test_red_run_before_edit_still_counts_exit_agnostic(self):  # A2/HB6: TDD RED run counts for ordering
        # flow-ORDER is exit-agnostic: a failing test written FIRST (TDD red) is still a real before-edit
        # test run, so the following source edit is ALLOWED. (Only flow-STEP requires exit0.)
        cwd = self._cwd()
        roll = [_exec_fc_id("pytest", "c1"), _fc_output("c1", 1, "1 failed")]
        out = _run_hook(self._pre(cwd, _src_redirect_cmd(), rollout_lines=roll), ENV_ON)
        self.assertEqual(out.strip(), "")

    def test_source_edit_with_no_process_evidence_still_denies(self):  # the gate still bites
        cwd = self._cwd()  # no spec/plan, no test run -> deny
        out = _run_hook(self._pre(cwd, _src_redirect_cmd(), rollout_lines=[]), ENV_ON)
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
        self.assertIn("process.env.PLUGIN_ROOT", order[0])
        self.assertNotIn("${PLUGIN_ROOT}", order[0])
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", order[0])
        # the deferred Claude flow-order-guard.mjs is NOT a substring of -codex.mjs
        self.assertNotIn('"flow-order-guard.mjs"', self.cfg_text)
        for h in block["hooks"]:
            self.assertNotIn("args", h, "Codex must use the shell-string form")
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", self.cfg_text)
        self.assertFalse((REPO / "hooks" / "hooks.json").exists())

    def test_command_block_and_stop_match_the_pinned_wiring(self):  # additive-regression guarantee
        # Pinned literals, not `git show HEAD:`. Against HEAD this compared the file to itself
        # on any clean checkout, so an additive-regression "guarantee" guaranteed nothing. The
        # blocks are small enough to read, which is the point: a reviewer sees which guards are
        # wired, in which order, with which timeouts.
        cur = self.cfg
        cur_first = [b for b in cur["hooks"]["PreToolUse"] if b.get("matcher") == "Bash"][0]
        self.assertEqual(cur_first, PINNED_CODEX_BASH_BLOCK)
        self.assertEqual(cur["hooks"]["SessionStart"], PINNED_CODEX_SESSION_START)
        self.assertEqual(cur["hooks"]["Stop"], PINNED_CODEX_STOP)


# ---- BR8/§7: the named regression surface stays byte-identical --------------
# "Named", not "full": the list below is what is locked, and it has shrunk as files
# became fix targets. Each release is recorded in place with its reason.
class TestRegressionSurfaceUntouched(unittest.TestCase):
    BYTE_LOCKED = [
        # RELEASED by the 2026-08-22 guard-bypass fix (same convention as codex-rollout.mjs above:
        # a locked file that becomes a fix target moves out of the lock and into its own regression
        # test). These five carried confirmed fail-open paths found by an adversarial multi-lens
        # review and re-verified by execution; every one is now covered by
        # tests/test_secret_guard_bypasses.py, which asserts both the closed bypass AND a control
        # case proving the guard did not simply start blocking everything:
        #   hooks/secret-patterns.mjs     - placeholder filter applied to vendor tokens;  anchoring
        #   hooks/codex-write-signal.mjs  - extractLiteral payload truncation; dishonest `parsed`
        #   hooks/scan-commit.mjs         - git-alias gate bypass; unscanned commit message; filenames
        #   hooks/branch-guard.mjs        - git-alias gate bypass
        #   hooks/hooks-claude.json       - Bash-only matcher; bypassable `if` subcommand filter
        # Claude flow files (spec §7).
        "hooks/flow-order-guard.mjs",
        "hooks/flow-step-guard.mjs",
        # hooks/flow-evidence.mjs and hooks/codex-flow-evidence.mjs are NOT locked here — the AP2
        # "regression surface untouched" guarantee is intentionally SUPERSEDED for these two files
        # by work-package-artifact-resolution (per-package recognition + Claude Stop co-located
        # pairing); their new behavior is covered by test_flow_guards / test_codex_flow_step_guard.
        # hooks/flow-requirements.json is NOT locked here — B1 broadened its testCommand allowlist
        # (a shared config change, covered by the AP2b recognition test).
        "hooks/completion-claim-guard.mjs",
        # AP2a/AP2b Codex modules (reused read-only).
        # NOTE: hooks/codex-rollout.mjs is intentionally NOT locked here — a DP-LIVE follow-up fix
        # corrected readRolloutSignals to read the real `patch_apply_end` carrier; that file is the
        # fix target, covered by its own regression test (test_patch_targets_from_patch_apply_end).
        # hooks/completion-claim-guard-codex.mjs RELEASED by publication-readiness 0.4.3 (BR17) for the
        # owner-aware completion message (same convention as codex-rollout.mjs and the 2026-08-22
        # releases above); coverage in tests/test_codex_completion_claim_guard.py
        # (TestHouseMessageBytes, TestOwnerAwareCompletion).
        "hooks/flow-step-guard-codex.mjs",
        # hooks/codex-write-signal.mjs is NOT locked here, and no other list locks it either. The #5 fix left
        # the shared secret-write extractor byte-untouched (the precise recognizer re-implements its pattern
        # rather than editing it), but the file has since been a security-fix target twice, and a byte lock
        # would have blocked those fixes — the same reason codex-rollout.mjs and scan-write-codex.mjs are out.
        # So the spec Must-not-change item it names is enforced by behaviour, not by bytes: its coverage is
        # tests/test_secret_guard_bypasses.py (closed bypass plus a control proving the guard still passes
        # legitimate input). Anyone relying on a byte lock for that surface should read this as: there is none.
        # AP1 command/write guards + reused pattern source (this slice edits the very
        # Bash|apply_patch block scan-write-codex.mjs lives in, so its bytes must be locked).
        # hooks/scan-write-codex.mjs is NOT locked here — a security follow-up sanitized the target
        # path in its deny reason (prompt-injection fix); it is covered by the AP1 write-guard suite.
        # destructive-command-guard.mjs and codex-write-signal.mjs are security-fix targets with
        # dedicated parser/behavior regressions; byte-locking them to the vulnerable HEAD would
        # prevent release hardening.
    ]

    def test_locked_files_byte_identical(self):  # BR8
        for rel, want in sorted(LOCK_DIGESTS.items()):
            with self.subTest(file=rel):
                path = REPO / rel
                # Existence first, so a deleted or renamed file fails by name rather than
                # raising. The old shape got this half right and it is kept.
                self.assertTrue(path.exists(), f"{rel} is missing from the tree")
                # CRLF-normalized: a Windows working tree must not fail a Linux checkout, and
                # a pure line-ending change is out of scope by design.
                got = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                self.assertEqual(got, want,
                                 f"{rel} changed; bump the digest in LOCK_DIGESTS in the same "
                                 f"commit, with the reason, or release the file from the lock")

    def test_released_completion_guard_not_locked_and_rationale_present(self):  # AC48
        self.assertNotIn("hooks/completion-claim-guard-codex.mjs", self.BYTE_LOCKED)
        comments = [line for line in Path(__file__).read_text(encoding="utf-8").splitlines()
                    if line.strip().startswith("#")]
        self.assertTrue(any("publication-readiness 0.4.3 (BR17)" in line for line in comments),
                        "the lock release needs its rationale comment beside the list")


# ==== B5 (#5 write-form symmetry): drivers + tests ==========================
# NB (DP-NS): the file's earlier `# AC*` comments carry AP2c meanings; the tests below use `B5-AC*`
# ids (spec codex-flow-order-writeform-symmetry). `_signals`/`_precise_targets`/`_raw_targets` drive the
# newly-exported readRolloutSignals / preciseWriteTargetsOf / writeTargetsOf directly.
def _signals(rollout_lines):
    """Drive the exported readRolloutSignals over a synthetic rollout; return its object."""
    rollout = _write_rollout(rollout_lines)
    script = ("const r = await import(%s);"
              "process.stdout.write(JSON.stringify(r.readRolloutSignals(process.argv[1])));"
              % json.dumps(ROLLOUT.as_uri()))
    return json.loads(_node(script, rollout))


def _precise_targets(command):
    """Drive the exported preciseWriteTargetsOf (current-edit precise recognizer)."""
    script = ("const r = await import(%s);"
              "process.stdout.write(JSON.stringify(r.preciseWriteTargetsOf(process.argv[1])));"
              % json.dumps(ROLLOUT.as_uri()))
    return json.loads(_node(script, command))


def _raw_targets(command):
    """Drive the exported writeTargetsOf (raw prior-evidence superset recognizer)."""
    script = ("const r = await import(%s);"
              "process.stdout.write(JSON.stringify(r.writeTargetsOf(process.argv[1])));"
              % json.dumps(ROLLOUT.as_uri()))
    return json.loads(_node(script, command))


def _cmd_fc(script_str):
    """A rollout exec_command carrier for a Bash `-lc` script (the realistic codex argv shape)."""
    return _exec_fc(["bash", "-lc", script_str])


BR6_TABLE = REPO / "tests" / "fixtures" / "transcripts" / "br6-attribution-cases.json"


def _br6_carrier_lines(row):
    """A shared-table row's runner carrier with no spec/plan write: callEvents exec_command calls on
    one call_id and outputRecords outputs ('Exit code: N' first only when exitCode is non-null)."""
    carrier = row["carrier"]
    call_id = "call-" + row["id"]
    text = carrier["outputSummary"] or ""
    if carrier["exitCode"] is not None:
        text = f"Exit code: {carrier['exitCode']}\n{text}"
    output = _line("response_item", {"type": "function_call_output", "call_id": call_id, "output": text})
    return [_exec_fc_id(row["command"], call_id)] * carrier["callEvents"] + [output] * carrier["outputRecords"]


# ---- AC130: the Stop-evidence closure never reaches the Codex ordering decision (Task 16) ----
class TestClosureScopeCodexOrderGuard(_Tmp):
    def test_table_order_decision_unchanged(self):  # AC130
        rows = json.loads(BR6_TABLE.read_text(encoding="utf-8"))["rows"]
        req = json.loads((REPO / "hooks" / "flow-requirements.json").read_text(encoding="utf-8"))
        cwd = self._cwd()
        bad = []
        for row in rows:
            decision = _order_decision(_br6_carrier_lines(row), req, cwd)
            expected = row["baseline5801cb9"]["codexOrderGuard"] == "satisfied"
            if (decision.get("satisfied") is True) != expected:
                bad.append(row["id"])
        self.assertEqual(bad, [], f"order decisions that differ from the 5801cb9 column: {bad}")


class TestB5WriteformSymmetry(_Tmp):
    """B5 (#5): the current-edit deny trigger must recognize the SAME literal write forms
    (`sed -i` / `tee` / plain `>`,`>>`) the prior-evidence detector does, PRECISELY (quote/heredoc/
    expansion-aware), and multi-file `sed`/`tee` must surface every operand on both sides."""

    def _assert_denies(self, command):
        out = _run_hook(self._pre(self._cwd(), command), ENV_ON)
        self.assertTrue(_is_deny(out), f"expected DENY for {command!r}, got {out!r}")
        self.assertEqual(_missing_list(out), ["spec", "plan"])

    def _assert_allows(self, command, tool_name="Bash"):
        out = _run_hook(self._pre(self._cwd(), command, tool_name=tool_name), ENV_ON)
        self.assertEqual(out.strip(), "", f"expected ALLOW (silent) for {command!r}, got {out!r}")

    # ---- NEW behaviour: symmetric current-edit DENY (RED-first vs HEAD) ----
    def test_sed_source_edit_denies(self):  # B5-AC1
        self._assert_denies("sed -i 's/x/y/' src/app.py")
        self._assert_denies("sed -i.bak 's/x/y/' src/app.py")

    def test_sed_glued_expression_denies(self):  # B5-AC1 (glued -e)
        self._assert_denies("sed -i -e's/x/y/' src/app.py")

    def test_tee_source_edit_denies(self):  # B5-AC2
        self._assert_denies("printf x | tee src/app.py")
        self._assert_denies("printf x | tee -a src/app.py")

    def test_plain_redirect_source_edit_denies(self):  # B5-AC3
        self._assert_denies("cat tmp > src/app.py")
        self._assert_denies("cat tmp >> src/app.py")

    def test_multifile_sed_nonlast_source_denies(self):  # B5-AC4 (discriminating)
        self._assert_denies("sed -i 's/x/y/' src/app.py README.md")
        self._assert_denies("sed -i 's/x/y/' src/a.py src/b.py")

    def test_multifile_tee_nonfirst_source_denies(self):  # B5-AC5
        self._assert_denies("printf x | tee README.md src/app.py")

    def test_sed_source_and_test_file_denies(self):  # B5-AC4 (source+test edge, finding 5)
        self._assert_denies("sed -i 's/x/y/' src/a.py tests/test_b.py")

    def test_current_edit_sed_e_only_real_file(self):  # B5-AC7-current
        self.assertEqual(_precise_targets("sed -i -e 's/x/y/' src/a.py"), ["src/a.py"])
        self._assert_denies("sed -i -e 's/x/y/' src/a.py")

    def test_sed_two_expressions_denies_only_real_file(self):  # B5-AC7 (finding 4)
        cmd = "sed -i -e 's/a/b/' -e 's/c/d/' src/app.py"
        self._assert_denies(cmd)
        self.assertEqual(_precise_targets(cmd), ["src/app.py"])

    def test_literal_source_write_beside_expansion_sibling_denies(self):  # B5-AC11 (finding 4)
        cmd = "printf x > src/app.py; cat y > $F.py"
        self._assert_denies(cmd)
        self.assertEqual(_precise_targets(cmd), ["src/app.py"])

    def test_deny_reason_leakfree_new_forms(self):  # B5-AC8 (security)
        secret = "SENTINEL_LEAK_XYZ"
        cmd = f"sed -i 's/x/{secret}/' /abs/secret/src/app.py"
        out = _run_hook(self._pre(self._cwd(), cmd), ENV_ON)
        self.assertTrue(_is_deny(out))
        reason = _deny_reason(out)
        for leak in (secret, "/abs/secret", "src/app.py"):
            self.assertNotIn(leak, reason)

    # ---- RAW prior-evidence completeness (exact set, both sides) ----
    def test_prior_evidence_multifile_sed_exact_set(self):  # B5-AC6
        sig = _signals([_cmd_fc("sed -i 's/x/y/' docs/agentic-sdlc/specs/W.md src/app.py")])
        self.assertEqual(set(sig["editTargets"]), {"docs/agentic-sdlc/specs/W.md", "src/app.py"})

    def test_prior_evidence_sed_expression_never_target_exact_set(self):  # B5-AC7-raw
        sig = _signals([_cmd_fc("sed -i -e 's/x/y/' src/a.py src/b.py")])
        self.assertEqual(set(sig["editTargets"]), {"src/a.py", "src/b.py"})

    def test_prior_evidence_glued_expression_exact_set(self):  # B5-AC7-raw (glued)
        sig = _signals([_cmd_fc("sed -i -e's/x/y/' src/a.py src/b.py")])
        self.assertEqual(set(sig["editTargets"]), {"src/a.py", "src/b.py"})

    def test_prior_evidence_multifile_tee_all_operands(self):  # B5-AC5-raw (RED at HEAD: first-only)
        sig = _signals([_cmd_fc("cat x | tee README.md src/app.py")])
        self.assertEqual(set(sig["editTargets"]), {"README.md", "src/app.py"})

    def test_prior_evidence_pathqualified_tee_superset(self):  # B5-AC9-raw (GREEN at HEAD, superset)
        sig = _signals([_cmd_fc("cat x | /usr/bin/tee out.txt")])
        self.assertIn("out.txt", sig["editTargets"])

    def test_raw_scan_linear_flood(self):  # B5-AC15-raw (ReDoS-safe)
        import time
        cmd = "printf x > a.py; sed -i s/x/y/ b.py c.py; cat | tee d.py e.py; " * 1200  # ~76 KB (< argv cap)
        t = time.time()
        _raw_targets(cmd)
        self.assertLess(time.time() - t, 5.0)

    # ---- PRESERVATION: fail-open / no new spurious DENY (GREEN at HEAD and after) ----
    def test_unmodeled_form_fail_open(self):  # B5-AC10 (repoint target for DP3)
        self._assert_allows("cp a.py src/app.py")
        self._assert_allows("dd if=x of=src/app.py")

    def test_expansion_target_fail_open(self):  # B5-AC11
        self._assert_allows("sed -i 's/x/y/' $F.py")
        self._assert_allows("cat x > $F.py")
        self._assert_allows("printf x | tee $DIR/app.py")

    def test_quoted_or_heredoc_writelooking_allows(self):  # B5-AC12
        self._assert_allows('git commit -m "wrote > app.py"')
        self._assert_allows('echo "x > y.py"')
        self._assert_allows("grep 'a > b.py' f")
        self._assert_allows("printf 'see notes > backup.py' > README.md")
        self._assert_allows("echo run sed -i on foo.py > notes.md")
        self._assert_allows("cat <<'EOF' > notes.md\nsee > evil.py\nEOF\n")

    def test_patch_content_redirect_not_denied(self):  # B5-AC14 (BR8)
        patch = _v4a_add("docs/note.md", body_lines=("printf x > src/evil.py", "return a > config.py"))
        self._assert_allows(patch, tool_name="apply_patch")

    def test_precise_scan_linear(self):  # B5-AC15 (ReDoS-safe, precise side)
        import time
        cmd = "sed -i s/x/y/ a.py; printf x | tee b.py; cat c > d.py; " * 1400  # ~76 KB (< argv cap)
        t = time.time()
        _precise_targets(cmd)
        self.assertLess(time.time() - t, 5.0)

    def test_precise_scan_linear_internal_whitespace(self):  # B5-AC15 (ReDoS regression: stripWrappingSubshell)
        # A long INTERNAL whitespace run with no trailing ')' was the O(n^2) trap in the `/\s*\)$/`
        # subshell strip (security review, High): ~8s at 110 KB with the greedy regex, <0.1s linear.
        import time
        cmd = "echo " + " " * 110000 + "x"  # ~110 KB, < argv cap
        t = time.time()
        _precise_targets(cmd)
        self.assertLess(time.time() - t, 3.0)

    def test_sed_program_file_not_target(self):  # B5-AC16 (-f program file, not written)
        self.assertEqual(_precise_targets("sed -i -f script.py README.md"), ["README.md"])
        self._assert_allows("sed -i -f script.py README.md")

    def test_sed_script_token_not_target(self):  # B5-AC17 (in-script look-alike token)
        self._assert_allows("sed -i 's/x/y.py/' README.md")
        self.assertEqual(_precise_targets("sed -i 's/a/> b.py/' README.md"), ["README.md"])
        self._assert_allows("sed -i 's/a/> b.py/' README.md")

    def test_fd_redirect_source_fail_open(self):  # B5-AC3 scope / DP5 (fd/extended redirects deferred)
        self._assert_allows("cmd &> src/app.py")
        self._assert_allows("cmd >| src/app.py")
        self._assert_allows("cmd 1> src/app.py")

    def test_flow_order_recognized_forms_documented(self):  # B5 (finding 6): docs match behavior
        readme = (REPO / "hooks" / "README.md").read_text(encoding="utf-8")
        row = "\n".join(ln for ln in readme.splitlines() if "flow-order-guard-codex.mjs" in ln)
        self.assertTrue(row, "flow-order-guard-codex.mjs row missing from hooks/README.md")
        for form in ("sed -i", "tee", "`>`/`>>`"):        # recognized current-edit forms (B5)
            self.assertIn(form, row, f"recognized form {form!r} not documented")
        for residual in ("&>", ">|"):  # deferred residuals (#6)
            self.assertIn(residual, row, f"deferred residual {residual!r} not documented")
        self.assertIn("literal `*** Begin Patch` inside Bash no longer selects", row)


if __name__ == "__main__":
    unittest.main()
