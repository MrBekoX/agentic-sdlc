"""Native Codex 0.154.0 WSL success/denial records captured 2026-09-12.

Fixture bytes are the six original redacted records selected in
tests/artifacts/dual-runtime-remediation/codex-lifecycle-wsl/run-02/
parser-regression.provenance.json; test mutations are synthetic, not native runs.
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
FIXTURE = REPO / "tests/fixtures/transcripts/codex-0.154.0-native-tool-carriers.jsonl"


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


if __name__ == "__main__":
    unittest.main()
