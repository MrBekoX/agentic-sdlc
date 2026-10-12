import importlib.util
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "install_git_hooks.py"


def _git_version():
    out = subprocess.run(["git", "--version"], capture_output=True, text=True, encoding="utf-8").stdout
    found = re.search(r"(\d+)\.(\d+)", out)
    return (int(found.group(1)), int(found.group(2))) if found else (0, 0)


# GIT_CONFIG_GLOBAL needs git 2.32 and `config --show-scope` 2.26; older git keeps the location rule.
GLOBAL_CONFIG_TESTABLE = shutil.which("git") is not None and _git_version() >= (2, 32)


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

    @unittest.skipIf(os.name == "nt", "creating symlinks needs extra privileges on Windows")
    def test_a_dangling_symlinked_hook_is_never_written_through(self):
        # A committed dangling symlink in an in-repository hooks directory read as "absent", and the
        # install then wrote an executable hook body to wherever the link pointed - outside the repo,
        # without the external-path opt-in.
        installer = load_installer()
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside:
            root = Path(td)
            self._repo(root)
            hooks = root / ".githooks"
            hooks.mkdir()
            target = Path(outside) / "planted-hook"
            (hooks / "pre-commit").symlink_to(target)
            subprocess.run(["git", "config", "core.hooksPath", ".githooks"], cwd=root, check=True,
                           capture_output=True)
            self.assertEqual(installer.hook_state(hooks / "pre-commit", "pre-commit"), "foreign")
            self.assertEqual(installer.cmd_install(root), 2)
            self.assertFalse(target.exists(), "the installer wrote through a dangling symlink")

    def test_tilde_hooks_path_resolves_to_the_users_home_like_git_does(self):
        # Git expands a leading `~/` in core.hooksPath (a pathname-typed key). Reading the raw value
        # made `~/.githooks` a directory literally named `~` inside the checkout: the installer then
        # classified it as in-repository, skipped the external opt-in, reported "installed", and
        # wrote hooks git never runs.
        installer = load_installer()
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as home_td:
            root = Path(td)
            home = Path(home_td)
            self._repo(root)
            subprocess.run(["git", "config", "core.hooksPath", "~/agentic-hooks"],
                           cwd=root, check=True, capture_output=True)
            with mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}):
                resolved = installer.hooks_dir(root)
                self.assertEqual(resolved, (home / "agentic-hooks").resolve())
                self.assertTrue(installer.external_hooks_path(root, resolved))
                self.assertEqual(installer.cmd_install(root), 2)
                self.assertFalse((root / "~").exists())
                self.assertFalse((home / "agentic-hooks").exists())
                self.assertEqual(installer.cmd_install(root, allow_external_hooks_path=True), 0)
                self.assertTrue((home / "agentic-hooks" / "pre-commit").is_file())
                self.assertEqual(installer.cmd_uninstall(root, allow_external_hooks_path=True), 0)

    def test_a_relative_hooks_path_resolves_from_the_top_level_like_git(self):
        # git resolves a relative core.hooksPath against the top of the working tree; resolved
        # against a subdirectory --repo, the installer wrote hooks git never runs.
        installer = load_installer()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            subprocess.run(["git", "config", "core.hooksPath", ".githooks"], cwd=root, check=True,
                           capture_output=True)
            sub = root / "sub"
            sub.mkdir()
            self.assertEqual(installer.hooks_dir(sub), (root / ".githooks").resolve())
            self.assertEqual(installer.cmd_install(sub), 0)
            self.assertTrue((root / ".githooks" / "pre-commit").is_file())
            self.assertFalse((sub / ".githooks").exists())

    @unittest.skipUnless(GLOBAL_CONFIG_TESTABLE, "needs git 2.32+ (GIT_CONFIG_GLOBAL)")
    def test_a_relative_global_hooks_path_is_each_repositorys_own_folder(self):
        # `git config --global core.hooksPath .githooks` resolves inside every repository, so it
        # is not a shared folder and needs no opt-in.
        installer = load_installer()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            global_config = root / "global.gitconfig"
            global_config.write_text("[core]\n\thooksPath = .githooks\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(global_config)}):
                self.assertEqual(installer.hooks_dir(root), (root / ".githooks").resolve())
                self.assertFalse(installer.external_hooks_path(root, installer.hooks_dir(root)))
                self.assertEqual(installer.cmd_install(root), 0)
                self.assertTrue((root / ".githooks" / "pre-commit").is_file())

    @unittest.skipUnless(GLOBAL_CONFIG_TESTABLE, "needs git 2.32+ (GIT_CONFIG_GLOBAL)")
    def test_a_global_hooks_path_is_external_even_inside_the_checkout(self):
        # A global/system core.hooksPath is shared by every repository on the machine (often a
        # dotfiles checkout); writing there changes the user's configuration beyond this repo.
        installer = load_installer()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            shared = root / "dotfiles" / "hooks"
            global_config = root / "global.gitconfig"
            global_config.write_text("[core]\n\thooksPath = %s\n" % shared.as_posix(), encoding="utf-8")
            with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(global_config)}):
                self.assertEqual(installer.hooks_dir(root), shared.resolve())
                self.assertTrue(installer.external_hooks_path(root, shared.resolve()))
                self.assertEqual(installer.cmd_install(root), 2)
                self.assertFalse(shared.exists())

    def test_a_linked_worktree_installs_where_git_runs_hooks(self):
        # In a linked worktree `--git-dir` is `.git/worktrees/<name>`, but git runs hooks from the
        # shared `.git/hooks`: the installer reported "installed" for hooks git never ran, so the
        # commit scan silently stopped.
        installer = load_installer()
        with tempfile.TemporaryDirectory() as td:
            main, linked = Path(td) / "main", Path(td) / "linked"
            main.mkdir()
            self._repo(main)

            def git(*args, cwd=main):
                return subprocess.run(["git", "-c", "user.email=t@e.st", "-c", "user.name=t",
                                       "-c", "commit.gpgsign=false", *args],
                                      cwd=cwd, capture_output=True, text=True, encoding="utf-8")

            git("commit", "--allow-empty", "-qm", "base")
            self.assertEqual(git("worktree", "add", "-q", "-b", "feature", str(linked)).returncode, 0)
            shared = (main / ".git" / "hooks").resolve()
            self.assertEqual(installer.hooks_dir(linked), shared)
            self.assertFalse(installer.external_hooks_path(linked, shared))
            self.assertEqual(installer.cmd_install(linked), 0)
            self.assertTrue((shared / "pre-commit").is_file())
            self.assertFalse((main / ".git" / "worktrees" / "linked" / "hooks" / "pre-commit").exists())
            # One ownership record for the shared folder, whichever checkout installed it.
            self.assertTrue(installer.load_ownership(main, installer.hooks_dir(main)))
            if shutil.which("node"):
                (linked / "app.cfg").write_text("TOKEN = ghp_" + "a1B2" * 9 + "\n", encoding="utf-8")
                git("add", "app.cfg", cwd=linked)
                self.assertNotEqual(git("commit", "-qm", "leak", cwd=linked).returncode, 0,
                                    "git did not run the installed pre-commit hook")
            self.assertEqual(installer.cmd_uninstall(linked), 0)
            self.assertFalse((shared / "pre-commit").exists())
            self.assertFalse(installer.ownership_manifest_path(main).exists())


if __name__ == "__main__":
    unittest.main()
