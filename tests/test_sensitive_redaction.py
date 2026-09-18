import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.sensitive_redaction import redact_text

REPO = Path(__file__).resolve().parents[1]


class TestSensitiveRedaction(unittest.TestCase):
    def test_json_redaction_preserves_structure_and_credential_key_context(self):
        from scripts.sensitive_redaction import redact_json
        value = "FixtureOnly" + "A1b2C3d4E5f6"
        data = {"result": {"access_token": value, "items": [{"name": "safe", "key": value}]}}
        out = redact_json(data)
        self.assertNotIn(value, json.dumps(out))
        self.assertEqual(out["result"]["items"][0]["name"], "safe")
        self.assertIn("access_token", out["result"])
        self.assertEqual(json.loads(json.dumps(out)), out)
        self.assertEqual(data["result"]["access_token"], value)

    def test_json_redaction_masks_embedded_vendor_token_and_private_key(self):
        from scripts.sensitive_redaction import redact_json
        value = "ghp_" + "A1b2" * 9
        pem = "-----BEGIN PRIVATE KEY-----\nsynthetic-fixture\n-----END PRIVATE KEY-----"  # agentic-sdlc:allow-secret
        data = {"command": "echo " + value, "messages": ["safe", value, pem]}
        out = redact_json(data)
        self.assertNotIn(value, json.dumps(out))
        self.assertEqual(out["messages"][0], "safe")
        self.assertTrue(out["command"].startswith("echo "))
        self.assertNotIn("synthetic-fixture", out["messages"][2])

    def test_json_field_context_is_not_lost_after_a_vendor_match(self):
        from scripts.sensitive_redaction import redact_json
        opaque = "FixtureCredentialA1B2C3D4"
        vendor = "ghp_" + "A1b2" * 9
        out = redact_json({"access_token": opaque + " " + vendor, vendor: "safe"})
        self.assertNotIn(opaque, json.dumps(out))
        self.assertNotIn(vendor, json.dumps(out))

    def test_masks_secret_without_echoing_value(self):
        secret = "ghp_" + "A1b2" * 9
        out = redact_text("before " + secret + " after\n")
        self.assertNotIn(secret, out)
        self.assertIn("***MASKED:github-token***", out)
        self.assertIn("before ", out)

    def test_masks_secret_even_with_source_scanner_allow_marker(self):
        secret = "ghp_" + "A1b2" * 9
        for marker in ("agentic-sdlc:allow-secret", "gitleaks:allow"):
            with self.subTest(marker=marker):
                out = redact_text(secret + " # " + marker + "\n")
                self.assertNotIn(secret, out)
                self.assertIn("***MASKED:github-token***", out)

    def test_masks_entire_private_key_block(self):
        body = "QWxhZGRpbjpvcGVuIHNlc2FtZQ=="
        pem = (
            "-----BEGIN RSA PRIVATE KEY-----\n"  # agentic-sdlc:allow-secret synthetic fixture
            + body
            + "\n-----END RSA PRIVATE KEY-----\n"
        )
        out = redact_text(pem)
        self.assertEqual(out, "***MASKED:private-key***\n")
        self.assertNotIn(body, out)
        self.assertNotIn("END RSA PRIVATE KEY", out)

    def test_masks_unterminated_private_key_through_eof(self):
        body = "QWxhZGRpbjpvcGVuIHNlc2FtZQ=="
        out = redact_text("-----BEGIN PRIVATE KEY-----\n" + body)  # agentic-sdlc:allow-secret
        self.assertEqual(out, "***MASKED:private-key***")

    def test_quote_inside_credential_value_is_masked(self):
        # SEC-14. Mutation: the structured member test re-serializing a value whose `"` ends the value class early.
        from scripts.sensitive_redaction import redact_json
        tail = "Wd4" + "Qx8Ls2Np6Rt9Vb3Kz"
        self.assertEqual(len(tail), 20)
        out = redact_json({"pass" + "word": "ab" + '"' + tail})
        dumped = json.dumps(out)
        self.assertFalse(tail in dumped, "the value after the quote survived redaction")
        self.assertFalse("ab" + '\\"' in dumped, "the value before the quote survived redaction")

    # D25 model (5): node is started only from an absolute PATH entry (SEC-7 class).
    def _in_dir_with_path(self, cwd, path):
        """Run the rest of the test with the process cwd and PATH replaced; both are restored afterwards."""
        from unittest import mock
        previous = os.getcwd()
        os.chdir(cwd)
        self.addCleanup(os.chdir, previous)
        patcher = mock.patch.dict(os.environ, {"PATH": path})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _redact_or_none(self, text):
        try:
            return redact_text(text)
        except RuntimeError:
            return None  # a planted program ran and failed

    def test_node_behind_relative_path_entry_is_not_run(self):
        # Mutation: shutil.which("node"), which walks the relative `.` entry first.
        root = Path(tempfile.mkdtemp(prefix="redact-node-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        sentinel = root.parent / (root.name + "-sentinel")
        self.addCleanup(lambda: sentinel.exists() and sentinel.unlink())
        if sys.platform == "win32":
            whoami = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "whoami.exe"
            if not whoami.is_file():
                self.skipTest("whoami.exe is not available to stand in for a planted node.exe")
            shutil.copyfile(whoami, root / "node.exe")
        else:
            fake = root / "node"
            fake.write_text(f"#!/bin/sh\ntouch '{sentinel}'\nexit 1\n", encoding="utf-8")
            fake.chmod(0o755)
        self._in_dir_with_path(root, "." + os.pathsep + os.environ.get("PATH", ""))
        self.assertEqual(self._redact_or_none("x"), "x")
        self.assertFalse(sentinel.exists(), "the planted node ran")

    @unittest.skipUnless(sys.platform == "win32", "PATHEXT batch candidates exist only on win32")
    def test_batch_file_is_not_a_candidate(self):
        # Mutation: a PATHEXT-driven lookup that accepts node.cmd from the first absolute entry.
        root = Path(tempfile.mkdtemp(prefix="redact-cmd-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        sentinel = root / "sentinel"
        (bin_dir / "node.cmd").write_bytes(f'@echo off\r\ntype nul > "{sentinel}"\r\n'.encode("utf-8"))
        self._in_dir_with_path(root, str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
        self.assertEqual(self._redact_or_none("x"), "x")
        self.assertFalse(sentinel.exists(), "the batch file ran")


# D22 (Task 129): every unsuppressed match is masked, including a value glued to or joined with a suppressed one.
# Tokens are assembled at runtime; presence checks use assertTrue/assertFalse so a failure never echoes a value.
GH_CLEAN = "ghp_" + "A1b2" * 9
GH_PLACEHOLDER = "ghp_" + "x" * 36
AWS_SAMPLE = "AK" + "IA" + "IOSFODNN7EXAMPLE"
AWS_KEY = "".join(["AK", "IA", "ZQ4T7MXB", "2KWL9RPD"])
PASSWORD = "pass" + "word="
CHANGE_ME = "change" + "me"
REAL_PASSWORD = "Hunter2" + "Real99"
GITHUB_MASK = "***MASKED:github-token***"
AWS_MASK = "***MASKED:aws-access-key-id***"
PASSWORD_MASK = "***MASKED:password-literal***"


class TestPerMatchRedaction(unittest.TestCase):
    def test_real_token_glued_to_suppressed_sample_is_masked(self):
        # Mutation: a global replace whose lookbehind rejects a token glued after another token.
        cases = (
            ("github-placeholder+github", GH_PLACEHOLDER, GH_CLEAN, GITHUB_MASK),
            ("aws-sample+aws", AWS_SAMPLE, AWS_KEY, AWS_MASK),
            ("aws-sample+github", AWS_SAMPLE, GH_CLEAN, GITHUB_MASK),
            ("github-placeholder+aws", GH_PLACEHOLDER, AWS_KEY, AWS_MASK),
        )
        for label, sample, real, mask in cases:
            with self.subTest(case=label):
                out = redact_text("value " + sample + real + "\n")
                self.assertFalse(real in out, "the real value survived redaction")
                self.assertTrue(sample in out, "the suppressed sample was not preserved")
                self.assertTrue(mask in out, "the named mask is missing")

    def test_real_password_joined_to_placeholder_assignment_is_masked(self):
        # Mutation: one greedy value per assignment, so the real assignment hides inside the change-me value.
        cases = (
            ("comma", PASSWORD + CHANGE_ME + "," + PASSWORD + REAL_PASSWORD, PASSWORD + CHANGE_ME),
            ("query-string", "?" + PASSWORD + "change-" + "me" + "&" + "pw" + "d=" + REAL_PASSWORD,
             PASSWORD + "change-" + "me"),
        )
        for label, line, preserved in cases:
            with self.subTest(case=label):
                out = redact_text(line + "\n")
                self.assertFalse(REAL_PASSWORD in out, "the real password survived redaction")
                self.assertTrue(preserved in out, "the change-me assignment was not preserved")
                self.assertTrue(PASSWORD_MASK in out, "the named mask is missing")

    def test_real_token_glued_after_real_token_of_later_pattern_is_masked(self):
        # Mutation: running the earlier-index AWS pass without the boundary after the GitHub token.
        out = redact_text("key " + GH_CLEAN + AWS_KEY + "\n")
        self.assertFalse(GH_CLEAN in out, "the GitHub token survived redaction")
        self.assertFalse(AWS_KEY in out, "the AWS key survived redaction")

    def test_redact_json_masks_glued_token_in_value(self):
        from scripts.sensitive_redaction import redact_json
        out = redact_json({"command": "echo " + GH_PLACEHOLDER + GH_CLEAN})
        self.assertFalse(GH_CLEAN in json.dumps(out), "the glued token survived JSON redaction")
        self.assertTrue(out["command"].startswith("echo "))

    def test_real_values_separated_from_suppressed_samples_are_masked(self):
        # Regression lock: the separated forms the old global replace already masked stay masked.
        cases = (
            ("github", GH_PLACEHOLDER + " " + GH_CLEAN, GH_CLEAN),
            ("aws", AWS_SAMPLE + " " + AWS_KEY, AWS_KEY),
            ("password-semicolon", PASSWORD + CHANGE_ME + "; " + PASSWORD + REAL_PASSWORD, REAL_PASSWORD),
        )
        for label, line, real in cases:
            with self.subTest(case=label):
                self.assertFalse(real in redact_text(line + "\n"), "the real value survived redaction")

    def test_suppressed_samples_are_preserved_byte_for_byte(self):
        # CONTROL: suppressed matches are copied unchanged.
        line = GH_PLACEHOLDER + " " + AWS_SAMPLE + " " + PASSWORD + CHANGE_ME + "\n"
        self.assertTrue(redact_text(line) == line, "a suppressed sample line was changed")

    def test_overlapping_json_credential_hit_extends_the_mask(self):
        # SEC-11. Mutation: skipping a hit that starts inside the span this pass masked, although it ends past it.
        node = shutil.which("node")
        if not node:
            self.skipTest("node is required for the hook-layer scanner")
        key = "my_" + "pass" + "word_text_long_value"
        value = "Zq9" + "Lm4Rt8Vx2Kp6Hn3Bw5Jc7"
        self.assertEqual((len(key), len(value)), (27, 24))
        line = '"to' + 'ken": "' + key + '": "' + value + '"'
        script = ("import('./hooks/secret-patterns.mjs').then(m=>{let s='';process.stdin.on('data',d=>s+=d)"
                  ".on('end',()=>process.stdout.write(String(m.scanLines(s,m.HIGH).length)))})")
        proc = subprocess.run([node, "-e", script], input=line, capture_output=True, text=True,
                              encoding="utf-8", cwd=str(REPO))
        self.assertEqual(proc.returncode, 0, "the scanner probe failed")
        self.assertTrue(proc.stdout == "1", "scanLines did not report exactly one hit")
        self.assertFalse(value in redact_text(line + "\n"), "the overlapping credential value survived redaction")

    def test_redaction_stays_linear_on_long_suppressed_chains(self):
        import time
        glued = GH_PLACEHOLDER * 16000 + "\n"
        chained = (PASSWORD + CHANGE_ME + ",") * 16000 + "\n"
        started = time.time()
        self.assertTrue(redact_text(glued) == glued, "glued placeholders were changed")
        self.assertTrue(redact_text(chained) == chained, "the change-me chain was changed")
        self.assertLess(time.time() - started, 10.0, "per-match redaction is not linear")


if __name__ == "__main__":
    unittest.main()
