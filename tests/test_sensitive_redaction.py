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


if __name__ == "__main__":
    unittest.main()
