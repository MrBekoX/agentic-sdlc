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
ANTIGRAVITY_MANIFEST_KEYS = frozenset({"name", "description"})
ANTIGRAVITY_NAME_RE = re.compile(r"^[a-zA-Z0-9-_]+$")
RUNTIME_ROOT_REF_RE = re.compile(r"<runtime-root>/([A-Za-z0-9_./-]+)")


def antigravity_manifest_violations(manifest):
    """Validate against https://antigravity.google/schemas/v1/plugin.json (additionalProperties: false)."""
    if not isinstance(manifest, dict):
        return ["manifest_not_object"]
    violations = []
    extra = sorted(set(manifest) - ANTIGRAVITY_MANIFEST_KEYS)
    missing = sorted(ANTIGRAVITY_MANIFEST_KEYS - set(manifest))
    if extra:
        violations.extend(f"unsupported_key:{key}" for key in extra)
    if missing:
        violations.extend(f"missing_key:{key}" for key in missing)
    name = manifest.get("name")
    if not isinstance(name, str) or not ANTIGRAVITY_NAME_RE.fullmatch(name):
        violations.append("invalid_name")
    description = manifest.get("description")
    if not isinstance(description, str) or not description.strip():
        violations.append("invalid_description")
    return violations


class TestAntigravityPackaging(unittest.TestCase):
    def setUp(self):
        self.manifest_path = REPO / ".antigravity-plugin" / "plugin.json"
        self.readme_path = REPO / ".antigravity-plugin" / "README.md"
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.readme = self.readme_path.read_text(encoding="utf-8")

    def test_manifest_conforms_to_strict_antigravity_schema(self):
        self.assertEqual(antigravity_manifest_violations(self.manifest), [])
        self.assertEqual(set(self.manifest.keys()), {"name", "description"})
        self.assertEqual(self.manifest["name"], "agentic-sdlc")
        self.assertNotIn("Claude Code skill library", self.manifest["description"])
        raw = self.manifest_path.read_bytes()
        self.assertNotIn(b"\r", raw)
        self.assertTrue(raw.endswith(b"\n"))

    def test_manifest_validator_rejects_extra_or_invalid_fields(self):
        self.assertIn(
            "unsupported_key:version",
            antigravity_manifest_violations({**self.manifest, "version": "0.5.0"}),
        )
        self.assertIn(
            "unsupported_key:skills",
            antigravity_manifest_violations({**self.manifest, "skills": "./skills/"}),
        )
        self.assertIn(
            "invalid_name",
            antigravity_manifest_violations({**self.manifest, "name": "bad name!"}),
        )
        self.assertIn(
            "missing_key:description",
            antigravity_manifest_violations({"name": "agentic-sdlc"}),
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
            for dirname in ("skills", "contracts", "scripts", "assets", "commands", "workflows"):
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
