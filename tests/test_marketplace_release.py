"""Committed-source publication staging; no original Git or external publication."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from scripts import build_release
from test_release_distribution import ScratchRepo, repository_state


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "prepare_marketplace_release.py"


def tree_bytes(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file() and ".git" not in path.parts}


class TestMarketplacePreparation(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'NTFS junction verification requires Windows')
    def test_verify_rejects_internal_junction(self):
        result = self.run_prepare()
        self.assertEqual(result.exit_code, 0, result.lines)
        external = self.base / 'outside packet'
        external.mkdir()
        junction = self.output / 'clean-source' / 'external-junction'
        self.assertTrue(external.resolve().is_relative_to(self.base.resolve()))
        self.assertTrue(junction.parent.resolve().is_relative_to(self.base.resolve()))
        command = str(Path(os.environ['SystemRoot']) / 'System32' / 'cmd.exe')
        proc = subprocess.run([command, '/d', '/c', 'mklink', '/J', str(junction), str(external)],
                              capture_output=True, timeout=10)
        self.assertEqual(proc.returncode, 0, 'Temporary NTFS junction could not be created')
        self.assertTrue(junction.is_junction())
        result = self.run_verify()
        self.assertEqual(result.exit_code, 1, result.lines)
        self.assertIn('error=unsafe_output_member:clean-source/external-junction', result.lines)

    @classmethod
    def setUpClass(cls):
        if not build_release._program_on_absolute_path("git") or not build_release._program_on_absolute_path("node"):
            raise unittest.SkipTest("Git/Node unavailable; committed publication staging not exercised")
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True,
                                text=True, encoding="utf-8")
        if result.returncode:
            raise unittest.SkipTest("Source checkout has no recorded commit; staging provenance not exercised")
        cls.commit = result.stdout.strip()
        cls.source = build_release._commit_members(cls.commit, cwd=REPO)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.output = self.base / "reviewed publication packet"

    def module(self):
        self.assertTrue(SCRIPT.is_file(), "publication staging helper is not implemented")
        from scripts import prepare_marketplace_release
        return prepare_marketplace_release

    def run_prepare(self, *, source=None, repo=REPO, commit=None, output=None):
        module = self.module()
        with contextlib.ExitStack() as stack:
            if source is not None:
                stack.enter_context(mock.patch.object(build_release, "_commit_members",
                                                       return_value=source))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            return module.prepare(repo, commit or self.commit, output or self.output)

    def run_verify(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.module().verify_preparation(REPO, self.commit, self.output)

    def test_staging_uses_committed_bytes_and_preserves_source(self):
        self.module()
        repo = ScratchRepo(self.base, "source")
        repo.write({path: blob for path, (_mode, blob) in self.source.items()})
        repo.git("add", "--all")
        repo.git("commit", "-q", "-m", "disposable publication fixture")
        commit = repo.git("rev-parse", "HEAD")
        original = (repo.root / "README.md").read_bytes()
        (repo.root / "README.md").write_bytes(b"uncommitted tracked edit\n")
        (repo.root / "untracked-private.txt").write_bytes(b"never distribute this\n")
        before_git, before_files = repository_state(repo.root), tree_bytes(repo.root)
        result = self.run_prepare(repo=repo.root, commit=commit)
        self.assertEqual(result.exit_code, 0, result.lines)
        clean = self.output / "clean-source"
        self.assertEqual((clean / "README.md").read_bytes(), original)
        self.assertFalse((clean / ".git").exists())
        self.assertFalse((clean / "untracked-private.txt").exists())
        self.assertFalse((clean / "audit-docs/codex-audit-docs.md").exists())
        self.assertEqual(repository_state(repo.root), before_git)
        self.assertEqual(tree_bytes(repo.root), before_files)

    def test_missing_companion_rejects_without_output(self):
        source = dict(self.source)
        del source["docs/runtime-adapter.md"]
        result = self.run_prepare(source=source)
        self.assertEqual(result.exit_code, 1, result.lines)
        self.assertIn("error=missing_companion:docs/runtime-adapter.md", result.lines)
        self.assertFalse(self.output.exists())

    def test_secret_in_source_rejects_without_output(self):
        source = dict(self.source)
        token = ("gh" + "p_") + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
        source["notes/leaked.txt"] = ("100644", ("token=" + token + "\n").encode())
        result = self.run_prepare(source=source)
        self.assertEqual(result.exit_code, 1, result.lines)
        self.assertTrue(any("notes/leaked.txt" in line and "secret" in line
                            for line in result.lines), result.lines)
        self.assertNotIn(token, "\n".join(result.lines))
        self.assertFalse(self.output.exists())

    def test_existing_output_is_never_changed(self):
        self.output.mkdir()
        for empty in (True, False):
            if not empty:
                (self.output / "keep.txt").write_bytes(b"original user data")
            before = tree_bytes(self.output)
            result = self.run_prepare()
            self.assertEqual(result.exit_code, 1, result.lines)
            self.assertIn("error=output_exists", result.lines)
            self.assertEqual(tree_bytes(self.output), before)

    def test_invalid_commit_rejects_without_output(self):
        for commit in ("HEAD", "abc123", "A" * 40, "0" * 40):
            with self.subTest(commit=commit):
                result = self.run_prepare(commit=commit)
                self.assertNotEqual(result.exit_code, 0, result.lines)
                self.assertFalse(self.output.exists())

    def test_vendor_layout_readmes_and_versions(self):
        result = self.run_prepare()
        self.assertEqual(result.exit_code, 0, result.lines)
        grok = self.output / "grok-catalog"
        gp = grok / "external_plugins/agentic-sdlc"
        gc = json.loads((grok / ".grok-plugin/marketplace.json").read_bytes())
        self.assertEqual(gc["plugins"][0]["source"],
                         {"type": "local", "path": "./external_plugins/agentic-sdlc"})
        self.assertFalse((gp / "hooks/hooks.json").exists())
        self.assertEqual(len(list((gp / "skills").glob("*/SKILL.md"))), 16)
        self.assertEqual(len(list((gp / "commands").glob("*.md"))), 1)
        self.assertEqual(len(list((gp / "agents").glob("*.md"))), 9)
        wire = json.loads((gp / "hooks/hooks-grok.json").read_bytes())
        self.assertEqual(set(wire["hooks"]), {"PreToolUse"})
        self.assertEqual(sum(len(group["hooks"]) for group in wire["hooks"]["PreToolUse"]), 3)
        zp = self.output / "zcode-catalog/plugins/agentic-sdlc"
        zc = json.loads((self.output / "zcode-catalog/marketplace.json").read_bytes())
        manifest = json.loads((zp / ".zcode-plugin/plugin.json").read_bytes())
        entry = zc["plugins"][0]
        self.assertEqual(entry["source"], "./plugins/agentic-sdlc")
        self.assertEqual(entry["version"], manifest["version"])
        self.assertEqual(entry["description_i18n"], manifest["description_i18n"])
        self.assertEqual(set(zc["description_i18n"]), {"en", "zh-CN"})
        for name in ("README.md", "README_CN.md"):
            text = (zp / name).read_text(encoding="utf-8")
            for signal in ("Node.js", "Python", "Git", "MIT", "obra/superpowers",
                           "PreToolUse", "PostToolUse", "SessionStart", "LICENSE"):
                self.assertIn(signal, text, (name, signal))
            self.assertNotIn("../docs/", text)
        self.assertEqual((zp / "LICENSE").read_bytes(), self.source["LICENSE"][1])
        for path, (_mode, blob) in self.source.items():
            if path.startswith(("skills/", "hooks/", "agents/", "commands/", "contracts/")):
                self.assertEqual((gp / path).read_bytes(), blob, path)
                self.assertEqual((zp / path).read_bytes(), blob, path)

    def test_verify_rejects_changed_output(self):
        self.assertEqual(self.run_prepare().exit_code, 0)
        self.assertEqual(self.run_verify().exit_code, 0)
        target = self.output / "clean-source/README.md"
        original = target.read_bytes()
        target.write_bytes(b"tampered content\n")
        self.assertEqual(self.run_verify().exit_code, 1)
        target.write_bytes(original)
        extra = self.output / "clean-source/extra.txt"
        extra.write_bytes(b"unexpected member")
        self.assertEqual(self.run_verify().exit_code, 1)
        extra.unlink()
        target.unlink()
        self.assertEqual(self.run_verify().exit_code, 1)

    def test_partial_write_rollback_preserves_existing_siblings(self):
        self.module()
        sibling = self.base / "keep.txt"
        sibling.write_bytes(b"existing data")
        original_open = Path.open

        def failed_receipt(path, *args, **kwargs):
            if path == self.output / "receipt.json" and args and "x" in args[0]:
                raise OSError("injected output failure")
            return original_open(path, *args, **kwargs)

        with mock.patch.object(Path, "open", failed_receipt):
            result = self.run_prepare()
        self.assertEqual(result.exit_code, 2, result.lines)
        self.assertFalse(self.output.exists())
        self.assertEqual(sibling.read_bytes(), b"existing data")

    def test_unsafe_destination_rejects_without_output(self):
        for output in (REPO, REPO.parent, REPO / ".git/new-packet",
                       REPO / "skills/new-packet", REPO / "new-packet"):
            with self.subTest(output=output):
                result = self.run_prepare(output=output)
                self.assertNotEqual(result.exit_code, 0, result.lines)
                if output not in (REPO, REPO.parent):
                    self.assertFalse(output.exists())
        if hasattr(os, "symlink"):
            alias = self.base / "alias"
            try:
                alias.symlink_to(REPO, target_is_directory=True)
            except OSError:
                return  # Win32 symlink privilege absence does not skip other boundaries.
            result = self.run_prepare(output=alias / "build/new-packet")
            self.assertNotEqual(result.exit_code, 0, result.lines)

    def test_nested_source_root_cannot_bypass_destination_policy(self):
        result = self.run_prepare(repo=REPO / "skills")
        self.assertNotEqual(result.exit_code, 0, result.lines)
        self.assertFalse(self.output.exists())

    def test_invalid_manifest_rejects_without_output(self):
        source = dict(self.source)
        path = ".grok-plugin/plugin.json"
        manifest = json.loads(source[path][1])
        del manifest["author"]
        source[path] = (source[path][0], json.dumps(manifest).encode())
        result = self.run_prepare(source=source)
        self.assertEqual(result.exit_code, 1, result.lines)
        self.assertIn("error=manifest_invalid:" + path, result.lines)
        self.assertFalse(self.output.exists())

    def test_git_metadata_alias_rejects_without_output(self):
        for path in (".git/config", ".Git/HEAD", "nested/git~1/config",
                     "nested/.git./config", "../escape.txt", "bad?.txt"):
            with self.subTest(path=path):
                source = dict(self.source)
                source[path] = ("100644", b"metadata must never be exported\n")
                result = self.run_prepare(source=source)
                self.assertEqual(result.exit_code, 1, result.lines)
                self.assertFalse(self.output.exists())

    def test_output_is_deterministic(self):
        self.assertEqual(self.run_prepare().exit_code, 0)
        second = self.base / "second packet"
        self.assertEqual(self.run_prepare(output=second).exit_code, 0)
        self.assertEqual(tree_bytes(self.output), tree_bytes(second))
        receipt = json.loads((self.output / "receipt.json").read_bytes())
        self.assertEqual(receipt["source_commit"], self.commit)
        self.assertEqual(receipt["publication_status"], "not-published")
        self.assertEqual(receipt["producer"]["scripts/prepare_marketplace_release.py"],
                         hashlib.sha256(SCRIPT.read_bytes()).hexdigest())
        receipt["producer"]["scripts/prepare_marketplace_release.py"] = "0" * 64
        (self.output / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
        result = self.run_verify()
        self.assertEqual(result.exit_code, 1, result.lines)
        self.assertIn("error=producer_identity_mismatch", result.lines)


if __name__ == "__main__":
    unittest.main()
