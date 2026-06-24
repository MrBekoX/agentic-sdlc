import json
import subprocess
import sys
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


class TestPackagingMetadata(unittest.TestCase):
    def test_plugin_manifests_exist_and_match_version(self):
        version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
        plugin = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        marketplace = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        codex_plugin = json.loads((REPO / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin["name"], "agentic-sdlc")
        self.assertEqual(plugin["version"], version)
        self.assertEqual(plugin["hooks"], "./hooks/hooks-claude.json")
        self.assertEqual(marketplace["plugins"][0]["name"], "agentic-sdlc")
        self.assertEqual(marketplace["plugins"][0]["version"], version)
        self.assertEqual(marketplace["plugins"][0]["source"], "./")
        self.assertEqual(codex_plugin["name"], "agentic-sdlc")
        self.assertEqual(codex_plugin["version"], version)
        self.assertEqual(codex_plugin["skills"], "./skills/")
        self.assertEqual(codex_plugin["hooks"], "./hooks/hooks-codex.json")

    def test_marketplace_name_is_public_and_matches_readme(self):
        mp = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual(mp["name"], "mrbekox")
        self.assertNotIn("dev", mp["name"])
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("agentic-sdlc@mrbekox", readme)
        self.assertNotIn("agentic-sdlc@agentic-sdlc-dev", readme)

    def test_public_docs_match_current_version(self):
        version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
        docs = [
            REPO / "README.md",
            REPO / "docs" / "plugin-readme.md",
            REPO / "docs" / "release-readiness.md",
        ]
        for path in docs:
            text = path.read_text(encoding="utf-8")
            self.assertIn(version, text, f"{path.relative_to(REPO)} missing current version")
            self.assertNotIn("0.2.7", text, f"{path.relative_to(REPO)} still references old release")

    def test_runtime_readmes_use_canonical_work_package_paths(self):
        canonical = "docs/agentic-sdlc/"
        legacy = ("docs/specs/", "docs/plans/")
        for rel in (".claude-plugin/README.md", ".codex-plugin/README.md"):
            text = (REPO / rel).read_text(encoding="utf-8")
            self.assertIn(canonical, text)
            for old in legacy:
                self.assertNotIn(old, text, f"{rel} still uses legacy artifact path {old}")

    def test_codex_docs_use_current_personal_plugin_directory(self):
        docs = [
            REPO / "README.md",
            REPO / ".codex-plugin" / "README.md",
            REPO / "docs" / "troubleshooting.md",
        ]
        for path in docs:
            text = path.read_text(encoding="utf-8")
            rel = path.relative_to(REPO)
            self.assertIn(
                "~/.codex/plugins/agentic-sdlc",
                text,
                f"{rel} missing current Codex personal plugin path",
            )
            self.assertNotIn(
                "~/plugins/agentic-sdlc",
                text,
                f"{rel} still uses legacy Codex personal plugin path",
            )

    def test_codex_manifest_uses_publishable_schema_keys(self):
        codex_plugin = json.loads((REPO / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        allowed_keys = {
            "id",
            "name",
            "version",
            "description",
            "skills",
            "hooks",
            "apps",
            "mcpServers",
            "interface",
            "author",
            "homepage",
            "repository",
            "license",
            "keywords",
        }
        self.assertEqual(set(codex_plugin) - allowed_keys, set())

    def test_local_agent_instruction_files_are_not_tracked_plugin_payload(self):
        proc = subprocess.run(
            ["git", "ls-files"],
            cwd=REPO,
            capture_output=True,
            text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        tracked = set(proc.stdout.splitlines())
        self.assertNotIn("AGENTS.md", tracked)
        self.assertNotIn("CLAUDE.md", tracked)

    def test_plugin_components_do_not_depend_on_local_agent_instruction_files(self):
        component_roots = [
            ".claude-plugin",
            ".codex-plugin",
            "agents",
            "commands",
            "contracts",
            "hooks",
            "skills",
            "workflows",
        ]
        checked_suffixes = {".json", ".js", ".md", ".mjs", ".py"}
        forbidden = ("AGENTS.md", "CLAUDE.md")
        findings = []
        for root_name in component_roots:
            root = REPO / root_name
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix not in checked_suffixes:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                for token in forbidden:
                    if token in text:
                        findings.append(f"{path.relative_to(REPO)} references {token}")
        self.assertEqual(findings, [])

    def test_plugin_components_do_not_hardcode_legacy_skill_creator_path(self):
        component_roots = [
            ".claude-plugin",
            ".codex-plugin",
            "agents",
            "commands",
            "contracts",
            "hooks",
            "skills",
            "workflows",
        ]
        checked_suffixes = {".json", ".js", ".md", ".mjs", ".py"}
        legacy_path = "/".join(
            (
                "~",
                ".claude",
                "plugins",
                "marketplaces",
                "anthropic-agent-skills",
                "skills",
                "skill-creator",
            )
        )
        findings = []
        for root_name in component_roots:
            root = REPO / root_name
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix not in checked_suffixes:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                if legacy_path in text:
                    findings.append(f"{path.relative_to(REPO)} references legacy skill-creator path")
        self.assertEqual(findings, [])

    def test_version_check_script_passes(self):
        proc = subprocess.run(
            [sys.executable, "scripts/bump_version.py", "--check"],
            cwd=REPO,
            capture_output=True,
            text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("version_check=passed", proc.stdout)
