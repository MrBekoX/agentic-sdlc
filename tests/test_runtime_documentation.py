"""Regression checks for material runtime coverage claims, not live proof."""
from pathlib import Path
import unittest


REPO = Path(__file__).resolve().parents[1]


class RuntimeDocumentationTests(unittest.TestCase):
    def test_portable_metadata_is_not_claimed_as_hook_delivery_on_current_binary(self):
        text = (REPO / "docs/runtime-adapter.md").read_text(encoding="utf-8")
        for fact in ("0.154.0", "portable", "legacy", "zero hooks", "eight hooks",
                     "does not prove hook execution"):
            self.assertTrue(fact in text, f"Missing runtime loader evidence: {fact}")

    def test_codex_test_evidence_distinguishes_stop_from_ordering(self):
        text = (REPO / "docs/runtime-adapter.md").read_text(encoding="utf-8").lower()
        for fact in ("exit code 0", "nonzero", "missing exit", "red run",
                     "latest source edit", "pytest --version"):
            with self.subTest(fact=fact):
                self.assertIn(fact, text)
        self.assertNotIn("exit code not inspected", text)
        self.assertNotIn("exit code never inspected", text)

    def test_current_runner_support_is_not_listed_as_a_gap(self):
        text = (REPO / "docs/runtime-adapter.md").read_text(encoding="utf-8")
        self.assertNotIn("shell scripts are unrecognized — DP-M", text)
        for command in ("make test", "npm test", "pnpm", "tox", "nox"):
            self.assertIn(command, text)
        self.assertIn("arbitrary shell scripts", text)

    def test_coexistence_records_runtime_specific_resume_bootstrap(self):
        text = (REPO / "docs/runtime-adapter.md").read_text(encoding="utf-8")
        for fact in ("b36e0829c6d0140e93cfef2ca599b1b07d4a7797",
                     '"hooks": {}', "resume", "startup|clear|compact"):
            self.assertIn(fact, text)
        self.assertIn("does not select a process owner", text)

    def test_worktree_scan_is_unwired_without_invented_loop_incompatibility(self):
        text = (REPO / "hooks/README.md").read_text(encoding="utf-8")
        self.assertNotIn("produce a prompt loop", text)
        self.assertIn("stop_hook_active", text)
        self.assertIn("VERIFY", text)

    def test_live_testing_separates_model_routing_and_trust_proof(self):
        text = (REPO / "docs/testing.md").read_text(encoding="utf-8")
        for fact in ("modelUsage", "trust bypass", "skill invocation/read",
                     "resume/compact", "held-out"):
            self.assertIn(fact, text)
        self.assertNotIn("declares no icon paths", text)
        self.assertNotIn("Harmless noise; ignore for trigger-eval results", text)


if __name__ == "__main__":
    unittest.main()
