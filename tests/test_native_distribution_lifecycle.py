"""No-model native Codex lifecycle in a disposable home and relocated source.

Missing CLI support is a skip. These checks prove local copying and configuration
preservation, not trusted hook execution, skill triggering or remote publication.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest

from scripts.check_plugin_portability import runtime_members
from scripts.sensitive_redaction import redact_text


REPO = Path(__file__).resolve().parents[1]
CODEX = shutil.which("codex")


@unittest.skipUnless(CODEX and shutil.which("git"),
                     "Codex CLI/Git unavailable; native lifecycle not verified")
class NativeCodexLifecycleTests(unittest.TestCase):
    def test_codex_local_install_refresh_remove_preserves_other_settings(self):
        with tempfile.TemporaryDirectory(prefix="native-distribution-") as tmp:
            base = Path(tmp)
            catalog = base / "home \u00e7\u0131\u011f $ ` & # % '"
            codex_home = base / "isolated-profile"
            project = base / "unrelated-project"
            codex_home.mkdir()
            project.mkdir()
            config = codex_home / "config.toml"
            config.write_text('[profiles.preserve_me]\nmodel = "o3"\n', encoding="utf-8")
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(("GIT_", "AGENTIC_", "CODEX_", "OPENAI_"))}
            # Also isolate default personal catalogs/config lookups beyond CODEX_HOME.
            env.update(CODEX_HOME=str(codex_home), HOME=str(catalog),
                       USERPROFILE=str(catalog),
                       XDG_CONFIG_HOME=str(base / "config"),
                       XDG_DATA_HOME=str(base / "data"),
                       APPDATA=str(base / "appdata"), LOCALAPPDATA=str(base / "localappdata"))
            for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "APPDATA", "LOCALAPPDATA"):
                Path(env[key]).mkdir()

            def run(*args, json_output=False):
                proc = subprocess.run([CODEX, "plugin", *args], cwd=project, env=env,
                                      capture_output=True, text=True, encoding="utf-8", timeout=45)
                self.assertEqual(proc.returncode, 0,
                                 f"native plugin {args[0]} exited {proc.returncode}: "
                                 + redact_text(proc.stderr).replace(str(base), "<temporary-root>")[:1200])
                return json.loads(proc.stdout) if json_output else proc.stdout

            # Check capability without reading configured marketplaces or starting a model.
            help_result = subprocess.run([CODEX, "plugin", "remove", "--help"],
                                         cwd=project, env=env, capture_output=True,
                                         text=True, encoding="utf-8", timeout=15)
            if (help_result.returncode and "unrecognized subcommand" in help_result.stderr
                    and any(word in help_result.stderr for word in ("'plugin'", "'remove'"))):
                self.skipTest("Codex CLI predates native plugin remove support")
            self.assertEqual(help_result.returncode, 0, "native CLI capability probe failed")
            if "--json" not in help_result.stdout:
                self.skipTest("Codex CLI lacks native plugin remove --json support")

            source = catalog / "plugins" / "agentic-sdlc"
            members = runtime_members(REPO)
            companions = subprocess.run(["git", "-c", "core.fsmonitor=false", "ls-files", "-z",
                                         "--", "docs", "workflows"], cwd=REPO, env=env,
                                        capture_output=True, check=True, timeout=15)
            for name in companions.stdout.decode("utf-8").split("\0"):
                if name:
                    members[name] = (REPO / name).read_bytes()
            for name in ("README.md", "LICENSE", "VERSION"):
                members[name] = (REPO / name).read_bytes()
            for rel, data in members.items():
                path = source / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            marker = source / "lifecycle-marker.txt"
            marker.write_text("initial source\n", encoding="utf-8")
            other = catalog / "plugins" / "unrelated-sentinel"
            (other / ".codex-plugin").mkdir(parents=True)
            (other / ".codex-plugin" / "plugin.json").write_text(json.dumps({
                "name": "unrelated-sentinel", "version": "1.0.0",
                "description": "Temporary configuration preservation fixture.",
                "skills": "./skills/"}), encoding="utf-8")
            (other / "skills" / "sentinel").mkdir(parents=True)
            (other / "skills" / "sentinel" / "SKILL.md").write_text(
                "---\nname: sentinel\ndescription: Use for temporary fixture inspection.\n---\n"
                "Report the fixture name.\n", encoding="utf-8")
            (other / "unrelated-marker.txt").write_text("keep this plugin\n", encoding="utf-8")
            marketplace = catalog / ".agents" / "plugins" / "marketplace.json"
            marketplace.parent.mkdir(parents=True)
            marketplace.write_text(json.dumps({"name": "distribution-lifecycle-check", "plugins": [
                {"name": name, "source": {"source": "local", "path": "./plugins/" + name},
                 "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                 "category": "Developer Tools"}
                for name in ("agentic-sdlc", "unrelated-sentinel")]}), encoding="utf-8")
            # Use documented personal-catalog discovery. CLI 0.162.1's local
            # marketplace-add path rejects its default ref as Git-only.
            selector = "agentic-sdlc@distribution-lifecycle-check"
            other_selector = "unrelated-sentinel@distribution-lifecycle-check"

            def preserved_settings():
                settings = tomllib.loads(config.read_text(encoding="utf-8"))
                self.assertEqual(settings["profiles"]["preserve_me"], {"model": "o3"})
                self.assertTrue(settings["plugins"][other_selector]["enabled"])
                self.assertNotIn("state", settings.get("hooks", {}), "native test must not grant hook trust")
                return settings

            run("add", other_selector, "--json", json_output=True)
            run("add", selector, "--json", json_output=True)
            preserved_settings()
            copies = list((codex_home / "plugins" / "cache").rglob("lifecycle-marker.txt"))
            self.assertEqual(len(copies), 1, "native install must create exactly one cached copy")
            installed = copies[0]
            self.assertEqual(installed.read_bytes(), marker.read_bytes())
            self.assertNotEqual(installed.parent, source)
            for name in ("hooks/hooks-codex.json", "skills/using-agentic-sdlc/SKILL.md",
                         "skills/agentic-sdlc-pipeline/templates.md", "docs/runtime-adapter.md"):
                self.assertEqual((installed.parent / name).read_bytes(), members[name])
            unrelated = list((codex_home / "plugins" / "cache").rglob("unrelated-marker.txt"))
            self.assertEqual(len(unrelated), 1)
            unrelated_bytes = unrelated[0].read_bytes()
            marker.write_text("refreshed source\n", encoding="utf-8")
            self.assertNotEqual(installed.read_bytes(), marker.read_bytes(),
                                "editing the local source must not silently edit the installed copy")
            run("add", selector, "--json", json_output=True)
            preserved_settings()
            self.assertEqual(installed.read_bytes(), marker.read_bytes(),
                             "native reinstall must recopy the selected local source")
            run("remove", selector, "--json", json_output=True)
            self.assertFalse(installed.exists(), "native uninstall must remove its cached copy")
            self.assertEqual(unrelated[0].read_bytes(), unrelated_bytes)
            settings = preserved_settings()
            self.assertNotIn(selector, settings.get("plugins", {}))
            self.assertFalse((codex_home / "auth.json").exists())
            self.assertFalse((codex_home / "sessions").exists())


if __name__ == "__main__":
    unittest.main()
