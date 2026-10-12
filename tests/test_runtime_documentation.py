"""Regression checks for material runtime coverage claims, not live proof."""
from pathlib import Path
import re
import unittest


REPO = Path(__file__).resolve().parents[1]


class CompatibilityMatrixTests(unittest.TestCase):
    """docs/publication/compatibility-matrix.md: a cell says `passed` only with recorded evidence.

    The goal rule is that an untested platform or OS is never reported as passing. Each platform x
    OS cell must be `passed (<evidence id>, <YYYY-MM-DD>, <CLI version>)` or `not-run: <reason>`;
    every evidence id must exist in the evidence log with the same platform, OS, date and version;
    and the log must not leak a host name, user name or temporary path.
    """

    PLATFORMS = ("Claude Code", "Codex", "Kimi Code", "Grok CLI", "ZCode")
    OSES = ("Windows", "Linux", "macOS")
    CELL = re.compile(r"^(?:passed \((E\d+), (\d{4}-\d{2}-\d{2}), ([^)]+)\)|not-run: \S.*)$")

    def setUp(self):
        self.text = (REPO / "docs" / "publication" / "compatibility-matrix.md").read_text(encoding="utf-8")

    def _table(self, heading):
        section = self.text.split("## " + heading, 1)[1].split("\n## ", 1)[0]
        rows = [ln for ln in section.splitlines() if ln.startswith("|")]
        header = [c.strip() for c in rows[0].strip("|").split("|")]
        return header, [[c.strip() for c in r.strip("|").split("|")] for r in rows[2:]]

    def test_every_cell_is_evidenced_passed_or_not_run(self):
        header, rows = self._table("Verification by platform and operating system")
        self.assertEqual(header, ["Platform", *self.OSES])
        self.assertEqual([r[0] for r in rows], list(self.PLATFORMS))
        _log_header, log_rows = self._table("Evidence log")
        log = {r[0]: r for r in log_rows}
        for row in rows:
            for os_name, cell in zip(self.OSES, row[1:]):
                with self.subTest(platform=row[0], os=os_name):
                    match = self.CELL.match(cell)
                    self.assertIsNotNone(match, cell)
                    if match.group(1):
                        entry = log.get(match.group(1))
                        self.assertIsNotNone(entry, "passed cell cites an evidence id not in the log")
                        self.assertEqual((entry[2], entry[3], entry[1], entry[4]),
                                         (row[0], os_name, match.group(2), match.group(3)))
                        self.assertIn("native_", entry[5])
                        self.assertIn("=passed", entry[6])

    def test_an_os_without_a_recorded_run_is_never_passed(self):
        _h, log_rows = self._table("Evidence log")
        logged_oses = {r[3] for r in log_rows}
        _h, rows = self._table("Verification by platform and operating system")
        for os_index, os_name in enumerate(self.OSES, start=1):
            if os_name not in logged_oses:
                for row in rows:
                    self.assertTrue(row[os_index].startswith("not-run: "), (row[0], os_name))

    def test_evidence_log_masks_hosts_users_and_temporary_paths(self):
        log = self.text.split("## Evidence log", 1)[1]
        for leak in (r"[A-Za-z]:\\", r"/home/", r"/Users/", r"/tmp/", r"AppData", r"\\\\"):
            self.assertNotRegex(log, leak)

    def test_every_platform_row_names_install_update_uninstall_and_limits(self):
        header, rows = self._table("Platforms")
        for column in ("Native mechanism", "Install", "Update", "Uninstall", "Consent / trust", "Limits"):
            self.assertIn(column, header)
        self.assertEqual([r[0] for r in rows], list(self.PLATFORMS))
        for row in rows:
            self.assertTrue(all(cell for cell in row), row[0])


class RuntimeDocumentationTests(unittest.TestCase):
    def test_git_safety_check_runs_on_powershell_only_hosts_and_never_prints_values(self):
        # The manual command used `git diff --cached | grep -nEi ...`: Windows hosts with only
        # PowerShell (the Codex and Claude fallback shell) have no grep, `grep` was not an allowed
        # tool, and the pipeline printed matched secret values before the masking instruction.
        import json
        text =(REPO / "commands" / "git-safety-check.md").read_text(encoding="utf-8")
        front = text.split("---", 2)[1]
        allowed = json.loads(re.search(r"allowed-tools:\s*(\[.*\])", front).group(1))
        self.assertNotRegex(text, r"\|\s*(grep|findstr|Select-String)\b")
        for block in re.findall(r"```(?:bash|powershell)?\n(.*?)```", text, re.DOTALL):
            for command in filter(None, (ln.strip() for ln in block.splitlines())):
                with self.subTest(command=command):
                    self.assertRegex(command, r"^git [a-z]")
                    if command.split()[1] == "diff" and "--name-only" not in command.split()[2:4]:
                        # A repository diff driver or textconv program must not run, or rewrite
                        # the bytes being reviewed.
                        self.assertIn("--no-ext-diff", command)
                        self.assertIn("--no-textconv", command)
                    if " -G " in command:
                        # The marker search is not pre-approved: its regex cannot be written as a
                        # reliable exact rule, so the user approves it when asked.
                        self.assertIn("--no-textconv", command)
                        continue
                    self.assertIn(f"Bash({command})", allowed)
                    self.assertIn(f"PowerShell({command})", allowed)
        # Exact rules only: a prefix rule such as `Bash(git diff:*)` also pre-approves
        # `git diff --output=<file>`, which overwrites any file. A pre-approved `git grep` runs any
        # command through `-O<pager>` (`--no-cached` undoes `--cached`), and splicing staged names
        # into a command line lets a name like `a$(…)` run, so names are read with the Read/Grep tools.
        shell_rules = [rule for rule in allowed if rule.startswith(("Bash(", "PowerShell("))]
        self.assertFalse([rule for rule in shell_rules if rule.endswith((":*)", " *)", "*)"))], allowed)
        self.assertFalse([rule for rule in allowed if "git grep" in rule], allowed)
        self.assertNotIn("<staged files>", text)
        self.assertIn("***MASKED***", text)
        self.assertIn("do not print the real value", text)
        self.assertNotIn("agentic-sdlc:allow-secret", text, "no secret-shaped literal should need a marker")

    def test_distribution_lifecycle_uses_supported_commands(self):
        text = (REPO / "docs/publication/multi-platform-distribution.md").read_text(encoding="utf-8")
        self.assertNotIn("`/plugin update ", text)
        for command in ("claude plugin update agentic-sdlc@mrbekox",
                        "claude plugin uninstall agentic-sdlc@mrbekox",
                        "codex plugin remove agentic-sdlc@",
                        "/plugins remove agentic-sdlc",
                        "grok plugin uninstall agentic-sdlc"):
            with self.subTest(command=command):
                self.assertIn(command, text)
        self.assertIn("Uninstall", text)
        self.assertIn("managed copy", text)

    def test_adapter_docs_do_not_prescribe_machine_paths(self):
        for rel in ("README.md", ".grok-plugin/README.md", "hooks/README.md", "docs/runtime-adapter.md"):
            text = (REPO / rel).read_text(encoding="utf-8")
            with self.subTest(file=rel):
                self.assertNotIn("D:/agentic-sdlc", text)
                self.assertNotIn("node.exe D:", text)

    def test_all_five_platforms_have_install_and_update_guidance(self):
        text = (REPO / "docs/publication/multi-platform-distribution.md").read_text(encoding="utf-8")
        install_text = text.split("| Platform | Uninstall |", 1)[0]
        for runtime in ("Claude Code", "Codex", "Kimi Code", "ZCode", "Grok CLI"):
            rows = [line for line in install_text.splitlines() if line.startswith("| " + runtime + " |")]
            self.assertEqual(len(rows), 1, runtime)
            self.assertGreaterEqual(len(rows[0].split('|')), 6)
        self.assertIn("not native trust", text)

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


class TestRuntimeDocumentation(unittest.TestCase):
    def test_grok_update_instructions_match_native_copy_semantics(self):
        for rel in ('docs/publication/grok-marketplace.md', '.grok-plugin/README.md'):
            text = (REPO / rel).read_text(encoding='utf-8')
            with self.subTest(path=rel):
                self.assertNotIn('Reinstall a refreshed local directory', text)
                self.assertIn('local `plugin update` does not recopy', text)
                self.assertIn('already installed', text)
                self.assertIn('moving Git branch', text)


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
