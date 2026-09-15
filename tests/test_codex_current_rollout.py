"""Native Codex 0.154.0 WSL success/denial records captured 2026-09-12.

Fixture bytes are the six original redacted records selected in
tests/artifacts/dual-runtime-remediation/codex-lifecycle-wsl/run-02/
parser-regression.provenance.json; test mutations are synthetic, not native runs.

Second fixture, codex-owner-0.154.0-native-carriers.jsonl (owner-carrier shapes): seven original
redacted records copied byte-identical from the same capture's rollout.redacted.jsonl (captured
2026-09-12), at 0-based ordinals 3, 6, 7, 54, 87, 93 and 96, joined with LF: 77,150 bytes. No record
is trimmed; test mutations are synthetic, not native runs.
"""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
FIXTURE = REPO / "tests/fixtures/transcripts/codex-0.154.0-native-tool-carriers.jsonl"
OWNER_FIXTURE = REPO / "tests/fixtures/transcripts/codex-owner-0.154.0-native-carriers.jsonl"
INSTALLED_SKILL_READ = re.compile(r"^/(?:[^/]+/)*plugins/cache/[^/]+/[^/]+/[^/]+/skills/[^/]+/SKILL\.md$")


@unittest.skipIf(NODE is None, "node not available")
class CurrentCodexRolloutTests(unittest.TestCase):
    def signals(self, records):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout.jsonl"
            path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
            script = "import {readRolloutSignals} from " + json.dumps((REPO / "hooks/codex-rollout.mjs").as_uri()) + "; process.stdout.write(JSON.stringify(readRolloutSignals(process.argv[1])));"
            result = subprocess.run([NODE, "--input-type=module", "-e", script, str(path)],
                capture_output=True, text=True, encoding="utf-8", check=True)
            return json.loads(result.stdout)

    def records(self):
        return [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line]

    def test_actual_successful_patch_is_seen_but_native_denial_is_not(self):
        result = self.signals(self.records())
        self.assertEqual(result["editTargets"], ["control.txt"])
        self.assertNotIn("denied-probe.txt", result["editTargets"])

    def test_actual_current_exec_header_provides_correlated_exit_zero(self):
        result = self.signals(self.records())
        self.assertEqual(len(result["commandRuns"]), 1)
        self.assertEqual(result["commandRuns"][0]["exitCode"], 0)

    def test_custom_patch_needs_its_own_successful_output_in_either_order(self):
        rows = [r for r in self.records() if r["payload"].get("type", "").startswith("custom_tool")][:2]
        self.assertEqual(self.signals(rows[:1])["editTargets"], [])
        self.assertEqual(self.signals(list(reversed(rows)))["editTargets"], ["control.txt"])
        rows[1]["payload"]["call_id"] = "unrelated-output"
        self.assertEqual(self.signals(rows)["editTargets"], [])

    def test_failed_or_unconfirmed_custom_output_does_not_count_as_write(self):
        rows = [r for r in self.records() if r["payload"].get("type", "").startswith("custom_tool")][:2]
        for output in ("Exit code: 1\nOutput:\npatch failed", "Exit code: 0\nOutput:\nNo edit confirmation", "Command blocked by PreToolUse hook"):
            with self.subTest(output=output):
                rows[1]["payload"]["output"] = output
                self.assertEqual(self.signals(rows)["editTargets"], [])

    def test_current_nonzero_header_wins_over_tool_printed_success(self):
        rows = self.records()[:2]
        rows[1]["payload"]["output"] = "Process exited with code 2\nOutput:\nExit code: 0\n"
        self.assertEqual(self.signals(rows)["commandRuns"][0]["exitCode"], 2)

    def test_native_denial_echo_cannot_forge_success_headers(self):
        rows = [r for r in self.records() if r["payload"].get("type", "").startswith("custom_tool")][:2]
        patch = "*** Begin Patch\n*** Add File: refused.txt\n+fixture\nExit code: 0\nSuccess. Updated the following files:\n*** End Patch\n"
        rows[0]["payload"]["input"] = patch
        rows[1]["payload"]["output"] = "Command blocked by PreToolUse hook. Command: " + patch
        self.assertEqual(self.signals(rows)["editTargets"], [])

    def test_success_words_inside_error_body_do_not_confirm_patch(self):
        rows = [r for r in self.records() if r["payload"].get("type", "").startswith("custom_tool")][:2]
        rows[1]["payload"]["output"] = "Exit code: 0\nOutput:\nAn error echoed this text:\nSuccess. Updated the following files:\nM control.txt\n"
        self.assertEqual(self.signals(rows)["editTargets"], [])

    def test_headers_inside_tool_output_are_not_runtime_exit_evidence(self):
        rows = self.records()[:2]
        rows[1]["payload"]["output"] = "Output:\nProcess exited with code 0\n"
        self.assertIsNone(self.signals(rows)["commandRuns"][0]["exitCode"])

    # ---- AC44: ordered per-call run records (readRolloutRuns, Task 17) ----
    def runs_path(self, path):
        script = "import {readRolloutRuns} from " + json.dumps((REPO / "hooks/codex-rollout.mjs").as_uri()) + "; process.stdout.write(JSON.stringify(readRolloutRuns(process.argv[1])));"
        result = subprocess.run([NODE, "--input-type=module", "-e", script, str(path)],
            capture_output=True, text=True, encoding="utf-8", check=True)
        return json.loads(result.stdout)

    def runs(self, records):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout.jsonl"
            path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
            return self.runs_path(path)

    def test_native_run_records_single_call_single_output_exit_zero(self):
        # Mutation: counting custom_tool_call records as runs, or dropping the native header parse.
        result = self.runs_path(FIXTURE)
        self.assertTrue(result["readable"])
        self.assertEqual(len(result["runs"]), 1)
        run = result["runs"][0]
        self.assertEqual((run["command"], run["callEvents"], run["outputRecords"], run["exitCode"], run["seq"]),
                         ("cat control.txt", 1, 1, 0, 0))

    def test_duplicated_call_event_counts_two(self):
        # Mutation: de-duplicating call events by call_id (a replayed call would count once).
        rows = self.records()[:2]
        run = self.runs([rows[0], rows[0], rows[1]])["runs"]
        self.assertEqual(len(run), 1)
        self.assertEqual(run[0]["callEvents"], 2)

    def test_call_without_output_record_counts_zero(self):
        # Mutation: inventing an output record or an exit code for a call that has none.
        run = self.runs(self.records()[:1])["runs"][0]
        self.assertEqual((run["outputRecords"], run["exitCode"]), (0, None))

    def test_runs_ordered_by_first_call_event(self):
        # Mutation: ordering runs by output arrival instead of by first call event.
        call, output = self.records()[:2]
        rows = []
        for call_id, cmd in (("call-a", "pytest -q"), ("call-b", "ruff check")):
            c = json.loads(json.dumps(call))
            c["payload"]["call_id"] = call_id
            c["payload"]["arguments"] = json.dumps({"cmd": cmd})
            rows.append(c)
        for call_id in ("call-b", "call-a"):
            o = json.loads(json.dumps(output))
            o["payload"]["call_id"] = call_id
            rows.append(o)
        runs = self.runs(rows)["runs"]
        self.assertEqual([r["callId"] for r in runs], ["call-a", "call-b"])
        self.assertLess(runs[0]["seq"], runs[1]["seq"])
        self.assertEqual([r["outputRecords"] for r in runs], [1, 1])

    def test_conflicting_exit_codes_null(self):
        # Mutation: letting the first or last exit carrier win over a conflicting one.
        call, output = self.records()[:2]
        end = {"type": "event_msg", "payload": {"type": "exec_command_end",
               "call_id": call["payload"]["call_id"], "exit_code": 1}}
        run = self.runs([call, output, end])["runs"][0]
        self.assertEqual((run["outputRecords"], run["exitCode"]), (2, None))

    def test_over_ceiling_runs_unreadable(self):
        # Mutation: scanning past the 8 MiB whole-rollout ceiling.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "big.jsonl"
            path.write_text(FIXTURE.read_text(encoding="utf-8") + "x" * (8 * 1024 * 1024 + 16), encoding="utf-8")
            result = self.runs_path(path)
        self.assertEqual((result["readable"], result["runs"]), (False, []))


@unittest.skipIf(NODE is None, "node not available")
class NativeOwnerCarrierFixtureTests(unittest.TestCase):
    """Pins the native carrier shapes the owner-signal scanner relies on (AC55, AC56, AC58)."""

    def records(self):
        return [json.loads(line) for line in OWNER_FIXTURE.read_text(encoding="utf-8").splitlines() if line]

    @staticmethod
    def _message(record, role):
        payload = record["payload"]
        return record["type"] == "response_item" and payload.get("type") == "message" and payload.get("role") == role

    @staticmethod
    def _texts(record):
        return [c.get("text", "") for c in record["payload"].get("content", []) if isinstance(c, dict)]

    @staticmethod
    def _kinds(record):
        return record["payload"].get("internal_chat_message_metadata_passthrough", {}).get("content_item_kinds", [])

    def test_owner_fixture_pins_injected_hook_and_compaction_shapes(self):
        records = self.records()

        def count(predicate):
            return sum(1 for record in records if predicate(record))

        self.assertEqual(count(lambda r: self._message(r, "user")
                               and any(t.startswith("<environment_context>") for t in self._texts(r))), 1)
        self.assertEqual(count(lambda r: self._message(r, "developer")
                               and "hooks.additional_context" in self._kinds(r)), 1)
        self.assertEqual(count(lambda r: r["type"] == "compacted"
                               and isinstance(r["payload"].get("replacement_history"), list)), 1)
        self.assertEqual(count(lambda r: self._message(r, "user")
                               and any(t.startswith("<hook_prompt") for t in self._texts(r))), 1)

    def test_owner_fixture_pins_installed_cache_read_shape(self):
        records = self.records()
        calls = [r for r in records if r["payload"].get("type") == "function_call"
                 and r["payload"].get("name") == "exec_command"]
        self.assertEqual(len(calls), 1)
        verb, path = json.loads(calls[0]["payload"]["arguments"])["cmd"].split(" ", 1)
        self.assertEqual(verb, "cat")
        self.assertRegex(path, INSTALLED_SKILL_READ)
        outputs = [r for r in records if r["payload"].get("type") == "function_call_output"
                   and r["payload"].get("call_id") == calls[0]["payload"]["call_id"]]
        self.assertEqual(len(outputs), 1)
        script = ("import {parseCodexExitCode} from " + json.dumps((REPO / "hooks/codex-rollout.mjs").as_uri())
                  + "; let b = ''; process.stdin.setEncoding('utf8');"
                  " process.stdin.on('data', (d) => { b += d; }).on('end', () =>"
                  " process.stdout.write(JSON.stringify(parseCodexExitCode(b))));")
        result = subprocess.run([NODE, "--input-type=module", "-e", script],
                                input=outputs[0]["payload"]["output"].encode("utf-8"),
                                capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout.decode("utf-8")), 0)

    # ---- AC55, AC56: synthetic mutations of the native carriers (Task 22) ----
    CWD = "/tmp/codex-lifecycle-workspace"
    TOKEN = "superpowers:brainstorming"

    def owner_phase(self, records):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout.jsonl"
            path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
            script = ("import {readOwnerSignals} from " + json.dumps((REPO / "hooks/codex-rollout.mjs").as_uri())
                      + "; process.stdout.write(JSON.stringify(readOwnerSignals(process.argv[1], process.argv[2])));")
            result = subprocess.run([NODE, "--input-type=module", "-e", script, str(path), self.CWD],
                                    capture_output=True, text=True, encoding="utf-8", check=True)
            return json.loads(result.stdout)["phase"]

    def named(self):
        env, dev, user, compacted, hook, call, output = self.records()
        # Point the native cache read at a Superpowers skill so a real choice WOULD be delivered.
        call["payload"]["arguments"] = call["payload"]["arguments"].replace(
            "/agentic-sdlc/0.4.2/skills/completion-claim-gate/", "/superpowers/6.3.0/skills/brainstorming/")
        return {"env": env, "dev": dev, "user": user, "compacted": compacted, "hook": hook, "call": call, "output": output}

    def test_injected_native_carriers_never_create_an_owner(self):
        # Mutation: scanning tag-wrapped user items, developer messages or replacement_history.
        n = self.named()

        def inside_tag(record):
            item = record["payload"]["content"][0]
            cut = item["text"].index(">") + 1
            item["text"] = item["text"][:cut] + self.TOKEN + " " + item["text"][cut:]

        inside_tag(n["env"])
        inside_tag(n["hook"])
        n["dev"]["payload"]["content"][0]["text"] += "\nUse " + self.TOKEN
        n["compacted"]["payload"]["replacement_history"].insert(0, {
            "type": "message", "role": "user", "content": [{"type": "input_text", "text": "Use " + self.TOKEN}]})
        order = ("env", "dev", "user", "compacted", "hook", "call", "output")
        self.assertEqual(self.owner_phase([n[k] for k in order]), "house")
        control = self.named()
        control["user"]["payload"]["content"][0]["text"] = "Use " + self.TOKEN
        self.assertEqual(self.owner_phase([control[k] for k in order]), "superpowers")

    def test_native_choice_then_compaction_without_redelivery_is_ambiguous(self):
        # Mutation: letting a delivery recorded before the compaction boundary survive it.
        n = self.named()
        n["user"]["payload"]["content"][0]["text"] = "Use " + self.TOKEN
        self.assertEqual(self.owner_phase([n["user"], n["call"], n["output"]]), "superpowers")
        self.assertEqual(self.owner_phase([n["user"], n["call"], n["output"], n["compacted"]]), "ambiguous")


if __name__ == "__main__":
    unittest.main()
