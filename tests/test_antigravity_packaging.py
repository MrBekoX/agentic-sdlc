"""Packaging, schema, staging, and documentation regression tests for the experimental Google Antigravity adapter."""
from pathlib import Path
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
# https://antigravity.google/schemas/v1/plugin.json (agy 1.5.14 bundled build-plugins.md, read
# 2026-11-21): `required: ["name"]`, `additionalProperties: false`, and these properties.
ANTIGRAVITY_SCHEMA_KEYS = frozenset({
    "$schema", "name", "displayName", "description", "version", "disabled", "logo", "suggestedPrompts",
    "skills", "author", "homepage", "repository", "license", "keywords", "extensions",
})
# The keys this adapter's manifest carries (the documented metadata keys, versioned from VERSION).
ANTIGRAVITY_MANIFEST_KEYS = frozenset({
    "name", "displayName", "version", "description", "author", "homepage", "repository", "license",
    "keywords", "logo",
})
ANTIGRAVITY_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
RUNTIME_ROOT_REF_RE = re.compile(r"<runtime-root>/([A-Za-z0-9_./-]+)")


def antigravity_manifest_violations(manifest):
    """Validate against https://antigravity.google/schemas/v1/plugin.json (additionalProperties: false)."""
    if not isinstance(manifest, dict):
        return ["manifest_not_object"]
    violations = [f"unsupported_key:{key}" for key in sorted(set(manifest) - ANTIGRAVITY_SCHEMA_KEYS)]
    name = manifest.get("name")
    if not isinstance(name, str) or not ANTIGRAVITY_NAME_RE.fullmatch(name):
        violations.append("invalid_name")
    for key in ("displayName", "description", "version", "logo", "homepage", "repository", "license"):
        if key in manifest and (not isinstance(manifest[key], str) or not manifest[key].strip()):
            violations.append(f"invalid_{key}")
    author = manifest.get("author")
    if author is not None and not (isinstance(author, str) or (
            isinstance(author, dict) and set(author) <= {"name", "email", "url"}
            and all(isinstance(v, str) for v in author.values()))):
        violations.append("invalid_author")
    keywords = manifest.get("keywords")
    if keywords is not None and not (isinstance(keywords, list) and all(isinstance(k, str) for k in keywords)):
        violations.append("invalid_keywords")
    return violations


class TestAntigravityPackaging(unittest.TestCase):
    def setUp(self):
        self.manifest_path = REPO / ".antigravity-plugin" / "plugin.json"
        self.readme_path = REPO / ".antigravity-plugin" / "README.md"
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.readme = self.readme_path.read_text(encoding="utf-8")

    def test_manifest_conforms_to_the_antigravity_schema_and_carries_the_version(self):
        self.assertEqual(antigravity_manifest_violations(self.manifest), [])
        self.assertEqual(set(self.manifest), ANTIGRAVITY_MANIFEST_KEYS)
        self.assertEqual(self.manifest["name"], "agentic-sdlc")
        self.assertEqual(self.manifest["displayName"], "Agentic SDLC")
        self.assertEqual(self.manifest["version"], (REPO / "VERSION").read_text(encoding="utf-8").strip())
        self.assertEqual(self.manifest["logo"], "assets/logo.png")
        self.assertTrue((REPO / self.manifest["logo"]).is_file())
        self.assertEqual(set(self.manifest["author"]), {"name", "url"})
        self.assertNotIn("Claude Code skill library", self.manifest["description"])
        for word in ("Antigravity", "Gemini", "Claude", "Cursor"):
            self.assertFalse(self.manifest["displayName"].startswith(word))
        raw = self.manifest_path.read_bytes()
        self.assertNotIn(b"\r", raw)
        self.assertTrue(raw.endswith(b"\n"))
        # bump_version.py rewrites the manifest with json.dumps(indent=2); keep the committed bytes in that form.
        self.assertEqual(raw.decode("utf-8"), json.dumps(self.manifest, indent=2, ensure_ascii=False) + "\n")

    def test_manifest_validator_rejects_extra_or_invalid_fields(self):
        self.assertEqual(antigravity_manifest_violations({**self.manifest, "version": "0.5.0"}), [])
        self.assertIn(
            "unsupported_key:hooks",
            antigravity_manifest_violations({**self.manifest, "hooks": "./hooks.json"}),
        )
        self.assertIn(
            "unsupported_key:interface",
            antigravity_manifest_violations({**self.manifest, "interface": {}}),
        )
        self.assertIn(
            "invalid_name",
            antigravity_manifest_violations({**self.manifest, "name": "Bad_Name"}),
        )
        self.assertIn(
            "invalid_author",
            antigravity_manifest_violations({**self.manifest, "author": {"name": "x", "twitter": "y"}}),
        )

    def test_root_plugin_json_and_default_hooks_json_remain_absent(self):
        self.assertFalse((REPO / "plugin.json").exists())
        self.assertFalse((REPO / "hooks" / "hooks.json").exists())

    def test_staged_antigravity_plugin_resolves_runtime_root_and_runs_helpers(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "consumer-workspace"
            plugin_root = workspace / ".agents" / "plugins" / "agentic-sdlc"
            plugin_root.mkdir(parents=True)

            shutil.copy2(self.manifest_path, plugin_root / "plugin.json")
            for dirname in ("skills", "contracts", "scripts", "flows", "assets", "commands", "workflows"):
                shutil.copytree(REPO / dirname, plugin_root / dirname)
            (plugin_root / "docs").mkdir(parents=True, exist_ok=True)
            for doc_name in ("runtime-adapter.md", "zcode-runtime-adapter.md"):
                shutil.copy2(REPO / "docs" / doc_name, plugin_root / "docs" / doc_name)
            (plugin_root / "agents").mkdir(parents=True, exist_ok=True)
            for agent_md in (REPO / "agents").glob("*.md"):
                shutil.copy2(agent_md, plugin_root / "agents" / agent_md.name)

            staged_skills = sorted((plugin_root / "skills").glob("*/SKILL.md"))
            self.assertEqual(len(staged_skills), 16)

            for skill_md in staged_skills:
                resolved_root = skill_md.parent.parent.parent
                self.assertEqual(resolved_root, plugin_root)
                text = skill_md.read_text(encoding="utf-8")
                for match in RUNTIME_ROOT_REF_RE.finditer(text):
                    rel = match.group(1).rstrip(".,;:")
                    target = resolved_root / rel
                    with self.subTest(skill=skill_md.parent.name, ref=rel):
                        self.assertTrue(target.exists(), f"Unresolved <runtime-root>/{rel} in {skill_md}")

            project_dir = workspace / "app"
            project_dir.mkdir(parents=True)
            proc = subprocess.run(
                [sys.executable, str(plugin_root / "scripts" / "detect_context.py"), "--path", str(project_dir)],
                cwd=project_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("context_detection=greenfield", proc.stdout)

    def test_antigravity_adapter_docs_and_skills_preserve_contracts(self):
        for required in (
            "https://antigravity.google/schemas/v1/plugin.json",
            "`additionalProperties`: `false`",
            "invoke_subagent",
            "October 19, 2026",
            "Not a supported release target",
            "hooks.json",
            # The staging commands copy the runner's flows/ next to scripts/, as the staged-plugin test does.
            'cp -R skills contracts scripts flows assets commands LICENSE "$TARGET/"',
            '@("skills", "contracts", "scripts", "flows", "assets", "commands", "LICENSE")',
        ):
            with self.subTest(readme_required=required):
                self.assertIn(required, self.readme)

        runtime_adapter = (REPO / "docs" / "runtime-adapter.md").read_text(encoding="utf-8")
        for required in (
            "## Google Antigravity adapter (experimental — not a supported release target)",
            "VERSIONLESS_PLUGIN_MANIFESTS",
            "invoke_subagent",
            "October 19, 2026",
            "toolCall",
        ):
            with self.subTest(runtime_adapter_required=required):
                self.assertIn(required, runtime_adapter)

        router = (REPO / "skills" / "using-agentic-sdlc" / "SKILL.md").read_text(encoding="utf-8")
        dispatch = (REPO / "skills" / "dispatch-strategy" / "SKILL.md").read_text(encoding="utf-8")
        pipeline = (REPO / "skills" / "agentic-sdlc-pipeline" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("In Google Antigravity (experimental adapter)", router)
        self.assertIn("invoke_subagent", dispatch)
        self.assertIn("invoke_subagent", pipeline)
        self.assertIn("October 19, 2026", pipeline)


if __name__ == "__main__":
    unittest.main()
