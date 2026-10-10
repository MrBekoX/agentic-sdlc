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
EVID = REPO / "hooks" / "codex-flow-evidence.mjs"
FLOW_EVID = REPO / "hooks" / "flow-evidence.mjs"
HOOK = REPO / "hooks" / "flow-step-guard-codex.mjs"
CODEX_CFG = REPO / "hooks" / "hooks-codex.json"

# LF-normalized sha256 of the two files this suite locks. The longer rationale sits beside
# LOCK_DIGESTS in tests/test_codex_flow_order_guard.py: a lock that re-reads its expected value
# from the moving HEAD cannot fail on a committed change.
LOCK_DIGESTS = {
    # Rebased for Claude Code 2.1.293: last_assistant_message + background_tasks on Stop.
    "hooks/flow-step-guard.mjs":
        "e5f66136c69096748375ea1fb357b1f6282d478f9857ddca974a29853595e165",
    # Rebased for Claude Code 2.1.293: prefer last_assistant_message; block only when caught up.
    "hooks/completion-claim-guard.mjs":
        "ad454dd5f68c2ba08583c283b444318c24892d9c3305161b913dea3bcf317c9b",
}

# The Codex Stop handler this suite pins by NAME and by VALUE. Presence is asserted before the
# comparison, because the shape this replaces compared two name-filtered lists and passed when
# both were empty.
PINNED_CODEX_COMPLETION_STOP_HANDLER = {
    "type": "command",
    "command": "node -e \"const p=require('node:path').join(process.env.PLUGIN_ROOT,'hooks','completion-claim-guard-codex.mjs');process.argv[1]=p;import(require('node:url').pathToFileURL(p).href)\"",
    "commandWindows": "node.exe -e \"const p=require('node:path').join(process.env.PLUGIN_ROOT,'hooks','completion-claim-guard-codex.mjs');process.argv[1]=p;import(require('node:url').pathToFileURL(p).href)\"",
    "timeout": 20,
    "statusMessage": "Completion-claim gate (marker)...",
}


MARKER = "<!-- agentic-sdlc:gate:completion-claim:verified -->"
FLOW_LABEL = "an artifact-bearing SDLC flow (spec/plan/tests)"

# ---- artifact bodies (must pass/fail validate_artifacts.py --strict for the RIGHT reason) ----
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
- {ac_id}: Given a valid spec written this session, when derivation runs, then the spec step passes.

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


# ---- BR6 exit attribution (publication-readiness Tasks 15, 16, 18) ------------
BR6_TABLE = REPO / "tests" / "fixtures" / "transcripts" / "br6-attribution-cases.json"


def _br6_rows():
    """Rows of the shared BR6 attribution case table (D3). Read-only: no test here writes it."""
    return json.loads(BR6_TABLE.read_text(encoding="utf-8"))["rows"]


def _br6_eval(commands):
    """Evaluate the BR6 helpers for a list of commands in ONE node process.

    Per command: splitBr6Statements, lastStatement, the version/help and pipe flags and the
    grammar-derived runner rule (isBr6RunnerStatement, D27) for the last statement and for the whole
    command, the grammar verdict, and the 5801cb9 text check (isRealRunnerInvocation) of the whole
    command. The list travels as one JSON argument, so a large input takes the _node_argv_or_stdin
    stdin path."""
    script = (
        "const r = await import(%s); const f = await import(%s);"
        "const re = new RegExp(f.loadRequirements().testCommand, 'i');"
        "const out = JSON.parse(process.argv[1]).map((c) => { const last = r.lastStatement(c); return {"
        "statements: r.splitBr6Statements(c), last,"
        "lastVersionOrHelpOnly: r.isVersionOrHelpOnly(last, re), lastHasPipe: r.hasUnquotedPipe(last),"
        "lastIsRealRunner: r.isBr6RunnerStatement(last, re), runnerShape: f.isRealRunnerInvocation(c, re),"
        "runsRunner: r.isBr6RunnerStatement(c, re), inGrammar: r.inSafeBr6Grammar(c),"
        "versionOrHelpOnly: r.isVersionOrHelpOnly(c, re), hasPipe: r.hasUnquotedPipe(c)}; });"
        "process.stdout.write(JSON.stringify(out));"
        % (json.dumps(ROLLOUT.as_uri()), json.dumps(FLOW_EVID.as_uri())))
    return json.loads(_node(script, json.dumps(list(commands))))


def _fc_output_text(call_id, text):
    """response_item function_call_output with verbatim output text (no added Exit code line)."""
    return _line("response_item", {"type": "function_call_output", "call_id": call_id, "output": text})


def _br6_rollout(cwd, row):
    """Rollout for one shared-table row: a valid in-session spec/plan pair for work id W, a source
    edit, then the row's carrier - callEvents exec_command calls sharing one call_id and
    outputRecords outputs whose text is outputSummary, preceded by 'Exit code: N' only when the
    row's exitCode is non-null."""
    spec = _artifact(cwd, "spec", "W", valid=True)
    plan = _artifact(cwd, "plan", "W", valid=True)
    carrier = row["carrier"]
    call_id = "call-" + row["id"]
    text = carrier["outputSummary"] or ""
    if carrier["exitCode"] is not None:
        text = f"Exit code: {carrier['exitCode']}\n{text}"
    lines = [_mark_write(spec), _mark_write(plan), _src_patch()]
    lines += [_exec_fc_id(row["command"], call_id)] * carrier["callEvents"]
    lines += [_fc_output_text(call_id, text)] * carrier["outputRecords"]
    return _write_rollout(lines)


def _derive_env(rollout_paths, cwd, env_extra=None):
    """deriveFlowEvidence for many rollouts in one node process, with the flow flags cleared and
    env_extra applied. The strict flag is read per call, so one process serves every row."""
    script = ("const m = await import(%s);"
              "const out = JSON.parse(process.argv[1]).map((p) => m.deriveFlowEvidence(p, process.argv[2]));"
              "process.stdout.write(JSON.stringify(out));" % json.dumps(EVID.as_uri()))
    argv, payload = _node_argv_or_stdin(script, (json.dumps(list(rollout_paths)), str(cwd)))
    env = dict(os.environ)
    for name in ("AGENTIC_FLOW_GATE_BLOCK", "AGENTIC_FLOW_STRICT_EVIDENCE"):
        env.pop(name, None)
    if env_extra:
        env.update(env_extra)
    r = subprocess.run(argv, input=payload, capture_output=True, text=True, encoding="utf-8", env=env)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _br6_tests_outcomes(env_extra=None):
    """{row id: 'missing'|'satisfied'} for the live Codex `tests` step, one rollout per table row, plus
    the raw derivation results so callers can check that only `tests` varies."""
    rows = _br6_rows()
    cwd = tempfile.mkdtemp(prefix="codex-br6-cwd-")
    paths = [_br6_rollout(cwd, row) for row in rows]
    try:
        results = _derive_env(paths, cwd, env_extra)
    finally:
        shutil.rmtree(cwd, ignore_errors=True)
        for path in paths:
            os.unlink(path)
    outcomes = {row["id"]: ("missing" if "tests" in res["missingBlockSteps"] else "satisfied")
                for row, res in zip(rows, results)}
    return {row["id"]: row for row in rows}, outcomes, dict(zip((row["id"] for row in rows), results))


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
        self.assertIn("process.env.PLUGIN_ROOT", new[0])
        self.assertNotIn("${PLUGIN_ROOT}", new[0])
        self.assertNotIn("flow-step-guard.mjs", new[0])  # -codex infix keeps the deferred lock intact
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", self.cfg_text)
        self.assertFalse((REPO / "hooks" / "hooks.json").exists())


# ---- AC18: the named §10 regression surface stays byte-identical -----------
# Pinned by LOCK_DIGESTS above, not by a comparison against HEAD: on a clean checkout
# the working tree IS HEAD, so the shape this replaces compared each file to itself.
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
        # hooks/completion-claim-guard-codex.mjs RELEASED by publication-readiness 0.4.3 (BR17) for the
        # owner-aware completion message (same convention as codex-rollout.mjs); coverage in
        # tests/test_codex_completion_claim_guard.py (TestHouseMessageBytes, TestOwnerAwareCompletion).
    ]

    def test_released_completion_guard_not_locked_and_rationale_present(self):  # AC48
        self.assertNotIn("hooks/completion-claim-guard-codex.mjs", self.BYTE_LOCKED)
        comments = [line for line in Path(__file__).read_text(encoding="utf-8").splitlines()
                    if line.strip().startswith("#")]
        self.assertTrue(any("publication-readiness 0.4.3 (BR17)" in line for line in comments),
                        "the lock release needs its rationale comment beside the list")

    def test_remaining_locks_still_listed(self):  # AC48
        import test_codex_flow_order_guard as order_suite
        self.assertLessEqual({"hooks/flow-step-guard.mjs", "hooks/completion-claim-guard.mjs"},
                             set(self.BYTE_LOCKED))
        self.assertLessEqual({"hooks/flow-order-guard.mjs", "hooks/flow-step-guard.mjs",
                              "hooks/completion-claim-guard.mjs", "hooks/flow-step-guard-codex.mjs"},
                             set(order_suite.TestRegressionSurfaceUntouched.BYTE_LOCKED))

    def test_locked_files_byte_identical(self):  # AC18
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

    def test_codex_pretooluse_sessionstart_unchanged(self):  # AC18 (additive-only since AP2c)
        # AP2c additively appends flow-order-guard-codex.mjs to the Bash|apply_patch PreToolUse
        # block, so strict PreToolUse == HEAD is no longer the contract. Relaxed to additive-only:
        # SessionStart unchanged, the Bash command-guard block unchanged, and the scan-write-codex
        # handler dict unchanged (the new flow-order handler is the only permitted addition, asserted
        # positively by tests/test_codex_flow_order_guard.py::test_pretooluse_array_has_both_guards).
        import test_codex_flow_order_guard as order_suite
        cur = json.loads(CODEX_CFG.read_text(encoding="utf-8"))
        # Pinned literals, not `git show HEAD:`. Against HEAD both sides came from the same
        # bytes on any clean checkout, so "unchanged" was true by construction.
        self.assertEqual(cur["hooks"]["SessionStart"], order_suite.PINNED_CODEX_SESSION_START)
        cur_bash = [b for b in cur["hooks"]["PreToolUse"] if b.get("matcher") == "Bash"]
        self.assertEqual(cur_bash, [order_suite.PINNED_CODEX_BASH_BLOCK])

        def _scan_handler(cfg):
            for b in cfg["hooks"]["PreToolUse"]:
                if b.get("matcher") == "Bash|apply_patch":
                    return [h for h in b["hooks"] if "scan-write-codex.mjs" in h["command"]]
            return []

        # PRESENCE first: the previous form compared this list against the same list derived
        # from HEAD, so removing the handler - or the whole Bash|apply_patch block - made both
        # sides `[]` and the assertion passed.
        found = _scan_handler(cur)
        self.assertTrue(found, "the Codex write guard is not wired at all")
        self.assertEqual(found, [order_suite.PINNED_CODEX_SCAN_WRITE_HANDLER])

    def _stop_handlers_named(self, cfg, needle):
        return [h for blk in cfg["hooks"]["Stop"] for h in blk["hooks"]
                if needle in h["command"]]

    def test_existing_completion_claim_stop_handler_unchanged(self):  # AC18
        cur = json.loads(CODEX_CFG.read_text(encoding="utf-8"))
        found = self._stop_handlers_named(cur, "completion-claim-guard-codex.mjs")
        # PRESENCE first. The previous form filtered HEAD and the working tree by the same
        # name and compared the results, so removing the handler made both sides empty and
        # the assertion passed - a lock that went green when the thing it guards was deleted.
        self.assertTrue(found, "the completion-claim Stop handler is not wired at all")
        self.assertEqual(found, [PINNED_CODEX_COMPLETION_STOP_HANDLER])

    def test_removing_the_stop_handler_would_fail_this_lock(self):  # AC18 discriminator
        # The mutation the old shape could not see, applied to an in-memory copy so nothing
        # on disk changes. If this ever passes, the lock above has gone vacuous again.
        cur = json.loads(CODEX_CFG.read_text(encoding="utf-8"))
        for blk in cur["hooks"]["Stop"]:
            blk["hooks"] = [h for h in blk["hooks"]
                            if "completion-claim-guard-codex.mjs" not in h["command"]]
        found = self._stop_handlers_named(cur, "completion-claim-guard-codex.mjs")
        self.assertEqual(found, [], "the fixture did not actually remove the handler")
        self.assertNotEqual(found, [PINNED_CODEX_COMPLETION_STOP_HANDLER],
                            "an empty handler list must not satisfy the pinned literal")


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


# ---- AC118, AC29: BR6 statement split and version/help/pipe helpers (Task 15) ----
class TestBR6StatementSplit(unittest.TestCase):
    """Pure BR6 helpers exported by hooks/codex-rollout.mjs, checked against spec shapes and the
    shared table. Each test names the helper mutation that would turn it red."""

    def _one(self, command):
        return _br6_eval([command])[0]

    def test_split_on_semicolon_newline_oror_not_andand(self):
        # Mutation: splitting on '&&', '|' or '&', or not splitting on '||'.
        self.assertEqual(self._one("cd a; pytest || true")["statements"], ["cd a", "pytest", "true"])
        self.assertEqual(self._one("cd repo && pytest")["statements"], ["cd repo && pytest"])
        self.assertEqual(self._one("pytest | tee x & wait")["statements"], ["pytest | tee x & wait"])
        import time
        flood = ";\n||" * 50000 + "pytest"  # 200 KB of separators, shipped on stdin
        started = time.time()
        self.assertEqual(self._one(flood)["statements"], ["pytest"])
        self.assertLess(time.time() - started, 5.0, "the BR6 split must stay linear")

    def test_backslash_newline_continuation_joins(self):
        # Mutation: treating the continuation newline as a statement separator.
        self.assertEqual(self._one("pytest \\\n-q")["statements"], ["pytest -q"])

    def test_empty_and_comment_statements_ignored(self):
        # Mutation: keeping empty or comment-only statements (the last statement would change).
        for command in ("pytest;", "pytest ; ", "pytest\n# done"):
            with self.subTest(command=command):
                got = self._one(command)
                self.assertEqual(got["statements"], ["pytest"])
                self.assertEqual(got["last"], "pytest")
        empty = self._one("")
        self.assertEqual((empty["statements"], empty["last"]), ([], ""))

    def test_midline_comment_hides_its_separators(self):
        # Mutation: splitting on a `;` inside a comment that starts mid-line, or reading a `#` that
        # does not start a word as a comment.
        cases = {
            "pytest; echo EXIT=$? # ; pytest": (["pytest", "echo EXIT=$?"], "echo EXIT=$?"),
            "pytest # ; echo x": (["pytest"], "pytest"),
            "pytest;# ; echo x": (["pytest"], "pytest"),
            "pytest -k a#b; echo x": (["pytest -k a#b", "echo x"], "echo x"),
            "echo $#; pytest": (["echo $#", "pytest"], "pytest"),
            "pytest -k 'a # ;b'": (["pytest -k 'a # ;b'"], "pytest -k 'a # ;b'"),
            "pytest; (echo x)# ; pytest": (["pytest", "(echo x)"], "(echo x)"),
        }
        for (command, (statements, last)), got in zip(cases.items(), _br6_eval(list(cases))):
            with self.subTest(command=command):
                self.assertEqual((got["statements"], got["last"]), (statements, last))

    # Every bash metacharacter after which an unquoted `#` starts a comment. Bash 5.2 probe:
    # `false; (true)<b># ; echo RAN` never prints RAN for any of them (a syntax error for `(`, `|`,
    # `<` and `>` also stops bash). COMMENT_BOUNDARY in hooks/codex-rollout.mjs must equal this set.
    COMMENT_BOUNDARIES = (" ", "\t", "\n", ";", "|", "&", "(", ")", "<", ">")

    def test_comment_starts_after_every_bash_metacharacter(self):
        # Mutation: dropping any character from COMMENT_BOUNDARY, so the separator hidden in the
        # comment splits again (splitBr6Statements) or the pipe in the comment counts (forEachUnquoted).
        splits = ["pytest; (echo x)" + b + "# ; pytest" for b in self.COMMENT_BOUNDARIES]
        pipes = ["pytest" + b + "# | tee x" for b in self.COMMENT_BOUNDARIES]
        got = _br6_eval(splits + pipes)
        for n, b in enumerate(self.COMMENT_BOUNDARIES):
            with self.subTest(boundary=repr(b)):
                head = "(echo x)" if b in ";\n" else ("(echo x)" + b).strip()
                split = got[n]
                self.assertEqual((split["statements"], split["last"]), (["pytest", head], head))
                self.assertEqual(got[len(splits) + n]["hasPipe"], b == "|")  # only a real `|` pipes

    def test_hash_glued_to_a_word_character_is_data(self):
        # Mutation: widening COMMENT_BOUNDARY past bash's metacharacters (`$#`, `x}#`, `a=#` are words).
        glued = ("a", "$", "=", "}", "/", "-", "#")
        commands = ["pytest -k x" + c + "#; pytest" for c in glued]
        for c, command, got in zip(glued, commands, _br6_eval(commands)):
            with self.subTest(glued=c):
                self.assertEqual(got["statements"], ["pytest -k x" + c + "#", "pytest"])

    def _helpers(self, commands):
        script = ("const r = await import(%s);"
                  "process.stdout.write(JSON.stringify(JSON.parse(process.argv[1]).map((c) => ["
                  "r.trailingOrRun(c), r.hasUnmodeledShellSyntax(c)])));" % json.dumps(ROLLOUT.as_uri()))
        return json.loads(_node(script, json.dumps(list(commands))))

    def test_trailing_oror_run_records_the_joining_separator(self):
        # Mutation: resetting the `||` join on a newline or comment after `||` (bash continues the
        # list there), or carrying it past a `;` or newline that ends a statement.
        cases = {"cd a; pytest || true": ["pytest", "true"], "echo ok ||\npytest": ["echo ok", "pytest"],
                 "a ||\n# note\nb": ["a", "b"], "a || b; c": ["c"], "a || b\nc": ["c"],
                 "a && b || c": ["a && b", "c"], "pytest -k 'a||b'": ["pytest -k 'a||b'"], "": []}
        for (command, run), (got, _) in zip(cases.items(), self._helpers(cases)):
            with self.subTest(command=command):
                self.assertEqual(got, run)

    # Constructs the lexer does not model, each paired with every separator it can hide.
    UNMODELED = ("$(", "`", "<(", ">(", "$'")
    HIDDEN_SEPARATORS = (";", "\n", "||")

    def test_unmodeled_syntax_with_any_separator_fails_closed(self):
        # Mutation: dropping any construct or separator, or reading the quote mask instead of raw text.
        commands = ["pytest " + u + "x" + s + "y" for u in self.UNMODELED for s in self.HIDDEN_SEPARATORS]
        controls = ["pytest " + u + "x" for u in self.UNMODELED] + ["pytest; pytest || pytest", "echo $x; pytest"]
        got = [flag for _, flag in self._helpers(commands + controls)]
        self.assertEqual(got, [True] * len(commands) + [False] * len(controls))

    def test_quoted_separators_are_data(self):
        # Mutation: splitting inside single or double quotes.
        for command in ('pytest -k "a;b"', "pytest -k 'a;b'", "pytest -k 'a||b'"):
            with self.subTest(command=command):
                self.assertEqual(self._one(command)["statements"], [command])

    def test_version_help_only_per_andand_segment(self):
        # Mutation: checking only the first '&&' segment, counting a non-flag word such as
        # 'help', or calling a runner-less statement version-only.
        true_cases = ("pytest --version", "pytest --version -q", "python -m pytest --version",
                      "npm test -- --help", "pytest -V", "pytest -h")
        false_cases = ("pytest -k help", "pytest && pytest --version", "pytest --version && pytest",
                       "cd repo", "echo --version")
        got = _br6_eval(true_cases + false_cases)
        for command, result in zip(true_cases + false_cases, got):
            with self.subTest(command=command):
                self.assertEqual(result["versionOrHelpOnly"], command in true_cases)

    def test_runner_words_follow_bash_quote_removal(self):
        # D25 model (1), the Task 141 lists. Mutation: comparing raw words, splitting only at blanks, reading an
        # expansion or a slash-free glob as literal text, or counting a segment that only names the runner.
        from test_procedure_eval import TestStrictRedGreen as lists
        bs = chr(92)
        version_only = [c.replace("<bs>", bs) for c in lists.VERSION_ONLY_WORDS]
        runner = [c.replace("<bs>", bs) for c in lists.RUNNER_WORDS]
        got = _br6_eval(version_only + runner)
        for command, result in zip(version_only + runner, got):
            with self.subTest(command=command):
                self.assertIs(result["versionOrHelpOnly"], command in version_only)
        nbsp_pipe = chr(0xA0) + "#x | pytest | tee log.txt"
        result = self._one(nbsp_pipe)
        self.assertEqual(result["statements"], [nbsp_pipe])
        self.assertIs(result["hasPipe"], True)

    def test_heredoc_helper_is_not_exported(self):
        # QUAL-12: the unused hasUnquotedHeredoc export is deleted, not left as dead API.
        script = ("const r = await import(%s); process.stdout.write(JSON.stringify(["
                  "'hasUnquotedHeredoc' in r, typeof r.isVersionOrHelpOnly]));" % json.dumps(ROLLOUT.as_uri()))
        self.assertEqual(json.loads(_node(script, "[]")), [False, "function"])
        self.assertNotIn("hasUnquotedHeredoc", ROLLOUT.read_text(encoding="utf-8"))

    def test_runner_rule_matches_whole_words(self):
        # D27, the Task 174 lists. Mutation: reading `NAME+=` as a command word, splitting at an escaped separator,
        # ending an assignment value at a Unicode or escaped blank, building the pattern without `^(?:...)$`, dropping
        # the ASCII word check, dropping BR6_PYTHON_MODULES, or accepting a redirection word before the command word.
        # Adding the `i`/`u` flag to the ASCII word check is an equivalent mutant here (the `i`-only testCommand
        # already refuses U+017F); the Python mirror's TestStrictRedGreen kills that mutation.
        from test_procedure_eval import TestStrictRedGreen as lists
        runner, non_runner = list(lists.RUNNER_STATEMENTS), list(lists.NON_RUNNER_STATEMENTS)
        versions = ["pytest --version;", "pytest --version\n", "pytest --help # ;"]
        got = _br6_eval(runner + non_runner + versions)
        for command, result in zip(runner + non_runner, got):
            with self.subTest(command=command):
                self.assertIs(result["runsRunner"], command in runner)
        for command, result in zip(versions, got[len(runner) + len(non_runner):]):
            with self.subTest(version=command):
                self.assertIs(result["versionOrHelpOnly"], True)

    def test_operand_rule_puts_syntax_errors_outside(self):
        # D27. Mutation: dropping either half of the operand rule admits a bash syntax error that runs nothing.
        from test_procedure_eval import TestStrictRedGreen as lists
        outside, inside = list(lists.OPERAND_OUTSIDE), list(lists.OPERAND_INSIDE)
        for command, result in zip(outside + inside, _br6_eval(outside + inside)):
            with self.subTest(command=command):
                self.assertIs(result["inGrammar"], command in inside)

    def test_d28_rules_match_python_lists(self):
        # D28 (DP40), the Task 181 lists. Mutation: no pipeWaiting reset at a word, no null at a newline while a pipe
        # waits, a selector after a python word, a `-[0-9.]+` selector, dropping the npm `k === 3` rule, the `iu` flags
        # on BR6_SCRIPT_WORD (U+017F folds to `s`), toLowerCase before the ASCII script-word check (U+212A lowers to
        # `k`), `--if-present` in BR6_PACKAGE_NEUTRAL, or VERSION_HELP_ARGS as the only version test. The `i` flag
        # alone is an equivalent mutant: without `u`, JavaScript never folds a non-ASCII letter onto an ASCII one.
        from test_procedure_eval import TestStrictRedGreen as lists
        outside, inside = list(lists.D28_PIPE_NEWLINE_OUTSIDE), list(lists.D28_PIPE_NEWLINE_INSIDE)
        runner = list(lists.D28_RUNNER_STATEMENTS)
        non_runner = list(lists.D28_NON_RUNNER_STATEMENTS) + list(lists.D28_NON_ASCII_SCRIPT_WORDS)
        version, not_version = list(lists.D28_VERSION_ONLY), list(lists.D28_NOT_VERSION_ONLY)
        commands = outside + inside + runner + non_runner + version + not_version
        results = dict(zip(commands, _br6_eval(commands)))
        for command in outside + inside:
            with self.subTest(grammar=command):
                self.assertIs(results[command]["inGrammar"], command in inside)
        for command in runner + non_runner:
            with self.subTest(runner=command):
                self.assertIs(results[command]["runsRunner"], command in runner)
        for command in version + not_version:
            with self.subTest(version=command):
                self.assertIs(results[command]["runsRunner"], True)
                self.assertIs(results[command]["versionOrHelpOnly"], command in version)

    def test_runner_rule_does_not_import_the_5801cb9_helper(self):
        # D27: runner identification no longer goes through the 5801cb9 text helper in the rollout module, and the
        # Codex flow evidence imports the grammar-derived rule.
        self.assertNotIn("from './flow-evidence.mjs'", ROLLOUT.read_text(encoding="utf-8"))
        imports = EVID.read_text(encoding="utf-8").split("from './codex-rollout.mjs'")[0]
        self.assertRegex(imports, r"\bisBr6RunnerStatement\b")

    def test_rollout_module_imports_without_cycle(self):
        # The rollout module no longer imports hooks/flow-evidence.mjs (D27); loading it alone in a fresh process must
        # still succeed.
        node = shutil.which("node")
        self.assertIsNotNone(node, "node binary missing")
        script = "import(%s).then((m) => process.stdout.write(typeof m.deliveryReadSkill))" % json.dumps(
            ROLLOUT.as_uri())
        proc = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True,
                              encoding="utf-8", timeout=60)
        self.assertEqual((proc.returncode, proc.stdout), (0, "function"), proc.stderr[-400:])

    def test_pipe_detection_quote_aware(self):
        # Mutation: reading '||' as a pipe, or a quoted '|' as a pipe.
        cases = {"pytest | tee log": True, "pytest |& tee log": True,
                 "pytest || true": False, 'echo "a|b"': False}
        got = _br6_eval(list(cases))
        for (command, expected), result in zip(cases.items(), got):
            with self.subTest(command=command):
                self.assertEqual(result["hasPipe"], expected)

    def test_shared_table_split_and_flags(self):
        # D3 consumer rule: every row of the shared table, no row-count literal.
        rows = _br6_rows()
        results = _br6_eval([row["command"] for row in rows])
        self.assertEqual(len(results), len(rows))
        mismatches = []
        for row, got in zip(rows, results):
            expected = (row["statements"], row["lastVersionOrHelpOnly"], row["lastHasPipe"],
                        row["lastIsRealRunner"], row["runnerShape5801cb9"])
            actual = (got["statements"], got["lastVersionOrHelpOnly"], got["lastHasPipe"],
                      got["lastIsRealRunner"], got["runnerShape"])
            if expected != actual:
                mismatches.append(row["id"])
        self.assertEqual(mismatches, [], f"BR6 helpers disagree with table rows: {mismatches}")


# ---- AC28-AC31, AC118, AC41: default-on BR6 exit-attribution closure (Task 16) ----
class TestExitAttributionClosure(_Tmp):
    """Live Codex Stop `tests` outcome, every flag unset, for each shared-table row carried by its own
    rollout. Outcomes are derived once per class; the tests select rows by id or tag, never by a
    duplicated command literal."""

    @classmethod
    def setUpClass(cls):
        cls.rows, cls.outcome, cls.results = _br6_tests_outcomes()

    def _mismatches(self, ids, expected_column):
        return [i for i in ids if self.outcome[i] != self.rows[i][expected_column]]

    def test_shared_table_default_column(self):  # D3 (RED before the closure)
        bad = self._mismatches(self.rows, "defaultTests")
        self.assertEqual(bad, [], f"rows whose default tests outcome differs from defaultTests: {bad}")

    def test_semicolon_echo_exit_forgery_tests_missing(self):  # AC28
        self.assertEqual(self.outcome["ac28-semicolon-echo-exit"], "missing")

    def test_nbsp_comment_pipe_head_is_missing_by_default(self):  # D25 model (2), QUAL-3
        # Mutation: trimming U+00A0 off the statement (its `#` would start a comment and hide the head's pipe).
        self.assertEqual(self.outcome["edge-forged-blank-nbsp-comment-pipe-head"], "missing")

    def test_trailing_version_help_oror_newline_forms_missing(self):  # AC118
        ids = [i for i, r in self.rows.items() if "AC118" in r["specRefs"] and r["defaultTests"] == "missing"]
        self.assertTrue(ids)
        for i in ids:
            with self.subTest(id=i):
                self.assertEqual(self.outcome[i], "missing")

    # ---- guards: pass before and after the closure ----
    def test_rows_only_vary_the_tests_step(self):  # fixture validity: spec/plan valid, flow active
        bad = [i for i, res in self.results.items()
               if not res["flow"] or not set(res["missingBlockSteps"]) <= {"tests"}]
        self.assertEqual(bad, [], f"rows whose rollout is not a valid active flow: {bad}")

    def test_shared_table_unchanged_rows_match_baseline(self):
        ids = [i for i, r in self.rows.items() if r["defaultTests"] == r["baseline5801cb9"]["codexStopTests"]]
        bad = self._mismatches(ids, "defaultTests")
        self.assertEqual(bad, [], f"rows that changed although the table says they keep 5801cb9: {bad}")

    def test_andand_chains_keep_attribution(self):  # AC118 `&&` half
        for i in ("ac118-andand-echo-ok", "ac118-andand-trailing-version"):
            with self.subTest(id=i):
                self.assertEqual(self.outcome[i], "satisfied")

    def test_legitimate_last_statement_runner_shapes_satisfy(self):  # AC29
        ids = [i for i, r in self.rows.items() if "AC29" in r["specRefs"]]
        self.assertTrue(ids)
        for i in ids:
            with self.subTest(id=i):
                self.assertEqual(self.outcome[i], "satisfied")

    def test_semicolon_echo_nonzero_exit_missing_as_before(self):  # AC30
        self.assertEqual(self.outcome["ac30-semicolon-echo-exit-nonzero"], "missing")

    def test_pipeline_default_outcome_unchanged(self):  # AC31 default half
        for i in ("ac31-pipe-tee", "ac31-pipe-tail"):
            with self.subTest(id=i):
                self.assertEqual(self.outcome[i], self.rows[i]["baseline5801cb9"]["codexStopTests"])

    def test_no_exit_code_multi_statement_fails_open(self):
        self.assertEqual(self.outcome["edge-semicolon-echo-no-exit-record"], "satisfied")

    def test_bash_c_wrapper_not_newly_satisfied(self):
        self.assertEqual(self.outcome["edge-bash-c-wrapper"], "missing")

    # ---- D27: grammar-derived runner identification in the default derivation ----
    D27_FORGED_PREFIXES = ("edge-forged-append-", "edge-forged-escaped-separator-", "edge-forged-join-",
                           "edge-forged-value-blank-", "edge-forged-pipeline-mention-", "edge-forged-version-single-")

    def _d27_forged(self, with_separator):
        ids = [i for i, r in self.rows.items() if i.startswith(self.D27_FORGED_PREFIXES)
               and any(s in r["command"] for s in (";", "\n", "||")) is with_separator]
        return ids

    def test_d27_forgeries_with_a_separator_missing_by_default(self):
        # Mutation: keeping isRealRunnerInvocation in attributable, keeping the unconditional single-statement
        # shortcut, or testing only isBr6RunnerStatement in step 4 (the version-single rows).
        ids = self._d27_forged(True)
        self.assertEqual(len(ids), 26)
        for i in ids:
            with self.subTest(id=i):
                self.assertEqual(self.outcome[i], "missing")

    def test_d27_separator_free_forgeries_keep_5801cb9_default(self):
        # Mutation: dropping the explicit separator-free step (these rows would turn missing).
        ids = self._d27_forged(False)
        self.assertEqual(len(ids), 6)
        for i in ids:
            with self.subTest(id=i):
                self.assertEqual(self.outcome[i], "satisfied")

    def test_d27_grammar_runner_shapes_satisfy(self):
        # Mutation: reading an assignment prefix, an escaped blank in a value or a background head as no runner run.
        ids = [i for i in self.rows if i.startswith(("edge-inside-runner-", "edge-inside-value-", "edge-inside-append-",
                                                     "edge-inside-background-"))]
        self.assertEqual(len(ids), 23)
        for i in ids:
            with self.subTest(id=i):
                self.assertEqual(self.outcome[i], "satisfied")

    # ---- D28 (DP40): pipe-newline, launcher, option and script-name rows in the default derivation ----
    D28_FORGED_PREFIXES = ("edge-forged-pipe-newline-", "edge-forged-launcher-list-", "edge-forged-option-",
                           "edge-forged-script-option-")

    def test_d28_forgeries_with_a_separator_missing_by_default(self):
        # Mutation: no null at a newline while a pipe waits (the pipe-newline rows), a `py -0` selector, or
        # VERSION_HELP_ARGS as the only version test (the option rows) turns a row satisfied.
        ids = [i for i, r in self.rows.items() if i.startswith(self.D28_FORGED_PREFIXES)
               and any(s in r["command"] for s in (";", "\n", "||"))]
        self.assertEqual(len(ids), 30)
        for i in ids:
            with self.subTest(id=i):
                self.assertEqual(self.outcome[i], "missing")

    def test_d28_separator_free_forgeries_keep_5801cb9_default(self):
        # Mutation: a default step that reads the DP40 rules for a separator-free command (these rows would turn
        # missing).
        for i in ("edge-forged-launcher-list-single", "edge-forged-option-pytest-cluster-single",
                  "edge-forged-option-npm-single"):
            with self.subTest(id=i):
                self.assertEqual(self.outcome[i], "satisfied")

    def test_d28_inside_rows_satisfy(self):
        # Mutation: dropping the script-name branch, the `py` selector, the verbose `-v` runner set or the neutral
        # allowlist, or ending a statement at a newline after `&&`, turns a row missing.
        ids = [i for i in self.rows if i.startswith(("edge-inside-join-", "edge-inside-selector-",
                                                     "edge-inside-option-", "edge-inside-script-"))]
        self.assertEqual(len(ids), 19)
        for i in ids:
            with self.subTest(id=i):
                self.assertEqual(self.outcome[i], "satisfied")

    # ---- D29 (DP41): redirection-target `--` and key-letter rows in the default derivation ----
    D29_FORGED_PREFIXES = ("edge-forged-target-separator-", "edge-forged-key-letter-")

    def test_d29_forgeries_with_a_separator_missing_by_default(self):
        # Mutation: a redirection target `--` that ends the option region, or a single-dash word judged to its end,
        # turns a row satisfied.
        ids = [i for i, r in self.rows.items() if i.startswith(self.D29_FORGED_PREFIXES)
               and any(s in r["command"] for s in (";", "\n", "||"))]
        self.assertEqual(len(ids), 18)
        for i in ids:
            with self.subTest(id=i):
                self.assertEqual(self.outcome[i], "missing")

    def test_d29_separator_free_forgeries_keep_5801cb9_default(self):
        for i in ("edge-forged-target-separator-single", "edge-forged-key-letter-single"):
            with self.subTest(id=i):
                self.assertEqual(self.outcome[i], "satisfied")

    def test_d29_inside_rows_satisfy(self):
        # Mutation: counting a redirection target `--` as an option word, or reading a single-dash word without a key
        # letter as a version or help spelling, turns a row missing.
        ids = [i for i in self.rows if i.startswith(("edge-inside-target-separator-", "edge-inside-key-letter-"))]
        self.assertEqual(len(ids), 4)
        for i in ids:
            with self.subTest(id=i):
                self.assertEqual(self.outcome[i], "satisfied")

    # ---- D30 (DP42): dash-word rows in the default derivation ----
    D30_REAL_FORGED_PREFIX = "edge-real-forged-dash-word-"

    def test_d30_forgeries_with_a_separator_missing_by_default(self):
        # Mutation: a two-dash word judged by its whole part before `=`, or a three-dash word left out, turns a row
        # satisfied.
        ids = [i for i, r in self.rows.items() if i.startswith(self.D30_REAL_FORGED_PREFIX)
               and any(s in r["command"] for s in (";", "\n", "||"))]
        self.assertEqual(len(ids), 15)
        for i in ids:
            with self.subTest(id=i):
                self.assertEqual(self.outcome[i], "missing")

    def test_d30_separator_free_forgery_keeps_5801cb9_default(self):
        self.assertEqual(self.outcome[self.D30_REAL_FORGED_PREFIX + "single"], "satisfied")

    def test_d30_inside_rows_satisfy(self):
        # Mutation: reading a two-dash word without a leading letter-run prefix (`--.h`, `--no-help`) as a version or
        # help spelling turns a row missing.
        ids = [i for i in self.rows if i.startswith("edge-inside-dash-word-")]
        self.assertEqual(len(ids), 4)
        for i in ids:
            with self.subTest(id=i):
                self.assertEqual(self.outcome[i], "satisfied")


# ---- AC31, AC41, AC42: opt-in AGENTIC_FLOW_STRICT_EVIDENCE for live Codex evidence (Task 18) ----
STRICT_ON = {"AGENTIC_FLOW_STRICT_EVIDENCE": "true"}


def _strictly_attributable(rows):
    """isStrictlyAttributable({command, callEvents, outputRecords, exitCode}, re) per table row."""
    items = [{"command": r["command"], "callEvents": r["carrier"]["callEvents"],
              "outputRecords": r["carrier"]["outputRecords"], "exitCode": r["carrier"]["exitCode"]} for r in rows]
    script = ("const e = await import(%s); const f = await import(%s);"
              "const re = new RegExp(f.loadRequirements().testCommand, 'i');"
              "process.stdout.write(JSON.stringify(JSON.parse(process.argv[1]).map((x) => e.isStrictlyAttributable(x, re))));"
              % (json.dumps(EVID.as_uri()), json.dumps(FLOW_EVID.as_uri())))
    return json.loads(_node(script, json.dumps(items)))


class TestStrictEvidenceFlag(_Tmp):
    """Strict Codex `tests` evidence under the flag: only an attributable, single-counted, green run
    satisfies it. Table outcomes are derived once per flag state; the tests select rows by id."""

    @classmethod
    def setUpClass(cls):
        cls.rows, cls.strict, _ = _br6_tests_outcomes(STRICT_ON)
        _, cls.default, _ = _br6_tests_outcomes()

    def _row_rollout(self, row_id):
        cwd = self._cwd()
        path = _br6_rollout(cwd, self.rows[row_id])
        self.addCleanup(os.unlink, path)
        return path, cwd

    def test_is_strictly_attributable_matches_table(self):  # D3
        rows = list(self.rows.values())
        got = _strictly_attributable(rows)
        bad = [row["id"] for row, value in zip(rows, got) if value != row["strictAttributable"]]
        self.assertEqual(bad, [], f"isStrictlyAttributable disagrees with strictAttributable: {bad}")

    def test_shared_table_strict_column(self):  # D3
        bad = [i for i, row in self.rows.items() if self.strict[i] != row["strictTests"]]
        self.assertEqual(bad, [], f"rows whose strict tests outcome differs from strictTests: {bad}")

    def test_strict_flag_rejects_fail_open_shape_only_version_only_and_pipe(self):  # AC42, AC31 strict half
        for i in ("carrier-substrate-absent", "edge-standalone-version", "edge-cd-andand-version",
                  "ac31-pipe-tee", "ac31-pipe-tail"):
            with self.subTest(id=i):
                self.assertEqual(self.strict[i], "missing")

    def test_strict_duplicate_call_or_missing_output_not_satisfied(self):
        for i in ("carrier-duplicate-call-event", "carrier-duplicate-output-record", "carrier-missing-exit-code"):
            with self.subTest(id=i):
                self.assertEqual(self.strict[i], "missing")

    def test_strict_flag_value_matrix(self):
        path, cwd = self._row_rollout("carrier-substrate-absent")
        for value, expected in (("TRUE", "missing"), ("1", "missing"), ("yes", "missing"),
                                ("false", "satisfied"), ("0", "satisfied"), ("", "satisfied"), (None, "satisfied")):
            with self.subTest(value=value):
                env = None if value is None else {"AGENTIC_FLOW_STRICT_EVIDENCE": value}
                steps = _derive_env([path], cwd, env)[0]["missingBlockSteps"]
                self.assertEqual("missing" if "tests" in steps else "satisfied", expected)

    def test_strict_hook_blocks_under_gate_flag(self):
        path, cwd = self._row_rollout("carrier-substrate-absent")
        out = _run_hook({"transcript_path": path, "cwd": str(cwd)},
                        {"AGENTIC_FLOW_GATE_BLOCK": "true", **STRICT_ON})
        self.assertIn('"decision":"block"', out.replace(" ", ""))
        self.assertIn("[tests]", out)

    # ---- guards: pass before and after the flag exists ----
    def test_shared_table_flag_unset_equals_default(self):
        bad = [i for i, row in self.rows.items() if self.default[i] != row["defaultTests"]]
        self.assertEqual(bad, [], f"flag-unset outcomes that differ from defaultTests: {bad}")

    def test_strict_flag_accepts_attributable_green_run(self):
        self.assertEqual(self.strict["carrier-plain-green"], "satisfied")

    def test_flag_unset_existing_fixture_outcomes_unchanged(self):  # AC41
        for i in ("edge-standalone-version", "carrier-substrate-absent", "carrier-missing-exit-code"):
            with self.subTest(id=i):
                self.assertEqual(self.default[i], "satisfied")


# ---- AC28 closure: a mid-line comment or a heredoc cannot lend a trailing exit 0 to the runner ----
def _synthetic_row(row_id, command, exit_code=0):
    """A carrier shaped like a shared-table row (one call event, one output record), built in this
    module only: the shared table is read-only (D3)."""
    return {"id": row_id, "command": command,
            "carrier": {"callEvents": 1, "outputRecords": 1, "exitCode": exit_code, "outputSummary": "5 passed"}}


class TestCommentAndHeredocForgery(_Tmp):
    """bash ends `pytest; echo EXIT=$? # ; pytest` on echo and `pytest; cat <<EOF\\npytest` on cat, so
    their exit 0 never belongs to pytest. D23: an exit code is attributed only while the command lies inside
    the safe shell grammar (inSafeBr6Grammar); a command holding `;`, newline or `||` outside it is never
    attributable by default, and strict evaluation applies the grammar to every command. Mutation: dropping
    the comment skip in splitBr6Statements, the grammar check in attributable() / isStrictlyAttributable(),
    or the head-operand pipe/background check."""

    FORGED = {"comment": "pytest; echo EXIT=$? # ; pytest", "heredoc": "pytest; cat <<EOF\npytest",
              "heredoc-dash": "pytest; cat <<-EOF\npytest",
              "paren-comment": "pytest; (echo x)# ; pytest",  # bash ends on the subshell's exit 0
              # Constructs outside the safe grammar hide a separator inside a word, so bash ends on
              # echo/cat (bash 5.2.37: rc=0 from the trailing echo/cat for every row).
              "command-substitution": "pytest; echo $(echo x; pytest)",
              "process-substitution": "pytest; cat <(echo x; pytest)",
              "backtick": "pytest; echo `true; pytest`",
              "substitution-in-double-quotes": 'pytest; echo "$(echo "; pytest")"',
              "ansi-c-quote": "pytest; echo $'\\'; pytest'",
              "param-comment-closer": "pytest; echo ${x:-; pytest #}",
              "double-bracket": "[[ x &&\npytest ||\npytest ]]",
              # Command words outside the grammar shadow the runner or rewrite the exit status.
              "function-shadow": "pytest() { true; }; pytest",
              "eval-function-shadow": "cd repo; eval 'pytest() { true; }'; pytest",
              "set-noexec": "set -n; pytest",
              "trap-exit-rewrite": "trap 'exit 0' EXIT; pytest",
              # A left `||` operand that succeeds means bash never runs the right side, and a piped or
              # backgrounded head operand's own exit decides whether the runner after `||` runs.
              "oror-leading-success": "true || pytest",
              "oror-leading-version": "pytest --version || pytest",
              "oror-newline-leading-echo": "echo ok ||\npytest",
              "oror-piped-operand": "pytest | tee log.txt || pytest",
              "oror-background-head": "pytest & wait || pytest"}
    # Separator-free commands outside the grammar keep their 5801cb9 default (a disclosed limit: `set -n &&
    # pytest` never runs pytest), but strict evaluation applies the grammar to every command.
    STRICT_ONLY = {"hidden-pipe-ansi-c": "pytest $'\\'' | true ''",
                   "separator-free-substitution": "pytest $(cat args)",
                   "separator-free-noexec": "set -n && pytest"}
    # Every operand of the trailing `||` run is a real runner inside the grammar.
    OROR_RUNNERS = {"oror-real-runners": "pytest -x || pytest --lf"}
    # `pytest # --version` runs a bare pytest: the gate reads version/help on the comment-free last
    # statement only, so it is a real run (the whole-command helper value alone still sees `--version`).
    ONE_RUNNER = {"comment-after-runner": "pytest # ; echo x", "comment-version": "pytest # --version"}
    # Disclosed conservative limits of the grammar: a false 'missing', never a false satisfy. Any syntax or
    # command word outside the safe grammar together with a `;`, newline or `||` fails closed, so a
    # legitimate `cd repo; pytest $(cat args)` or `source .venv/bin/activate; pytest` is missing.
    CONSERVATIVE = {"arith-shift": "pytest; echo $((1<<2)); pytest",
                    "substitution-with-separator": "cd repo; pytest $(cat args)",
                    "here-string": "pytest; cat <<<x; pytest",
                    "source-venv": "source .venv/bin/activate; pytest"}

    def _outcomes(self, rows, env_extra=None):
        cwd = self._cwd()
        paths = [_br6_rollout(cwd, row) for row in rows]
        for path in paths:
            self.addCleanup(os.unlink, path)
        results = _derive_env(paths, cwd, env_extra)
        return {row["id"]: ("missing" if "tests" in res["missingBlockSteps"] else "satisfied")
                for row, res in zip(rows, results)}

    def _rows(self, commands):
        return [_synthetic_row(name, command) for name, command in commands.items()]

    def test_forged_shapes_default_tests_step_missing(self):
        got = self._outcomes(self._rows(self.FORGED))
        self.assertEqual(got, {name: "missing" for name in self.FORGED})

    def test_forged_shapes_not_strictly_attributable(self):
        rows = self._rows(self.FORGED)
        self.assertEqual(_strictly_attributable(rows), [False] * len(rows))
        self.assertEqual(self._outcomes(rows, STRICT_ON), {name: "missing" for name in self.FORGED})

    # ---- guards: pass before and after the closure ----
    def test_single_runner_statement_shapes_still_satisfy(self):
        rows = self._rows(self.ONE_RUNNER)
        self.assertEqual(self._outcomes(rows), {name: "satisfied" for name in self.ONE_RUNNER})
        self.assertEqual(_strictly_attributable(rows), [True] * len(rows))

    def test_single_statement_outside_grammar_is_strict_only(self):
        # Mutation: applying the grammar to strict separator commands only. The default keeps 5801cb9 for them.
        rows = self._rows(self.STRICT_ONLY)
        self.assertEqual(_strictly_attributable(rows), [False] * len(rows))
        self.assertEqual(self._outcomes(rows, STRICT_ON), {name: "missing" for name in self.STRICT_ONLY})
        self.assertEqual(self._outcomes(rows), {name: "satisfied" for name in self.STRICT_ONLY})

    def test_real_runner_oror_run_still_satisfies(self):
        rows = self._rows(self.OROR_RUNNERS)
        self.assertEqual(self._outcomes(rows), {name: "satisfied" for name in self.OROR_RUNNERS})
        self.assertEqual(_strictly_attributable(rows), [True] * len(rows))

    def test_disclosed_conservative_limits_never_satisfy(self):
        rows = self._rows(self.CONSERVATIVE)
        self.assertEqual(self._outcomes(rows), {name: "missing" for name in self.CONSERVATIVE})
        self.assertEqual(self._outcomes(rows, STRICT_ON), {name: "missing" for name in self.CONSERVATIVE})


# ---- AC35: the locked Codex Stop guard never reports the branch step (Task 19) ----
GIT = shutil.which("git")


@unittest.skipIf(GIT is None, "git not available")
class TestCodexStopNoBranchReport(_Tmp):
    def _repo(self, branch):
        repo = Path(self._cwd())
        for args in (("init", "-b", "main"),
                     ("-c", "user.email=slice-b@invalid", "-c", "user.name=slice-b", "commit", "--allow-empty", "-m", "init")):
            subprocess.run([GIT, *args], cwd=repo, check=True, capture_output=True)
        if branch != "main":
            subprocess.run([GIT, "checkout", "-b", branch], cwd=repo, check=True, capture_output=True)
        return repo

    def _stop_output(self, branch, extra, env_extra):
        repo = self._repo(branch)
        spec = _artifact(repo, "spec", "W")
        plan = _artifact(repo, "plan", "W")
        path = _write_rollout([_mark_write(spec), _mark_write(plan), _src_patch(), *extra])
        self.addCleanup(os.unlink, path)
        return _run_hook({"transcript_path": path, "cwd": str(repo)}, env_extra)

    def test_main_and_feature_outputs_identical_no_branch(self):  # AC35
        for flags in ({}, {"AGENTIC_FLOW_GATE_BLOCK": "true"}, {"AGENTIC_FLOW_GATE_BLOCK": "true", **STRICT_ON}):
            with self.subTest(flags=flags):
                on_main = self._stop_output("main", [], flags)
                self.assertTrue(on_main.strip())  # the tests step is missing, so the guard speaks
                self.assertEqual(on_main, self._stop_output("feature/x", [], flags))
                self.assertNotIn("branch", on_main)
        green = [_exec_fc_id("pytest", "c1"), _fc_output("c1", 0, "1 passed")]
        self.assertEqual(self._stop_output("main", green, {}).strip(), "")


if __name__ == "__main__":
    unittest.main()
