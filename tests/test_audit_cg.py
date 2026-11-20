"""Regression tests for the command-guard findings CG-1..CG-11 of the f430715 bug audit
(session-reports/2026-11-18-bug-audit-f430715.md).

Every hook runs as a subprocess on a JSON payload, the way a runtime delivers it. Git fixtures
live in temporary directories with the system and global config switched off, so a developer's
own aliases cannot change a decision.

No literal credential-shaped value appears in this file: the synthetic token is assembled at
runtime from harmless parts.
"""
import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
GIT = shutil.which("git")

SCAN = REPO / "hooks" / "scan-commit.mjs"
BRANCH = REPO / "hooks" / "branch-guard.mjs"
DESTRUCTIVE = REPO / "hooks" / "destructive-command-guard.mjs"

# Synthetic GitHub-shaped token: prefix + 36 mixed characters, built at runtime.
SECRET = "gh" + "p_" + "Zq8Lm4Tx9" * 4

BASE_ENV = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
BASE_ENV.pop("AGENTIC_BRANCH_GUARD_BLOCK", None)


def m(text):
    """Mask the synthetic token in labels and messages."""
    return text.replace(SECRET, "<S>")


def run_hook(hook, command, cwd, *, tool="Bash", block=True, env=None, timeout=60):
    """Run a hook; return 'deny', 'warn' or 'silent'."""
    hook_env = dict(BASE_ENV, AGENTIC_BRANCH_GUARD_BLOCK="true" if block else "false")
    hook_env.update(env or {})
    proc = subprocess.run(
        [NODE, str(hook)], cwd=str(cwd),
        input=json.dumps({"tool_name": tool, "cwd": str(cwd),
                          "tool_input": {"command": command}}),
        capture_output=True, text=True, encoding="utf-8", env=hook_env, timeout=timeout,
    )
    if proc.returncode != 0:
        raise AssertionError("hook exited %d: %s" % (proc.returncode, proc.stderr[-400:]))
    out = json.loads(proc.stdout) if proc.stdout.strip() else {}
    decision = out.get("hookSpecificOutput", {}).get("permissionDecision")
    if decision:
        return decision
    return "warn" if out.get("systemMessage") else "silent"


def git(cwd, *args):
    return subprocess.run(
        [GIT, "-c", "core.hooksPath=" + os.devnull, *args], cwd=str(cwd), env=BASE_ENV,
        check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout


def make_repo(root, branch="feature/x"):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", branch)
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "commit.gpgsign", "false")
    (root / "config.py").write_text("x = 1\n", encoding="utf-8")
    (root / "src.py").write_text("y = 2\n", encoding="utf-8")
    git(root, "add", "config.py", "src.py")
    git(root, "commit", "-qm", "base")
    for name in ("main", "master"):
        if name != branch:
            git(root, "branch", name)
    git(root, "config", "remote.origin.url", "https://example.invalid/fixture.git")
    return root


class _RepoCase(unittest.TestCase):
    branch = "feature/x"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="audit-cg-")
        self.addCleanup(self._tmp.cleanup)
        self.repo = make_repo(Path(self._tmp.name) / "repo", self.branch)

    def write(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def decide(self, hook, command, **kw):
        return run_hook(hook, command, self.repo, **kw)


# --------------------------------------------------------------------------------------------
# CG-1: scan-commit must model the index changes the same command line makes before the commit.
# --------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestCG1SameCommandStaging(_RepoCase):

    def test_cg1_add_and_commit_is_scanned(self):
        self.write("config.py", "key = '" + SECRET + "'\n")
        for command in ("git add config.py && git commit -m update",
                        "git add -- config.py; git commit -m update",
                        "git stage config.py && git commit -m update",
                        "git add -A && git commit -m update",
                        "git add --all && git commit -m update",
                        "git add -u && git commit -m update",
                        "git add . && git commit -m update"):
            with self.subTest(command=m(command)):
                self.assertEqual(self.decide(SCAN, command), "deny", m(command))

    def test_cg1_untracked_file_added_in_same_command_is_scanned(self):
        self.write("new.py", "key = '" + SECRET + "'\n")
        for command in ("git add . && git commit -m 'add new'",
                        "git add --all && git commit -m 'add new'",
                        "git add new.py && git commit -m 'add new'",
                        "git add -A; git commit -m 'add new'"):
            with self.subTest(command=m(command)):
                self.assertEqual(self.decide(SCAN, command), "deny", m(command))

    def test_cg1_untracked_credential_file_added_in_same_command_is_flagged(self):
        self.write("id_rsa", "opaque key body\n")
        self.assertEqual(self.decide(SCAN, "git add id_rsa && git commit -m keys"), "deny")

    def test_cg1_commit_pathspec_only_and_include_are_scanned(self):
        self.write("config.py", "key = '" + SECRET + "'\n")
        for command in ("git commit -m update config.py",
                        "git commit -m update -- config.py",
                        "git commit -o config.py -m update",
                        "git commit --only -m update config.py",
                        "git commit -i config.py -m update",
                        "git commit --include -m update config.py"):
            with self.subTest(command=m(command)):
                self.assertEqual(self.decide(SCAN, command), "deny", m(command))

    def test_cg1_all_flag_inside_shell_payload_is_honoured(self):
        self.write("config.py", "key = '" + SECRET + "'\n")
        for command in ("bash -c 'git commit -am update'",
                        "sh -c \"git commit -a -m update\"",
                        "eval 'git commit --all -m update'"):
            with self.subTest(command=m(command)):
                self.assertEqual(self.decide(SCAN, command), "deny", m(command))

    def test_cg1_staging_through_an_alias_is_scanned(self):
        self.write("config.py", "key = '" + SECRET + "'\n")
        git(self.repo, "config", "alias.aa", "add -A")
        self.assertEqual(self.decide(SCAN, "git aa && git commit -m update"), "deny")
        self.assertEqual(
            self.decide(SCAN, "git -c alias.ac='!git add config.py && git commit -m x' ac"), "deny")

    def test_cg1_apply_cached_patch_is_scanned(self):
        patch = ("diff --git a/config.py b/config.py\n--- a/config.py\n+++ b/config.py\n"
                 "@@ -1 +1 @@\n-x = 1\n+key = '" + SECRET + "'\n")
        self.write("fix.patch", patch)
        self.assertEqual(
            self.decide(SCAN, "git apply --cached fix.patch && git commit -m update"), "deny")

    def test_cg1_existing_denies_still_hold(self):
        self.write("config.py", "key = '" + SECRET + "'\n")
        self.assertEqual(self.decide(SCAN, "git commit -am update"), "deny")
        git(self.repo, "add", "config.py")
        self.assertEqual(self.decide(SCAN, "git commit -m update"), "deny")

    def test_cg1_controls_stay_silent(self):
        # An unrelated untracked or modified file with a secret is not part of this commit.
        self.write("notes.txt", "token " + SECRET + "\n")
        self.write("config.py", "key = '" + SECRET + "'\n")
        self.write("src.py", "y = 3\n")
        for command in ("git add src.py && git commit -m update",
                        "git commit -m update src.py",
                        "git commit -m update",
                        "git add -n . && git commit -m update"):
            with self.subTest(command=m(command)):
                self.assertEqual(self.decide(SCAN, command), "silent", m(command))


# --------------------------------------------------------------------------------------------
# CG-2: unique long-option prefixes, clean.requireForce=false and git aliases.
# --------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestCG2DestructiveSpellings(_RepoCase):

    def assertDenied(self, command, label, **kw):
        self.assertEqual(self.decide(DESTRUCTIVE, command, **kw), "deny", m(command))

    def test_cg2_rm_long_option_prefixes(self):
        for command in ("rm --recursiv x", "rm --rec -f x", "rm --r x", "rm --recu --force x"):
            with self.subTest(command=m(command)):
                self.assertDenied(command, "rm-recursive")

    def test_cg2_git_reset_hard_prefixes(self):
        for command in ("git reset --har", "git reset --ha HEAD", "git reset --h"):
            with self.subTest(command=m(command)):
                self.assertDenied(command, "git-reset-hard")

    def test_cg2_git_clean_force_prefixes(self):
        for command in ("git clean --forc -d", "git clean --fo -x", "git clean --f -d"):
            with self.subTest(command=m(command)):
                self.assertDenied(command, "git-clean-force")

    def test_cg2_require_force_false_is_force(self):
        for command in ("git -c clean.requireForce=false clean -dx",
                        "git -c Clean.RequireForce=no clean -d",
                        "git -c clean.requireforce=0 clean -X"):
            with self.subTest(command=m(command)):
                self.assertDenied(command, "git-clean-force")
        git(self.repo, "config", "clean.requireForce", "false")
        self.assertDenied("git clean -dx", "git-clean-force")

    def test_cg2_inline_and_stored_aliases_are_expanded(self):
        for command in ("git -c alias.nuke='reset --hard' nuke",
                        "git -c alias.wipe='clean -fdx' wipe",
                        "git -c alias.x='!rm -rf build' x"):
            with self.subTest(command=m(command)):
                self.assertDenied(command, "alias")
        git(self.repo, "config", "alias.nuke", "reset --hard")
        self.assertDenied("git nuke", "git-reset-hard")
        self.assertDenied("git -C . nuke", "git-reset-hard")

    def test_cg2_controls_stay_allowed(self):
        git(self.repo, "config", "alias.st", "status")
        for command in ("rm --force file.txt", "rm --verbose file.txt", "rm --dir emptydir",
                        "rm --interactive file.txt", "git reset --soft HEAD~1",
                        "git reset --mixed", "git clean -n -d", "git clean --dry-run -dx",
                        "git -c clean.requireForce=true clean -dx", "git st", "git status",
                        "git -c alias.lg='log --oneline' lg"):
            with self.subTest(command=m(command)):
                self.assertEqual(self.decide(DESTRUCTIVE, command), "silent", m(command))


# --------------------------------------------------------------------------------------------
# CG-3: statically decidable shell constructs.
# --------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None, "node required")
class TestCG3ShellConstructs(unittest.TestCase):

    def decide(self, command, tool="Bash"):
        return run_hook(DESTRUCTIVE, command, REPO, tool=tool)

    def test_cg3_bypass_forms_are_denied(self):
        backslash = chr(92)
        for command in ("echo a" + backslash + "> & rm -rf x",
                        "echo " + backslash + "> & git reset --hard",
                        "env -S 'rm -rf x'",
                        "env --split-string='rm -rf x'",
                        "env -S\"rm -rf x\"",
                        "env -S 'FOO=1 rm -rf x'",
                        "{rm,-rf,x}",
                        "rm -{r,f} x",
                        "bash -c -- 'rm -rf x'",
                        "bash -c -e 'rm -rf x'",
                        "bash -ce 'rm -rf x'",
                        "sh -c -x 'rm -rf x'",
                        "eval -- rm -rf x",
                        "exec -a foo rm -rf x",
                        "exec -c rm -rf x",
                        "exec -cl -a foo rm -rf x",
                        "bash <<< 'rm -rf x'",
                        "bash <<<'rm -rf x'",
                        # A double-quoted substitution body is a command line of its own.
                        "echo \"$(true; rm -rf x)\"",
                        "x=\"$(cd /; rm -rf x)\"",
                        "echo \"`true && rm -rf x`\""):
            with self.subTest(command=m(command)):
                self.assertEqual(self.decide(command), "deny", m(command))

    def test_cg3_controls_stay_allowed(self):
        backslash = chr(92)
        for command in ("echo a" + backslash + "> b",
                        "env -S 'ls -la'",
                        "echo {a,b}",
                        "echo {rm,-rf,x}",
                        "bash -c -- 'ls'",
                        "eval -- echo hi",
                        "exec -a foo ls",
                        "bash <<< 'ls -la'",
                        "echo 'bash -c -- rm -rf x'"):
            with self.subTest(command=m(command)):
                self.assertEqual(self.decide(command), "silent", m(command))


# --------------------------------------------------------------------------------------------
# CG-4: one wrapper/option table for both resolvers.
# --------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestCG4SharedWrapperTable(_RepoCase):

    #: (label, shape); `%s` takes the command. Every row must reach every guard.
    WRAPPED = (
        ("env-unset", "env -u HOME %s"),
        ("env-chdir", "env -C . %s"),
        ("env-split", "env -S '%s'"),
        ("timeout-kill-after", "timeout --kill-after 1 30 %s"),
        ("timeout-kill-prefix", "timeout --kill 1 30 %s"),
        ("timeout-signal-long", "timeout --signal=KILL 30 %s"),
        ("xargs-L", "xargs -L 1 %s"),
        ("xargs-I", "xargs -I {} %s"),
        ("sudo-chdir", "sudo -D . %s"),
        ("sudo-user-long", "sudo --user root %s"),
        ("nice-long", "nice --adjustment 5 %s"),
        ("stdbuf", "stdbuf -o L %s"),
        ("bash-c-dashdash", "bash -c -- '%s'"),
        ("bash-c-option", "bash -c -e '%s'"),
        ("eval-dashdash", "eval -- %s"),
        ("exec-a", "exec -a g %s"),
        ("here-string", "bash <<< '%s'"),
        ("nohup-env", "nohup FOO=1 env %s"),
    )

    def test_cg4_scan_commit_sees_the_commit(self):
        for label, shape in self.WRAPPED:
            with self.subTest(shape=label):
                command = shape % ("git commit --allow-empty -m fix-" + SECRET)
                self.assertEqual(self.decide(SCAN, command), "deny", m(command))

    def test_cg4_branch_guard_sees_the_push(self):
        for label, shape in self.WRAPPED:
            with self.subTest(shape=label):
                command = shape % "git push origin HEAD:main"
                self.assertEqual(self.decide(BRANCH, command), "deny", m(command))

    def test_cg4_destructive_guard_sees_the_same_rows(self):
        for label, shape in self.WRAPPED:
            with self.subTest(shape=label):
                command = shape % "rm -rf build"
                self.assertEqual(self.decide(DESTRUCTIVE, command), "deny", m(command))

    def test_cg4_one_wrapper_table(self):
        destructive = DESTRUCTIVE.read_text(encoding="utf-8")
        self.assertNotIn("const WRAPPERS", destructive,
                         "the destructive guard keeps its own wrapper table")
        self.assertIn("from './git-invocation.mjs'", destructive)
        self.assertIn("unwrapCommand(", destructive)
        self.assertNotIn("function unwrapCommand(", destructive)

    def test_cg4_controls_stay_silent(self):
        for command in ("env -u HOME git status", "timeout --kill-after 1 30 git log -1",
                        "xargs -L 1 git status", "sudo -D . git status"):
            with self.subTest(command=m(command)):
                self.assertEqual(self.decide(BRANCH, command), "silent", m(command))
                self.assertEqual(self.decide(SCAN, command), "silent", m(command))


# --------------------------------------------------------------------------------------------
# CG-5: redirections are not remote or refspec.
# --------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestCG5Redirections(_RepoCase):

    def test_cg5_configured_push_destination_with_redirect(self):
        git(self.repo, "config", "remote.origin.push", "HEAD:main")
        for command in ("git push origin", "git push origin 2>&1", "git push origin 2>&1 | tail -5",
                        "git push origin >/dev/null 2>&1", "git push 2>&1",
                        "git push origin > /tmp/log 2>&1", "git 2>/dev/null push origin"):
            with self.subTest(command=m(command)):
                self.assertEqual(self.decide(BRANCH, command), "deny", m(command))

    def test_cg5_upstream_destination_with_redirect(self):
        git(self.repo, "config", "push.default", "upstream")
        git(self.repo, "config", "branch.feature/x.remote", "origin")
        git(self.repo, "config", "branch.feature/x.merge", "refs/heads/main")
        for command in ("git push", "git push 2>&1", "git push 2>/dev/null",
                        "git push -q 2>&1 | tail -3"):
            with self.subTest(command=m(command)):
                self.assertEqual(self.decide(BRANCH, command), "deny", m(command))

    def test_cg5_mirror_with_redirect(self):
        git(self.repo, "config", "remote.origin.mirror", "true")
        for command in ("git push origin", "git push origin 2>&1", "git push 2>&1"):
            with self.subTest(command=m(command)):
                self.assertEqual(self.decide(BRANCH, command), "deny", m(command))

    def test_cg5_controls(self):
        for command in ("git push origin feature/x 2>&1", "git push -u origin feature/x >/dev/null"):
            with self.subTest(command=m(command)):
                self.assertEqual(self.decide(BRANCH, command), "silent", m(command))
        # A quoted message that LOOKS like a redirect is still the message.
        self.assertEqual(self.decide(SCAN, "git commit --allow-empty -m '>note " + SECRET + "'"),
                         "deny")


# --------------------------------------------------------------------------------------------
# CG-6: the `heads/main` destination shorthand.
# --------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestCG6HeadsShorthand(_RepoCase):

    def test_cg6_heads_shorthand_is_protected(self):
        for command in ("git push origin HEAD:heads/main", "git push origin +HEAD:heads/main",
                        "git push origin feature/x:heads/master", "git push -f origin HEAD:heads/Main"):
            with self.subTest(command=m(command)):
                self.assertEqual(self.decide(BRANCH, command), "deny", m(command))

    def test_cg6_controls(self):
        for command in ("git push origin HEAD:heads/feature", "git push origin HEAD:refs/heads/heads/main"):
            with self.subTest(command=m(command)):
                self.assertEqual(self.decide(BRANCH, command), "silent", m(command))


# --------------------------------------------------------------------------------------------
# CG-7: command substitution and inline functions are walked.
# --------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestCG7SubstitutionAndFunctions(_RepoCase):

    def test_cg7_commit_in_substitution_is_scanned(self):
        message = "'fix " + SECRET + "'"
        for command in ("out=$(git commit --allow-empty -m " + message + ")",
                        "echo $(git commit --allow-empty -m " + message + ")",
                        "echo \"$(git commit --allow-empty -m " + message + ")\"",
                        "echo `git commit --allow-empty -m " + message + "`",
                        "git -c alias.c='!f() { git commit --allow-empty -m \"fix " + SECRET
                        + "\"; }; f' c",
                        "f() { git commit --allow-empty -m " + message + "; }; f",
                        "function f { git commit --allow-empty -m " + message + "; }; f"):
            with self.subTest(command=m(command)[:50]):
                self.assertEqual(self.decide(SCAN, command), "deny", m(command))

    def test_cg7_push_in_substitution_is_guarded(self):
        for command in ("echo $(git push origin HEAD:main)", "out=$(git push origin HEAD:main)",
                        "x=`git push origin HEAD:main`", "cat <(git push origin HEAD:main)",
                        "git -c alias.p='!f() { git push origin HEAD:main; }; f' p"):
            with self.subTest(command=m(command)):
                self.assertEqual(self.decide(BRANCH, command), "deny", m(command))

    def test_cg7_substitution_with_spaces_inside_git_options(self):
        # The tokenizer split inside the `$( )`, so `config` became the subcommand and the commit
        # (or push) after it was never seen.
        command = ("git -c user.name=$(git config user.name) commit --allow-empty -m 'fix "
                   + SECRET + "'")
        self.assertEqual(self.decide(SCAN, command), "deny", m(command))
        self.assertEqual(
            self.decide(BRANCH, "git -c user.name=$(git config user.name) push origin HEAD:main"), "deny")

    def test_cg7_controls(self):
        for command in ("echo \"$(date)\"", "out=$(git log -1 --format=%s)",
                        "npm test # $(git push origin HEAD:main)",
                        "echo '$(git push origin HEAD:main)'",
                        "git commit --allow-empty -m \"$(cat <<'EOF'\nfix: docs\n\n"
                        "git push origin main\nEOF\n)\""):
            with self.subTest(command=m(command)[:40]):
                self.assertEqual(self.decide(BRANCH, command), "silent", m(command))


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestCG7FunctionOnMain(_RepoCase):
    branch = "main"

    def test_cg7_function_commit_on_main(self):
        for command in ("f() { git commit -m x; }; f", "out=$(git commit -m x)"):
            with self.subTest(command=m(command)):
                self.assertEqual(self.decide(BRANCH, command), "deny", m(command))


# --------------------------------------------------------------------------------------------
# CG-8: commit-message extraction (stdin, attached and abbreviated options).
# --------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestCG8CommitMessageForms(_RepoCase):

    def test_cg8_message_forms_are_scanned(self):
        self.write("msg.txt", "fix " + SECRET + "\n")
        for command in ("git commit --allow-empty -F - <<'EOF'\nfix: thing\n\ntoken " + SECRET + "\nEOF",
                        "git commit --allow-empty -F - <<EOF\nfix " + SECRET + "\nEOF",
                        "git commit --allow-empty --file=- <<-'EOF'\n\tfix " + SECRET + "\n\tEOF",
                        "git commit --allow-empty -F /dev/stdin <<'EOF'\nfix " + SECRET + "\nEOF",
                        "git commit --allow-empty -F - <<< 'fix " + SECRET + "'",
                        "git commit --allow-empty -Fmsg.txt",
                        "git commit --allow-empty --fil=msg.txt",
                        "git commit --allow-empty --fil msg.txt",
                        "git commit --allow-empty -qF msg.txt",
                        "git commit --allow-empty --mess 'fix " + SECRET + "'",
                        "git commit --allow-empty --messa='fix " + SECRET + "'",
                        "git commit --allow-empty --m 'fix " + SECRET + "'"):
            with self.subTest(command=m(command)[:45]):
                self.assertEqual(self.decide(SCAN, command), "deny", m(command))

    def test_cg8_controls(self):
        self.write("clean.txt", "fix: clean message\n")
        for command in ("git commit --allow-empty -F - <<'EOF'\nfix: clean\nEOF",
                        "git commit --allow-empty -Fclean.txt",
                        "git commit --allow-empty --fixup=HEAD",
                        "git commit --allow-empty --mess 'fix: ordinary'"):
            with self.subTest(command=m(command)[:45]):
                self.assertEqual(self.decide(SCAN, command), "silent", m(command))


# --------------------------------------------------------------------------------------------
# CG-9: PowerShell forms (parsed on payload text; no PowerShell runtime needed).
# --------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None, "node required")
class TestCG9PowerShellForms(unittest.TestCase):

    def decide(self, command, tool="PowerShell"):
        return run_hook(DESTRUCTIVE, command, REPO, tool=tool)

    @staticmethod
    def encoded(text):
        return base64.b64encode(text.encode("utf-16-le")).decode("ascii")

    def test_cg9_powershell_bypass_forms_are_denied(self):
        tick = "`"
        rm = "Remove-Item -Recurse C:\\x"
        for command in ("iex '" + rm + "'",
                        "Invoke-Expression \"" + rm + "\"",
                        "Invoke-Expression -Command '" + rm + "'",
                        ". " + rm,
                        "powershell -com \"" + rm + "\"",
                        "pwsh -Comm \"" + rm + "\"",
                        "pwsh -co \"" + rm + "\"",
                        "powershell -EncodedCommand " + self.encoded(rm),
                        "pwsh -enc " + self.encoded(rm),
                        "pwsh -e " + self.encoded(rm),
                        "Remove-It" + tick + "em -Recurse C:\\x",
                        "R" + tick + "emove-Item -Recurse C:\\x",
                        "Remove-Item -Rec" + tick + "urse C:\\x"):
            with self.subTest(command=m(command)):
                self.assertEqual(self.decide(command), "deny", m(command))

    def test_cg9_encoded_payload_through_bash_is_denied(self):
        rm = "Remove-Item -Recurse C:\\x"
        self.assertEqual(self.decide("pwsh -EncodedCommand " + self.encoded(rm), tool="Bash"), "deny")

    def test_cg9_controls_stay_allowed(self):
        tick = "`"
        for command in ("iex 'Get-ChildItem -Recurse'",
                        "powershell -EncodedCommand " + self.encoded("Get-ChildItem -Recurse"),
                        "Write-Output " + tick + "\"hi" + tick + "\"",
                        ". ./profile.ps1",
                        "pwsh -c \"Get-ChildItem\""):
            with self.subTest(command=m(command)):
                self.assertEqual(self.decide(command), "silent", m(command))


# --------------------------------------------------------------------------------------------
# CG-10: heredoc bodies are data, except where something executes them.
# --------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestCG10Heredocs(_RepoCase):

    def test_cg10_heredoc_data_is_not_a_command(self):
        # R3-CG-1 re-plan: only exact whole-command shapes keep their body out of the command view
        # (unquoted, `<<-` and extra-redirect forms moved to TestR3CG1ExactShapesOnly as denies).
        for command in ("cat > notes.md <<'EOF'\nrm -rf build/\nEOF",
                        "git commit -m \"$(cat <<'EOF'\nfix: never rm -rf build\nEOF\n)\""):
            with self.subTest(command=m(command)[:30]):
                self.assertEqual(self.decide(DESTRUCTIVE, command), "silent", m(command))
        for command in ("cat > RELEASE.md <<'EOF'\nTo publish run:\ngit push origin main\nEOF",
                        "git commit --allow-empty -F - <<'EOF'\nfix: x\n\ngit push origin main\nEOF"):
            with self.subTest(command=m(command)[:30]):
                self.assertEqual(self.decide(BRANCH, command), "silent", m(command))

    def test_cg10_executed_heredocs_are_still_commands(self):
        for command in ("bash <<'EOF'\nrm -rf build\nEOF",
                        "sh <<EOF\nrm -rf build\nEOF",
                        "cat <<'EOF' | bash\nrm -rf build\nEOF",
                        "sudo -s <<'EOF'\nrm -rf build\nEOF",
                        "ssh host <<'EOF'\nrm -rf build\nEOF",
                        "cat <<EOF\n$(rm -rf build)\nEOF",
                        "cat <<EOF\n`rm -rf build`\nEOF",
                        "cat > f <<'EOF'\nx\nEOF\nrm -rf build",
                        "echo x # <<EOF\nrm -rf build\nEOF",
                        "echo $((1 << 2))\nrm -rf build\n2",
                        "(( x = 1 << 2 ))\nrm -rf build\n2"):
            with self.subTest(command=m(command)[:30]):
                self.assertEqual(self.decide(DESTRUCTIVE, command), "deny", m(command))
        for command in ("bash <<'EOF'\ngit push origin main\nEOF",
                        "cat <<'EOF' > f\nx\nEOF\ngit push origin main",
                        "cat <<EOF\n$(git push origin main)\nEOF"):
            with self.subTest(command=m(command)[:30]):
                self.assertEqual(self.decide(BRANCH, command), "deny", m(command))


# --------------------------------------------------------------------------------------------
# CG-11: alias lookups are capped per invocation, and the cap does not fail open.
# --------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestCG11AliasLookupCap(_RepoCase):

    def _shim(self):
        shim = Path(self._tmp.name) / "shim"
        shim.mkdir()
        count = Path(self._tmp.name) / "lookups.log"
        script = shim / "git"
        script.write_text(
            "#!/bin/sh\n"
            "case \"$*\" in *\"config --get alias.\"*) echo x >> \"" + str(count) + "\";; esac\n"
            "exec \"" + GIT + "\" \"$@\"\n", encoding="utf-8")
        script.chmod(0o755)
        env = {"PATH": str(shim) + os.pathsep + os.environ.get("PATH", "")}
        return env, count

    def _lookups(self, count):
        return len(count.read_text().splitlines()) if count.exists() else 0

    def test_cg11_alias_lookups_are_capped_and_the_push_is_still_denied(self):
        env, count = self._shim()
        command = ";".join("git zq%d" % i for i in range(4500)) + "; git push origin HEAD:main"
        start = time.monotonic()
        decision = self.decide(BRANCH, command, env=env, timeout=120)
        elapsed = time.monotonic() - start
        self.assertLessEqual(self._lookups(count), 64, "alias lookups are not capped")
        self.assertEqual(decision, "deny")
        self.assertLess(elapsed, 10.0)

    def test_cg11_cap_holds_for_the_other_guards(self):
        env, count = self._shim()
        filler = ";".join("git zq%d" % i for i in range(2000))
        self.assertEqual(self.decide(DESTRUCTIVE, filler + "; git reset --hard", env=env, timeout=120),
                         "deny")
        self.assertLessEqual(self._lookups(count), 64)
        count.unlink(missing_ok=True)
        self.assertEqual(
            self.decide(SCAN, filler + "; git commit --allow-empty -m fix-" + SECRET, env=env,
                        timeout=120), "deny")
        self.assertLessEqual(self._lookups(count), 64)

    def test_cg11_repeated_alias_is_looked_up_once(self):
        env, count = self._shim()
        git(self.repo, "config", "alias.pp", "push origin HEAD:main")
        command = ";".join(["git pp"] * 50)
        self.assertEqual(self.decide(BRANCH, command, env=env), "deny")
        self.assertLessEqual(self._lookups(count), 2)


# --------------------------------------------------------------------------------------------
# Linear time: the new lexer and the regexes it adds must stay linear on long single lines.
# --------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestAuditCGLinearTime(_RepoCase):

    SHAPES = {
        "substitution-nest": lambda n: "$(" * n,
        "backticks": lambda n: "`" * n,
        "heredoc-operators": lambda n: "cat <<A " * n,
        "arith": lambda n: "$((" * n,
        "param": lambda n: "${" * n,
        "braces": lambda n: "{a," * n,
        "comment-words": lambda n: "a #b " * n,
        "ansi-c": lambda n: "$'\\'" * n,
        "ps-params": lambda n: "pwsh -comm -enc " * n,
    }

    def _time(self, hook, command):
        start = time.monotonic()
        run_hook(hook, command, self.repo, timeout=120)
        return time.monotonic() - start

    def test_brace_expansion_is_bounded_under_the_input_cap(self):
        # The destructive guard parses inputs up to 20 000 characters precisely. One brace list
        # with thousands of alternatives must be refused by count, not built and then counted.
        for size in (2000, 9000):
            command = "echo {" + "a," * size + "a}"
            with self.subTest(size=size):
                self.assertLess(self._time(DESTRUCTIVE, command), 3.0)
                self.assertEqual(run_hook(DESTRUCTIVE, command, self.repo), "silent")
        nested = "echo " + "{a,b}" * 3000
        self.assertLess(self._time(DESTRUCTIVE, nested), 3.0)
        long_prefix = "echo " + "p" * 9000 + "{" + "a," * 4500 + "a}"
        self.assertLess(self._time(DESTRUCTIVE, long_prefix), 3.0)

    def test_lexer_shapes_are_linear(self):
        for label, make in self.SHAPES.items():
            for hook in (BRANCH, DESTRUCTIVE, SCAN):
                with self.subTest(shape=label, hook=hook.name):
                    small = self._time(hook, "git status; " + make(25000))
                    large = self._time(hook, "git status; " + make(100000))
                    self.assertLess(large, 8.0, "%s on %s: %.2fs" % (label, hook.name, large))
                    # 4x the input: linear is ~4x, quadratic ~16x. Node start-up dominates the
                    # small run, so the ratio is only meaningful once the large run is slow.
                    if large > 1.0:
                        self.assertLess(large / max(small, 0.05), 9.0,
                                        "%s on %s: %.2fs vs %.2fs" % (label, hook.name, small, large))


if __name__ == "__main__":
    unittest.main()


# --------------------------------------------------------------------------------------------
# SW-6 in scan-commit: one oversized staged diff must not drop the scan of every other file.
# Found by the SW slice: scan-commit read the whole staged diff in one call capped at 5 MiB, so a
# regenerated fixture made `git diff` overflow and the small secret beside it was never read.
# --------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestSW6ScanCommitBoundedDiff(_RepoCase):
    def _big(self, name="fixtures.csv"):
        row = "a,b,c,d,e,f,g,h,i,j,k,l,m,n,o,p,q,r,s,t,u,v,w,x,y,z,0123456789\n"
        return self.write(name, row * 120000)   # about 7.7 MB of added lines

    def test_sw6_staged_secret_beside_an_oversized_file_is_denied(self):
        self._big()
        self.write("app.cfg", "token = " + SECRET + "\n")
        git(self.repo, "add", "fixtures.csv", "app.cfg")
        self.assertEqual(self.decide(SCAN, "git commit -m regenerate"), "deny")

    def test_sw6_same_command_staging_beside_an_oversized_file_is_denied(self):
        # Tracked first, so the regenerated fixture is in the unstaged diff that `add -A` stages.
        self.write("fixtures.csv", "a,b\n")
        git(self.repo, "add", "fixtures.csv")
        git(self.repo, "commit", "-qm", "fixture")
        self._big()
        self.write("config.py", "key = '" + SECRET + "'\n")
        self.assertEqual(self.decide(SCAN, "git add -A && git commit -m regenerate"), "deny")

    def test_sw6_oversized_clean_commit_warns_that_a_file_was_not_scanned(self):
        self._big()
        git(self.repo, "add", "fixtures.csv")
        self.assertEqual(self.decide(SCAN, "git commit -m regenerate"), "warn")


# ============================================================================================
# Round 2: regressions found by the security review of the round-1 CG fixes (R2-CG-1..13).
# A recursive force delete is assembled at runtime (RM) so the source carries no such command.
# ============================================================================================
RM = "r" + "m -r" + "f build"


def timed(hook, command, cwd, **kw):
    start = time.monotonic()
    try:
        decision = run_hook(hook, command, cwd, **kw)
    except subprocess.TimeoutExpired:
        decision = "timeout"
    return decision, time.monotonic() - start


class _ShimCase(_RepoCase):
    """A `git` shim on PATH that logs every invocation, to count the processes a hook spawns."""

    def shim(self, pattern=""):
        shim = Path(self._tmp.name) / "shim"
        shim.mkdir(exist_ok=True)
        log = Path(self._tmp.name) / "spawns.log"
        script = shim / "git"
        script.write_text(
            "#!/bin/sh\n"
            "case \"$*\" in *\"" + pattern + "\"*) echo x >> \"" + str(log) + "\";; esac\n"
            "exec \"" + GIT + "\" \"$@\"\n", encoding="utf-8")
        script.chmod(0o755)
        return {"PATH": str(shim) + os.pathsep + os.environ.get("PATH", "")}, log

    @staticmethod
    def count(log):
        return len(log.read_text().splitlines()) if log.exists() else 0


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR2CG3HeredocDefaultInverted(_RepoCase):
    """R2-CG-3: a here-document body is a command unless its own command is a known data sink
    whose output is not run later on the line."""

    def test_r2cg3_executed_bodies_are_denied(self):
        for command in ("(bash <<'EOF'\nRM\nEOF\n)",
                        "eval $(cat <<'EOF'\nRM\nEOF\n)",
                        "eval \"$(cat <<'EOF'\nRM\nEOF\n)\"",
                        "cat > clean.sh <<'EOF'\nRM\nEOF\nchmod +x clean.sh && ./clean.sh",
                        "cat > clean.sh <<'EOF'\nRM\nEOF\nbash clean.sh",
                        "$(cat <<'EOF'\nRM\nEOF\n)",
                        "cat <<'EOF' | (sh)\nRM\nEOF",
                        "at now <<'EOF'\nRM\nEOF",
                        "batch <<'EOF'\nRM\nEOF",
                        "parallel <<'EOF'\nRM\nEOF",
                        "make -f - <<'EOF'\nall:\n\tRM\nEOF",
                        "cat > Makefile <<'EOF'\nall:\n\tRM\nEOF\nmake",
                        "cat > .git/hooks/pre-commit <<'EOF'\nRM\nEOF\ngit commit -m x",
                        # Writers whose output file is an operand, not a redirection.
                        "sort -o .git/hooks/pre-commit <<'EOF'\nRM\nEOF\nchmod +x .git/hooks/pre-commit"
                        " && git commit -m x",
                        "uniq - .git/hooks/pre-commit <<'EOF'\nRM\nEOF\ngit commit -m x",
                        "x=$(cat <<'EOF'\nRM\nEOF\n); eval \"$x\""):
            command = command.replace("RM", RM)
            with self.subTest(command=command[:40]):
                self.assertEqual(self.decide(DESTRUCTIVE, command), "deny", command)

    def test_r2cg3_powershell_never_strips(self):
        command = "cat > notes.md <<'EOF'\nRemove-Item -Recurse C:\\x\nEOF"
        self.assertEqual(self.decide(DESTRUCTIVE, command, tool="PowerShell"), "deny")

    def test_r2cg3_git_guards_see_executed_bodies(self):
        for command in ("eval \"$(cat <<'EOF'\ngit push origin HEAD:main\nEOF\n)\"",
                        "(bash <<'EOF'\ngit push origin HEAD:main\nEOF\n)",
                        "cat > p.sh <<'EOF'\ngit push origin HEAD:main\nEOF\nsh p.sh"):
            with self.subTest(command=command[:40]):
                self.assertEqual(self.decide(BRANCH, command), "deny", command)
        command = "(bash <<'EOF'\ngit commit --allow-empty -m 'fix " + SECRET + "'\nEOF\n)"
        self.assertEqual(self.decide(SCAN, command), "deny", m(command))

    def test_r2cg3_data_bodies_stay_allowed(self):
        # R3-CG-1 re-plan: the non-exact shapes that round 2 allowed are denies now (see
        # TestR3CG1ExactShapesOnly); the exact shapes stay allowed.
        for command in ("cat > notes.md <<'EOF'\nRM\nEOF",
                        "git commit -m \"$(cat <<'EOF'\nfix: RM\nEOF\n)\" && git push origin feature/x"):
            command = command.replace("RM", RM)
            with self.subTest(command=command[:40]):
                self.assertEqual(self.decide(DESTRUCTIVE, command), "silent", command)
        for command in ("cat > RELEASE.md <<'EOF'\nTo publish run:\ngit push origin main\nEOF",
                        "git commit --allow-empty -F - <<'EOF'\nfix: x\n\ngit push origin main\nEOF"):
            with self.subTest(command=command[:40]):
                self.assertEqual(self.decide(BRANCH, command), "silent", command)


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR2CG4HeredocBoundaries(_RepoCase):
    """R2-CG-4: where the lexer's reading of a here-document could differ from bash, keep the body."""

    def test_r2cg4_uncertain_bodies_are_denied(self):
        for command in ("((1))#<<EOF\nRM\nEOF",
                        "x=$( (true)#<<EOF\nRM\nEOF\n)",
                        "cat >notes <<$(x)\n$(x)\nRM",
                        "cat >notes <<$'EOF'\nEOF\nRM\nEOF"):
            command = command.replace("RM", RM)
            with self.subTest(command=command[:40]):
                self.assertEqual(self.decide(DESTRUCTIVE, command), "deny", command)

    def test_r2cg4_powershell_here_string_controls(self):
        # A PowerShell here-string that mentions `<<EOF` must not turn the script after it into a
        # here-document body. (An apostrophe inside a single-quoted here-string is covered by
        # tests/test_audit_residuals_r2.py, R2-a.)
        for command in ("$s = @'\n<<EOF\n'@\nRemove-Item -Recurse C:\\x\nEOF",
                        "$s = @\"\nnote <<EOF\n\"@\nRemove-Item -Recurse C:\\x\nEOF",
                        "$s = @'\ncat > n <<EOF\n'@\nRemove-Item -Recurse C:\\x\nEOF"):
            with self.subTest(command=command[:30]):
                self.assertEqual(self.decide(DESTRUCTIVE, command, tool="PowerShell"), "deny")


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR2CG5CarriageReturnIsNotABlank(_RepoCase):

    def test_r2cg5_cr_does_not_start_a_comment(self):
        self.assertEqual(self.decide(BRANCH, "echo hi\r#; git push origin HEAD:main"), "deny")
        self.assertEqual(
            self.decide(SCAN, "echo hi\r#; git commit --allow-empty -m 'fix " + SECRET + "'"), "deny")

    def test_r2cg5_real_comment_still_a_comment(self):
        # A comment with no separator in it is still not a command. (`echo hi #; git push ...` is
        # denied: base f430715 split it at `;`, and R3-CG-1 never reads less than base.)
        self.assertEqual(self.decide(BRANCH, "echo hi # git push origin HEAD:main"), "silent")


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR2CG6WrapperRoundCap(_RepoCase):

    def test_r2cg6_many_wrappers(self):
        for count in (33, 200):
            with self.subTest(count=count):
                self.assertEqual(self.decide(DESTRUCTIVE, "nohup " * count + RM), "deny")
                self.assertEqual(self.decide(BRANCH, "nohup " * count + "git push origin HEAD:main"), "deny")


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR2CG7ShellFlagScanIsLinear(_RepoCase):

    def test_r2cg7_many_shells_and_a_long_flag(self):
        command = "sh " * 1330 + "-" + "c" * 14000 + "1; " + RM
        decision, elapsed = timed(DESTRUCTIVE, command, self.repo, timeout=60)
        self.assertEqual(decision, "deny")
        self.assertLess(elapsed, 8.0)

    def test_r2cg7_controls(self):
        for command in ("bash script.sh -c x", "sh -x ./build.sh"):
            with self.subTest(command=command):
                self.assertEqual(self.decide(DESTRUCTIVE, command), "silent")
        self.assertEqual(self.decide(DESTRUCTIVE, "bash -o pipefail -c '" + RM + "'"), "deny")


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR2CG8ResolverBudget(_RepoCase):

    def test_r2cg8a_nested_eval_is_bounded(self):
        command = "eval $(" * 31 + "a " * 100000 + ")" * 31 + "; git push origin HEAD:main"
        decision, elapsed = timed(BRANCH, command, self.repo, timeout=60)
        self.assertEqual(decision, "deny")
        self.assertLess(elapsed, 8.0)

    def test_r2cg8b_boolean_parse_is_linear(self):
        command = 'git -c "clean.requireForce=' + " " * 200000 + 'x" clean -d; ' + RM
        decision, elapsed = timed(DESTRUCTIVE, command, self.repo, timeout=60)
        self.assertEqual(decision, "deny")
        self.assertLess(elapsed, 8.0)
        command = 'git -c "clean.requireForce=' + " " * 18000 + 'false " clean -d'
        self.assertEqual(self.decide(DESTRUCTIVE, command), "deny")


@unittest.skipIf(NODE is None or GIT is None or not hasattr(os, "mkfifo"), "node, git, mkfifo")
class TestR2CG9HostileConfigLookups(_RepoCase):

    def _fifo_include(self):
        fifo = Path(self._tmp.name) / "cfg.fifo"
        os.mkfifo(str(fifo))
        with open(self.repo / ".git" / "config", "a", encoding="utf-8") as handle:
            handle.write("[include]\n\tpath = " + str(fifo) + "\n")

    def test_r2cg9_destructive_command_is_denied_before_lookups(self):
        self._fifo_include()
        for k in range(8):
            (self.repo / ("s%d" % k)).mkdir()
        command = (" && ".join(["false"] + ["git -C s%d clean -d" % k for k in range(8)])
                   + "; " + RM.replace("build", "~/w"))
        decision, elapsed = timed(DESTRUCTIVE, command, self.repo, timeout=60)
        self.assertEqual(decision, "deny")
        self.assertLess(elapsed, 8.0)

    def test_r2cg9_unknown_require_force_denies_clean_with_targets(self):
        self._fifo_include()
        decision, elapsed = timed(DESTRUCTIVE, " && ".join(["git clean -d"] * 8), self.repo, timeout=60)
        self.assertEqual(decision, "deny")
        self.assertLess(elapsed, 8.0)


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR2CG10AliasCapDoesNotHide(_RepoCase):

    FILLER = " && ".join(["false"] + ["git z%d" % i for i in range(1, 33)])

    def test_r2cg10_commit_past_the_cap_is_scanned_as_commit_all(self):
        git(self.repo, "config", "alias.ci", "commit -a")
        self.write("config.py", "key = '" + SECRET + "'\n")
        self.assertEqual(self.decide(SCAN, self.FILLER + "; git ci -m wip"), "deny")

    def test_r2cg10_push_past_the_cap(self):
        git(self.repo, "config", "alias.pp", "push origin HEAD:main")
        self.assertEqual(self.decide(BRANCH, self.FILLER + "; git pp"), "deny")
        self.assertEqual(self.decide(BRANCH, self.FILLER + "; git pp", block=False), "warn")


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR2CG1StagingScopeBudget(_ShimCase):

    def test_r2cg1_many_add_scopes_are_merged(self):
        env, log = self.shim()
        command = " && ".join(["false"] + ["git add f%d" % i for i in range(2000)]) + "; git commit -m x"
        decision, elapsed = timed(SCAN, command, self.repo, env=env, timeout=120)
        self.assertLessEqual(self.count(log), 40, "git spawns are not bounded")
        self.assertLess(elapsed, 10.0)
        self.assertIn(decision, ("silent", "warn"))

    def test_r2cg1_whole_tree_scopes_read_once(self):
        env, log = self.shim("diff")
        self.write("config.py", "key = '" + SECRET + "'\n")
        command = "git add . && git add :/ && git add '*' && git add -A && git commit -m x"
        self.assertEqual(self.decide(SCAN, command, env=env), "deny")
        self.assertLessEqual(self.count(log), 6)

    def test_r2cg1_merged_scopes_still_find_the_secret(self):
        self.write("new.py", "key = '" + SECRET + "'\n")
        command = " && ".join(["git add f%d" % i for i in range(300)] + ["git add new.py", "git commit -m x"])
        self.assertEqual(self.decide(SCAN, command), "deny")


@unittest.skipIf(NODE is None or GIT is None or not hasattr(os, "mkfifo"), "node, git, mkfifo")
class TestR2CG2AgentNamedFiles(_RepoCase):

    def test_r2cg2_fifo_and_device_are_not_read(self):
        os.mkfifo(str(self.repo / "p.patch"))
        os.mkfifo(str(self.repo / "msg.fifo"))
        for command in ("git apply --cached p.patch && git commit -m x",
                        "git commit --allow-empty -F msg.fifo",
                        "git commit --allow-empty -F /dev/zero"):
            with self.subTest(command=command):
                decision, elapsed = timed(SCAN, command, self.repo, timeout=20)
                self.assertNotEqual(decision, "timeout")
                self.assertLess(elapsed, 10.0)

    def test_r2cg2_regular_message_file_is_still_read(self):
        self.write("msg.txt", "fix " + SECRET + "\n")
        self.assertEqual(self.decide(SCAN, "git commit --allow-empty -F msg.txt"), "deny")


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR2CG11ReadContext(_RepoCase):

    def test_r2cg11_other_config_disables_force_requirement(self):
        other = Path(self._tmp.name) / "other.cfg"
        other.write_text("[clean]\n\trequireForce = false\n", encoding="utf-8")
        for command in ("GIT_CONFIG_GLOBAL=" + str(other) + " git clean -d",
                        "HOME=/nonexistent-home git clean -dx",
                        "git -c include.path=" + str(other) + " clean -d",
                        "git --git-dir=.git clean -d"):
            with self.subTest(command=command):
                self.assertEqual(self.decide(DESTRUCTIVE, command), "deny")

    def test_r2cg11_controls(self):
        for command in ("git clean -d", "git clean -n -d", "git status"):
            with self.subTest(command=command):
                self.assertEqual(self.decide(DESTRUCTIVE, command), "silent")


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR2CG12NonStagingCommands(_RepoCase):

    def test_r2cg12_cleanup_commits_are_not_denied_by_unstaged_edits(self):
        self.write("config.py", "key = '" + SECRET + "'\n")
        self.write("src.py", "token = '" + SECRET + "'\n")
        for command in ("git rm --cached config.py && git commit -m untrack",
                        "git mv src.py lib.py && git commit -m rename",
                        "git restore --staged config.py && git commit -m unstage"):
            with self.subTest(command=command):
                self.assertEqual(self.decide(SCAN, command), "silent")


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR2CG13OptionChecksAreLinear(_RepoCase):

    def test_r2cg13_long_flag_clusters(self):
        for command in ("rm -" + "r" * 200000 + "1 x",
                        "git clean -" + "f" * 200000 + "1 -d",
                        "git clean -" + "d" * 200000 + "1 -f",
                        "git clean -" + "n" * 200000 + "1 -d"):
            with self.subTest(command=command[:20]):
                decision, elapsed = timed(DESTRUCTIVE, command, self.repo, timeout=60)
                self.assertNotEqual(decision, "timeout")
                self.assertLess(elapsed, 8.0)
        self.assertEqual(self.decide(DESTRUCTIVE, "rm -" + "v" * 50 + "r x"), "deny")


# ============================================================================================
# Round 3: CG-10 re-planned (R3-CG-1) and the second-pass review findings (R3-CG-2..10).
# ============================================================================================
@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR3CG1ExactShapesOnly(_RepoCase):
    """R3-CG-1: no here-document body leaves the command view, except in an exact, whole-command
    `cat`/`tee` to a plain relative path, `git commit -F -`, or Claude Code's
    `git commit -m "$(cat <<'EOF' ... EOF\n)"` message idiom."""

    DENIED = (
        "cat > notes.md <<'EOF'\nok\nEOF\nRM",
        "cat <<EOF > notes.md\nRM\nEOF",
        "cat > notes.md <<-EOF\n\tRM\n\tEOF",
        "cat > notes.md <<-'EOF'\n\tRM\n\tEOF",
        "tee notes.md <<\"EOF\" >/dev/null\nRM\nEOF",
        ": <<'EOF'\nRM\nEOF",
        "cat <<'EOF' | grep build\nRM\nEOF",
        "x=$(cat <<'EOF'\nRM\nEOF\n); echo \"$x\"",
        "cat > notes.md <<'EOF'\nRM\nEOF\ngit add notes.md && git commit -m docs",
        "cat > ../notes.md <<'EOF'\nRM\nEOF",
        "cat > .notes <<'EOF'\nRM\nEOF",
        "cat > docs/.hidden/n.md <<'EOF'\nRM\nEOF",
        "cat > /tmp/notes.md <<'EOF'\nRM\nEOF",
        "cat > ~/notes.md <<'EOF'\nRM\nEOF",
        "cat > $HOME/n.md <<'EOF'\nRM\nEOF",
        "cat > n*.md <<'EOF'\nRM\nEOF",
        "cat > notes.md <<'EOF'\nx\nEOF\nRM\nEOF",
        "cat > notes.md <<'EOF'\nRM\nEOF\r",
        "cat > notes.md <<'EOF' ; true\nRM\nEOF",
        "cat > notes.md <<'EOF' <<'EOG'\nRM\nEOF\nx\nEOG",
        "true\ncat > notes.md <<'EOF'\nRM\nEOF",
        "cat > notes.md <<'E-F'\nRM\nE-F",
        "git commit -C HEAD -F - <<'EOF'\nRM\nEOF",
    )

    def test_r3cg1_non_exact_shapes_keep_base_behavior(self):
        for command in self.DENIED:
            command = command.replace("RM", RM)
            with self.subTest(command=command[:40]):
                self.assertEqual(self.decide(DESTRUCTIVE, command), "deny", command)

    def test_r3cg1_exact_shapes_are_allowed(self):
        for command in ("cat > notes.md <<'EOF'\nRM\nEOF",
                        "cat <<'EOF' > notes.md\nRM\nEOF",
                        "cat >> notes.md <<'EOF'\nRM\nEOF",
                        "tee notes.md <<'EOF'\nRM\nEOF",
                        "cat > docs/notes-v2.md <<\"EOF\"\nRM\nEOF",
                        "  cat > notes.md <<'EOF'\nRM\nEOF\n  ",
                        "git commit --allow-empty -F - <<'EOF'\nfix: RM\nEOF"):
            command = command.replace("RM", RM)
            with self.subTest(command=command[:40]):
                self.assertEqual(self.decide(DESTRUCTIVE, command), "silent", command)
        # R4-1 removed the `-m "$(cat <<'EOF' ... )"` message exception: that body is read as a
        # command now (see TestR41MessageExceptionRemoved); branch-guard still models the quotes, so
        # a push mentioned inside the quoted message stays silent (the row below).
        for command in ("git commit --allow-empty -F - <<'EOF'\nfix: x\n\ngit push origin main\nEOF",
                        "cat > RELEASE.md <<'EOF'\nTo publish run:\ngit push origin main\nEOF",
                        "git commit --allow-empty -m \"$(cat <<'EOF'\nfix: docs\n\ngit push origin main\nEOF\n)\""):
            with self.subTest(command=command[:40]):
                self.assertEqual(self.decide(BRANCH, command), "silent", command)

    def test_r3cg1_git_guards_read_body_lines_as_commands(self):
        for command in ("cat > n.md <<EOF\ngit push origin HEAD:main\nEOF",
                        ": <<'EOF'\ngit push origin HEAD:main\nEOF",
                        "cat > n.md <<'EOF'\nx\nEOF\ngit push origin HEAD:main"):
            with self.subTest(command=command[:40]):
                self.assertEqual(self.decide(BRANCH, command), "deny", command)

    def test_r3cg1_exact_commit_message_is_scanned(self):
        command = "git commit --allow-empty -F - <<'EOF'\nfix " + SECRET + "\nEOF"
        self.assertEqual(self.decide(SCAN, command), "deny")


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR3CG2CommentQuotes(_RepoCase):

    def test_r3cg2_quote_in_comment_does_not_hide_the_next_line(self):
        for command in ("# don't forget\nRM",
                        "# Let's record the plan\ncat > NOTES.md <<'EOF'\nWe're shipping v2.\nEOF\nRM",
                        "echo ok # it's fine\nRM"):
            command = command.replace("RM", RM)
            with self.subTest(command=command[:30]):
                self.assertEqual(self.decide(DESTRUCTIVE, command), "deny", command)

    def test_r3cg2_powershell_comments(self):
        for command in ("# don't forget\nRemove-Item -Recurse C:\\x",
                        "<# it's a\nblock #>\nRemove-Item -Recurse C:\\x"):
            with self.subTest(command=command[:30]):
                self.assertEqual(self.decide(DESTRUCTIVE, command, tool="PowerShell"), "deny")

    def test_r3cg2_controls(self):
        for command in ("# " + RM + " is dangerous\necho ok", "echo ok # " + RM):
            with self.subTest(command=command[:30]):
                self.assertEqual(self.decide(DESTRUCTIVE, command), "silent")


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR3CG3NoCrash(_RepoCase):

    def test_r3cg3_huge_word_lists_do_not_crash(self):
        command = "git push origin HEAD:main; tee " + "x " * 130000 + "<<'EOF'\nEOF"
        self.assertEqual(self.decide(BRANCH, command, timeout=120), "deny")
        command = "git commit -m x; " * 130000
        self.assertIn(self.decide(SCAN, command, timeout=120), ("silent", "warn", "deny"))
        self.assertIn(self.decide(BRANCH, command, timeout=120), ("silent", "warn", "deny"))


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR3CG4SpawnBudgetStarvation(_RepoCase):

    def test_r3cg4_dummy_directories_do_not_starve_the_real_repository(self):
        self.write("config.py", "key = '" + SECRET + "'\n")
        git(self.repo, "add", "config.py")
        command = " && ".join(["false"] + ["git -C a%d commit -m x" % i for i in range(1, 25)]) + "; git commit -m wip"
        self.assertEqual(self.decide(SCAN, command), "deny")


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR3CG5UnresolvedAliasInAnotherRepo(_RepoCase):

    def test_r3cg5_unresolved_alias_scans_the_target_repository(self):
        other = make_repo(Path(self._tmp.name) / "other")
        git(other, "config", "alias.ci", "commit -a")
        (other / "config.py").write_text("key = '" + SECRET + "'\n", encoding="utf-8")
        filler = " && ".join(["false"] + ["git z%d" % i for i in range(1, 33)])
        self.assertEqual(self.decide(SCAN, filler + "; git -C ../other ci -m wip"), "deny")


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR3CG6ScannedVolume(_ShimCase):

    def test_r3cg6_whole_repo_diff_is_read_once(self):
        row = "a,b,c,d,e,f,g,h,i,j,k,l,m,n,o,p,q,r,s,t,u,v,w,x,y,z,0123456789\n"
        names = ["big%d.csv" % k for k in range(5)]
        for name in names:
            self.write(name, "x\n")
        git(self.repo, "add", *names)
        git(self.repo, "commit", "-qm", "big")
        for name in names:
            self.write(name, row * 55000)                         # about 3.4 MB each, unstaged
        for k in range(8):
            (self.repo / ("s%d" % k)).mkdir()
        command = " && ".join(["git -C s%d add -A" % k for k in range(8)] + ["git commit -m x"])
        env, log = self.shim("diff")
        decision, elapsed = timed(SCAN, command, self.repo, env=env, timeout=120)
        self.assertNotEqual(decision, "timeout")
        self.assertLess(elapsed, 15.0)
        # One whole-repository unstaged read (plus the staged read and its fallback listing), not
        # one per `-C` subdirectory: the scanned volume is what outlives the hook timeout.
        self.assertLessEqual(self.count(log), 16, "the whole-repository diff is re-read per scope")


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR3CG7UntrackedLoop(_RepoCase):

    def test_r3cg7_untracked_file_count_is_capped(self):
        sub = self.repo / "many"
        sub.mkdir()
        for k in range(6000):
            (sub / ("f%d.txt" % k)).write_text("x\n", encoding="utf-8")
        self.assertEqual(self.decide(SCAN, "git add -A && git commit -m x"), "warn")

    def test_r3cg7_staged_secret_is_reported_first(self):
        sub = self.repo / "many"
        sub.mkdir()
        for k in range(6000):
            (sub / ("f%d.txt" % k)).write_text("x\n", encoding="utf-8")
        self.write("config.py", "key = '" + SECRET + "'\n")
        git(self.repo, "add", "config.py")
        self.assertEqual(self.decide(SCAN, "git add -A && git commit -m x"), "deny")


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR3CG8PowerShellBlockComment(_RepoCase):

    def test_r3cg8_block_comment_does_not_hide_the_call(self):
        self.assertEqual(self.decide(BRANCH, "<#x#> git push origin HEAD:main", tool="PowerShell"), "deny")
        self.assertEqual(
            self.decide(SCAN, "<#x#> git commit --allow-empty -m 'fix " + SECRET + "'", tool="PowerShell"),
            "deny")


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR3CG9BoundedNamedReads(_RepoCase):

    def test_r3cg9_large_message_file_is_read_up_to_the_cap(self):
        self.write("msg.txt", "fix " + SECRET + "\n" + ("x" * 100 + "\n") * 70000)   # about 7 MB
        self.assertEqual(self.decide(SCAN, "git commit --allow-empty -F msg.txt"), "deny")

    @unittest.skipIf(not Path("/proc/self/pagemap").exists(), "procfs required")
    def test_r3cg9_endless_proc_file_is_bounded(self):
        decision, elapsed = timed(SCAN, "git commit --allow-empty -F /proc/self/pagemap", self.repo, timeout=30)
        self.assertNotEqual(decision, "timeout")
        self.assertLess(elapsed, 15.0)


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR3CG10ExecutedBodyDepth(_RepoCase):

    def test_r3cg10_three_nested_shells_inside_an_executed_body(self):
        import shlex
        inner = "git push origin HEAD:main"
        for _ in range(3):
            inner = "bash -c " + shlex.quote(inner)
        self.assertEqual(self.decide(BRANCH, "bash <<'EOF'\n" + inner + "\nEOF"), "deny")


# ============================================================================================
# Round 4: the final review (R4-1..R4-6).
# ============================================================================================
def msg_idiom(line3):
    """Claude Code's `git commit -m "$(cat <<'EOF' ... )"` idiom: bash ends the heredoc early and
    runs line 3 as a top-level command (R4-1)."""
    return ("git commit -m \"$(cat <<'EOF'\n"
            "EOF)\"\n"
            + line3 + "\n"
            "x=\"$(cat <<'EOF'\n"
            "EOF)\"")


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR41MessageExceptionRemoved(_RepoCase):
    """R4-1: the `-m "$(cat <<'EOF' ... )"` message exception is gone; every line is read again."""

    def test_r41_destructive_line_runs(self):
        self.assertEqual(self.decide(DESTRUCTIVE, msg_idiom(RM)), "deny")

    def test_r41_push_line_is_guarded(self):
        self.assertEqual(self.decide(BRANCH, msg_idiom("git push origin HEAD:main")), "deny")

    def test_r41_commit_in_another_repo_is_scanned(self):
        other = make_repo(Path(self._tmp.name) / "other")
        (other / "config.py").write_text("key = '" + SECRET + "'\n", encoding="utf-8")
        git(other, "add", "config.py")
        self.assertEqual(self.decide(SCAN, msg_idiom("git -C ../other commit -m wip")), "deny")

    def test_r41_commit_all_on_main_is_seen(self):
        main = make_repo(Path(self._tmp.name) / "m", "main")
        self.assertEqual(run_hook(BRANCH, msg_idiom("git commit -a -m x"), main), "deny")

    def test_r41_message_idiom_still_scans_its_own_message(self):
        # The first line is a real `git commit`; a secret in its heredoc body reaches history as the
        # message. With the body now read line by line, the secret line is a scanned statement.
        command = ("git commit --allow-empty -m \"$(cat <<'EOF'\n"
                   "token " + SECRET + "\nEOF\n)\"")
        self.assertEqual(self.decide(SCAN, command), "deny")

    def test_r41_body_line_starting_with_delimiter_is_not_an_exact_shape(self):
        # A body line that merely starts with the delimiter (bash's back-compat closes some here) must
        # drop the exact-shape treatment, so the lines are read as commands.
        for command in ("cat > notes.md <<'EOF'\nEOFx\nRM\nEOF",
                        "cat > notes.md <<'EOF'\nEOF)\nRM\nEOF"):
            command = command.replace("RM", RM)
            with self.subTest(command=command[:30]):
                self.assertEqual(self.decide(DESTRUCTIVE, command), "deny", command)
        # The `-F -` shape with a delimiter-prefixed body line also falls back: the push is read.
        self.assertEqual(
            self.decide(BRANCH, "git commit --allow-empty -F - <<'EOF'\nEOF-\ngit push origin HEAD:main\nEOF"),
            "deny")

    def test_r41_clean_message_idiom_body_is_read(self):
        # The regression the removal fixes: round 3 treated the heredoc body as the message and
        # excluded it, so a destructive body line was allowed. It is read as a command again.
        self.assertEqual(
            self.decide(DESTRUCTIVE, "git commit -m \"$(cat <<'EOF'\n" + RM + "\nEOF\n)\""), "deny")

    def test_r41_exact_shapes_still_allowed(self):
        for command in ("cat > notes.md <<'EOF'\nRM\nEOF",
                        "git commit --allow-empty -F - <<'EOF'\nfix: RM\nEOF"):
            command = command.replace("RM", RM)
            with self.subTest(command=command[:30]):
                self.assertEqual(self.decide(DESTRUCTIVE, command), "silent", command)


@unittest.skipIf(NODE is None, "node required")
class TestR42BraceWordQuotes(unittest.TestCase):
    """R4-2: braceWordEnd mis-read a double-quoted span, so a brace word holding `"$(...)"` (or an
    escaped quote) hid a destructive command from the segmenter."""

    def decide(self, command):
        return run_hook(DESTRUCTIVE, command, REPO)

    def test_r42_brace_word_with_quoted_substitution_is_denied(self):
        rm = "r" + chr(92) + "m -rf build"            # bash view decodes r\m -> rm
        for command in ('{a,"$(' + rm + ')"}',
                        'echo {a,"$(' + rm + ')"}',
                        'x={a,"$(' + rm + ')"}'):
            with self.subTest(command=command):
                self.assertEqual(self.decide(command), "deny", command)

    def test_r42_brace_list_still_expands(self):
        # The fix must not stop ordinary brace expansion.
        self.assertEqual(self.decide("{a,b,c}"), "silent")
        self.assertEqual(self.decide("{r" + "m,-rf,build}"), "deny")


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR43R44StagedReadCuts(_ShimCase):
    """R4-3 / R4-4: a budget cut or a timeout kill on the phase-1 staged read denies, not warns, so a
    staged credential file caught only by name is not missed."""

    def _slow_names_shim(self):
        shim = Path(self._tmp.name) / "shim"
        shim.mkdir(exist_ok=True)
        script = shim / "git"
        script.write_text(
            "#!/bin/sh\n"
            "for a in \"$@\"; do if [ \"$a\" = --name-only ]; then sleep 40; fi; done\n"
            "exec \"" + GIT + "\" \"$@\"\n", encoding="utf-8")
        script.chmod(0o755)
        return {"PATH": str(shim) + os.pathsep + os.environ.get("PATH", "")}

    def test_r43_staged_name_read_cut_denies(self):
        # A staged rename to a credential name is caught only by `--name-only`. Killing that read
        # must deny, not warn: the credential would otherwise reach the commit unscanned.
        self.write("plain.txt", "placeholder\n")
        git(self.repo, "add", "plain.txt")
        git(self.repo, "commit", "-qm", "seed")
        git(self.repo, "mv", "plain.txt", "id_rsa")
        env = self._slow_names_shim()
        decision, elapsed = timed(SCAN, "git commit -m rename", self.repo, env=env, timeout=40)
        self.assertEqual(decision, "deny")
        self.assertLess(elapsed, 30.0)


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR45NulInHeredocShape(_RepoCase):

    def test_r45_nul_rejects_the_exact_shape(self):
        command = "cat > notes.md <<'EOF'\n\x00\n" + RM + "\nEOF"
        self.assertEqual(self.decide(DESTRUCTIVE, command), "deny")


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR46MissingCommitTarget(_RepoCase):

    def test_r46_missing_commit_cwd_is_reported(self):
        self.assertEqual(self.decide(SCAN, "git -C does-not-exist commit -m x"), "warn")

    def test_r46_existing_clean_commit_stays_silent(self):
        self.assertEqual(self.decide(SCAN, "git commit -m x"), "silent")


# --------------------------------------------------------------------------------------------
# R5 (final review, High): the exact heredoc shape applied to nested payloads. A payload's text
# comes out of a lossy decode (`\\` before a newline, `\cJ` in ANSI-C quoting), so a delimiter
# line bash sees could merge into the line above in the guard's copy, the shape matched, and the
# lines after it went unread. The shape now applies only to the tool's raw command (depth 0).
# --------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None, "node required")
class TestR5ExactShapeOnlyAtTopLevel(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="audit-cg-r5-")
        self.addCleanup(self._tmp.cleanup)

    def test_r5_payload_decode_cannot_hide_a_line_after_the_delimiter(self):
        rm = "r" + "m -" + "rf y"
        commands = (
            "bash -c \"cat > a <<'D'\nA\\\\\\\"B\\\\\nD\n%s\nD\"" % rm,
            "bash -c $'cat > a <<\\'D\\'\\nx\\cJD\\n%s\\nD'" % rm,
            "eval $'cat > a <<\\'D\\'\\nx\\cJD\\n%s\\nD'" % rm,
        )
        for command in commands:
            with self.subTest(command=command[:40]):
                self.assertEqual(run_hook(DESTRUCTIVE, command, self._tmp.name), "deny")

    def test_r5_alias_text_never_gets_the_exact_shape(self):
        # An inline `!` alias comes out of the resolver's tokenizer (`\cJ` dropped, a double-quoted
        # backslash-newline kept), so the shape must not be judged on it (R5 follow-up).
        rm = "r" + "m -" + "rf y"
        commands = (
            "git -c alias.x=$'!cat > a <<\\'D\\'\\nx\\cJD\\n%s\\nD' x" % rm,
            "git -c alias.x=\"!cat > a <<'D'\\\n; %s\nx\nD\" x" % rm,
        )
        for command in commands:
            with self.subTest(command=command[:40]):
                self.assertEqual(run_hook(DESTRUCTIVE, command, self._tmp.name), "deny")

    def test_r5_top_level_exact_shape_still_allowed(self):
        rm = "r" + "m -" + "rf build"
        command = "cat > notes.md <<'EOF'\n%s\nEOF" % rm
        self.assertEqual(run_hook(DESTRUCTIVE, command, self._tmp.name), "silent")
