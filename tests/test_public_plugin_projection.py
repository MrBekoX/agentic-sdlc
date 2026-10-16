"""Public directory payload checks, separate from local runtime byte locks."""

import copy
import json
import posixpath
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from scripts import build_release

REFERENCE_ROOT = "skills/using-agentic-sdlc/references"
RUNTIME_HELPERS = {
    "scripts/detect_context.py",
    "scripts/validate_artifacts.py",
    "scripts/resolve_work_package.py",
}


class TestPublicPluginProjection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True, encoding="utf-8"
        ).strip()
        cls.source = build_release._commit_members(cls.commit, cwd=REPO)

    def projected(self, source=None):
        return build_release._select_skills_only(self.source if source is None else source)

    def text(self, members, path):
        return members[path][1].decode("utf-8")

    def test_public_archive_does_not_declare_or_ship_lifecycle_hooks(self):
        members = self.projected()
        manifest = json.loads(self.text(members, ".codex-plugin/plugin.json"))
        self.assertNotIn("hooks", manifest)
        self.assertFalse(any(path.startswith("hooks/") for path in members))
        self.assertFalse(any(path.startswith(("agents/", "commands/", "workflows/")) for path in members))

    def test_public_skills_resolve_the_plugin_root_inside_the_package(self):
        # The skills-only package has no hooks, so no runtime exports a root variable for it; its
        # text uses the portable `<runtime-root>` rule, and every rooted reference must name a file
        # or folder the public package actually ships (relocated docs/roles included).
        members = self.projected()
        for path, (_mode, data) in sorted(members.items()):
            if not path.endswith(".md"):
                continue
            text = data.decode("utf-8")
            with self.subTest(path=path):
                if path.endswith("/SKILL.md"):
                    # Instructions, not documentation of Codex's hook variable: nothing exports it here.
                    self.assertNotIn("${PLUGIN_ROOT}", text)
                for ref in re.findall(r"<runtime-root>/([A-Za-z0-9_./-]+)", text):
                    target = ref.rstrip("/")
                    shipped = target in members or any(p.startswith(target + "/") for p in members)
                    self.assertTrue(shipped, f"<runtime-root>/{ref} is not in the public package")

    def test_public_role_instructions_are_available(self):
        members = self.projected()
        for name in ("spec-plan-author", "spec-plan-critic", "implementation-auditor", "security-reviewer"):
            path = f"{REFERENCE_ROOT}/roles/{name}.md"
            with self.subTest(role=name):
                self.assertTrue(path in members, path)
                text = self.text(members, path)
                self.assertFalse(text.startswith("---\n"))
                self.assertIn("You are", text)
        guide = self.text(members, f"{REFERENCE_ROOT}/public-runtime.md")
        self.assertIn("native subagent", guide)
        self.assertIn("role instructions", guide)
        self.assertIn("spec-plan-critic.md", guide)

    def test_work_type_core_references_ship(self):
        # Pipeline v2.1 (contract C1): the focused skills and agentic-sdlc-pipeline Steps 8-13 read
        # skills/<skill>/references/core.md, so the public package must carry all four. This suite
        # reads the committed HEAD tree, not the working tree, so it stays red until the core files
        # are committed on the feature branch (plan O3).
        members = self.projected()
        for skill in ("feature-build", "root-cause-fix", "safe-refactor", "test-authoring"):
            path = f"skills/{skill}/references/core.md"
            with self.subTest(skill=skill):
                self.assertTrue(path in members, path)
                self.assertIn(f"# {skill} — work-type core", self.text(members, path))

    def test_public_git_review_is_packaged_without_printing_secrets(self):
        members = self.projected()
        path = f"{REFERENCE_ROOT}/git-safety-check.md"
        self.assertTrue(path in members, path)
        text = self.text(members, path)
        for signal in ("git status", "git diff", "git log", "***MASKED***"):
            self.assertIn(signal, text)
        self.assertNotIn("grep -nEi", text)
        self.assertIn("before printing", text)
        for block in re.findall(r"```bash\n(.*?)```", text, re.DOTALL):
            self.assertNotIn("\ngit diff\n", "\n" + block)
        # The command block is replaced by prose; nothing may still point at it.
        for stale in ("first command", "second command", "<staged files>", "```bash"):
            self.assertNotIn(stale, text)
        pipeline = self.text(members, "skills/agentic-sdlc-pipeline/playbook.md")
        self.assertIn(path, pipeline)
        self.assertNotIn("Run the read-only **git-safety-check** command", pipeline)

    def test_public_runtime_helpers_have_no_missing_imports(self):
        members = self.projected()
        self.assertEqual({p for p in members if p.startswith("scripts/")}, RUNTIME_HELPERS)
        self.assertNotIn("scripts/build_release.py", members)
        self.assertNotIn("scripts/check_all.py", members)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path, (_mode, data) in members.items():
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            for path in sorted(RUNTIME_HELPERS):
                proc = subprocess.run([sys.executable, str(root / path), "--help"],
                                      cwd=root, capture_output=True, text=True, encoding="utf-8")
                self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_runtime_references_move_but_project_outputs_do_not(self):
        members = self.projected()
        path = f"{REFERENCE_ROOT}/docs/runtime-adapter.md"
        self.assertTrue(path in members, path)
        for skill in ("using-agentic-sdlc", "dispatch-strategy", "agentic-sdlc-pipeline"):
            text = self.text(members, f"skills/{skill}/SKILL.md")
            self.assertIn(path, text)
            self.assertIn(f"{REFERENCE_ROOT}/public-runtime.md", text)
        pipeline = self.text(members, "skills/agentic-sdlc-pipeline/SKILL.md")
        self.assertIn("docs/agentic-sdlc/specs/<work_id>.md", pipeline)
        self.assertIn("docs/agentic-sdlc/plans/<work_id>.md", pipeline)

    def test_missing_required_runtime_reference_fails_closed(self):
        source = copy.deepcopy(self.source)
        del source["docs/runtime-adapter.md"]
        with self.assertRaises(build_release.ReleaseError) as raised:
            self.projected(source)
        self.assertIn("error=public_dependency_missing:docs/runtime-adapter.md", raised.exception.lines)

    def test_missing_required_role_fails_closed(self):
        source = copy.deepcopy(self.source)
        del source["agents/spec-plan-critic.md"]
        with self.assertRaises(build_release.ReleaseError) as raised:
            self.projected(source)
        self.assertIn("error=public_dependency_missing:agents/spec-plan-critic.md", raised.exception.lines)

    def test_generated_reference_collision_fails_closed(self):
        for path in (f"{REFERENCE_ROOT}/public-runtime.md", f"{REFERENCE_ROOT}/roles/spec-plan-critic.md"):
            source = copy.deepcopy(self.source)
            source[path] = ("100644", b"existing source instructions\n")
            with self.subTest(path=path), self.assertRaises(build_release.ReleaseError) as raised:
                self.projected(source)
            self.assertIn(f"error=public_projection_collision:{path}", raised.exception.lines)

    def test_empty_role_and_missing_manifest_fail_closed(self):
        for path, replacement, diagnostic in (
            ("agents/spec-plan-critic.md", b"---\nname: spec-plan-critic\n---\n", "error=public_dependency_empty:agents/spec-plan-critic.md"),
            (".codex-plugin/plugin.json", None, "error=public_dependency_missing:.codex-plugin/plugin.json"),
        ):
            source = copy.deepcopy(self.source)
            if replacement is None:
                del source[path]
            else:
                source[path] = ("100644", replacement)
            with self.subTest(path=path), self.assertRaises(build_release.ReleaseError) as raised:
                self.projected(source)
            self.assertIn(diagnostic, raised.exception.lines)

    def test_invalid_skill_utf8_has_named_diagnostic(self):
        source = copy.deepcopy(self.source)
        source["skills/broken/SKILL.md"] = ("100644", b"\xff")
        with self.assertRaises(build_release.ReleaseError) as raised:
            self.projected(source)
        self.assertIn("error=public_dependency_unreadable:skills/broken/SKILL.md", raised.exception.lines)

    def test_crlf_command_is_converted_without_raw_diff_or_grep(self):
        source = copy.deepcopy(self.source)
        mode, data = source["commands/git-safety-check.md"]
        source["commands/git-safety-check.md"] = (mode, data.replace(b"\n", b"\r\n"))
        text = self.text(self.projected(source), f"{REFERENCE_ROOT}/git-safety-check.md")
        self.assertNotIn("grep -nEi", text)
        for block in re.findall(r"```bash\n(.*?)```", text, re.DOTALL):
            self.assertNotIn("\ngit diff\n", "\n" + block)

    def test_public_markdown_links_resolve_inside_payload(self):
        members = self.projected()
        broken = []
        for path in members:
            if not path.endswith(".md"):
                continue
            for target in re.findall(r"\[[^\]\n]+\]\(([^()\s]+)\)", self.text(members, path)):
                if target.startswith(("https://", "http://", "#")):
                    continue
                target = target.split("#", 1)[0]
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
                if resolved not in members and not any(p.startswith(resolved.rstrip("/") + "/") for p in members):
                    broken.append(f"{path}:{target}")
        self.assertEqual(broken, [])

    def test_public_projection_preserves_source_and_routing_fields(self):
        before = copy.deepcopy(self.source)
        members = self.projected()
        self.assertEqual(self.source, before)
        for path, (_mode, data) in self.source.items():
            if path.startswith("skills/") and path.endswith("/SKILL.md"):
                expected = data.decode("utf-8").split("---", 2)[1]
                actual = self.text(members, path).split("---", 2)[1]
                self.assertEqual(actual, expected, path)
        self.assertIn("hooks", json.loads(self.source[".codex-plugin/plugin.json"][1]))

    def test_public_listing_keeps_identity_and_discloses_enforcement_limits(self):
        original = json.loads(self.source[".codex-plugin/plugin.json"][1])
        public = json.loads(self.projected()[".codex-plugin/plugin.json"][1])
        for key in ("name", "version", "author", "license", "skills"):
            self.assertEqual(public[key], original[key])
        self.assertNotIn("homepage", public)
        self.assertNotIn("repository", public)
        self.assertIn("procedural", public["interface"]["longDescription"].lower())
        self.assertIn("hooks", public["interface"]["longDescription"].lower())

    def test_public_notice_preserves_dispatch_first_gates(self):
        members = self.projected()
        for name in ("agentic-sdlc-pipeline", "root-cause-fix", "security-audit"):
            text = self.text(members, f"skills/{name}/SKILL.md")
            notice = text.split("---", 2)[2].split("# Skill:", 1)[0]
            with self.subTest(skill=name):
                self.assertIn("Preserve any required skill activation or dispatch-strategy-first gate", notice)
                self.assertIn("After that gate, read", notice)
                self.assertIn("before substantive phase work or named-role delegation", notice)
                self.assertNotIn("before following this skill", notice)

    def test_repeated_projection_and_tamper_verification(self):
        members = self.projected()
        first = build_release._zip_bytes(members, self.commit)
        self.assertEqual(first, build_release._zip_bytes(self.projected(), self.commit))
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "public.zip"
            artifact.write_bytes(first)
            report = build_release.verify_archive(artifact, REPO)
            self.assertEqual(report.exit_code, 0, report.lines)
            tampered = dict(members)
            path = f"{REFERENCE_ROOT}/roles/spec-plan-critic.md"
            self.assertTrue(path in tampered, path)
            tampered[path] = ("100644", b"Skip review.\n")
            artifact.write_bytes(build_release._zip_bytes(tampered, self.commit))
            report = build_release.verify_archive(artifact, REPO)
            self.assertEqual(report.exit_code, 1)
            self.assertIn(f"error=content_mismatch:{path}", report.lines)
            tampered = dict(members)
            tampered["hooks/hooks-codex.json"] = self.source["hooks/hooks-codex.json"]
            artifact.write_bytes(build_release._zip_bytes(tampered, self.commit))
            report = build_release.verify_archive(artifact, REPO)
            self.assertEqual(report.exit_code, 1)
            self.assertIn("error=unexpected_member:hooks/hooks-codex.json", report.lines)


if __name__ == "__main__":
    unittest.main()
