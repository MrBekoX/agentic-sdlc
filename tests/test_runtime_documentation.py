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


class TestClaudeCurrencyClaims(unittest.TestCase):
    """AC25: current Claude claims match the 2026-10-07 documentation snapshot."""

    def _text(self, *parts):
        return (REPO.joinpath(*parts)).read_text(encoding="utf-8")

    def test_ac25_directory_submission_matches_publish_docs(self):
        for rel in ("README.md", "docs/release-readiness.md", ".claude-plugin/README.md",
                    "docs/publication/claude-community.md"):
            text = self._text(rel)
            with self.subTest(rel=rel):
                self.assertNotIn("Team or Enterprise plan with directory management", text)
                self.assertIn("claude.ai/directory/manage", text)
                self.assertIn("paid claude.ai plan", text)
                self.assertIn("plugins/publish", text)

    def test_ac25_validate_directory_form_is_not_described_as_skipping_the_plugin(self):
        for rel in ("README.md", "docs/release-readiness.md"):
            text = self._text(rel)
            with self.subTest(rel=rel):
                self.assertNotIn("marketplace validation checks no plugin contents", text)
                self.assertIn("2.1.289", text)

    def test_ac25_task_tracker_and_loop_match_current_tools(self):
        adapter = self._text("docs/runtime-adapter.md")
        self.assertNotIn("| Task tracking | `TodoWrite` |", adapter)
        self.assertIn("TaskCreate", adapter)
        self.assertIn("CLAUDE_CODE_ENABLE_TASKS=0", adapter)
        self.assertNotIn("| Loop fail-fix-retest | `/loop` |", adapter)
        self.assertIn("scheduled", adapter.lower())
        skill = self._text("skills/agentic-sdlc-pipeline/SKILL.md")
        self.assertNotIn("`TodoWrite`, `update_plan`", skill)
        self.assertIn("TaskCreate", skill)

    def test_ac25_workflow_availability_is_conditional(self):
        runtime = self._text("docs/claude-code-runtime.md")
        self.assertIn("paid plans", runtime)
        self.assertIn("Pro", runtime)

    def test_ac25_multiedit_is_marked_legacy(self):
        hooks = self._text("hooks/README.md")
        self.assertIn("legacy", hooks.lower())
        self.assertIn("MultiEdit", hooks)

    def test_ac25_pretooluse_additional_context_reaches_the_model(self):
        text = self._text("docs/data-handling.md")
        self.assertNotIn("debug-log output only", text)
        self.assertIn("last_assistant_message", text)
        self.assertIn("background_tasks", text)
        self.assertIn(".claude/commands/", text)

    def test_ac25_commit_scan_is_not_limited_to_a_git_commit_prefix(self):
        text = self._text("docs/troubleshooting.md")
        self.assertNotIn("only runs for `git commit*`", text)

    def test_ac25_stop_list_includes_the_working_tree_scan(self):
        text = self._text("docs/claude-code-runtime.md")
        self.assertIn("worktree-scan", text)

    def test_ac25_frontmatter_is_not_described_as_tolerating_extra_keys(self):
        text = self._text("docs/claude-code-runtime.md")
        self.assertNotIn("may tolerate", text)

    def test_ac25_trigger_eval_shim_and_bare_match_the_runner(self):
        text = self._text("docs/testing.md")
        self.assertNotIn("temporary `commands/<skill>", text)
        self.assertNotIn("--smoke --bare", text)
        self.assertIn(".claude/commands/", text)
        self.assertIn("exit 2", text)
        self.assertIn("disabled:plugin-dir", text)

    def test_ac25_review_result_names_launch_receipts(self):
        text = self._text("hooks/README.md")
        self.assertIn("async_launched", text)
        self.assertNotIn("live-tested on 2.1.293", self._text("README.md"))
        self.assertNotIn("live-tested on 2.1.293", self._text("docs/runtime-adapter.md"))


if __name__ == "__main__":
    unittest.main()
