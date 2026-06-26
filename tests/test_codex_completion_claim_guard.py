"""AP2a — Codex completion-claim guard (marker mechanism). Covers AC1-AC17.

Parser unit tests drive `hooks/codex-rollout.mjs` via `node` over synthetic rollout fixtures;
behavioral tests drive the real Stop hook `hooks/completion-claim-guard-codex.mjs` as a subprocess.
All text-mode subprocess calls pin encoding='utf-8' (locale-independent, house rule from PR #10/#11).
"""
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROLLOUT = REPO / "hooks" / "codex-rollout.mjs"
HOOK = REPO / "hooks" / "completion-claim-guard-codex.mjs"
CLAUDE_GUARD = REPO / "hooks" / "completion-claim-guard.mjs"
SKILL = REPO / "skills" / "completion-claim-gate" / "SKILL.md"
CODEX_CFG = REPO / "hooks" / "hooks-codex.json"

MARKER = "<!-- agentic-sdlc:gate:completion-claim:verified -->"
# A claim that matches CLAIM and not NEGATED; distinctive so AC10 can assert its absence from output.
CLAIM_TEXT = "All tests passing, done and verified. SENTINEL_CLAIM_XYZ"


# ---- fixture helpers -------------------------------------------------------
def _line(type_, payload):
    return json.dumps({"type": type_, "payload": payload})


def _assistant(text):
    return _line("response_item", {"type": "message", "role": "assistant",
                                   "content": [{"type": "output_text", "text": text}]})


def _agent_msg(text):
    return _line("event_msg", {"type": "agent_message", "message": text})


def _task_complete(text):
    return _line("event_msg", {"type": "task_complete", "last_agent_message": text})


def _user(text):
    return _line("response_item", {"type": "message", "role": "user",
                                   "content": [{"type": "input_text", "text": text}]})


def _write_rollout(lines):
    fd, path = tempfile.mkstemp(suffix=".jsonl", prefix="codex-rollout-")
    os.close(fd)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _read_rollout(path):
    """Call readRollout(path) from the real module and return its result dict."""
    script = (
        "const m = await import(%s);"
        "process.stdout.write(JSON.stringify(m.readRollout(process.argv[1])));"
        % json.dumps(ROLLOUT.as_uri())
    )
    r = subprocess.run(["node", "--input-type=module", "-e", script, path],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _gate_marker_const():
    """The GATE_MARKER constant as the module actually exports it."""
    script = ("const m = await import(%s); process.stdout.write(m.GATE_MARKER);"
              % json.dumps(ROLLOUT.as_uri()))
    r = subprocess.run(["node", "--input-type=module", "-e", script],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout


def _run_hook(stop_input, env_extra=None):
    env = dict(os.environ)
    env.pop("AGENTIC_COMPLETION_GATE_BLOCK", None)
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


# ---- AC1, AC16: the pure rollout reader ------------------------------------
class TestRolloutReader(unittest.TestCase):
    def test_final_from_task_complete_authoritative(self):  # AC1
        path = _write_rollout([_assistant("earlier"), _task_complete("FINAL"), _assistant("trailing")])
        self.assertEqual(_read_rollout(path)["finalMessage"], "FINAL")

    def test_final_from_assistant_when_no_task_complete(self):  # AC1
        path = _write_rollout([_assistant("first"), _agent_msg("LAST")])
        self.assertEqual(_read_rollout(path)["finalMessage"], "LAST")

    def test_marker_in_final_message(self):  # AC2
        path = _write_rollout([_assistant("work"), _task_complete("done " + MARKER)])
        self.assertTrue(_read_rollout(path)["gateMarkerPresent"])

    def test_marker_in_earlier_carrier(self):  # AC2 (two placements)
        path = _write_rollout([_assistant("ran the gate " + MARKER), _task_complete(CLAIM_TEXT)])
        self.assertTrue(_read_rollout(path)["gateMarkerPresent"])

    def test_marker_absent(self):  # AC2
        path = _write_rollout([_assistant("work"), _task_complete(CLAIM_TEXT)])
        self.assertFalse(_read_rollout(path)["gateMarkerPresent"])

    def test_name_mention_is_not_marker(self):  # AC2 (name != signature)
        path = _write_rollout([_assistant("I ran completion-claim-gate"), _task_complete(CLAIM_TEXT)])
        self.assertFalse(_read_rollout(path)["gateMarkerPresent"])

    def test_missing_file_unconfirmable(self):  # AC8/DP5
        r = _read_rollout("/no/such/rollout.jsonl")
        self.assertFalse(r["readable"])
        self.assertFalse(r["gateMarkerPresent"])

    def test_unknown_line_types_tolerated(self):  # AC1 tolerance
        path = _write_rollout([_line("turn_context", {"type": "whatever"}), "{not json",
                               _task_complete("FINAL " + MARKER)])
        r = _read_rollout(path)
        self.assertEqual(r["finalMessage"], "FINAL " + MARKER)
        self.assertTrue(r["gateMarkerPresent"])

    def test_over_ceiling_unconfirmable(self):  # AC16b
        # > 8 MiB -> readable:false (never toward a block), without ever scanning content.
        fd, path = tempfile.mkstemp(suffix=".jsonl", prefix="codex-big-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(_task_complete(CLAIM_TEXT) + "\n")
            fh.write("x" * (8 * 1024 * 1024 + 16))
        r = _read_rollout(path)
        self.assertFalse(r["readable"])
        os.unlink(path)


# ---- AC17: marker output contract + single-source drift lock ---------------
class TestGateMarkerContract(unittest.TestCase):
    def test_skill_md_contains_marker(self):  # AC17 (R12)
        self.assertIn(MARKER, SKILL.read_text(encoding="utf-8"))

    def test_marker_single_source_no_drift(self):  # AC17 (derive both, never re-hardcode)
        const = _gate_marker_const()  # from the guard module
        m = re.search(r"<!--\s*agentic-sdlc:gate:[^>]*?-->", SKILL.read_text(encoding="utf-8"))
        self.assertIsNotNone(m, "no sentinel literal found in SKILL.md")
        self.assertEqual(const, m.group(0))  # byte-identical


# ---- AC2-AC10: behavioral Stop hook ----------------------------------------
class TestGuardBehavior(unittest.TestCase):
    def _stop(self, lam, rollout_lines, **kw):
        path = _write_rollout(rollout_lines)
        inp = {"last_assistant_message": lam, "transcript_path": path}
        inp = {**inp, **kw} if False else inp
        for k, v in kw.items():
            inp[k] = v
        return inp

    def test_block_without_marker(self):  # AC3
        inp = self._stop(CLAIM_TEXT, [_assistant("work"), _task_complete(CLAIM_TEXT)])
        out = _run_hook(inp, {"AGENTIC_COMPLETION_GATE_BLOCK": "true"})
        self.assertIn('"decision":"block"', out.replace(" ", ""))

    def test_silent_with_marker(self):  # AC2
        inp = self._stop(CLAIM_TEXT, [_assistant("ran gate " + MARKER), _task_complete(CLAIM_TEXT)])
        out = _run_hook(inp, {"AGENTIC_COMPLETION_GATE_BLOCK": "true"})
        self.assertEqual(out.strip(), "")

    def test_default_advisory_no_block_env(self):  # AC4
        inp = self._stop(CLAIM_TEXT, [_task_complete(CLAIM_TEXT)])
        out = _run_hook(inp)  # no block env
        self.assertIn("systemMessage", out)
        self.assertNotIn("block", out)

    def test_silent_no_claim(self):  # AC5
        inp = self._stop("Here is a progress update; a couple tests remain.", [_task_complete("update")])
        out = _run_hook(inp, {"AGENTIC_COMPLETION_GATE_BLOCK": "true"})
        self.assertEqual(out.strip(), "")

    def test_negated_claim_silent(self):  # AC6
        inp = self._stop("All tests passing, but it's not done yet.", [_task_complete("x")])
        out = _run_hook(inp, {"AGENTIC_COMPLETION_GATE_BLOCK": "true"})
        self.assertEqual(out.strip(), "")

    def test_stop_hook_active_silent(self):  # AC7
        inp = self._stop(CLAIM_TEXT, [_task_complete(CLAIM_TEXT)], stop_hook_active=True)
        out = _run_hook(inp, {"AGENTIC_COMPLETION_GATE_BLOCK": "true"})
        self.assertEqual(out.strip(), "")

    def test_missing_transcript_silent(self):  # AC8/DP5
        inp = {"last_assistant_message": CLAIM_TEXT, "transcript_path": "/no/such.jsonl"}
        out = _run_hook(inp, {"AGENTIC_COMPLETION_GATE_BLOCK": "true"})
        self.assertEqual(out.strip(), "")

    def test_malformed_stdin_silent(self):  # AC8/R7
        out = _run_hook("this is not json", {"AGENTIC_COMPLETION_GATE_BLOCK": "true"})
        self.assertEqual(out.strip(), "")

    def test_fffd_primary_falls_back_to_rollout(self):  # AC9c
        inp = self._stop("garbled�message", [_task_complete(CLAIM_TEXT)])  # suspect primary, no marker
        out = _run_hook(inp, {"AGENTIC_COMPLETION_GATE_BLOCK": "true"})
        self.assertIn('"decision":"block"', out.replace(" ", ""))  # used the rollout final text

    def test_output_carries_no_claim_text(self):  # AC10
        inp = self._stop(CLAIM_TEXT, [_task_complete(CLAIM_TEXT)])
        out = _run_hook(inp, {"AGENTIC_COMPLETION_GATE_BLOCK": "true"})
        self.assertNotIn("SENTINEL_CLAIM_XYZ", out)  # the distinctive claim substring never leaks


# ---- AC11: Claude byte-identical + regex parity ----------------------------
class TestClaudeParity(unittest.TestCase):
    @staticmethod
    def _extract(pattern_name, text):
        m = re.search(r"const %s\s*=\s*(/.*?/[a-z]*)\s*;" % pattern_name, text, re.DOTALL)
        assert m, f"could not extract {pattern_name}"
        return re.sub(r"\s+", "", m.group(1))  # normalize incidental wrapping whitespace

    def test_claim_negation_regex_parity(self):  # AC11
        claude = CLAUDE_GUARD.read_text(encoding="utf-8")
        codex = HOOK.read_text(encoding="utf-8")
        for name in ("CLAIM", "NEGATED"):
            self.assertEqual(self._extract(name, claude), self._extract(name, codex),
                             f"{name} regex drifted between Claude and Codex guards")

    def test_claude_guard_byte_identical(self):  # AC11 / §10
        head = _git_show("hooks/completion-claim-guard.mjs")
        self.assertIsNotNone(head, "completion-claim-guard.mjs not in HEAD")
        self.assertEqual(CLAUDE_GUARD.read_text(encoding="utf-8"), head)


# ---- AC12, AC13: Codex-only Stop wiring, AP1 untouched ----------------------
class TestWiring(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads(CODEX_CFG.read_text(encoding="utf-8"))

    def test_stop_block_wired_shell_string_plugin_root(self):  # AC12
        stop = self.cfg["hooks"]["Stop"]
        cmds = [h["command"] for blk in stop for h in blk["hooks"]]
        target = [c for c in cmds if "completion-claim-guard-codex.mjs" in c]
        self.assertEqual(len(target), 1)
        self.assertIsInstance(target[0], str)  # shell-string form (args-array does not run on Codex)
        self.assertIn("${PLUGIN_ROOT}", target[0])

    def test_no_claude_plugin_root_and_no_hooks_json(self):  # AC12
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", CODEX_CFG.read_text(encoding="utf-8"))
        self.assertFalse((REPO / "hooks" / "hooks.json").exists())

    def test_ap1_pretooluse_and_sessionstart_unchanged(self):  # AC13 (additive-only since AP2c)
        # AP2c additively appends flow-order-guard-codex.mjs to the Bash|apply_patch PreToolUse
        # block, so strict PreToolUse == HEAD is no longer the contract. The AP2a intent — this
        # slice does not touch the AP1 PreToolUse surface or SessionStart — is preserved as
        # additive-only: SessionStart unchanged, the Bash command-guard block unchanged, and the
        # scan-write-codex handler dict unchanged.
        head = json.loads(_git_show("hooks/hooks-codex.json"))
        self.assertEqual(self.cfg["hooks"]["SessionStart"], head["hooks"]["SessionStart"])
        cur_bash = [b for b in self.cfg["hooks"]["PreToolUse"] if b.get("matcher") == "Bash"]
        head_bash = [b for b in head["hooks"]["PreToolUse"] if b.get("matcher") == "Bash"]
        self.assertEqual(cur_bash, head_bash)

        def _scan_handler(cfg):
            for b in cfg["hooks"]["PreToolUse"]:
                if b.get("matcher") == "Bash|apply_patch":
                    return [h for h in b["hooks"] if "scan-write-codex.mjs" in h["command"]]
            return []

        self.assertEqual(_scan_handler(self.cfg), _scan_handler(head))


if __name__ == "__main__":
    unittest.main()
