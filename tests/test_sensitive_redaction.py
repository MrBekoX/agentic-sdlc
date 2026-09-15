import unittest
import json

from scripts.sensitive_redaction import redact_text


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
