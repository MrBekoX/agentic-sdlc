"""Round 2 regression tests for the residuals that CHANGELOG `## Unreleased` lists as
"Known and not fixed" after the f430715 bug audit (plan: docs/agentic-sdlc/plans/audit-residuals.md).

Every hook runs as a subprocess on a JSON payload, the way a runtime delivers it. Git fixtures
live in temporary directories with the system and global config switched off.

No literal credential-shaped value appears in this file: the synthetic token is assembled at
runtime from harmless parts.
"""
import base64
import gc
import json
import os
import sys
import time
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
GIT = shutil.which("git")

DESTRUCTIVE = REPO / "hooks" / "destructive-command-guard.mjs"
CODEX_WRITE = REPO / "hooks" / "scan-write-codex.mjs"
WRITE_SIGNAL = REPO / "hooks" / "codex-write-signal.mjs"
GIT_INVOCATION = REPO / "hooks" / "git-invocation.mjs"
CODEX_FLOW_ORDER = REPO / "hooks" / "flow-order-guard-codex.mjs"
SCAN_COMMIT = REPO / "hooks" / "scan-commit.mjs"
BRANCH_GUARD = REPO / "hooks" / "branch-guard.mjs"

# Synthetic GitHub-shaped token: prefix + 36 mixed characters, built at runtime.
SECRET = "gh" + "p_" + "Zq8Lm4Tx9" * 4

BASE_ENV = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
for _name in ("AGENTIC_BRANCH_GUARD_BLOCK", "AGENTIC_WORKTREE_SCAN_STATE", "ZCODE_PLUGIN_ROOT"):
    BASE_ENV.pop(_name, None)


def m(text):
    """Mask the synthetic token in labels and messages."""
    return text.replace(SECRET, "<S>")


def run_hook(hook, command, cwd, *, tool="Bash", env=None, timeout=60):
    """Run a PreToolUse hook; return 'deny', 'ask', 'warn' or 'silent'."""
    hook_env = dict(BASE_ENV, AGENTIC_BRANCH_GUARD_BLOCK="true")
    hook_env.update(env or {})
    proc = subprocess.run(
        [NODE, str(hook)], cwd=str(cwd),
        input=json.dumps({"tool_name": tool, "cwd": str(cwd), "tool_input": {"command": command}}),
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
    (root / "readme.md").write_text("# fixture\n", encoding="utf-8")
    git(root, "add", "readme.md")
    git(root, "commit", "-qm", "base")
    git(root, "branch", "main")
    git(root, "config", "remote.origin.url", "https://example.invalid/fixture.git")
    return root


def here_string(newline="\n", indent=""):
    """A PowerShell single-quoted here-string whose body holds an apostrophe."""
    return "$s = @'" + newline + "it's done" + newline + indent + "'@" + newline


class _RepoCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="audit-r2-")
        cls.repo = make_repo(Path(cls._tmp.name) / "repo")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def decide(self, hook, command, **kw):
        return run_hook(hook, command, self.repo, **kw)


# --------------------------------------------------------------------------------------------
# R2-a: an apostrophe inside a PowerShell `@'...'@` here-string. The raw splitter paired the `'` of
# `@'` with the apostrophe, and the `'` of `'@` then opened a quote that swallowed the next command.
# --------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR2aPowerShellHereString(_RepoCase):

    def test_apostrophe_in_here_string_does_not_hide_the_next_command(self):
        for label, prefix in (("LF", here_string()), ("CRLF", here_string("\r\n")),
                              ("blanks before '@", here_string(indent="  "))):
            command = prefix + "Remove-Item -Recurse C:\\x"
            with self.subTest(form=label):
                self.assertEqual(self.decide(DESTRUCTIVE, command, tool="PowerShell"), "deny")

    def test_here_string_controls(self):
        self.assertEqual(self.decide(DESTRUCTIVE, here_string() + "Get-ChildItem", tool="PowerShell"), "silent")
        self.assertEqual(self.decide(DESTRUCTIVE, "$s = 'it''s done'; Get-ChildItem", tool="PowerShell"), "silent")
        self.assertEqual(self.decide(DESTRUCTIVE, "Remove-Item -Recurse C:\\x", tool="PowerShell"), "deny")


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR2aGitGuardsPowerShellHereString(_RepoCase):

    def test_push_after_apostrophe_here_string_is_seen(self):
        command = here_string() + "git push origin main"
        self.assertEqual(self.decide(BRANCH_GUARD, command, tool="PowerShell"), "deny")

    def test_commit_message_after_apostrophe_here_string_is_scanned(self):
        command = here_string() + "git commit --allow-empty -m 'fix " + SECRET + "'"
        self.assertEqual(self.decide(SCAN_COMMIT, command, tool="PowerShell"), "deny", m(command))

    def test_git_guard_controls(self):
        self.assertEqual(self.decide(BRANCH_GUARD, here_string() + "git status", tool="PowerShell"), "silent")
        self.assertEqual(self.decide(SCAN_COMMIT, here_string() + "git commit --allow-empty -m 'fix: clean'",
                                     tool="PowerShell"), "silent")



def _node_json(script, *args, timeout=120):
    proc = subprocess.run([NODE, "--input-type=module", "-e", script, *args], capture_output=True,
                          text=True, encoding="utf-8", timeout=timeout)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr[-600:])
    return json.loads(proc.stdout)


def _node_timed(module, body, inputs, timeout=120):
    """Run `body` (JS using `m` and `s`) over each input read from a temp file; return elapsed ms
    (a copy of the helper in tests/test_audit_fh.py). A run past `timeout` returns timeout*1000."""
    with tempfile.TemporaryDirectory() as td:
        data = Path(td) / "inputs.json"
        data.write_text(json.dumps(inputs), encoding="utf-8")
        script = ("import { readFileSync } from 'node:fs'; const m = await import(%s);"
                  "const inputs = JSON.parse(readFileSync(process.argv[1], 'utf8')); const t = Date.now();"
                  "for (const s of inputs) { %s }"
                  "process.stdout.write(JSON.stringify(Date.now() - t));" % (json.dumps(module.as_uri()), body))
        try:
            return _node_json(script, str(data), timeout=timeout)
        except subprocess.TimeoutExpired:
            return timeout * 1000


def _assert_linear(case, small, large):
    """The rule of tests/test_audit_cg.py: the 4x input under 3000 ms, and under 9x the 1x input when
    it takes long enough to measure."""
    case.assertLess(large, 3000, "the 4x input took %d ms" % large)
    if large > 1000:
        case.assertLess(large, 9 * max(small, 1), "4x input cost %d ms vs %d ms" % (large, small))


# --------------------------------------------------------------------------------------------
# R2-b: the Codex write guard's shared heredoc grammar read only `[A-Za-z_]\w*` as the delimiter, so
# `<<EOF-1` ended at `EOF`, the body went unread and the written secret was not scanned.
# --------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None, "node required")
class TestR2bCodexDelimiterWord(unittest.TestCase):

    def run_codex(self, command):
        payload = {"tool_name": "Bash", "hook_event_name": "PreToolUse", "tool_input": {"command": command},
                   "cwd": "/repo", "session_id": "s", "transcript_path": "/x"}
        proc = subprocess.run([NODE, str(CODEX_WRITE)], input=json.dumps(payload), capture_output=True,
                              text=True, encoding="utf-8", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def decision(self, command):
        return self.run_codex(command).get("hookSpecificOutput", {}).get("permissionDecision")

    def test_dash_dot_and_digit_delimiters_are_scanned(self):
        for opener, word in (("<<EOF-1", "EOF-1"), ("<<'EOF-1'", "EOF-1"), ('<<"END.1"', "END.1"), ("<<1EOF", "1EOF")):
            command = "cat > .env " + opener + "\nTOKEN=" + SECRET + "\n" + word
            with self.subTest(opener=opener):
                self.assertEqual(self.decision(command), "deny", m(command))

    def test_body_line_equal_to_a_prefix_does_not_end_the_body(self):
        command = "cat > .env <<EOF-1\nEOF\nTOKEN=" + SECRET + "\nEOF-1"
        self.assertEqual(self.decision(command), "deny", m(command))

    def test_clean_body_and_classic_delimiter_unchanged(self):
        self.assertEqual(self.run_codex("cat > notes.txt <<EOF-1\nhello\nEOF-1"), {})
        self.assertEqual(self.run_codex("cat > notes.txt <<'EOF'\nhello\nEOF"), {})
        self.assertEqual(self.decision("cat > .env <<'EOF'\nTOKEN=" + SECRET + "\nEOF"), "deny")

    def test_delimiter_grammar_stays_linear(self):
        def inputs(n):
            head = " ".join(["cat > f <<E"] * 23)
            return [head + " <<" + "a-" * (n // 2), head + " <<'" + "a." * (n // 2)]
        body = "m.extractWrittenContent('Bash', s); m.blankHeredocBodies(s);"
        small = _node_timed(WRITE_SIGNAL, body, inputs(100000))
        large = _node_timed(WRITE_SIGNAL, body, inputs(400000))
        _assert_linear(self, small, large)


# --------------------------------------------------------------------------------------------
# R2-c: `stripGroupWrappers` stopped after eight rounds, so a git call nested nine spaced subshells
# deep kept a leading `(` and was not read.
# --------------------------------------------------------------------------------------------
OLD_STRIP = """
function oldStrip(seg, rounds = 8) {
  let s = String(seg).trim();
  for (let i = 0; i < rounds; i += 1) {
    const before = s;
    if (s.startsWith('(') || s.startsWith('{')) s = s.slice(1).trim();
    if (s.endsWith(')') || s.endsWith('}')) s = s.slice(0, -1).trim();
    if (s === before) break;
  }
  return s;
}
"""


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR2cDeepGroupWrappers(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="audit-r2c-")
        self.addCleanup(self._tmp.cleanup)
        self.repo = make_repo(Path(self._tmp.name) / "repo")

    @staticmethod
    def nested(command, levels):
        return "( " * levels + command + " )" * levels

    def timed_decide(self, hook, command):
        import time
        start = time.perf_counter()
        decision = run_hook(hook, command, self.repo)
        self.assertLess(time.perf_counter() - start, 5.0, "the hook run took over 5 s")
        return decision

    def test_nine_and_sixty_four_subshells_do_not_hide_a_push(self):
        for levels in (9, 64):
            with self.subTest(levels=levels):
                self.assertEqual(self.timed_decide(BRANCH_GUARD, self.nested("git push origin main", levels)), "deny")

    def test_deep_subshell_commit_is_scanned(self):
        (self.repo / "config.py").write_text("key = '" + SECRET + "'\n", encoding="utf-8")
        git(self.repo, "add", "config.py")
        self.assertEqual(self.timed_decide(SCAN_COMMIT, self.nested("git commit -m x", 9)), "deny")

    def test_strip_matches_the_old_loop(self):
        cases = []
        for levels in range(0, 9):
            for core in ("git push", "x", "", ")(", "(}", "{ (", "( )", "a)b", "x (y)"):
                cases.append("( " * levels + core + " )" * levels)
                cases.append("{ " * levels + core + "; }" * levels)
        cases += [")(", "(}", "{ (", "( )", "((((", "))))", "()()()", "\u00a0( x )\u2003", "(\tgit\n)"]
        # The new strip is the old loop's fixed point: equal to the old loop run until nothing changes,
        # and to the eight-round loop wherever eight rounds reached that fixed point.
        script = OLD_STRIP + (
            "const { stripGroupWrappers } = await import(process.argv[1]);\n"
            "const cases = JSON.parse(process.argv[2]);\n"
            "const fixed = (c) => oldStrip(c, 1e6);\n"
            "const reached = cases.filter((c) => oldStrip(c) === fixed(c));\n"
            "console.log(JSON.stringify({\n"
            "  vsFixedPoint: cases.filter((c) => stripGroupWrappers(c) !== fixed(c)),\n"
            "  vsEightRounds: reached.filter((c) => stripGroupWrappers(c) !== oldStrip(c)),\n"
            "  reached: reached.length, total: cases.length }));\n")
        result = _node_json(script, GIT_INVOCATION.as_uri(), json.dumps(cases))
        self.assertEqual(result["vsFixedPoint"], [])
        self.assertEqual(result["vsEightRounds"], [])
        self.assertGreater(result["reached"], result["total"] // 2, result)

    def test_strip_is_linear(self):
        body = "m.stripGroupWrappers(s);"
        small = _node_timed(GIT_INVOCATION, body, ["( " * (128 * 1024 // 2)])
        large = _node_timed(GIT_INVOCATION, body, ["( " * (512 * 1024 // 2)])
        _assert_linear(self, small, large)



# --------------------------------------------------------------------------------------------
# R2-d: git resolves each later relative `-C` against the previous one, so `git -C sub -C sub commit`
# commits in `sub/sub`. The scan took its target from the de-duplicated `-C` list (`sub`).
# --------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR2dRepeatedDashC(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="audit-r2d-")
        self.addCleanup(self._tmp.cleanup)
        self.outer = Path(self._tmp.name) / "outer"
        self.outer.mkdir()
        self.sub = make_repo(self.outer / "sub")
        self.nested = make_repo(self.sub / "sub")

    def stage_token(self, repo):
        (repo / "config.py").write_text("key = '" + SECRET + "'\n", encoding="utf-8")
        git(repo, "add", "config.py")

    def decide(self, command):
        return run_hook(SCAN_COMMIT, command, self.outer)

    def test_real_git_agrees_on_the_target(self):
        top = git(self.outer, "-C", "sub", "-C", "sub", "rev-parse", "--show-toplevel").strip()
        self.assertEqual(Path(top).resolve(), self.nested.resolve())

    def test_repeated_dash_c_scans_the_nested_repository(self):
        self.stage_token(self.nested)
        self.assertEqual(self.decide("git -C sub -C sub commit -m x"), "deny")

    def test_message_file_is_read_from_the_nested_target(self):
        (self.sub / "msg.txt").write_text("fix " + SECRET + "\n", encoding="utf-8")
        (self.nested / "msg.txt").write_text("fix: clean\n", encoding="utf-8")
        self.assertEqual(self.decide("git -C sub -C sub commit --allow-empty -F msg.txt"), "silent")

    def test_dash_c_controls(self):
        # `-C sub -C ../sub` comes back to `sub`; an absolute `-C` replaces the chain; `-C ''` is a no-op.
        self.stage_token(self.sub)
        self.assertEqual(self.decide("git -C sub -C ../sub commit -m x"), "deny")
        self.assertEqual(self.decide("git -C sub -C " + json.dumps(str(self.sub)) + " commit -m x"), "deny")
        self.assertEqual(self.decide("git -C '' -C sub commit -m x"), "deny")
        # A `-C` inside a shell payload redirects no read: its `-F` file is not opened (the outer folder
        # is no repository, so the scan of the hook's own cwd only warns that it could not read it).
        (self.nested / "msg.txt").write_text("fix " + SECRET + "\n", encoding="utf-8")
        self.assertIn(self.decide("bash -c 'git -C sub -C sub commit -F msg.txt'"), ("silent", "warn"))

    def test_collected_c_directories_stay_de_duplicated(self):
        script = ("const { resolveGitCommands } = await import(process.argv[1]);\n"
                  "const r = resolveGitCommands('git -C sub -C sub commit -m x', { lookup: () => '', cwd: process.argv[2] });\n"
                  "console.log(JSON.stringify({ dirs: r.dirs, calls: r.calls.map((c) => c.dirs) }));\n")
        out = _node_json(script, GIT_INVOCATION.as_uri(), str(self.outer))
        self.assertEqual(out["dirs"], ["sub"])
        self.assertEqual(out["calls"], [["sub"]])



# --------------------------------------------------------------------------------------------
# R2-e: `mask.py` sliced the value of every prefix hit, so K hits sharing one long value run copied
# O(K*L) characters. It now checks the value by index.
# --------------------------------------------------------------------------------------------
def _load_mask():
    sys.path.insert(0, str(REPO / "scripts"))
    try:
        from sdlc_runner import mask
    finally:
        sys.path.remove(str(REPO / "scripts"))
    return mask


UNIT = "db_pass" + "word="       # every repeat is a prefix hit; all share the run to the line end


class TestR2eMaskLinear(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.mask = _load_mask()

    def best_time(self, line, repeats):
        best = float("inf")
        gc.disable()
        try:
            for _ in range(repeats):
                start = time.perf_counter()
                self.mask.mask_text(line)
                best = min(best, time.perf_counter() - start)
        finally:
            gc.enable()
        return best

    def test_one_long_run_with_many_prefix_hits_is_linear(self):
        small = self.best_time(UNIT * 8000, 3)
        large = self.best_time(UNIT * 128000, 2)
        ratio = large / max(small, 1e-6)
        self.assertLess(ratio, 40, "16x the line cost %.1fx the time (%.3fs vs %.3fs)" % (ratio, large, small))

    @unittest.skipIf(NODE is None, "node required")
    def test_output_equals_node_on_long_hit_lines(self):
        quoted = 'db_pass' + 'word="'
        lines = [UNIT * 300, quoted * 300, UNIT * 50 + "Hq7mK2pWz9 tail", quoted * 20 + 'Hq7mK2pWz9" end',
                 ("pass" + "word=${X}") * 30, "pass" + "word=" + "x" * 5000, ("pass" + "word='") * 40 + "abc'"]
        src = ("let c='';process.stdin.setEncoding('utf8');process.stdin.on('data',d=>c+=d).on('end',()=>"
               "import('./hooks/secret-patterns.mjs').then(m=>{const t=JSON.parse(c);"
               "process.stdout.write(JSON.stringify({broad:t.map(x=>m.redactSecrets(x,m.BROAD)),"
               "high:t.map(x=>m.redactSecrets(x))}));}))")
        proc = subprocess.run([NODE, "-e", src], input=json.dumps(lines), cwd=str(REPO), capture_output=True,
                              text=True, encoding="utf-8", timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        node = json.loads(proc.stdout)
        for i, line in enumerate(lines):
            with self.subTest(i=i):
                self.assertEqual(self.mask.redact_labelled(line), node["broad"][i])
                self.assertEqual(self.mask.redact_labelled(line, self.mask.HIGH), node["high"][i])



# --------------------------------------------------------------------------------------------
# Round 2 adversarial pins (AC32).
# --------------------------------------------------------------------------------------------
REMOVE = "Remove-" + "Item -Recurse C:\\x"   # assembled so this file's own command lines stay plain


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR2SecurityAdversarial(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="audit-r2-sec-")
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.repo = make_repo(self.base / "repo")

    def test_here_string_view_reaches_command_and_encoded_payloads(self):
        script = here_string() + REMOVE
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        for label, command in (("-Command", 'pwsh -Command "' + script.replace("$", "`$") + '"'),
                               ("-EncodedCommand", "pwsh -EncodedCommand " + encoded)):
            with self.subTest(payload=label):
                self.assertEqual(run_hook(DESTRUCTIVE, command, self.repo, tool="PowerShell"), "deny")

    def test_eof_dash_source_write_counts_for_codex_flow_order(self):
        rollout = self.base / "rollout.jsonl"
        rollout.write_text("", encoding="utf-8")
        payload = {"tool_name": "Bash", "tool_input": {"command": "cat <<'EOF-1' > src/app.py\nx = 1\nEOF-1\n"},
                   "transcript_path": str(rollout), "cwd": str(self.base)}
        env = dict(os.environ, AGENTIC_FLOW_ORDER_BLOCK="true")
        start = time.perf_counter()
        proc = subprocess.run([NODE, str(CODEX_FLOW_ORDER)], input=json.dumps(payload), capture_output=True,
                              text=True, encoding="utf-8", env=env, timeout=60)
        self.assertLess(time.perf_counter() - start, 5.0)
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        out = json.loads(proc.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_here_string_scan_is_linear(self):
        def inputs(size):
            unit_a = "@'\nit's done\n'@\n"
            unit_b = "@' it's '' \"x\" "
            return [unit_a * (size // len(unit_a)), unit_b * (size // len(unit_b)), "@'\n" + "it's\n" * (size // 5)]
        body = "m.powershellHereStringRanges(s);"
        small = _node_timed(GIT_INVOCATION, body, inputs(128 * 1024))
        large = _node_timed(GIT_INVOCATION, body, inputs(512 * 1024))
        _assert_linear(self, small, large)

    def test_payload_dash_c_never_redirects_reads(self):
        nested = make_repo(make_repo(self.base / "sub") / "sub")
        (nested / "msg.txt").write_text("fix " + SECRET + "\n", encoding="utf-8")
        for command in ("bash -c 'git -C sub -C sub commit --allow-empty -F msg.txt'",
                        "sh -c \"git -C sub -C sub commit --allow-empty --file=msg.txt\""):
            with self.subTest(command=command):
                self.assertIn(run_hook(SCAN_COMMIT, command, self.base), ("silent", "warn"))

    def test_masked_long_hit_lines_keep_no_value_part(self):
        mask = _load_mask()
        value = "Hq7mK2pWz9" + "Rt4Lx8Vn3Bc6"
        for line in (UNIT * 50 + value, (UNIT + value + " ") * 20, ('db_pass' + 'word="') * 30 + value + '"'):
            masked = mask.mask_text(line)
            parts = {value[i:i + 8] for i in range(len(value) - 7)}
            with self.subTest(line=line[:30]):
                self.assertFalse([part for part in parts if part in masked], "a value part survived masking")



# --------------------------------------------------------------------------------------------
# Round 2 docs (AC33): the limitations Round 2 fixed are gone, and the new behaviour is described.
# --------------------------------------------------------------------------------------------
class TestR2DocsFollowFixes(unittest.TestCase):

    REMOVED = (
        "confuses the raw splitter",
        "`stripGroupWrappers` stops after 8 rounds",
        "`-C sub -C sub` is not de-duplicated",
        "does not read a `<<EOF-1` delimiter",
        "slices in O(K·L)",
    )

    def test_round2_limitations_removed_and_described(self):
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        start = changelog.index("## Unreleased")
        unreleased = changelog[start:changelog.index("\n## ", start + 5)]
        readme = (REPO / "hooks" / "README.md").read_text(encoding="utf-8")
        for phrase in self.REMOVED:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, unreleased)
                self.assertNotIn(phrase, readme)
        for needle in ("R2-a", "R2-b", "R2-c", "R2-d", "R2-e"):
            self.assertIn(needle, unreleased)
        troubleshooting = (REPO / "docs" / "troubleshooting.md").read_text(encoding="utf-8")
        self.assertIn("here-string", troubleshooting)
        testing = (REPO / "docs" / "testing.md").read_text(encoding="utf-8")
        self.assertIn("`tests/test_audit_residuals_r2.py`", testing)



# --------------------------------------------------------------------------------------------
# Round 2 security review follow-ups.
# --------------------------------------------------------------------------------------------
@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestR2ReviewFollowUps(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="audit-r2-fu-")
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)

    def test_commit_in_a_shell_inside_an_alias_is_scanned_in_the_dash_c_repository(self):
        # Review M1: targets came only from invocations, and a payload invocation keeps the hook's own
        # cwd, so `git -C ../other x` with `x = !sh -c "git commit"` was scanned in the wrong
        # repository. Round 1 scanned the call's `-C` target.
        here = make_repo(self.base / "here")
        other = make_repo(self.base / "other")
        (other / "config.py").write_text("key = '" + SECRET + "'\n", encoding="utf-8")
        git(other, "add", "config.py")
        command = "git -C ../other -c alias.x='!sh -c \"git commit -m wip\"' x"
        self.assertEqual(run_hook(SCAN_COMMIT, command, here), "deny")

    def test_grammar_leaves_unsafe_delimiter_words_unread(self):
        # The heredoc grammar reads only a word of letters, digits, `_`, `.` and `-` (the same inside
        # and outside quotes); every other opener stays unread, as an unknown form, rather than read
        # with a body longer than bash's.
        commands = ['cat > n <<"E\\"F"\nx\nE"F\nE\\', 'cat > n <<"A$(x "\nx\nA$(x ',
                    "cat > n <<\\'EOF'\nx\nEOF", "cat > n <<'EOF'X\nx\nEOF", "cat > n <<EOF$x\nx\nEOF",
                    "cat > n <<EOF\rX\nx\nEOF", "cat <<<EOF > n\nx\nEOF", "cat \\<<EOF > n\nx\nEOF"]
        script = ("const m = await import(process.argv[1]); const cs = JSON.parse(process.argv[2]);"
                  "console.log(JSON.stringify(cs.map((c) => m.blankHeredocBodies(c) === c)));")
        self.assertEqual(_node_json(script, WRITE_SIGNAL.as_uri(), json.dumps(commands)), [True] * len(commands))
        safe = ["cat > n <<EOF-1\nx\nEOF-1", "cat > n <<'END.1'\nx\nEND.1", 'cat > n <<"1EOF"\nx\n1EOF',
                "cat > n <<\\EOF\nx\nEOF", "cat > n <<'EOF'\r\nx\r\nEOF\r",
                "cat > n <<EOF''\nx\nEOF", "cat > n <<'EOF'\"\"\nx\nEOF"]
        self.assertEqual(_node_json(script, WRITE_SIGNAL.as_uri(), json.dumps(safe)), [False] * len(safe))

    def test_secret_after_an_empty_quote_pair_word_is_scanned(self):
        # An empty quote pair after the word (`<<EOF''`, bash's word `EOF`) was read by 1905c15; leaving it
        # unread would skip the written content in the Codex write guard.
        payload = {"tool_name": "Bash", "hook_event_name": "PreToolUse", "cwd": "/repo", "session_id": "s",
                   "transcript_path": "/x",
                   "tool_input": {"command": "cat > config.py <<EOF''\nTOKEN=" + SECRET + "\nEOF"}}
        proc = subprocess.run([NODE, str(CODEX_WRITE)], input=json.dumps(payload), capture_output=True,
                              text=True, encoding="utf-8", timeout=60)
        out = json.loads(proc.stdout) if proc.stdout.strip() else {}
        self.assertEqual(out.get("hookSpecificOutput", {}).get("permissionDecision"), "deny")

    def test_commit_in_a_nested_alias_with_its_own_dash_c_is_scanned_there(self):
        # Confirmation review M2: `x = !git -C b y`, `y = !sh -c "git commit"` commits in `a/b`; the
        # targets must stay a superset of Round 1's, which named `a/b`.
        here = make_repo(self.base / "here")
        nested = make_repo(make_repo(here / "a") / "b")
        (nested / "config.py").write_text("key = '" + SECRET + "'\n", encoding="utf-8")
        git(nested, "add", "config.py")
        command = ("git -C a -c alias.x='!git -C b y' -c alias.y='!sh -c \"git commit -m wip\"' x")
        self.assertEqual(run_hook(SCAN_COMMIT, command, here), "deny")

    def _codex_order(self, command):
        rollout = self.base / "rollout.jsonl"
        rollout.write_text("", encoding="utf-8")
        payload = {"tool_name": "Bash", "tool_input": {"command": command},
                   "transcript_path": str(rollout), "cwd": str(self.base)}
        env = dict(os.environ, AGENTIC_FLOW_ORDER_BLOCK="true")
        proc = subprocess.run([NODE, str(CODEX_FLOW_ORDER)], input=json.dumps(payload), capture_output=True,
                              text=True, encoding="utf-8", env=env, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        out = json.loads(proc.stdout) if proc.stdout.strip() else {}
        return out.get("hookSpecificOutput", {}).get("permissionDecision")

    def test_heredoc_body_is_never_longer_than_bash_reads(self):
        # Review M2: a backslash inside a double-quoted delimiter, and `<<-` backtracking to a `-EOF`
        # word, made the grammar read past the line where bash ends the body, so the source write after
        # it was swallowed.
        for label, command in (
                ("escaped quote in a double-quoted delimiter",
                 'cat > n.txt <<"E\\"F"\nx\nE"F\nprintf y > src/app.py\nE\\'),
                ("<<- with a tab-indented terminator",
                 "cat > n.txt <<-EOF\n\tx\n\tEOF\nprintf y > src/app.py\n-EOF"),
                ("a $( construct in a double-quoted delimiter",
                 'cat > n.txt <<"A$(x "\n")"; printf y > src/app.py;\nA$(x '),
                ("a here-string, not a heredoc",
                 "cat <<<EOF > n.txt\nprintf y > src/app.py\nEOF"),
                ("a CR inside the delimiter word",
                 "cat > n.txt <<EOF\rX\nEOF\rX\nprintf y > src/app.py\nEOF\r")):
            with self.subTest(case=label):
                self.assertEqual(self._codex_order(command), "deny", "the source write was hidden")


# --------------------------------------------------------------------------------------------
# Implementation audit follow-ups: the delimiter set leaves openers unread that 1905c15 read with an
# identifier-prefix delimiter (`<<'EOF'X`, `<<EOF$x`, `<<EOF+`). An unread opener must not make the
# Codex write guard scan less, nor make the test-run check read the lines after it as commands.
# --------------------------------------------------------------------------------------------
FLOW_EVIDENCE = REPO / "hooks" / "flow-evidence.mjs"


@unittest.skipIf(NODE is None, "node is not installed")
class TestR2AuditFollowUps(unittest.TestCase):
    def decision(self, command):
        payload = {"tool_name": "Bash", "hook_event_name": "PreToolUse", "cwd": "/repo", "session_id": "s",
                   "transcript_path": "/x", "tool_input": {"command": command}}
        proc = subprocess.run([NODE, str(CODEX_WRITE)], input=json.dumps(payload), capture_output=True,
                              text=True, encoding="utf-8", timeout=60)
        out = json.loads(proc.stdout) if proc.stdout.strip() else {}
        return out.get("hookSpecificOutput", {}).get("permissionDecision")

    def runs_tests(self, commands):
        script = ("const m = await import(process.argv[1]); const cs = JSON.parse(process.argv[2]);"
                  "const re = /pytest/; console.log(JSON.stringify(cs.map((c) => m.isRealRunnerInvocation(c, re))));")
        return _node_json(script, FLOW_EVIDENCE.as_uri(), json.dumps(commands))

    def test_secret_after_an_unread_opener_is_still_scanned(self):
        for opener in ("<<'EOF'X", "<<EOF$x", "<<EOF+", '<<"EOF"X', "<<'E F'"):
            with self.subTest(opener=opener):
                self.assertEqual(self.decision("cat > .env " + opener + "\nTOKEN=" + SECRET + "\nEOF"), "deny")

    def test_secret_past_the_opener_cap_is_still_scanned(self):
        head = "; ".join(["cat > f <<E\nx\nE"] * 30)
        self.assertEqual(self.decision(head + "\ncat > .env <<'EOF'\nTOKEN=" + SECRET + "\nEOF"), "deny")

    def test_clean_write_after_an_unread_opener_is_not_denied(self):
        self.assertIsNone(self.decision("cat > notes.txt <<'EOF'X\nhello\nEOF"))

    def test_lines_after_an_unread_opener_are_not_a_test_run(self):
        self.assertEqual(self.runs_tests([
            "cat > notes.md <<'EOF'X\npytest -q\nEOF",
            "cat > notes.md <<EOF+\npytest -q\nEOF",
            "cat > notes.md <<'E F'\npytest -q\nE F",
        ]), [False, False, False])

    def test_test_runs_around_read_heredocs_and_here_strings_still_count(self):
        self.assertEqual(self.runs_tests([
            "pytest -q\ncat > notes.md <<'EOF'X\nx\nEOF",
            "pytest -q; cat > notes.md <<'EOF'X\nx",
            "cat > notes.md <<'EOF'\nx <<'Y Z'\nEOF\npytest -q",
            "cat <<<x\npytest -q",
            "cat \\<<EOF\npytest -q",
            "pytest -q",
        ]), [True, True, True, True, True, True])

    def test_secret_in_a_multi_line_or_unread_segment_is_scanned(self):
        # Security review of the follow-up: the scan must stay a superset of what bash writes. Every
        # segment holding a newline or `<<` is now scanned raw; an even backslash run before `<<`
        # leaves a real operator.
        cases = {
            "an even backslash run before the operator": "tee .env \\\\<<'EOF'\nTOKEN=" + SECRET + "\nEOF",
            "a command after an escaped operator": "cat \\<<EOF > n\nprintf '" + SECRET + "' > .env\nEOF",
            "a command after a here-string": "cat <<<EOF > n\nprintf '" + SECRET + "' > .env\nEOF",
            "a command after a dotted delimiter's body": "cat > a <<EOF.txt\nx\nEOF.txt\necho " + SECRET + " > .env\nEOF",
            "a write on the line after true": "true\necho " + SECRET + " > .env",
            "a write on the line after cd": "cd /x\necho " + SECRET + " > .env",
            "an empty quote pair with a $ in the body": "cat > config.py <<EOF''\nTOKEN=" + SECRET + "\nP=$HOME\nEOF",
            "a second opener on a read opener's line": "cat <<A <<'B' > .env\nx\nA\nTOKEN=" + SECRET + "\nB",
            "a command after a read opener on its line": "cat <<'EOF' > a.txt; printf '" + SECRET + "' > b.txt\nx\nEOF",
        }
        for name, command in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.decision(command), "deny")

    def test_clean_multi_line_commands_are_not_denied(self):
        for command in ("cat > notes.txt <<EOF''\nP=$HOME\nEOF", "true\necho hello > notes.txt",
                        "cat <<<EOF > n\nprintf hi > notes.txt\nEOF"):
            with self.subTest(command=command):
                self.assertIsNone(self.decision(command))

    def test_escaped_parity_and_second_opener_cut_the_test_run_check(self):
        self.assertEqual(self.runs_tests([
            "cat \\\\<<'EOF' > notes.md\npytest -q\nEOF",
            "cat <<A <<'B' > n\nx\nA\npytest -q\nB",
        ]), [False, False])

    def test_no_reading_is_narrower_than_1905c15(self):
        # Re-plan after the superset review: each check runs the current heredoc grammar AND 1905c15's,
        # and combines them in its safe direction (scan: union; targets: union; test run: both count).
        octal = "".join("\\%03o" % ord(c) for c in SECRET)
        cases = {
            "a here-string, then a piped write": "cat <<<EOF > n\na; printf %s " + SECRET + " | tee .env; b\nEOF",
            "an escaped operator, then a piped write": "cat \\<<EOF > n\na; printf %s " + SECRET + " | tee .env; b\nEOF",
            "four less-than signs": "cat <<<<EOF > n\na; printf %s " + SECRET + " | tee .env; b\nEOF",
            "a dotted delimiter's later line": "cat > a <<EOF.txt\nx\nEOF.txt\na; printf %s " + SECRET + " | tee .env; b\nEOF",
            "a quoted digit word before an escaped printf": "echo \"a <<1 b\"\ntrue; printf '" + octal + "' > .env;\n1",
            "an escaped printf after an even backslash run": "tee .env \\\\<<'EOF'\nit's\nEOF\nx; printf '" + octal + "' > b",
        }
        for name, command in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.decision(command), "deny")
        self.assertEqual(self.runs_tests([
            "echo \"shift <<1 bit\"\ncat > notes.md <<EOF\n1\npytest -q\nEOF",
            "cat <<<<EOF\npytest -q\nEOF",
        ]), [False, False])
        script = ("const m = await import(process.argv[1]);"
                  "console.log(JSON.stringify(m.currentEditTargets('Bash', process.argv[2])));")
        targets = _node_json(script, (REPO / "hooks" / "codex-rollout.mjs").as_uri(),
                             "echo \"a <<1 b\"\nprintf y > src/app.py\n1")
        self.assertIn("src/app.py", targets)

    def test_unread_opener_scan_stays_linear(self):
        def inputs(n):
            return ["cat > f <<'E F'\n" + "x <<a\n" * (n // 6), "<<'a'b " * (n // 7),
                    "\\\\\\<<'a'b\n" * (n // 10), "\\" * n + "<<a\nx"]
        body = "m.extractWrittenContent('Bash', s);"
        small = _node_timed(WRITE_SIGNAL, body, inputs(100000))
        large = _node_timed(WRITE_SIGNAL, body, inputs(400000))
        _assert_linear(self, small, large)
        # A leading `pytest -q` line makes the current reading count a run, so the legacy reading (run
        # only then) is timed too.
        body = "m.isRealRunnerInvocation('pytest -q\\n' + s, /pytest/);"
        small = _node_timed(FLOW_EVIDENCE, body, inputs(25000))
        large = _node_timed(FLOW_EVIDENCE, body, inputs(100000))
        _assert_linear(self, small, large)

    def test_worst_case_command_scans_well_inside_the_hook_timeout(self):
        # Both readings on a 500 KiB command (under the 512 KiB cap) of multi-line printf segments with
        # `<<`: far over the 24-opener cap, so the grammar passes are skipped while the raw-segment push,
        # the unread-opener slice and both payload forms fire. It must finish far inside the 20 s Codex
        # hook timeout. The grammar passes under the cap are timed by the in-process linear tests.
        line = "true; printf 'a\\101 <<x' > f; x <<'E F'\n"
        command = (line * (500 * 1024 // len(line)))[: 500 * 1024]
        payload = {"tool_name": "Bash", "hook_event_name": "PreToolUse", "cwd": "/repo", "session_id": "s",
                   "transcript_path": "/x", "tool_input": {"command": command}}
        start = time.monotonic()
        proc = subprocess.run([NODE, str(CODEX_WRITE)], input=json.dumps(payload), capture_output=True,
                              text=True, encoding="utf-8", timeout=60)
        elapsed = time.monotonic() - start
        self.assertEqual(proc.returncode, 0, proc.stderr[-400:])
        self.assertLess(elapsed, 5.0, "a 500 KiB command took %.1f s" % elapsed)


if __name__ == "__main__":
    unittest.main()
