"""Packaging, schema, staging, and documentation regression tests for the experimental Google Antigravity adapter."""
from pathlib import Path
import contextlib
import io
import json
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from scripts import build_release, project_roles  # noqa: E402
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

    def test_antigravity_adapter_docs_and_skills_preserve_contracts(self):
        for required in (
            "https://antigravity.google/schemas/v1/plugin.json",
            "`additionalProperties`: `false`",
            "invoke_subagent",
            "Not a supported release target",
            "hooks.json",
            "python3 scripts/build_release.py --output <zip> --antigravity",
            "agy plugin install <package-dir>",
            "agy plugin uninstall agentic-sdlc",
            "no `agy plugin update`",
            "deprecated (no removal date announced)",
            "agy-launch.mjs",
            "PLUGIN_ROOT",
            "inheritMcp: false",
            "24000",
        ):
            with self.subTest(readme_required=required):
                self.assertIn(required, self.readme)

        runtime_adapter = (REPO / "docs" / "runtime-adapter.md").read_text(encoding="utf-8")
        section = runtime_adapter.split(
            "## Google Antigravity adapter (experimental — not a supported release target)", 1)[1].split("\n## ", 1)[0]
        for required in (
            "invoke_subagent",
            "toolCall",
            "deprecated (no removal date announced)",
            ".antigravity-plugin/hooks.json",
            "agy-launch.mjs",
            "SessionStart",
            "Stop",
            "PreInvocation",
            "PostInvocation",
            "fails closed",
            "--antigravity",
        ):
            with self.subTest(runtime_adapter_required=required):
                self.assertIn(required, section)

        router = (REPO / "skills" / "using-agentic-sdlc" / "SKILL.md").read_text(encoding="utf-8")
        dispatch = (REPO / "skills" / "dispatch-strategy" / "SKILL.md").read_text(encoding="utf-8")
        pipeline = (REPO / "skills" / "agentic-sdlc-pipeline" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("In Google Antigravity (experimental adapter)", router)
        self.assertIn("invoke_subagent", dispatch)
        self.assertIn("invoke_subagent", pipeline)
        for text in (router, dispatch, pipeline):
            self.assertIn("deprecated (no removal date announced)", text)

    def test_retired_antigravity_claims_are_gone(self):
        # agy 1.5.14 (2026-11-21): workflows are deprecated with no removal date, the manifest
        # schema has more than two keys and accepts `version`, and hooks.json supports SessionStart
        # and Stop. These sentences must not come back.
        docs = [REPO / ".antigravity-plugin" / "README.md", REPO / "README.md", REPO / "docs" / "runtime-adapter.md",
                REPO / "docs" / "publication" / "multi-platform-distribution.md", REPO / "docs" / "testing.md",
                REPO / "skills" / "using-agentic-sdlc" / "SKILL.md", REPO / "skills" / "dispatch-strategy" / "SKILL.md",
                REPO / "skills" / "agentic-sdlc-pipeline" / "SKILL.md"]
        for path in docs:
            text = path.read_text(encoding="utf-8")
            with self.subTest(doc=str(path.relative_to(REPO))):
                for retired in ("October 19, 2026", "two-key", "VERSIONLESS_PLUGIN_MANIFESTS",
                                "without `SessionStart`, `Stop`", "does not support `SessionStart`",
                                "staged to `<plugin-dir>/plugin.json`", "cp -R skills"):
                    self.assertNotIn(retired, text)


def quiet(fn, *args, **kwargs):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = fn(*args, **kwargs)
    return result, buf.getvalue()


FOREIGN_ROOTS = ("commands/", "cursor/", "rules/", "workflows/grok/", "tests/", ".github/", ".grok/",
                 ".claude-plugin/", ".codex-plugin/", ".kimi-plugin/", ".zcode-plugin/", ".grok-plugin/",
                 ".cursor-plugin/")
FOREIGN_FILES = ("plugin.json", "marketplace.json", "marketplace-kimi.json", "AGENTS.md", "CLAUDE.md",
                 "hooks/hooks.json", ".antigravity-plugin/hooks.json")
AGY_HANDLERS = ("agy-launch.mjs", "scan-commit.mjs", "destructive-command-guard.mjs", "branch-guard.mjs",
                "scan-write.mjs", "session-start.mjs", "worktree-scan.mjs")


class AntigravityPackageBuildTests(unittest.TestCase):
    """AC8: `build_release.py --antigravity` builds the agy package from the committed HEAD tree."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "agy.zip"
        cls.result, cls.text = quiet(build_release.build_archive, REPO, cls.out, antigravity=True)
        with zipfile.ZipFile(cls.out) as zf:
            cls.members = {name: zf.read(name) for name in zf.namelist()}
        cls.head = build_release.release_members(REPO, build_release._resolve_head_commit(REPO))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_build_reports_the_antigravity_kind(self):
        self.assertEqual(self.result.exit_code, 0, self.text)
        lines = self.text.splitlines()
        self.assertIn("archive_kind=antigravity", lines)
        self.assertTrue(any(line.startswith("antigravity_payload_identity=") for line in lines))
        self.assertIn("build=passed", lines)

    def test_manifest_and_root_hooks_come_from_the_adapter_folder(self):
        self.assertEqual(self.members[".antigravity-plugin/plugin.json"], self.head[".antigravity-plugin/plugin.json"])
        self.assertEqual(self.members["hooks.json"], self.head[".antigravity-plugin/hooks.json"])
        self.assertIn("LICENSE", self.members)
        self.assertIn("assets/logo.png", self.members)

    def test_no_other_runtime_component_ships(self):
        for name in self.members:
            with self.subTest(member=name):
                self.assertFalse(name.startswith(FOREIGN_ROOTS), name)
                self.assertNotIn(name, FOREIGN_FILES)
                self.assertFalse(name.startswith("hooks/hooks-"), name)

    def test_hooks_are_the_launcher_and_its_closure_only(self):
        hooks = sorted(name[len("hooks/"):] for name in self.members if name.startswith("hooks/"))
        for handler in AGY_HANDLERS:
            self.assertIn(handler, hooks)
        for unwired in ("flow-order-guard.mjs", "completion-claim-guard.mjs", "cursor-launch.mjs",
                        "session-start-codex.mjs", "flow-step-guard.mjs"):
            self.assertNotIn(unwired, hooks)
        import_ref = re.compile(r"(?:from\s*|import\s*(?:\(\s*)?)[\"'](\.{1,2}/[^\"']+\.mjs)[\"']")
        for name in hooks:
            if name.endswith(".mjs"):
                for rel in import_ref.findall(self.members["hooks/" + name].decode("utf-8")):
                    target = str(Path("hooks", rel).as_posix()).replace("hooks/./", "hooks/")
                    self.assertIn(target, self.members, f"{name} imports {rel}")

    def test_agents_are_the_agy_projection_of_every_shared_role(self):
        agents = sorted(name for name in self.members if name.startswith("agents/"))
        shared = sorted(name for name in self.head if name.startswith("agents/") and name.endswith(".md"))
        self.assertEqual(agents, shared)
        self.assertEqual(len(agents), 11)
        for name in agents:
            with self.subTest(role=name):
                expected = project_roles.project_antigravity(self.head[name].decode("utf-8")).encode("utf-8")
                self.assertEqual(self.members[name], expected)

    def test_over_long_skill_bodies_are_split_and_the_rest_ships_whole(self):
        # AC1: agy loads only the first 24000 bytes of a SKILL.md body (agy 1.5.14 `plugin validate`).
        limit = build_release.AGY_SKILL_BODY_LIMIT
        continuation = build_release.AGY_SKILL_CONTINUATION
        split = []
        for name, data in sorted(self.head.items()):
            if not name.startswith("skills/"):
                continue
            with self.subTest(member=name):
                if not (name.endswith("/SKILL.md") and name.count("/") == 2):
                    self.assertEqual(self.members[name], data)
                    continue
                head_fm, head_body = build_release._skill_parts(data)
                out_fm, out_body = build_release._skill_parts(self.members[name])
                self.assertEqual(out_fm, head_fm)
                self.assertLessEqual(len(out_body), limit)
                extra = name.rsplit("/", 1)[0] + "/" + continuation
                if len(head_body) <= limit:
                    self.assertEqual(self.members[name], data)
                    self.assertNotIn(extra, self.members)
                    continue
                split.append(name)
                rest = self.members[extra]
                note_end = out_body.index(b"\n\n") + 2
                self.assertIn(continuation.encode(), out_body[:note_end])
                self.assertIn(b"read_file", out_body[:note_end])
                self.assertIn(rest.split(b"\n", 1)[0].lstrip(b"#").strip(), out_body[:note_end])
                self.assertEqual(out_body[note_end:] + rest, head_body)
                self.assertTrue(rest.startswith(b"#"))
        self.assertIn("skills/agentic-sdlc-pipeline/SKILL.md", split)
        pipeline_rest = self.members["skills/agentic-sdlc-pipeline/" + continuation]
        self.assertIn(b"\n## Finalize\n", pipeline_rest)

    def test_projected_skill_relative_links_resolve(self):
        link = re.compile(r"\]\((?!https?:|#|mailto:)([^)\s#]+)")
        for name, data in sorted(self.members.items()):
            if not (name.startswith("skills/") and name.endswith(".md")) or self.head.get(name) == data:
                continue
            folder = name.rsplit("/", 1)[0]
            for rel in link.findall(data.decode("utf-8")):
                target = posixpath.normpath(posixpath.join(folder, rel))
                with self.subTest(doc=name, link=rel):
                    self.assertTrue(target in self.members or any(m.startswith(target + "/") for m in self.members),
                                    target)

    @unittest.skipUnless(shutil.which("agy"), "agy CLI not installed")
    def test_agy_strict_validate_passes_on_the_built_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(self.out) as zf:
                zf.extractall(tmp)
            proc = subprocess.run(["agy", "plugin", "validate", "--strict", "--json", tmp], capture_output=True,
                                  text=True, encoding="utf-8", check=False, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            report = json.loads(proc.stdout)
            self.assertEqual([f for f in report["findings"] if f["severity"] != "note"], [])

    def test_skills_ship_whole_and_every_runtime_root_reference_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_root = Path(tmp) / "consumer-workspace" / ".agents" / "plugins" / "agentic-sdlc"
            with zipfile.ZipFile(self.out) as zf:
                zf.extractall(plugin_root)
            skills = sorted((plugin_root / "skills").glob("*/SKILL.md"))
            self.assertEqual(len(skills), 16)
            for doc in sorted(list((plugin_root / "skills").rglob("*.md")) + list((plugin_root / "contracts").rglob("*.md"))):
                text = doc.read_text(encoding="utf-8")
                for match in RUNTIME_ROOT_REF_RE.finditer(text):
                    rel = match.group(1).rstrip(".,;:")
                    with self.subTest(doc=str(doc.relative_to(plugin_root)), ref=rel):
                        self.assertTrue((plugin_root / rel).exists(), f"Unresolved <runtime-root>/{rel}")
            project_dir = Path(tmp) / "consumer-workspace" / "app"
            project_dir.mkdir(parents=True)
            proc = subprocess.run(
                [sys.executable, str(plugin_root / "scripts" / "detect_context.py"), "--path", str(project_dir)],
                cwd=project_dir, capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("context_detection=greenfield", proc.stdout)

    def test_verify_passes_and_infers_the_kind(self):
        report, text = quiet(build_release.verify_archive, self.out, REPO)
        self.assertEqual(report.exit_code, 0, text)
        self.assertIn("archive_kind=antigravity", text.splitlines())

    def test_verify_rejects_an_added_member(self):
        commit = build_release._resolve_head_commit(REPO)
        members = build_release._kind_members(commit, cwd=REPO, kind="antigravity")
        members["commands/extra.md"] = ("100644", b"extra\n")
        tampered = Path(self.tmp.name) / "tampered.zip"
        tampered.write_bytes(build_release._zip_bytes(members, commit))
        report, text = quiet(build_release.verify_archive, tampered, REPO)
        self.assertEqual(report.exit_code, 1, text)
        self.assertIn("error=unexpected_member:commands/extra.md", text)
        self.assertIn("archive_kind=antigravity", text.splitlines())

    def test_build_is_byte_identical_twice(self):
        again = Path(self.tmp.name) / "again.zip"
        result, text = quiet(build_release.build_archive, REPO, again, antigravity=True)
        self.assertEqual(result.exit_code, 0, text)
        self.assertEqual(again.read_bytes(), self.out.read_bytes())

    def test_cli_accepts_antigravity_only_with_output_and_not_with_skills_only(self):
        script = REPO / "scripts" / "build_release.py"
        for args in (["--verify", str(self.out), "--antigravity"],
                     ["--output", str(Path(self.tmp.name) / "x.zip"), "--antigravity", "--skills-only"]):
            with self.subTest(args=args[-1]):
                proc = subprocess.run([sys.executable, str(script), *args], cwd=REPO, capture_output=True,
                                      text=True, encoding="utf-8", check=False)
                self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)


class AntigravitySelectionTests(unittest.TestCase):
    BASE = {
        ".antigravity-plugin/plugin.json": ("100644", b'{"name": "x", "version": "1.0.0"}\n'),
        ".antigravity-plugin/hooks.json": ("100644", b'{"g": {"enabled": true, "Stop": [{"type": "command", '
                                           b'"command": "node ./hooks/agy-launch.mjs --event Stop --handler w.mjs"}]}}\n'),
        "hooks/agy-launch.mjs": ("100644", b"// launcher\n"),
        "hooks/w.mjs": ("100644", b"import { x } from './dep.mjs';\n"),
        "hooks/dep.mjs": ("100644", b"export const x = 1;\n"),
        "hooks/unused.mjs": ("100644", b"// not wired\n"),
        "skills/s/SKILL.md": ("100644", b"---\nname: s\n---\nRead <runtime-root>/docs/a.md.\n"),
        "docs/a.md": ("100644", b"# a\n"),
        "docs/b.md": ("100644", b"# b\n"),
        "agents/r.md": ("100644", b"---\nname: r\ndescription: d\ntools: Read, Grep\nmodel: inherit\n---\nBody\n"),
        "commands/c.md": ("100644", b"# c\n"),
        "LICENSE": ("100644", b"MIT\n"),
    }

    def select(self, **changes):
        members = dict(self.BASE)
        for path, value in changes.items():
            path = path.replace("__", "/")
            if value is None:
                members.pop(path, None)
            else:
                members[path] = value
        return build_release._select_antigravity(members)

    def test_selection_follows_the_wire_and_the_skill_references(self):
        selected = self.select()
        self.assertEqual(sorted(selected), sorted([
            ".antigravity-plugin/plugin.json", "hooks.json", "hooks/agy-launch.mjs", "hooks/w.mjs", "hooks/dep.mjs",
            "skills/s/SKILL.md", "docs/a.md", "agents/r.md", "LICENSE",
        ]))
        self.assertIn(b"  - read_file\n", selected["agents/r.md"][1])

    @staticmethod
    def skill(body: bytes, frontmatter: bytes = b"---\nname: s\ndescription: d\n---\n") -> tuple:
        return ("100644", frontmatter + body)

    @staticmethod
    def section(title: str, size: int, level: int = 2) -> bytes:
        """A section of exactly `size` bytes: one heading line, then filler lines, ending in a newline."""
        head = ("#" * level + " " + title + "\n").encode()
        filler = size - len(head)
        lines, tail = divmod(filler, 80)
        data = head + (b"x" * 79 + b"\n") * lines
        if tail:
            data += b"y" * (tail - 1) + b"\n"
        assert len(data) == size
        return data

    def split(self, body: bytes, frontmatter: bytes = b"---\nname: s\ndescription: d\n---\n"):
        members = dict(self.BASE)
        members["skills/s/SKILL.md"] = self.skill(body, frontmatter)
        selected = build_release._select_antigravity(members)
        return selected, body

    def assert_split(self, selected, body, frontmatter=b"---\nname: s\ndescription: d\n---\n", first=None):
        limit = build_release.AGY_SKILL_BODY_LIMIT
        out = selected["skills/s/SKILL.md"][1]
        self.assertTrue(out.startswith(frontmatter))
        out_body = out[len(frontmatter):]
        self.assertLessEqual(len(out_body), limit)
        rest = selected["skills/s/" + build_release.AGY_SKILL_CONTINUATION][1]
        self.assertEqual(selected["skills/s/" + build_release.AGY_SKILL_CONTINUATION][0], "100644")
        note_end = out_body.index(b"\n\n") + 2
        self.assertEqual(out_body[note_end:] + rest, body)
        if first is not None:
            self.assertTrue(rest.startswith(first), rest[:80])
        return out_body[:note_end], out_body[note_end:], rest

    def test_body_at_the_limit_is_kept_and_one_byte_more_is_split(self):
        limit = build_release.AGY_SKILL_BODY_LIMIT
        intro = b"# T\n\nIntro.\n\n"
        at_limit = intro + self.section("A", 12000) + self.section("B", limit - 12000 - len(intro))
        self.assertEqual(len(at_limit), limit)
        selected, _ = self.split(at_limit)
        self.assertEqual(selected["skills/s/SKILL.md"][1], self.skill(at_limit)[1])
        self.assertNotIn("skills/s/" + build_release.AGY_SKILL_CONTINUATION, selected)
        over = at_limit + b"z"
        selected, _ = self.split(over)
        note, kept, rest = self.assert_split(selected, over, first=b"## B\n")
        self.assertIn(b"agy loads only", note.lower().replace(b"antigravity (agy)", b"agy"))
        self.assertIn(b"skills/s/" + build_release.AGY_SKILL_CONTINUATION.encode(), note)
        self.assertIn(b"read_file", note)
        self.assertIn(b"B", note)

    def test_split_ignores_headings_inside_code_fences(self):
        fenced = b"## A\n```\n" + b"## not a heading\n" + (b"q" * 79 + b"\n") * 200 + b"```\n"
        body = b"# T\n\n" + fenced + self.section("B", 20000)
        selected, _ = self.split(body)
        _note, kept, rest = self.assert_split(selected, body, first=b"## B\n")
        self.assertIn(b"## not a heading", kept)

    def test_a_section_over_the_limit_splits_at_the_next_lower_heading(self):
        big = b"## A\n\n" + self.section("A1", 15000, 3) + self.section("A2", 15000, 3)
        body = b"# T\n\n" + big + self.section("B", 3000)
        selected, _ = self.split(body)
        self.assert_split(selected, body, first=b"### A2\n")

    def test_crlf_frontmatter_is_kept(self):
        frontmatter = b"---\r\nname: s\r\ndescription: d\r\n---\r\n"
        body = b"# T\r\n\r\n" + self.section("A", 20000) + self.section("B", 6000)
        selected, _ = self.split(body, frontmatter)
        out = selected["skills/s/SKILL.md"][1]
        self.assertTrue(out.startswith(frontmatter))
        out_body = out[len(frontmatter):]
        rest = selected["skills/s/" + build_release.AGY_SKILL_CONTINUATION][1]
        note_end = out_body.index(b"\r\n\r\n") + 4
        self.assertEqual(out_body[note_end:] + rest, body)
        self.assertLessEqual(len(out_body), build_release.AGY_SKILL_BODY_LIMIT)

    def test_unsplittable_skill_and_continuation_collision_fail_the_build(self):
        cases = {
            "error=antigravity_skill_unsplittable:skills/s/SKILL.md": {
                "skills/s/SKILL.md": self.skill(b"# T\n\n" + b"x" * 30000 + b"\n")},
            "error=antigravity_skill_continuation_exists:skills/s/" + build_release.AGY_SKILL_CONTINUATION: {
                "skills/s/SKILL.md": self.skill(b"# T\n\n" + self.section("A", 20000) + self.section("B", 6000)),
                "skills/s/" + build_release.AGY_SKILL_CONTINUATION: ("100644", b"# taken\n")},
        }
        for expected, change in cases.items():
            with self.subTest(expected=expected):
                members = dict(self.BASE)
                members.update(change)
                with self.assertRaises(build_release.ReleaseError) as ctx:
                    build_release._select_antigravity(members)
                self.assertIn(expected, ctx.exception.lines)

    def test_missing_pieces_and_bad_roles_fail_the_build(self):
        cases = {
            "error=antigravity_member_missing:.antigravity-plugin/hooks.json": {".antigravity-plugin/hooks.json": None},
            "error=antigravity_member_missing:LICENSE": {"LICENSE": None},
            "error=antigravity_hook_dependency_missing:hooks/dep.mjs": {"hooks/dep.mjs": None},
            "error=antigravity_role_invalid:unknown_tool:NotebookEdit:agents/r.md": {
                "agents/r.md": ("100644", b"---\nname: r\ndescription: d\ntools: NotebookEdit\nmodel: inherit\n---\nB\n")},
            "error=mcp_configuration:skills/.mcp.json": {"skills/.mcp.json": ("100644", b"{}\n")},
            "error=antigravity_role_invalid:name_missing:agents/r.md": {"agents/r.md": ("100644", b"---\n---\nB\n")},
        }
        for expected, change in cases.items():
            with self.subTest(expected=expected):
                members = dict(self.BASE)
                for path, value in change.items():
                    if value is None:
                        members.pop(path)
                    else:
                        members[path] = value
                with self.assertRaises(build_release.ReleaseError) as ctx:
                    build_release._select_antigravity(members)
                self.assertIn(expected, ctx.exception.lines)


if __name__ == "__main__":
    unittest.main()
