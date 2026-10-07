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
import subprocess
import shutil
import re
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO = Path(__file__).resolve().parents[1]


def workflow_port_sources(root):
    """Source ports, including accidental .zcode copies, excluding generated archive/cache trees."""
    found = []
    for directory, dirs, files in os.walk(root):
        relative = Path(directory).relative_to(root)
        dirs[:] = [name for name in dirs if name not in {".git", "node_modules", "__pycache__"}
                   and not (relative == Path(".") and name in {"dist", "build"})
                   and not (relative == Path("tests") and name == "artifacts")]
        found.extend((relative / name).as_posix() for name in files if name.endswith(".dwf.ts"))
    return sorted(found)

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
        # `source` is a plain path string for a local marketplace; assert that directly rather
        # than behind an `isinstance(dict)` arm that the "./" assertion above makes unreachable.
        self.assertIsInstance(entry["source"], str)
        self.assertNotIn("sha256", entry)


class TestZcodeHookWire(unittest.TestCase):
    def setUp(self):
        self.wire = read_json(ZCODE_HOOKS)

    def test_only_verified_events_are_wired(self):
        events = set(self.wire["hooks"])
        self.assertEqual(events, {"PreToolUse", "PostToolUse", "SessionStart"})
        # The literal above is the contract; this pins it to the documented event vocabulary so a
        # typo in the literal is caught rather than silently redefining what "verified" means.
        self.assertLessEqual({"PreToolUse", "PostToolUse", "SessionStart"}, ZCODE_HOOK_EVENTS)

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
        # This cannot merely re-derive the wired set: `wired == WIRED_SCRIPTS` above already
        # implies it. Assert the property on the CONSTANT instead, so widening WIRED_SCRIPTS to
        # admit a Claude-transcript or Codex-rollout reader fails here even if the wire matches.
        self.assertTrue(WIRED_SCRIPTS, "the verified set must not be empty")
        for name in WIRED_SCRIPTS:
            for token in UNVERIFIED_SCRIPT_TOKENS:
                self.assertNotIn(token, name, f"{name} carries unverified-reader token {token}")


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


class TestZcodeSkillAdapters(unittest.TestCase):
    """Skill-level ZCode runtime adapter locks (docs/zcode-runtime-adapter.md)."""

    def test_runtime_adapter_doc_records_the_capability_map(self):
        text = (REPO / "docs" / "zcode-runtime-adapter.md").read_text(encoding="utf-8")
        for fact in (
            # NOT "CreateWorkflow": that name appears in no shipped source and in no Z.ai
            # document. Pinning it here made an unverified API name harder to delete.
            "Goal Mode",
            "${ZCODE_PLUGIN_ROOT}",
            "spec-plan-draft",
            "agents/*.md",
            "not a 0.4.3 release target",
        ):
            self.assertIn(fact, text)

    def test_router_carries_a_zcode_platform_note(self):
        text = (REPO / "skills" / "using-agentic-sdlc" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("ZCode", text)
        self.assertIn("${ZCODE_PLUGIN_ROOT}", text)
        self.assertIn("docs/zcode-runtime-adapter.md", text)

    def test_dispatch_strategy_maps_zcode_mechanisms(self):
        text = (REPO / "skills" / "dispatch-strategy" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("docs/zcode-runtime-adapter.md", text)
        # The ZCode row must state the tier is unavailable rather than naming an unpublished API.
        zcode_line = next(ln for ln in text.splitlines() if "ZCode (experimental adapter)" in ln)
        self.assertIn("unavailable", zcode_line)
        self.assertNotIn("CreateWorkflow", text)

    def test_pipeline_names_the_zcode_adapter_gate(self):
        text = (REPO / "skills" / "agentic-sdlc-pipeline" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("ZCode Adapter Gate", text)
        self.assertIn("workflows/zcode/spec-plan-draft.dwf.ts", text)

    def test_exactly_one_zcode_workflow_script_exists(self):
        # A second copy under .zcode/workflows/ was orphaned (referenced nowhere) and had already
        # drifted from this one within minutes. One file, one source of truth.
        found = workflow_port_sources(REPO)
        self.assertEqual(found, ["workflows/zcode/spec-plan-draft.dwf.ts"])

    def test_source_port_inventory_ignores_build_copies_but_rejects_orphans(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative in ("workflows/zcode/spec-plan-draft.dwf.ts",
                             "dist/cache/workflows/zcode/spec-plan-draft.dwf.ts",
                             "build/package/workflows/zcode/spec-plan-draft.dwf.ts"):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("// fixture\n", encoding="utf-8")
            with mock.patch.dict(globals(), {"REPO": root}):
                self.test_exactly_one_zcode_workflow_script_exists()
                orphan = root / ".zcode/workflows/spec-plan-draft.dwf.ts"
                orphan.parent.mkdir(parents=True)
                orphan.write_text("// orphan\n", encoding="utf-8")
                with self.assertRaises(AssertionError):
                    self.test_exactly_one_zcode_workflow_script_exists()

    def test_spec_plan_draft_workflow_port_is_present(self):
        text = (REPO / "workflows" / "zcode" / "spec-plan-draft.dwf.ts").read_text(encoding="utf-8")
        self.assertIn("zcode-workflow", text)
        self.assertIn("agent(", text)
        self.assertIn("phase(", text)
        self.assertIn("world.run(", text)
        self.assertIn("validate_artifacts.py", text)
        # Fresh-context critic and the revise ceiling are the contract, not decoration.
        self.assertIn("spec-critic", text)
        self.assertIn("rounds < 2", text)
        # Negative lock: the Claude JS facade must not leak into the ZCode port. Without this a
        # copy of workflows/spec-plan-draft.js would satisfy every positive assertion above.
        for claude_token in ("export const meta", "agentType:", "isolation:", "pipeline("):
            self.assertNotIn(claude_token, text, f"Claude facade token {claude_token} in a ZCode port")
        # The header declares the args the body reads; a rename in one half must fail here.
        header = text.split("*/", 1)[0]
        for arg in ("workId", "requirement", "mode"):
            self.assertIn(f"{arg}:", header, f"{arg} missing from the zcode-workflow header")
            self.assertIn(f"args.{arg}", text, f"{arg} declared but never read")


class TestZcodeWorkflowClaimSweep(unittest.TestCase):
    """The contradiction must be gone from TRACKED files, in EVERY language.

    Four tracked files carried "ZCode has no Workflow runtime", one of them in Chinese - so an
    English-only sweep found three of four and would have shipped the contradiction. These
    assertions run over `git ls-files`, not over a hand-listed set, so a fifth file carrying the
    claim fails here instead of being missed.
    """

    #: Negative forms, in every language the adapter docs are written in.
    STALE_CLAIM = ("has no Workflow runtime", "\u6ca1\u6709 Workflow")
    #: An API name that appears in no shipped workflow script and in no vendor document.
    UNSOURCED_API = "CreateWorkflow"

    def _tracked_text_files(self):
        git = shutil.which("git")
        if git is None:
            self.skipTest("git not available - cannot enumerate the tracked set")
        proc = subprocess.run(
            [git, "ls-files", "--", "*.md", "*.json", "*.mjs", "*.ts", "*.py"],
            cwd=str(REPO), capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for rel in proc.stdout.split("\n"):
            rel = rel.strip()
            if not rel or rel == "tests/test_zcode_packaging.py":
                continue  # this file states the forbidden strings in order to forbid them
            path = REPO / rel
            try:
                yield rel, path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

    def test_no_tracked_file_still_says_zcode_has_no_workflow_runtime(self):
        # Subject-aware. The bare phrase is also a TRUE statement about other runtimes -
        # "Codex has no Workflow runtime" is correct and appears in a test comment on another
        # branch - so matching it without checking who it is about flags a correct sentence as
        # stale documentation. The claim counts only when ZCode is the subject of the line that
        # carries it.
        offenders = []
        for rel, text in self._tracked_text_files():
            for line in text.splitlines():
                for claim in self.STALE_CLAIM:
                    if claim in line and "zcode" in line.lower():
                        offenders.append((rel, claim))
        self.assertEqual(offenders, [], "stale ZCode workflow claim still tracked: %r" % offenders)

    def test_no_tracked_file_asserts_the_unsourced_api_name(self):
        offenders = [
            rel for rel, text in self._tracked_text_files() if self.UNSOURCED_API in text
        ]
        self.assertEqual(
            offenders, [],
            "%s names no API in either workflow script and has no vendor source; "
            "it must not be written into a tracked file: %r" % (self.UNSOURCED_API, offenders),
        )

class TestZcodeFilesAreTracked(unittest.TestCase):
    """Every repository path this suite reads must be COMMITTED, not merely present here.

    The trap this catches: a tracked test that reads an untracked file passes in the authoring
    working tree and fails on a clean clone and in CI with FileNotFoundError - and the release
    archive is built from the commit tree, so the file would be missing there too. Staging
    everything instead is the opposite trap: it sweeps in orphans. This test makes the required
    set explicit.
    """

    REQUIRED = (
        "docs/zcode-runtime-adapter.md",
        "workflows/zcode/spec-plan-draft.dwf.ts",
        "hooks/hooks-zcode.json",
        ".zcode-plugin/plugin.json",
        "marketplace.json",
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
