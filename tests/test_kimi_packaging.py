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
import subprocess
import shutil
import re
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
