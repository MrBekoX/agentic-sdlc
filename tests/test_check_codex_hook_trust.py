"""Hermetic tests for scripts/check_codex_hook_trust.py (spec DP36, AC131).

The check talks to `codex app-server --stdio`. These tests never run a real Codex binary:
every CLI run passes `--codex` pointing at a fake app-server launcher written to a temp dir
(`codex.cmd` calling sys.executable on win32, a `#!` file with mode 0755 elsewhere), so the
full CLI path runs on both CI operating systems with no network and no paid call.

The fake speaks newline-delimited JSON-RPC shaped after the stable Codex 0.154.0 schemas
(HooksListParams / HooksListResponse), picks its behaviour from FAKE_TRUST_MODE, logs every
received method to a file and writes its own PID to a file.

AGENTIC_TRUST_CHECK_UNDER_TEST overrides the script path (mutation control only).
"""
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
UNDER_TEST = Path(os.environ.get("AGENTIC_TRUST_CHECK_UNDER_TEST") or REPO / "scripts" / "check_codex_hook_trust.py")
PLUGIN = "agentic-sdlc@personal"
OTHER_PLUGIN = "other-plugin@elsewhere"
LOG_NAME = "methods.log"
PID_NAME = "server.pid"
LINE_KEYS = (
    "codex_hook_trust_plugin",
    "codex_hook_trust_counts",
    "codex_hook_trust_untrusted_events",
    "codex_hook_trust",
    "codex_hook_trust_next_step",
)
CLI_TIMEOUT_SECONDS = 90

FAKE_SERVER = r'''
import json
import os
import sys
import time

MODE = os.environ["FAKE_TRUST_MODE"]
STATE = os.environ["FAKE_TRUST_STATE_DIR"]
EXPECT_CWD = os.environ["FAKE_TRUST_EXPECT_CWD"]
PLUGIN = "agentic-sdlc@personal"
OTHER = "other-plugin@elsewhere"
MARK = os.environ["FAKE_TRUST_MARK"]
# The 8 hooks of hooks/hooks-codex.json: 5 preToolUse, 1 sessionStart, 2 stop.
EVENTS = ["preToolUse"] * 5 + ["sessionStart"] + ["stop"] * 2

with open(os.path.join(STATE, "server.pid"), "w", encoding="utf-8") as fh:
    fh.write(str(os.getpid()))
if sys.argv[1:] != ["app-server", "--stdio"]:
    sys.exit(3)


def log(method):
    with open(os.path.join(STATE, "methods.log"), "a", encoding="utf-8") as fh:
        fh.write(method + "\n")


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def hook(index, plugin, event, status):
    home = os.path.expanduser("~")
    return {
        "key": "%s-key-%d" % (MARK, index),
        "currentHash": "%s-hash-%d" % (MARK, index),
        "sourcePath": os.path.join(home, "%s-source" % MARK, "hooks-%d.json" % index),
        "pluginId": plugin,
        "eventName": event,
        "trustStatus": status,
        "source": "plugin",
        "enabled": True,
        "isManaged": status == "managed",
        "displayOrder": index,
        "timeoutSec": 20,
        "matcher": None,
        "statusMessage": None,
        "handlerType": "command",
        "command": "node hook-%d.mjs" % index,
    }


def plugin_hooks(statuses):
    return [hook(i, PLUGIN, EVENTS[i], s) for i, s in enumerate(statuses)]


def hooks_for_mode():
    other = [hook(99, OTHER, "preToolUse", "untrusted")]
    if MODE in ("trusted", "notify-first"):
        return plugin_hooks(["trusted"] * 8) + other
    if MODE == "baseline":
        return plugin_hooks(["untrusted"] * 5 + ["trusted"] + ["untrusted"] * 2)
    if MODE == "modified":
        return plugin_hooks(["trusted"] * 7 + ["modified"]) + other
    if MODE == "managed":
        return plugin_hooks(["managed"] * 5 + ["trusted"] * 3) + other
    if MODE == "no-hooks":
        return other
    raise SystemExit("unknown mode " + MODE)


def same_path(a, b):
    return isinstance(a, str) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def reply(msg_id, result):
    if MODE == "notify-first":
        send({"method": "configWarning", "params": {"summary": "fake notification"}})
    send({"id": msg_id, "result": result})


def bad_request(msg_id, why):
    send({"id": msg_id, "error": {"code": -32602, "message": "fake rejected " + why}})


for raw in sys.stdin:
    raw = raw.strip()
    if not raw:
        continue
    msg = json.loads(raw)
    method = msg.get("method")
    log(str(method))
    if MODE == "exit-early":
        sys.exit(0)
    if MODE == "hang":
        continue
    if MODE == "deep-nest":
        # A syntactically unfinished but very deeply nested line: json.loads raises RecursionError.
        sys.stdout.write("[" * 200000 + "\n")
        sys.stdout.flush()
        continue
    if method == "initialize":
        params = msg.get("params") or {}
        if params.get("clientInfo") != {"name": "agentic_sdlc_trust_check", "version": "1"} or params.get("capabilities") != {"experimentalApi": False}:
            bad_request(msg["id"], "initialize params")
            continue
        if MODE == "malformed":
            sys.stdout.write("this line is not json\n")
            sys.stdout.flush()
            send({"id": msg["id"]})
            continue
        reply(msg["id"], {"userAgent": "fake/0.0.0"})
    elif method == "initialized":
        if "id" in msg:
            bad_request(msg["id"], "initialized carries an id")
    elif method == "hooks/list":
        cwds = (msg.get("params") or {}).get("cwds")
        if not (isinstance(cwds, list) and len(cwds) == 1 and same_path(cwds[0], EXPECT_CWD)):
            bad_request(msg["id"], "hooks/list cwds")
            continue
        if MODE == "rpc-error":
            send({"id": msg["id"], "error": {"code": -32603, "message": "fake internal error"}})
            continue
        reply(msg["id"], {"data": [{"cwd": cwds[0], "errors": [], "warnings": [], "hooks": hooks_for_mode()}]})
    elif "id" in msg:
        bad_request(msg["id"], "unexpected method")

if MODE == "hang":
    time.sleep(3600)
'''


def _pid_running(pid: int) -> bool:
    if sys.platform == "win32":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        ).stdout
        return f'"{pid}"' in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class TrustCheckCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.state = self.tmp / "server"
        self.work = self.tmp / "work"
        self.state.mkdir()
        self.work.mkdir()
        self.mark = "fakemark" + str(os.getpid())
        fake = self.state / "fake_app_server.py"
        fake.write_text(FAKE_SERVER, encoding="utf-8", newline="\n")
        if sys.platform == "win32":
            self.launcher = self.state / "codex.cmd"
            self.launcher.write_text(f'@echo off\r\n"{sys.executable}" "{fake}" %*\r\n', encoding="utf-8", newline="")
        else:
            self.launcher = self.state / "codex"
            self.launcher.write_text(f"#!{sys.executable}\n" + FAKE_SERVER, encoding="utf-8", newline="\n")
            self.launcher.chmod(0o755)
            self.assertTrue(self.launcher.stat().st_mode & stat.S_IXUSR)
        self.before = sorted(p.name for p in self.state.iterdir())

    def tearDown(self):
        pid_file = self.state / PID_NAME
        if pid_file.is_file():
            pid = int(pid_file.read_text(encoding="utf-8"))
            if _pid_running(pid):
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
                else:
                    os.kill(pid, 9)
        self._tmp.cleanup()

    def run_cli(self, mode, *extra, codex=None, cwd=None, timeout="30", empty_path_dir=None, drop_env=()):
        env = dict(os.environ)
        if empty_path_dir is None:
            codex_path = Path(codex) if codex is not None else self.launcher
            # Fail closed: a CLI run may only ever target a launcher path inside this test's temp dir.
            if self.tmp not in codex_path.parents:
                raise AssertionError(f"refusing a --codex outside the fake temp dir: {codex_path}")
            codex_args = ["--codex", str(codex_path)]
        else:
            # The one run without --codex: PATH is stripped to a single empty dir inside this test's
            # temp dir, so the default `codex` lookup can never reach a real Codex binary.
            path_dir = Path(empty_path_dir)
            if codex is not None or self.tmp not in path_dir.parents or not path_dir.is_dir() or any(path_dir.iterdir()):
                raise AssertionError(f"refusing a run without --codex unless PATH is one empty temp dir: {path_dir}")
            env["PATH"] = str(path_dir)
            codex_args = []
        argv = [sys.executable, str(UNDER_TEST), *codex_args, "--cwd", str(cwd or self.work), "--timeout", timeout, *extra]
        env.update(
            FAKE_TRUST_MODE=mode,
            FAKE_TRUST_STATE_DIR=str(self.state),
            FAKE_TRUST_EXPECT_CWD=str(self.work),
            FAKE_TRUST_MARK=self.mark,
        )
        env.pop("AGENTIC_TRUST_CHECK_UNDER_TEST", None)
        # os.environ upper-cases names on Windows, so drop them case-insensitively.
        dropped = {name.upper() for name in drop_env}
        env = {key: value for key, value in env.items() if key.upper() not in dropped}
        started = time.monotonic()
        proc = subprocess.run(
            argv,
            cwd=str(self.work),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CLI_TIMEOUT_SECONDS,
        )
        self.elapsed = time.monotonic() - started
        return proc

    def five_lines(self, proc):
        lines = proc.stdout.splitlines()
        self.assertEqual(len(lines), 5, f"expected exactly five stdout lines, got {proc.stdout!r} stderr={proc.stderr!r}")
        parsed = {}
        for key, line in zip(LINE_KEYS, lines):
            self.assertTrue(line.startswith(key + "="), f"line {line!r} does not start with {key}=")
            parsed[key] = line[len(key) + 1 :]
        self.assertEqual(parsed["codex_hook_trust_plugin"], PLUGIN)
        self.assertTrue(parsed["codex_hook_trust_next_step"].strip(), "next_step text is empty")
        self.assert_no_leak(proc.stdout)
        return parsed

    def assert_no_leak(self, stdout):
        self.assertNotIn(self.mark, stdout, "stdout leaks a hook key, hash or sourcePath")
        self.assertNotIn(os.path.expanduser("~"), stdout, "stdout leaks the home path")
        self.assertNotIn(str(self.tmp), stdout, "stdout leaks the temp/cwd path")
        self.assertNotIn(self.tmp.name, stdout, "stdout leaks the temp dir name")

    def methods(self):
        return (self.state / LOG_NAME).read_text(encoding="utf-8").splitlines()

    def assert_error(self, proc, name):
        parsed = self.five_lines(proc)
        self.assertEqual(parsed["codex_hook_trust"], "error:" + name, proc.stdout)
        self.assertEqual(proc.returncode, 2, proc.stdout)
        return parsed


class TestTrustVerdicts(TrustCheckCase):
    def test_baseline_seven_untrusted_hooks_exit_1(self):
        # The verified 2026-09-14 WSL probe: 8 plugin hooks, 7 untrusted, nothing reported it.
        proc = self.run_cli("baseline")
        parsed = self.five_lines(proc)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertEqual(parsed["codex_hook_trust"], "untrusted")
        self.assertEqual(parsed["codex_hook_trust_counts"], "hooks:8 trusted:1 managed:0 untrusted:7 modified:0")
        events = parsed["codex_hook_trust_untrusted_events"].split(",")
        self.assertEqual(len(events), 7, parsed)
        for pair in events:
            self.assertRegex(pair, r"^[A-Za-z]+:untrusted$")
        self.assertEqual(sorted(events), sorted(["preToolUse:untrusted"] * 5 + ["stop:untrusted"] * 2))

    def test_trusted_exit_0_and_other_plugin_untrusted_hook_never_counts(self):
        proc = self.run_cli("trusted")
        parsed = self.five_lines(proc)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(parsed["codex_hook_trust"], "trusted")
        self.assertEqual(parsed["codex_hook_trust_counts"], "hooks:8 trusted:8 managed:0 untrusted:0 modified:0")
        self.assertEqual(parsed["codex_hook_trust_untrusted_events"], "none")

    def test_managed_hooks_exit_0(self):
        proc = self.run_cli("managed")
        parsed = self.five_lines(proc)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(parsed["codex_hook_trust"], "trusted")
        self.assertEqual(parsed["codex_hook_trust_counts"], "hooks:8 trusted:3 managed:5 untrusted:0 modified:0")
        self.assertEqual(parsed["codex_hook_trust_untrusted_events"], "none")

    def test_notifications_before_replies_are_ignored_exit_0(self):
        proc = self.run_cli("notify-first")
        parsed = self.five_lines(proc)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(parsed["codex_hook_trust"], "trusted")
        self.assertEqual(parsed["codex_hook_trust_counts"], "hooks:8 trusted:8 managed:0 untrusted:0 modified:0")

    def test_modified_hook_exit_1(self):
        proc = self.run_cli("modified")
        parsed = self.five_lines(proc)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertEqual(parsed["codex_hook_trust"], "untrusted")
        self.assertEqual(parsed["codex_hook_trust_counts"], "hooks:8 trusted:7 managed:0 untrusted:0 modified:1")
        self.assertEqual(parsed["codex_hook_trust_untrusted_events"], "stop:modified")

    def test_no_plugin_hooks_exit_2(self):
        proc = self.run_cli("no-hooks")
        parsed = self.five_lines(proc)
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertEqual(parsed["codex_hook_trust"], "no-hooks")
        self.assertEqual(parsed["codex_hook_trust_counts"], "hooks:0 trusted:0 managed:0 untrusted:0 modified:0")
        self.assertEqual(parsed["codex_hook_trust_untrusted_events"], "none")

    def test_plugin_option_counts_only_that_plugin(self):
        proc = self.run_cli("trusted", "--plugin", OTHER_PLUGIN)
        lines = proc.stdout.splitlines()
        self.assertEqual(len(lines), 5, proc.stdout)
        self.assertEqual(lines[0], "codex_hook_trust_plugin=" + OTHER_PLUGIN)
        self.assertEqual(lines[1], "codex_hook_trust_counts=hooks:1 trusted:0 managed:0 untrusted:1 modified:0")
        self.assertEqual(lines[3], "codex_hook_trust=untrusted")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assert_no_leak(proc.stdout)


class TestTrustErrors(TrustCheckCase):
    def test_rpc_error_exit_2(self):
        self.assert_error(self.run_cli("rpc-error"), "rpc_error")

    def test_malformed_response_exit_2(self):
        self.assert_error(self.run_cli("malformed"), "malformed_response")

    def test_server_exiting_before_reply_exit_2(self):
        self.assert_error(self.run_cli("exit-early"), "server_exited")

    def test_hang_times_out_and_kills_the_server_process_tree(self):
        proc = self.run_cli("hang", timeout="2")
        parsed = self.assert_error(proc, "timeout")
        self.assertEqual(parsed["codex_hook_trust_counts"], "hooks:0 trusted:0 managed:0 untrusted:0 modified:0")
        self.assertLess(self.elapsed, 2 + 10, "the check did not return within the timeout plus 10 seconds")
        pid_file = self.state / PID_NAME
        self.assertTrue(pid_file.is_file(), "the fake server never recorded its PID")
        pid = int(pid_file.read_text(encoding="utf-8"))
        self.assertFalse(_pid_running(pid), f"fake app-server PID {pid} is still running after the timeout")

    def test_missing_codex_binary_exit_2(self):
        proc = self.run_cli("trusted", codex=str(self.tmp / "no-such-codex"))
        self.assert_error(proc, "codex_not_found")
        self.assertFalse((self.state / PID_NAME).exists())

    def test_missing_cwd_exit_2(self):
        proc = self.run_cli("trusted", cwd=str(self.tmp / "no-such-dir"))
        self.assert_error(proc, "cwd_not_found")
        self.assertFalse((self.state / PID_NAME).exists())

    def test_usage_error_prints_usage_to_stderr_and_no_block(self):
        proc = self.run_cli("trusted", timeout="abc")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, "")
        self.assertIn("usage:", proc.stderr)
        self.assertFalse((self.state / PID_NAME).exists())

    def test_non_ascii_plugin_is_a_usage_error_not_an_encoding_crash(self):
        # Redirected stdout uses the locale code page (cp1252 on Windows) without UTF-8 mode.
        plugin = "\u65e5\u672c@x"
        proc = self.run_cli("trusted", "--plugin", plugin, drop_env=("PYTHONUTF8", "PYTHONIOENCODING"))
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertEqual(proc.stdout, "")
        self.assertIn("usage:", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertFalse((self.state / PID_NAME).exists())

    def test_deeply_nested_server_line_is_malformed_response_exit_2(self):
        proc = self.run_cli("deep-nest")
        self.assert_error(proc, "malformed_response")
        self.assertNotIn("Traceback", proc.stderr)

    @unittest.skipUnless(sys.platform == "win32", "Windows searches the current directory before PATH")
    def test_default_codex_is_never_taken_from_the_current_directory(self):
        marker = self.work / "cwd-codex-ran.txt"
        planted = self.work / "codex.cmd"
        planted.write_text(f'@echo off\r\ntype nul > "{marker}"\r\n', encoding="utf-8", newline="")
        empty = self.tmp / "empty-path"
        empty.mkdir()
        # The Claude Code shell sets this variable to 1, which would hide the current-directory lookup.
        proc = self.run_cli("trusted", empty_path_dir=empty, drop_env=("NoDefaultCurrentDirectoryInExePath",))
        self.assert_error(proc, "codex_not_found")
        self.assertFalse(marker.exists(), "a codex.cmd from the current directory was executed")
        self.assertFalse((self.state / PID_NAME).exists())


class TestTerminateTree(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "taskkill is the Windows tree-kill path")
    def test_taskkill_is_started_by_absolute_system32_path(self):
        spec = importlib.util.spec_from_file_location("check_codex_hook_trust_under_test", UNDER_TEST)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        expected = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "taskkill.exe")
        calls = []

        class FakeProc:
            pid = 424242

            def poll(self):
                return None

            def kill(self):
                raise AssertionError("kill fallback used instead of taskkill")

            def wait(self, timeout=None):
                return 0

        def fake_run(argv, **kwargs):
            # Fail closed: only the exact taskkill argv is accepted; nothing reaches a real process.
            if argv != [expected, "/T", "/F", "/PID", "424242"]:
                raise AssertionError(f"unexpected subprocess argv: {argv!r}")
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0)

        original = module.subprocess.run
        module.subprocess.run = fake_run
        try:
            module._terminate_tree(FakeProc())
        finally:
            module.subprocess.run = original
        self.assertEqual(len(calls), 1)

    def _posix_module(self):
        """The module with its POSIX tree-kill branch selected, whatever the host platform is."""
        spec = importlib.util.spec_from_file_location("check_codex_hook_trust_posix", UNDER_TEST)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        patches = [
            mock.patch.object(module.sys, "platform", "linux"),
            mock.patch.object(module.signal, "SIGKILL", 9, create=True),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return module

    def test_posix_branch_never_signals_a_reaped_child(self):
        # SEC-9: query_hooks reaches _terminate_tree through its `finally:` on the SUCCESS path, after
        # proc.wait() already reaped the child. The pid is then free for kernel reuse, so killpg would
        # SIGKILL whatever session leader inherited it. The win32 branch already guards with poll().
        module = self._posix_module()
        killed = []

        class ReapedProc:
            pid = 515151

            def poll(self):
                return 0  # already reaped by query_hooks' proc.wait()

            def kill(self):
                killed.append("kill")

            def wait(self, timeout=None):
                return 0

        def refuse(pid, sig):
            killed.append((pid, sig))
            raise AssertionError(f"killpg on a reaped pid: {pid!r}")

        with mock.patch.object(module.os, "killpg", refuse, create=True):
            module._terminate_tree(ReapedProc())
        self.assertEqual(killed, [], "a reaped child's process group was signalled")

    def test_posix_branch_still_kills_a_live_child_group(self):
        # Control: the guard must not turn the tree kill off for a child that is still running.
        module = self._posix_module()
        calls = []

        class LiveProc:
            pid = 626262

            def poll(self):
                return None

            def kill(self):
                calls.append("kill")

            def wait(self, timeout=None):
                return 0

        with mock.patch.object(module.os, "killpg", lambda pid, sig: calls.append((pid, sig)), create=True):
            module._terminate_tree(LiveProc())
        self.assertEqual(calls, [(626262, 9)])


class TestReadOnlyProtocol(TrustCheckCase):
    def test_sends_exactly_initialize_initialized_hooks_list(self):
        proc = self.run_cli("trusted")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.methods(), ["initialize", "initialized", "hooks/list"])

    def test_writes_no_file_beyond_the_fake_log_and_pid(self):
        for mode in ("trusted", "baseline", "modified"):
            with self.subTest(mode=mode):
                for name in (LOG_NAME, PID_NAME):
                    (self.state / name).unlink(missing_ok=True)
                self.run_cli(mode)
                after = sorted(p.name for p in self.state.iterdir())
                self.assertEqual(after, sorted(self.before + [LOG_NAME, PID_NAME]))
                self.assertEqual(list(self.work.iterdir()), [], "the check created a file in --cwd")
                self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["server", "work"])

    def test_stdout_never_leaks_key_hash_source_path_or_home(self):
        for mode in ("baseline", "trusted", "modified", "managed"):
            with self.subTest(mode=mode):
                proc = self.run_cli(mode)
                self.five_lines(proc)
                self.assertIsNone(re.search(r"[\\/]", proc.stdout.split("codex_hook_trust_next_step=")[0]), proc.stdout)

    def test_source_has_one_accepted_literal_and_no_write_method(self):
        text = UNDER_TEST.read_text(encoding="utf-8")
        self.assertNotIn("config/batchWrite", text)
        if "AGENTIC_TRUST_CHECK_UNDER_TEST" not in os.environ:
            self.assertEqual(text.count("ACCEPTED = ('trusted', 'managed')"), 1)


if __name__ == "__main__":
    unittest.main()
