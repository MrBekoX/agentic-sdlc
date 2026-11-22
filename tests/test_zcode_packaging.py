"""ZCode adapter packaging contract: manifest, local marketplace, narrow hook wiring.

ZCode (Z.ai) is an experimental adapter target, not a supported 0.4.3 release
target (docs/runtime-adapter.md). These tests lock the adapter files to the
ZCode plugin/hook schema fetched on 2026-09-19 from zcode.z.ai/en/docs/plugin,
zcode.z.ai/en/docs/skill and zcode.z.ai/en/docs/hooks, plus the plugin/marketplace
naming rules of github.com/zai-org/zcode-plugins, without loosening the
Claude Code / Codex packaging contracts in test_packaging_metadata.py.

Version binding: scripts/bump_version.py tracks the ZCode manifest and marketplace
entry; these tests independently bind their values to VERSION.
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
                   and not (relative == Path(".") and name in {"dist", "build", ".worktrees", "audit-docs"})
                   and not (relative == Path(".claude") and name == "worktrees")
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
# SessionStart sources per the vendor CLI README (zai-org/ZCode apps/zcode-cli/README.md): the matcher
# sees `startup` or `resume`; without `resume` a resumed session got no bootstrap context.
ALLOWED_MATCHERS = {"Bash", "Write|Edit", "startup|resume|clear|compact"}
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


def runtime_adapter_section(heading_prefix):
    """The `## <heading_prefix>...` section of docs/runtime-adapter.md, up to the next `## `."""
    text = (REPO / "docs" / "runtime-adapter.md").read_text(encoding="utf-8")
    start = text.index("\n## " + heading_prefix)
    end = text.find("\n## ", start + 1)
    return text[start:end if end >= 0 else len(text)]


def tracked_markdown(root=REPO):
    """Tracked *.md paths, or None when they cannot be listed (no git, not a work tree, or
    an empty listing), so the sweep skips instead of passing over zero files."""
    git = shutil.which("git")
    if git is None:
        return None
    proc = subprocess.run([git, "ls-files", "-z", "--", "*.md"], cwd=str(root),
                          capture_output=True, text=True, encoding="utf-8")
    names = [name for name in proc.stdout.split("\0") if name]
    if proc.returncode != 0 or not names:
        return None
    return names


# The retired claim: ZCode reads a directory or GitHub source through the Claude catalog
# first / before / instead of the root file. Paraphrases are covered, not only the old text.
STALE_ZCODE_CATALOG_CLAIMS = (
    re.compile(r"\.claude-plugin/marketplace\.json`?\s+(first|before|instead|takes precedence)"),
    re.compile(r"prefers\s+(the\s+)?`?\.claude-plugin/marketplace\.json"),
    re.compile(r"先读取\s*`\.claude-plugin/marketplace\.json`"),
    re.compile(r"先通过\s*`\.claude-plugin/marketplace\.json`"),
)

# Historical records may quote the retired claim in order to say it was removed.
HISTORICAL_RECORDS = re.compile(r"^(CHANGELOG\.md|docs/release-evidence-[^/]+\.md)$")


# The one native observation of the lookup order (compatibility matrix E36, 2026-11-22: the agent
# CLI 0.16.9 bundled with ZCode desktop 3.14.5, `plugins marketplace add MrBekoX/agentic-sdlc`).
# A paragraph may state the order only while it cites that row (the exact id) and names the scope
# E36 observed (the agent CLI 0.16.9 and a GitHub source); the clause that states the order must not
# extend it to the desktop GUI, which was not driven. Anything else is still stale.
CATALOG_ORDER_EVIDENCE = re.compile(r"\bE36\b")
CATALOG_ORDER_SCOPE = ("agent CLI 0.16.9", "GitHub")
CLAUSE_BREAK = re.compile(r"(?<=[。；])|(?<=[.;])\s+")


def _cited_in_scope(paragraph, clause):
    flat = " ".join(paragraph.split())
    return (CATALOG_ORDER_EVIDENCE.search(flat) is not None
            and all(term in flat for term in CATALOG_ORDER_SCOPE)
            and "GUI" not in clause)


def stale_zcode_catalog_claim(text):
    for paragraph in re.split(r"\n\s*\n", text):
        for clause in CLAUSE_BREAK.split(" ".join(paragraph.split())):
            if any(pattern.search(clause) for pattern in STALE_ZCODE_CATALOG_CLAIMS) \
                    and not _cited_in_scope(paragraph, clause):
                return True
    return False


def sweep_targets(names):
    return [name for name in names if not HISTORICAL_RECORDS.match(name)]


class TestRootMarketplaceStaysTheZcodeCatalog(unittest.TestCase):
    """The root marketplace.json is ZCode's only documented catalog location.

    zcode.z.ai/en/docs/plugin (fetched 2026-11-21): "list them in a marketplace.json at the
    root, and push to GitHub"; a marketplace source is "A GitHub repository", "A Git URL" or
    "A local marketplace file or directory". `.claude-plugin` appears there only in the
    plugin-manifest lookup (.zcode-plugin/plugin.json -> .claude-plugin/plugin.json), never as
    a catalog location. Removing the root file removes the documented ZCode install path.
    """

    def test_root_marketplace_is_present_and_the_zcode_schema_catalog(self):
        self.assertTrue(ZCODE_MARKETPLACE.is_file(),
                        "root marketplace.json is ZCode's only documented catalog; keep it")
        market = read_json(ZCODE_MARKETPLACE)
        self.assertEqual(market["name"], "mrbekox")
        self.assertEqual(len(market["plugins"]), 1)
        entry = market["plugins"][0]
        self.assertEqual(entry["name"], "agentic-sdlc")
        self.assertEqual(entry["source"], "./")
        self.assertEqual(entry["category"], "developer-tools")
        i18n = entry.get("description_i18n")
        self.assertIsInstance(i18n, dict, "description_i18n is the ZCode-only catalog field")
        self.assertTrue(i18n.get("en"))
        self.assertTrue(i18n.get("zh-CN"))

    def test_no_tracked_doc_says_zcode_reads_the_claude_catalog_first(self):
        # The claim "a directory or GitHub source is read through the Claude catalog first" is
        # not in the vendor doc, and the E9/E14/E15 lifecycle runs did not observe it. The agent
        # CLI 0.16.9 did read `.claude-plugin/marketplace.json` first for a GitHub source on
        # 2026-11-22 (E36), so a paragraph may say so only while it cites E36. CHANGELOG.md and the
        # docs/release-evidence-*.md records are excluded: they may name the retired claim.
        files = tracked_markdown()
        if files is None:
            self.skipTest("tracked docs cannot be listed (no git work tree)")
        for name in sweep_targets(files):
            text = (REPO / name).read_text(encoding="utf-8")
            self.assertFalse(stale_zcode_catalog_claim(text), f"{name} repeats the undocumented claim")

    def test_stale_claim_patterns_catch_paraphrases_but_not_the_correction(self):
        claude = "`.claude-plugin/marketplace.json`"
        for claim in (
            f"a GitHub source is read through {claude} first",
            f"a directory source reads {claude} before the root file",
            f"ZCode uses {claude} instead of the root file",
            f"{claude} takes precedence over the root file",
            f"ZCode prefers {claude} for such sources",
            f"目录源会先读取 {claude}",
        ):
            self.assertTrue(stale_zcode_catalog_claim(claim), claim)
        for correction in (
            f"whether ZCode reads {claude} from such a source is undocumented",
            f"a {claude} catalog fallback is undocumented and not observed",
            f"for a GitHub source the agent CLI 0.16.9 read {claude} first (E36)",
        ):
            self.assertFalse(stale_zcode_catalog_claim(correction), correction)
        # The citation must sit in the same paragraph as the claim.
        self.assertTrue(stale_zcode_catalog_claim(f"see E36.\n\nZCode prefers {claude} for such sources"))
        # A citation does not license a wider claim than E36 observed (agent CLI 0.16.9, a GitHub
        # source run; the GUI was not driven), and only the exact row id counts as a citation.
        for overreach in (
            f"The ZCode desktop GUI and every directory source read {claude} first (E36).",
            f"ZCode reads {claude} first for every source (E36).",
            f"for a GitHub source the agent CLI 0.16.9 read {claude} first (E360)",
            f"the agent CLI 0.16.9 read {claude} first for a GitHub source, and so does the GUI (E36)",
        ):
            self.assertTrue(stale_zcode_catalog_claim(overreach), overreach)

    def test_sweep_excludes_only_the_historical_records(self):
        self.assertEqual(
            sweep_targets(["CHANGELOG.md", "docs/release-evidence-0.7.0.md", "README.md",
                           "docs/troubleshooting.md", "docs/CHANGELOG.md"]),
            ["README.md", "docs/troubleshooting.md", "docs/CHANGELOG.md"])

    def test_tracked_markdown_is_none_outside_a_work_tree(self):
        if shutil.which("git") is None:
            self.skipTest("git not available")
        with tempfile.TemporaryDirectory() as tmp:
            probe = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=tmp,
                                   capture_output=True, text=True, encoding="utf-8")
            if probe.returncode == 0:
                self.skipTest("TMPDIR is inside a git work tree")
            self.assertIsNone(tracked_markdown(Path(tmp)))

    def test_zcode_docs_do_not_overstate_how_a_source_is_resolved(self):
        # The vendor page tells catalog authors to put marketplace.json at the root; it does not
        # say how ZCode resolves a directory or repository source, so only an observation (E36)
        # may say it.
        names = (".zcode-plugin/README.md", "docs/zcode-runtime-adapter.md", "docs/runtime-adapter.md",
                 "docs/plugin-readme.md", "docs/troubleshooting.md", "README.md",
                 "docs/publication/multi-platform-distribution.md", "docs/release-readiness.md")
        for name in names:
            flat = " ".join((REPO / name).read_text(encoding="utf-8").split())
            for phrase in ("documented to use", "documented to read", "as ZCode documents",
                           "ZCode documents a directory or GitHub"):
                self.assertNotIn(phrase, flat, f"{name} overstates the vendor doc: {phrase}")
        for name, text in (
            (".zcode-plugin/README.md", (REPO / ".zcode-plugin" / "README.md").read_text(encoding="utf-8")),
            ("docs/runtime-adapter.md#ZCode", runtime_adapter_section("ZCode adapter")),
            ("docs/zcode-runtime-adapter.md", (REPO / "docs" / "zcode-runtime-adapter.md").read_text(encoding="utf-8")),
        ):
            flat = " ".join(text.split())
            # The lookup order is an observation of one CLI build, cited to its evidence row; the
            # desktop GUI flow was not driven, so the docs must not generalise it to the GUI.
            self.assertIn("agent CLI 0.16.9", flat, name)
            self.assertIn("E36", flat, name)
            self.assertIn("GUI", flat, name)
            # The bundled code uses the same lookup for a directory source (code read 2026-11-22),
            # so the docs state that consequence and that only the GitHub source was run.
            self.assertIn("directory source", flat, name)
            self.assertIn("only the GitHub source was run", flat, name)

    def test_troubleshooting_does_not_present_the_claude_entry_as_a_known_symptom(self):
        text = (REPO / "docs" / "troubleshooting.md").read_text(encoding="utf-8")
        self.assertNotIn("## ZCode Shows The Claude Entry", text)
        start = text.index("\n## ZCode ")
        section = " ".join(text[start:text.find("\n## ", start + 1)].split())
        # Since E36 (2026-11-22) the Claude-entry card is an observed agent CLI 0.16.9 result, so
        # the section cites it and keeps the remedy; the lifecycle runs it relied on stay named.
        self.assertIn("E36", section)
        self.assertIn("E9, E14 and E15", section)
        self.assertIn("add the root file as a file source instead", section)

    def test_zcode_docs_name_the_documented_catalog_and_flag_the_fallback(self):
        docs = {
            ".zcode-plugin/README.md": (REPO / ".zcode-plugin" / "README.md").read_text(encoding="utf-8"),
            "docs/runtime-adapter.md#ZCode": runtime_adapter_section("ZCode adapter"),
            "docs/zcode-runtime-adapter.md": (REPO / "docs" / "zcode-runtime-adapter.md").read_text(encoding="utf-8"),
        }
        for name, text in docs.items():
            flat = " ".join(text.split())
            self.assertIn("zcode.z.ai/en/docs/plugin", flat, name)
            self.assertIn("2026-11-21", flat, name)
            self.assertIn("root `marketplace.json`", flat, name)
            self.assertIn("is undocumented", flat, name)
        cn = (REPO / ".zcode-plugin" / "README_CN.md").read_text(encoding="utf-8")
        self.assertIn("2026-11-21", cn)
        self.assertIn("文档未记载", cn)


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
            self.assertEqual(len(hook["args"]), 2)
            self.assertRegex(hook["args"][0], r"^\$\{ZCODE_PLUGIN_ROOT\}/hooks/[a-z-]+\.mjs$")
            # The literal second element flips the shared scripts to ZCode
            # output mode (hooks/hook-output.mjs) independently of env-var
            # injection: runtime detection must not hinge on one mechanism.
            self.assertEqual(hook["args"][1], "--zcode-runtime")
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

    def test_adapter_readmes_document_marketplace_install(self):
        # A marketplace download is the product path: both READMEs must name the
        # GitHub marketplace source, not only the maintainer's local clone.
        for name in ("README.md", "README_CN.md"):
            text = (REPO / ".zcode-plugin" / name).read_text(encoding="utf-8")
            for marker in ("MrBekoX/agentic-sdlc", "GitHub"):
                self.assertIn(marker, text, f".zcode-plugin/{name} missing {marker}")

    def test_adapter_status_is_recorded_not_promoted(self):
        adapter = (REPO / "docs" / "runtime-adapter.md").read_text(encoding="utf-8")
        self.assertIn("ZCode", adapter)
        self.assertIn("experimental", adapter.lower())
        self.assertIn("not a 0.4.3 release target", adapter)


class TestZcodeNativeHookEvidenceIsRecorded(unittest.TestCase):
    """Hook registration and delivery of all five ZCode declarations were observed natively with
    the agent CLI 0.16.9 of ZCode desktop 3.14.5 (compatibility matrix E34, E35), and the GitHub
    marketplace source's catalog lookup was recorded (E36); the docs must say so."""

    def docs(self):
        return {
            ".zcode-plugin/README.md": (REPO / ".zcode-plugin" / "README.md").read_text(encoding="utf-8"),
            "docs/runtime-adapter.md#ZCode": runtime_adapter_section("ZCode adapter"),
            "docs/zcode-runtime-adapter.md": (REPO / "docs" / "zcode-runtime-adapter.md").read_text(encoding="utf-8"),
        }

    def test_docs_cite_the_native_hook_evidence(self):
        for name, text in self.docs().items():
            flat = " ".join(text.split())
            for marker in ("E34", "E35", "E36", "runnable", "local OpenAI-compatible"):
                self.assertIn(marker, flat, f"{name} missing {marker}")
        cn = (REPO / ".zcode-plugin" / "README_CN.md").read_text(encoding="utf-8")
        for marker in ("E34", "E35", "E36"):
            self.assertIn(marker, cn)

    def test_docs_no_longer_call_hook_delivery_unverified(self):
        for name, text in self.docs().items():
            flat = " ".join(text.split())
            for stale in ("Native display and invocation remain unverified",
                          "Native delivery/display remains unverified",
                          "actual hook delivery and model behavior remain unverified",
                          "does not cover the desktop GUI flow, hook execution"):
                self.assertNotIn(stale, flat, f"{name} still says: {stale}")

    def test_matrix_records_the_zcode_rows(self):
        log = (REPO / "docs" / "publication" / "compatibility-matrix.md").read_text(encoding="utf-8")
        log = log.split("## Evidence log", 1)[1]
        rows = {r.split("|")[1].strip(): r for r in log.splitlines() if r.startswith("| E")}
        for row_id, result in (("E34", "hook_registration=passed"), ("E35", "hook_delivery=passed"),
                               ("E36", "catalog_lookup=recorded")):
            self.assertIn(row_id, rows)
            self.assertIn("ZCode", rows[row_id])
            self.assertIn("agent CLI 0.16.9", rows[row_id])
            self.assertIn(result, rows[row_id])


class TestZcodeSkillAdapters(unittest.TestCase):
    """Skill-level ZCode runtime adapter locks (docs/zcode-runtime-adapter.md)."""

    def test_runtime_adapter_doc_records_the_capability_map(self):
        text = (REPO / "docs" / "zcode-runtime-adapter.md").read_text(encoding="utf-8")
        for fact in (
            "Goal Mode",
            "${ZCODE_PLUGIN_ROOT}",
            "spec-plan-draft",
            "agents/*.md",
            "not a 0.4.3 release target",
            # The launch tool the runner's ZCode card prints (runner contract §10, design §5.9.2,
            # the 2026-10-22 platform research), with the two rules that gate it.
            "`CreateWorkflow`",
            "only when the user explicitly asks",
            "Auto permission mode denies",
            "--engine zcode-dwf --json",
            "sdlc loop-record",
            "**UNVERIFIED** until a live ZCode run",
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
        # The skill's ZCode row keeps the workflow tier out of the defaults: the runner prints the
        # workflow launch only on the user's explicit request.
        zcode_line = next(ln for ln in text.splitlines() if "ZCode (experimental adapter)" in ln)
        self.assertIn("unavailable", zcode_line)

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
                             ".worktrees/other-checkout/workflows/zcode/spec-plan-draft.dwf.ts",
                             ".claude/worktrees/other-checkout/workflows/zcode/spec-plan-draft.dwf.ts",
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
        # The driver's behaviour is tested in test_zcode_driver.py; this pins its shape.
        text = (REPO / "workflows" / "zcode" / "spec-plan-draft.dwf.ts").read_text(encoding="utf-8")
        self.assertIn("zcode-workflow", text)
        self.assertIn("agent(", text)
        self.assertIn("phase(", text)
        self.assertIn("world.run(", text)
        # A new actor for every card, the critic included: a reused actor is not fresh.
        self.assertIn("const actor = agent(", text.split("for (let asked = 0;", 1)[1])
        # Negative lock: the Claude JS facade must not leak into the ZCode port. Without this a
        # copy of workflows/spec-plan-draft.js would satisfy every positive assertion above.
        for claude_token in ("export const meta", "agentType:", "isolation:", "pipeline("):
            self.assertNotIn(claude_token, text, f"Claude facade token {claude_token} in a ZCode port")
        # The header declares the args the body reads; a rename in one half must fail here.
        header = text.split("*/", 1)[0]
        for arg in ("slug", "pluginRoot", "python", "maxRounds"):
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

    def test_the_launch_tool_is_named_where_the_runner_prints_it(self):
        # The 2026-10-22 platform research sourced the ZCode launch tool; the runner's card prints
        # it and the adapter docs explain when ZCode allows it (replacing the earlier sweep that
        # forbade the name while it had no source).
        source = (REPO / "scripts" / "sdlc_runner" / "loop.py").read_text(encoding="utf-8")
        self.assertIn('line = "CreateWorkflow " + dumps_json(', source)
        for rel in ("docs/zcode-runtime-adapter.md", ".zcode-plugin/README.md", ".zcode-plugin/README_CN.md"):
            with self.subTest(doc=rel):
                self.assertIn("`CreateWorkflow`", (REPO / rel).read_text(encoding="utf-8"))

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
