"""Role projection generator: one source (`agents/*.md`), one projection per runtime.

The Cursor projection must reproduce the committed `cursor/agents/` mirror byte for byte, and
`--check` must fail on a drifted mirror. The Antigravity projection must emit agy-native agents
(YAML-list `tools` of agy runtime names) with the role body unchanged.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import project_roles  # noqa: E402

GENERATOR = REPO / "scripts" / "project_roles.py"
AGY_READ = ["read_file", "search_web"]
AGY_WRITE_TOOLS = {"write_file", "edit_file", "run_command"}


def _run(*args, cwd=REPO):
    return subprocess.run([sys.executable, str(GENERATOR), *args], cwd=cwd, capture_output=True,
                          text=True, encoding="utf-8", timeout=60, check=False)


def _split(text):
    head, body = text[4:].split("\n---\n", 1)
    return head.splitlines(), body


class CursorProjectionTests(unittest.TestCase):
    def test_cursor_projection_reproduces_every_committed_mirror_byte_for_byte(self):
        generated = project_roles.generate(REPO, "cursor")
        committed = sorted(p.name for p in (REPO / "cursor" / "agents").glob("*.md"))
        self.assertEqual(sorted(generated), committed)
        self.assertEqual(len(committed), 11)
        for name, data in sorted(generated.items()):
            with self.subTest(role=name):
                self.assertEqual(data, (REPO / "cursor" / "agents" / name).read_bytes())

    def test_check_passes_on_the_repository(self):
        proc = _run("--target", "cursor", "--check")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("project_roles_check=passed", proc.stdout)

    def _copy_tree(self, tmp):
        root = Path(tmp) / "repo"
        shutil.copytree(REPO / "agents", root / "agents")
        shutil.copytree(REPO / "cursor" / "agents", root / "cursor" / "agents")
        return root

    def test_check_fails_on_a_hand_edited_mirror(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._copy_tree(tmp)
            mirror = root / "cursor" / "agents" / "code-reviewer.md"
            mirror.write_bytes(mirror.read_bytes() + b"hand edit\n")
            proc = _run("--target", "cursor", "--check", "--root", str(root))
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            self.assertIn("error=mirror_drift:cursor/agents/code-reviewer.md", proc.stdout)
            self.assertIn("project_roles_check=failed", proc.stdout)

    def test_check_fails_on_a_missing_or_extra_mirror(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._copy_tree(tmp)
            (root / "cursor" / "agents" / "debugger.md").unlink()
            (root / "cursor" / "agents" / "stray.md").write_text("---\nname: stray\n---\n", encoding="utf-8")
            proc = _run("--target", "cursor", "--check", "--root", str(root))
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            self.assertIn("error=mirror_missing:cursor/agents/debugger.md", proc.stdout)
            self.assertIn("error=mirror_unexpected:cursor/agents/stray.md", proc.stdout)

    def test_write_regenerates_a_drifted_mirror(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._copy_tree(tmp)
            mirror = root / "cursor" / "agents" / "debugger.md"
            mirror.write_text("drift\n", encoding="utf-8")
            proc = _run("--target", "cursor", "--write", "--root", str(root))
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(mirror.read_bytes(), (REPO / "cursor" / "agents" / "debugger.md").read_bytes())

    def test_mixed_read_and_write_role_is_not_read_only_on_cursor(self):
        text = "---\nname: mix\ndescription: d\ntools: Read, Grep, Edit\nmodel: inherit\n---\nbody\n"
        self.assertEqual(project_roles.project_cursor(text),
                         "---\nname: mix\ndescription: d\nmodel: inherit\n---\nbody\n")


class AntigravityProjectionTests(unittest.TestCase):
    def setUp(self):
        self.generated = {name: data.decode("utf-8")
                          for name, data in project_roles.generate(REPO, "antigravity").items()}

    def test_every_shared_role_is_projected(self):
        self.assertEqual(sorted(self.generated), sorted(p.name for p in (REPO / "agents").glob("*.md")))

    def test_frontmatter_uses_yaml_list_agy_tool_names_and_keeps_the_body(self):
        for name, text in sorted(self.generated.items()):
            with self.subTest(role=name):
                source = (REPO / "agents" / name).read_text(encoding="utf-8")
                lines, body = _split(text)
                self.assertEqual(body, _split(source)[1])
                self.assertEqual(lines[0], "name: " + name[:-3])
                source_lines = _split(source)[0]
                description = next(line for line in source_lines if line.startswith("description:"))
                self.assertEqual(lines[1], description)
                self.assertEqual(lines[2], "tools:")
                tools = []
                for line in lines[3:]:
                    if not line.startswith("  - "):
                        break
                    tools.append(line[4:])
                self.assertTrue(tools)
                self.assertEqual(len(tools), len(set(tools)))
                self.assertEqual(tools[0], "read_file")
                order = AGY_READ + ["write_file", "edit_file", "run_command"]
                self.assertEqual(tools, sorted(tools, key=order.index))
                rest = lines[3 + len(tools):]
                read_only = not (set(tools) & AGY_WRITE_TOOLS)
                expected = ["model: inherit", "subagent: true", "mainAgent: false"]
                if read_only:
                    expected.append("inheritMcp: false")
                self.assertEqual(rest, expected)
                self.assertNotIn(",", "".join(tools))

    def test_reviewers_are_read_only_and_writers_get_their_tools(self):
        def tools_of(role):
            lines, _ = _split(self.generated[role + ".md"])
            return [line[4:] for line in lines if line.startswith("  - ")]

        for role in ("code-reviewer", "context-analyst", "implementation-auditor", "security-reviewer",
                     "software-architect", "spec-plan-author", "spec-plan-critic"):
            with self.subTest(role=role):
                self.assertEqual(tools_of(role), ["read_file", "search_web"])
                self.assertIn("inheritMcp: false", self.generated[role + ".md"])
        self.assertEqual(tools_of("spec-builder-check"), ["read_file"])
        self.assertEqual(tools_of("draft-scribe"), ["read_file", "write_file", "run_command"])
        self.assertEqual(tools_of("debugger"), ["read_file", "search_web", "run_command"])
        self.assertNotIn("inheritMcp", self.generated["draft-scribe.md"])

    def test_mapping_is_deduplicated_in_a_stable_order(self):
        text = ("---\nname: w\ndescription: d\nmodel: inherit\n"
                "tools: Bash, Edit, MultiEdit, Write, WebSearch, Grep, Read, PowerShell, WebFetch, Glob\n---\nB\n")
        out = project_roles.project_antigravity(text)
        self.assertEqual(out, "---\nname: w\ndescription: d\ntools:\n  - read_file\n  - search_web\n"
                              "  - write_file\n  - edit_file\n  - run_command\nmodel: inherit\n"
                              "subagent: true\nmainAgent: false\n---\nB\n")

    def test_unknown_claude_tool_is_an_error(self):
        text = "---\nname: x\ndescription: d\ntools: Read, NotebookEdit\nmodel: inherit\n---\nB\n"
        with self.assertRaises(project_roles.RoleError) as ctx:
            project_roles.project_antigravity(text)
        self.assertIn("unknown_tool:NotebookEdit", str(ctx.exception))

    def test_role_without_a_frontmatter_or_tools_is_an_error(self):
        for text, code in (("no frontmatter\n", "frontmatter_missing"),
                           ("---\nname: x\ndescription: d\nmodel: inherit\n---\nB\n", "tools_missing")):
            with self.subTest(code=code):
                with self.assertRaises(project_roles.RoleError) as ctx:
                    project_roles.project_antigravity(text)
                self.assertIn(code, str(ctx.exception))

    def test_output_writes_the_antigravity_projection_outside_the_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "agents"
            proc = _run("--target", "antigravity", "--output", str(out))
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(sorted(p.name for p in out.glob("*.md")), sorted(self.generated))
            self.assertEqual((out / "debugger.md").read_text(encoding="utf-8"), self.generated["debugger.md"])

    def test_check_is_refused_for_the_uncommitted_antigravity_projection(self):
        proc = _run("--target", "antigravity", "--check")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
