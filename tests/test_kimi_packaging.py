"""Kimi Code adapter packaging contract: manifest, local marketplace, inline hook wiring.

Kimi Code is an experimental adapter target, not a supported 0.4.3 release target
(docs/runtime-adapter.md). These tests lock the adapter files to the Kimi Code plugin/hook
schema fetched 2026-10-08 from the official docs
(kimi.com/code/docs/en/kimi-code-cli/customization/plugins.html and hooks.html), plus the
local precedent at ~/.kimi-code/plugins/managed/superpowers/.kimi-plugin/plugin.json,
without loosening the Claude Code / Codex packaging contracts in test_packaging_metadata.py.

Version binding note: scripts/bump_version.py MANIFESTS tracks .kimi-plugin/plugin.json.
marketplace-kimi.json intentionally carries no plugin version (its "2" is the marketplace
SCHEMA version), so bump tracking stays on the manifest and this suite pins that shape.
"""
import json
import os
import subprocess
import shutil
import re
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
KIMI_MANIFEST = REPO / ".kimi-plugin" / "plugin.json"
KIMI_MARKETPLACE = REPO / "marketplace-kimi.json"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
# Hook events listed in the fetched Kimi Code hooks reference (2026-10-08).
KIMI_HOOK_EVENTS = {
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PermissionRequest",
    "PermissionResult",
    "Stop",
    "StopFailure",
    "UserPromptSubmit",
    "UserPromptQueued",
    "SessionStart",
    "SessionEnd",
    "SessionHeartbeat",
    "Notification",
    "TurnStarted",
    "SubagentStart",
    "SubagentStop",
    "TaskStarted",
    "Interrupt",
    "PreCompact",
    "PostCompact",
}
WIRED_SCRIPTS = {
    "scan-commit.mjs",
    "destructive-command-guard.mjs",
    "branch-guard.mjs",
}
# Script basenames that must never appear in the wired command: Claude-transcript
# and Codex-rollout readers, the write scanner (PostToolUse Write/Edit payload fields
# are not documented for Kimi), and the session-start hook (sessionStart.skill in the
# manifest replaces it).
UNVERIFIED_SCRIPT_TOKENS = (
    "scan-write",
    "session-start",
    "completion-claim",
    "flow-order",
    "flow-step",
    "worktree-scan",
    "codex",
)
CLAUDE_ONLY_DESCRIPTION = "Claude Code skill library"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def current_version():
    return (REPO / "VERSION").read_text(encoding="utf-8").strip()


def command_script_basename(command):
    # The wired command quotes its plugin-root-relative path (see the executor test for why),
    # so strip the closing quote before taking the basename — otherwise every name ends up
    # as `x.mjs"`.
    return str(command).replace("\\", "/").rsplit("/", 1)[-1].split()[0].strip('"')


class TestKimiManifest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(KIMI_MANIFEST.is_file(), ".kimi-plugin/plugin.json missing")
        self.manifest = read_json(KIMI_MANIFEST)

    def test_manifest_identity_matches_version(self):
        self.assertRegex(self.manifest["name"], NAME_RE)
        self.assertEqual(self.manifest["name"], "agentic-sdlc")
        self.assertEqual(self.manifest["version"], current_version())

    def test_description_is_not_the_claude_only_sentence(self):
        description = self.manifest["description"]
        self.assertTrue(description)
        self.assertNotIn(CLAUDE_ONLY_DESCRIPTION, description)

    def test_shared_components_are_declared_explicitly(self):
        # Kimi resolves skills/commands/agents from the manifest fields; if `skills` is
        # omitted only a root SKILL.md would be picked up, so the field is required here.
        self.assertEqual(self.manifest["skills"], "./skills/")
        self.assertEqual(self.manifest["commands"], "./commands/")
        self.assertEqual(self.manifest["agents"], "./agents/")

    def test_session_start_router_and_skill_instructions(self):
        self.assertEqual(self.manifest["sessionStart"]["skill"], "using-agentic-sdlc")
        self.assertTrue(
            (REPO / "skills" / "using-agentic-sdlc" / "SKILL.md").is_file(),
            "sessionStart.skill names a skill that does not exist",
        )
        instructions = self.manifest["skillInstructions"]
        self.assertIsInstance(instructions, str)
        self.assertTrue(instructions.strip(), "skillInstructions must not be empty")

    def test_skill_instructions_name_qualified_skills_and_the_runner_cards(self):
        # Kimi Code 2.3.0 names plugin skills agentic-sdlc:<skill>; plugin agents keep their bare role
        # name. A runner role card goes to a NEW Agent, never a resumed or forked one, and the
        # caller keeps an author's decision points (design §5.9.2, plan Task 14).
        instructions = self.manifest["skillInstructions"]
        for fact in ("Kimi Code 2.3.0", "agentic-sdlc:<skill>", "agentic-sdlc:using-agentic-sdlc",
                     'Agent(subagent_type="spec-plan-critic")', "NEW Agent", "never resume or fork",
                     "write path", "decisions path", "then= command"):
            with self.subTest(fact=fact):
                self.assertIn(fact, instructions)
        self.assertNotIn('subagent_type="agentic-sdlc:', instructions)

    def test_skills_name_kimi_plugin_skills_as_the_manifest_does(self):
        # Kimi's plugin docs: a plugin skill is listed and invoked as <plugin-id>:<skill-name>, and a
        # bare skill name never resolves to a plugin skill. The skill text a Kimi session reads must
        # not tell it the opposite of skillInstructions.
        for skill in sorted((REPO / "skills").glob("*/SKILL.md")):
            text = skill.read_text(encoding="utf-8")
            with self.subTest(skill=skill.parent.name):
                self.assertNotIn("resolves bare skill names", text)
                self.assertNotIn("invoke skills by bare name", text)
        router = (REPO / "skills" / "using-agentic-sdlc" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("/skill:agentic-sdlc:<name>", router)

    def test_interface_display_name_present(self):
        self.assertTrue(self.manifest["interface"]["displayName"])

    def test_no_mcp_surface(self):
        self.assertNotIn("mcpServers", self.manifest)

    def test_no_root_kimi_dot_plugin_manifest(self):
        # kimi.plugin.json at the plugin root would take precedence over
        # .kimi-plugin/plugin.json; shipping only the latter keeps one manifest.
        self.assertFalse((REPO / "kimi.plugin.json").exists())


class TestKimiMarketplace(unittest.TestCase):
    def setUp(self):
        self.assertTrue(KIMI_MARKETPLACE.is_file(), "marketplace-kimi.json missing")
        self.market = read_json(KIMI_MARKETPLACE)

    def test_schema_version_and_single_entry(self):
        self.assertEqual(self.market["version"], "2")
        self.assertEqual(len(self.market["plugins"]), 1)

    def test_entry_identity_and_public_source(self):
        entry = self.market["plugins"][0]
        self.assertEqual(entry["id"], "agentic-sdlc")
        self.assertEqual(entry["displayName"], "Agentic SDLC")
        # Product-grade source: a marketplace file is meant to be consumable by anyone,
        # including fetched from a URL, where a relative "./" would be meaningless. The
        # documented source forms are local path, zip URL, or GitHub URL; the GitHub repo
        # URL is the only one that resolves identically on every machine.
        self.assertEqual(entry["source"], "https://github.com/MrBekoX/agentic-sdlc")

    def test_entry_carries_no_plugin_version(self):
        # The "2" above is the marketplace SCHEMA version, not a plugin version. Bump
        # tracking for the plugin stays on .kimi-plugin/plugin.json via bump_version.py;
        # a version key here would be a second source that silently drifts.
        self.assertNotIn("version", self.market["plugins"][0])


class TestKimiHookWire(unittest.TestCase):
    def setUp(self):
        self.assertTrue(KIMI_MANIFEST.is_file(), ".kimi-plugin/plugin.json missing")
        self.hooks = read_json(KIMI_MANIFEST)["hooks"]

    def test_hooks_are_an_inline_list(self):
        # Kimi wires hooks INLINE in the manifest: a list of {event, matcher, command,
        # timeout} entries, not a path to a hooks-*.json file.
        self.assertIsInstance(self.hooks, list)
        self.assertTrue(self.hooks, "hooks list must not be empty")

    def test_only_verified_events_are_wired(self):
        events = {entry["event"] for entry in self.hooks}
        self.assertEqual(events, {"PreToolUse"})
        self.assertLessEqual(events, KIMI_HOOK_EVENTS)

    def test_matchers_are_bash_only(self):
        for entry in self.hooks:
            # Kimi evaluates matchers with an unanchored `new RegExp(pattern).test(toolName)`;
            # anchor so only the Bash tool (not any name containing "Bash") runs the guards.
            self.assertEqual(entry["matcher"], "^Bash$")

    def test_executors_are_quoted_relative_node_commands_with_second_timeouts(self):
        # Decision, made before pinning (see lessons.md 2026-09-20 anchored-assertion
        # entry): the command form is `node "./hooks/<script>.mjs"`. Kimi runs plugin
        # hooks with cwd = plugin root, so a RELATIVE path never contains the install
        # path and there is no ${} expansion to mis-expand; the quotes are harmless
        # insurance, not a spaced-install-path guard. Kimi documents hook failure as
        # fail-open (hooks reference: script error or timeout defaults to allow), so a
        # broken command would silently disarm all three guards — keep `node` on PATH.
        # timeout is in SECONDS, integer, documented range 1-600 (default 30).
        for entry in self.hooks:
            self.assertRegex(entry["command"], r'^node "\./hooks/[a-z-]+\.mjs"$')
            self.assertIsInstance(entry["timeout"], int)
            self.assertGreaterEqual(entry["timeout"], 1)
            self.assertLessEqual(entry["timeout"], 600)

    def test_wired_scripts_exist_and_are_the_verified_set(self):
        wired = {command_script_basename(entry["command"]) for entry in self.hooks}
        self.assertEqual(wired, WIRED_SCRIPTS)
        for name in wired:
            self.assertTrue((REPO / "hooks" / name).is_file(), name)

    def test_unverified_runtime_readers_stay_unwired(self):
        # Assert the property on the CONSTANT as well as the wire: widening WIRED_SCRIPTS
        # to admit a Claude-transcript or Codex-rollout reader fails here even if the
        # wire matches (same reasoning as test_zcode_packaging.py).
        self.assertTrue(WIRED_SCRIPTS, "the verified set must not be empty")
        for name in WIRED_SCRIPTS | {
            command_script_basename(entry["command"]) for entry in self.hooks
        }:
            for token in UNVERIFIED_SCRIPT_TOKENS:
                self.assertNotIn(token, name, f"{name} carries unverified-reader token {token}")


def runtime_adapter_section(heading_prefix):
    """The `## <heading_prefix>...` section of docs/runtime-adapter.md, up to the next `## `."""
    text = (REPO / "docs" / "runtime-adapter.md").read_text(encoding="utf-8")
    start = text.index("\n## " + heading_prefix)
    end = text.find("\n## ", start + 1)
    return text[start:end if end >= 0 else len(text)]


class TestKimiStopAndSessionStartStayUnwired(unittest.TestCase):
    """Kimi's Stop/SessionStart output contract differs from the shared handlers' output.

    Kimi hooks doc (fetched 2026-11-21): a Stop block is exit 2 with the reason on stderr, or
    stdout {"hookSpecificOutput":{"permissionDecision":"deny",...}}; SessionStart is
    observation-only and its exit-0 stdout "may be appended to context"; the payload has no
    transcript field and no stop_hook_active. worktree-scan.mjs prints Claude-style
    decision/systemMessage and exits 0, and session-start.mjs prints additionalContext JSON,
    so neither is a documented Kimi result. Routing is already done by sessionStart.skill.
    """

    def test_manifest_declares_no_stop_or_session_start_hook(self):
        events = {entry["event"] for entry in read_json(KIMI_MANIFEST)["hooks"]}
        self.assertNotIn("Stop", events)
        self.assertNotIn("SessionStart", events)
        self.assertEqual(read_json(KIMI_MANIFEST)["sessionStart"]["skill"], "using-agentic-sdlc")

    def test_docs_state_why_stop_and_session_start_stay_unwired(self):
        docs = {
            ".kimi-plugin/README.md": (REPO / ".kimi-plugin" / "README.md").read_text(encoding="utf-8"),
            "docs/runtime-adapter.md#Kimi": runtime_adapter_section("Kimi Code adapter"),
        }
        for name, text in docs.items():
            flat = " ".join(text.split())
            for marker in (
                "checked 2026-11-21",
                "exit 2",
                "hookSpecificOutput.permissionDecision",
                "observation-only",
                "no transcript field",
                "stop_hook_active",
                "`sessionStart.skill`",
                "A future Kimi mode",
                "payload `cwd`",
                "hookEventName",
                "GitHub-installed",
            ):
                self.assertIn(marker, flat, f"{name} missing {marker}")

    def test_readme_does_not_settle_the_hook_cwd_the_docs_leave_open(self):
        # K3: plugins.html says hook cwd is the plugin root, hooks.html says the session's
        # project directory; the docs do not reconcile the two.
        flat = " ".join((REPO / ".kimi-plugin" / "README.md").read_text(encoding="utf-8").split())
        self.assertNotIn("which for a Kimi plugin hook is the plugin root", flat)
        self.assertIn("the docs do not reconcile them", flat)


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                   cwd=str(cwd), check=True, capture_output=True)


def make_protected_repo(root, stage_secret=False):
    """A throwaway Git repository on `main` with one commit (and optionally a staged synthetic secret)."""
    repo = Path(root) / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    if stage_secret:
        (repo / "config.txt").write_text('token = "%s"\n' % ("ghp_" + "a1B2" * 9), encoding="utf-8")
        _git(repo, "add", "config.txt")
    return repo


def node_env(root, **extra):
    """The caller's environment without house-policy switches, with Node's temp folder isolated
    (TMPDIR, TEMP and TMP: Node reads TEMP/TMP on Windows)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTIC_")}
    for key in ("TMPDIR", "TEMP", "TMP"):
        env[key] = str(root)
    env.update(extra)
    return env


def kimi_2_7_2_hook_result(exit_code, stdout, stderr):
    """Mirror of `resultFromExitCode()` / `structuredOutput()` in
    packages/agent-core-v2/src/features/externalHooks/internal/runHook.ts as shipped inside the
    installed Kimi Code 2.7.2 binary (read 2026-11-22, compatibility matrix E30).

    Exit 2 blocks with stderr as the reason. On exit 0 the stdout is parsed with a zod
    `looseObject` ({message?, hookSpecificOutput?: looseObject({message?, permissionDecision?,
    permissionDecisionReason?})}): unknown keys such as `hookEventName` or a top-level
    `systemMessage` are kept and ignored, and only `permissionDecision == "deny"` blocks.
    Anything else (other exit codes, unparsable stdout) allows: hooks fail open.
    """
    if exit_code == 2:
        return {"action": "block", "reason": stderr.strip()}
    if exit_code != 0 or not stdout.strip():
        return {"action": "allow"}
    try:
        parsed = json.loads(stdout.strip())
    except ValueError:
        return {"action": "allow"}
    if not isinstance(parsed, dict):
        return {"action": "allow"}
    specific = parsed.get("hookSpecificOutput")
    specific = specific if isinstance(specific, dict) else {}
    message = parsed.get("message", specific.get("message"))
    if specific.get("permissionDecision") != "deny":
        return {"action": "allow", "message": message}
    reason = specific.get("permissionDecisionReason")
    return {"action": "block", "reason": reason if isinstance(reason, str) else None, "message": message}


class TestKimiGuardOutputUnderTheInstalledParser(unittest.TestCase):
    """K5: the wired guards' stdout, run as Kimi runs them (cwd = plugin root, snake_case payload),
    decides as Kimi Code 2.7.2's own hook parser decides. The same three blocks and the warn-mode
    allow were seen in live `kimi -p` turns (E31)."""

    def run_guard(self, script, command, block=False, stage_secret=False):
        with tempfile.TemporaryDirectory(prefix="kimi-guard-") as tmp:
            repo = make_protected_repo(tmp, stage_secret=stage_secret)
            payload = {"hook_event_name": "PreToolUse", "session_id": "s", "cwd": str(repo),
                       "tool_name": "Bash", "tool_input": {"command": command}, "tool_call_id": "c"}
            extra = {"KIMI_PLUGIN_ROOT": str(REPO)}
            if block:
                extra["AGENTIC_BRANCH_GUARD_BLOCK"] = "true"
            proc = subprocess.run(["node", "./hooks/" + script], cwd=str(REPO), input=json.dumps(payload),
                                  capture_output=True, text=True, encoding="utf-8", timeout=60,
                                  env=node_env(tmp, **extra))
        return proc, kimi_2_7_2_hook_result(proc.returncode, proc.stdout, proc.stderr)

    def setUp(self):
        if shutil.which("node") is None or shutil.which("git") is None:
            self.skipTest("node and git are required to replay the Kimi hooks")

    def assert_blocks(self, script, command, expected, **kw):
        proc, result = self.run_guard(script, command, **kw)
        self.assertEqual(result["action"], "block", proc.stdout + proc.stderr)
        self.assertIn(expected, result["reason"])
        # The extra key Kimi's documented example does not show is present and tolerated.
        self.assertEqual(json.loads(proc.stdout)["hookSpecificOutput"]["hookEventName"], "PreToolUse")

    def test_destructive_guard_blocks(self):
        self.assert_blocks("destructive-command-guard.mjs", "git reset --hard", "git-reset-hard")

    def test_branch_guard_blocks_in_block_mode(self):
        self.assert_blocks("branch-guard.mjs", "git commit --allow-empty -m x", "Protected branch 'main'", block=True)

    def test_secret_scan_blocks_a_staged_secret(self):
        self.assert_blocks("scan-commit.mjs", "git commit -m x", "possible secret", stage_secret=True)

    def test_branch_warning_allows_and_is_not_shown(self):
        proc, result = self.run_guard("branch-guard.mjs", "git commit --allow-empty -m x")
        self.assertEqual(result["action"], "allow", proc.stdout)
        # Kimi reads only `message`; the warn text sits in `systemMessage`, so Kimi shows nothing.
        self.assertIsNone(result.get("message"))
        self.assertIn("systemMessage", json.loads(proc.stdout))


class TestKimiNativeHookEvidenceIsRecorded(unittest.TestCase):
    """K4 and K5 were settled natively on Kimi Code 2.7.2 (compatibility matrix E30, E31); the docs
    must say so instead of listing them as unverified."""

    def docs(self):
        return {
            ".kimi-plugin/README.md": (REPO / ".kimi-plugin" / "README.md").read_text(encoding="utf-8"),
            "docs/runtime-adapter.md#Kimi": runtime_adapter_section("Kimi Code adapter"),
        }

    def test_docs_cite_the_native_hook_evidence(self):
        for name, text in self.docs().items():
            flat = " ".join(text.split())
            for marker in ("E30", "E31", "2.7.2", "looseObject", "local OpenAI-compatible"):
                self.assertIn(marker, flat, f"{name} missing {marker}")

    def test_docs_no_longer_list_k4_and_k5_as_unverified(self):
        for name, text in self.docs().items():
            flat = " ".join(text.split())
            for stale in ("Still unverified, because no Kimi CLI was available",
                          "Unverified without a live Kimi run",
                          "that route is not natively verified here",
                          "Hook delivery and live model behavior are unverified",
                          "without a model session or hook execution claim"):
                self.assertNotIn(stale, flat, f"{name} still says: {stale}")

    def test_matrix_records_the_kimi_rows(self):
        log = (REPO / "docs" / "publication" / "compatibility-matrix.md").read_text(encoding="utf-8")
        log = log.split("## Evidence log", 1)[1]
        rows = {r.split("|")[1].strip(): r for r in log.splitlines() if r.startswith("| E")}
        for row_id, result in (("E30", "hook_registration=passed"), ("E31", "hook_delivery=passed")):
            self.assertIn(row_id, rows)
            self.assertIn("Kimi Code", rows[row_id])
            self.assertIn("2.7.2", rows[row_id])
            self.assertIn(result, rows[row_id])

    def test_warn_mode_claim_matches_a_commit_that_succeeded(self):
        # The first warn turn stopped at git's missing author identity after the hook allowed the
        # call; the claim stands only on the re-run with a repo-local identity, where the commit
        # succeeded. The GitHub-URL provenance (source, ref, installed sha) is recorded in E30.
        readme = " ".join((REPO / ".kimi-plugin" / "README.md").read_text(encoding="utf-8").split())
        self.assertNotIn("the warned commit ran and", readme)
        self.assertIn("repo-local Git identity", readme)
        log = (REPO / "docs" / "publication" / "compatibility-matrix.md").read_text(encoding="utf-8")
        rows = {r.split("|")[1].strip(): r for r in log.split("## Evidence log", 1)[1].splitlines()
                if r.startswith("| E")}
        self.assertIn("user.email", rows["E31"])
        self.assertIn("succeeded on `main`", rows["E31"])
        for field in ("original_source", "installed_sha", "0e93e820032a84a7535f20521e6b37a270cb3e42",
                      "GET /api/v1/plugins/agentic-sdlc"):
            self.assertIn(field, rows["E30"])


class TestAdapterFilesKeepHouseContracts(unittest.TestCase):
    def test_no_root_portable_manifest_and_no_auto_discovered_hook_file(self):
        self.assertFalse((REPO / "plugin.json").exists())
        self.assertFalse((REPO / "hooks" / "hooks.json").exists())

    def test_other_adapters_keep_their_own_wiring(self):
        claude = read_json(REPO / ".claude-plugin" / "plugin.json")
        codex = read_json(REPO / ".codex-plugin" / "plugin.json")
        zcode = read_json(REPO / ".zcode-plugin" / "plugin.json")
        grok = read_json(REPO / ".grok-plugin" / "plugin.json")
        self.assertEqual(claude["hooks"], "./hooks/hooks-claude.json")
        self.assertEqual(codex["hooks"], "./hooks/hooks-codex.json")
        self.assertEqual(zcode["name"], "agentic-sdlc")
        self.assertEqual(zcode["hooks"], "./hooks/hooks-zcode.json")
        self.assertEqual(grok["hooks"], "./hooks/hooks-grok.json")

    def test_zcode_marketplace_is_untouched(self):
        zcode_market = read_json(REPO / "marketplace.json")
        self.assertEqual(zcode_market["name"], "mrbekox")

    def test_adapter_readme_documents_local_install(self):
        text = (REPO / ".kimi-plugin" / "README.md").read_text(encoding="utf-8")
        for marker in (
            "/plugins install",
            "experimental",
            "node",
            "not a 0.4.3 release target",
        ):
            self.assertIn(marker, text, f".kimi-plugin/README.md missing {marker}")

    def test_adapter_status_is_recorded_not_promoted(self):
        adapter = (REPO / "docs" / "runtime-adapter.md").read_text(encoding="utf-8")
        self.assertIn("Kimi Code adapter (experimental", adapter)
        self.assertIn("KIMI_PLUGIN_ROOT", adapter)
        self.assertIn("tool_input", adapter)


class TestKimiFilesAreTracked(unittest.TestCase):
    """Every repository path this suite reads must be COMMITTED, not merely present here.

    The trap this catches: a tracked test that reads an untracked file passes in the authoring
    working tree and fails on a clean clone and in CI with FileNotFoundError - and the release
    archive is built from the commit tree, so the file would be missing there too. Staging
    everything instead is the opposite trap: it sweeps in orphans. This test makes the required
    set explicit.
    """

    REQUIRED = (
        ".kimi-plugin/plugin.json",
        ".kimi-plugin/README.md",
        "marketplace-kimi.json",
        "docs/publication/kimi-marketplace.md",
        "tests/test_kimi_packaging.py",
    )

    def test_paths_this_suite_reads_are_tracked(self):
        git = shutil.which("git")
        if git is None:
            self.skipTest("git not available - cannot check the tracked set")
        proc = subprocess.run(
            [git, "ls-files", "--error-unmatch", "--"] + sorted(self.REQUIRED),
            cwd=str(REPO), capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(
            proc.returncode, 0,
            "untracked path read by a tracked test (commit it, or the clean clone fails): "
            + (proc.stderr or proc.stdout).strip(),
        )


if __name__ == "__main__":
    unittest.main()
