"""Regression tests for the secret, write and git-hook findings SW-1..SW-6 and SW-8..SW-10 of the
2026-11-18 bug audit (session-reports/2026-11-18-bug-audit-f430715.md).

Every credential-shaped value is assembled at runtime from parts or random characters, so this file
holds no secret-shaped literal. Assertions that a value is absent use assertFalse/assertTrue, so a
failure never prints the value.
"""
import json
import os
import secrets
import shutil
import string
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from sdlc_runner import mask  # noqa: E402

NODE = shutil.which("node")
GIT = shutil.which("git")
PY = sys.executable
HOOKS = REPO / "hooks"
PATTERNS = HOOKS / "secret-patterns.mjs"
INSTALLER = REPO / "scripts" / "install_git_hooks.py"

ALNUM = string.ascii_letters + string.digits
B64U = ALNUM + "-_"
UPPER_DIGITS = string.ascii_uppercase + string.digits


def rnd(n, alphabet=ALNUM):
    return "".join(secrets.choice(alphabet) for _ in range(n))


def gh_token():
    return "gh" + "p_" + rnd(36)


def anthropic_key():
    return "sk" + "-ant-" + "api03-" + rnd(93, B64U) + "AA"


def private_key_header(kind):
    return "-----BEGIN " + kind + " PRIV" + "ATE KEY" + ("" if kind != "PGP" else " BLOCK") + "-----"


def private_key_footer(kind):
    return "-----END " + kind + " PRIV" + "ATE KEY" + ("" if kind != "PGP" else " BLOCK") + "-----"


# One node process per call: scanLines (HIGH and BROAD) and redactSecrets (HIGH and BROAD) per text.
_NODE_SCAN = (
    "let c='';process.stdin.setEncoding('utf8');process.stdin.on('data',d=>c+=d).on('end',()=>"
    "import(require('node:url').pathToFileURL(process.argv[1]).href).then(m=>{const t=JSON.parse(c);"
    "process.stdout.write(JSON.stringify(t.map(x=>({high:m.scanLines(x,m.HIGH).map(f=>f.label),"
    "broad:m.scanLines(x,m.BROAD).map(f=>f.label),red:m.redactSecrets(x),"
    "redBroad:m.redactSecrets(x,m.BROAD)}))))}).catch(e=>{process.stderr.write(String(e));process.exit(3)}))"
)


def node_scan(texts):
    proc = subprocess.run([NODE, "-e", _NODE_SCAN, str(PATTERNS)], input=json.dumps(texts),
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    if proc.returncode != 0:
        raise AssertionError("node scan failed: " + proc.stderr[:400])
    return json.loads(proc.stdout)


def _git(args, cwd, env=None, **kw):
    return subprocess.run([GIT, *args], cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", env=env, **kw)


def _isolated_env(**extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AGENTIC_", "GIT_"))}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    env.update(extra)
    return env


def _init_repo(path, env):
    path.mkdir(parents=True, exist_ok=True)
    for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@e.st"), ("config", "user.name", "t"),
                 ("config", "commit.gpgsign", "false")):
        _git(list(args), path, env).check_returncode()


# ---------------------------------------------------------------------------------------------
# SW-1: Anthropic and current OpenAI key forms, prefixed env names, and same-family vendor tokens.
# ---------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None, "node not available")
class TestSW1VendorKeys(unittest.TestCase):
    def setUp(self):
        self.cases = {
            "anthropic-env": ("ANTHROPIC_API_KEY=" + anthropic_key(), "anthropic-key"),
            "anthropic-admin": ("key: " + "sk" + "-ant-admin01-" + rnd(93, B64U) + "AA", "anthropic-key"),
            "openai-proj-dash-early": ("OPENAI_API_KEY=" + "sk" + "-proj-" + "Ab3-" + rnd(150, B64U), "openai-key"),
            "openai-proj-underscore": ("k = " + "sk" + "-proj-" + "x_" + rnd(30) + "_" + rnd(100, B64U), "openai-key"),
            "openai-svcacct": ("OPENAI_API_KEY=" + "sk" + "-svcacct-" + rnd(30, B64U) + "-" + rnd(60), "openai-key"),
            "openai-admin": ("OPENAI_ADMIN_KEY=" + "sk" + "-admin-" + rnd(150, B64U), "openai-key"),
            "openai-legacy": ("OPENAI=" + "sk" + "-" + rnd(48), "openai-key"),
            "aws-sts": ("AWS_ACCESS_KEY_ID=" + "AS" + "IA" + rnd(16, "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"),
                        "aws-access-key-id"),
            "gitlab-pat": ("GITLAB_TOKEN=" + "gl" + "pat-" + rnd(20, B64U), "gitlab-token"),
            "npm-token": ("//registry.npmjs.org/:_authToken=" + "np" + "m_" + rnd(36), "npm-token"),
            "hf-token": ("HF_TOKEN=" + "h" + "f_" + rnd(34, string.ascii_letters), "huggingface-token"),
        }

    def test_sw1_vendor_keys_are_high_and_redacted_in_node_and_python(self):
        texts = [text for text, _label in self.cases.values()]
        results = node_scan(texts)
        for (name, (text, label)), got in zip(self.cases.items(), results):
            token = text.split("=", 1)[-1].split(": ", 1)[-1].split("= ", 1)[-1].strip()
            with self.subTest(case=name):
                self.assertIn(label, got["high"], "HIGH missed the %s form" % name)
                self.assertFalse(token in got["red"], "redactSecrets kept the %s value" % name)
                self.assertFalse(token in mask.mask_text(text), "mask.py kept the %s value" % name)
                self.assertEqual(mask.redact_labelled(text, mask.HIGH), got["red"], "mask.py differs from the .mjs")
                self.assertEqual(mask.redact_labelled(text), got["redBroad"], "mask.py differs from the .mjs")

    def test_sw1_assigned_secret_matches_prefixed_env_names(self):
        value = rnd(28)
        names = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MYAPP_SECRET", "GITHUB_CLIENT_SECRET",
                 "X_AUTH_TOKEN", "DJANGO_SECRET_KEY", "SECRET_KEY")
        texts = [name + "=" + value for name in names]
        for name, text, got in zip(names, texts, node_scan(texts)):
            with self.subTest(name=name):
                self.assertEqual(got["broad"], ["assigned-secret"])
                self.assertFalse(value in got["redBroad"])
                self.assertFalse(value in mask.mask_text(text))

    def test_sw1_controls_stay_clean(self):
        controls = [
            "task-runner --skip-proj-checks",
            "npm_config_cache_directory_for_the_build_server=1",
            "hf_hub_download_with_a_long_snake_case_name()",
            "AWS_REGION=" + "ASIA" + "-pacific",
            "hashed_password = get_password_hash(user.password)",
            "secret_key_id = settings.lookup_identifier_value",
            "password=<your-password>",
            "sk" + "-ant-" + "api03-short",
        ]
        for text, got in zip(controls, node_scan(controls)):
            with self.subTest(text=text):
                self.assertEqual(got["broad"], [])
                self.assertEqual(mask.mask_text(text), text)


# ---------------------------------------------------------------------------------------------
# SW-2: PGP armored private key blocks.
# ---------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None, "node not available")
class TestSW2PgpPrivateKey(unittest.TestCase):
    def test_sw2_pgp_private_key_block_is_detected_and_fully_redacted(self):
        body = rnd(64, ALNUM + "+/")
        block = "\n".join([private_key_header("PGP"), "", body, "=" + rnd(4), private_key_footer("PGP")])
        text = "before\n" + block + "\nafter"
        got = node_scan([text])[0]
        self.assertIn("private-key", got["high"])
        self.assertEqual(got["red"], "before\n***MASKED:private-key***\nafter")
        self.assertEqual(mask.redact_labelled(text, mask.HIGH), got["red"])
        self.assertFalse(body in mask.mask_text(text))

    def test_sw2_public_key_block_stays_clean(self):
        text = "-----BEGIN PGP PUBLIC KEY BLOCK-----\n" + rnd(40) + "\n-----END PGP PUBLIC KEY BLOCK-----"
        got = node_scan([text])[0]
        self.assertEqual(got["broad"], [])
        self.assertEqual(mask.mask_text(text), text)


# ---------------------------------------------------------------------------------------------
# SW-3: json-credential and jwt must stay linear on a long single line.
# ---------------------------------------------------------------------------------------------
_NODE_TIMING = (
    "import(require('node:url').pathToFileURL(process.argv[1]).href).then(m=>{"
    "const n=Number(process.argv[2]);const shapes={"
    "'quote-key':'\"'+'key '.repeat(n/4),'quote-token':'\"'+'token '.repeat(n/6),"
    "'jwt-run':'eyJabcde-'.repeat(n/9),'jwt-dots':'eyJabcdefgh.'.repeat(n/12)};const out={};"
    "for(const[k,s]of Object.entries(shapes)){const t0=process.hrtime.bigint();m.scanLines(s,m.BROAD);"
    "m.redactSecrets(s,m.BROAD);out[k]=Number(process.hrtime.bigint()-t0)/1e6;}"
    "process.stdout.write(JSON.stringify(out));})"
)


@unittest.skipIf(NODE is None, "node not available")
class TestSW3LinearPatterns(unittest.TestCase):
    BOUND_MS = 2500  # generous: the quadratic shapes took 13 s and more at 256 KB

    def test_sw3_node_patterns_are_linear_on_long_single_lines(self):
        for size in (64 * 1024, 256 * 1024):
            proc = subprocess.run([NODE, "-e", _NODE_TIMING, str(PATTERNS), str(size)], capture_output=True,
                                  text=True, encoding="utf-8", timeout=180)
            self.assertEqual(proc.returncode, 0, proc.stderr[:400])
            for shape, ms in json.loads(proc.stdout).items():
                with self.subTest(size=size, shape=shape):
                    self.assertLess(ms, self.BOUND_MS, "%s at %d bytes took %.0f ms" % (shape, size, ms))

    def test_sw3_python_mask_is_linear_on_long_single_lines(self):
        size = 256 * 1024
        shapes = {
            "quote-key": '"' + "key " * (size // 4),
            "jwt-run": "eyJabcde-" * (size // 9),
        }
        for shape, text in shapes.items():
            with self.subTest(shape=shape):
                started = time.perf_counter()
                mask.mask_text(text)
                elapsed = time.perf_counter() - started
                self.assertLess(elapsed, 5.0, "%s took %.1f s" % (shape, elapsed))

    def test_sw3_normal_lines_are_still_found(self):
        value = rnd(24)
        jwt = "ey" + "J" + rnd(20, B64U) + ".eyJ" + rnd(30, B64U) + "." + rnd(43, B64U)
        texts = [
            '{"client_secret": "' + value + '"}',
            '{"name": "x", "apiKey": "' + value + '", "n": 1}',
            "Cookie: session=" + jwt,
            "url?id_token=" + jwt + "&x=1",
        ]
        labels = ("json-credential", "json-credential", "jwt", "jwt")
        for text, label, got in zip(texts, labels, node_scan(texts)):
            with self.subTest(text=text[:20]):
                self.assertIn(label, got["high"])
                self.assertFalse(value in got["red"] or jwt in got["red"])
                self.assertEqual(mask.redact_labelled(text, mask.HIGH), got["red"])

    def test_sw3_codex_write_guard_denies_a_token_on_a_long_line_in_time(self):
        token = gh_token()
        line = '"' + "key " * (96 * 1024 // 4) + "eyJabcde-" * (96 * 1024 // 9) + " " + token
        patch = "*** Begin Patch\n*** Add File: big.txt\n+" + line + "\n*** End Patch\n"
        payload = {"tool_name": "apply_patch", "tool_input": {"command": patch}, "cwd": str(REPO)}
        started = time.perf_counter()
        proc = subprocess.run([NODE, str(HOOKS / "scan-write-codex.mjs")], input=json.dumps(payload),
                              capture_output=True, text=True, encoding="utf-8", timeout=120)
        elapsed = time.perf_counter() - started
        self.assertEqual(proc.returncode, 0, proc.stderr[:400])
        self.assertLess(elapsed, 10.0, "the Codex write guard took %.1f s (hook timeout 20 s)" % elapsed)
        self.assertIn('"permissionDecision":"deny"', proc.stdout)
        self.assertFalse(token in proc.stdout)


# ---------------------------------------------------------------------------------------------
# SW-4: raw-mode redaction of JSONL lines, and short password values under a password key.
# ---------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None, "node not available")
class TestSW4JsonlRedaction(unittest.TestCase):
    def _redact(self, text, *flags):
        # Bytes in and out: text mode would turn the CRLF this test checks into LF.
        proc = subprocess.run([NODE, str(HOOKS / "redact-sensitive.mjs"), *flags], input=text.encode("utf-8"),
                              capture_output=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr[:400])
        return proc.stdout.decode("utf-8")

    def test_sw4_raw_mode_redacts_values_inside_jsonl_lines(self):
        pw = "Zq" + rnd(12) + "7"
        cs = rnd(24)
        contents = "\n".join(["DB_PASSWORD=\"" + pw + "\"", '{"client_secret": "' + cs + '"}',
                              'password: "' + pw + '"'])
        line = json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Write", "input": {"file_path": "config/.env", "content": contents}}]}})
        out = self._redact("first plain line\n" + line + "\n" + line + "\r\n")
        self.assertFalse(pw in out, "a password-literal value survived raw JSONL redaction")
        self.assertFalse(cs in out, "a json-credential value survived raw JSONL redaction")
        lines = out.split("\n")
        self.assertEqual(lines[0], "first plain line")
        record = json.loads(lines[1])
        self.assertEqual(record["message"]["content"][0]["input"]["file_path"], "config/.env")
        self.assertTrue(lines[2].endswith("\r"), "the CRLF line ending was not preserved")
        json.loads(lines[2])

    def test_sw4_short_password_value_under_a_password_key_is_masked(self):
        short = "Wq7" + rnd(6)
        record = {"user": "app", "nested": {}}
        record["pass" + "word"] = short
        record["nested"]["db_" + "pass" + "word"] = short + "x"
        for flags, text in ((("--json",), json.dumps(record)), ((), json.dumps(record) + "\n")):
            with self.subTest(flags=flags):
                out = self._redact(text, *flags)
                self.assertFalse(short in out, "a short password value survived JSON redaction")
                self.assertEqual(json.loads(out)["user"], "app")

    def test_sw4_quoted_password_values_are_redacted_whole(self):
        # The guard's value class stops at a blank, `;`, a quote or `\`: durable redaction kept the rest
        # of a quoted value, or all of it when its first word is under six characters.
        key = "PASS" + "WORD"
        tail = rnd(12)
        cases = {
            "blank": (key + '="Qm7 ' + tail + '"', "***MASKED:password-literal***" + '"'),
            "semicolon": ("pass" + "word: 'Qm7Tz2;" + tail + "' # x", "***MASKED:password-literal***' # x"),
            "escaped": ("DB_" + key + '=\\"Zq' + tail + '\\" next',
                        "***MASKED:password-literal***" + '\\" next'),
        }
        texts = [text for text, _want in cases.values()]
        for (name, (text, want)), got in zip(cases.items(), node_scan(texts)):
            with self.subTest(case=name):
                self.assertEqual(got["red"], want)
                self.assertEqual(mask.redact_labelled(text, mask.HIGH), want)
                self.assertEqual(mask.redact_labelled(text), got["redBroad"])
                self.assertFalse(tail in self._redact(text + "\n"))
        controls = ["pass" + 'word: "<your-password>"', "pass" + 'word = "${DB_PW}"', key + '="abc"',
                    "pass" + 'word: ""']
        for text, got in zip(controls, node_scan(controls)):
            with self.subTest(control=text):
                self.assertEqual(got["red"], text)
                self.assertEqual(mask.mask_text(text), text)

    def test_sw4_unchanged_and_non_json_lines_are_byte_identical(self):
        token = gh_token()
        text = '{"a": 1,   "b": "plain"}\n[1, 2]\nnot json {\n  "k": "v",\necho ' + token + "\n"
        out = self._redact(text)
        self.assertEqual(out.split("\n")[:4], text.split("\n")[:4])
        self.assertFalse(token in out)
        self.assertIn("***MASKED:github-token***", out)


# ---------------------------------------------------------------------------------------------
# SW-5: commit-message scan stops at git's scissors line; the block advice matches the hook.
# ---------------------------------------------------------------------------------------------
CUT = "-" * 24 + " >8 " + "-" * 24


@unittest.skipIf(NODE is None or GIT is None or os.name == "nt", "node, git and a POSIX editor required")
class TestSW5Scissors(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sw5-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.env = _isolated_env()
        self.repo = self.tmp / "repo"
        _init_repo(self.repo, self.env)
        self.token = gh_token()
        (self.repo / "config.py").write_text("TOKEN = '" + self.token + "'\nother = 1\n", encoding="utf-8")
        _git(["add", "-A"], self.repo, self.env).check_returncode()
        _git(["commit", "-q", "-m", "base"], self.repo, self.env).check_returncode()
        result = subprocess.run([PY, str(INSTALLER), "--install", "--repo", str(self.repo)], env=self.env,
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.editor = self.tmp / "editor.sh"
        self.editor.write_text('#!/bin/sh\nf="$1"; { echo "remove leaked token"; cat "$f"; } > "$f.new"'
                               ' && mv "$f.new" "$f"\n', encoding="utf-8")
        self.editor.chmod(0o700)

    def _remove_secret_and_commit(self, *git_opts):
        (self.repo / "config.py").write_text("other = 1\n", encoding="utf-8")
        _git(["add", "-A"], self.repo, self.env).check_returncode()
        env = dict(self.env, GIT_EDITOR=str(self.editor))
        return _git([*git_opts, "commit", "-v"], self.repo, env)

    def test_sw5_verbose_commit_that_removes_a_secret_is_allowed(self):
        result = self._remove_secret_and_commit()
        self.assertEqual(result.returncode, 0, "removing a secret was blocked: " + result.stderr[-600:])
        self.assertEqual(_git(["log", "-1", "--format=%s"], self.repo, self.env).stdout.strip(),
                         "remove leaked token")

    def test_sw5_custom_comment_char_is_honoured(self):
        result = self._remove_secret_and_commit("-c", "core.commentChar=;")
        self.assertEqual(result.returncode, 0, "removing a secret was blocked: " + result.stderr[-600:])

    def test_sw5_text_after_a_typed_scissors_line_is_still_scanned(self):
        # Without -v, git keeps everything after a scissors line the author typed into -m.
        (self.repo / "other.txt").write_text("x\n", encoding="utf-8")
        _git(["add", "-A"], self.repo, self.env).check_returncode()
        for tail in ("note " + self.token, "@@ -1 +1 @@\n+" + self.token):
            with self.subTest(tail=tail[:8]):
                message = "subject\n\n# " + CUT + "\n" + tail + "\n"
                result = _git(["commit", "-m", message], self.repo, self.env)
                self.assertNotEqual(result.returncode, 0, "a secret after a typed scissors line was committed")
                self.assertIn("github-token (commit message)", result.stderr)
                self.assertFalse(self.token in result.stderr)

    def test_sw5_added_secret_in_a_verbose_commit_is_still_blocked(self):
        (self.repo / "new.py").write_text("KEY = '" + gh_token() + "'\n", encoding="utf-8")
        _git(["add", "-A"], self.repo, self.env).check_returncode()
        env = dict(self.env, GIT_EDITOR=str(self.editor))
        result = _git(["commit", "-v"], self.repo, env)
        self.assertNotEqual(result.returncode, 0, "an added secret was committed under -v")

    def test_sw5_advice_matches_the_blocking_hook(self):
        message = self.tmp / "msg.txt"
        message.write_text("subject " + self.token + "\n", encoding="utf-8")
        for mode in ("prepare-commit-msg", "commit-msg"):
            with self.subTest(mode=mode):
                result = subprocess.run([NODE, str(HOOKS / "git-hook-scan.mjs"), mode, str(message)],
                                        cwd=str(self.repo), env=self.env, capture_output=True, text=True,
                                        encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 1)
                self.assertNotIn("`git commit --no-verify` bypasses this hook", result.stderr)
                self.assertIn("prepare-commit-msg", result.stderr)
                self.assertIn("agentic-sdlc:allow-secret", result.stderr)
                # R2-SW-6: turning every hook off also turns off the backstop; an agent must ask.
                self.assertNotIn("core.hooksPath", result.stderr)
                self.assertIn("ask the user", result.stderr)
                if mode == "prepare-commit-msg":
                    self.assertIn("--no-verify` does not skip", result.stderr)

    def test_r2_sw1_typed_diff_lines_below_a_scissors_line_are_scanned(self):
        # Without -v git records every line below a typed scissors line. Only lines of the real staged
        # diff may be skipped as old content; typed `@@`, ` ` and `-` lines are message text.
        other = gh_token()
        (self.repo / "other.txt").write_text("x\n", encoding="utf-8")
        _git(["add", "-A"], self.repo, self.env).check_returncode()
        tails = ("diff x\n@@ -1 +1 @@ " + other + "\n",
                 "diff --git a/x b/x\n@@ -1 +1 @@\n " + other + "\n",
                 "diff --git a/x b/x\n@@ -1 +1 @@\n-" + other + "\n")
        for tail in tails:
            with self.subTest(tail=tail[:14]):
                message = "subject\n\n# " + CUT + "\n" + tail
                result = _git(["commit", "-m", message], self.repo, self.env)
                self.assertNotEqual(result.returncode, 0, "a typed diff line hid a secret from the message scan")
                self.assertIn("github-token (commit message)", result.stderr)
                self.assertFalse(other in result.stderr)


# ---------------------------------------------------------------------------------------------
# SW-6: one oversized diff must not turn off the whole tracked-change scan.
# ---------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestSW6OversizedDiff(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sw6-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.env = _isolated_env()
        self.repo = self.tmp / "repo"
        _init_repo(self.repo, self.env)
        (self.repo / "fixture.txt").write_text("old\n", encoding="utf-8")
        (self.repo / "app.cfg").write_text("name = app\n", encoding="utf-8")
        _git(["add", "-A"], self.repo, self.env).check_returncode()
        _git(["commit", "-q", "-m", "base"], self.repo, self.env).check_returncode()
        # A regenerated fixture: about 7 MB of new lines, over both diff caps.
        row = "data " + "z" * 70 + "\n"
        (self.repo / "fixture.txt").write_text(row * (7 * 1024 * 1024 // len(row)), encoding="utf-8")
        self.token = gh_token()
        (self.repo / "app.cfg").write_text("name = app\ntoken = " + self.token + "\n", encoding="utf-8")

    def test_sw6_pre_commit_scans_the_small_file_and_names_the_skipped_one(self):
        _git(["add", "-A"], self.repo, self.env).check_returncode()
        result = subprocess.run([NODE, str(HOOKS / "git-hook-scan.mjs"), "pre-commit"], cwd=str(self.repo),
                                env=self.env, capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(result.returncode, 1, "the small secret was not found: " + result.stderr[-400:])
        self.assertIn("github-token", result.stderr)
        self.assertIn("fixture.txt", result.stderr)
        self.assertFalse(self.token in result.stderr)

    def test_sw6_worktree_scan_reports_the_small_file(self):
        env = dict(self.env, AGENTIC_WORKTREE_SCAN_STATE=str(self.tmp / "state.json"))
        payload = {"hook_event_name": "Stop", "session_id": "sw6", "cwd": str(self.repo), "stop_hook_active": False}
        result = subprocess.run([NODE, str(HOOKS / "worktree-scan.mjs")], cwd=str(self.repo), env=env,
                                input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8",
                                timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip(), "worktree-scan stayed silent")
        message = json.loads(result.stdout)["systemMessage"]
        self.assertIn("github-token (uncommitted change)", message)
        self.assertIn("fixture.txt", message)
        self.assertFalse(self.token in result.stdout)


# ---------------------------------------------------------------------------------------------
# SW-8 / SW-9: the write scanner's pre-write and NotebookEdit shapes.
# ---------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None, "node not available")
class TestSW8SW9WriteScanner(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sw8-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.token = gh_token()
        self.existing = self.tmp / "leaked.env.bak"
        self.existing.write_text("TOKEN=" + self.token + "\n", encoding="utf-8")

    def _scan_write(self, payload):
        proc = subprocess.run([NODE, str(HOOKS / "scan-write.mjs")], input=json.dumps(payload), cwd=str(self.tmp),
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def _cursor(self, payload):
        proc = subprocess.run([NODE, str(HOOKS / "cursor-launch.mjs"), "--event", "preToolUse", "--handler",
                               "scan-write.mjs"], input=json.dumps(payload), cwd=str(self.tmp),
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_sw8_pre_write_event_does_not_scan_the_old_file(self):
        out = self._scan_write({"hook_event_name": "PreToolUse", "tool_name": "Delete", "cwd": str(self.tmp),
                                "tool_input": {"file_path": str(self.existing)}})
        self.assertEqual(out, "")

    def test_sw8_cursor_delete_of_a_file_with_a_secret_is_allowed(self):
        out = self._cursor({"tool_name": "Delete", "cwd": str(self.tmp),
                            "tool_input": {"path": str(self.existing)}})
        self.assertEqual(out.get("permission"), "allow", out)

    def test_sw8_cursor_edit_without_known_text_does_not_scan_the_old_file(self):
        # A pre-write edit whose new text sits in a field the adapter does not map: the file on disk is
        # the old content, so its existing secret is not this write's.
        out = self._cursor({"tool_name": "StrReplace", "cwd": str(self.tmp),
                            "tool_input": {"path": str(self.existing), "old_str": "TOKEN", "new_str": "KEY"}})
        self.assertEqual(out.get("permission"), "allow", out)

    def test_sw8_cursor_write_with_a_secret_is_still_denied(self):
        out = self._cursor({"tool_name": "Write", "cwd": str(self.tmp),
                            "tool_input": {"path": "src/app.py", "contents": "token = '" + gh_token() + "'\n"}})
        self.assertEqual(out.get("permission"), "deny", out)

    def test_sw8_cursor_wiring_does_not_route_delete_to_the_write_scanner(self):
        wire = json.loads((HOOKS / "hooks-cursor.json").read_text(encoding="utf-8"))
        entry = next(item for item in wire["hooks"]["preToolUse"] if "scan-write.mjs" in item["command"])
        self.assertNotIn("Delete", entry["matcher"].split("|"))
        self.assertIn("Write", entry["matcher"].split("|"))

    def test_sw9_notebook_edit_new_source_is_scanned(self):
        out = self._scan_write({"hook_event_name": "PostToolUse", "tool_name": "NotebookEdit", "cwd": str(self.tmp),
                                "tool_input": {"notebook_path": str(self.tmp / "explore.ipynb"), "cell_id": "c1",
                                               "new_source": "import os\nos.environ['T'] = '" + gh_token() + "'\n",
                                               "edit_mode": "replace"}})
        self.assertTrue(out, "a secret in NotebookEdit new_source was not reported")
        self.assertIn("github-token", json.loads(out)["systemMessage"])
        self.assertIn("explore.ipynb", json.loads(out)["systemMessage"])

    def test_sw9_notebook_cell_delete_does_not_rescan_the_notebook(self):
        notebook = self.tmp / "nb.ipynb"
        notebook.write_text(json.dumps({"cells": [{"source": ["T = '" + gh_token() + "'"]}]}), encoding="utf-8")
        out = self._scan_write({"hook_event_name": "PostToolUse", "tool_name": "NotebookEdit", "cwd": str(self.tmp),
                                "tool_input": {"notebook_path": str(notebook), "cell_id": "c1",
                                               "edit_mode": "delete"}})
        self.assertEqual(out, "")


# ---------------------------------------------------------------------------------------------
# SW-10: worktree-scan honours stop_hook_active only when it can block.
# ---------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestSW10StopHookActive(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sw10-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.env = _isolated_env()
        self.repo = self.tmp / "repo"
        _init_repo(self.repo, self.env)
        (self.repo / ".env").write_text("TOKEN=" + gh_token() + "\n", encoding="utf-8")

    def _run(self, **env_extra):
        env = dict(self.env, AGENTIC_WORKTREE_SCAN_STATE=str(self.tmp / ("state-%d.json" % len(env_extra))),
                   **env_extra)
        payload = {"hook_event_name": "Stop", "session_id": "sw10", "cwd": str(self.repo), "stop_hook_active": True}
        proc = subprocess.run([NODE, str(HOOKS / "worktree-scan.mjs")], cwd=str(self.repo), env=env,
                              input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def test_sw10_advisory_mode_scans_even_when_stop_hook_active(self):
        out = self._run()
        self.assertTrue(out.strip(), "the advisory scan was skipped on stop_hook_active")
        self.assertNotIn("decision", json.loads(out))

    def test_sw10_blocking_mode_still_skips_on_stop_hook_active(self):
        self.assertEqual(self._run(AGENTIC_WORKTREE_SCAN_BLOCK="true"), "")



# ---------------------------------------------------------------------------------------------
# Round 2 (security review of the integrated fixes): R2-SW-2 .. R2-SW-5, R2-SW-7, R2-SW-8.
# ---------------------------------------------------------------------------------------------
def _redact_raw(text, *flags):
    proc = subprocess.run([NODE, str(HOOKS / "redact-sensitive.mjs"), *flags], input=text.encode("utf-8"),
                          capture_output=True, timeout=120)
    return proc.returncode, proc.stdout.decode("utf-8"), proc.stderr.decode("utf-8", "replace")


@unittest.skipIf(NODE is None, "node not available")
class TestR2Redaction(unittest.TestCase):
    def test_r2_sw2_numeric_value_and_shadowed_duplicate_key_are_masked(self):
        digits = "".join(secrets.choice(string.digits[1:]) for _ in range(12))
        token = gh_token()
        line1 = '{"pass' + 'word": ' + digits + ', "user": "app"}'
        line2 = '{"note": "' + token + '", "note": "ok"}'
        code, out, err = _redact_raw(line1 + "\n" + line2 + "\n")
        self.assertEqual(code, 0, err[:300])
        self.assertFalse(digits in out, "a numeric password survived raw JSONL redaction")
        self.assertFalse(token in out, "a value under a shadowed duplicate key survived raw JSONL redaction")
        for line in out.splitlines():
            json.loads(line)
        code, out, err = _redact_raw(line1, "--json")
        self.assertEqual(code, 0, err[:300])
        self.assertFalse(digits in out, "a numeric password survived --json redaction")

    def test_r2_sw8_deeply_nested_jsonl_line_falls_back_to_text_redaction(self):
        token = gh_token()
        deep = '{"a":' * 30000 + '"' + token + '"' + "}" * 30000
        code, out, err = _redact_raw("plain " + gh_token() + "\n" + deep + "\n")
        self.assertEqual(code, 0, "the adapter crashed on a deeply nested line: " + err[-300:])
        self.assertFalse(token in out)
        self.assertIn("***MASKED:github-token***", out.split("\n")[0])


_NODE_GLUED_TIMING = (
    "import(require('node:url').pathToFileURL(process.argv[1]).href).then(m=>{"
    "const n=Number(process.argv[2]);const A='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';"
    "const r=k=>{let s='';for(let i=0;i<k;i++)s+=A[Math.floor(Math.random()*A.length)];return s;};"
    "const unit={'akia-skproj':()=>'-AKIA'+r(16)+'sk-proj-','akia-eyJ':()=>'-AKIA'+r(16)+'eyJabcdefgh',"
    "'ghp-glpat':()=>'ghp_'+r(36)+'glpat-'};const out={};"
    "for(const[k,f]of Object.entries(unit)){let s='';while(s.length<n)s+=f();"
    "const t0=process.hrtime.bigint();m.scanLines(s,m.BROAD);m.redactSecrets(s,m.BROAD);"
    "out[k]=Number(process.hrtime.bigint()-t0)/1e6;}process.stdout.write(JSON.stringify(out));})"
)


@unittest.skipIf(NODE is None, "node not available")
class TestR2Patterns(unittest.TestCase):
    def test_r2_sw3_glued_token_boundaries_stay_linear_in_node(self):
        # One long line of glued tokens: every token end is a boundary, and the boundary re-scan ran each
        # pattern from there to the end of the run. 64 KB took 5 s before the fix.
        for size, bound_ms in ((128 * 1024, 2000), (1024 * 1024, 4000)):
            proc = subprocess.run([NODE, "-e", _NODE_GLUED_TIMING, str(PATTERNS), str(size)], capture_output=True,
                                  text=True, encoding="utf-8", timeout=900)
            self.assertEqual(proc.returncode, 0, proc.stderr[:400])
            for shape, ms in json.loads(proc.stdout).items():
                if ms >= bound_ms:
                    self.fail("%s at %d bytes took %.0f ms" % (shape, size, ms))

    def test_r2_sw3_glued_token_boundaries_stay_linear_in_python(self):
        alphabet = string.ascii_uppercase + string.digits
        units = {
            "akia-skproj": lambda: "-AK" + "IA" + rnd(16, alphabet) + "sk" + "-proj-",
            "akia-eyJ": lambda: "-AK" + "IA" + rnd(16, alphabet) + "eyJ" + "abcdefgh",
        }
        for size, bound in ((128 * 1024, 4.0), (1024 * 1024, 12.0)):
            for shape, unit in units.items():
                parts, length = [], 0
                while length < size:
                    parts.append(unit())
                    length += len(parts[-1])
                text = "".join(parts)
                started = time.perf_counter()
                mask.mask_text(text)
                elapsed = time.perf_counter() - started
                if elapsed >= bound:
                    self.fail("%s at %d bytes took %.1f s" % (shape, size, elapsed))

    def test_r2_sw4_jwt_glued_after_a_dash_is_found(self):
        jwt = "ey" + "J" + rnd(20, B64U) + ".eyJ" + rnd(30, B64U) + "." + rnd(43, B64U)
        texts = ["Cookie: session-" + jwt, "x-auth-token-" + jwt + " rest", "id_" + jwt]
        for text, got in zip(texts, node_scan(texts)):
            with self.subTest(text=text[:16]):
                self.assertIn("jwt", got["high"])
                self.assertFalse(jwt in got["red"])
                self.assertFalse(jwt in mask.mask_text(text))
                self.assertEqual(mask.redact_labelled(text, mask.HIGH), got["red"])

    def test_r2_sw5_key_followed_by_padding_is_not_read_as_degenerate(self):
        head = rnd(20)
        texts = ["OPENAI_API_KEY=" + "sk" + "-proj-" + head + "-" + "a" * 200,
                 "k=" + "gl" + "pat-" + head + "_" + "x" * 120]
        for text, got in zip(texts, node_scan(texts)):
            with self.subTest(text=text[:20]):
                self.assertTrue(got["high"], "a real key followed by padding was suppressed as degenerate")
                self.assertFalse(head in got["red"])
                self.assertFalse(head in mask.mask_text(text))
                self.assertEqual(mask.redact_labelled(text, mask.HIGH), got["red"])
        controls = ["TOKEN = " + "gh" + "p_" + "x" * 36, "OPENAI=" + "sk" + "-proj-" + "x" * 60]
        for text, got in zip(controls, node_scan(controls)):
            with self.subTest(control=text[:16]):
                self.assertEqual(got["high"], [], "a degenerate placeholder is now reported")


# A fake git for boundedDiff: the whole diff overflows, the listing returns `files` small files and each
# group call takes `delay` seconds.
_NODE_BOUNDED = (
    "import(require('node:url').pathToFileURL(process.argv[1]).href).then(n=>{"
    "const files=Number(process.argv[2]);const delay=Number(process.argv[3]);const budget=Number(process.argv[4]);"
    "const calls=[];const sleep=ms=>Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,ms);"
    "const git=(args)=>{calls.push(args);if(!args.includes('--')&&!args.includes('--numstat')){"
    "const e=new Error('spawnSync git ENOBUFS');e.code='ENOBUFS';throw e;}"
    "if(args.includes('--numstat')){let o='';for(let i=0;i<files;i++)o+='1\\t0\\tf'+i+'.txt\\0';return o;}"
    "sleep(delay);return 'diff --git a/x b/x\\n@@ -0,0 +1 @@\\n+x\\n';};"
    "const t0=Date.now();const opts=budget>0?{deadline:Date.now()+budget}:{};"
    "const r=n.boundedDiff(git,['diff','HEAD','--unified=0'],opts);"
    "process.stdout.write(JSON.stringify({ms:Date.now()-t0,skipped:r.skipped.length,"
    "listing:calls.find(a=>a.includes('--numstat'))}));})"
)


@unittest.skipIf(NODE is None, "node not available")
class TestR2SW7BoundedDiff(unittest.TestCase):
    def _run(self, files, delay_ms, budget_ms):
        proc = subprocess.run([NODE, "-e", _NODE_BOUNDED, str(HOOKS / "scan-commit-names.mjs"), str(files),
                               str(delay_ms), str(budget_ms)], capture_output=True, text=True,
                              encoding="utf-8", timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr[:400])
        return json.loads(proc.stdout)

    def test_r2_sw7_the_fallback_stops_at_its_deadline_and_names_the_rest(self):
        out = self._run(3000, 60, 300)
        self.assertLess(out["ms"], 1500, "the per-file fallback ignored its wall-clock budget")
        self.assertGreater(out["skipped"], 2000, "files past the deadline were not named as not scanned")

    def test_r2_sw7_the_fallback_listing_keeps_unmerged_paths(self):
        out = self._run(3, 0, 0)
        self.assertIn("--diff-filter=ACMRTU", out["listing"])
        self.assertEqual(out["skipped"], 0)

    def test_r2_sw7_worktree_scan_gives_the_fallback_a_deadline(self):
        source = (HOOKS / "worktree-scan.mjs").read_text(encoding="utf-8")
        self.assertTrue("deadline:" in source, "worktree-scan passes no deadline to boundedDiff")



# ---------------------------------------------------------------------------------------------
# Round 3 (second-pass review): R3-SW-1 .. R3-SW-3.
# ---------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None, "node not available")
class TestR3(unittest.TestCase):
    def test_r3_sw1_dollar_and_percent_passphrases_are_masked_in_json(self):
        # The `_` stand-in for blanks turned `$uper Secret …` into a `$IDENT` template, read as a placeholder.
        for value in ("$uper Secret Holiday " + rnd(4, string.digits), "%Secret Holiday " + rnd(6) + "%"):
            record = {"user": "app"}
            record["pass" + "word"] = value
            for flags, text in ((("--json",), json.dumps(record)), ((), json.dumps(record) + "\n")):
                with self.subTest(value=value[:6], flags=flags):
                    code, out, err = _redact_raw(text, *flags)
                    self.assertEqual(code, 0, err[:300])
                    self.assertFalse(value in out, "a passphrase under a password key survived")
                    self.assertEqual(json.loads(out.strip())["user"], "app")

    def test_r3_sw1_placeholders_under_a_password_key_stay(self):
        for value in ("$DB_PASSWORD", "${DB_PASSWORD}", "<your-password>", "%DB_PASSWORD%", "your password here"):
            record = {"pass" + "word": value}
            code, out, err = _redact_raw(json.dumps(record), "--json")
            with self.subTest(value=value):
                self.assertEqual(code, 0, err[:300])
                self.assertEqual(json.loads(out), record)

    def test_r3_sw1_numbers_keep_their_text_when_a_line_is_rewritten(self):
        token = gh_token()
        line = '{"note": "' + token + '", "x": 0.0000001, "big": 12345678901234567890}'
        code, out, err = _redact_raw(line + "\n")
        self.assertEqual(code, 0, err[:300])
        self.assertFalse(token in out)
        self.assertIn('"x":0.0000001', out)
        self.assertIn('"big":12345678901234567890', out)
        # The raw scan masked something, so the rewritten line is redacted as text as well; the masks
        # already in it read as placeholders, so the line stays valid JSON.
        value = rnd(24)
        line = '{"note": "' + token + '", "note": "ok", "api_' + 'token": "' + value + '"}'
        code, out, err = _redact_raw(line + "\n")
        self.assertEqual(code, 0, err[:300])
        self.assertFalse(token in out or value in out)
        json.loads(out)

    def test_r3_sw2_real_key_inside_a_degenerate_span_is_found(self):
        body = rnd(40)
        texts = [
            "OPENAI_API_KEY=" + "sk" + "-proj-" + "a" * 300 + "-" + "sk" + "-proj-" + body,
            "k " + "sk" + "-proj-" + "a" * 300 + "-AK" + "IA" + "A" * 16 + "sk" + "-proj-" + body,
            "t " + "gl" + "pat-" + "x" * 300 + "-" + "gl" + "pat-" + body,
        ]
        for text, got in zip(texts, node_scan(texts)):
            with self.subTest(text=text[:12]):
                self.assertTrue(got["high"], "a real key inside a degenerate span was not reported")
                self.assertFalse(body in got["red"], "a real key inside a degenerate span survived redaction")
                self.assertFalse(body in mask.mask_text(text))
                self.assertEqual(mask.redact_labelled(text, mask.HIGH), got["red"])
        control = "OPENAI=" + "sk" + "-proj-" + "a" * 300
        self.assertEqual(node_scan([control])[0]["high"], [])

    def test_r3_sw3_jwt_after_a_bare_dash_or_a_long_word_chain_is_found(self):
        jwt = "ey" + "J" + rnd(20, B64U) + ".eyJ" + rnd(30, B64U) + "." + rnd(43, B64U)
        texts = ["arg -" + jwt, "x --" + jwt, "-".join("abcdefghij") + "-" + jwt, "w" * 70 + "-" + jwt,
                 "_" + jwt, "Cookie: session-" + jwt]
        for text, got in zip(texts, node_scan(texts)):
            with self.subTest(text=text[:12]):
                self.assertIn("jwt", got["high"])
                self.assertFalse(jwt in got["red"])
                self.assertFalse(jwt in mask.mask_text(text))
                self.assertEqual(mask.redact_labelled(text, mask.HIGH), got["red"])

    def test_r3_new_shapes_stay_linear(self):
        script = (
            "import(require('node:url').pathToFileURL(process.argv[1]).href).then(m=>{const n=1<<20;const shapes={"
            "'dash-eyJ':'-eyJabcdefgh'.repeat(n/12),'dashes-eyJ':'--eyJabcde'.repeat(n/9),"
            "'words-eyJ':('ab-'.repeat(12)+'eyJabcdefgh').repeat(n/47),"
            "'embedded-proj':'sk-proj-'+('a'.repeat(20)+'-sk-proj-').repeat(n/29),"
            "'embedded-glpat':'glpat-'+('x'.repeat(20)+'-glpat-').repeat(n/27)};const out={};"
            "for(const[k,s]of Object.entries(shapes)){const t0=process.hrtime.bigint();m.scanLines(s,m.BROAD);"
            "m.redactSecrets(s,m.BROAD);out[k]=Number(process.hrtime.bigint()-t0)/1e6;}"
            "process.stdout.write(JSON.stringify(out));})"
        )
        proc = subprocess.run([NODE, "-e", script, str(PATTERNS)], capture_output=True, text=True,
                              encoding="utf-8", timeout=900)
        self.assertEqual(proc.returncode, 0, proc.stderr[:400])
        for shape, ms in json.loads(proc.stdout).items():
            if ms >= 4000:
                self.fail("%s at 1 MB took %.0f ms" % (shape, ms))
        size = 1 << 20
        for shape, text in {"dash-eyJ": "-eyJabcdefgh" * (size // 12), "dashes-eyJ": "--eyJabcde" * (size // 9),
                            "embedded-proj": "sk" + "-proj-" + ("a" * 20 + "-sk-proj-") * (size // 29)}.items():
            started = time.perf_counter()
            mask.mask_text(text)
            elapsed = time.perf_counter() - started
            if elapsed >= 12.0:
                self.fail("python %s at 1 MB took %.1f s" % (shape, elapsed))


if __name__ == "__main__":
    unittest.main()
