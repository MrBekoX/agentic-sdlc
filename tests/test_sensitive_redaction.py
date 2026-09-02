import unittest

from scripts.sensitive_redaction import redact_text


class TestSensitiveRedaction(unittest.TestCase):
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
