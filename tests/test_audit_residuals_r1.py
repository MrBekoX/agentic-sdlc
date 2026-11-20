"""Round 1 regression tests for the residuals that CHANGELOG `## Unreleased` lists as
"Known and not fixed" after the f430715 bug audit (plan: docs/agentic-sdlc/plans/audit-residuals.md).

Every hook runs as a subprocess on a JSON payload, the way a runtime delivers it. Git fixtures
live in temporary directories with the system and global config switched off.

No literal credential-shaped value appears in this file: the synthetic token is assembled at
runtime from harmless parts.
"""
import importlib.util
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
GIT = shutil.which("git")

WORKTREE_SCAN = REPO / "hooks" / "worktree-scan.mjs"
SCAN_COMMIT = REPO / "hooks" / "scan-commit.mjs"
BRANCH_GUARD = REPO / "hooks" / "branch-guard.mjs"
SECRET_PATTERNS_MJS = REPO / "hooks" / "secret-patterns.mjs"
VALIDATOR = REPO / "scripts" / "validate_artifacts.py"

# Synthetic GitHub-shaped token: prefix + 36 mixed characters, built at runtime.
SECRET = "gh" + "p_" + "Zq8Lm4Tx9" * 4

BASE_ENV = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
for _name in ("AGENTIC_BRANCH_GUARD_BLOCK", "AGENTIC_WORKTREE_SCAN_BLOCK"):
    BASE_ENV.pop(_name, None)

POSIX_FIFO = os.name != "nt" and hasattr(os, "mkfifo")


def git(cwd, *args):
    return subprocess.run(
        [GIT, "-c", "core.hooksPath=" + os.devnull, *args], cwd=str(cwd), env=BASE_ENV,
        check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout


def m(text):
    """Mask the synthetic token in labels and messages."""
    return text.replace(SECRET, "<S>")


def run_hook(hook, command, cwd, *, tool="Bash", env=None, timeout=60):
    """Run a PreToolUse hook; return 'deny', 'ask', 'warn' or 'silent'."""
    hook_env = dict(BASE_ENV, AGENTIC_BRANCH_GUARD_BLOCK="true")
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


def make_repo(root, branch="feature/x"):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", branch)
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "commit.gpgsign", "false")
    (root / "readme.md").write_text("# fixture\n", encoding="utf-8")
    git(root, "add", "readme.md")
    git(root, "commit", "-qm", "base")
    return root


# --------------------------------------------------------------------------------------------
# R1-a: the Stop worktree scan never opens a file that is not a regular file. A FIFO, a device
# or a socket reached by name or through a link used to be read with readFileSync, which blocks
# on a FIFO until the runtime kills the hook - and a killed hook renders no decision at all.
# --------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None or GIT is None, "node and git required")
@unittest.skipUnless(POSIX_FIFO, "FIFOs need a POSIX os.mkfifo")
class TestR1aWorktreeScanNonRegular(unittest.TestCase):

    TIMEOUT = 20

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="audit-r1a-")
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.repo = make_repo(self.base / "repo")
        self.outside = self.base / "outside"
        self.outside.mkdir()
        self.state = self.base / "scan-state.json"

    def _fifo(self, path):
        """Make a FIFO and, where the platform allows it, buffer one line in it.

        Returns the descriptor that holds the buffered line, or None. Holding it open keeps a
        writer on the FIFO, so a reader that opens it gets the line and then waits for more.
        """
        os.mkfifo(str(path))
        try:
            fd = os.open(str(path), os.O_RDWR | os.O_NONBLOCK)
        except OSError:
            return None
        self.addCleanup(os.close, fd)
        os.write(fd, b"buffered-line\n")
        return fd

    def _still_buffered(self, fd):
        if fd is None:
            return
        self.assertEqual(os.read(fd, 64), b"buffered-line\n", "the scan read from the FIFO")

    def _scan(self, env=None):
        hook_env = dict(BASE_ENV, AGENTIC_WORKTREE_SCAN_STATE=str(self.state))
        hook_env.update(env or {})
        proc = subprocess.run(
            [NODE, str(WORKTREE_SCAN)], cwd=str(self.repo), env=hook_env,
            input=json.dumps({"hook_event_name": "Stop", "session_id": "r1a",
                              "cwd": str(self.repo), "stop_hook_active": False}),
            capture_output=True, text=True, encoding="utf-8", timeout=self.TIMEOUT,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-400:])
        return proc.stdout

    def _notes_with_token(self, name="notes.txt"):
        (self.repo / name).write_text("token = " + SECRET + "\n", encoding="utf-8")

    def test_symlink_to_fifo_does_not_hang_and_rest_is_scanned(self):
        fd = self._fifo(self.outside / "pipe")
        (self.repo / "link").symlink_to(self.outside / "pipe")
        self._notes_with_token()
        out = self._scan()
        self.assertIn("notes.txt", out, "the token in notes.txt was not reported")
        self.assertNotIn("(link)", out, "the link to a FIFO was reported")
        self.assertNotIn(SECRET, out, "the report must mask the value")
        self._still_buffered(fd)

    def test_listed_fifo_is_never_read(self):
        # git never lists a FIFO itself, so a shim adds one to the untracked listing: the scan
        # must not trust the listing to name regular files only.
        fd = self._fifo(self.repo / "pipe")
        shim_dir = self.base / "shim"
        shim_dir.mkdir()
        shim = shim_dir / "git"
        shim.write_text(
            "#!/bin/sh\n"
            "case \" $* \" in\n"
            "  *\" ls-files \"*--others*) \"" + GIT + "\" \"$@\"; s=$?; printf 'pipe\\000'; exit $s ;;\n"
            "esac\n"
            "exec \"" + GIT + "\" \"$@\"\n",
            encoding="utf-8")
        shim.chmod(0o755)
        self._notes_with_token()
        out = self._scan(env={"PATH": str(shim_dir) + os.pathsep + BASE_ENV.get("PATH", "")})
        self.assertIn("notes.txt", out, "the token in notes.txt was not reported")
        self._still_buffered(fd)

    def test_fifo_at_the_state_path_does_not_hang(self):
        self.state = self.base / "state-fifo"
        fd = self._fifo(self.state)
        self._notes_with_token()
        out = self._scan()
        self.assertIn("notes.txt", out, "the report was not printed")
        self._still_buffered(fd)
        self.assertFalse(self.state.is_file(), "the FIFO at the state path was replaced")

    def test_symlink_to_device_and_socket_are_skipped(self):
        # GREEN only: before the fix the scan reads /dev/zero until Node's buffer limit.
        if not Path("/dev/zero").exists():
            self.skipTest("no /dev/zero")
        (self.repo / "zero").symlink_to("/dev/zero")
        sock_dir = tempfile.mkdtemp(prefix="r1a-", dir="/tmp")
        self.addCleanup(shutil.rmtree, sock_dir, ignore_errors=True)
        sock_path = os.path.join(sock_dir, "s")
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(server.close)
        server.bind(sock_path)
        server.listen(1)
        (self.repo / "sock").symlink_to(sock_path)
        self._notes_with_token()
        out = self._scan()
        self.assertIn("notes.txt", out, "the token in notes.txt was not reported")
        self.assertNotIn("(zero)", out)
        self.assertNotIn("(sock)", out)

    def test_regular_files_and_links_to_regular_files_still_scanned(self):
        target = self.outside / "kept.txt"
        target.write_text("token = " + SECRET + "\n", encoding="utf-8")
        (self.repo / "linked.txt").symlink_to(target)
        self._notes_with_token()
        out = self._scan()
        self.assertIn("notes.txt", out)
        self.assertIn("linked.txt", out, "a link to a regular file is no longer scanned")



# --------------------------------------------------------------------------------------------
# R1-b: a literal here-document piped into `git commit -F -` is the commit message. The lexer
# kept the body on the `cat` statement, so the commit read no stdin and the message went unscanned.
# --------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR1bPipedHeredocMessage(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="audit-r1b-")
        cls.repo = make_repo(Path(cls._tmp.name) / "repo")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def decide(self, command, **kw):
        return run_hook(SCAN_COMMIT, command, self.repo, **kw)

    @staticmethod
    def _piped(opener, flag, body, closer="EOF"):
        return "cat " + opener + " | git commit --allow-empty " + flag + "\n" + body + "\n" + closer

    def test_piped_heredoc_message_is_scanned(self):
        body = "fix: rotate\n\ntoken " + SECRET
        for flag in ("-F -", "--file=-", "--file -"):
            for opener, closer, text in (("<<'EOF'", "EOF", body), ('<<"EOF"', "EOF", body),
                                         ("<<EOF", "EOF", body), ("<<-EOF", "\tEOF", "\t" + body)):
                command = self._piped(opener, flag, text, closer)
                with self.subTest(command=m(command)[:50]):
                    self.assertEqual(self.decide(command), "deny", m(command))

    def test_piped_heredoc_in_a_shell_payload_is_scanned(self):
        command = 'bash -c "cat <<\'EOF\' | git commit --allow-empty -F -\nfix ' + SECRET + '\nEOF"'
        self.assertEqual(self.decide(command), "deny", m(command))

    def test_piped_heredoc_controls(self):
        # Pins of current behaviour, not of a goal: the secret-bearing producers below (`cat -`,
        # `/bin/cat`, a `cat` with a redirect, `echo`, `printf`) are known gaps, recorded in the
        # CHANGELOG Known limitations; a later fix that scans them should change these expectations.
        secret_body = "fix " + SECRET
        cases = (
            ("clean body", self._piped("<<'EOF'", "-F -", "fix: clean message"), "Bash"),
            ("tee next to a clean commit",
             "cat <<'EOF' | tee notes.md\n" + secret_body + "\nEOF\ngit commit --allow-empty -m 'fix: clean'", "Bash"),
            ("supported -F - form, clean", "git commit --allow-empty -F - <<'EOF'\nfix: clean\nEOF", "Bash"),
            ("cat -", "cat - <<'EOF' | git commit --allow-empty -F -\n" + secret_body + "\nEOF", "Bash"),
            ("/bin/cat", "/bin/cat <<'EOF' | git commit --allow-empty -F -\n" + secret_body + "\nEOF", "Bash"),
            ("cat with a redirect",
             "cat <<'EOF' 2>/dev/null | git commit --allow-empty -F -\n" + secret_body + "\nEOF", "Bash"),
            ("echo", "echo '" + secret_body + "' | git commit --allow-empty -F -", "Bash"),
            ("printf", "printf '%s' '" + secret_body + "' | git commit --allow-empty -F -", "Bash"),
            ("PowerShell tool", self._piped("<<'EOF'", "-F -", secret_body), "PowerShell"),
        )
        for label, command, tool in cases:
            with self.subTest(case=label):
                self.assertEqual(self.decide(command, tool=tool), "silent", m(command))



# --------------------------------------------------------------------------------------------
# R1-c: the validator's secret check had no bearer-token or URL-credential pattern, and its label
# patterns need `:` or `=` right after the label, so a JSON- or Python-quoted key was missed.
# --------------------------------------------------------------------------------------------
def _load_validator():
    spec = importlib.util.spec_from_file_location("_residuals_validator", str(VALIDATOR))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Values assembled at run time; none is a real credential.
BEARER_VALUE = "Ab3dE" * 5                        # 25 characters
URL_PASSWORD = "Qw7Rt9" + "Zx2P"                  # 10 characters
KEY_VALUE = "Zx81Kq" + "92Lm"                     # 10 characters


def _pair(key, value, braces=True):
    """A JSON key-value pair built at run time, so no source line looks like a credential."""
    text = '"%s": "%s"' % (key, value)
    return "{" + text + "}" if braces else text


class TestR1cValidatorSecretShapes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.va = _load_validator()

    def errors(self, line):
        return self.va.scan_placeholders_and_secrets("# Notes\n" + line + "\n")["errors"]

    def test_bearer_url_and_json_quoted_keys_fire(self):
        lines = (
            "Authorization: Bearer " + BEARER_VALUE,
            "DATABASE_URL=postgres://app:" + URL_PASSWORD + "@db.example.invalid/main",
            _pair("api_key", KEY_VALUE),
            _pair("apiKey", KEY_VALUE),
            "settings = {'pass" + "word': '" + KEY_VALUE + "'}",
            _pair("client_secret", KEY_VALUE, braces=False) + ",",
            '"secret"= "' + KEY_VALUE + '"',
        )
        for line in lines:
            value = BEARER_VALUE if "Bearer" in line else URL_PASSWORD if "://" in line else KEY_VALUE
            with self.subTest(line=line.replace(value, "<v>")):
                result = self.errors(line)
                self.assertEqual(result, ["possible_secret:2=***MASKED***"])
                self.assertNotIn(value, json.dumps(result))

    def test_validator_exits_1_and_masks_the_value(self):
        with tempfile.TemporaryDirectory(prefix="audit-r1c-") as tmp:
            spec = Path(tmp, "spec.md")
            spec.write_text("# Spec\n\nAuthorization: Bearer " + BEARER_VALUE + "\n", encoding="utf-8")
            proc = subprocess.run([sys.executable, str(VALIDATOR), "--mode", "spec", "--file", str(spec)],
                                  capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("possible_secret:3=***MASKED***", proc.stdout)
        self.assertNotIn(BEARER_VALUE, proc.stdout + proc.stderr)

    def test_placeholders_do_not_fire(self):
        lines = (
            "Authorization: Bearer ***MASKED***",
            "Authorization: Bearer ${API_TOKEN}",
            "DATABASE_URL=postgres://app:${DB_PASSWORD}@db.example.invalid/main",
            "DATABASE_URL=postgres://app:<password>@db.example.invalid/main",
            "DATABASE_URL=postgres://app:$DB_PASSWORD@db.example.invalid/main",
            '{"api_key": "<token>"}',
            '{"api_key": "${API_KEY}"}',
            '{"secret": "$CLIENT_SECRET"}',
            '{"pass' + 'word": "***MASKED***"}',
            '{"pass' + 'word": "***MASKED:password***"}',
        )
        for line in lines:
            with self.subTest(line=line):
                self.assertEqual(self.errors(line), [])

    def test_lowercase_type_names_and_prose_do_not_fire(self):
        # D15: an all-lowercase word of at most three hyphen-joined parts is a type name or prose.
        lines = (
            '{"pass' + 'word": "string"}',
            '{"api_key": "required"}',
            _pair("client_secret", "rotated-every-month", braces=False),
            "Authorization: Bear" + "er token-refresh-handling",
            "see https://user:" + "password" + "@example.invalid/docs",
            '{"pass' + 'word": {"type": "string", "minLength": 8}}',
            '{"api_key": null}',
        )
        for line in lines:
            with self.subTest(line=line):
                self.assertEqual(self.errors(line), [])

    def test_new_patterns_stay_linear(self):
        quote_label = '"pass' + 'word":'
        lines = ((quote_label + ' "') * 15000,
                 "Bearer " * 30000,
                 ("a://" + "b" * 250 + ":") * 800,
                 "'api_key'" + " " * 200000 + ":x",
                 '"secret"=' + "q" * 200000)
        for line in lines:
            start = time.perf_counter()
            self.va.scan_placeholders_and_secrets(line)
            self.assertLess(time.perf_counter() - start, 2.0, line[:30])

    def test_tracked_agentic_sdlc_artifacts_have_no_finding(self):
        if GIT is None or not (REPO / ".git").exists():
            self.skipTest("not a git checkout")
        listed = subprocess.run([GIT, "ls-files", "-z", "--", "docs/agentic-sdlc"], cwd=str(REPO),
                                capture_output=True, text=True, encoding="utf-8")
        if listed.returncode != 0:
            self.skipTest("git ls-files failed")
        for rel in filter(None, listed.stdout.split("\0")):
            text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
            with self.subTest(path=rel):
                errors = [e for e in self.va.scan_placeholders_and_secrets(text)["errors"]
                          if e.startswith("possible_secret")]
                self.assertEqual(errors, [])


# A JS regex literal: /body/flags (the parser of tests/test_sdlc_mask_parity.py).
_JS_LITERAL = r"/(?:\\.|\[(?:\\.|[^\]\\])*\]|[^/\\\[\n])+/[a-z]*"
_PATTERN_ENTRY = re.compile(r"\{ label: '([^']+)', re: (" + _JS_LITERAL + r")(?:, valueGroup: (\d+))? \}")
_BEARER_RUN = "[A-Za-z0-9._\\-]{20,}"


def _mjs_sources(text):
    entries = {m.group(1): m.group(2) for m in _PATTERN_ENTRY.finditer(text)}
    start = text.index("const TEMPLATE_VALUE = [")
    block = text[start:text.index("];", start)]
    templates = re.findall(r"^\s*(" + _JS_LITERAL + r"),", block, flags=re.MULTILINE)
    return entries, templates


def _expected_mirror(text):
    """The validator's mirrored sources as the .mjs dictates them: the bearer token is group 1."""
    entries, templates = _mjs_sources(text)
    bearer = entries["bearer-token"]
    return {"bearer-token": bearer.replace(_BEARER_RUN, "(" + _BEARER_RUN + ")", 1),
            "url-credential": entries["url-credential"],
            "templates": templates}


class TestR1cValidatorPatternParity(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.va = _load_validator()
        cls.mjs = SECRET_PATTERNS_MJS.read_text(encoding="utf-8")

    def _actual(self):
        return {"bearer-token": self.va.BEARER_TOKEN_SOURCE,
                "url-credential": self.va.URL_CREDENTIAL_SOURCE,
                "templates": list(self.va.TEMPLATE_VALUE_SOURCES)}

    def test_mirrored_sources_equal_the_mjs(self):
        expected = _expected_mirror(self.mjs)
        self.assertGreaterEqual(len(expected["templates"]), 8)
        self.assertIn("(" + _BEARER_RUN + ")", expected["bearer-token"])
        self.assertEqual(self._actual(), expected)

    def test_parity_parser_negative_control(self):
        drifted = self.mjs.replace("[A-Za-z0-9._\\-]{20,}/i", "[A-Za-z0-9._\\-]{24,}/i", 1)
        self.assertNotEqual(drifted, self.mjs)
        self.assertNotEqual(_expected_mirror(drifted), self._actual())

    def test_translation_matches_mask_py(self):
        sys.path.insert(0, str(REPO / "scripts"))
        try:
            from sdlc_runner import mask
        finally:
            sys.path.remove(str(REPO / "scripts"))
        pairs = [(self.va.BEARER_TOKEN_SOURCE, self.va.BEARER_TOKEN_RE),
                 (self.va.URL_CREDENTIAL_SOURCE, self.va.URL_CREDENTIAL_RE)]
        pairs += list(zip(self.va.TEMPLATE_VALUE_SOURCES, self.va.TEMPLATE_VALUE_RES))
        for source, compiled in pairs:
            body, flags = mask._split_literal(source)
            with self.subTest(source=source):
                self.assertEqual(compiled.pattern, mask._translate(body))
                self.assertEqual(compiled.flags & (re.ASCII | re.IGNORECASE),
                                 re.ASCII | (re.IGNORECASE if "i" in flags else 0))



# --------------------------------------------------------------------------------------------
# R1-d: a git call the resolver drops at a budget (payload statements, payload depth, the alias
# walk) was skipped silently, so the commit or push inside it was neither checked nor reported.
# --------------------------------------------------------------------------------------------
SCAN_NOTICE = "a commit inside it was NOT scanned for secrets"
BRANCH_NOTICE = "a commit or push inside it was not checked against protected branches"
PROTECTED_PUSH = "git push origin HEAD:refs/heads/main"


def run_raw(hook, command, cwd, *, block=True, env=None):
    hook_env = dict(BASE_ENV, AGENTIC_BRANCH_GUARD_BLOCK="true" if block else "false")
    hook_env.pop("ZCODE_PLUGIN_ROOT", None)
    hook_env.update(env or {})
    proc = subprocess.run(
        [NODE, str(hook)], cwd=str(cwd),
        input=json.dumps({"tool_name": "Bash", "cwd": str(cwd), "tool_input": {"command": command}}),
        capture_output=True, text=True, encoding="utf-8", env=hook_env, timeout=60,
    )
    if proc.returncode != 0:
        raise AssertionError("hook exited %d: %s" % (proc.returncode, proc.stderr[-400:]))
    return proc.stdout


def _payload(statements):
    return "bash -c " + shlex.quote("; ".join(statements))


def _echoes(n):
    return ["echo n%d" % i for i in range(n)]


def _nested(command, shells):
    for _ in range(shells):
        command = "bash -c " + shlex.quote(command)
    return command


def _bang_alias(n_echoes, last):
    body = "!" + "; ".join(_echoes(n_echoes) + [last])
    return "git -c " + shlex.quote("alias.x=" + body) + " x"


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR1dBudgetsAreLoud(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="audit-r1d-")
        cls.repo = make_repo(Path(cls._tmp.name) / "repo")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def out(self, hook, command, **kw):
        stdout = run_raw(hook, command, self.repo, **kw)
        return json.loads(stdout) if stdout.strip() else {}

    def assertWarns(self, hook, command, notice):
        out = self.out(hook, command)
        self.assertNotIn("hookSpecificOutput", out, "a skipped read must not deny on its own")
        self.assertIn(notice, out.get("systemMessage", ""), command[:60])
        self.assertNotIn("echo n", json.dumps(out), "the notice must not quote the command")

    def test_commit_past_the_payload_budget_warns(self):
        command = _payload(_echoes(130) + ["git commit --allow-empty -m 'fix: clean'"])
        self.assertWarns(SCAN_COMMIT, command, SCAN_NOTICE)

    def test_push_past_the_payload_budget_warns_not_denies(self):
        command = _payload(_echoes(130) + [PROTECTED_PUSH])
        self.assertWarns(BRANCH_GUARD, command, BRANCH_NOTICE)

    def test_payload_depth_cap_warns(self):
        self.assertWarns(SCAN_COMMIT, _nested("git commit --allow-empty -m 'fix: clean'", 4), SCAN_NOTICE)
        self.assertWarns(BRANCH_GUARD, _nested(PROTECTED_PUSH, 4), BRANCH_NOTICE)

    def test_alias_past_the_walk_budget_warns(self):
        self.assertWarns(BRANCH_GUARD, _bang_alias(70, PROTECTED_PUSH), BRANCH_NOTICE)
        self.assertWarns(SCAN_COMMIT, _bang_alias(70, "git commit --allow-empty -m 'fix: clean'"), SCAN_NOTICE)

    def test_early_exit_emits_one_json_object(self):
        command = ("HOME=/nonexistent git zz; "
                   + _payload(_echoes(130) + [PROTECTED_PUSH]))
        stdout = run_raw(BRANCH_GUARD, command, self.repo)
        out = json.loads(stdout)                    # exactly one object, or this raises
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("could not be resolved", reason)
        self.assertIn(BRANCH_NOTICE, reason)
        stdout = run_raw(SCAN_COMMIT, command, self.repo)
        out = json.loads(stdout)
        self.assertIn("could not be resolved", out["systemMessage"])
        self.assertIn(SCAN_NOTICE, out["systemMessage"])

    def test_zcode_maps_the_notice_to_additional_context(self):
        command = _payload(_echoes(130) + ["git commit --allow-empty -m 'fix: clean'"])
        stdout = run_raw(SCAN_COMMIT, command, self.repo, env={"ZCODE_PLUGIN_ROOT": str(REPO)})
        out = json.loads(stdout)
        self.assertIn(SCAN_NOTICE, out["hookSpecificOutput"]["additionalContext"])
        self.assertNotIn("systemMessage", out)

    def test_zcode_maps_the_branch_guard_notice_to_additional_context(self):
        command = _payload(_echoes(130) + [PROTECTED_PUSH])
        stdout = run_raw(BRANCH_GUARD, command, self.repo, env={"ZCODE_PLUGIN_ROOT": str(REPO)})
        out = json.loads(stdout)
        self.assertIn(BRANCH_NOTICE, out["hookSpecificOutput"]["additionalContext"])
        self.assertNotIn("permissionDecision", out["hookSpecificOutput"])

    def test_within_budgets_no_new_notice(self):
        self.assertEqual(self.out(SCAN_COMMIT, _payload(_echoes(100) + ["git commit --allow-empty -m 'fix: clean'"])), {})
        self.assertEqual(self.out(SCAN_COMMIT, _nested("git commit --allow-empty -m 'fix: clean'", 3)), {})
        self.assertEqual(self.out(SCAN_COMMIT, _bang_alias(10, "git commit --allow-empty -m 'fix: clean'")), {})
        for command in (_payload(_echoes(100) + [PROTECTED_PUSH]), _nested(PROTECTED_PUSH, 3),
                        _bang_alias(10, PROTECTED_PUSH)):
            with self.subTest(command=command[:40]):
                out = self.out(BRANCH_GUARD, command)
                self.assertEqual(out.get("hookSpecificOutput", {}).get("permissionDecision"), "deny")
                self.assertNotIn(BRANCH_NOTICE, json.dumps(out))

    def test_long_payload_without_git_emits_no_notice(self):
        command = _payload(_echoes(130)) + " && git status"
        self.assertEqual(self.out(SCAN_COMMIT, command), {})
        self.assertEqual(self.out(BRANCH_GUARD, command), {})



# --------------------------------------------------------------------------------------------
# Round 1 security pins (AC20): no new notice or finding prints a scanned value.
# --------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR1SecurityPins(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="audit-r1-sec-")
        cls.repo = make_repo(Path(cls._tmp.name) / "repo")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_budget_notice_echoes_no_command_text(self):
        command = _payload(["echo " + SECRET] + _echoes(130) + ["git commit --allow-empty -m 'fix: clean'"])
        for hook in (SCAN_COMMIT, BRANCH_GUARD):
            with self.subTest(hook=hook.name):
                stdout = run_raw(hook, command, self.repo)
                self.assertTrue(stdout.strip(), "no notice")
                self.assertNotIn(SECRET, stdout)

    def test_worktree_scan_and_validator_print_no_value(self):
        notes = self.repo / "notes.txt"
        notes.write_text("token = " + SECRET + "\n", encoding="utf-8")
        self.addCleanup(notes.unlink)
        with tempfile.TemporaryDirectory(prefix="audit-r1-state-") as state_dir:
            proc = subprocess.run(
                [NODE, str(WORKTREE_SCAN)], cwd=str(self.repo),
                env=dict(BASE_ENV, AGENTIC_WORKTREE_SCAN_STATE=str(Path(state_dir, "s.json"))),
                input=json.dumps({"hook_event_name": "Stop", "session_id": "pins", "cwd": str(self.repo)}),
                capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertIn("notes.txt", proc.stdout)
        self.assertNotIn(SECRET, proc.stdout + proc.stderr)
        with tempfile.TemporaryDirectory(prefix="audit-r1-va-") as tmp:
            spec = Path(tmp, "spec.md")
            spec.write_text("# Spec\n\n" + _pair("api_key", KEY_VALUE) + "\n"
                            "Authorization: Bearer " + BEARER_VALUE + "\n", encoding="utf-8")
            proc = subprocess.run([sys.executable, str(VALIDATOR), "--mode", "spec", "--file", str(spec)],
                                  capture_output=True, text=True, encoding="utf-8")
        self.assertIn("possible_secret", proc.stdout)
        for value in (KEY_VALUE, BEARER_VALUE):
            self.assertNotIn(value, proc.stdout + proc.stderr)



# --------------------------------------------------------------------------------------------
# Round 1 docs (AC21): the limitations Round 1 fixed are gone, and the portable hooks are described.
# --------------------------------------------------------------------------------------------
class TestR1DocsFollowFixes(unittest.TestCase):

    REMOVED = (
        "`cat <<'EOF' | git commit -F -` is not scanned",
        "a payload past the payload budget is skipped silently",
        "a payload past its budget is skipped silently",
        "follows an untracked symlink to a FIFO",
        "has no bearer-token or URL-credential pattern",
        "and a piped `-F -`",
        # The prose exemption is not the rule for URL userinfo (review L10).
        "For these three shapes a template",
        "For its bearer, URL and quoted-key shapes",
    )

    def test_round1_limitations_removed_and_described(self):
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = changelog[changelog.index("## Unreleased"):changelog.index("\n## ", changelog.index("## Unreleased") + 5)]
        readme = (REPO / "hooks" / "README.md").read_text(encoding="utf-8")
        for phrase in self.REMOVED:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, unreleased)
                self.assertNotIn(phrase, readme)
        troubleshooting = (REPO / "docs" / "troubleshooting.md").read_text(encoding="utf-8")
        for needle in ("agentic-sdlc-scanner", "scanner=stale", "--install"):
            self.assertIn(needle, troubleshooting)
        self.assertIn("agentic-sdlc-scanner", unreleased)
        self.assertIn("agentic-sdlc-scanner", readme)



# --------------------------------------------------------------------------------------------
# Round 1 security review follow-ups (new tasks under contract 03).
# --------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR1SecurityFollowUps(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="audit-r1-fu-")
        cls.repo = make_repo(Path(cls._tmp.name) / "repo")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_own_heredoc_of_a_piped_commit_is_still_scanned(self):
        # Review M1: a redirect on the commit overrides the pipe, so git reads B; attaching only the
        # piped body A must not hide B (the statement union can only add).
        body = "fix " + SECRET
        for command in ("cat <<'A' | git commit --allow-empty -F - <<'B'\nclean\nA\n" + body + "\nB",
                        'bash -c "cat <<\'A\' | git commit --allow-empty -F - <<\'B\'\nclean\nA\n' + body + '\nB"'):
            with self.subTest(command=m(command)[:40]):
                self.assertEqual(run_hook(SCAN_COMMIT, command, self.repo), "deny", m(command))

    def test_piped_copies_do_not_spend_the_payload_budget(self):
        # Review 2 row 1: each piped copy was its own queue item, so 63 piped pairs pushed a later
        # commit past the payload budget that 1905c15 still reached and denied.
        pairs = "".join("cat <<A | git log -n %d\nx\nA\n" % i for i in range(63))
        command = "bash -c '" + pairs + "git commit --allow-empty -m \"fix " + SECRET + "\"'"
        self.assertEqual(run_hook(SCAN_COMMIT, command, self.repo), "deny", m(command[-80:]))

    def test_piped_shell_consumer_is_not_expanded_twice(self):
        # Review 3: a piped copy whose consumer is a shell re-expanded the same payload, and those
        # children spent the budget a later commit needed (1905c15 still reached and denied it).
        inner = "cat <<A | bash -c " + shlex.quote("; ".join(_echoes(100))) + "\nx\nA\n"
        inner += "bash -c " + shlex.quote("git commit --allow-empty -m 'fix " + SECRET + "'")
        command = "bash -c " + shlex.quote(inner)
        self.assertEqual(run_hook(SCAN_COMMIT, command, self.repo), "deny", m(command[-80:]))

    def test_piped_copy_spends_no_shared_work_budget(self):
        # Audit Loop C: a piped copy still charged its text to the resolver's shared work budget, so a
        # long piped consumer tipped `workExhausted` before a later commit was read. A piped producer
        # must leave the outcome exactly as the same command with `;` instead of `|` (1905c15's view).
        script = (
            "const { resolveGitCommands } = await import(process.argv[1]);\n"
            "const q = (s) => \"'\" + s.replace(/'/g, \"'\\\\''\") + \"'\";\n"
            "const rows = [];\n"
            "for (let F = 180000; F <= 280000; F += 10000) {\n"
            "  const seen = [];\n"
            "  for (const sep of [';', '|']) {\n"
            "    const payload = 'cat <<A ' + sep + ' bash -c ' + q('echo ' + 'a'.repeat(F)) + '\\nx\\nA\\ngit commit -m \"fix\"';\n"
            "    const alias = '!bash -c ' + q(payload);\n"
            "    const r = resolveGitCommands('git x', { lookup: (n) => (n === 'x' ? alias : ''), cwd: process.cwd() });\n"
            "    seen.push(r.subcommands.has('commit'));\n"
            "  }\n"
            "  rows.push([F, seen[0], seen[1]]);\n"
            "}\n"
            "console.log(JSON.stringify(rows));\n")
        proc = subprocess.run([NODE, "--input-type=module", "-e", script,
                               (REPO / "hooks" / "git-invocation.mjs").as_uri()],
                              capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr[-400:])
        for size, sequenced, piped in json.loads(proc.stdout):
            with self.subTest(filler=size):
                self.assertEqual(piped, sequenced, "the piped producer changed what the resolver reached")

    def _node_json(self, script):
        proc = subprocess.run([NODE, "--input-type=module", "-e", script,
                               (REPO / "hooks" / "git-invocation.mjs").as_uri()],
                              capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr[-400:])
        return json.loads(proc.stdout)

    def test_piped_body_rides_on_its_statement_not_a_second_item(self):
        # Review 4: a piped copy as its own queue item was read even when its plain copy was dropped,
        # an uncharged re-read. The body now rides on the statement it feeds; a dropped statement
        # drops its body with it, and nothing is read twice.
        rows = self._node_json(
            "const { statementsOf } = await import(process.argv[1]);\n"
            "const sts = statementsOf(\"cat <<A | git commit -F -\\nbody\\nA\\n"
            "cat <<B | git commit -F -\\nother\\nB\");\n"
            "console.log(JSON.stringify(sts.map((s) => [s.text.trim(), s.pipedStdins || null])));\n")
        commits = [r for r in rows if r[0] == "git commit -F -"]
        self.assertEqual(len(commits), 1, rows)
        self.assertEqual(commits[0][1], ["body\n", "other\n"])

    def test_second_piped_body_of_a_repeated_commit_is_scanned(self):
        command = ("cat <<'A' | git commit --allow-empty -F -\nfix: clean\nA\n"
                   "cat <<'B' | git commit --allow-empty -F -\nfix " + SECRET + "\nB")
        self.assertEqual(run_hook(SCAN_COMMIT, command, self.repo), "deny", m(command))

    def test_repeated_piped_commit_reads_its_message_file_once(self):
        # Review 5: each piped body is one more invocation record with the same `-F <file>`, and
        # scan-commit read the file once per record, so 60 repeats of a 1.6 MB file ran a capped heap
        # out and the hook crashed (a crashed hook decides nothing). 1905c15 kept one record for the
        # repeated statement and read the file twice.
        big = self.repo / "big-message.txt"
        big.write_text(("fix: message line " * 4 + "\n") * 22000, encoding="utf-8")
        self.addCleanup(big.unlink)
        command = "".join("cat <<A | git commit --allow-empty -F big-message.txt\nx\nA\n" for _ in range(60))
        env = {"NODE_OPTIONS": "--max-old-space-size=64"}
        self.assertEqual(run_hook(SCAN_COMMIT, command, self.repo, env=env), "silent")

    def _probe(self, head, word):
        return self._node_json(
            "const { resolveGitCommands } = await import(process.argv[1]);\n"
            "const head = " + json.dumps(head) + ";\n"
            "let nest = 'echo ' + 'z'.repeat(" + str(word) + ");\n"
            "for (let i = 0; i < 30; i += 1) nest = 'echo $(' + nest + ')';\n"
            "const cmd = 'bash -c ' + JSON.stringify(head + '; ' + nest);\n"
            "const r = resolveGitCommands(cmd, { lookup: () => '', cwd: process.cwd() });\n"
            "console.log(JSON.stringify([r.probedChars, r.probeLimit, r.skippedReads]));\n")

    def test_message_file_that_is_also_the_applied_patch_is_still_scanned(self):
        # Review 6 pin: one file used as `-F` and as the `git apply --cached` patch is read once; the
        # message scan reads every line of it, so a token on a `+` line is still denied.
        patch = self.repo / "change.patch"
        patch.write_text("--- a/config.py\n+++ b/config.py\n@@ -0,0 +1 @@\n+key = '" + SECRET + "'\n",
                         encoding="utf-8")
        self.addCleanup(patch.unlink)
        command = "git apply --cached change.patch && git commit --allow-empty -F change.patch"
        self.assertEqual(run_hook(SCAN_COMMIT, command, self.repo), "deny")

    def test_skipped_read_probe_is_capped(self):
        # Review 4 row 2: every item a budget dropped ran the git probe over its text. The fillers use up
        # the payload budget, so the 30 nested levels around a 250k word are all dropped; without the
        # cap they probe about 7.75M characters against a limit of about 3.06M.
        head = "; ".join("echo n%d" % i for i in range(140))
        probed, limit, skipped = self._probe(head, 250000)
        self.assertLessEqual(probed, limit)
        self.assertEqual(skipped, 1, "past the cap a drop must still count as not inspected")

    def test_skipped_read_probe_stops_at_the_first_hit(self):
        # The hooks need only whether a dropped text could name git: the first hit ends the probing.
        head = "; ".join(["echo n%d" % i for i in range(130)] + ["git log -1"])
        probed, _, skipped = self._probe(head, 250000)
        self.assertEqual(skipped, 1)
        self.assertLess(probed, 1000, "probing went on after a dropped text named git")

    def test_piped_heredoc_reaches_a_consumer_with_a_substitution(self):
        # Review 2 row 2: the substitution inside the consumer is lexed before it, so the previous
        # statement was not the producer.
        command = ("cat <<'A' | git commit --allow-empty --date=\"$(date -R)\" -F -\nfix " + SECRET + "\nA")
        self.assertEqual(run_hook(SCAN_COMMIT, command, self.repo), "deny", m(command))

    @unittest.skipUnless(os.name != "nt", "POSIX hard links")
    def test_hard_linked_state_file_is_not_truncated(self):
        # Review 2 row 4: O_TRUNC ran before the fstat check, so a hard link at the state path lost
        # its content.
        with tempfile.TemporaryDirectory(prefix="audit-r1-hl-") as tmp:
            victim = Path(tmp, "victim.txt")
            victim.write_text("keep\n", encoding="utf-8")
            state = Path(tmp, "state.json")
            os.link(str(victim), str(state))
            proc = self._scan({"AGENTIC_WORKTREE_SCAN_STATE": str(state)})
            self.assertIn("notes.txt", proc.stdout)
            self.assertEqual(victim.read_text(encoding="utf-8"), "keep\n")

    def _scan(self, env):
        notes = self.repo / "notes.txt"
        notes.write_text("token = " + SECRET + "\n", encoding="utf-8")
        self.addCleanup(lambda: notes.exists() and notes.unlink())
        hook_env = dict(BASE_ENV)
        hook_env.pop("AGENTIC_WORKTREE_SCAN_STATE", None)  # a runner's own setting must not leak in
        hook_env.update(env)
        return subprocess.run(
            [NODE, str(WORKTREE_SCAN)], cwd=str(self.repo), env=hook_env,
            input=json.dumps({"hook_event_name": "Stop", "session_id": "fu", "cwd": str(self.repo)}),
            capture_output=True, text=True, encoding="utf-8", timeout=60)

    @unittest.skipUnless(os.name != "nt", "POSIX symlinks")
    def test_state_file_link_is_never_followed(self):
        # Review M2: a link at the state path made the scan truncate and rewrite its target.
        with tempfile.TemporaryDirectory(prefix="audit-r1-link-") as tmp:
            victim = Path(tmp, "victim.txt")
            victim.write_text("keep\n", encoding="utf-8")
            link = Path(tmp, "state.json")
            link.symlink_to(victim)
            proc = self._scan({"AGENTIC_WORKTREE_SCAN_STATE": str(link)})
            self.assertIn("notes.txt", proc.stdout)
            self.assertEqual(victim.read_text(encoding="utf-8"), "keep\n")
            self.assertTrue(link.is_symlink())

    @unittest.skipUnless(os.name != "nt", "POSIX symlinks and TMPDIR")
    def test_linked_default_state_folder_is_not_used(self):
        # Review M2: a pre-created `agentic-sdlc` folder that is a link (or not the user's own,
        # owner-only folder) is not trusted with the dedup keys.
        with tempfile.TemporaryDirectory(prefix="audit-r1-tmp-") as tmp:
            elsewhere = Path(tmp, "elsewhere")
            elsewhere.mkdir()
            Path(tmp, "agentic-sdlc").symlink_to(elsewhere)
            proc = self._scan({"TMPDIR": tmp})
            self.assertIn("notes.txt", proc.stdout)
            self.assertEqual(list(elsewhere.iterdir()), [])


class TestR1ValidatorUrlCredentialFollowUp(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.va = _load_validator()

    def test_lowercase_url_password_fires_but_placeholder_words_do_not(self):
        # Review L10: the prose exemption suits quoted keys and prose after `Bearer`, not URL userinfo,
        # where a lowercase word is a weak real password; only placeholder words stay clean there.
        fires = "DATABASE_URL=postgres://app:" + "supersecret" + "value@db.example.invalid/main"
        result = self.va.scan_placeholders_and_secrets("# Notes\n" + fires + "\n")["errors"]
        self.assertEqual(result, ["possible_secret:2=***MASKED***"])
        for word in ("password", "changeme", "secret"):
            with self.subTest(word=word):
                line = "see https://user:" + word + "@example.invalid/docs"
                self.assertEqual(self.va.scan_placeholders_and_secrets(line)["errors"], [])


if __name__ == "__main__":
    unittest.main()
