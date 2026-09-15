"""Distribution tooling: release and skills-only archives, verify, and history scan.

Every repository these tests mutate is a ScratchRepo in a temporary directory with a
host-independent git environment. The real repository is only read, and the module guard
proves its HEAD, index stage entries and refs are unchanged afterwards (AC101).

Synthetic credentials are assembled by string concatenation at runtime, so this file carries
no scannable literal.
"""

import contextlib
import hashlib
import io
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import scripts.build_release as build_release

REPO = Path(__file__).resolve().parents[1]
FIXED_DATE = "2026-01-01T00:00:00+0000"
_STATE_COMPONENTS = ("HEAD", "index stage entries", "refs")


def _git_bytes(root: Path, *args: str) -> bytes:
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    proc = subprocess.run(["git", *args], cwd=root, env=env, capture_output=True)
    if proc.returncode != 0:
        raise AssertionError("git %s failed in %s" % (" ".join(args), root))
    return proc.stdout


def repository_state(root: Path) -> tuple:
    """HEAD, SHA-256 of the index stage entries, SHA-256 of every ref and its object."""
    head = _git_bytes(root, "rev-parse", "HEAD").decode("ascii").strip()
    index = hashlib.sha256(_git_bytes(root, "ls-files", "-s", "-z")).hexdigest()
    refs = hashlib.sha256(_git_bytes(root, "for-each-ref", "--format=%(objectname) %(refname)")).hexdigest()
    return (head, index, refs)


_REPO_STATE_AT_START = None


def setUpModule():
    global _REPO_STATE_AT_START
    _REPO_STATE_AT_START = repository_state(REPO)


def tearDownModule():
    now = repository_state(REPO)
    changed = [name for name, a, b in zip(_STATE_COMPONENTS, _REPO_STATE_AT_START, now) if a != b]
    if changed:
        raise AssertionError("source repository changed: " + ", ".join(changed))


class ScratchRepo:
    """A git repository in a temporary directory, isolated from host git configuration."""

    def __init__(self, base: Path, name: str = "repo"):
        self.base = Path(base)
        self.root = self.base / name
        self.root.mkdir(parents=True)
        global_config = self.base / f"{name}-global.gitconfig"
        global_config.write_bytes(b"")
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=str(global_config),
            GIT_AUTHOR_NAME="Scratch Author",
            GIT_AUTHOR_EMAIL="author@example.invalid",
            GIT_COMMITTER_NAME="Scratch Committer",
            GIT_COMMITTER_EMAIL="committer@example.invalid",
            GIT_AUTHOR_DATE=FIXED_DATE,
            GIT_COMMITTER_DATE=FIXED_DATE,
            GIT_TERMINAL_PROMPT="0",
        )
        self.env = env
        self.git("init", "-q", "-b", "main")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *args: str, stdin: bytes | None = None, cwd: Path | None = None) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd or self.root,
            env=self.env,
            input=stdin,
            capture_output=True,
        )
        if proc.returncode != 0:
            raise AssertionError(
                "git %s failed: %s" % (" ".join(args), proc.stderr.decode("utf-8", "replace"))
            )
        return proc.stdout.decode("utf-8", "replace").strip()

    def write(self, files: dict) -> None:
        for rel, data in files.items():
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    def commit(self, files: dict, message: str = "commit") -> str:
        """Write, stage and commit files; a None value removes the path."""
        for rel, data in files.items():
            if data is None:
                self.git("rm", "-q", "--", rel)
            else:
                self.write({rel: data})
                self.git("add", "--", rel)
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def add_cacheinfo(self, mode: str, content: bytes, path: str) -> str:
        oid = self.git("hash-object", "-w", "--stdin", stdin=content)
        self.git("update-index", "--add", "--cacheinfo", f"{mode},{oid},{path}")
        return oid

    def crafted_commit(self, entries, ref: str, message: str = "crafted", parent: str | None = None) -> str:
        """Commit a flat tree of (mode, name, content) entries that git refuses in the index."""
        lines = []
        for mode, name, content in entries:
            oid = self.git("hash-object", "-w", "--stdin", stdin=content)
            lines.append(f"{mode} blob {oid}\t{name}")
        tree = self.git("mktree", stdin=("\n".join(lines) + "\n").encode("utf-8"))
        args = ["commit-tree", tree, "-m", message]
        if parent:
            args += ["-p", parent]
        commit = self.git(*args)
        self.git("update-ref", ref, commit)
        return commit


class ScratchTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def scratch(self, name: str = "repo") -> ScratchRepo:
        return ScratchRepo(self.tmp, name)

    @staticmethod
    def quiet(fn, *args, **kwargs):
        """Call an in-process build_release entry and capture what it prints."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = fn(*args, **kwargs)
        return result, buf.getvalue()

    @staticmethod
    def cli(args, *, cwd, env) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(REPO / "scripts" / "build_release.py"), *[str(a) for a in args]],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def build(self, root: Path, name: str = "a.zip", **kwargs):
        out = self.tmp / "out" / name
        result, text = self.quiet(build_release.build_archive, root, out, **kwargs)
        return result, text, out


class TestMemberPolicy(unittest.TestCase):
    def test_classify_member_flags_each_exclusion_class(self):
        samples = {
            1: [("agentic-sdlc-prompts/plan.md", "100644"), ("agentic-sdlc-prompts/a/b.txt", "100644")],
            2: [("tests/test_superpowers_referenced_eval_prompt.py", "100644")],
            3: [("AGENTS.md", "100644"), ("CLAUDE.md", "100644"), ("skills/x/AGENTS.md", "100644")],
            4: [
                (".claude/settings.json", "100644"),
                ("sub/.codex/config.toml", "100644"),
                ("settings.local.json", "100644"),
                ("deep/settings.local.json", "100644"),
                (".env", "100644"),
                (".env.production", "100644"),
                ("app/.env", "100644"),
            ],
            5: [("tests/artifacts/run.jsonl", "100644"), ("tests/artifacts/publication/x.json", "100644")],
            6: [("audit-docs/codex-audit-docs.md", "100644"), (".handoffs/h.md", "100644")],
            7: [
                ("link", "120000"),
                ("/abs", "100644"),
                ("C:/x", "100644"),
                ("a/../b", "100644"),
                ("..", "100644"),
                ("a\\b", "100644"),
            ],
        }
        for expected, paths in samples.items():
            for path, mode in paths:
                with self.subTest(path=path, mode=mode):
                    self.assertEqual(build_release.exclusion_class(path, mode), expected)

    def test_classify_member_allows_near_misses(self):
        for path in (
            ".env.example",
            ".codex-plugin/plugin.json",
            ".claude-plugin/plugin.json",
            "tests/fixtures/transcripts/codex-strict-green.jsonl",
            "docs/agentic-sdlc/x.md",
            "skills/x/SKILL.md",
            "hooks/scan-commit.mjs",
        ):
            with self.subTest(path=path):
                self.assertIsNone(build_release.exclusion_class(path, "100644"))
        self.assertIsNone(build_release.exclusion_class("scripts/tool.py", "100755"))


class TestScratchRepoIsolation(ScratchTestCase):
    def test_scratch_repo_ignores_host_git_config(self):
        template = self.tmp / "bogus-template"
        (template / "hooks").mkdir(parents=True)
        (template / "hooks" / "pre-commit").write_bytes(b"#!/bin/sh\nexit 1\n")
        bogus = self.tmp / "bogus-global.gitconfig"
        bogus.write_bytes(
            ("[core]\n\tautocrlf = true\n[init]\n\ttemplateDir = %s\n" % template.as_posix()).encode("utf-8")
        )
        with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(bogus)}):
            repo = self.scratch()
        origin = repo.git("config", "--show-origin", "core.autocrlf")
        self.assertTrue(origin.endswith("false"), origin)
        self.assertIn(".git/config", origin.replace("\\", "/"))
        every_origin = repo.git("config", "--show-origin", "--get-all", "core.autocrlf").splitlines()
        self.assertEqual(len(every_origin), 1, every_origin)
        self.assertFalse((repo.root / ".git" / "hooks" / "pre-commit").exists())


class TestSourceRepositoryGuard(ScratchTestCase):
    def test_repository_state_detects_ref_index_and_head_changes(self):
        repo = self.scratch()
        repo.commit({"a.txt": b"a\n", "run.sh": b"echo hi\n"}, "c1")
        before = repository_state(repo.root)
        repo.git("update-ref", "refs/heads/probe", "HEAD")
        after_ref = repository_state(repo.root)
        self.assertNotEqual(before[2], after_ref[2])
        self.assertEqual(before[:2], after_ref[:2])
        repo.git("update-index", "--chmod=+x", "run.sh")
        after_index = repository_state(repo.root)
        self.assertNotEqual(after_ref[1], after_index[1])
        repo.commit({"b.txt": b"b\n"}, "c2")
        after_commit = repository_state(repo.root)
        self.assertNotEqual(after_index[0], after_commit[0])


COMMITTED_CLASS_SAMPLES = {
    1: "agentic-sdlc-prompts/plan.md",
    2: "tests/test_superpowers_referenced_eval_prompt.py",
    3: "AGENTS.md",
    4: ".claude/settings.json",
    5: "tests/artifacts/raw.jsonl",
    6: "audit-docs/dump.md",
}


class TestReleaseBuild(ScratchTestCase):
    def base_files(self) -> dict:
        return {
            "README.md": b"readme\n",
            "skills/x/SKILL.md": b"---\nname: x\n---\n",
            "scripts/tool.py": b"print('tool')\n",
            "tests/fixtures/transcripts/committed.jsonl": b'{"type":"message"}\n',
        }

    def assert_rejected(self, repo: ScratchRepo, cls: int, path: str):
        result, text, out = self.build(repo.root)
        self.assertEqual(result.exit_code, 1, text)
        self.assertIn(f"error=excluded_member:class-{cls}:{path}", text.splitlines())
        self.assertIn("build=failed", text.splitlines())
        self.assertFalse(out.exists())

    def test_build_members_equal_commit_tree_and_bytes(self):
        repo = self.scratch()
        commit = repo.commit({**self.base_files(), ".gitignore": b".env\ntests/artifacts/\n"}, "c1")
        repo.write({
            "agentic-sdlc-prompts/plan.md": b"private\n",
            "tests/test_superpowers_referenced_eval_prompt.py": b"private\n",
            "CLAUDE.md": b"local\n",
            ".env": b"LOCAL=1\n",
            "tests/artifacts/run.jsonl": b"{}\n",
            "audit-docs/dump.md": b"dump\n",
            "tests/fixtures/transcripts/raw.jsonl": b"{}\n",
            "README.md": b"uncommitted edit\n",
        })
        cwd_before = Path.cwd()
        result, text, out = self.build(repo.root)
        self.assertEqual(Path.cwd(), cwd_before)
        self.assertEqual(result.exit_code, 0, text)
        tree_paths = repo.git("ls-tree", "-r", "--name-only", "--full-tree", commit).splitlines()
        with zipfile.ZipFile(out) as zf:
            self.assertEqual(sorted(zf.namelist()), sorted(tree_paths))
            for name in zf.namelist():
                blob = subprocess.run(
                    ["git", "cat-file", "blob", f"{commit}:{name}"],
                    cwd=repo.root, env=repo.env, capture_output=True, check=True,
                ).stdout
                self.assertEqual(zf.read(name), blob, name)
        self.assertIn(f"source_commit={commit}", text.splitlines())

    def test_build_rejects_committed_class_1(self):
        self._reject_committed_class(1)

    def test_build_rejects_committed_class_2(self):
        self._reject_committed_class(2)

    def test_build_rejects_committed_class_3(self):
        self._reject_committed_class(3)

    def test_build_rejects_committed_class_4(self):
        self._reject_committed_class(4)

    def test_build_rejects_committed_class_5(self):
        self._reject_committed_class(5)

    def test_build_rejects_committed_class_6(self):
        self._reject_committed_class(6)

    def _reject_committed_class(self, cls: int):
        repo = self.scratch()
        path = COMMITTED_CLASS_SAMPLES[cls]
        repo.commit({**self.base_files(), path: b"committed private content\n"}, f"class {cls}")
        self.assert_rejected(repo, cls, path)

    def test_build_rejects_committed_class_7_symlink_entry(self):
        repo = self.scratch()
        repo.write(self.base_files())
        repo.git("add", "--", *self.base_files())
        repo.add_cacheinfo("120000", b"../../outside", "escape-link")
        repo.git("commit", "-q", "-m", "symlink entry")
        self.assert_rejected(repo, 7, "escape-link")

    def test_build_rejects_committed_class_7_dotdot_and_backslash_entries(self):
        repo = self.scratch()
        repo.crafted_commit(
            [("100644", "README.md", b"readme\n"), ("100644", "..", b"dotdot\n"), ("100644", "a\\b", b"bs\n")],
            "refs/heads/main",
        )
        result, text, out = self.build(repo.root)
        self.assertEqual(result.exit_code, 1, text)
        lines = text.splitlines()
        self.assertIn("error=excluded_member:class-7:..", lines)
        self.assertIn("error=excluded_member:class-7:a\\b", lines)
        self.assertFalse(out.exists())

    def test_build_rejects_os_symlink_escaping_root(self):
        repo = self.scratch()
        repo.git("config", "core.symlinks", "true")
        outside = self.tmp / "outside.txt"
        outside.write_bytes(b"outside\n")
        try:
            os.symlink(outside, repo.root / "escape")
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        repo.commit(self.base_files(), "base")
        repo.git("add", "--", "escape")
        repo.git("commit", "-q", "-m", "os symlink")
        self.assertEqual(repo.git("ls-files", "-s", "--", "escape").split()[0], "120000")
        self.assert_rejected(repo, 7, "escape")

    def test_untracked_transcript_under_fixtures_is_never_member(self):
        repo = self.scratch()
        repo.commit(self.base_files(), "c1")
        repo.write({"tests/fixtures/transcripts/raw.jsonl": b'{"raw":true}\n'})
        result, text, out = self.build(repo.root)
        self.assertEqual(result.exit_code, 0, text)
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        self.assertIn("tests/fixtures/transcripts/committed.jsonl", names)
        self.assertNotIn("tests/fixtures/transcripts/raw.jsonl", names)

    def test_cli_output_prints_identity_lines(self):
        repo = self.scratch()
        commit = repo.commit(self.base_files(), "c1")
        out = self.tmp / "cli" / "a.zip"
        proc = self.cli(["--output", out], cwd=repo.root, env=repo.env)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        lines = proc.stdout.splitlines()
        self.assertIn("archive_kind=release", lines)
        self.assertIn(f"source_commit={commit}", lines)
        self.assertIn(f"members={len(self.base_files())}", lines)
        self.assertIn("archive_sha256=" + hashlib.sha256(out.read_bytes()).hexdigest(), lines)
        self.assertEqual(lines[-1], "build=passed")

    def test_real_head_release_archive_has_no_root_portable_manifest(self):
        result, text, out = self.build(REPO, "release.zip")
        self.assertEqual(result.exit_code, 0, text)
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
            self.assertNotIn("plugin.json", names)
            self.assertIn(".codex-plugin/plugin.json", names)
            self.assertIn(".claude-plugin/plugin.json", names)
            manifest = json.loads(zf.read(".codex-plugin/plugin.json").decode("utf-8"))
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertEqual(manifest["hooks"], "./hooks/hooks-codex.json")


# Recorded when Task 47 went GREEN; asserted on both CI operating systems.
GOLDEN_COMMIT = "51e01c39dc9290011b206ec409745c6909da541b"
GOLDEN_ARCHIVE_SHA256 = "ae1f6d17756a9f44a677d4e3aa37eee60ed3409eadc1320ac3bcbb50b29158f3"
LEDGER_DOCS = ("docs/release-evidence-0.4.3.md", "docs/release-readiness.md")


def manifest_identity(members: dict, exclude=()) -> str:
    """Independent BR20 recompute: SHA-256 of sha256sum-style lines in UTF-8 path order."""
    lines = "".join(
        "%s  %s\n" % (hashlib.sha256(members[p]).hexdigest(), p)
        for p in sorted(members, key=lambda p: p.encode("utf-8"))
        if p not in exclude
    )
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def archive_members(path: Path) -> dict:
    with zipfile.ZipFile(path) as zf:
        return {info.orig_filename: zf.read(info) for info in zf.infolist()}


def printed(text: str, key: str) -> str:
    values = [line.split("=", 1)[1] for line in text.splitlines() if line.startswith(key + "=")]
    if len(values) != 1:
        raise AssertionError(f"expected one {key}= line, got {values}: {text}")
    return values[0]


class TestDeterministicLayout(ScratchTestCase):
    def layout_repo(self) -> ScratchRepo:
        repo = self.scratch()
        repo.write({
            "Z.txt": b"upper\n",
            "a.txt": b"lower\n",
            "a-b.txt": b"dash\n",
            "a/b.txt": b"nested\n",
            "run.sh": b"#!/bin/sh\necho run\n",
            LEDGER_DOCS[0]: b"# ledger\n",
            LEDGER_DOCS[1]: b"# readiness\n",
        })
        repo.git("add", "--", ".")
        repo.git("update-index", "--chmod=+x", "run.sh")
        repo.git("commit", "-q", "-m", "layout")
        return repo

    def test_same_commit_builds_byte_identical(self):
        repo = self.layout_repo()
        first, text1, out1 = self.build(repo.root, "one.zip")
        second, text2, out2 = self.build(repo.root, "two.zip")
        self.assertEqual((first.exit_code, second.exit_code), (0, 0), text1 + text2)
        self.assertEqual(out1.read_bytes(), out2.read_bytes())

    def test_zip_entry_fields_are_fixed(self):
        repo = self.layout_repo()
        commit = repo.git("rev-parse", "HEAD")
        result, text, out = self.build(repo.root)
        self.assertEqual(result.exit_code, 0, text)
        with zipfile.ZipFile(out) as zf:
            infos = zf.infolist()
            self.assertEqual(zf.comment, b"agentic-sdlc-archive source_commit=" + commit.encode("ascii"))
        names = [i.orig_filename for i in infos]
        self.assertEqual(names, sorted(names, key=lambda p: p.encode("utf-8")))
        self.assertEqual(names[:4], ["Z.txt", "a-b.txt", "a.txt", "a/b.txt"])
        for info in infos:
            with self.subTest(member=info.orig_filename):
                self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(info.compress_type, zipfile.ZIP_STORED)
                self.assertEqual(info.create_system, 3)
                self.assertEqual(info.create_version, 20)
                self.assertEqual(info.extract_version, 20)
                expected_mode = 0o100755 if info.orig_filename == "run.sh" else 0o100644
                self.assertEqual(info.external_attr >> 16, expected_mode)

    def test_runtime_payload_identity_formula_excludes_ledger_docs(self):
        repo = self.layout_repo()
        result, text, out = self.build(repo.root)
        self.assertEqual(result.exit_code, 0, text)
        members = archive_members(out)
        expected = manifest_identity(members, LEDGER_DOCS)
        self.assertEqual(build_release.payload_identity(members, build_release.RUNTIME_PAYLOAD_EXCLUDE), expected)
        self.assertEqual(printed(text, "runtime_payload_identity"), expected)
        self.assertEqual(build_release.RUNTIME_PAYLOAD_EXCLUDE, frozenset(LEDGER_DOCS))
        for doc in LEDGER_DOCS:
            with self.subTest(changed=doc):
                changed = {**members, doc: members[doc] + b"edited\n"}
                self.assertEqual(build_release.payload_identity(changed, build_release.RUNTIME_PAYLOAD_EXCLUDE), expected)
        for name in ("a.txt", "run.sh"):
            with self.subTest(changed=name):
                changed = {**members, name: members[name] + b"edited\n"}
                self.assertNotEqual(build_release.payload_identity(changed, build_release.RUNTIME_PAYLOAD_EXCLUDE), expected)

    def test_committed_ledger_edit_changes_archive_hash_not_payload_identity(self):
        repo = self.layout_repo()
        first, text1, _ = self.build(repo.root, "before.zip")
        repo.commit({LEDGER_DOCS[0]: b"# ledger\narchive_sha256 recorded\n"}, "ledger")
        second, text2, _ = self.build(repo.root, "after.zip")
        self.assertEqual((first.exit_code, second.exit_code), (0, 0), text1 + text2)
        self.assertNotEqual(printed(text1, "archive_sha256"), printed(text2, "archive_sha256"))
        self.assertEqual(printed(text1, "runtime_payload_identity"), printed(text2, "runtime_payload_identity"))

    def test_release_members_equal_archive_members(self):
        repo = self.layout_repo()
        commit = repo.git("rev-parse", "HEAD")
        result, text, out = self.build(repo.root)
        self.assertEqual(result.exit_code, 0, text)
        members = build_release.release_members(repo.root, commit)
        self.assertEqual(members, archive_members(out))
        self.assertEqual(
            build_release.payload_identity(members, build_release.RUNTIME_PAYLOAD_EXCLUDE),
            printed(text, "runtime_payload_identity"),
        )

    def test_windows_line_ending_checkout_uses_commit_bytes_and_index_modes(self):
        repo = self.scratch()
        repo.git("config", "core.autocrlf", "true")
        binary = b"\x00\x01\r\n\x02\r\n"
        repo.write({".gitattributes": b"*.bin -text\n", "notes.txt": b"one\ntwo\n", "data.bin": binary, "tool.sh": b"echo tool\n"})
        repo.git("add", "--", ".")
        repo.git("update-index", "--chmod=+x", "tool.sh")
        repo.git("commit", "-q", "-m", "eol")
        repo.write({"notes.txt": b"one\r\ntwo\r\n"})
        result, text, out = self.build(repo.root)
        self.assertEqual(result.exit_code, 0, text)
        with zipfile.ZipFile(out) as zf:
            self.assertEqual(zf.read("notes.txt"), b"one\ntwo\n")
            self.assertEqual(zf.read("data.bin"), binary)
            modes = {i.orig_filename: i.external_attr >> 16 for i in zf.infolist()}
        self.assertEqual(modes["tool.sh"], 0o100755)
        self.assertEqual(modes["notes.txt"], 0o100644)

    def test_golden_archive_digest_is_platform_independent(self):
        repo = self.layout_repo()
        commit = repo.git("rev-parse", "HEAD")
        result, text, out = self.build(repo.root)
        self.assertEqual(result.exit_code, 0, text)
        self.assertEqual(commit, GOLDEN_COMMIT)
        self.assertEqual(hashlib.sha256(out.read_bytes()).hexdigest(), GOLDEN_ARCHIVE_SHA256)


BR24_ROOTS = (".codex-plugin/", "skills/", "hooks/", "contracts/skills/", "scripts/", "assets/")
FORBIDDEN_SKILLS_ONLY_ROOTS = ("commands", "agents", "workflows", ".claude-plugin", "docs", "tests")


class TestSkillsOnlyBuild(ScratchTestCase):
    def br24_files(self) -> dict:
        return {
            ".codex-plugin/plugin.json": b'{"name": "x", "skills": "./skills/"}\n',
            "skills/x/SKILL.md": b"---\nname: x\n---\n",
            "hooks/hooks-codex.json": b"{}\n",
            "contracts/skills/00-global.md": b"# contract\n",
            "scripts/tool.py": b"print('tool')\n",
            "assets/logo.png": b"\x89PNG\r\n",
            "LICENSE": b"MIT\n",
        }

    def outside_files(self) -> dict:
        return {
            "commands/c.md": b"# c\n",
            "agents/a.md": b"# a\n",
            "workflows/w.js": b"// w\n",
            ".claude-plugin/plugin.json": b"{}\n",
            "docs/d.md": b"# d\n",
            "tests/test_x.py": b"# t\n",
            "contracts/other.md": b"# not skills contracts\n",
            "README.md": b"# readme\n",
        }

    def test_skills_only_members_equal_br24_selection(self):
        repo = self.scratch()
        repo.commit({**self.br24_files(), **self.outside_files()}, "c1")
        result, text, out = self.build(repo.root, skills_only=True)
        self.assertEqual(result.exit_code, 0, text)
        with zipfile.ZipFile(out) as zf:
            self.assertEqual(sorted(zf.namelist()), sorted(self.br24_files()))
        self.assertIn("archive_kind=skills-only", text.splitlines())

        bare = self.scratch("no-license")
        files = self.br24_files()
        del files["LICENSE"]
        bare.commit(files, "no license")
        result, text, out = self.build(bare.root, "no-license.zip", skills_only=True)
        self.assertEqual(result.exit_code, 1, text)
        self.assertIn("error=missing_br24_member:LICENSE", text.splitlines())
        self.assertFalse(out.exists())

    def test_skills_only_rejects_mcp_configuration(self):
        cases = {
            ".codex-plugin/.mcp.json": {".codex-plugin/.mcp.json": b'{"mcpServers": {}}\n'},
            ".codex-plugin/plugin.json": {".codex-plugin/plugin.json": b'{"name": "x", "mcpServers": {}}\n'},
        }
        for index, (named, extra) in enumerate(cases.items()):
            with self.subTest(carrier=named):
                repo = self.scratch(f"mcp-{index}")
                repo.commit({**self.br24_files(), **extra}, "mcp")
                result, text, out = self.build(repo.root, f"mcp-{index}.zip", skills_only=True)
                self.assertEqual(result.exit_code, 1, text)
                self.assertIn(f"error=mcp_configuration:{named}", text.splitlines())
                self.assertFalse(out.exists())

    def test_skills_only_real_head_has_no_forbidden_roots_and_all_br24_paths(self):
        result, text, out = self.build(REPO, "skills-only.zip", skills_only=True)
        self.assertEqual(result.exit_code, 0, text)
        with zipfile.ZipFile(out) as zf:
            names = set(zf.namelist())
            manifest = json.loads(zf.read(".codex-plugin/plugin.json").decode("utf-8"))
        self.assertEqual([n for n in names if n.split("/")[0] in FORBIDDEN_SKILLS_ONLY_ROOTS], [])
        self.assertEqual([n for n in names if n.rsplit("/", 1)[-1] == ".mcp.json"], [])
        committed = _git_bytes(REPO, "ls-tree", "-r", "-z", "--name-only", "--full-tree", "HEAD").decode("utf-8")
        expected = {p for p in committed.split("\0") if p and (p == "LICENSE" or p.startswith(BR24_ROOTS))}
        self.assertEqual(names, expected)
        self.assertTrue(any(n.startswith(manifest["skills"].removeprefix("./")) for n in names))
        for referenced in (manifest["hooks"], manifest["interface"]["logo"], manifest["interface"]["composerIcon"]):
            with self.subTest(referenced=referenced):
                self.assertIn(referenced.removeprefix("./"), names)

    def test_skills_only_builds_twice_byte_identical_and_reports_payload_identity(self):
        repo = self.scratch()
        repo.commit({**self.br24_files(), **self.outside_files()}, "c1")
        first, text1, out1 = self.build(repo.root, "one.zip", skills_only=True)
        second, text2, out2 = self.build(repo.root, "two.zip", skills_only=True)
        self.assertEqual((first.exit_code, second.exit_code), (0, 0), text1 + text2)
        self.assertEqual(out1.read_bytes(), out2.read_bytes())
        expected = manifest_identity(archive_members(out1))
        self.assertEqual(printed(text1, "skills_only_payload_identity"), expected)
        self.assertEqual(printed(text1, "archive_sha256"), hashlib.sha256(out1.read_bytes()).hexdigest())


def _clone_info(info: zipfile.ZipInfo, date_time=None) -> zipfile.ZipInfo:
    new = zipfile.ZipInfo(info.orig_filename, date_time=date_time or info.date_time)
    new.filename = info.orig_filename
    new.compress_type = info.compress_type
    new.create_system = info.create_system
    new.create_version = info.create_version
    new.extract_version = info.extract_version
    new.external_attr = info.external_attr
    return new


def rewrite_zip(src: Path, dst: Path, *, drop=(), replace=None, modes=None, date_time=None, extra=(), comment=None):
    """Copy an archive while tampering with it; header fields are kept unless named."""
    replace, modes = replace or {}, modes or {}
    with zipfile.ZipFile(src) as zf:
        entries = [(info, zf.read(info)) for info in zf.infolist()]
        original_comment = zf.comment
    with zipfile.ZipFile(dst, "w") as out:
        out.comment = original_comment if comment is None else comment
        for info, data in entries:
            name = info.orig_filename
            if name in drop:
                continue
            new = _clone_info(info, date_time)
            if name in modes:
                new.external_attr = modes[name] << 16
            out.writestr(new, replace.get(name, data))
        for name, data, mode in extra:
            new = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            new.filename = name  # keep backslashes: the constructor normalizes os.sep on Windows
            new.create_system = 3
            new.external_attr = mode << 16
            out.writestr(new, data)
    return dst


def flip_stored_byte(path: Path, name: str) -> None:
    raw = bytearray(path.read_bytes())
    with zipfile.ZipFile(path) as zf:
        offset = zf.getinfo(name).header_offset
    name_len, extra_len = struct.unpack("<HH", bytes(raw[offset + 26:offset + 30]))
    raw[offset + 30 + name_len + extra_len] ^= 0xFF
    path.write_bytes(bytes(raw))


def commit_layout(repo: ScratchRepo) -> str:
    repo.write({
        "a.txt": b"lower\n",
        "run.sh": b"#!/bin/sh\necho run\n",
        LEDGER_DOCS[0]: b"# ledger\n",
        LEDGER_DOCS[1]: b"# readiness\n",
    })
    repo.git("add", "--", ".")
    repo.git("update-index", "--chmod=+x", "run.sh")
    repo.git("commit", "-q", "-m", "layout")
    return repo.git("rev-parse", "HEAD")


class TestVerifyIntegrity(ScratchTestCase):
    def verify(self, archive: Path, root: Path):
        report, text = self.quiet(build_release.verify_archive, archive, root)
        return report, text, text.splitlines()

    def built_layout(self):
        repo = self.scratch()
        commit_layout(repo)
        result, text, out = self.build(repo.root)
        self.assertEqual(result.exit_code, 0, text)
        return repo, out

    def assert_failed_naming(self, lines, report, expected_line):
        self.assertEqual(report.exit_code, 1, lines)
        self.assertIn(expected_line, lines)
        self.assertIn("verify=failed", lines)
        self.assertNotIn("verify=passed", lines)

    def test_verify_intact_release_reports_kind_and_passes(self):
        repo, out = self.built_layout()
        archive_before = hashlib.sha256(out.read_bytes()).hexdigest()
        state_before = repository_state(repo.root)
        report, text, lines = self.verify(out, repo.root)
        self.assertEqual(report.exit_code, 0, text)
        self.assertIn("archive_kind=release", lines)
        self.assertIn(f"archive_sha256={archive_before}", lines)
        self.assertEqual(lines[-1], "verify=passed")
        self.assertEqual(hashlib.sha256(out.read_bytes()).hexdigest(), archive_before)
        self.assertEqual(repository_state(repo.root), state_before)

    def test_verify_intact_skills_only_reports_kind(self):
        repo = self.scratch()
        repo.commit({
            ".codex-plugin/plugin.json": b'{"name": "x"}\n',
            "skills/x/SKILL.md": b"---\nname: x\n---\n",
            "LICENSE": b"MIT\n",
            "docs/d.md": b"# d\n",
        }, "c1")
        result, text, out = self.build(repo.root, skills_only=True)
        self.assertEqual(result.exit_code, 0, text)
        report, text, lines = self.verify(out, repo.root)
        self.assertEqual(report.exit_code, 0, text)
        self.assertIn("archive_kind=skills-only", lines)
        self.assertEqual(lines[-1], "verify=passed")

    def test_verify_names_missing_member(self):
        repo, out = self.built_layout()
        tampered = rewrite_zip(out, self.tmp / "missing.zip", drop={"a.txt"})
        report, _text, lines = self.verify(tampered, repo.root)
        self.assert_failed_naming(lines, report, "error=missing_member:a.txt")
        self.assertIn("archive_kind=release", lines)

    def test_verify_names_unexpected_member_matching_neither_kind(self):
        repo = self.scratch()
        repo.commit({
            ".codex-plugin/plugin.json": b'{"name": "x"}\n',
            "skills/x/SKILL.md": b"---\nname: x\n---\n",
            "LICENSE": b"MIT\n",
            "README.md": b"# readme\n",
        }, "c1")
        result, text, out = self.build(repo.root, skills_only=True)
        self.assertEqual(result.exit_code, 0, text)
        tampered = rewrite_zip(out, self.tmp / "extra.zip", extra=[("docs/x.md", b"# x\n", 0o100644)])
        report, _text, lines = self.verify(tampered, repo.root)
        self.assert_failed_naming(lines, report, "error=unexpected_member:docs/x.md")
        self.assertIn("archive_kind=skills-only", lines)

    def test_verify_names_crc_mismatch(self):
        repo, out = self.built_layout()
        flip_stored_byte(out, "a.txt")
        report, _text, lines = self.verify(out, repo.root)
        self.assert_failed_naming(lines, report, "error=crc_mismatch:a.txt")

    def test_verify_names_content_mismatch_with_valid_crc(self):
        repo, out = self.built_layout()
        tampered = rewrite_zip(out, self.tmp / "content.zip", replace={"a.txt": b"tampered\n"})
        report, _text, lines = self.verify(tampered, repo.root)
        self.assert_failed_naming(lines, report, "error=content_mismatch:a.txt")

    def test_verify_names_executable_mode_mismatch(self):
        repo, out = self.built_layout()
        tampered = rewrite_zip(out, self.tmp / "mode.zip", modes={"run.sh": 0o100644})
        report, _text, lines = self.verify(tampered, repo.root)
        self.assert_failed_naming(lines, report, "error=mode_mismatch:run.sh")

    def test_verify_reports_rebuild_mismatch(self):
        repo, out = self.built_layout()
        tampered = rewrite_zip(out, self.tmp / "dates.zip", date_time=(1981, 1, 1, 0, 0, 0))
        tampered_sha = hashlib.sha256(tampered.read_bytes()).hexdigest()
        report, _text, lines = self.verify(tampered, repo.root)
        self.assert_failed_naming(lines, report, f"error=rebuild_mismatch:{tampered_sha}")
        self.assertEqual([l for l in lines if l.startswith("error=")], [f"error=rebuild_mismatch:{tampered_sha}"])

    def test_verify_rejects_zip_slip_absolute_backslash_and_symlink_members(self):
        repo, out = self.built_layout()
        crafted = [
            ("../escape.txt", b"x\n", 0o100644),
            ("/abs.txt", b"x\n", 0o100644),
            ("a\\b.txt", b"x\n", 0o100644),
            ("link", b"../../outside", 0o120777),
        ]
        tampered = rewrite_zip(out, self.tmp / "slip.zip", extra=crafted)
        report, _text, lines = self.verify(tampered, repo.root)
        self.assertEqual(report.exit_code, 1, lines)
        for name, _data, _mode in crafted:
            with self.subTest(member=name):
                self.assertIn(f"error=unsafe_member:{name}", lines)
        self.assertNotIn("verify=passed", lines)

    def test_verify_passes_after_uncommitted_ledger_edit(self):
        repo, out = self.built_layout()
        repo.write({LEDGER_DOCS[0]: b"# ledger\narchive_sha256 recorded, uncommitted\n"})
        report, text, lines = self.verify(out, repo.root)
        self.assertEqual(report.exit_code, 0, text)
        self.assertEqual(lines[-1], "verify=passed")


class TestSecretPatternExports(unittest.TestCase):
    def test_suppression_primitives_are_exported(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node unavailable")
        module = (REPO / "hooks" / "secret-patterns.mjs").resolve().as_uri()
        script = (
            "const m = await import(%s);"
            "console.log(JSON.stringify({"
            "marker: m.ALLOW_MARKER instanceof RegExp,"
            "samples: m.DOC_SAMPLES instanceof Set && m.DOC_SAMPLES.size > 0,"
            "degenerate: typeof m.isDegenerateToken === 'function'}));" % json.dumps(module)
        )
        proc = subprocess.run(
            [node, "--input-type=module", "-e", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), {"marker": True, "samples": True, "degenerate": True})


def synthetic_aws_key() -> str:
    """A non-degenerate, vendor-shaped synthetic key, assembled so no literal exists in this file."""
    return "".join(["AK", "IA", "ZQ4T7MXB", "2KWL9RPD"])


def exported_doc_sample(prefix: str) -> str:
    module = (REPO / "hooks" / "secret-patterns.mjs").resolve().as_uri()
    script = "const m = await import(%s); console.log([...m.DOC_SAMPLES].find((s) => s.startsWith(%s)));" % (
        json.dumps(module), json.dumps(prefix))
    proc = subprocess.run(["node", "--input-type=module", "-e", script],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0 or not proc.stdout.strip():
        raise AssertionError("could not read DOC_SAMPLES: " + proc.stderr)
    return proc.stdout.strip()


class TestVerifySecretScan(ScratchTestCase):
    def built_with(self, extra: dict):
        repo = self.scratch()
        commit_layout(repo)
        repo.commit(extra, "secret-shaped content")
        result, text, out = self.build(repo.root)
        self.assertEqual(result.exit_code, 0, text)
        return repo, out

    def test_verify_fails_on_unmarked_high_confidence_key_naming_member_masked(self):
        key = synthetic_aws_key()
        repo, out = self.built_with({"config/keys.txt": ("# keys\naws_key_id = " + key + "\n").encode("ascii")})
        proc = self.cli(["--verify", out], cwd=repo.root, env=repo.env)
        lines = proc.stdout.splitlines()
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("secret_finding=config/keys.txt:2:aws-access-key-id", lines)
        self.assertIn("verify=failed", lines)
        self.assertNotIn(key, proc.stdout + proc.stderr)

    def test_verify_fails_when_allow_marker_is_on_previous_line(self):
        key = synthetic_aws_key()
        body = "# agentic-sdlc:allow-secret\naws_key_id = " + key + "\n"
        repo, out = self.built_with({"config/keys.txt": body.encode("ascii")})
        report, text = self.quiet(build_release.verify_archive, out, repo.root)
        self.assertEqual(report.exit_code, 1, text)
        self.assertIn("secret_finding=config/keys.txt:2:aws-access-key-id", text.splitlines())
        self.assertNotIn(key, text)

    def test_verify_lists_marker_sample_and_degenerate_suppressions(self):
        pem_header = "-----BEGIN " + "RSA PRIVATE KEY-----"
        body = "\n".join([
            pem_header + "  # agentic-sdlc:allow-secret",
            "documented = " + exported_doc_sample("AK" + "IA"),
            "placeholder = " + "AK" + "IA" + "A" * 16,
        ]) + "\n"
        repo, out = self.built_with({"notes/samples.txt": body.encode("ascii")})
        report, text = self.quiet(build_release.verify_archive, out, repo.root)
        lines = text.splitlines()
        self.assertEqual(report.exit_code, 0, text)
        self.assertIn("suppressed_finding=notes/samples.txt:1:private-key:allow-marker", lines)
        self.assertIn("suppressed_finding=notes/samples.txt:2:aws-access-key-id:documentation-sample", lines)
        self.assertIn("suppressed_finding=notes/samples.txt:3:aws-access-key-id:degenerate-token", lines)
        self.assertIn("suppressed_count=3", lines)
        self.assertEqual([l for l in lines if l.startswith("secret_finding=")], [])
        self.assertEqual(lines[-1], "verify=passed")

    def test_verify_fails_closed_when_node_unavailable(self):
        repo, out = self.built_with({"notes/plain.txt": b"nothing secret\n"})
        real_which = shutil.which
        with mock.patch.object(build_release.shutil, "which",
                               side_effect=lambda name, *a, **k: None if name == "node" else real_which(name, *a, **k)):
            report, text = self.quiet(build_release.verify_archive, out, repo.root)
        lines = text.splitlines()
        self.assertEqual(report.exit_code, 2, text)
        self.assertIn("error=node_unavailable", lines)
        self.assertNotIn("verify=passed", lines)


SUPPRESSION_REASONS = {"allow-marker", "documentation-sample", "degenerate-token"}


class TestRealTreeVerify(ScratchTestCase):
    def verify_real_head(self):
        state_before = repository_state(REPO)
        result, text, out = self.build(REPO, "release.zip")
        self.assertEqual(result.exit_code, 0, text)
        report, text = self.quiet(build_release.verify_archive, out, REPO)
        self.assertEqual(repository_state(REPO), state_before)
        return report, text, text.splitlines(), out

    def test_real_head_release_archive_verifies_and_lists_suppressions(self):
        report, text, lines, _out = self.verify_real_head()
        self.assertEqual([l for l in lines if l.startswith("secret_finding=")], [])
        self.assertEqual(report.exit_code, 0, text)
        self.assertIn("archive_kind=release", lines)
        suppressed = []
        for line in lines:
            if line.startswith("suppressed_finding="):
                member, line_no, label, reason = line[len("suppressed_finding="):].rsplit(":", 3)
                self.assertTrue(line_no.isdigit(), line)
                self.assertIn(reason, SUPPRESSION_REASONS, line)
                suppressed.append((member, label, reason))
        self.assertIn(f"suppressed_count={len(suppressed)}", lines)
        for expected in (
            ("tests/test_sensitive_redaction.py", "private-key", "allow-marker"),
            ("hooks/secret-patterns.mjs", "aws-access-key-id", "documentation-sample"),
            ("commands/git-safety-check.md", "password-literal", "allow-marker"),
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, suppressed)
        marked = [s for s in suppressed if s[2] == "allow-marker"]
        self.assertEqual([s for s in marked if s[0].startswith("skills/")], [])
        self.assertEqual([s for s in marked if s[0] == "tests/test_validate_artifacts.py"], [])

    def test_real_head_archive_contains_every_committed_transcript_fixture(self):
        _report, _text, lines, out = self.verify_real_head()
        committed = _git_bytes(
            REPO, "ls-tree", "-r", "-z", "--name-only", "HEAD", "tests/fixtures/transcripts/"
        ).decode("utf-8")
        fixtures = [p for p in committed.split("\0") if p]
        self.assertTrue(fixtures)
        with zipfile.ZipFile(out) as zf:
            names = set(zf.namelist())
        findings = [l for l in lines if l.startswith("secret_finding=")]
        for path in fixtures:
            with self.subTest(fixture=path):
                self.assertIn(path, names)
                self.assertEqual([l for l in findings if l.startswith(f"secret_finding={path}:")], [])


class TestHistoryArguments(ScratchTestCase):
    def scan_cli(self, argument: str):
        return self.quiet(build_release.main, ["--scan-history", argument])

    def test_url_shaped_arguments_rejected_before_any_git_call(self):
        cases = {
            "https://github.com/o/r.git": "https://github.com/o/r.git",
            "git@github.com:o/r.git": "git@github.com:o/r.git",
            "ssh://git@example.invalid/r.git": "ssh://***MASKED***@example.invalid/r.git",
        }
        for argument, shown in cases.items():
            with self.subTest(argument=argument):
                with mock.patch.object(build_release, "_run_git") as run_git:
                    code, text = self.scan_cli(argument)
                self.assertEqual(code, 2, text)
                self.assertIn(f"error=url_argument_rejected:{shown}", text.splitlines())
                run_git.assert_not_called()
        with self.subTest(argument="D:/audit/history.git"):
            refused = subprocess.CompletedProcess([], 1, b"", b"")
            with mock.patch.object(build_release, "_run_git", return_value=refused):
                code, text = self.scan_cli("D:/audit/history.git")
            self.assertNotIn("error=url_argument_rejected", text)

    def test_url_user_info_is_masked_in_rejection(self):
        value = "".join(["s3", "cr", "etV", "alue9"])
        argument = "https://user:" + value + "@example.invalid/r.git"
        with mock.patch.object(build_release, "_run_git") as run_git:
            code, text = self.scan_cli(argument)
        self.assertEqual(code, 2, text)
        self.assertIn("error=url_argument_rejected:https://***MASKED***@example.invalid/r.git", text.splitlines())
        self.assertNotIn(value, text)
        run_git.assert_not_called()

    def test_mirror_inside_repository_worktree_rejected(self):
        inside = REPO / "dist" / "history-mirror.git"
        self.assertFalse(inside.exists())
        code, text = self.scan_cli(str(inside))
        self.assertEqual(code, 2, text)
        self.assertIn("error=mirror_inside_repository", text.splitlines())
        self.assertFalse(inside.exists())

    def test_non_bare_directory_rejected(self):
        repo = self.scratch()
        repo.commit({"a.txt": b"a\n"}, "c1")
        code, text = self.scan_cli(str(repo.root))
        self.assertEqual(code, 2, text)
        self.assertIn("error=mirror_not_bare", text.splitlines())

    def test_missing_mirror_path_rejected(self):
        absent = self.tmp / "absent.git"
        code, text = self.scan_cli(str(absent))
        self.assertEqual(code, 2, text)
        self.assertIn("error=mirror_missing", text.splitlines())
        self.assertFalse(absent.exists())


HISTORY_GIT_SUBCOMMANDS = {"for-each-ref", "rev-list", "ls-tree", "cat-file", "rev-parse"}


def values(text: str, key: str) -> list:
    return [line[len(key) + 1:] for line in text.splitlines() if line.startswith(key + "=")]


class HistoryTestCase(ScratchTestCase):
    def mirror(self, repo: ScratchRepo, name: str = "mirror.git") -> Path:
        target = self.tmp / name
        repo.git("clone", "--mirror", "-q", str(repo.root), str(target), cwd=self.tmp)
        return target

    def scan(self, mirror: Path, **kwargs):
        report, text = self.quiet(build_release.scan_history, mirror, **kwargs)
        return report, text

    def pull_only_commit(self, repo: ScratchRepo, files: dict, ref: str, message: str = "pull request") -> str:
        repo.git("checkout", "-q", "-b", "pr-work")
        commit = repo.commit(files, message)
        repo.git("update-ref", ref, commit)
        repo.git("checkout", "-q", "main")
        repo.git("branch", "-q", "-D", "pr-work")
        return commit

    @staticmethod
    def finding_fields(line: str) -> dict:
        return dict(part.split("=", 1) for part in line.split(" "))


class TestHistorySecretScan(HistoryTestCase):
    def test_scans_all_refs_including_pull_refs_and_commit_messages(self):
        key = synthetic_aws_key()
        repo = self.scratch()
        repo.commit({"README.md": b"readme\n"}, "c1")
        message_commit = repo.commit({"b.txt": b"b\n"}, "rotate credentials\n\naws_key_id " + key)
        pull_commit = self.pull_only_commit(repo, {"leak.txt": ("key = " + key + "\n").encode("ascii")}, "refs/pull/7/head")
        report, text = self.scan(self.mirror(repo))
        self.assertEqual(report.exit_code, 1, text)
        self.assertEqual(values(text, "pull_refs_scanned"), ["1"])
        findings = [self.finding_fields(v) for v in values(text, "secret_finding")]
        by_path = {f["path"]: f for f in findings}
        self.assertEqual(by_path["leak.txt"]["first_commit"], pull_commit)
        self.assertEqual(by_path["leak.txt"]["label"], "aws-access-key-id")
        self.assertEqual(by_path[":commit-message"]["first_commit"], message_commit)
        for finding in findings:
            self.assertEqual(finding["state"], "unresolved")
            self.assertRegex(finding["key"], r"^[0-9a-f]{64}$")
        self.assertEqual(values(text, "scan_history"), ["failed"])

    def test_output_never_contains_raw_value(self):
        key = synthetic_aws_key()
        repo = self.scratch()
        repo.commit({"leak.txt": ("key = " + key + "\n").encode("ascii")}, "leak " + key)
        mirror = self.mirror(repo)
        proc = self.cli(["--scan-history", mirror], cwd=self.tmp, env=repo.env)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertTrue(values(proc.stdout, "secret_finding"))
        self.assertNotIn(key, proc.stdout + proc.stderr)
        report, text = self.scan(mirror)
        self.assertNotIn(key, text + "\n".join(report.lines))

    def test_same_sample_across_commits_and_shifted_line_share_one_key(self):
        key = synthetic_aws_key()
        repo = self.scratch()
        first = repo.commit({"notes.txt": ("intro\nkey = " + key + "\n").encode("ascii")}, "c0")
        for i in range(40):
            repo.commit({}, f"empty {i}")
        repo.commit({"notes.txt": ("intro\nmore\nlines\nkey = " + key + "\n").encode("ascii")}, "shift")
        report, text = self.scan(self.mirror(repo))
        findings = [self.finding_fields(v) for v in values(text, "secret_finding")]
        self.assertEqual(len(findings), 1, text)
        self.assertEqual(findings[0]["first_commit"], first)
        self.assertEqual(findings[0]["line"], "2")
        self.assertEqual(values(text, "commits_scanned"), ["42"])

    def test_sample_moved_to_new_path_gets_new_key(self):
        key = synthetic_aws_key()
        body = ("key = " + key + "\n").encode("ascii")
        repo = self.scratch()
        repo.commit({"a/keys.txt": body}, "add")
        repo.commit({"a/keys.txt": None, "b/keys.txt": body}, "move")
        report, text = self.scan(self.mirror(repo))
        findings = {f["path"]: f["key"] for f in map(self.finding_fields, values(text, "secret_finding"))}
        self.assertEqual(set(findings), {"a/keys.txt", "b/keys.txt"})
        self.assertNotEqual(findings["a/keys.txt"], findings["b/keys.txt"])

    def test_same_line_allow_marker_in_history_is_listed_as_suppressed(self):
        pem_header = "-----BEGIN " + "PRIVATE KEY-----"
        repo = self.scratch()
        commit = repo.commit({"fixture.txt": (pem_header + " # agentic-sdlc:allow-secret\n").encode("ascii")}, "fixture")
        report, text = self.scan(self.mirror(repo))
        self.assertEqual(report.exit_code, 0, text)
        self.assertIn(
            f"suppressed_finding=path=fixture.txt label=private-key first_commit={commit} line=1 reason=allow-marker",
            text.splitlines(),
        )
        self.assertEqual(values(text, "unresolved_count"), ["0"])

    def test_binary_blob_skipped_and_counted(self):
        key = synthetic_aws_key()
        repo = self.scratch()
        repo.commit({"blob.bin": b"\x00\x01key = " + key.encode("ascii") + b"\n"}, "binary")
        report, text = self.scan(self.mirror(repo))
        self.assertEqual(report.exit_code, 0, text)
        self.assertEqual(values(text, "binary_blobs_skipped"), ["1"])
        self.assertEqual(values(text, "secret_finding"), [])

    def test_git_invocations_are_local_only(self):
        repo = self.scratch()
        repo.commit({"a.txt": b"a\n"}, "c1")
        mirror = self.mirror(repo)
        with mock.patch.object(build_release.subprocess, "run", wraps=subprocess.run) as run:
            report, text = self.scan(mirror)
        self.assertEqual(report.exit_code, 0, text)
        git_calls = [c.args[0] for c in run.call_args_list if Path(str(c.args[0][0])).stem == "git"]
        self.assertTrue(git_calls)
        for argv in git_calls:
            with self.subTest(argv=argv):
                self.assertIn("protocol.allow=never", argv)
                self.assertIn("--git-dir", argv)
                subcommand = argv[argv.index("--git-dir") + 2]
                self.assertIn(subcommand, HISTORY_GIT_SUBCOMMANDS)

    def test_scan_leaves_source_repository_unchanged(self):
        repo = self.scratch()
        repo.commit({"a.txt": b"a\n"}, "c1")
        mirror = self.mirror(repo)
        before = repository_state(REPO)
        self.scan(mirror)
        self.assertEqual(repository_state(REPO), before)

    def test_node_bridge_spawns_are_batched(self):
        repo = self.scratch()
        for i in range(40):
            repo.commit({f"unique/file-{i}.txt": f"unique text {i}\n".encode("ascii")}, f"c{i}")
        mirror = self.mirror(repo)

        def node_calls(run):
            return [c for c in run.call_args_list if "--input-type=module" in c.args[0]]

        with mock.patch.object(build_release.subprocess, "run", wraps=subprocess.run) as run:
            report, text = self.scan(mirror)
        self.assertEqual(report.exit_code, 0, text)
        self.assertEqual(len(node_calls(run)), 1)
        with mock.patch.object(build_release, "SCAN_BATCH_SIZE", 16), \
                mock.patch.object(build_release.subprocess, "run", wraps=subprocess.run) as run:
            report, text = self.scan(mirror)
        items = int(values(text, "text_blobs_scanned")[0]) + int(values(text, "commits_scanned")[0])
        calls = node_calls(run)
        self.assertEqual(len(calls), math.ceil(items / 16))
        self.assertEqual(values(text, "scan_batches"), [str(len(calls))])
        sent = [json.loads(raw)["id"] for c in calls for raw in c.kwargs["input"].decode("utf-8").splitlines() if raw]
        self.assertEqual(len(sent), items)
        self.assertEqual(len(set(sent)), items)


class TestHistoryPrivatePaths(HistoryTestCase):
    def test_reports_added_then_deleted_audit_dump_with_first_commit_and_no_content(self):
        sentinel = "".join(["SENTINEL", "-", "audit", "-", "7f3c9e"])
        repo = self.scratch()
        repo.commit({"README.md": b"readme\n"}, "c1")
        added = repo.commit({"audit-docs/codex-audit-docs.md": ("dump " + sentinel + "\n").encode("ascii")}, "c2")
        repo.commit({"audit-docs/codex-audit-docs.md": None}, "c3")
        report, text = self.scan(self.mirror(repo))
        self.assertEqual(report.exit_code, 1, text)
        self.assertIn(
            f"private_path_finding=path=audit-docs/codex-audit-docs.md class=6 first_commit={added} state=unresolved",
            text.splitlines(),
        )
        self.assertNotIn(sentinel, text)

    def test_reports_classes_1_to_5(self):
        for cls in (1, 2, 3, 4, 5):
            with self.subTest(cls=cls):
                path = COMMITTED_CLASS_SAMPLES[cls]
                repo = self.scratch(f"class-{cls}")
                commit = repo.commit({"README.md": b"readme\n", path: b"private\n"}, f"class {cls}")
                report, text = self.scan(self.mirror(repo, f"class-{cls}.git"))
                self.assertEqual(report.exit_code, 1, text)
                self.assertIn(
                    f"private_path_finding=path={path} class={cls} first_commit={commit} state=unresolved",
                    text.splitlines(),
                )

    def test_reports_class_7_entries_from_crafted_trees(self):
        repo = self.scratch()
        base = repo.commit({"README.md": b"readme\n"}, "c1")
        crafted = repo.crafted_commit(
            [("100644", "README.md", b"readme\n"), ("120000", "link", b"../outside"),
             ("100644", "..", b"dotdot\n"), ("100644", "a\\b", b"backslash\n")],
            "refs/pull/3/head",
            parent=base,
        )
        report, text = self.scan(self.mirror(repo))
        self.assertEqual(report.exit_code, 1, text)
        lines = text.splitlines()
        for path in ("link", "..", "a\\b"):
            with self.subTest(path=path):
                self.assertIn(f"private_path_finding=path={path} class=7 first_commit={crafted} state=unresolved", lines)

    def test_private_path_only_reachable_from_pull_ref_is_reported(self):
        repo = self.scratch()
        repo.commit({"README.md": b"readme\n"}, "c1")
        pull = self.pull_only_commit(repo, {".handoffs/h.md": b"handoff\n"}, "refs/pull/9/head")
        report, text = self.scan(self.mirror(repo))
        self.assertEqual(report.exit_code, 1, text)
        self.assertIn(f"private_path_finding=path=.handoffs/h.md class=6 first_commit={pull} state=unresolved", text.splitlines())


def second_synthetic_aws_key() -> str:
    return "".join(["AK", "IA", "R8N2W5QX", "7JT4HV6M"])


def line_sha256(line: str) -> str:
    return hashlib.sha256(line.strip().encode("utf-8")).hexdigest()


class TestFindingsRecord(HistoryTestCase):
    VALID_ACCEPTANCE = {
        "kind": "private-path",
        "path": "audit-docs/dump.md",
        "class": 6,
        "state": "maintainer-accepted",
        "accepted_on": "2026-09-15",
        "maintainer_reference": "https://example.invalid/owner/review/1",
    }

    def record_file(self, payload, name: str = "record.json") -> Path:
        target = self.tmp / "records" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        data = payload if isinstance(payload, bytes) else json.dumps(payload, indent=2).encode("utf-8")
        target.write_bytes(data)
        return target

    def two_key_mirror(self):
        repo = self.scratch()
        line_a = "key = " + synthetic_aws_key()
        line_b = "key = " + second_synthetic_aws_key()
        repo.commit({"a.txt": (line_a + "\n").encode("ascii"), "b.txt": (line_b + "\n").encode("ascii")}, "keys")
        return self.mirror(repo), line_a, line_b

    @staticmethod
    def secret_entry(path: str, line: str, state: str) -> dict:
        return {"kind": "secret", "path": path, "label": "aws-access-key-id", "line_sha256": line_sha256(line), "state": state}

    def finding_states(self, text: str) -> dict:
        return {f["path"]: f["state"] for f in map(self.finding_fields, values(text, "secret_finding"))}

    def test_secret_findings_resolved_by_inspected_sample_or_false_positive_exit_zero(self):
        mirror, line_a, line_b = self.two_key_mirror()
        record = self.record_file({"entries": [
            self.secret_entry("a.txt", line_a, "inspected-sample"),
            self.secret_entry("b.txt", line_b, "false-positive"),
        ]})
        report, text = self.scan(mirror, record=record)
        self.assertEqual(report.exit_code, 0, text)
        self.assertEqual(self.finding_states(text), {"a.txt": "inspected-sample", "b.txt": "false-positive"})
        self.assertEqual(values(text, "unresolved_count"), ["0"])
        self.assertEqual(values(text, "scan_history"), ["passed"])

    def test_unrecorded_secret_finding_stays_unresolved(self):
        mirror, line_a, _line_b = self.two_key_mirror()
        record = self.record_file({"entries": [self.secret_entry("a.txt", line_a, "inspected-sample")]})
        report, text = self.scan(mirror, record=record)
        self.assertEqual(report.exit_code, 1, text)
        self.assertEqual(self.finding_states(text), {"a.txt": "inspected-sample", "b.txt": "unresolved"})
        self.assertEqual(values(text, "unresolved_count"), ["1"])

    def test_record_key_ignores_commit_and_line_number(self):
        repo = self.scratch()
        line = "key = " + synthetic_aws_key()
        repo.commit({"a.txt": (line + "\n").encode("ascii")}, "first")
        repo.commit({"a.txt": ("header\n\n" + line + "\n").encode("ascii")}, "moved down")
        record = self.record_file({"entries": [self.secret_entry("a.txt", "  " + line + "  ", "false-positive")]})
        report, text = self.scan(self.mirror(repo), record=record)
        self.assertEqual(report.exit_code, 0, text)
        self.assertEqual(self.finding_states(text), {"a.txt": "false-positive"})

    def test_private_path_resolved_only_by_valid_maintainer_accepted_entry(self):
        repo = self.scratch()
        repo.commit({"README.md": b"readme\n", "audit-docs/dump.md": b"dump\n"}, "dump")
        mirror = self.mirror(repo)
        missing_date = {k: v for k, v in self.VALID_ACCEPTANCE.items() if k != "accepted_on"}
        invalid = {
            "accepted_on missing": missing_date,
            "accepted_on soon": {**self.VALID_ACCEPTANCE, "accepted_on": "soon"},
            "accepted_on impossible date": {**self.VALID_ACCEPTANCE, "accepted_on": "2026-02-30"},
            "http reference": {**self.VALID_ACCEPTANCE, "maintainer_reference": "http://example.invalid/owner/review/1"},
            "relative reference": {**self.VALID_ACCEPTANCE, "maintainer_reference": "owner/review/1"},
            "other state": {**self.VALID_ACCEPTANCE, "state": "inspected-sample"},
        }
        for index, (label, entry) in enumerate(invalid.items()):
            with self.subTest(case=label):
                record = self.record_file({"entries": [entry]}, f"invalid-{index}.json")
                report, text = self.scan(mirror, record=record)
                self.assertEqual(report.exit_code, 1, text)
                self.assertTrue(values(text, "findings_record_entry_invalid"), text)
                self.assertIn("private_path_finding=path=audit-docs/dump.md class=6 first_commit=", text)
                self.assertIn("state=unresolved", values(text, "private_path_finding")[0])
        record = self.record_file({"entries": [self.VALID_ACCEPTANCE]}, "valid.json")
        report, text = self.scan(mirror, record=record)
        self.assertEqual(report.exit_code, 0, text)
        self.assertTrue(values(text, "private_path_finding")[0].endswith("state=maintainer-accepted"), text)

    def test_record_rejects_value_bearing_fields(self):
        mirror, line_a, _line_b = self.two_key_mirror()
        entry = {**self.secret_entry("a.txt", line_a, "inspected-sample"), "matched_line": line_a}
        record = self.record_file({"entries": [entry]})
        report, text = self.scan(mirror, record=record)
        self.assertNotEqual(report.exit_code, 0, text)
        self.assertIn("findings_record_entry_invalid=0:matched_line", text.splitlines())
        self.assertNotIn(synthetic_aws_key(), text)
        self.assertEqual(self.finding_states(text)["a.txt"], "unresolved")

    def test_record_sha256_is_reported(self):
        mirror, line_a, line_b = self.two_key_mirror()
        record = self.record_file({"entries": [self.secret_entry("a.txt", line_a, "inspected-sample")]})
        _report, text = self.scan(mirror, record=record)
        self.assertEqual(values(text, "findings_record_sha256"), [hashlib.sha256(record.read_bytes()).hexdigest()])

    def test_absent_or_unreadable_record(self):
        mirror, _line_a, _line_b = self.two_key_mirror()
        report, text = self.scan(mirror, record=self.tmp / "records" / "absent.json")
        self.assertEqual(report.exit_code, 1, text)
        self.assertIn("findings_record=absent", text.splitlines())
        self.assertEqual(set(self.finding_states(text).values()), {"unresolved"})
        unreadable = self.record_file(b"not json", "unreadable.json")
        with mock.patch.object(build_release, "_run_git") as run_git:
            report, text = self.scan(mirror, record=unreadable)
        self.assertEqual(report.exit_code, 2, text)
        self.assertIn("error=findings_record_unreadable", text.splitlines())
        run_git.assert_not_called()

    def test_cli_reads_fixed_record_path_under_repository_root(self):
        self.assertEqual(
            build_release.FINDINGS_RECORD_PATH,
            REPO / "tests" / "artifacts" / "publication" / "history" / "reviewed-findings.json",
        )
        repo = self.scratch()
        repo.commit({"a.txt": b"a\n"}, "c1")
        mirror = self.mirror(repo)
        with mock.patch.object(build_release, "scan_history", return_value=mock.Mock(exit_code=0, lines=[])) as scan:
            code, _text = self.quiet(build_release.main, ["--scan-history", str(mirror)])
        self.assertEqual(code, 0)
        scan.assert_called_once()
        self.assertEqual(scan.call_args.kwargs["record"], build_release.FINDINGS_RECORD_PATH)

    def test_scan_history_cli_accepts_no_record_option(self):
        repo = self.scratch()
        repo.commit({"a.txt": b"a\n"}, "c1")
        mirror = self.mirror(repo)
        record = self.record_file({"entries": []})
        proc = self.cli(["--scan-history", mirror, "--findings-record", record], cwd=self.tmp, env=repo.env)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("unrecognized arguments", proc.stderr)
        help_proc = self.cli(["--help"], cwd=self.tmp, env=repo.env)
        self.assertNotIn("findings-record", help_proc.stdout)


CI_WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
SOURCE_STEPS = [
    ("Version consistency", "python3 scripts/bump_version.py --release-check"),
    ("Static checks", "python3 scripts/check_all.py"),
    ("Skill harness", "python3 tests/skills/harness.py"),
    ("Unit tests", "python3 -m unittest discover -s tests -v"),
]
ARCHIVE_STEPS = [
    ("Archive build", "scripts/build_release.py --output"),
    ("Archive verify", "scripts/build_release.py --verify"),
    ("Archive extract to clean directory", "python3 -m zipfile -e"),
    ("Archive gate: version check", "python3 scripts/bump_version.py --check"),
    ("Archive gate: release check", "python3 scripts/bump_version.py --release-check"),
    ("Archive gate: static checks", "python3 scripts/check_all.py"),
    ("Archive gate: skill harness", "python3 tests/skills/harness.py"),
    ("Archive gate: unit tests", "python3 -m unittest discover -s tests -v"),
    ("Archive gate: coverage comparison", "check_archive_gate_log"),
]


def ci_steps(text: str) -> list:
    """(name, run, block text) for each '- ' step under 'steps:', in file order (stdlib text parse)."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "steps:")
    blocks, current = [], None
    for line in lines[start + 1:]:
        if line.startswith("      - "):
            current = [line]
            blocks.append(current)
        elif current is not None and (line.startswith("        ") or not line.strip()):
            current.append(line)
    steps = []
    for block in blocks:
        name, run = None, []
        for i, line in enumerate(block):
            body = line.strip().removeprefix("- ")
            if body.startswith("name: "):
                name = body[len("name: "):].strip().strip('"')
            elif body == "run: |":
                indent = len(block[i + 1]) - len(block[i + 1].lstrip())
                run = [l[indent:] for l in block[i + 1:] if l.strip() and len(l) - len(l.lstrip()) >= indent]
            elif body.startswith("run: "):
                run = [body[len("run: "):]]
        steps.append((name, "\n".join(run), "\n".join(block)))
    return steps


class TestCiArchiveSteps(unittest.TestCase):
    def setUp(self):
        self.text = CI_WORKFLOW.read_text(encoding="utf-8")
        self.steps = ci_steps(self.text)
        self.names = [name for name, _run, _block in self.steps]

    def test_source_steps_and_triggers_unchanged(self):
        self.assertIn("on:\n  push:\n  pull_request:\n", self.text)
        self.assertIn("os: [ubuntu-latest, windows-latest]", self.text)
        source = [(name, run) for name, run, _block in self.steps if name in dict(SOURCE_STEPS)]
        self.assertEqual(source, SOURCE_STEPS)

    def test_archive_steps_follow_source_steps_in_order(self):
        unit_index = self.names.index("Unit tests")
        appended = self.steps[unit_index + 1:]
        self.assertEqual([name for name, _run, _block in appended], [name for name, _cmd in ARCHIVE_STEPS])
        for (name, run, block), (_expected, command) in zip(appended, ARCHIVE_STEPS):
            with self.subTest(step=name):
                self.assertIn(command, run)
                self.assertIn("shell: bash", block)
                if name.startswith("Archive gate:") and "coverage" not in name:
                    self.assertIn("working-directory: ${{ runner.temp }}/archive-extract/agentic-sdlc", block)

    def test_archive_steps_create_no_commit_and_reference_no_test_artifacts(self):
        self.assertNotIn("git commit", self.text)
        self.assertNotIn("tests/artifacts", self.text)

    def test_archive_logs_are_named_distinctly(self):
        unit_index = self.names.index("Unit tests")
        for name, run, _block in self.steps[unit_index + 1:]:
            with self.subTest(step=name):
                self.assertTrue(name.startswith("Archive"), name)
        targets = re.findall(r'tee "([^"]+)"', self.text)
        self.assertTrue(targets)
        for target in targets:
            with self.subTest(target=target):
                self.assertTrue(target.rsplit("/", 1)[-1].startswith("archive-"), target)


SAMPLE_TESTS = b'''import unittest


class Sample(unittest.TestCase):
    def test_one(self):
        self.assertTrue(True)

    @unittest.skip("named reason")
    def test_skipped(self):
        """Docstring line."""

    def test_two(self):
        self.assertTrue(True)
'''

GOOD_ARCHIVE_LOG = """test_one (test_sample.Sample.test_one) ... ok
test_skipped (test_sample.Sample.test_skipped)
Docstring line. ... skipped 'named reason'
test_two (test_sample.Sample.test_two) ... ok

----------------------------------------------------------------------
Ran 3 tests in 0.001s

OK (skipped=1)
"""


class TestArchiveGateCoverage(ScratchTestCase):
    def source_tree(self) -> Path:
        root = self.tmp / "source"
        (root / "tests").mkdir(parents=True)
        (root / "tests" / "test_sample.py").write_bytes(SAMPLE_TESTS)
        self.assertFalse((root / "tests" / "__init__.py").exists())
        return root

    def check(self, log_text: str, root: Path):
        log = self.tmp / "archive-gate-unit-tests.log"
        log.write_bytes(log_text.encode("utf-8"))
        return self.quiet(build_release.check_archive_gate_log, log, root)

    def test_equal_count_with_named_skips_passes_on_tree_without_tests_init(self):
        code, text = self.check(GOOD_ARCHIVE_LOG, self.source_tree())
        lines = text.splitlines()
        self.assertEqual(code, 0, text)
        self.assertIn("source_tests=3", lines)
        self.assertIn("archive_tests_run=3", lines)
        self.assertIn("archive_skipped=1", lines)
        self.assertIn("skip_reason=test_sample.Sample.test_skipped:named reason", lines)
        self.assertEqual(lines[-1], "archive_coverage=passed")

    def test_crlf_log_from_windows_runner_passes(self):
        # Windows Python writes text-mode stdout/stderr with CRLF, so a tee'd archive log carries \r\n.
        crlf_log = GOOD_ARCHIVE_LOG.replace("\n", "\r\n")
        code, text = self.check(crlf_log, self.source_tree())
        lines = text.splitlines()
        self.assertEqual(code, 0, text)
        self.assertIn("skip_reason=test_sample.Sample.test_skipped:named reason", lines)
        self.assertEqual(lines[-1], "archive_coverage=passed")

    def test_lost_test_count_fails(self):
        log = GOOD_ARCHIVE_LOG.replace("test_two (test_sample.Sample.test_two) ... ok\n", "").replace("Ran 3", "Ran 2")
        code, text = self.check(log, self.source_tree())
        self.assertEqual(code, 1, text)
        self.assertIn("archive_coverage=failed", text.splitlines())

    def test_failing_log_fails(self):
        log = GOOD_ARCHIVE_LOG.replace(
            "test_two (test_sample.Sample.test_two) ... ok", "test_two (test_sample.Sample.test_two) ... FAIL"
        ).replace("OK (skipped=1)", "FAIL: test_two (test_sample.Sample.test_two)\n\nFAILED (failures=1, skipped=1)")
        code, text = self.check(log, self.source_tree())
        self.assertEqual(code, 1, text)
        self.assertIn("archive_coverage=failed", text.splitlines())

    def test_empty_skip_reason_fails(self):
        log = GOOD_ARCHIVE_LOG.replace("skipped 'named reason'", "skipped ''")
        code, text = self.check(log, self.source_tree())
        self.assertEqual(code, 1, text)
        self.assertIn("archive_coverage=failed", text.splitlines())

    def test_source_count_unavailable_fails(self):
        empty_root = self.tmp / "no-tests"
        empty_root.mkdir()
        code, text = self.check(GOOD_ARCHIVE_LOG, empty_root)
        self.assertEqual(code, 1, text)
        self.assertIn("error=source_count_unavailable", text.splitlines())


class TestSkillsOnlyListingManifest(ScratchTestCase):
    """AC108: the Ölçüt 4 listing rules hold on the manifest inside the skills-only archive.

    The BR7 rules live only in slice A's helpers in tests/test_packaging_metadata.py; they are
    imported lazily here so an ImportError affects only the listing-rules test.
    """

    def skills_only_archive(self) -> Path:
        result, text, out = self.build(REPO, "skills-only.zip", skills_only=True)
        self.assertEqual(result.exit_code, 0, text)
        return out

    def test_archive_codex_manifest_is_committed_manifest(self):
        out = self.skills_only_archive()
        with zipfile.ZipFile(out) as zf:
            member = zf.read(".codex-plugin/plugin.json")
        self.assertEqual(member, _git_bytes(REPO, "cat-file", "blob", "HEAD:.codex-plugin/plugin.json"))

    def test_archive_codex_manifest_meets_listing_rules(self):
        out = self.skills_only_archive()
        from test_packaging_metadata import asset_violations, listing_violations

        extract_dir = self.tmp / "skills-only-extract"
        with zipfile.ZipFile(out) as zf:
            zf.extractall(extract_dir)
        manifest = json.loads((extract_dir / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        record = json.loads(_git_bytes(REPO, "cat-file", "blob", "HEAD:docs/publication/link-checks.json").decode("utf-8"))
        self.assertEqual(listing_violations(manifest, record, extract_dir), [])
        self.assertEqual(asset_violations(manifest["interface"], extract_dir), [])
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertEqual(manifest["hooks"], "./hooks/hooks-codex.json")


class TestVerifyOutsideCheckout(ScratchTestCase):
    def built(self):
        repo = self.scratch()
        commit = commit_layout(repo)
        result, text, out = self.build(repo.root)
        self.assertEqual(result.exit_code, 0, text)
        return repo, commit, out

    def assert_unavailable(self, proc, commit):
        lines = proc.stdout.splitlines()
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn(f"error=source_commit_unavailable:{commit}", lines)
        self.assertNotIn("verify=passed", lines)
        self.assertEqual([l for l in lines if l.startswith(("archive_kind=", "content_", "mode_"))], [])

    def test_verify_outside_git_checkout_names_unavailable_commit(self):
        repo, commit, out = self.built()
        nogit = self.tmp / "nogit"
        nogit.mkdir()
        env = {**repo.env, "GIT_CEILING_DIRECTORIES": str(self.tmp)}
        proc = self.cli(["--verify", out], cwd=nogit, env=env)
        self.assert_unavailable(proc, commit)

    def test_verify_in_checkout_lacking_commit_names_commit(self):
        repo, commit, out = self.built()
        other = self.scratch("other")
        other.commit({"unrelated.txt": b"other history\n"}, "other")
        proc = self.cli(["--verify", out], cwd=other.root, env=other.env)
        self.assert_unavailable(proc, commit)

    def test_verify_without_recorded_commit_comment_fails(self):
        repo, _commit, out = self.built()
        tampered = rewrite_zip(out, self.tmp / "nocomment.zip", comment=b"")
        report, text = self.quiet(build_release.verify_archive, tampered, repo.root)
        self.assertEqual(report.exit_code, 1, text)
        self.assertIn("error=source_commit_unrecorded", text.splitlines())
        self.assertNotIn("verify=passed", text.splitlines())


if __name__ == "__main__":
    unittest.main()
