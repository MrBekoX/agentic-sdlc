import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "install_git_hooks.py"


def load_installer():
    spec = importlib.util.spec_from_file_location("install_git_hooks", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipIf(shutil.which("git") is None, "git not available")
class TestGitHookInstaller(unittest.TestCase):
    def _repo(self, root: Path) -> None:
        subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)

    def test_scanner_path_is_one_posix_shell_literal(self):
        installer = load_installer()
        path = Path('/tmp/plugin $() `tick` \' " quote/hooks/git-hook-scan.mjs')
        with mock.patch.object(installer, "SCANNER", path):
            body = installer.hook_body("pre-commit")
        assignment = next(line for line in body.splitlines() if line.startswith("SCANNER="))
        self.assertNotIn('SCANNER="', assignment)
        if os.name != "nt" and shutil.which("sh"):
            proc = subprocess.run(
                ["sh", "-c", assignment + "\nprintf '%s' \"$SCANNER\""],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout, path.as_posix())

    def test_modified_managed_hook_is_never_overwritten_or_deleted(self):
        installer = load_installer()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            self.assertEqual(installer.cmd_install(root), 0)
            hook = installer.hooks_dir(root) / "pre-commit"
            modified = hook.read_text(encoding="utf-8") + "# user chain\n"
            hook.write_text(modified, encoding="utf-8")

            self.assertEqual(installer.cmd_install(root), 2)
            self.assertEqual(hook.read_text(encoding="utf-8"), modified)
            self.assertEqual(installer.cmd_uninstall(root), 2)
            self.assertTrue(hook.exists())
            self.assertEqual(hook.read_text(encoding="utf-8"), modified)

    def test_exact_managed_hooks_remain_idempotent_and_reversible(self):
        installer = load_installer()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            self.assertEqual(installer.cmd_install(root), 0)
            before = {
                name: (installer.hooks_dir(root) / name).read_bytes()
                for name in installer.HOOKS
            }
            self.assertEqual(installer.cmd_install(root), 0)
            self.assertEqual(
                before,
                {name: (installer.hooks_dir(root) / name).read_bytes() for name in installer.HOOKS},
            )
            self.assertEqual(installer.cmd_uninstall(root), 0)
            self.assertTrue(all(not (installer.hooks_dir(root) / name).exists() for name in installer.HOOKS))
            self.assertFalse(installer.ownership_manifest_path(root).exists())

    def test_self_digested_sentinel_without_manifest_is_foreign(self):
        installer = load_installer()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            hooks = installer.hooks_dir(root)
            hooks.mkdir(parents=True, exist_ok=True)
            unsigned = "#!/bin/sh\n# " + installer.SENTINEL + "\necho foreign\n"
            body = unsigned.replace(
                "# " + installer.SENTINEL + "\n",
                "# " + installer.SENTINEL + "\n"
                + installer.DIGEST_PREFIX + installer._body_digest(unsigned) + "\n",
            )
            hook = hooks / "pre-commit"
            hook.write_text(body, encoding="utf-8")

            self.assertEqual(installer.hook_state(hook, "pre-commit"), "foreign")
            self.assertEqual(installer.cmd_install(root), 2)
            self.assertEqual(hook.read_text(encoding="utf-8"), body)
            self.assertEqual(installer.cmd_uninstall(root), 0)
            self.assertEqual(hook.read_text(encoding="utf-8"), body)

    def test_external_hooks_path_requires_explicit_opt_in(self):
        installer = load_installer()
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as shared_td:
            root = Path(td)
            shared = Path(shared_td) / "shared-hooks"
            self._repo(root)
            subprocess.run(
                ["git", "config", "core.hooksPath", str(shared)],
                cwd=root,
                check=True,
                capture_output=True,
            )

            self.assertEqual(installer.cmd_install(root), 2)
            self.assertFalse(shared.exists())
            self.assertEqual(installer.cmd_install(root, allow_external_hooks_path=True), 0)
            self.assertTrue((shared / "pre-commit").is_file())
            self.assertEqual(installer.cmd_uninstall(root), 2)
            self.assertTrue((shared / "pre-commit").is_file())
            self.assertEqual(installer.cmd_uninstall(root, allow_external_hooks_path=True), 0)
            self.assertFalse((shared / "pre-commit").exists())


if __name__ == "__main__":
    unittest.main()
