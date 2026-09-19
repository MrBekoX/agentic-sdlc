"""ZCode adapter packaging contract: manifest, local marketplace, narrow hook wiring.

ZCode (Z.ai) is an experimental adapter target, not a supported 0.4.3 release
target (docs/runtime-adapter.md). These tests lock the adapter files to the
ZCode plugin/hook schema fetched on 2026-09-19 from zcode.z.ai/en/docs/plugin,
zcode.z.ai/en/docs/skill and zcode.z.ai/en/docs/hooks, plus the plugin/marketplace
naming rules of github.com/zai-org/zcode-plugins, without loosening the
Claude Code / Codex packaging contracts in test_packaging_metadata.py.

Version binding note: scripts/bump_version.py MANIFEST_KEYS tracks only the
Claude Code and Codex manifests, so these tests pin the ZCode manifest and
marketplace entry to VERSION instead. A version bump that forgets the ZCode
files fails this test loudly rather than drifting silently.
"""
import json
import re
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
ZCODE_MANIFEST = REPO / ".zcode-plugin" / "plugin.json"
ZCODE_MARKETPLACE = REPO / "marketplace.json"
ZCODE_HOOKS = REPO / "hooks" / "hooks-zcode.json"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
# The seven events of the fetched ZCode hook reference (2026-09-19).
ZCODE_HOOK_EVENTS = {
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "PostToolUseFailure",
    "Stop",
}
# Only tool names observed in a live ZCode session and SessionStart source
# values from the fetched hooks example may appear as matchers.
ALLOWED_MATCHERS = {"Bash", "Write|Edit", "startup|clear|compact"}
WIRED_SCRIPTS = {
    "scan-commit.mjs",
    "destructive-command-guard.mjs",
    "branch-guard.mjs",
    "scan-write.mjs",
    "session-start.mjs",
}
# Script basenames that must never appear in the wired args: Claude-transcript
# and Codex-rollout readers and guards not verified against the ZCode payload
# shape. Prose in the wire's "description" is not checked — only what executes.
UNVERIFIED_SCRIPT_TOKENS = (
    "completion-claim-guard",
    "flow-step-guard",
    "flow-order-guard",
    "worktree-scan",
    "codex",
)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def current_version():
    return (REPO / "VERSION").read_text(encoding="utf-8").strip()


def wired_hooks(wire):
    for groups in wire["hooks"].values():
        for group in groups:
            for hook in group["hooks"]:
                yield hook


class TestZcodeManifest(unittest.TestCase):
    def setUp(self):
        self.manifest = read_json(ZCODE_MANIFEST)

    def test_manifest_identity_matches_version(self):
        self.assertRegex(self.manifest["name"], NAME_RE)
        self.assertEqual(self.manifest["name"], "agentic-sdlc")
        self.assertEqual(self.manifest["version"], current_version())

    def test_shared_components_are_declared_flat(self):
        # Flat root layout: skills/<name>/SKILL.md — grouped subdirectories are
        # not picked up by the ZCode agent (fetched skill doc, 2026-09-19).
        self.assertEqual(self.manifest["skills"], "skills")
        self.assertEqual(self.manifest["commands"], "commands")
        self.assertEqual(self.manifest["agents"], "agents")

    def test_hooks_point_at_the_zcode_wire_not_the_auto_discovered_file(self):
        self.assertEqual(self.manifest["hooks"], "./hooks/hooks-zcode.json")

    def test_no_mcp_or_user_config_surface(self):
        self.assertNotIn("mcpServers", self.manifest)
        self.assertNotIn("userConfig", self.manifest)

    def test_bilingual_description_present(self):
        i18n = self.manifest["description_i18n"]
        self.assertTrue(i18n.get("en"))
        self.assertTrue(i18n.get("zh-CN"))


class TestZcodeMarketplace(unittest.TestCase):
    def setUp(self):
        self.market = read_json(ZCODE_MARKETPLACE)

    def test_marketplace_identity_and_entry_align_with_manifest(self):
        self.assertRegex(self.market["name"], NAME_RE)
        self.assertEqual(self.market["name"], "mrbekox")
        entry = self.market["plugins"][0]
        self.assertEqual(entry["name"], "agentic-sdlc")
        self.assertEqual(entry["version"], current_version())
        self.assertEqual(entry["source"], "./")
        self.assertEqual(entry["category"], "developer-tools")

    def test_no_zip_artifact_fields_invented_for_a_local_source(self):
        # sha256/_artifact belong to the docs/distribution.md zip channel; a
        # local directory source must not fabricate them.
        entry = self.market["plugins"][0]
        self.assertNotIn("_artifact", entry)
        source = entry["source"]
        if isinstance(source, dict):
            self.assertNotIn("sha256", source)


class TestZcodeHookWire(unittest.TestCase):
    def setUp(self):
        self.wire = read_json(ZCODE_HOOKS)

    def test_only_verified_events_are_wired(self):
        events = set(self.wire["hooks"])
        self.assertEqual(events, {"PreToolUse", "PostToolUse", "SessionStart"})
        self.assertLessEqual(events, ZCODE_HOOK_EVENTS)

    def test_matchers_use_only_observed_tool_and_event_names(self):
        for groups in self.wire["hooks"].values():
            for group in groups:
                self.assertIn(group.get("matcher"), ALLOWED_MATCHERS)

    def test_executors_are_process_argv_with_plugin_root(self):
        for hook in wired_hooks(self.wire):
            self.assertEqual(hook["type"], "process")
            self.assertEqual(hook["command"], "node")
            self.assertEqual(len(hook["args"]), 1)
            self.assertRegex(hook["args"][0], r"^\$\{ZCODE_PLUGIN_ROOT\}/hooks/[a-z-]+\.mjs$")
            self.assertIsInstance(hook["timeoutMs"], int)

    def test_wired_scripts_exist_and_are_the_verified_set(self):
        wired = {hook["args"][0].rsplit("/", 1)[-1] for hook in wired_hooks(self.wire)}
        self.assertEqual(wired, WIRED_SCRIPTS)
        for name in wired:
            self.assertTrue((REPO / "hooks" / name).is_file(), name)

    def test_unverified_runtime_readers_stay_unwired(self):
        for hook in wired_hooks(self.wire):
            basename = hook["args"][0].rsplit("/", 1)[-1]
            for token in UNVERIFIED_SCRIPT_TOKENS:
                self.assertNotIn(token, basename)


class TestAdapterFilesKeepHouseContracts(unittest.TestCase):
    def test_no_root_portable_manifest_and_no_auto_discovered_hook_file(self):
        self.assertFalse((REPO / "plugin.json").exists())
        self.assertFalse((REPO / "hooks" / "hooks.json").exists())

    def test_claude_and_codex_manifests_keep_their_own_wiring(self):
        claude = read_json(REPO / ".claude-plugin" / "plugin.json")
        codex = read_json(REPO / ".codex-plugin" / "plugin.json")
        self.assertEqual(claude["hooks"], "./hooks/hooks-claude.json")
        self.assertEqual(codex["hooks"], "./hooks/hooks-codex.json")

    def test_adapter_readmes_document_local_install(self):
        for name in ("README.md", "README_CN.md"):
            text = (REPO / ".zcode-plugin" / name).read_text(encoding="utf-8")
            for marker in ("Add marketplace", "Install", "Enable", "$using-agentic-sdlc", "node"):
                self.assertIn(marker, text, f".zcode-plugin/{name} missing {marker}")

    def test_adapter_status_is_recorded_not_promoted(self):
        adapter = (REPO / "docs" / "runtime-adapter.md").read_text(encoding="utf-8")
        self.assertIn("ZCode", adapter)
        self.assertIn("experimental", adapter.lower())
        self.assertIn("not a 0.4.3 release target", adapter)


if __name__ == "__main__":
    unittest.main()
