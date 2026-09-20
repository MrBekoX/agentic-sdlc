"""RED regression coverage for the guard bypasses confirmed by the 2026-08-22 adversarial
multi-lens security review of the secret/commit/branch guards.

Every case here was verified BY EXECUTION before any fix: a high-confidence, structurally
valid secret reaches its sink (a commit, or a file on disk) while the guard reports success.
These are fail-OPEN paths, not style issues.

No literal secret-shaped string appears in this file: every token is CONSTRUCTED at runtime
from synthetic parts.

Findings covered (severity as assessed against the guards' own threat model):
  F1  codex-write-signal.extractLiteral truncates a multi-token echo/printf payload; the guard
      scans the empty string and still reports parsed:true, while the shell writes the full
      payload including the secret.                                              (critical)
  F2  scan-commit / branch-guard gate their whole logic on the literal substring commit|push
      in the raw command, so a git alias (git config alias.ci 'commit -a'; git ci) disarms
      both guards entirely.                                                          (high)
  F3  scan-commit never scans the commit MESSAGE, so a secret passed via -m is written to
      permanent git history unscanned.                                               (high)
  F4  secret-patterns.looksPlaceholder is applied to the WHOLE match for the nine HIGH
      patterns that carry no valueGroup, so a vendor-shaped token that happens to contain
      'xxxx' / 'example' / '<' is discarded as a placeholder.                        (high)
  F5  scan-commit SECRET_FILENAME misses derived credential filenames (id_rsa.bak).  (medium)
  F6  Word-boundary-anchored fixed-length token patterns miss a token that is adjacent to
      another word character.                                                        (medium)

Each class also asserts CONTROL cases: a clean input must stay allowed, and a plain secret
must stay blocked. A fix that simply blocks everything fails these.
"""
import json
import shutil
import subprocess
import time
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
GIT = shutil.which("git")

# --- Synthetic tokens, assembled so no secret-shaped literal exists in this source. ---
# Every token here is NON-DEGENERATE (no single character dominates it), because a real vendor
# token never is. A token built from one repeated character is a documentation placeholder, and
# suppressing THOSE is legitimate — that case is asserted separately below.
_A = "a1B2"
_R16 = "4eC39HqLyjWDarjt"                       # 16 mixed-case/digit chars, no dominant character
GH_CLEAN = "ghp_" + _A * 9                      # ghp_ + 36
GH_XXXX = "ghp_" + "xxxx" + _A * 8              # ghp_ + 36, carries an xxxx run but is otherwise real
AWS_CLEAN = "AKIA" + "IOSFODNN7EXAMPL2"         # AKIA + 16 (not the AWS doc sample: trailing 2)
AWS_XXXX = "AKIA" + "XXXX" + "IOSFODNN7EXA"     # AKIA + 16, uppercase run, rest realistic
STRIPE_CLEAN = "sk_" + "live_" + _R16
STRIPE_XXXX = "sk_" + "test_" + "xxxx" + _R16
OPENAI_XXXX = "sk-" + "xxxx" + "T3BlbkFJabc123XYZ789"
GOOGLE_CLEAN = "AIza" + _A * 8 + "abc"          # AIza + 35

# Genuine documentation placeholders: a single repeated run. These MUST stay suppressed, or every
# README that shows a token shape starts blocking commits.
GH_PLACEHOLDER = "ghp_" + "x" * 36
AWS_PLACEHOLDER = "AKIA" + "X" * 16

HEREDOC_WRITE = "cat <<'XEOFX' > f\n{}\nXEOFX"


def _node_json(module_expr, stdin_text):
    """Run a tiny node program that imports a hook module and prints JSON."""
    src = (
        "let c='';process.stdin.setEncoding('utf8');"
        "process.stdin.on('data',d=>c+=d).on('end',()=>"
        + module_expr +
        ".catch(e=>{process.stderr.write(String(e&&e.message||e));process.exit(3)}))"
    )
    proc = subprocess.run(
        [NODE, "-e", src], input=stdin_text,
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, "node errored: " + proc.stderr
    return json.loads(proc.stdout)


def scan_high(text):
    """secret-patterns.scanLines(text, HIGH) -> list of findings."""
    return _node_json(
        "import('./hooks/secret-patterns.mjs')"
        ".then(m=>process.stdout.write(JSON.stringify(m.scanLines(c,m.HIGH))))",
        text,
    )


def scan_broad(text):
    """secret-patterns.scanLines(text, BROAD) -> list of findings."""
    return _node_json(
        "import('./hooks/secret-patterns.mjs')"
        ".then(m=>process.stdout.write(JSON.stringify(m.scanLines(c,m.BROAD))))",
        text,
    )


@unittest.skipIf(NODE is None, "node not available")
class TestPlaceholderFilterOnVendorTokens(unittest.TestCase):
    """F4 - the placeholder heuristic must not suppress a structurally valid vendor token.

    looksPlaceholder exists to skip user-authored right-hand-side values like
    `password=<your-password>` (agentic-sdlc:allow-secret). Nine of the eleven HIGH patterns
    have no valueGroup, so the
    value it inspects is the ENTIRE matched token - one that already passed a strict,
    vendor-published shape test. A token is not a placeholder because of the characters
    inside it.
    """

    def test_vendor_token_with_placeholder_run_is_still_detected(self):
        cases = {
            "github-xxxx": "TOKEN = " + GH_XXXX,
            "aws-XXXX": "KEY = " + AWS_XXXX,
            "stripe-xxxx": "STRIPE = " + STRIPE_XXXX,
            "openai-xxxx": "OPENAI = " + OPENAI_XXXX,
        }
        for label, line in cases.items():
            with self.subTest(case=label):
                self.assertTrue(
                    scan_high(line),
                    label + ": vendor-shaped token suppressed as a placeholder (fail-open)",
                )

    def test_captured_value_with_placeholder_word_is_still_detected(self):
        # password-literal and json-credential DO use a valueGroup, so the heuristic legitimately
        # applies - but only to obvious template text, never to a value that merely CONTAINS a
        # placeholder-ish word next to real entropy.
        cases = {
            "password-example": "password=MyRealSecret" + "Example" + "8412",  # agentic-sdlc:allow-secret
            "json-cred-angle": '"api_secret": "' + "q7" + "<" + "Wm4" + _A * 4 + '"',
        }
        for label, line in cases.items():
            with self.subTest(case=label):
                self.assertTrue(scan_high(line), label + ": real value suppressed (fail-open)")

    def test_true_placeholders_stay_suppressed(self):
        # CONTROL: the heuristic must keep working where it belongs, or the fix is just
        # "delete the filter" and every template file becomes a false positive.
        for line in [
            "password=<your-password-here>",
            "password=${DB_PASSWORD}",
            "password=CHANGE_ME",
            '"client_secret": "your-client-secret-goes-here"',
            "password=process.env.DB_PASS",
        ]:
            with self.subTest(line=line):
                self.assertEqual(scan_high(line), [], "false positive on template: " + line)

    def test_clean_prose_is_not_flagged(self):
        # CONTROL: no finding on ordinary text.
        self.assertEqual(scan_high("just a normal line of documentation about passwords"), [])

    def test_degenerate_documentation_tokens_stay_suppressed(self):
        # CONTROL, and the reason the keyword filter existed at all: a token that is one repeated
        # run is a doc placeholder, not a credential. Removing the keyword rule must not turn every
        # README token shape into a blocked commit.
        cases = {
            "github-all-x": "TOKEN = " + GH_PLACEHOLDER,
            "aws-all-X": "KEY = " + AWS_PLACEHOLDER,
        }
        for label, line in cases.items():
            with self.subTest(case=label):
                self.assertEqual(scan_high(line), [], label + ": doc placeholder now blocks commits")

    def test_published_doc_samples_stay_suppressed(self):
        # CONTROL: the canonical vendor documentation keys appear in countless READMEs. They are
        # suppressed by an EXACT-value allowlist, which cannot suppress a class the way the old
        # substring rule did.
        for label, line in {
            "aws-docs": "KEY = " + "AKIA" + "IOSFODNN7EXAMPLE",
            "google-docs": "KEY = " + "AIzaSyDaGmWKa4JsXZ-HjGw7ISLn_3namBGewQe",
        }.items():
            with self.subTest(case=label):
                self.assertEqual(scan_high(line), [], label + ": published doc sample blocks commits")


@unittest.skipIf(NODE is None, "node not available")
class TestTokenBoundaryAnchoring(unittest.TestCase):
    """F6 - a fixed-length token pattern closed with a word boundary is defeated by one
    adjacent word character. Open-ended patterns (stripe {16,}) are unaffected, which is
    exactly why this is a pattern-construction defect and not a detection-strategy one."""

    def test_token_adjacent_to_word_character_is_still_detected(self):
        # The two realistic shapes. `_` is a \w character, so a leading `\b` never fires on an
        # env-var-prefixed token; and a trailing `\b` after a FIXED length drops the token as soon
        # as one more word character follows.
        cases = {
            "github-underscore-prefix": "MYAPP_" + GH_CLEAN,
            "stripe-underscore-prefix": "STRIPE_" + STRIPE_CLEAN,
            "google-underscore-prefix": "GOOGLE_" + GOOGLE_CLEAN,
            "github-trailing": "TOKEN=" + GH_CLEAN + "X",
            "aws-trailing": "KEY=" + AWS_CLEAN + "C",
            "google-trailing": "KEY=" + GOOGLE_CLEAN + "9",
        }
        for label, line in cases.items():
            with self.subTest(case=label):
                self.assertTrue(scan_high(line), label + ": boundary anchor caused a miss")

    def test_prefix_inside_a_word_is_not_flagged(self):
        # CONTROL for dropping the anchors: `sk-` must not match inside an ordinary word, or every
        # `task-<20 chars>` identifier becomes a blocked "openai-key".
        for line in [
            "const task-abcdefghij0123456789 = 1",
            "risk-assessment-report-2026-08-22-final",
            "https://example.com/disk-usage-abcdefghij0123",
        ]:
            with self.subTest(line=line):
                self.assertEqual(scan_high(line), [], "false positive inside a word: " + line)

    def test_plain_tokens_remain_detected(self):
        # CONTROL: the anchoring fix must not lose the ordinary case.
        cases = {
            "github": "TOKEN=" + GH_CLEAN,
            "aws": "KEY=" + AWS_CLEAN,
            "google": "KEY=" + GOOGLE_CLEAN,
            "stripe": "S=" + STRIPE_CLEAN,
        }
        for label, line in cases.items():
            with self.subTest(case=label):
                self.assertTrue(scan_high(line), label + ": regression on the plain case")


@unittest.skipIf(NODE is None, "node not available")
class TestCodexWriteLiteralTruncation(unittest.TestCase):
    """F1 - extractLiteral returns only the first quoted or bare token of an echo/printf
    payload and silently discards the rest, while the shell writes all of it.

    Verified before the fix:
        echo "" <token> > notes.txt   ->  addedContent='', targets=['notes.txt'], parsed=true
    and the shell really does write the token to notes.txt.
    """

    HOOK = REPO / "hooks" / "scan-write-codex.mjs"

    def _parse(self, command, tool_name="Bash"):
        return _node_json(
            "import('./hooks/codex-write-signal.mjs')"
            ".then(m=>process.stdout.write(JSON.stringify("
            "m.extractWrittenContent(" + json.dumps(tool_name) + ",c))))",
            command,
        )

    def _run_hook(self, command, tool_name="Bash"):
        payload = {
            "tool_name": tool_name, "hook_event_name": "PreToolUse",
            "tool_input": {"command": command}, "cwd": "/repo",
            "session_id": "s", "transcript_path": "/x",
        }
        proc = subprocess.run(
            [NODE, str(self.HOOK)], input=json.dumps(payload),
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def _assert_denied(self, command):
        out = self._run_hook(command)
        self.assertEqual(
            out.get("hookSpecificOutput", {}).get("permissionDecision"), "deny",
            "write not denied, secret reaches disk: " + repr(command[:60]) + " -> " + repr(out),
        )
        self.assertNotIn(GH_CLEAN, json.dumps(out), "deny reason must mask the secret")

    def test_multi_token_payload_write_is_denied(self):
        cases = {
            "empty-quote-prefix": 'echo "" ' + GH_CLEAN + " > notes.txt",
            "empty-single-quote-prefix": "echo '' " + GH_CLEAN + " > notes.txt",
            "short-bareword-prefix": "echo x " + GH_CLEAN + " > notes.txt",
            "trailing-extra-token": "echo " + GH_CLEAN + " extra > notes.txt",
            "two-quoted-tokens": 'echo "a" "' + GH_CLEAN + '" > notes.txt',
            "printf-multi-arg": "printf '%s' " + GH_CLEAN + " > notes.txt",
            "append-form": 'echo "" ' + GH_CLEAN + " >> notes.txt",
        }
        for label, cmd in cases.items():
            with self.subTest(case=label):
                self._assert_denied(cmd)

    def test_parser_never_claims_parsed_while_dropping_payload(self):
        # The honest-coverage contract: if the parser cannot account for the whole payload of a
        # recognized write, it must not both (a) return content missing that payload and
        # (b) report parsed=true. Silent under-reporting is what made F1 exploitable.
        cases = {
            "empty-quote-prefix": 'echo "" ' + GH_CLEAN + " > notes.txt",
            "short-bareword-prefix": "echo x " + GH_CLEAN + " > notes.txt",
            "trailing-extra-token": "echo " + GH_CLEAN + " extra > notes.txt",
        }
        for label, cmd in cases.items():
            with self.subTest(case=label):
                res = self._parse(cmd)
                covered = GH_CLEAN in (res.get("addedContent") or "")
                self.assertTrue(
                    covered or res.get("parsed") is False,
                    label + ": payload dropped AND parsed=true -> silent under-report: " + repr(res),
                )

    def test_single_literal_forms_still_denied(self):
        # CONTROL: the forms that already worked must keep working.
        self._assert_denied("printf '" + GH_CLEAN + "' > f")
        self._assert_denied("echo '" + GH_CLEAN + "' >> f")
        self._assert_denied(HEREDOC_WRITE.format(GH_CLEAN))

    def test_clean_multi_token_write_is_allowed(self):
        # CONTROL: over-approximating the payload must not block ordinary multi-token writes.
        for cmd in [
            'echo "" hello world > notes.txt',
            "echo build ok > status.txt",
            "printf '%s' done > status.txt",
        ]:
            with self.subTest(cmd=cmd):
                self.assertEqual(self._run_hook(cmd), {}, "false block on clean write: " + cmd)

    def test_expansion_dependent_write_still_allowed(self):
        # CONTROL: an expansion-only payload carries no literal secret and must not be blocked.
        for cmd in ["printf '%s' \"$TOKEN\" > f", "echo $TOKEN > f"]:
            with self.subTest(cmd=cmd):
                self.assertEqual(self._run_hook(cmd), {})


@unittest.skipIf(NODE is None or GIT is None, "node or git not available")
class TestGitAliasGuardBypass(unittest.TestCase):
    """F2 - both guards gate on the literal substring commit|push in the raw command string.
    A git alias performs a real commit while that substring is absent, so the entire guard is
    skipped. Setting the alias (git config alias.ci ...) matches neither guard either."""

    SCAN = REPO / "hooks" / "scan-commit.mjs"
    BRANCH = REPO / "hooks" / "branch-guard.mjs"

    def _repo_with_staged_secret(self, td):
        subprocess.run(["git", "init", "-b", "main"], cwd=td, check=True, capture_output=True)
        subprocess.run(["git", "config", "alias.ci", "commit -a"], cwd=td, check=True, capture_output=True)
        subprocess.run(["git", "config", "alias.publish", "push origin main"], cwd=td, check=True, capture_output=True)
        p = Path(td) / "config.txt"
        p.write_text("TOKEN = " + GH_CLEAN + "\n", encoding="utf-8")
        subprocess.run(["git", "add", "--", "config.txt"], cwd=td, check=True, capture_output=True)

    def _run(self, hook, command, cwd):
        proc = subprocess.run(
            [NODE, str(hook)], cwd=cwd,
            input=json.dumps({"tool_input": {"command": command}}),
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def test_aliased_commit_is_still_scanned(self):
        with tempfile.TemporaryDirectory() as td:
            self._repo_with_staged_secret(td)
            cases = {
                "alias": "git ci -m wip",
                "alias-with-global-opt": "git --no-pager ci -m wip",
                "alias-with-C": "git -C . ci -m wip",
                "inline-config-alias": "git -c alias.zz=commit zz -m wip",
            }
            for label, cmd in cases.items():
                with self.subTest(case=label):
                    out = self._run(self.SCAN, cmd, td)
                    self.assertEqual(
                        out.get("hookSpecificOutput", {}).get("permissionDecision"), "deny",
                        label + ": staged secret committed unscanned via alias -> " + repr(out),
                    )

    def test_plain_commit_still_scanned(self):
        # CONTROL: the ordinary path must keep working.
        with tempfile.TemporaryDirectory() as td:
            self._repo_with_staged_secret(td)
            out = self._run(self.SCAN, "git commit -m wip", td)
            self.assertEqual(out.get("hookSpecificOutput", {}).get("permissionDecision"), "deny")

    def test_read_only_git_commands_stay_allowed(self):
        # CONTROL: resolving aliases must not turn every git call into a scan-and-deny.
        with tempfile.TemporaryDirectory() as td:
            self._repo_with_staged_secret(td)
            for cmd in ["git status", "git log --oneline", "git diff --cached", "git branch -a"]:
                with self.subTest(cmd=cmd):
                    self.assertEqual(self._run(self.SCAN, cmd, td), {}, "false block: " + cmd)

    def test_alias_shadowing_a_builtin_is_ignored_like_git_ignores_it(self):
        # CONTROL: git does NOT honour an alias that hides an existing command - verified live,
        # `alias.status = "commit -a"` still runs status. A resolver that expanded it anyway would
        # DENY a read-only command whenever a secret happened to be staged.
        with tempfile.TemporaryDirectory() as td:
            self._repo_with_staged_secret(td)
            subprocess.run(["git", "config", "alias.status", "commit -a"],
                           cwd=td, check=True, capture_output=True)
            self.assertEqual(
                self._run(self.SCAN, "git status", td), {},
                "read-only `git status` denied because a shadowing alias was expanded",
            )

    def test_branch_guard_sees_aliased_commit_on_main(self):
        with tempfile.TemporaryDirectory() as td:
            self._repo_with_staged_secret(td)
            out = self._run(self.BRANCH, "git ci -m wip", td)
            self.assertTrue(
                out, "branch-guard silent on an aliased commit to main (guard fully skipped)",
            )


@unittest.skipIf(NODE is None or GIT is None, "node or git not available")
class TestCommitMessageScan(unittest.TestCase):
    """F3 - the commit MESSAGE is part of the commit and is persisted forever by git, but
    scan-commit builds its corpus only from the staged diff and the staged filenames."""

    HOOK = REPO / "hooks" / "scan-commit.mjs"

    def _run(self, command, td):
        proc = subprocess.run(
            [NODE, str(self.HOOK)], cwd=td,
            input=json.dumps({"tool_input": {"command": command}}),
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def _clean_repo(self, td):
        subprocess.run(["git", "init", "-b", "main"], cwd=td, check=True, capture_output=True)
        p = Path(td) / "readme.txt"
        p.write_text("nothing secret here\n", encoding="utf-8")
        subprocess.run(["git", "add", "--", "readme.txt"], cwd=td, check=True, capture_output=True)

    def test_secret_in_commit_message_is_denied(self):
        with tempfile.TemporaryDirectory() as td:
            self._clean_repo(td)
            cases = {
                "dash-m-double-quote": 'git commit -m "rotate ' + GH_CLEAN + '"',
                "dash-m-single-quote": "git commit -m 'rotate " + GH_CLEAN + "'",
                "dash-m-joined": 'git commit -m"' + GH_CLEAN + '"',
                "long-message-flag": 'git commit --message="' + GH_CLEAN + '"',
            }
            for label, cmd in cases.items():
                with self.subTest(case=label):
                    out = self._run(cmd, td)
                    self.assertEqual(
                        out.get("hookSpecificOutput", {}).get("permissionDecision"), "deny",
                        label + ": secret persisted into git history unscanned -> " + repr(out),
                    )

    def test_ordinary_message_allowed(self):
        # CONTROL: normal messages must not be blocked.
        with tempfile.TemporaryDirectory() as td:
            self._clean_repo(td)
            for cmd in [
                'git commit -m "fix: handle empty payload"',
                "git commit -m 'chore: bump version to 0.4.0'",
                'git commit -m "docs: explain the token refresh flow"',
            ]:
                with self.subTest(cmd=cmd):
                    self.assertEqual(self._run(cmd, td), {}, "false block: " + cmd)


@unittest.skipIf(NODE is None or GIT is None, "node or git not available")
class TestDerivedCredentialFilenames(unittest.TestCase):
    """F5 - SECRET_FILENAME anchors the exact name, so a copy/backup of a credential file
    (id_rsa.bak) is committed without the filename check firing. A DER/binary key body has no
    header line for the content scan to catch, so the filename check is the only control."""

    HOOK = REPO / "hooks" / "scan-commit.mjs"

    def _scan(self, name, content="binary-key-body-not-pem\n"):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", "-b", "main"], cwd=td, check=True, capture_output=True)
            p = Path(td) / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            subprocess.run(["git", "add", "--", name], cwd=td, check=True, capture_output=True)
            proc = subprocess.run(
                [NODE, str(self.HOOK)], cwd=td,
                input=json.dumps({"tool_input": {"command": "git commit -m test"}}),
                capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def test_derived_credential_filenames_are_caught(self):
        for name in ["id_rsa.bak", "id_rsa.backup", "id_ed25519.old", ".npmrc.old", "server.key.bak"]:
            with self.subTest(name=name):
                out = self._scan(name)
                self.assertEqual(
                    out.get("hookSpecificOutput", {}).get("permissionDecision"), "deny",
                    name + ": derived credential file committed unflagged -> " + repr(out),
                )

    def test_exact_credential_filenames_still_caught(self):
        # CONTROL: the original names must keep working.
        for name in ["id_rsa", "server.pem", ".npmrc", "cert.p12"]:
            with self.subTest(name=name):
                out = self._scan(name)
                self.assertEqual(out.get("hookSpecificOutput", {}).get("permissionDecision"), "deny")

    def test_ordinary_filenames_allowed(self):
        # CONTROL: broadening the pattern must not catch normal source files.
        for name in ["main.py", "keyboard.js", "monkey.txt", "notes.bak", "keys.md"]:
            with self.subTest(name=name):
                self.assertEqual(self._scan(name, "hello\n"), {}, "false block on " + name)


@unittest.skipIf(NODE is None or GIT is None, "node or git not available")
class TestFixResiduals(unittest.TestCase):
    """Second round. An adversarial re-review of the FIX found five defects the fix itself
    introduced or left behind; all five were reproduced by execution before being closed.

      R1  Both guards added a cheap `/\\bgit\\b/` pre-filter that runs BEFORE the quote-aware
          tokenizer, so `g'i't commit` exits early - the pre-filter defeats the very obfuscation
          handling the new resolver was written for.
      R2  UNREAD_WRITE recognizes `sed -i` but not GNU long-form `sed --in-place`, so that write
          still came back parsed:true (the exact CWE-636 shape the fix claimed to remove).
      R3  The commit-message scan tokenizes only the typed command, so a secret living inside the
          ALIAS definition (`alias.ci = "commit -a -m '<token>'"`) is never scanned.
      R4  Alias lookup and the git reads all use the hook process cwd, so `git -C ../other ci`
          resolves against the wrong repository and the guard skips a real commit.
      R5  SECRET_FILENAME was rebuilt with `(?:\\.[A-Za-z0-9]{1,8}|~)*$` - a repeated ambiguous
          group before an end anchor. Measured 459 ms / 1.16 s / 20.6 s at 8 / 10 / 12 groups:
          catastrophic backtracking introduced BY the fix, in a guard that runs on every commit.
    """

    SCAN = REPO / "hooks" / "scan-commit.mjs"

    def _run(self, command, cwd, hook=None):
        proc = subprocess.run(
            [NODE, str(hook or self.SCAN)], cwd=cwd,
            input=json.dumps({"tool_input": {"command": command}, "cwd": cwd}),
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def _decision(self, out):
        return out.get("hookSpecificOutput", {}).get("permissionDecision", "allow")

    def _repo(self, td, *, alias=None, staged_secret=True):
        subprocess.run(["git", "init", "-b", "main"], cwd=td, check=True, capture_output=True)
        if alias:
            subprocess.run(["git", "config", "alias." + alias[0], alias[1]],
                           cwd=td, check=True, capture_output=True)
        body = ("TOKEN = " + GH_CLEAN + "\n") if staged_secret else "clean\n"
        Path(td, "config.txt").write_text(body, encoding="utf-8")
        subprocess.run(["git", "add", "--", "config.txt"], cwd=td, check=True, capture_output=True)

    def test_r1_quote_obfuscated_git_is_still_scanned(self):
        with tempfile.TemporaryDirectory() as td:
            self._repo(td)
            for label, cmd in {
                "split-quotes": "g'i't commit -m wip",
                "quoted-name": '"git" commit -m wip',
                "backslash": "g\\it commit -m wip",
            }.items():
                with self.subTest(case=label):
                    self.assertEqual(
                        self._decision(self._run(cmd, td)), "deny",
                        label + ": cheap pre-filter skipped the quote-aware resolver",
                    )

    def test_r2_sed_long_option_is_not_claimed_as_parsed(self):
        res = _node_json(
            "import('./hooks/codex-write-signal.mjs')"
            ".then(m=>process.stdout.write(JSON.stringify(m.extractWrittenContent('Bash',c))))",
            "sed --in-place 's/x/y/' f.env",
        )
        self.assertFalse(
            res.get("parsed"),
            "sed --in-place is an unread write; parsed must not claim full coverage: " + repr(res),
        )

    def test_r3_secret_inside_the_alias_message_is_scanned(self):
        with tempfile.TemporaryDirectory() as td:
            self._repo(td, alias=("ci", "commit -a -m '" + GH_CLEAN + "'"), staged_secret=False)
            self.assertEqual(
                self._decision(self._run("git ci", td)), "deny",
                "secret in the alias's own -m reached history unscanned",
            )

    def test_r4_dash_C_target_repo_is_resolved(self):
        with tempfile.TemporaryDirectory() as base:
            other = Path(base, "other"); other.mkdir()
            here = Path(base, "here"); here.mkdir()
            self._repo(str(other), alias=("ci", "commit -a"))
            self._repo(str(here), staged_secret=False)      # no alias, no secret here
            self.assertEqual(
                self._decision(self._run("git -C ../other ci -m wip", str(here))), "deny",
                "-C target repo not resolved: alias + staged secret in the OTHER repo went unscanned",
            )

    def test_r5_derived_filename_match_is_linear(self):
        import time
        # 12 groups measured 20.6 s with the backtracking regex; a linear matcher is ~0 ms.
        name = "id_rsa" + ".a" * 24 + "!"
        res = _node_json(
            "import('./hooks/scan-commit-names.mjs')"
            ".then(m=>process.stdout.write(JSON.stringify(m.isCredentialFilename(c))))",
            name,
        )
        self.assertIsInstance(res, bool)

    def test_r5_timing_stays_flat(self):
        import time
        t = time.time()
        for n in (12, 18, 24):
            _node_json(
                "import('./hooks/scan-commit-names.mjs')"
                ".then(m=>process.stdout.write(JSON.stringify(m.isCredentialFilename(c))))",
                "id_rsa" + ".a" * n + "!",
            )
        self.assertLess(time.time() - t, 10.0, "derived-suffix matching is not linear")


@unittest.skipIf(NODE is None or GIT is None, "node or git not available")
class TestRoundThreeResiduals(unittest.TestCase):
    """Third adversarial round against the round-2 result. All three reproduced by execution.

      S1  `commit -a/--all` widening still regex-tested the RAW typed command, so an alias that
          supplies `-a` (`alias.ci = "commit -a -m wip"`) swept an unstaged tracked secret into
          the commit while only the STAGED diff was scanned. Same class as the message bug: the
          resolver's expansion was available and not consulted.
      S2  The heredoc reader matched `<<EOF` but not the tab-stripping `<<-EOF` form, so that
          write was neither read nor marked unread - `parsed:true` with empty content again.
      S3  `git -C a -C b` is CUMULATIVE in git (verified: it resolves to a/b), but only dirs[0]
          was used, pointing every git read at a strict ancestor of the real target repo.
    """

    SCAN = REPO / "hooks" / "scan-commit.mjs"

    def _run(self, command, cwd):
        proc = subprocess.run(
            [NODE, str(self.SCAN)], cwd=cwd,
            input=json.dumps({"tool_input": {"command": command}, "cwd": cwd}),
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout) if proc.stdout.strip() else {}
        return out.get("hookSpecificOutput", {}).get("permissionDecision", "allow")

    def test_s1_alias_supplied_dash_a_scans_unstaged_tracked_changes(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", "-b", "main"], cwd=td, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "t@e.st"], cwd=td, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=td, check=True, capture_output=True)
            subprocess.run(["git", "config", "alias.ci", "commit -a -m wip"], cwd=td, check=True, capture_output=True)
            f = Path(td, "config.txt")
            f.write_text("clean\n", encoding="utf-8")
            subprocess.run(["git", "add", "--", "config.txt"], cwd=td, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "base"], cwd=td, check=True, capture_output=True)
            # Tracked, MODIFIED, deliberately NOT staged - only `-a` sweeps it in.
            f.write_text("TOKEN = " + GH_CLEAN + "\n", encoding="utf-8")
            self.assertEqual(
                self._run("git ci", td), "deny",
                "alias-supplied -a swept an unstaged tracked secret in; only the staged diff was scanned",
            )

    def test_s2_tab_stripping_heredoc_is_read_or_declared_unread(self):
        res = _node_json(
            "import('./hooks/codex-write-signal.mjs')"
            ".then(m=>process.stdout.write(JSON.stringify(m.extractWrittenContent('Bash',c))))",
            "cat <<-EOF > s.txt\n" + GH_CLEAN + "\nEOF",
        )
        covered = GH_CLEAN in (res.get("addedContent") or "")
        self.assertTrue(
            covered or res.get("parsed") is False,
            "<<- heredoc neither read nor marked unread: " + repr(res),
        )

    def test_s2_tab_stripping_heredoc_write_is_denied(self):
        payload = {
            "tool_name": "Bash", "hook_event_name": "PreToolUse",
            "tool_input": {"command": "cat <<-EOF > s.txt\n" + GH_CLEAN + "\nEOF"},
            "cwd": "/repo", "session_id": "s", "transcript_path": "/x",
        }
        proc = subprocess.run(
            [NODE, str(REPO / "hooks" / "scan-write-codex.mjs")], input=json.dumps(payload),
            capture_output=True, text=True, encoding="utf-8",
        )
        out = json.loads(proc.stdout) if proc.stdout.strip() else {}
        self.assertEqual(
            out.get("hookSpecificOutput", {}).get("permissionDecision"), "deny",
            "secret written through a <<- heredoc reached disk",
        )

    def test_s3_repeated_dash_C_is_cumulative(self):
        with tempfile.TemporaryDirectory() as base:
            deep = Path(base, "a", "b")
            deep.mkdir(parents=True)
            subprocess.run(["git", "init", "-b", "main"], cwd=deep, check=True, capture_output=True)
            subprocess.run(["git", "config", "alias.ci", "commit -a"], cwd=deep, check=True, capture_output=True)
            Path(deep, "config.txt").write_text("TOKEN = " + GH_CLEAN + "\n", encoding="utf-8")
            subprocess.run(["git", "add", "--", "config.txt"], cwd=deep, check=True, capture_output=True)
            self.assertEqual(
                self._run("git -C a -C b ci -m wip", base), "deny",
                "repeated -C resolved to the ancestor, so the real target repo was never scanned",
            )


@unittest.skipIf(NODE is None or GIT is None, "node or git not available")
class TestRoundFourResiduals(unittest.TestCase):
    """Fourth adversarial round. All three reproduced by execution.

      T1  A wrapping subshell `( ... )` or brace group `{ ...; }` made the whole statement
          invisible: the first token is `(git`, whose basename is not `git`, so the resolver
          returned nothing and BOTH guards exited. destructive-command-guard.mjs has stripped
          these wrappers for a long time; the new resolver did not.
      T2  `-C` values were collected into ONE array across every statement, so an unrelated
          `git -C /tmp status` earlier on the line redirected the COMMIT's diff read to /tmp.
      T3  `id_rsa.pub` was treated as a credential. A public key is the half you are meant to
          commit; denying it is a false block that pushes people to switch the guard off.
    """

    SCAN = REPO / "hooks" / "scan-commit.mjs"
    BRANCH = REPO / "hooks" / "branch-guard.mjs"

    def _run(self, command, cwd, hook=None):
        proc = subprocess.run(
            [NODE, str(hook or self.SCAN)], cwd=cwd,
            input=json.dumps({"tool_input": {"command": command}, "cwd": cwd}),
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def _decision(self, out):
        return out.get("hookSpecificOutput", {}).get("permissionDecision", "allow")

    def _repo(self, td):
        subprocess.run(["git", "init", "-b", "main"], cwd=td, check=True, capture_output=True)
        Path(td, "config.txt").write_text("TOKEN = " + GH_CLEAN + "\n", encoding="utf-8")
        subprocess.run(["git", "add", "--", "config.txt"], cwd=td, check=True, capture_output=True)

    def test_t1_group_wrapped_commit_is_still_scanned(self):
        with tempfile.TemporaryDirectory() as td:
            self._repo(td)
            for label, cmd in {
                "subshell": "(git commit -am x)",
                "brace-group": "{ git commit -am x; }",
                "nested-subshell": "((git commit -am x))",
                "subshell-with-cd": "(cd . && git commit -am x)",
            }.items():
                with self.subTest(case=label):
                    self.assertEqual(
                        self._decision(self._run(cmd, td)), "deny",
                        label + ": group wrapper made the commit invisible to the resolver",
                    )

    def test_t1_group_wrapped_push_reaches_branch_guard(self):
        with tempfile.TemporaryDirectory() as td:
            self._repo(td)
            self.assertTrue(
                self._run("(git push --force origin main)", td, hook=self.BRANCH),
                "branch-guard silent on a group-wrapped force-push to main",
            )

    def test_t2_unrelated_dash_C_does_not_redirect_the_commit_scan(self):
        with tempfile.TemporaryDirectory() as td:
            self._repo(td)
            other = Path(td, "elsewhere"); other.mkdir()
            self.assertEqual(
                self._decision(self._run("git -C elsewhere status; git commit -am x", td)), "deny",
                "a -C from an unrelated statement redirected the commit's own diff read",
            )

    def test_t3_public_keys_are_not_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", "-b", "main"], cwd=td, check=True, capture_output=True)
            for name in ["id_rsa.pub", "id_ed25519.pub", "deploy.key.pub"]:
                Path(td, name).write_text("ssh-rsa AAAAB3NzaC1yc2E user@host\n", encoding="utf-8")
                subprocess.run(["git", "add", "--", name], cwd=td, check=True, capture_output=True)
            self.assertEqual(
                self._decision(self._run("git commit -m 'add public keys'", td)), "allow",
                "public keys are meant to be committed; denying them is a false block",
            )

    def test_t3_private_keys_are_still_blocked(self):
        # CONTROL: the .pub carve-out must not weaken the private-key check.
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", "-b", "main"], cwd=td, check=True, capture_output=True)
            Path(td, "id_rsa").write_text("binary-key-body\n", encoding="utf-8")
            subprocess.run(["git", "add", "--", "id_rsa"], cwd=td, check=True, capture_output=True)
            self.assertEqual(self._decision(self._run("git commit -m x", td)), "deny")


@unittest.skipIf(NODE is None or GIT is None, "node or git not available")
class TestRoundFiveResiduals(unittest.TestCase):
    """Fifth adversarial round. Two distinct defects (three lenses reported the first one).

      U1  A command line can carry more than one commit. `targetCwdFor` picked the FIRST matching
          call, so `git -C a commit ... && git -C b commit ...` scanned only `a` and let `b`'s
          staged secret through while reporting clean.
      U2  git bundles short options: `git commit -am"<msg>"` is `-a -m "<msg>"`. The message
          reader only recognized a literal `-m` prefix, so the token `-am<msg>` fell through and
          a secret pasted there was committed unscanned.
    """

    SCAN = REPO / "hooks" / "scan-commit.mjs"

    def _decision(self, command, cwd):
        proc = subprocess.run(
            [NODE, str(self.SCAN)], cwd=cwd,
            input=json.dumps({"tool_input": {"command": command}, "cwd": cwd}),
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout) if proc.stdout.strip() else {}
        return out.get("hookSpecificOutput", {}).get("permissionDecision", "allow")

    def _init(self, path, *, secret):
        subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
        body = ("TOKEN = " + GH_CLEAN + "\n") if secret else "clean\n"
        Path(path, "config.txt").write_text(body, encoding="utf-8")
        subprocess.run(["git", "add", "--", "config.txt"], cwd=path, check=True, capture_output=True)

    def test_u1_every_commit_target_repo_is_scanned(self):
        with tempfile.TemporaryDirectory() as base:
            a = Path(base, "repoA"); a.mkdir()
            b = Path(base, "repoB"); b.mkdir()
            self._init(str(a), secret=False)     # decoy: clean, and listed FIRST
            self._init(str(b), secret=True)      # the real one, carrying the secret
            self.assertEqual(
                self._decision("git -C repoA commit -m ok && git -C repoB commit -m ok2", base),
                "deny",
                "only the first commit's repo was scanned; the second one's secret went through",
            )

    def test_u1_single_repo_still_scanned(self):
        # CONTROL: the ordinary single-commit path must be unaffected.
        with tempfile.TemporaryDirectory() as td:
            self._init(td, secret=True)
            self.assertEqual(self._decision("git commit -m x", td), "deny")

    def test_u2_bundled_short_option_message_is_scanned(self):
        with tempfile.TemporaryDirectory() as td:
            self._init(td, secret=False)
            for label, cmd in {
                "attached -am": 'git commit -am"' + GH_CLEAN + '"',
                "attached -qam": 'git commit -qam"' + GH_CLEAN + '"',
                "separate -am": "git commit -am " + GH_CLEAN,
            }.items():
                with self.subTest(case=label):
                    self.assertEqual(
                        self._decision(cmd, td), "deny",
                        label + ": bundled short option hid the message from the scanner",
                    )

    def test_u2_ordinary_bundled_flags_not_treated_as_messages(self):
        # CONTROL: flags that carry no message must not swallow the next token as one.
        with tempfile.TemporaryDirectory() as td:
            self._init(td, secret=False)
            for cmd in ["git commit --amend --no-edit", "git commit -a -m 'ordinary message'"]:
                with self.subTest(cmd=cmd):
                    self.assertEqual(self._decision(cmd, td), "allow", "false block: " + cmd)


@unittest.skipIf(NODE is None or GIT is None, "node or git not available")
class TestRoundSixResidual(unittest.TestCase):
    """Sixth adversarial round: one finding, introduced by round five's multi-repo loop.

      V1  `-F <file>` was resolved by trying every commit repo in order and taking the first
          readable hit, so a clean `repoA/msg.txt` masked the secret in `repoB/msg.txt`. A message
          file belongs to the statement that names it, not to the command line.
    """

    SCAN = REPO / "hooks" / "scan-commit.mjs"

    def _decision(self, command, cwd):
        proc = subprocess.run(
            [NODE, str(self.SCAN)], cwd=cwd,
            input=json.dumps({"tool_input": {"command": command}, "cwd": str(cwd)}),
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout) if proc.stdout.strip() else {}
        return out.get("hookSpecificOutput", {}).get("permissionDecision", "allow")

    def _repo(self, base, name, message):
        d = Path(base, name)
        d.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=d, check=True, capture_output=True)
        Path(d, "r.txt").write_text("clean\n", encoding="utf-8")
        subprocess.run(["git", "add", "--", "r.txt"], cwd=d, check=True, capture_output=True)
        Path(d, "msg.txt").write_text(message, encoding="utf-8")

    def test_v1_message_file_is_read_from_its_own_repo(self):
        with tempfile.TemporaryDirectory() as base:
            self._repo(base, "repoA", "just a normal message\n")     # clean, listed FIRST
            self._repo(base, "repoB", "rotate " + GH_CLEAN + "\n")   # the one with the secret
            self.assertEqual(
                self._decision("git -C repoA commit -F msg.txt && git -C repoB commit -F msg.txt", base),
                "deny",
                "a same-named clean message file in an earlier repo masked the real one",
            )

    def test_v1_ordinary_message_file_still_allowed(self):
        # CONTROL: a clean -F message must not be blocked.
        with tempfile.TemporaryDirectory() as base:
            self._repo(base, "repoA", "chore: ordinary release notes\n")
            self.assertEqual(self._decision("git -C repoA commit -F msg.txt", base), "allow")


@unittest.skipIf(NODE is None or GIT is None, "node or git not available")
class TestRoundSevenResiduals(unittest.TestCase):
    r"""Seventh adversarial round. Four findings, all reproduced by execution.

      W1/W4  bash ANSI-C quoting `$'...'` is decoded by the SHELL before the command runs, so
             `git commit -m $'\x73\x6b\x2dlive...'` records `sk-live-...` in permanent history
             while the raw token carries no vendor-shaped text. Neither the message scan nor the
             write extractor decoded it, and the write extractor also returned parsed:true.
      W2     branch-guard was left on the singular resolver after scan-commit moved to the plural
             one, so only the first repo's branch was checked in a multi-repo command.
      W3     FALSE BLOCK: the `-a`/`--all` sweep test ran over raw statement text, so an ordinary
             `git commit -m "docs: describe -a flag behavior"` pulled the whole working tree in.
    """

    SCAN = REPO / "hooks" / "scan-commit.mjs"
    BRANCH = REPO / "hooks" / "branch-guard.mjs"
    BS = chr(92)   # a real backslash, built here so no shell/py escaping games change the input

    def _ansi_c(self, text):
        """The `$'...'` spelling of `text`, every character as a \\xHH escape."""
        return "$'" + "".join(self.BS + "x%02x" % ord(c) for c in text) + "'"

    def _run(self, command, cwd, hook=None):
        proc = subprocess.run(
            [NODE, str(hook or self.SCAN)], cwd=cwd,
            input=json.dumps({"tool_input": {"command": command}, "cwd": str(cwd)}),
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def _decision(self, out):
        return out.get("hookSpecificOutput", {}).get("permissionDecision", "allow")

    def _repo(self, path, *, branch="feature", staged="clean\n"):
        subprocess.run(["git", "init", "-b", branch], cwd=path, check=True, capture_output=True)
        Path(path, "r.txt").write_text(staged, encoding="utf-8")
        subprocess.run(["git", "add", "--", "r.txt"], cwd=path, check=True, capture_output=True)

    def test_w1_ansi_c_quoted_message_is_decoded_and_scanned(self):
        with tempfile.TemporaryDirectory() as td:
            self._repo(td)
            cmd = "git commit -m " + self._ansi_c(GH_CLEAN)
            self.assertEqual(
                self._decision(self._run(cmd, td)), "deny",
                "ANSI-C quoted message decoded by bash but not by the scanner",
            )

    def test_w4_ansi_c_quoted_write_is_decoded_and_denied(self):
        cmd = "echo " + self._ansi_c(GH_CLEAN) + " > out.txt"
        payload = {
            "tool_name": "Bash", "hook_event_name": "PreToolUse",
            "tool_input": {"command": cmd}, "cwd": "/repo",
        }
        proc = subprocess.run(
            [NODE, str(REPO / "hooks" / "scan-write-codex.mjs")], input=json.dumps(payload),
            capture_output=True, text=True, encoding="utf-8",
        )
        out = json.loads(proc.stdout) if proc.stdout.strip() else {}
        self.assertEqual(
            out.get("hookSpecificOutput", {}).get("permissionDecision"), "deny",
            "ANSI-C quoted payload decoded by bash but not by the write extractor",
        )

    def test_w2_branch_guard_checks_every_repo(self):
        with tempfile.TemporaryDirectory() as base:
            feat = Path(base, "featureRepo"); feat.mkdir()
            main = Path(base, "mainRepo"); main.mkdir()
            self._repo(str(feat), branch="feature")   # not protected, listed FIRST
            self._repo(str(main), branch="main")      # protected, listed SECOND
            out = self._run("git -C featureRepo commit -m a && git -C mainRepo commit -m b", base,
                            hook=self.BRANCH)
            self.assertTrue(
                out, "branch-guard checked only the first repo and missed the commit to main",
            )

    def test_w3_dash_a_inside_the_message_does_not_sweep(self):
        # FALSE BLOCK regression: an unstaged tracked file carrying a secret must NOT be pulled in
        # by a commit that never uses -a. The word "-a" appearing in the message is not a flag.
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", "-b", "main"], cwd=td, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "t@e.st"], cwd=td, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=td, check=True, capture_output=True)
            other = Path(td, "other.txt")
            other.write_text("clean\n", encoding="utf-8")
            Path(td, "staged.txt").write_text("clean\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=td, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "base"], cwd=td, check=True, capture_output=True)
            other.write_text("TOKEN = " + GH_CLEAN + "\n", encoding="utf-8")   # tracked, UNSTAGED
            self.assertEqual(
                self._decision(self._run('git commit -m "docs: describe -a flag behavior"', td)),
                "allow",
                "a literal '-a' in the message text pulled unstaged work into the scan",
            )

    def test_x1_ansi_c_encoded_command_name_reaches_the_resolver(self):
        # Round 8: the cheap pre-filter ran on the RAW command, before ANSI-C expansion, so
        # `$'\x67\x69\x74' commit` (which bash executes as `git commit`) exited before the resolver
        # ever ran. Third instance of "a pre-filter must be a strict superset of what it guards".
        with tempfile.TemporaryDirectory() as td:
            self._repo(td, branch="main", staged="TOKEN = " + GH_CLEAN + "\n")
            cmd = self._ansi_c("git") + " commit -am wip"
            self.assertEqual(
                self._decision(self._run(cmd, td)), "deny",
                "ANSI-C encoded command name skipped the pre-filter and disabled the guard",
            )

    def test_x1_non_git_commands_still_exit_cheaply(self):
        # CONTROL: widening the probe must not make every unrelated command do git work.
        with tempfile.TemporaryDirectory() as td:
            self._repo(td)
            for cmd in ["npm test", "python -m pytest", "ls -la"]:
                with self.subTest(cmd=cmd):
                    self.assertEqual(self._run(cmd, td), {}, "false trigger on: " + cmd)

    def test_w3_real_dash_a_still_sweeps(self):
        # CONTROL: an actual -a must still pull the unstaged tracked change in.
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", "-b", "main"], cwd=td, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "t@e.st"], cwd=td, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=td, check=True, capture_output=True)
            f = Path(td, "other.txt")
            f.write_text("clean\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=td, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "base"], cwd=td, check=True, capture_output=True)
            f.write_text("TOKEN = " + GH_CLEAN + "\n", encoding="utf-8")
            self.assertEqual(self._decision(self._run("git commit -am wip", td)), "deny")


@unittest.skipIf(NODE is None, "node not available")
class TestRoundNineResiduals(unittest.TestCase):
    r"""Ninth adversarial round. Two distinct defects, both introduced by earlier rounds' fixes.

      Y1  The `.pub` carve-out added in round four matched `pub` ANYWHERE in the dotted tail, so
          `secrets.pub.pem`, `config.pub.p12` and `id_rsa.pub.ppk` escaped the credential-filename
          check entirely — and those formats are usually binary, so the content scan is no backstop.
      Y2  POSIX `printf` decodes backslash escapes in its FORMAT string unconditionally (no -e
          needed), and `echo -e` does the same, so `printf '\163\153\137...' > f` writes
          `sk_live_...` while the extractor saw `163153137...` and reported parsed:true.
    """

    BS = chr(92)

    def _parse(self, command):
        return _node_json(
            "import('./hooks/codex-write-signal.mjs')"
            ".then(m=>process.stdout.write(JSON.stringify(m.extractWrittenContent('Bash',c))))",
            command,
        )

    def _names(self, name):
        return _node_json(
            "import('./hooks/scan-commit-names.mjs')"
            ".then(m=>process.stdout.write(JSON.stringify(m.isCredentialFilename(c))))",
            name,
        )

    def test_y1_pub_only_exempts_the_terminal_suffix(self):
        for name in ["secrets.pub.pem", "config.pub.p12", "id_rsa.pub.ppk", "keystore.pub.jks"]:
            with self.subTest(name=name):
                self.assertTrue(
                    self._names(name),
                    name + ": a mid-name `.pub.` disabled the credential-filename check",
                )

    def test_y1_real_public_keys_still_exempt(self):
        # CONTROL: the genuine public-key shape must stay allowed.
        for name in ["id_rsa.pub", "id_ed25519.pub", "deploy.key.pub"]:
            with self.subTest(name=name):
                self.assertFalse(self._names(name), name + ": false block on a public key")

    def test_y1_ordinary_and_credential_names_unchanged(self):
        for name, want in [("id_rsa", True), ("server.key", True), ("cert.p12", True),
                           ("notes.bak", False), ("keys.md", False), ("main.py", False)]:
            with self.subTest(name=name):
                self.assertEqual(self._names(name), want)

    def _escaped(self, text, style):
        if style == "octal":
            return "".join(self.BS + oct(ord(c))[2:].rjust(3, "0") for c in text)
        return "".join(self.BS + "x%02x" % ord(c) for c in text)

    def test_y2_printf_escape_sequences_are_decoded(self):
        for style in ("octal", "hex"):
            with self.subTest(style=style):
                cmd = "printf '" + self._escaped(GH_CLEAN, style) + "' > out.txt"
                res = self._parse(cmd)
                self.assertIn(
                    GH_CLEAN, res.get("addedContent") or "",
                    style + ": printf decodes these escapes itself; the guard did not",
                )

    def test_y2_escaped_write_is_denied_end_to_end(self):
        cmd = "printf '" + self._escaped(GH_CLEAN, "octal") + "' > out.txt"
        payload = {
            "tool_name": "Bash", "hook_event_name": "PreToolUse",
            "tool_input": {"command": cmd}, "cwd": "/repo",
        }
        proc = subprocess.run(
            [NODE, str(REPO / "hooks" / "scan-write-codex.mjs")], input=json.dumps(payload),
            capture_output=True, text=True, encoding="utf-8",
        )
        out = json.loads(proc.stdout) if proc.stdout.strip() else {}
        self.assertEqual(out.get("hookSpecificOutput", {}).get("permissionDecision"), "deny")

    def test_y2_clean_writes_still_allowed(self):
        # CONTROL: decoding must not invent findings in ordinary text.
        for cmd in ["printf 'just a note' > f", "printf 'path C:\\\\tmp\\\\x' > f",
                    "echo build ok > status.txt"]:
            with self.subTest(cmd=cmd):
                res = self._parse(cmd)
                self.assertNotIn("ghp_", res.get("addedContent") or "")


@unittest.skipIf(NODE is None, "node not available")
class TestRoundTenResiduals(unittest.TestCase):
    """Tenth adversarial round. Two distinct defects, both from the previous rounds' own fixes.

      Z1  Round nine narrowed the `.pub` carve-out to the TERMINAL suffix, which still let
          `cert.p12.pub` through: appending `.pub` to any credential container defeated the
          filename check, and those formats are binary so the content scan is no backstop.
      Z2  The printf/echo branch tested for `$` without knowing about quoting, so
          `echo 'password=p$ssw0rd...' > f` (agentic-sdlc:allow-secret) — a fully literal write
          extractor declares it covers — was skipped as expansion-dependent. The heredoc path
          one block above already checked its delimiter's quoting; this branch did not.
    """

    def _parse(self, command):
        return _node_json(
            "import('./hooks/codex-write-signal.mjs')"
            ".then(m=>process.stdout.write(JSON.stringify(m.extractWrittenContent('Bash',c))))",
            command,
        )

    def _names(self, name):
        return _node_json(
            "import('./hooks/scan-commit-names.mjs')"
            ".then(m=>process.stdout.write(JSON.stringify(m.isCredentialFilename(c))))",
            name,
        )

    def test_z1_pub_after_a_container_extension_is_still_flagged(self):
        for name in ["cert.p12.pub", "secrets.pfx.pub", "keystore.jks.pub", "key.ppk.pub"]:
            with self.subTest(name=name):
                self.assertTrue(
                    self._names(name),
                    name + ": appending .pub to a credential container defeated the check",
                )

    def test_z1_genuine_public_key_shapes_stay_exempt(self):
        # CONTROL: `.pub` next to a base name or a .key/.pem sibling is a real keypair half.
        for name in ["id_rsa.pub", "id_ed25519.pub", "deploy.key.pub", "server.pem.pub"]:
            with self.subTest(name=name):
                self.assertFalse(self._names(name), name + ": false block on a public key")

    def test_z2_single_quoted_dollar_is_literal_and_scanned(self):
        res = self._parse(
            "echo 'password=p$ssw0rd_SECRET_VALUE_1234567' > config.env")  # agentic-sdlc:allow-secret
        self.assertIn(
            "p$ssw0rd", res.get("addedContent") or "",
            "single-quoted $ is not an expansion; bash writes it literally: " + repr(res),
        )
        self.assertTrue(res.get("parsed"), "a fully literal write must be reported as accounted for")

    def test_z2_real_expansions_still_suppressed(self):
        # CONTROL: where bash really does expand, the content is unknown and must stay unscanned.
        for cmd in ['echo "$TOKEN" > f', "echo $TOKEN > f", 'printf "$(cat s)" > f',
                    'echo "${HOME}" > f']:
            with self.subTest(cmd=cmd):
                res = self._parse(cmd)
                self.assertFalse(res.get("parsed"), cmd + ": real expansion must clear parsed")
                self.assertEqual(res.get("addedContent"), "")


@unittest.skipIf(NODE is None, "node not available")
class TestInlineAllowlistMarker(unittest.TestCase):
    """An explicit, per-line escape hatch — the mechanism every mature scanner ships.

    Documenting a bypass requires writing the shape you are documenting, so this repo's own
    comments and lessons.md trip the scanner. Without an escape hatch the guard cries wolf on the
    files that explain it, and a guard that fires on ordinary work gets switched off.

    The rule the research settled on: suppression must be per-line and visible in review, never a
    pattern that silences a whole token class (detect-secrets' `pragma: allowlist secret`,
    gitleaks' `gitleaks:allow`). One marked line is auditable in a diff; a broadened regex is not.
    """

    def test_marked_line_is_skipped(self):
        line = "TOKEN = " + GH_CLEAN + "   # agentic-sdlc:allow-secret documented example"
        self.assertEqual(scan_high(line), [], "an explicitly marked line was still reported")

    def test_marker_only_affects_its_own_line(self):
        text = (
            "safe = " + GH_CLEAN + "  # agentic-sdlc:allow-secret\n"
            "real = " + GH_CLEAN + "\n"
        )
        found = scan_high(text)
        self.assertEqual(len(found), 1, "the marker leaked to a neighbouring line: " + repr(found))
        self.assertEqual(found[0]["line"], 2)

    def test_unmarked_secret_still_blocked(self):
        # CONTROL: the hatch must not weaken the default.
        self.assertTrue(scan_high("TOKEN = " + GH_CLEAN))


@unittest.skipIf(NODE is None, "node not available")
class TestPerMatchSuppression(unittest.TestCase):
    """D22 - a suppressed match (a placeholder value, a published documentation sample or a degenerate
    token) must hide only ITSELF. scanLines used to inspect only the first match of each pattern, so a
    real token after a suppressed one on the same line - separated, glued, or joined by a comma or an
    ampersand inside one greedy value - was never examined. Every token here is assembled at runtime."""

    AWS_DOC = "AKIA" + "IOSFODNN7EXAMPLE"   # the published AWS documentation sample (exact DOC_SAMPLES value)
    PASSWORD = "pass" + "word="
    CHANGE_ME = "change" + "me"
    REAL_PASSWORD = "Hunter2" + "Real99"     # 13 synthetic characters
    MIXED_GITHUB = "TOKEN = " + GH_PLACEHOLDER + " and " + GH_CLEAN

    def _one_finding(self, line, label=None):
        for scan in (scan_high, scan_broad):
            found = scan(line)
            self.assertEqual(len(found), 1, scan.__name__ + ": " + repr(found))
            self.assertEqual(found[0]["line"], 1)
            if label is not None:
                self.assertEqual(found[0]["label"], label)

    def test_real_token_after_suppressed_vendor_sample_is_detected(self):
        # Mutation: stopping at the first match of a pattern, or dropping the token-boundary retry (glued forms).
        cases = {
            "github-separated": GH_PLACEHOLDER + " then " + GH_CLEAN,
            "github-glued": GH_PLACEHOLDER + GH_CLEAN,
            "aws-separated": self.AWS_DOC + " then " + AWS_CLEAN,
            "aws-glued": self.AWS_DOC + AWS_CLEAN,
            "aws-sample-glued-to-github": self.AWS_DOC + GH_CLEAN,
            "github-placeholder-glued-to-aws": GH_PLACEHOLDER + AWS_CLEAN,
        }
        for label, line in cases.items():
            with self.subTest(case=label):
                self._one_finding(line)

    def test_real_password_after_placeholder_assignment_is_detected(self):
        # Mutation: iterating the value pattern globally (the greedy change-me value swallows the real assignment).
        cases = {
            "semicolon": self.PASSWORD + self.CHANGE_ME + "; " + self.PASSWORD + self.REAL_PASSWORD,
            "comma": self.PASSWORD + self.CHANGE_ME + "," + self.PASSWORD + self.REAL_PASSWORD,
            "query-string": "?" + self.PASSWORD + "change-" + "me" + "&" + "pw" + "d=" + self.REAL_PASSWORD,
        }
        for label, line in cases.items():
            with self.subTest(case=label):
                self._one_finding(line, "password-literal")

    def test_real_assigned_secret_after_placeholder_value_is_detected(self):
        # Mutation: resuming the prefix search after the whole suppressed match instead of at its start + 1.
        line = "api_" + "key=" + "change-me-" + "q" * 12 + "-" + "sec" + "ret=" + _R16
        self.assertEqual(scan_high(line), [])
        self.assertEqual(scan_broad(line), [{"line": 1, "label": "assigned-secret"}])

    def test_first_unsuppressed_pattern_labels_the_single_finding(self):
        # Mutation: labelling by the first pattern with ANY match, or keeping the hidden lower-index match hidden.
        cases = {
            "sample-then-real-aws-then-github": self.AWS_DOC + " " + AWS_CLEAN + " " + GH_CLEAN,
            "github-glued-to-aws": GH_CLEAN + AWS_CLEAN,
        }
        for label, line in cases.items():
            with self.subTest(case=label):
                expected = [{"line": 1, "label": "aws-access-key-id"}]
                self.assertEqual(scan_high(line), expected)
                self.assertEqual(scan_broad(line), expected)

    def test_suppressed_matches_alone_stay_suppressed(self):
        # CONTROL: examining every match must not turn a placeholder, a sample or prose into a finding.
        cases = {
            "github-placeholder": GH_PLACEHOLDER,
            "aws-sample": self.AWS_DOC,
            "github-placeholders-glued": GH_PLACEHOLDER + GH_PLACEHOLDER,
            "change-me-then-env-reference": self.PASSWORD + self.CHANGE_ME + "; " + self.PASSWORD + "${DB_PASSWORD}",
            "task-prose": "task-" + "abcdefghij" * 3,
        }
        for label, line in cases.items():
            with self.subTest(case=label):
                self.assertEqual(scan_high(line), [])
                self.assertEqual(scan_broad(line), [])

    def test_marker_still_escapes_a_mixed_line(self):
        # CONTROL: the per-line escape hatch is unchanged.
        self.assertEqual(scan_high(self.MIXED_GITHUB + " # agentic-sdlc:allow-secret"), [])

    def test_per_match_scan_stays_linear(self):
        # Mutation: re-scanning the greedy value from every prefix start (quadratic on a comma chain).
        import time
        lines = [
            GH_PLACEHOLDER * 16000,
            (GH_PLACEHOLDER + " ") * 16000,
            AWS_PLACEHOLDER * 32000,
            (self.PASSWORD + self.CHANGE_ME + ",") * 16000,
            ('"pass' + 'word": "' + "change-me-please" + '", ') * 16000,
        ]
        started = time.time()
        found = _node_json(
            "import('./hooks/secret-patterns.mjs').then(m=>{const ls=JSON.parse(c);"
            "process.stdout.write(JSON.stringify(ls.map(l=>[m.scanLines(l,m.HIGH).length,m.scanLines(l,m.BROAD).length])))})",
            json.dumps(lines),
        )
        self.assertLess(time.time() - started, 10.0, "per-match scanning is not linear")
        self.assertEqual(found, [[0, 0]] * len(lines))

    def _git_repo_with_staged(self, td, body):
        subprocess.run(["git", "init", "-b", "feat"], cwd=td, check=True, capture_output=True)
        (Path(td) / "config.txt").write_text(body + "\n", encoding="utf-8")
        subprocess.run(["git", "add", "--", "config.txt"], cwd=td, check=True, capture_output=True)

    def _scan_commit(self, td):
        proc = subprocess.run(
            [NODE, str(REPO / "hooks" / "scan-commit.mjs")], cwd=td,
            input=json.dumps({"tool_input": {"command": "git commit -m wip"}, "cwd": td}),
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, "scan-commit.mjs crashed")
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    @unittest.skipIf(GIT is None, "git not available")
    def test_commit_guard_blocks_mixed_line(self):
        with tempfile.TemporaryDirectory() as td:
            self._git_repo_with_staged(td, self.MIXED_GITHUB)
            out = self._scan_commit(td)
            self.assertEqual(out.get("hookSpecificOutput", {}).get("permissionDecision"), "deny")
            proc = subprocess.run([NODE, str(REPO / "hooks" / "git-hook-scan.mjs"), "pre-commit"], cwd=td,
                                  capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(proc.returncode, 1, "git-hook-scan pre-commit did not block the mixed line")
            self.assertTrue("github-token" in proc.stderr, "the block message does not name the label")
            self.assertFalse(GH_CLEAN in proc.stderr + proc.stdout, "the raw token was echoed")

    @unittest.skipIf(GIT is None, "git not available")
    def test_commit_guard_does_not_deny_suppressed_sample_only(self):
        # CONTROL: a staged placeholder alone must stay committable.
        with tempfile.TemporaryDirectory() as td:
            self._git_repo_with_staged(td, "TOKEN = " + GH_PLACEHOLDER)
            out = self._scan_commit(td)
            self.assertNotEqual(out.get("hookSpecificOutput", {}).get("permissionDecision"), "deny")


class TestGuardWiring(unittest.TestCase):
    """F7 - the wiring itself must not gate a security guard behind a filter that a legitimate
    spelling of the same operation escapes.

    Two documented facts drive this (code.claude.com/docs/en/hooks, fetched 2026-08-22):
      * "On Windows without Git Bash, the tool is enabled automatically and Claude Code doesn't
        register the Bash tool at all. A hook that matches only `Bash` never fires there."
        -> a Bash-only matcher makes every command guard inert on such a host.
      * "Because the `if` filter is best-effort, use the permission system rather than a hook to
        enforce a hard allow or deny."
        -> an `if` narrowed to `Bash(git commit*)` removes the guard entirely for `git ci`.
    """

    CLAUDE_WIRING = REPO / "hooks" / "hooks-claude.json"
    # Guards whose whole purpose is to inspect a shell command before it runs.
    COMMAND_GUARDS = ("scan-commit.mjs", "destructive-command-guard.mjs", "branch-guard.mjs")

    def setUp(self):
        self.wiring = json.loads(self.CLAUDE_WIRING.read_text(encoding="utf-8"))

    def _pre_tool_use_entries(self):
        for group in self.wiring["hooks"]["PreToolUse"]:
            for hook in group.get("hooks", []):
                yield group.get("matcher", ""), hook

    def _entries_for(self, guard):
        return [
            (matcher, hook) for matcher, hook in self._pre_tool_use_entries()
            if guard in json.dumps(hook)
        ]

    def test_command_guards_cover_the_powershell_tool(self):
        for guard in self.COMMAND_GUARDS:
            entries = self._entries_for(guard)
            self.assertTrue(entries, guard + ": not wired on PreToolUse at all")
            for matcher, _hook in entries:
                with self.subTest(guard=guard, matcher=matcher):
                    self.assertIn(
                        "PowerShell", matcher,
                        guard + ": matcher " + repr(matcher) + " is Bash-only; on a Windows host "
                        "without Git Bash the Bash tool is never registered and this guard "
                        "never fires.",
                    )

    def test_command_guards_are_not_gated_behind_a_subcommand_filter(self):
        # An `if` naming a specific git SUBCOMMAND is the bypassable shape: `git ci` (a git
        # alias for commit) does not match `Bash(git commit*)`, so the hook process never starts
        # and the guard cannot make a decision at all. A tool-level or `git *`-level filter is
        # fine; a subcommand-level one is not.
        for guard in self.COMMAND_GUARDS:
            for matcher, hook in self._entries_for(guard):
                cond = hook.get("if")
                if cond is None:
                    continue
                with self.subTest(guard=guard, cond=cond):
                    self.assertNotRegex(
                        cond, r"\((?:git|.*\s)\s*(?:commit|push|merge|rebase)",
                        guard + ": `if` " + repr(cond) + " filters on a git subcommand; an alias "
                        "for that subcommand escapes the filter and the guard never runs.",
                    )


@unittest.skipIf(NODE is None, "node not available")
class TestQuotedKeyPasswordLiteral(unittest.TestCase):
    """SEC-7 - `password-literal` required its keyword to be followed directly by `\\s*[:=]`, so a
    JSON-quoted key never matched: the closing `"` intervenes. `json-credential` covers the same line
    only from 16 characters, so a 6-15 character password was blocked in YAML/env spelling and
    invisible in the identical JSON spelling - the same value, two verdicts. Every value here is
    synthetic and assembled at runtime, so no password-shaped literal exists in this file."""

    REAL = "Hunter2" + "Real99"                 # 13 characters
    SHORT = "Sw0rd" + "fish"                    # 9 characters
    LONG = "Hunter2" + "Real99" + "Xyz123"      # 19 characters: already inside json-credential's floor
    WORD = "pass" + "word"
    FINDING = [{"line": 1, "label": "password-literal"}]

    @classmethod
    def member(cls, name, value, quote='"'):
        """One `  "name": "value",` member, built at runtime so this source holds no such literal."""
        sep = ":" + " "
        return "  " + quote + name + quote + sep + quote + value + quote + ","

    def test_quoted_key_password_is_high_confidence(self):
        # Mutation: requiring the separator to follow the keyword directly (the JSON spelling escapes).
        cases = {
            "quoted-json-name": self.member(self.WORD.capitalize(), self.REAL),
            "quoted-sa-name": self.member(("sa_" + self.WORD).upper(), self.REAL),
            "quoted-short-value": self.member("pw" + "d", self.SHORT),
            "single-quoted-name": self.member(self.WORD[:4] + "wd", self.SHORT, "'"),
        }
        for label, line in cases.items():
            with self.subTest(case=label):
                self.assertEqual(scan_high(line), self.FINDING)

    def test_existing_spellings_keep_their_verdict(self):
        # CONTROL: the shapes already covered must stay covered, in HIGH and in BROAD.
        for label, line in {
            "yaml-single-quoted": "  " + ("sa_" + self.WORD).upper() + ": " + "'" + self.REAL + "'",
            "env-assignment": self.WORD + "=" + self.REAL,
            "connection-string": "Server=db;" + self.WORD.capitalize() + "=" + self.REAL + ";",
        }.items():
            with self.subTest(case=label):
                self.assertEqual(scan_high(line), self.FINDING)
                self.assertEqual(scan_broad(line), self.FINDING)

    def test_long_quoted_value_is_still_a_finding(self):
        # A 16+ character quoted value was already reported (as json-credential); it stays a HIGH
        # finding, now under the lower-indexed password-literal label.
        self.assertEqual(scan_high(self.member(self.WORD.capitalize(), self.LONG)), self.FINDING)

    def test_widening_does_not_flag_hashes_templates_or_prose(self):
        # CONTROL: a fix that simply matches more fails these.
        for label, line in {
            "password-hash": self.member(self.WORD + "_hash", self.REAL),
            "template-value": self.member(self.WORD.capitalize(), "${DB_" + self.WORD.upper() + "}"),
            "masked-value": self.member(self.WORD.capitalize(), "***MASKED***"),
            "prose": "just a normal line of documentation about " + self.WORD + "s",
            "short-value": self.member(self.WORD.capitalize(), "ab12"),
        }.items():
            with self.subTest(case=label):
                self.assertEqual(scan_high(line), [])


@unittest.skipIf(NODE is None, "node not available")
class TestRoundElevenPrefixParity(unittest.TestCase):
    """Eleventh adversarial round. One root cause across all three command guards.

    Each guard resolves the command name at tokens[0] of a statement, and each walks off a
    DIFFERENT subset of the constructs that may legally precede a command name. POSIX 2.9.1
    closes that production (`cmd_prefix := io_redirect | ASSIGNMENT_WORD`), and bash adds a
    finite reserved-word list, so the prefix set is a positive grammar rather than another
    deny-list. Every deny row below was measured as ALLOW at main 82230cb.

    Severity is not uniform. destructive-command-guard.mjs has NO effect layer - a deleted
    tree does not come back. branch-guard.mjs has none for PUSH: install_git_hooks.py
    installs pre-commit / pre-merge-commit / commit-msg / prepare-commit-msg, and no
    pre-push. Only the commit scanner has a second layer, and only where the installer ran.
    """

    GUARD = REPO / "hooks" / "destructive-command-guard.mjs"

    def _decide(self, command, tool="Bash"):
        proc = subprocess.run(
            [NODE, str(self.GUARD)], cwd=str(REPO),
            input=json.dumps({"tool_name": tool, "tool_input": {"command": command}}),
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout) if proc.stdout.strip() else {}
        return out.get("hookSpecificOutput", {}).get("permissionDecision", "allow")

    def _all_deny(self, cases):
        for cmd in cases:
            with self.subTest(cmd=cmd):
                self.assertEqual(self._decide(cmd), "deny", cmd)

    def _all_allow(self, cases, tool="Bash"):
        for cmd in cases:
            with self.subTest(cmd=cmd):
                self.assertEqual(self._decide(cmd, tool=tool), "allow", cmd)

    def test_assignment_prefix_is_walked_off(self):  # AC1
        self._all_deny(["FOO=bar rm -rf /tmp/x", "A=1 B=2 rm -rf /tmp/x",
                        "FOO=bar git reset --hard"])

    def test_reserved_words_are_walked_off(self):  # AC2
        self._all_deny([
            "if true; then rm -rf /tmp/x; fi",
            "for i in 1; do rm -rf /tmp/x; done",
            "if false; then :; else rm -rf /tmp/x; fi",
            "while true; do rm -rf /tmp/x; done",
            "until false; do rm -rf /tmp/x; done",
            "if false; then :; elif true; then rm -rf /tmp/x; fi",
            "coproc rm -rf /tmp/x",
            "exec rm -rf /tmp/x",
            "if true; then git reset --hard; fi",
        ])

    def test_leading_redirections_and_negation_are_walked_off(self):  # AC3
        self._all_deny([
            "> /tmp/l rm -rf /tmp/x",
            ">/tmp/l rm -rf /tmp/x",
            ">> /tmp/l rm -rf /tmp/x",
            "2>/dev/null rm -rf /tmp/x",
            "2>&1 rm -rf /tmp/x",
            "< /tmp/in rm -rf /tmp/x",
            "> /tmp/l git reset --hard",
            "! rm -rf /tmp/x",
        ])

    def test_substitution_reaches_the_guard_in_every_spelling(self):  # AC4
        # The unquoted $( ) spelling already denies; the backtick spelling and the
        # double-quoted $( ) do not. Bash performs substitution inside double quotes.
        self._all_deny([
            "echo $(rm -rf /tmp/x)",
            "echo " + chr(96) + "rm -rf /tmp/x" + chr(96),
            'echo "$(rm -rf /tmp/x)"',
        ])

    def test_single_quoted_substitution_stays_allowed(self):  # AC4 control
        # CONTROL both ways: inside single quotes a backtick or $( ) is literal text. A
        # handler that is not quote-context aware turns an ordinary documentation commit
        # into a hard block - the failure mode that gets a guard switched off.
        self._all_allow([
            "echo '$(rm -rf /tmp/x)'",
            "echo '" + chr(96) + "rm -rf /tmp/x" + chr(96) + "'",
            "echo 'rm -rf /tmp/x'",
        ])

    def test_flag_and_attached_value_options_never_consume_the_command(self):  # AC1c
        # Seven measured rows, all ALLOW at main. The wrapper table declares these as taking
        # a FOLLOWING value; in GNU xargs they are either plain flags (`-p`/`--interactive`)
        # or take only an ATTACHED value (`-i[R]`, `-l[N]`, `-e[eof]`, and the long forms,
        # whose optional arguments must use `=`). Declaring them as value-taking makes the
        # walker skip the command name.
        self._all_deny([
            "xargs -i rm -rf /tmp/x",
            "xargs -e rm -rf /tmp/x",
            "xargs -p rm -rf /tmp/x",
            "xargs -l rm -rf /tmp/x",
            "xargs --replace rm -rf /tmp/x",
            "xargs --eof rm -rf /tmp/x",
            "xargs --max-lines rm -rf /tmp/x",
        ])

    def test_separate_value_options_still_consume_their_value(self):  # AC1c control
        # The opposite error is equally a bypass: UNDER-consuming leaves the option's value
        # sitting where the command name should be, so `5` is resolved as the command and
        # nothing matches. The rule has to be exact in both directions.
        self._all_deny([
            "xargs -I{} rm -rf /tmp/x", "xargs -I R rm -rf /tmp/x",
            "xargs -n 1 rm -rf /tmp/x", "xargs --max-args 1 rm -rf /tmp/x",
            "xargs -P 2 rm -rf /tmp/x", "xargs -d , rm -rf /tmp/x",
            "xargs -s 100 rm -rf /tmp/x", "xargs -L 1 rm -rf /tmp/x",
            "xargs rm -rf /tmp/x",
        ])

    def test_wrapper_parity_across_the_shared_table(self):  # AC1b
        self._all_deny([
            "sudo rm -rf /tmp/x", "env FOO=1 rm -rf /tmp/x", "command rm -rf /tmp/x",
            "builtin rm -rf /tmp/x", "nohup rm -rf /tmp/x", "setsid rm -rf /tmp/x",
            "nice -n 10 rm -rf /tmp/x", "ionice -c2 rm -rf /tmp/x",
            "stdbuf -o0 rm -rf /tmp/x", "timeout 3 rm -rf /tmp/x",
            "timeout -k 5 3 rm -rf /tmp/x",
        ])

    def test_powershell_colon_bound_switch(self):  # AC5
        for cmd in ["Remove-Item -Recurse:$true -Force C:/x",
                    "Remove-Item -Recurse:$True -Force C:/x",
                    "Remove-Item -Rec:$true -Force C:/x"]:
            with self.subTest(cmd=cmd):
                self.assertEqual(self._decide(cmd, tool="PowerShell"), "deny", cmd)

    def test_powershell_switch_bound_false_is_not_recursive(self):  # AC5 control
        self.assertEqual(
            self._decide("Remove-Item -Recurse:$false -Force C:/x", tool="PowerShell"),
            "allow", "a switch bound to false is off; denying it is a false block")

    def test_ordinary_work_stays_allowed(self):  # AC7
        self._all_allow([
            "echo rm -rf /tmp/x",
            "git reset --soft HEAD~1",
            "npm test",
            "npm test > /tmp/test.log 2>&1",
            "$PYTHON -m pytest -q",
            "rm file.txt",
            "cp -r a b",
            "git clean -n",
            "for i in 1; do echo $i; done",
            "if true; then npm test; fi",
            "time rm file.txt",
        ])

    def test_verb_scope_is_preserved_not_narrowed(self):  # AC8
        # Measured deny today and INTENDED: the guard is scope-narrow by VERB, not by
        # target. Pinned so a later "reduce false positives" change cannot loosen the rule.
        self.assertEqual(self._decide("rm -rf node_modules"), "deny")

    def test_runtime_resolved_command_names_stay_declared_out_of_reach(self):  # BR5
        # These resolve AFTER the hook decides, and are covered by the effect layer
        # (installed git hooks, the Stop-time worktree scan) rather than by this guard.
        # The guard header declares them; asserting ALLOW keeps that declaration honest.
        self._all_allow(["C=rm; $C -rf /tmp/x", "$(echo rm) -rf /tmp/x"])


@unittest.skipIf(NODE is None, "node not available")
class TestSegmenterBounds(unittest.TestCase):
    """The walk must be bounded, and the ALLOW path is the one that matters.

    A denial short-circuits at the first matching check; an allow runs all four checks to
    completion, each re-walking the whole payload tree, and the tokenizer runs it twice more
    for the generic and bash views. Measured at main 82230cb on a completely BENIGN command
    - nested shells in front of a harmless print - 67 chars 121 ms, 91 chars 854 ms,
    103 chars 3056 ms, 115 chars 11.4 s, against a 15 s wired timeout on every runtime.
    No attacker is required: an ordinary command with a few nested shells comes within
    seconds of disabling the guard for that call, and a timed-out hook renders no decision.
    """

    GUARD = REPO / "hooks" / "destructive-command-guard.mjs"
    #: Generous enough not to flake on a loaded CI box, tight enough to catch the exponent.
    CEILING_MS = 5000

    def _timed(self, command):
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
        start = time.time()
        try:
            # A HARD timeout, not a convenience: against the unbounded walk these inputs do
            # not finish in any useful time, and a test that hangs is worse than one that
            # fails. The timeout IS the failure - a hook the runtime kills renders no
            # decision, which is exactly the fail-open this class exists to close.
            proc = subprocess.run([NODE, str(self.GUARD)], cwd=str(REPO), input=payload,
                                  capture_output=True, text=True, encoding="utf-8",
                                  timeout=self.CEILING_MS / 1000.0)
        except subprocess.TimeoutExpired:
            return float(self.CEILING_MS) * 10, "timeout"
        elapsed = (time.time() - start) * 1000
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout) if proc.stdout.strip() else {}
        decision = out.get("hookSpecificOutput", {}).get("permissionDecision", "allow")
        return elapsed, decision

    def test_nesting_bomb_is_bounded_and_still_denies(self):  # AC9
        elapsed, decision = self._timed(("sh -c " * 20) + "rm -rf /tmp/x")
        self.assertEqual(decision, "deny", "a bound must not cost the detection")
        self.assertLess(elapsed, self.CEILING_MS, "%.0f ms - the walk is unbounded" % elapsed)

    def test_benign_nesting_is_bounded(self):  # AC9c
        # The ALLOW path: nothing short-circuits, so every check runs the full walk. This is
        # the path an ordinary command takes, which is why it is the worst case.
        # N=200, not 20: at 20 the unbounded walk is already only ~120 ms, so the row could
        # not fail. Unbounded, 200 nestings measured ~6 s and 400 measured ~35 s.
        elapsed, decision = self._timed(("sh -c " * 200) + "echo hi")
        self.assertEqual(decision, "allow")
        self.assertLess(elapsed, self.CEILING_MS,
                        "%.0f ms on a BENIGN command" % elapsed)

    def test_cost_scales_flat_not_exponentially(self):  # AC9b
        # A single wall-clock threshold cannot catch a reintroduced exponent on faster
        # hardware; a ratio can. But the ratio has to be taken against the WORK, not against
        # the process: node startup is ~70 ms here and dominates a shallow ladder, so a naive
        # shallow-to-deep ratio would pass through a large regression. Subtract a baseline
        # run that does no walking at all, and compare what is left.
        baseline, _ = self._timed("echo hi")
        shallow, _ = self._timed(("sh -c " * 8) + "echo hi")
        deep, _ = self._timed(("sh -c " * 40) + "echo hi")
        shallow_work = max(shallow - baseline, 1.0)
        deep_work = max(deep - baseline, 1.0)
        # Unbounded the curve is ~3.5x per two nestings, so 8 -> 40 is a factor in the
        # thousands. Bounded it is linear in length, i.e. about 5x for 5x the input.
        self.assertLess(deep_work, 25 * shallow_work,
                        "baseline=%.0f shallow=%.0f deep=%.0f ms - the exponent is back"
                        % (baseline, shallow, deep))

    def test_ordinary_nesting_depths_stay_allowed(self):  # AC10b
        # The bound must sit ABOVE real usage, or it becomes the false-block failure mode.
        for cmd in ['bash -c "npm run build && npm test"',
                    "timeout 300 bash -c 'npm test'",
                    "bash -c " + chr(34) + "sh -c 'echo hi'" + chr(34)]:
            with self.subTest(cmd=cmd):
                _, decision = self._timed(cmd)
                self.assertEqual(decision, "allow", cmd)

    def _decision_and_reason(self, command):
        proc = subprocess.run(
            [NODE, str(self.GUARD)], cwd=str(REPO),
            input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}),
            capture_output=True, text=True, encoding="utf-8", timeout=self.CEILING_MS / 1000.0,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout) if proc.stdout.strip() else {}
        block = out.get("hookSpecificOutput", {})
        return block.get("permissionDecision", "allow"), block.get("permissionDecisionReason", "")

    def test_over_cap_input_is_widened_not_skipped(self):  # AC10
        # The ONLY input shape that isolates the widened pass. A nesting ladder does not:
        # shellPayloads enumerates every shell position in one pass, so the innermost command
        # is already visible at depth 1 and the normal checks catch it. Past the input-length
        # cap the tokenizer returns nothing at all, so a deny here can only come from the
        # widened scan - and the reason must say so rather than claiming a parsed match.
        padded = "rm -rf /tmp/x " + ("# padding " * 3000)
        decision, reason = self._decision_and_reason(padded)
        self.assertEqual(decision, "deny", "an over-cap input must widen, not be skipped")
        self.assertIn("widened scan", reason,
                      "a coarse match must not be reported as a parsed one")

    def test_padding_past_the_input_cap_does_not_hide_the_verb(self):  # AC10 regression
        # The row that a first revision of this fix did NOT have, and that let a total
        # fail-open through: the widened backstop truncated at the same MAX_INPUT_CHARS the
        # precise walk uses, so padding the FRONT of a command pushed the destructive verb
        # past both. Measured on that revision: 19 991 chars deny, 20 011 chars ALLOW.
        # A backstop that stops where the thing it backs up stopped is not a backstop.
        # The verb must sit at the END, after the padding - a leading verb stays inside the
        # cap and the test cannot fail.
        for pad in (19990, 30000, 60000):
            with self.subTest(pad=pad):
                command = "echo " + ("a" * pad) + " ; rm -rf /tmp/x"
                decision, _ = self._decision_and_reason(command)
                self.assertEqual(decision, "deny",
                                 "%d chars of padding hid the verb" % len(command))

    def test_padding_past_the_input_cap_still_allows_benign_work(self):  # AC10 control
        decision, reason = self._decision_and_reason("echo " + ("a" * 60000) + " ; echo done")
        self.assertEqual(decision, "allow", reason)

    def test_a_bound_hit_in_one_segment_does_not_hide_its_siblings(self):  # BR3
        # The bounds make `commandTokensOne` return [] on the recursive payload path. If that
        # loss propagated to the sibling segments of the same command line, a partial parse
        # would be reported as a complete clean one - which is the property BR3 forbids and
        # the shape the input-cap fail-open already took once in this change.
        deep = "sh -c " * 60
        for command in (deep + "echo hi ; rm -rf /tmp/x",
                        "rm -rf /tmp/x ; " + deep + "echo hi",
                        deep + "echo hi ; git reset --hard",
                        ("echo a ; " * 2000) + "rm -rf /tmp/x"):
            with self.subTest(command=command[:40]):
                decision, _ = self._decision_and_reason(command)
                self.assertEqual(decision, "deny", "a sibling segment was lost")

    def test_a_bound_hit_does_not_deny_a_clean_command_line(self):  # BR3 control
        # The other half: exhausting a bound must not become "deny whatever I could not
        # finish reading", which would block ordinary work.
        for command in (("sh -c " * 60) + "echo hi ; echo done",
                        ("echo a ; " * 2000) + "echo done"):
            with self.subTest(command=command[:40]):
                decision, reason = self._decision_and_reason(command)
                self.assertEqual(decision, "allow", reason)

    def test_widened_scan_over_approximates_deliberately(self):  # AC10 trade-off
        # The widened pass treats quotes as token delimiters. That is not an accident: the
        # case it exists for is an over-long `bash -c "rm -rf x"`, where the verb sits INSIDE
        # quotes. The price is that an over-long command carrying a quoted destructive string
        # it never runs is denied too. Both halves are pinned here so the trade-off cannot be
        # changed silently in either direction.
        padding = " " + ("# pad " * 6000)
        needed, _ = self._decision_and_reason('bash -c "rm -rf /tmp/x"' + padding)
        self.assertEqual(needed, "deny", "the case the widened pass exists for")
        accepted_cost, _ = self._decision_and_reason('echo "rm -rf /tmp/x"' + padding)
        self.assertEqual(accepted_cost, "deny",
                         "accepted over-approximation: quoted verb past the cap")
        # And the same command SHORT enough to parse is resolved precisely, so the
        # over-approximation is confined to input the guard could not read.
        parsed, _ = self._decision_and_reason('echo "rm -rf /tmp/x"')
        self.assertEqual(parsed, "allow", "a parsable command must not be over-approximated")

    def test_over_cap_benign_input_is_allowed_silently(self):  # AC10 control
        # The other half: widening must not become "deny anything I could not parse", which
        # is the false-block failure mode that gets a guard switched off.
        decision, reason = self._decision_and_reason("echo hi " + ("# padding " * 3000))
        self.assertEqual(decision, "allow", reason)

    def test_a_deep_ladder_carrying_a_verb_is_still_denied(self):  # AC9
        # This does NOT isolate the widened pass, and an earlier revision claimed it did.
        # `shellPayloads` enumerates every shell position in one sweep, so the innermost
        # command is already visible at depth 1 and the precise checks catch it - the deny
        # reason for this input carries no widened-scan marker. Deleting the widened block
        # leaves this green. What it does pin is that bounding the walk did not cost the
        # detection. The widened pass is isolated by the over-cap rows below.
        elapsed, decision = self._timed(("sh -c " * 24) + "rm -rf /tmp/x")
        self.assertEqual(decision, "deny", "an exhausted bound must widen, not give up")
        self.assertLess(elapsed, self.CEILING_MS, "%.0f ms" % elapsed)


@unittest.skipIf(NODE is None, "node not available")
class TestRoundTwelveFixResiduals(unittest.TestCase):
    """Twelfth round: six defects the previous round's FIX introduced, five of them
    regressions against main. The pattern this repository has recorded nine times - the round
    that audits a patch finds more than the round that audits the original.

      A  A `)` or backtick inside DOUBLE quotes restarted the segment mid-string, so the next
         word was resolved as a command name. `git commit -m "fix(x) rm -rf handling"` and
         `printf "%s" "1) git reset --hard is blocked"` became denials: ordinary text, blocked.
      B  The widened fallback read the RAW string while the precise walk decodes ANSI-C
         quoting, line continuations and backslash escapes, so past the length cap `r\\m -rf x`
         and the ANSI-C spelling were allowed where main denies them.
      C  The widened fallback collected names and flags into two independent sets, so a flag
         belonging to one command satisfied a rule about another: `grep -rn "rm" src/...`
         matched the rm rule, with `-rn` grep's and `rm` grep's SEARCH PATTERN.
      D  One shared budget across both tokenizer views meant draining it on the raw view
         silently discarded the bash view - the only one that unescapes.
      E  The budget counted CALLS, not the payloads `shellPayloads` fans out, so a flat
         `eval eval ...` chain still exceeded the 15 s hook timeout (2 008 chars, 18.4 s) and
         a 19 900-char input - under the length cap - exhausted a 4 GB heap with no decision.
      F  Only `$false` counted as a falsy switch binding, so `-Recurse:0` was denied.
    """

    GUARD = REPO / "hooks" / "destructive-command-guard.mjs"
    CEILING_MS = 5000

    def _decide(self, command, tool="Bash"):
        proc = subprocess.run(
            [NODE, str(self.GUARD)], cwd=str(REPO),
            input=json.dumps({"tool_name": tool, "tool_input": {"command": command}}),
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout) if proc.stdout.strip() else {}
        return out.get("hookSpecificOutput", {}).get("permissionDecision", "allow")

    # --- A: quoted prose is not a statement -------------------------------------------------

    def test_a_quoted_text_after_a_paren_is_not_a_new_command(self):
        # Every one of these is text a shell never executes. Blocking routine work is the
        # failure mode that gets a guard switched off, and this repo writes commit messages
        # about this very guard.
        for command in (
            'git commit -m "fix(x) rm -rf handling"',
            'git commit -m "chore(deps) rm -rf node_modules no longer needed"',
            'git commit -m "fix(hooks) git clean -fd is now denied"',
            'printf "%s" "1) git reset --hard is blocked"',
            'gh pr create --body "Closes #12 (see docs) rm -rf is denied by the guard"',
        ):
            with self.subTest(command=command[:44]):
                self.assertEqual(self._decide(command), "allow", command)

    def test_a_text_after_a_real_substitution_is_not_a_new_command(self):
        # The substitution BODY is a command context; the quoted text around it is an
        # argument to the outer command. Splitting there was the same defect one position on.
        for command in (
            'echo "$(date) rm -rf /tmp/build finished"',
            'echo "$(date) git reset --hard was run"',
            'echo "cost $(price) dollars"',
            'git commit -m "release $(date +%F)"',
        ):
            with self.subTest(command=command[:44]):
                self.assertEqual(self._decide(command), "allow", command)

    def test_a_real_substitution_body_is_still_inspected(self):
        # The other direction: bash really runs these, in all three spellings.
        backtick = chr(96)
        for command in (
            'echo "$(rm -rf /tmp/x)"',
            "echo " + backtick + "rm -rf /tmp/x" + backtick,
            'echo "' + backtick + "rm -rf /tmp/x" + backtick + '"',
            "echo $(rm -rf /tmp/x)",
            'echo "$(git reset --hard)"',
        ):
            with self.subTest(command=command[:44]):
                self.assertEqual(self._decide(command), "deny", command)

    def test_a_live_backtick_in_a_message_is_denied_and_that_is_a_decision(self):
        # Borderline, recorded as a decision rather than left as a surprise. In DOUBLE quotes
        # bash really runs a backtick pair, so `git commit -m "docs: use `+B+B+"rm -rf"+B+B+` carefully"`
        # executes it. The guard is scope-narrow by VERB, not by target, and main already
        # denies a bare `rm -rf` with no operand - so denying it inside a live substitution is
        # the same rule, not a new one. main allowed this only because it did not read
        # backticks at all. The workaround is the one a careful shell user would pick anyway:
        # single quotes, which suppress the substitution and stay allowed (asserted below).
        live = "git commit -m " + chr(34) + "docs: use " + chr(96) + "rm -rf" + chr(96) + " carefully" + chr(34)
        self.assertEqual(self._decide(live), "deny", live)
        literal = "git commit -m " + chr(39) + "docs: use " + chr(96) + "rm -rf" + chr(96) + " carefully" + chr(39)
        self.assertEqual(self._decide(literal), "allow", literal)

    def test_a_single_quoted_substitution_stays_literal(self):
        backtick = chr(96)
        for command in ("echo '$(rm -rf /tmp/x)'",
                        "echo '" + backtick + "rm -rf /tmp/x" + backtick + "'"):
            with self.subTest(command=command[:44]):
                self.assertEqual(self._decide(command), "allow", command)

    # --- B: the backstop must read what the precise walk reads ------------------------------

    OVER_CAP = "#" * 20001

    def test_b_widened_scan_decodes_the_same_spellings(self):
        # Past the length cap the precise walk returns nothing, so these are decided by the
        # widened pass alone. main denies every one of them.
        backslash = chr(92)
        dollar = chr(36)
        quote = chr(39)
        for label, command, tool in (
            ("backslash", "r" + backslash + "m -rf /tmp/x " + self.OVER_CAP, "Bash"),
            ("ansi-c",
             dollar + quote + backslash + "x72" + backslash + "x6d" + quote
             + " -rf /tmp/x " + self.OVER_CAP, "Bash"),
            ("powershell-bare-r",
             "Remove-Item -r -Force C:/x " + self.OVER_CAP, "PowerShell"),
        ):
            with self.subTest(label=label):
                self.assertEqual(self._decide(command, tool=tool), "deny", label)

    # --- C: a flag belongs to its own command ----------------------------------------------

    def test_c_widened_scan_does_not_cross_attribute_a_flag(self):
        # `-rn` is grep's and `rm` is grep's search pattern. A rule about rm must not be
        # satisfied by a flag that belongs to something else.
        for label, command in (
            ("grep-rn", 'grep -rn "rm" ' + ("src/file.js " * 1400)),
            ("grep-r", "echo " + ("a" * 25000) + " ; grep -r rm ."),
            ("ls-r", "echo " + ("a" * 25000) + " ; ls -r rm"),
        ):
            with self.subTest(label=label):
                self.assertEqual(self._decide(command), "allow", label)

    # --- D: a bound must not delete a whole reading -----------------------------------------

    def test_d_escaped_spellings_survive_long_shell_chains(self):
        # Honest scope: this pins that the bash view - the only one that unescapes - still
        # reaches a `r\\m` spelling through a long chain of inner shells. It does NOT
        # currently discriminate the per-view budget fix it was written for: sharing one
        # budget again leaves every input here green, because the payload fan-out cap now
        # keeps the budget from draining at any length that still parses. The fix stays
        # because a bound must never delete a whole reading, but this test is a property
        # assertion, not a regression lock, and saying otherwise would be the "cannot fail
        # for the reason it names" defect this package exists to remove.
        backslash = chr(92)
        for count in (45, 50, 80):
            with self.subTest(count=count):
                command = ("eval " * count) + "echo hi ; r" + backslash + "m -rf /tmp/x"
                self.assertEqual(self._decide(command), "deny", "%d evals" % count)

    # --- E: the fan-out is bounded, not just the depth ---------------------------------------

    def test_e_flat_shell_chains_stay_inside_the_hook_budget(self):
        # `shellPayloads` emits one payload per shell/eval token in a segment, each a full
        # suffix. Counting CALLS did not bound that; a 2 008-char command took 18.4 s against
        # a 15 s timeout, and a timed-out hook renders no decision.
        import time
        for shape, tail, expected in (("eval ", "rm -rf /tmp/x", "deny"),
                                      ("eval ", "echo hi", "allow"),
                                      ("sh -c ", "echo hi", "allow")):
            for count in (200, 400):
                with self.subTest(shape=shape.strip(), count=count):
                    start = time.time()
                    decision = self._decide((shape * count) + tail)
                    elapsed = (time.time() - start) * 1000
                    self.assertEqual(decision, expected)
                    self.assertLess(elapsed, self.CEILING_MS,
                                    "%s x%d took %.0f ms" % (shape.strip(), count, elapsed))

    def test_e_a_long_quoted_payload_does_not_exhaust_memory(self):
        # This shape aborted the process with a 4 GB heap exhaustion and no decision at all,
        # at a length UNDER the input cap - so the length cap gave no protection.
        command = ("eval " * 100) + "'" + ("a" * 19797) + "'"
        self.assertEqual(self._decide(command), "allow")

    # --- F: a switch bound to any falsy value is off -----------------------------------------

    def test_f_switch_bound_to_a_falsy_value_is_not_recursive(self):
        for command in ("Remove-Item -Recurse:0 -Force C:/x",
                        "Remove-Item -Recurse: $false -Force C:/x",
                        "Remove-Item -Recurse:$false -Force C:/x",
                        "Remove-Item -Recurse:$null -Force C:/x"):
            with self.subTest(command=command):
                self.assertEqual(self._decide(command, tool="PowerShell"), "allow", command)

    def test_f_switch_bound_to_a_truthy_value_is_recursive(self):
        for command in ("Remove-Item -Recurse:$true -Force C:/x",
                        "Remove-Item -Recurse:1 -Force C:/x",
                        "Remove-Item -Rec:$true -Force C:/x",
                        "Remove-Item -Recurse -Force C:/x"):
            with self.subTest(command=command):
                self.assertEqual(self._decide(command, tool="PowerShell"), "deny", command)

    # --- the splitter change that had no test at all -----------------------------------------

    def test_ampersand_still_separates_statements(self):
        # `&` stopped being a separator when it belongs to a redirect operator. If that
        # narrowing over-reached, two statements would glue into one and the second would
        # never be resolved. Nothing pinned this.
        for command in ("git status && rm -rf /tmp/x",
                        "git status & rm -rf /tmp/x",
                        "npm test > /tmp/l 2>&1 && rm -rf /tmp/x",
                        "npm test &> /tmp/l && rm -rf /tmp/x"):
            with self.subTest(command=command):
                self.assertEqual(self._decide(command), "deny", command)

    def test_ampersand_in_a_redirect_is_not_a_separator(self):
        for command in ("2>&1 rm -rf /tmp/x", "&> /tmp/l rm -rf /tmp/x"):
            with self.subTest(command=command):
                self.assertEqual(self._decide(command), "deny", command)


if __name__ == "__main__":
    unittest.main()
