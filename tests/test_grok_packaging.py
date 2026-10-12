"""Grok CLI adapter packaging contract: manifest, local marketplace, narrow hook wiring.

Grok is an experimental adapter target, not a supported 0.4.3 release target
(docs/runtime-adapter.md). These tests lock the adapter files to the Grok plugin/hook
schema read this session from ~/.grok/docs/user-guide/09-plugins.md, 08-skills.md,
10-hooks.md and 16-subagents.md, plus live `grok plugin --help` / `validate --help`
(grok 1.0.34), without loosening the Claude Code / Codex packaging contracts in
test_packaging_metadata.py.

Version binding: scripts/bump_version.py tracks the Grok manifest and marketplace
entry; these tests independently bind their values to VERSION.
"""
import importlib.util
import json
import subprocess
import shutil
import re
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
GROK_MANIFEST = REPO / ".grok-plugin" / "plugin.json"
GROK_MARKETPLACE = REPO / ".grok-plugin" / "marketplace.json"
GROK_HOOKS = REPO / "hooks" / "hooks-grok.json"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
# Hook events listed in ~/.grok/docs/user-guide/10-hooks.md (read 2026-09-19).
GROK_HOOK_EVENTS = {
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PermissionDenied",
    "Stop",
    "StopFailure",
    "StopCancelled",
    "Notification",
    "SubagentStart",
    "SubagentStop",
    "SubagentEnd",
    "PreCompact",
    "PostCompact",
    "SessionEnd",
}
# Matcher tokens: 10-hooks.md alias table (Bash -> run_terminal_command) plus the
# live toolName observed in this Grok session. Write-scan matchers stay out until
# a search_replace toolInput envelope is captured as hook stdin.
ALLOWED_MATCHER_TOKENS = {"Bash", "run_terminal_command"}
WIRED_SCRIPTS = {
    "scan-commit.mjs",
    "destructive-command-guard.mjs",
    "branch-guard.mjs",
}
# Script basenames that must never appear in the wired command: Claude-transcript
# and Codex-rollout readers, write/Stop scanners, and SessionStart until a Grok
# payload is captured. Prose in the wire's "description" is not checked.
UNVERIFIED_SCRIPT_TOKENS = (
    "completion-claim-guard",
    "flow-step-guard",
    "flow-order-guard",
    "worktree-scan",
    "codex",
    "session-start",
    "scan-write",
)
CLAUDE_ONLY_DESCRIPTION = "Claude Code skill library"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def current_version():
    return (REPO / "VERSION").read_text(encoding="utf-8").strip()


def wired_hooks(wire):
    for groups in wire["hooks"].values():
        for group in groups:
            for hook in group["hooks"]:
                yield hook


def command_script_basename(command):
    if names := re.findall(r"[a-z-]+\.mjs", str(command)):
        return names[-1]
    # Final path segment. strip('"') stays so a quoted command would not keep the quote.
    return str(command).replace("\\", "/").rsplit("/", 1)[-1].split()[0].strip('"')


class TestGrokManifest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(GROK_MANIFEST.is_file(), ".grok-plugin/plugin.json missing")
        self.manifest = read_json(GROK_MANIFEST)

    def test_manifest_identity_matches_version(self):
        self.assertRegex(self.manifest["name"], NAME_RE)
        self.assertEqual(self.manifest["name"], "agentic-sdlc")
        self.assertEqual(self.manifest["version"], current_version())

    def test_description_is_not_the_claude_only_sentence(self):
        description = self.manifest["description"]
        self.assertTrue(description)
        self.assertNotIn(CLAUDE_ONLY_DESCRIPTION, description)

    def test_hooks_point_at_the_grok_wire_not_the_auto_discovered_file(self):
        self.assertEqual(self.manifest["hooks"], "./hooks/hooks-grok.json")

    def test_no_mcp_or_lsp_surface(self):
        self.assertNotIn("mcpServers", self.manifest)
        self.assertNotIn("lspServers", self.manifest)
        self.assertNotIn(".mcp.json", json.dumps(self.manifest))


class TestGrokMarketplace(unittest.TestCase):
    def setUp(self):
        self.assertTrue(GROK_MARKETPLACE.is_file(), ".grok-plugin/marketplace.json missing")
        self.market = read_json(GROK_MARKETPLACE)

    def test_marketplace_identity_and_entry_align_with_manifest(self):
        # Reuse the house catalog name `mrbekox` (Claude + ZCode) so one owner
        # index is recognizable; Grok 09-plugins.md does not require uniqueness
        # across other-runtime indexes.
        self.assertEqual(self.market["name"], "mrbekox")
        entry = self.market["plugins"][0]
        self.assertEqual(entry["name"], "agentic-sdlc")
        self.assertEqual(entry["version"], current_version())
        self.assertNotIn(CLAUDE_ONLY_DESCRIPTION, entry.get("description", ""))
        # Grok cannot point a catalog entry at the catalog's own root: MarketplaceRelativePath strips
        # "./", the remainder is empty, and the scanner logs MarketplacePathError::Empty and SKIPS the
        # entry (observed on grok 1.0.50: `plugin list --available` returned []). The catalog therefore
        # names the repository as a remote `url` source, the form the official xAI catalog uses.
        source = entry["source"]
        self.assertEqual(source, {"source": "url", "url": "https://github.com/MrBekoX/agentic-sdlc.git"})

    def test_no_artifact_or_pinned_sha_invented_for_the_personal_catalog(self):
        # A pinned 40-char sha belongs in the reviewed xAI catalog PR for a release commit; this
        # personal catalog follows the default branch and must not carry an invented one.
        entry = self.market["plugins"][0]
        self.assertNotIn("_artifact", entry)
        self.assertNotIn("sha256", entry)
        source = entry["source"]
        if isinstance(source, dict):
            self.assertNotIn("sha256", source)
            self.assertNotIn("sha", source)


class TestGrokHookWire(unittest.TestCase):
    def setUp(self):
        self.assertTrue(GROK_HOOKS.is_file(), "hooks/hooks-grok.json missing")
        self.wire = read_json(GROK_HOOKS)

    def test_only_verified_events_are_wired(self):
        events = set(self.wire["hooks"])
        self.assertEqual(events, {"PreToolUse"})
        self.assertLessEqual(events, GROK_HOOK_EVENTS)

    def test_matchers_use_only_proven_tool_names(self):
        for groups in self.wire["hooks"].values():
            for group in groups:
                matcher = group.get("matcher") or ""
                tokens = {part for part in matcher.split("|") if part}
                self.assertTrue(tokens, "empty matcher is not a proven tool name")
                self.assertLessEqual(tokens, ALLOWED_MATCHER_TOKENS)

    def test_executors_are_command_strings_with_plugin_root_and_second_timeouts(self):
        # Root bytes stay environment data until Node opens the module. Grok has
        # no Codex commandWindows selector; Node must be on the selected shell PATH.
        for hook in wired_hooks(self.wire):
            self.assertEqual(hook["type"], "command")
            self.assertRegex(
                hook["command"],
                r"^node -e \"const p=require\('node:path'\)\.join\(process\.env\.GROK_PLUGIN_ROOT,'hooks','[a-z-]+\.mjs'\);process\.argv\[1\]=p;import\(require\('node:url'\)\.pathToFileURL\(p\)\.href\)\"$",
            )
            self.assertIsInstance(hook["timeout"], int)
            self.assertGreater(hook["timeout"], 0)
            self.assertLess(hook["timeout"], 600)
            self.assertNotIn("timeoutMs", hook)
            self.assertNotIn("args", hook)
            self.assertNotIn("commandWindows", hook)

    def test_wired_scripts_exist_and_are_the_verified_set(self):
        wired = {command_script_basename(hook["command"]) for hook in wired_hooks(self.wire)}
        self.assertEqual(wired, WIRED_SCRIPTS)
        for name in wired:
            self.assertTrue((REPO / "hooks" / name).is_file(), name)

    def test_unverified_runtime_readers_stay_unwired(self):
        for hook in wired_hooks(self.wire):
            basename = command_script_basename(hook["command"])
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

    def test_zcode_marketplace_and_wire_are_untouched(self):
        zcode = read_json(REPO / "marketplace.json")
        self.assertEqual(zcode["name"], "mrbekox")
        self.assertEqual(zcode["plugins"][0]["source"], "./")
        zcode_manifest = read_json(REPO / ".zcode-plugin" / "plugin.json")
        self.assertEqual(zcode_manifest["hooks"], "./hooks/hooks-zcode.json")

    def test_adapter_readme_documents_local_install(self):
        text = (REPO / ".grok-plugin" / "README.md").read_text(encoding="utf-8")
        for marker in (
            "grok plugin marketplace add",
            "grok plugin install",
            "--trust",
            "grok plugin enable",
            "grok plugin details",
            "grok inspect",
            "/using-agentic-sdlc",
            "GROK_PLUGIN_ROOT",
            "experimental",
            "node",
        ):
            self.assertIn(marker, text, f".grok-plugin/README.md missing {marker}")

    def test_adapter_status_is_recorded_not_promoted(self):
        adapter = (REPO / "docs" / "runtime-adapter.md").read_text(encoding="utf-8")
        self.assertIn("Grok", adapter)
        self.assertIn("experimental", adapter.lower())
        self.assertIn("not a 0.4.3 release target", adapter)
        self.assertIn("GROK_PLUGIN_ROOT", adapter)
        self.assertIn("toolInput", adapter)
        self.assertIn("run_terminal_command", adapter)


def load_lifecycle_checker():
    spec = importlib.util.spec_from_file_location(
        "check_native_lifecycle", REPO / "scripts" / "check_native_lifecycle.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestGrokVendorValidator(unittest.TestCase):
    """The vendor's own manifest check, when the vendor CLI is installed.

    Opt-in by presence, never a silent pass: an absent CLI (or a .cmd/.bat shim) skips with a
    named reason. This is the same check xAI's tooling runs, so it catches a manifest defect the
    house tests do not model. `grok plugin validate` is read-only and offline, and it runs in a
    disposable profile: GROK_HOME, HOME and USERPROFILE point into a temporary directory, the
    environment is the lifecycle checker's allowlist (no provider keys), and the working directory
    is outside every repository, so neither the real ~/.grok nor this checkout's .grok/ is read.
    """

    def test_vendor_validate_accepts_the_manifest(self):
        checker = load_lifecycle_checker()
        try:
            grok = checker.resolve_cli("grok")
        except checker.NotRun as exc:
            self.skipTest("grok CLI not usable (%s) - vendor manifest validation not run" % exc.reason)
        with tempfile.TemporaryDirectory(prefix="grok-validate-", ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            env = checker.build_child_env(root, home=root / "home")
            cwd = root / "cwd"
            cwd.mkdir()
            for key in ("GROK_HOME", "HOME", "USERPROFILE"):
                self.assertTrue(Path(env[key]).resolve().is_relative_to(root.resolve()), key)
            self.assertFalse(cwd.resolve().is_relative_to(REPO.resolve()))
            proc = subprocess.run(
                [grok, "plugin", "validate", str(REPO)],
                cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, capture_output=True,
                text=True, encoding="utf-8", timeout=120,
            )
        self.assertEqual(proc.returncode, 0, (proc.stdout or "") + (proc.stderr or ""))
        self.assertIn("valid", (proc.stdout or "").lower())

class TestGrokFilesAreTracked(unittest.TestCase):
    """Every repository path this suite reads must be COMMITTED, not merely present here.

    The trap this catches: a tracked test that reads an untracked file passes in the authoring
    working tree and fails on a clean clone and in CI with FileNotFoundError - and the release
    archive is built from the commit tree, so the file would be missing there too. Staging
    everything instead is the opposite trap: it sweeps in orphans. This test makes the required
    set explicit.
    """

    REQUIRED = (
        ".grok/workflows/spec-plan-draft.rhai",
        ".grok/workflows/multi-lens-review.rhai",
        ".grok/workflows/skill-draft.rhai",
        "hooks/hooks-grok.json",
        ".grok-plugin/plugin.json",
        ".grok-plugin/marketplace.json",
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
