import json
import subprocess
import sys
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


class TestClaudePackagingMetadata(unittest.TestCase):
    def test_plugin_manifests_exist_and_match_version(self):
        version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
        plugin = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        marketplace = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        codex_plugin = json.loads((REPO / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin["name"], "agentic-sdlc")
        self.assertEqual(plugin["version"], version)
        self.assertEqual(marketplace["plugins"][0]["name"], "agentic-sdlc")
        self.assertEqual(marketplace["plugins"][0]["version"], version)
        self.assertEqual(marketplace["plugins"][0]["source"], "./")
        self.assertEqual(codex_plugin["name"], "agentic-sdlc")
        self.assertEqual(codex_plugin["version"], version)
        self.assertEqual(codex_plugin["skills"], "./skills/")
        self.assertEqual(codex_plugin["hooks"], "./hooks/hooks-codex.json")

    def test_version_check_script_passes(self):
        proc = subprocess.run(
            [sys.executable, "scripts/bump_version.py", "--check"],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("version_check=passed", proc.stdout)
