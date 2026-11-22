"""Google Antigravity (agy) hook adapter: `.antigravity-plugin/hooks.json` and `hooks/agy-launch.mjs`.

The replay payloads in tests/fixtures/agy/ are the hook stdin objects of a live agy 1.5.14 session
(2026-11-21), sanitized: ids are fixed placeholders, the workspace is /workspace/project and the agy
brain folder is `<agy-brain>`. These checks do not start agy; a passing replay is not a model turn.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import unittest


REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "agy"
LAUNCHER = REPO / "hooks" / "agy-launch.mjs"
WIRE = REPO / ".antigravity-plugin" / "hooks.json"
NODE = shutil.which("node")
FIXTURE_NAMES = ("session-start", "pre-run-command", "post-run-command", "pre-write-file", "post-write-file",
                 "pre-edit-file", "post-edit-file", "stop")
# The argument shapes of the other tools that can run commands or carry text, from a capture hook
# in a throwaway workspace (agy 1.5.14, 2026-11-22), sanitized the same way.
OTHER_TOOL_FIXTURES = {
    "pre-manage-task": "manage_task", "pre-send-message": "send_message", "pre-define-subagent": "define_subagent",
    "pre-run-workflow": "run_workflow", "pre-schedule": "schedule", "pre-swarm": "swarm",
    "pre-ask-question": "ask_question", "pre-search-web": "search_web", "pre-invoke-subagent": "invoke_subagent",
}
COMMAND_GUARDS = ("scan-commit.mjs", "destructive-command-guard.mjs", "branch-guard.mjs")
ARG_SCAN = "scan-tool-args.mjs"
SECRET = "ghp_" + "a1B2" * 9


def fixture(name, workspace=None):
    text = (FIXTURES / (name + ".json")).read_text(encoding="utf-8")
    payload = json.loads(text)
    if workspace is not None:
        payload = json.loads(json.dumps(payload).replace("/workspace/project", Path(workspace).as_posix()))
    return payload


def git_repo(root):
    root.mkdir(parents=True, exist_ok=True)
    for args in (["init", "-q", "-b", "feature/x"], ["config", "user.email", "t@example.invalid"],
                 ["config", "user.name", "t"], ["config", "commit.gpgsign", "false"]):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    (root / "README.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True, capture_output=True)
    return root


def launch(event, handler, payload, *, launcher=LAUNCHER, env=None, raw=None, extra=(), cwd=None):
    run_env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTIC_")}
    run_env.update(env or {})
    proc = subprocess.run(
        [NODE, str(launcher), "--event", event, "--handler", handler, *extra],
        input=raw if raw is not None else json.dumps(payload),
        text=True, encoding="utf-8", capture_output=True, env=run_env,
        cwd=str(cwd or launcher.parent.parent), timeout=60,
    )
    return proc


def answer(proc):
    """The launcher's stdout must be exactly one JSON object and its exit code 0."""
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    value = json.loads(proc.stdout)
    assert isinstance(value, dict), proc.stdout
    return value


@unittest.skipUnless(NODE, "node is required")
class AgyReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = git_repo(Path(self.tmp.name) / "project")

    def test_destructive_command_is_denied(self):
        payload = fixture("pre-run-command", self.work)
        payload["toolCall"]["args"]["CommandLine"] = "git reset --hard"
        out = answer(launch("PreToolUse", "destructive-command-guard.mjs", payload))
        self.assertEqual(out["decision"], "deny")
        self.assertIn("reset --hard", out["reason"])
        self.assertEqual(set(out), {"decision", "reason"})

    def test_captured_benign_command_is_allowed_by_every_command_guard(self):
        payload = fixture("pre-run-command", self.work)
        for handler in COMMAND_GUARDS:
            with self.subTest(handler=handler):
                self.assertEqual(answer(launch("PreToolUse", handler, payload)), {"decision": "allow"})

    def test_payload_cwd_selects_the_repository_when_no_args_cwd_is_sent(self):
        # run_command carries CommandLine, WaitMsBeforeAsync and toolSummary in the live capture
        # (agy 1.5.14, 2026-11-21); with no `Cwd` argument the payload `cwd` decides.
        protected = git_repo(Path(self.tmp.name) / "protected")
        subprocess.run(["git", "checkout", "-q", "-b", "main"], cwd=protected, check=True, capture_output=True)
        payload = fixture("pre-run-command", protected)
        payload["toolCall"]["args"]["CommandLine"] = "git commit -q --allow-empty -m x"
        env = {"AGENTIC_BRANCH_GUARD_BLOCK": "true"}
        out = answer(launch("PreToolUse", "branch-guard.mjs", payload, env=env))
        self.assertEqual(out["decision"], "deny")
        self.assertIn("main", out["reason"])
        payload = fixture("pre-run-command", self.work)
        payload["toolCall"]["args"]["CommandLine"] = "git commit -q --allow-empty -m x"
        self.assertEqual(answer(launch("PreToolUse", "branch-guard.mjs", payload, env=env)), {"decision": "allow"})

    def test_an_args_cwd_is_the_folder_the_guard_checks(self):
        # The web docs list a `Cwd` argument for run_command. When one is sent, the command runs
        # there, so the guard must check that folder, never only the payload `cwd`.
        protected = git_repo(Path(self.tmp.name) / "protected")
        subprocess.run(["git", "checkout", "-q", "-b", "main"], cwd=protected, check=True, capture_output=True)
        env = {"AGENTIC_BRANCH_GUARD_BLOCK": "true"}
        payload = fixture("pre-run-command", self.work)
        payload["toolCall"]["args"]["Cwd"] = str(protected)
        payload["toolCall"]["args"]["CommandLine"] = "git commit -q --allow-empty -m x"
        out = answer(launch("PreToolUse", "branch-guard.mjs", payload, env=env))
        self.assertEqual(out["decision"], "deny")
        self.assertIn("main", out["reason"])
        # A relative `Cwd` resolves against the payload `cwd`, where agy runs commands by default.
        payload = fixture("pre-run-command", Path(self.tmp.name))
        payload["toolCall"]["args"]["Cwd"] = "protected"
        payload["toolCall"]["args"]["CommandLine"] = "git commit -q --allow-empty -m x"
        out = answer(launch("PreToolUse", "branch-guard.mjs", payload, env=env))
        self.assertEqual(out["decision"], "deny")
        self.assertIn("main", out["reason"])

    def test_an_unusable_args_cwd_denies(self):
        # A `Cwd` that is not a string or names no folder cannot be checked, so the call is denied
        # instead of being judged in another folder.
        for value in (7, ["x"], None, str(Path(self.tmp.name) / "missing")):
            with self.subTest(cwd=value):
                payload = fixture("pre-run-command", self.work)
                payload["toolCall"]["args"]["Cwd"] = value
                payload["toolCall"]["args"]["CommandLine"] = "echo hi"
                for handler in COMMAND_GUARDS:
                    out = answer(launch("PreToolUse", handler, payload))
                    self.assertEqual(out["decision"], "deny", (handler, out))

    def test_payload_text_is_never_run_by_a_shell(self):
        marker = Path(self.tmp.name) / "pwned"
        payload = fixture("pre-run-command", self.work)
        payload["toolCall"]["args"]["CommandLine"] = f"echo $(touch {marker}) `touch {marker}`; touch {marker}"
        for handler in COMMAND_GUARDS:
            answer(launch("PreToolUse", handler, payload))
        self.assertFalse(marker.exists())

    def test_write_and_edit_with_a_secret_are_denied(self):
        # The shared write scanner only warns; on agy, as on Cursor, a finding stops the write,
        # because an allow would auto-approve writing the secret.
        secret = "ghp_" + "a1B2" * 9
        write = fixture("pre-write-file", self.work)
        write["toolCall"]["args"]["Content"] = f'token = "{secret}"\n'
        edit = fixture("pre-edit-file", self.work)
        edit["toolCall"]["args"]["Replacement"] = f'token = "{secret}"'
        for name, payload in (("write_file", write), ("edit_file", edit)):
            with self.subTest(tool=name):
                proc = launch("PreToolUse", "scan-write.mjs", payload)
                out = answer(proc)
                self.assertEqual(out["decision"], "deny")
                self.assertIn("secret", out["reason"].lower())
                self.assertNotIn(secret, proc.stdout + proc.stderr)

    def test_a_shell_guard_warning_asks_instead_of_approving(self):
        # branch-guard only warns on a protected branch unless AGENTIC_BRANCH_GUARD_BLOCK is set. An
        # allow would auto-approve the call; ask leaves the decision to the user, as on Cursor.
        protected = git_repo(Path(self.tmp.name) / "protected")
        subprocess.run(["git", "checkout", "-q", "-b", "main"], cwd=protected, check=True, capture_output=True)
        payload = fixture("pre-run-command", protected)
        payload["toolCall"]["args"]["CommandLine"] = "git commit -q --allow-empty -m x"
        out = answer(launch("PreToolUse", "branch-guard.mjs", payload))
        self.assertEqual(out["decision"], "ask")
        self.assertIn("main", out["reason"])

    def test_captured_write_and_edit_are_allowed_silently(self):
        for name in ("pre-write-file", "pre-edit-file"):
            with self.subTest(fixture=name):
                out = answer(launch("PreToolUse", "scan-write.mjs", fixture(name, self.work)))
                self.assertEqual(out, {"decision": "allow"})

    def test_a_handler_for_another_tool_allows_without_running(self):
        out = answer(launch("PreToolUse", "scan-write.mjs", fixture("pre-run-command", self.work)))
        self.assertEqual(out, {"decision": "allow"})
        payload = fixture("pre-write-file", self.work)
        out = answer(launch("PreToolUse", "destructive-command-guard.mjs", payload))
        self.assertEqual(out, {"decision": "allow"})

    def test_session_start_injects_the_bootstrap_as_a_system_message(self):
        out = answer(launch("SessionStart", "session-start.mjs", fixture("session-start", self.work)))
        self.assertEqual(list(out), ["injectSteps"])
        steps = out["injectSteps"]
        self.assertEqual(len(steps), 1)
        text = steps[0]["systemMessage"]["systemMessage"]
        self.assertIn("AGENTIC_SDLC_BOOTSTRAP", text)
        self.assertIn("feature/x", text)
        self.assertIn("Antigravity adapter", text)

    def block_env(self):
        # worktree-scan.mjs dedups findings per session in a state file; keep each test's own.
        return {"AGENTIC_WORKTREE_SCAN_BLOCK": "true",
                "AGENTIC_WORKTREE_SCAN_STATE": str(Path(self.tmp.name) / "scan-state.json")}

    def test_stop_continues_only_when_blocking_is_set_and_a_secret_is_found(self):
        secret = "ghp_" + "a1B2" * 9
        (self.work / "leak.py").write_text(f'token = "{secret}"\n', encoding="utf-8")
        payload = fixture("stop", self.work)
        blocked = launch("Stop", "worktree-scan.mjs", payload, env=self.block_env())
        out = answer(blocked)
        self.assertEqual(out["decision"], "continue")
        self.assertIn("secret", out["reason"].lower())
        self.assertNotIn(secret, blocked.stdout)
        self.assertEqual(answer(launch("Stop", "worktree-scan.mjs", payload)), {})
        payload["continuationActive"] = True
        self.assertEqual(answer(launch("Stop", "worktree-scan.mjs", payload, env=self.block_env())), {})

    def test_stop_findings_are_deduplicated_per_conversation(self):
        # The conversation id is the scan's session key: one conversation is told once, and another
        # conversation is told again (without it every agy conversation shared one key).
        (self.work / "leak.py").write_text('token = "ghp_' + "a1B2" * 9 + '"\n', encoding="utf-8")
        first = fixture("stop", self.work)
        first["conversationId"] = "conversation-one"
        second = dict(first, conversationId="conversation-two")
        env = dict(self.block_env())
        env.pop("AGENTIC_WORKTREE_SCAN_STATE")
        # The scan keeps its default state under Node's os.tmpdir(), which reads TMPDIR on POSIX but
        # TEMP/TMP on Windows. All three point at this test's folder, or a state file left by an
        # earlier run of the suite in the same job would make the first call a repeat.
        scan_tmp = Path(self.tmp.name) / "scan-tmp"
        scan_tmp.mkdir()
        for key in ("TMPDIR", "TEMP", "TMP"):
            env[key] = str(scan_tmp)
        self.assertEqual(answer(launch("Stop", "worktree-scan.mjs", first, env=env))["decision"], "continue")
        self.assertTrue((scan_tmp / "agentic-sdlc" / "worktree-scan-conversation-one.json").is_file())
        self.assertEqual(answer(launch("Stop", "worktree-scan.mjs", first, env=env)), {})
        self.assertEqual(answer(launch("Stop", "worktree-scan.mjs", second, env=env))["decision"], "continue")

    def test_clean_stop_allows_the_stop(self):
        self.assertEqual(answer(launch("Stop", "worktree-scan.mjs", fixture("stop", self.work),
                                       env=self.block_env())), {})


@unittest.skipUnless(NODE, "node is required")
class AgyBadPayloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = git_repo(Path(self.tmp.name) / "project")

    def test_unreadable_pretooluse_input_denies(self):
        bad = fixture("pre-run-command", self.work)
        no_call = dict(bad)
        no_call.pop("toolCall")
        args_list = json.loads(json.dumps(bad))
        args_list["toolCall"]["args"] = ["git", "reset"]
        for label, kwargs in (("invalid json", {"raw": "{not json"}), ("array", {"raw": "[]"}),
                              ("no toolCall", {"payload": no_call}), ("args not object", {"payload": args_list})):
            with self.subTest(case=label):
                out = answer(launch("PreToolUse", "destructive-command-guard.mjs", kwargs.get("payload"),
                                    raw=kwargs.get("raw")))
                self.assertEqual(out["decision"], "deny")
                self.assertTrue(out["reason"].startswith("agentic-sdlc:"))

    def test_a_missing_or_non_string_tool_argument_denies(self):
        # The guards cannot check a command or a write whose content is not a string, so it must
        # not reach them as an empty value and be allowed.
        cases = []
        for value in (["git", "reset", "--hard"], None, 7):
            payload = fixture("pre-run-command", self.work)
            payload["toolCall"]["args"]["CommandLine"] = value
            cases.append(("destructive-command-guard.mjs", payload))
        missing = fixture("pre-run-command", self.work)
        del missing["toolCall"]["args"]["CommandLine"]
        cases.append(("branch-guard.mjs", missing))
        for name, key, value in (("pre-write-file", "Content", ["x"]), ("pre-write-file", "Path", None),
                                 ("pre-edit-file", "Replacement", {"a": 1}), ("pre-edit-file", "Path", 3)):
            payload = fixture(name, self.work)
            payload["toolCall"]["args"][key] = value
            cases.append(("scan-write.mjs", payload))
        for name, key in (("pre-write-file", "Content"), ("pre-edit-file", "Replacement")):
            payload = fixture(name, self.work)
            del payload["toolCall"]["args"][key]
            cases.append(("scan-write.mjs", payload))
        for handler, payload in cases:
            with self.subTest(handler=handler, args=payload["toolCall"]["args"]):
                out = answer(launch("PreToolUse", handler, payload))
                self.assertEqual(out["decision"], "deny")
                self.assertTrue(out["reason"].startswith("agentic-sdlc:"))
                self.assertIn(handler, out["reason"])

    def test_unreadable_input_on_other_events_is_an_empty_answer(self):
        for event, handler in (("SessionStart", "session-start.mjs"), ("Stop", "worktree-scan.mjs")):
            with self.subTest(event=event):
                self.assertEqual(answer(launch(event, handler, None, raw="{not json")), {})

    def test_unknown_tool_and_empty_command_are_allowed(self):
        unknown = fixture("pre-run-command", self.work)
        unknown["toolCall"]["name"] = "send_message"
        empty = fixture("pre-run-command", self.work)
        empty["toolCall"]["args"]["CommandLine"] = ""
        for payload in (unknown, empty):
            self.assertEqual(answer(launch("PreToolUse", "destructive-command-guard.mjs", payload)),
                             {"decision": "allow"})

    def test_a_handler_outside_the_allowlist_is_never_started(self):
        out = answer(launch("PreToolUse", "../tests/x.mjs", fixture("pre-run-command", self.work)))
        self.assertEqual(out["decision"], "deny")
        self.assertEqual(answer(launch("SessionStart", "flow-order-guard.mjs", fixture("session-start"))), {})

    def test_unknown_event_is_an_empty_answer(self):
        self.assertEqual(answer(launch("PostToolUse", "scan-write.mjs", fixture("post-write-file", self.work))), {})

    def test_a_vanished_project_folder_still_gets_the_guards_own_decision(self):
        # The handler is spawned from the launcher's folder when the project folder is gone, so the
        # guard still answers: its own deny for a destructive command, and an allow for a harmless
        # one (a failed spawn would deny everything with the launcher's "could not check" reason).
        payload = fixture("pre-run-command", str(Path(self.tmp.name) / "gone"))
        payload["toolCall"]["args"]["CommandLine"] = "git reset --hard"
        out = answer(launch("PreToolUse", "destructive-command-guard.mjs", payload))
        self.assertEqual(out["decision"], "deny")
        self.assertIn("reset --hard", out["reason"])
        self.assertNotIn("could not check", out["reason"])
        payload["toolCall"]["args"]["CommandLine"] = "ls"
        self.assertEqual(answer(launch("PreToolUse", "destructive-command-guard.mjs", payload)), {"decision": "allow"})

    def test_a_tool_call_with_no_project_folder_is_denied(self):
        # With neither a payload `cwd` nor a `workspacePaths[0]` the guards would judge the plugin's
        # own folder, so the PreToolUse call is denied instead.
        for drop in (("cwd", "workspacePaths"), ("cwd",)):
            with self.subTest(dropped=drop):
                payload = fixture("pre-run-command", self.work)
                for key in drop:
                    payload.pop(key, None)
                if drop == ("cwd",):
                    payload["workspacePaths"] = [7]
                for handler in COMMAND_GUARDS:
                    out = answer(launch("PreToolUse", handler, payload))
                    self.assertEqual(out["decision"], "deny", (handler, out))
        payload = fixture("pre-run-command", self.work)
        payload.pop("cwd")
        payload["workspacePaths"] = [str(self.work)]
        self.assertEqual(answer(launch("PreToolUse", "destructive-command-guard.mjs", payload)), {"decision": "allow"})


@unittest.skipUnless(NODE, "node is required")
class AgyFailClosedTests(unittest.TestCase):
    """A stand-in handler with an allowed name sits next to a copy of the launcher."""

    STANDINS = {
        "crash": "process.stderr.write('boom'); process.exit(3);\n",
        "non-json": "process.stdout.write('this is not json{');\n",
        "array": "process.stdout.write('[1]');\n",
        "hang": "setInterval(() => {}, 1000);\n",
    }

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.hooks = Path(self.tmp.name) / "pkg" / "hooks"
        self.hooks.mkdir(parents=True)
        shutil.copy2(LAUNCHER, self.hooks / "agy-launch.mjs")
        self.work = git_repo(Path(self.tmp.name) / "project")

    def run_standin(self, handler, body, event, payload, env=None):
        (self.hooks / handler).write_text(body, encoding="utf-8")
        return launch(event, handler, payload, launcher=self.hooks / "agy-launch.mjs",
                      extra=("--handler-timeout", "2"), env=env)

    def test_pretooluse_guard_failures_deny(self):
        payload = fixture("pre-run-command", self.work)
        for label, body in self.STANDINS.items():
            with self.subTest(case=label):
                out = answer(self.run_standin("destructive-command-guard.mjs", body, "PreToolUse", payload))
                self.assertEqual(out["decision"], "deny")
                self.assertIn("destructive-command-guard.mjs", out["reason"])

    def test_write_guard_failure_denies(self):
        out = answer(self.run_standin("scan-write.mjs", self.STANDINS["crash"], "PreToolUse",
                                      fixture("pre-write-file", self.work)))
        self.assertEqual(out["decision"], "deny")

    def test_argument_scan_failure_denies(self):
        payload = fixture("pre-send-message", self.work)
        for label, body in self.STANDINS.items():
            with self.subTest(case=label):
                out = answer(self.run_standin(ARG_SCAN, body, "PreToolUse", payload))
                self.assertEqual(out["decision"], "deny")
                self.assertIn(ARG_SCAN, out["reason"])

    def test_empty_guard_output_allows(self):
        out = answer(self.run_standin("branch-guard.mjs", "", "PreToolUse", fixture("pre-run-command", self.work)))
        self.assertEqual(out, {"decision": "allow"})

    def test_session_start_and_stop_failures_are_empty_answers(self):
        for label, body in self.STANDINS.items():
            for event, handler, name in (("SessionStart", "session-start.mjs", "session-start"),
                                         ("Stop", "worktree-scan.mjs", "stop")):
                with self.subTest(case=label, event=event):
                    out = answer(self.run_standin(handler, body, event, fixture(name, self.work)))
                    self.assertEqual(out, {})

    def test_deny_without_a_reason_still_names_the_guard(self):
        body = ("process.stdout.write(JSON.stringify({hookSpecificOutput: "
                "{hookEventName: 'PreToolUse', permissionDecision: 'deny'}}));\n")
        out = answer(self.run_standin("branch-guard.mjs", body, "PreToolUse", fixture("pre-run-command", self.work)))
        self.assertEqual(out["decision"], "deny")
        self.assertIn("branch-guard.mjs", out["reason"])

    def test_stop_block_without_the_flag_is_not_a_continue(self):
        body = "process.stdout.write(JSON.stringify({decision: 'block', reason: 'r'}));\n"
        out = answer(self.run_standin("worktree-scan.mjs", body, "Stop", fixture("stop", self.work)))
        self.assertEqual(out, {})

    def test_a_notice_only_stop_answer_is_not_a_continue_even_when_blocking(self):
        # worktree-scan prints a non-block systemMessage for notices (a diff over the limit, files not
        # scanned); only a block may keep agy going.
        body = "process.stdout.write(JSON.stringify({systemMessage: 'notice'}));\n"
        env = {"AGENTIC_WORKTREE_SCAN_BLOCK": "true"}
        out = answer(self.run_standin("worktree-scan.mjs", body, "Stop", fixture("stop", self.work), env=env))
        self.assertEqual(out, {})

    def test_stop_never_continues_twice_even_if_the_handler_blocks_again(self):
        # The launcher's own loop guard: a handler that ignores stop_hook_active still cannot keep
        # agy going while continuationActive is true.
        body = "process.stdout.write(JSON.stringify({decision: 'block', reason: 'again'}));\n"
        env = {"AGENTIC_WORKTREE_SCAN_BLOCK": "true"}
        payload = fixture("stop", self.work)
        self.assertEqual(answer(self.run_standin("worktree-scan.mjs", body, "Stop", payload, env=env)),
                         {"decision": "continue", "reason": "again"})
        payload["continuationActive"] = True
        self.assertEqual(answer(self.run_standin("worktree-scan.mjs", body, "Stop", payload, env=env)), {})

    def test_a_legacy_block_decision_denies_the_tool_call(self):
        body = "process.stdout.write(JSON.stringify({decision: 'block', reason: 'blocked by stand-in'}));\n"
        out = answer(self.run_standin("branch-guard.mjs", body, "PreToolUse", fixture("pre-run-command", self.work)))
        self.assertEqual(out, {"decision": "deny", "reason": "blocked by stand-in"})

    def test_a_no_opinion_answer_is_an_explicit_allow_never_an_empty_object(self):
        # agy 1.5.14 denied a run_command whose PreToolUse hook printed `{}` ("tool call denied by
        # pre-tool hook", probe 2026-11-21), so `{}` is not a neutral answer there.
        for body in ("", "process.stdout.write('{}');\n"):
            with self.subTest(body=body):
                out = answer(self.run_standin("branch-guard.mjs", body, "PreToolUse",
                                              fixture("pre-run-command", self.work)))
                self.assertEqual(out, {"decision": "allow"})


@unittest.skipUnless(NODE, "node is required")
class AgyEveryToolTests(unittest.TestCase):
    """AC3: every agy tool reaches a guard: commands, writes, and a secret scan of all other arguments."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = git_repo(Path(self.tmp.name) / "project")

    def test_every_captured_other_tool_passes_the_argument_scan(self):
        for name, tool in OTHER_TOOL_FIXTURES.items():
            with self.subTest(fixture=name):
                payload = fixture(name, self.work)
                self.assertEqual(payload["toolCall"]["name"], tool)
                # manage_task and run_workflow are command tools: the argument scan leaves them alone,
                # but it never answers `allow` for run_workflow or terminal input (agy applies the
                # strictest answer of the groups, probe 2026-11-22, so this keeps the ask).
                out = answer(launch("PreToolUse", ARG_SCAN, payload))
                if tool == "run_workflow":
                    self.assertEqual(out["decision"], "ask")
                    self.assertIn("run_workflow", out["reason"])
                elif tool == "manage_task":
                    self.assertEqual(out["decision"], "ask")
                    self.assertIn("terminal task", out["reason"])
                else:
                    self.assertEqual(out, {"decision": "allow"})

    def test_no_handler_answers_allow_for_run_workflow(self):
        payload = fixture("pre-run-workflow", self.work)
        for handler in (*COMMAND_GUARDS, ARG_SCAN, "scan-write.mjs"):
            with self.subTest(handler=handler):
                self.assertEqual(answer(launch("PreToolUse", handler, payload))["decision"], "ask")

    def test_terminal_input_with_no_objection_asks_because_its_folder_is_unknown(self):
        # manage_task send_input types into a terminal task that may run in another folder (its own
        # Cwd, or a `cd` inside the shell), which the folder-sensitive guards cannot see. With nothing
        # to report, no handler answers allow for it; a guard's own deny still wins.
        payload = fixture("pre-manage-task", self.work)
        payload["toolCall"]["args"]["Input"] = "ls\n"
        for handler in (*COMMAND_GUARDS, ARG_SCAN, "scan-write.mjs"):
            with self.subTest(handler=handler):
                out = answer(launch("PreToolUse", handler, payload))
                self.assertEqual(out["decision"], "ask")
                self.assertIn("folder", out["reason"])
        payload["toolCall"]["args"]["Input"] = "git reset --hard\n"
        self.assertEqual(answer(launch("PreToolUse", "destructive-command-guard.mjs", payload))["decision"], "deny")
        # An action that types nothing (status, kill) runs no command and is not asked about.
        status = fixture("pre-manage-task", self.work)
        status["toolCall"]["args"].pop("Input", None)
        status["toolCall"]["args"]["Action"] = "status"
        self.assertEqual(answer(launch("PreToolUse", "branch-guard.mjs", status))["decision"], "allow")

    def test_a_secret_in_any_other_tool_argument_is_denied_without_echoing_it(self):
        cases = {
            "pre-send-message": ("Message", f"here is the key {SECRET}"),
            "pre-invoke-subagent": ("Prompt", f"Use token {SECRET} to call the API."),
            "pre-define-subagent": ("SystemPrompt", f"GITHUB_TOKEN={SECRET}"),
            "pre-schedule": ("Prompt", f"later: {SECRET}"),
            "pre-swarm": ("brief", f"x {SECRET}"),
            "pre-search-web": ("query", SECRET),
        }
        for name, (key, value) in cases.items():
            with self.subTest(fixture=name):
                payload = fixture(name, self.work)
                payload["toolCall"]["args"][key] = value
                proc = launch("PreToolUse", ARG_SCAN, payload)
                out = answer(proc)
                self.assertEqual(out["decision"], "deny")
                self.assertIn("secret", out["reason"].lower())
                self.assertIn("github-token", out["reason"])
                self.assertIn(OTHER_TOOL_FIXTURES[name], out["reason"])
                self.assertNotIn(SECRET, proc.stdout + proc.stderr)
                self.assertNotIn(SECRET[4:20], proc.stdout + proc.stderr)

    def test_a_secret_object_key_is_denied_whatever_its_value_and_never_echoed(self):
        for value in ("v", {}, {"inner": 1}, [], 1, True, None):
            with self.subTest(value=value):
                payload = fixture("pre-send-message", self.work)
                payload["toolCall"]["args"]["Extra"] = {SECRET: value}
                proc = launch("PreToolUse", ARG_SCAN, payload)
                out = answer(proc)
                self.assertEqual(out["decision"], "deny", proc.stdout)
                self.assertIn("github-token", out["reason"])
                self.assertNotIn(SECRET, proc.stdout + proc.stderr)
                self.assertNotIn(SECRET[4:20], proc.stdout + proc.stderr)
        # A secret value under a secret key: the reported path masks the key too.
        payload = fixture("pre-send-message", self.work)
        payload["toolCall"]["args"]["Extra"] = {SECRET: {"deeper": f"x {SECRET}"}}
        proc = launch("PreToolUse", ARG_SCAN, payload)
        self.assertEqual(answer(proc)["decision"], "deny")
        self.assertNotIn(SECRET[4:20], proc.stdout + proc.stderr)

    def test_nested_values_json_in_a_string_and_unknown_tools_are_scanned(self):
        nested = fixture("pre-ask-question", self.work)
        nested["toolCall"]["args"]["questions"][0]["options"].append(f"use {SECRET}")
        as_json = fixture("pre-send-message", self.work)
        as_json["toolCall"]["args"]["Message"] = json.dumps({"auth": {"api_key": "q7Wm4" + "Zr9Lp2Xv8Nt5Kc3"}})
        mcp = fixture("pre-send-message", self.work)
        mcp["toolCall"] = {"id": "call_201", "name": "call_mcp_tool", "args": {
            "ServerName": "other_server", "ToolName": "post", "Arguments": {"body": {"text": f"x {SECRET}"}}}}
        future = fixture("pre-send-message", self.work)
        future["toolCall"] = {"id": "call_202", "name": "some_future_tool", "args": {"x": [1, {"y": SECRET}]}}
        aws = fixture("pre-send-message", self.work)
        aws["toolCall"]["args"]["Message"] = "AKIA" + "Q3XRT7ZK2MWN4PLA"
        for label, payload in (("nested", nested), ("json string", as_json), ("mcp", mcp), ("future", future),
                               ("aws", aws)):
            with self.subTest(case=label):
                proc = launch("PreToolUse", ARG_SCAN, payload)
                self.assertEqual(answer(proc)["decision"], "deny", proc.stdout)
                self.assertNotIn(SECRET, proc.stdout + proc.stderr)

    def test_placeholders_allow_markers_and_keys_alone_are_not_findings(self):
        for value in ("ghp_" + "x" * 36, "token: ${GITHUB_TOKEN}", f"{SECRET} agentic-sdlc:allow-secret",
                      "the api_key field holds the key"):
            with self.subTest(value=value[:12]):
                payload = fixture("pre-send-message", self.work)
                payload["toolCall"]["args"]["Message"] = value
                self.assertEqual(answer(launch("PreToolUse", ARG_SCAN, payload)), {"decision": "allow"})

    def test_oversized_or_too_deep_arguments_deny(self):
        big = fixture("pre-send-message", self.work)
        big["toolCall"]["args"]["Message"] = "a" * (5 * 1024 * 1024)
        deep = fixture("pre-send-message", self.work)
        value = "leaf"
        for _ in range(200):
            value = {"k": value}
        deep["toolCall"]["args"]["Message"] = value
        for label, payload in (("big", big), ("deep", deep)):
            with self.subTest(case=label):
                out = answer(launch("PreToolUse", ARG_SCAN, payload))
                self.assertEqual(out["decision"], "deny")
                self.assertTrue(out["reason"].startswith("agentic-sdlc:"))

    def test_the_argument_scan_leaves_command_and_write_tools_to_their_guards(self):
        for name in ("pre-run-command", "pre-write-file", "pre-edit-file"):
            payload = fixture(name, self.work)
            key = {"pre-run-command": "CommandLine", "pre-write-file": "Content", "pre-edit-file": "Replacement"}[name]
            payload["toolCall"]["args"][key] = f"echo {SECRET}"
            with self.subTest(fixture=name):
                self.assertEqual(answer(launch("PreToolUse", ARG_SCAN, payload)), {"decision": "allow"})

    def test_manage_task_input_reaches_the_command_guards(self):
        # The captured benign input gets the guards' no-objection answer for terminal input: ask.
        payload = fixture("pre-manage-task", self.work)
        for handler in COMMAND_GUARDS:
            with self.subTest(handler=handler):
                out = answer(launch("PreToolUse", handler, payload))
                self.assertEqual(out["decision"], "ask")
                self.assertIn("terminal task", out["reason"])
        payload["toolCall"]["args"]["Input"] = "git reset --hard"
        out = answer(launch("PreToolUse", "destructive-command-guard.mjs", payload))
        self.assertEqual(out["decision"], "deny")
        self.assertIn("reset --hard", out["reason"])

    def test_manage_task_without_input_runs_nothing_and_a_bad_input_denies(self):
        status = fixture("pre-manage-task", self.work)
        status["toolCall"]["args"] = {"Action": "status", "TaskId": "t1"}
        self.assertEqual(answer(launch("PreToolUse", "destructive-command-guard.mjs", status)), {"decision": "allow"})
        for value in (["git", "reset"], 7, None):
            with self.subTest(value=value):
                bad = fixture("pre-manage-task", self.work)
                bad["toolCall"]["args"]["Input"] = value
                out = answer(launch("PreToolUse", "destructive-command-guard.mjs", bad))
                self.assertEqual(out["decision"], "deny")

    def test_run_workflow_scripts_reach_the_command_guards_and_never_auto_approve(self):
        payload = fixture("pre-run-workflow", self.work)
        for handler in COMMAND_GUARDS:
            with self.subTest(handler=handler):
                out = answer(launch("PreToolUse", handler, payload))
                self.assertEqual(out["decision"], "ask")
                self.assertIn("run_workflow", out["reason"])
        payload["toolCall"]["args"]["Script"] = "git reset --hard"
        out = answer(launch("PreToolUse", "destructive-command-guard.mjs", payload))
        self.assertEqual(out["decision"], "deny")
        script = Path(self.tmp.name) / "wf.py"
        script.write_text("git reset --hard\n", encoding="utf-8")
        by_path = fixture("pre-run-workflow", self.work)
        del by_path["toolCall"]["args"]["Script"]
        by_path["toolCall"]["args"]["ScriptPath"] = str(script)
        out = answer(launch("PreToolUse", "destructive-command-guard.mjs", by_path))
        self.assertEqual(out["decision"], "deny")
        for args in ({"Description": "d"}, {"Description": "d", "ScriptPath": str(Path(self.tmp.name) / "no.py")},
                     {"Description": "d", "Script": 7}):
            with self.subTest(args=args):
                bad = fixture("pre-run-workflow", self.work)
                bad["toolCall"]["args"] = args
                self.assertEqual(answer(launch("PreToolUse", "branch-guard.mjs", bad))["decision"], "deny")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFOs are required")
    def test_a_run_workflow_script_path_that_is_not_a_regular_file_denies_at_once(self):
        fifo = Path(self.tmp.name) / "wf.fifo"
        os.mkfifo(fifo)
        folder = Path(self.tmp.name) / "wf-dir"
        folder.mkdir()
        for target in (fifo, folder):
            with self.subTest(target=target.name):
                payload = fixture("pre-run-workflow", self.work)
                del payload["toolCall"]["args"]["Script"]
                payload["toolCall"]["args"]["ScriptPath"] = str(target)
                started = time.monotonic()
                out = answer(launch("PreToolUse", "destructive-command-guard.mjs", payload))
                self.assertLess(time.monotonic() - started, 20)
                self.assertEqual(out["decision"], "deny")
                self.assertIn("ScriptPath", out["reason"])

    def test_run_workflow_cwd_is_the_folder_the_guard_checks(self):
        protected = git_repo(Path(self.tmp.name) / "protected")
        subprocess.run(["git", "checkout", "-q", "-b", "main"], cwd=protected, check=True, capture_output=True)
        payload = fixture("pre-run-workflow", self.work)
        payload["toolCall"]["args"]["Cwd"] = str(protected)
        payload["toolCall"]["args"]["Script"] = "git commit -q --allow-empty -m x"
        out = answer(launch("PreToolUse", "branch-guard.mjs", payload, env={"AGENTIC_BRANCH_GUARD_BLOCK": "true"}))
        self.assertEqual(out["decision"], "deny")


class AgyWireTests(unittest.TestCase):
    def setUp(self):
        self.wire = json.loads(WIRE.read_text(encoding="utf-8"))

    def commands(self, event):
        group = self.wire["agentic-sdlc"]
        entries = group[event]
        if event in ("PreToolUse", "PostToolUse"):
            return {entry["matcher"]: [h["command"] for h in entry["hooks"]] for entry in entries}
        return [h["command"] for h in entries]

    def test_one_enabled_named_group_with_the_guard_events(self):
        self.assertEqual(list(self.wire), ["agentic-sdlc"])
        group = self.wire["agentic-sdlc"]
        self.assertIs(group["enabled"], True)
        self.assertEqual(set(group), {"enabled", "PreToolUse", "SessionStart", "Stop"})

    def test_pretooluse_wires_the_command_and_write_guards(self):
        base = "node ./hooks/agy-launch.mjs --event PreToolUse --handler "
        self.assertEqual(self.commands("PreToolUse"), {
            "run_command|manage_task|run_workflow": [base + h for h in COMMAND_GUARDS],
            "write_file|edit_file": [base + "scan-write.mjs"],
            "*": [base + ARG_SCAN],
        })

    def test_session_start_and_stop(self):
        self.assertEqual(self.commands("SessionStart"),
                         ["node ./hooks/agy-launch.mjs --event SessionStart --handler session-start.mjs"])
        self.assertEqual(self.commands("Stop"),
                         ["node ./hooks/agy-launch.mjs --event Stop --handler worktree-scan.mjs"])

    def test_every_handler_has_a_type_and_a_timeout_and_exists(self):
        flat = json.dumps(self.wire)
        for handler in re.findall(r"--handler ([a-z-]+\.mjs)", flat):
            self.assertTrue((REPO / "hooks" / handler).is_file(), handler)
        for group in self.wire["agentic-sdlc"].values():
            if not isinstance(group, list):
                continue
            for entry in group:
                for hook in entry.get("hooks", [entry]):
                    self.assertEqual(hook["type"], "command")
                    self.assertIsInstance(hook["timeout"], int)
        # Claude transcript readers stay unwired on agy (no Claude transcript, no Skill tool events).
        for unwired in ("flow-order-guard", "completion-claim-guard", "flow-step-guard", "flow-evidence"):
            self.assertNotIn(unwired, flat)
        self.assertNotRegex(flat, r"[A-Za-z]:[\\/]|/home/|/Users/|\$\{")

    @unittest.skipUnless(NODE and os.name != "nt", "node and a POSIX shell are required")
    def test_wired_command_runs_from_the_package_root(self):
        # agy runs hooks with `sh -c` and cwd set to the folder holding hooks.json (package root).
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "pkg dir"
            shutil.copytree(REPO / "hooks", pkg / "hooks")
            shutil.copy2(WIRE, pkg / "hooks.json")
            work = git_repo(Path(tmp) / "project")
            payload = fixture("pre-run-command", work)
            payload["toolCall"]["args"]["CommandLine"] = "git reset --hard"
            command = self.commands("PreToolUse")["run_command|manage_task|run_workflow"][1]
            proc = subprocess.run(["/bin/sh", "-c", command], input=json.dumps(payload), text=True,
                                  encoding="utf-8", capture_output=True, cwd=pkg, timeout=60)
            self.assertEqual(answer(proc)["decision"], "deny")


class AgyFixtureHygieneTests(unittest.TestCase):
    def test_every_captured_event_has_a_fixture(self):
        self.assertEqual(sorted(p.stem for p in FIXTURES.glob("*.json")),
                         sorted(FIXTURE_NAMES + tuple(OTHER_TOOL_FIXTURES)))
        for name, tool in OTHER_TOOL_FIXTURES.items():
            self.assertEqual(fixture(name)["toolCall"]["name"], tool)
        events = {name: fixture(name)["hookEventName"] for name in FIXTURE_NAMES}
        self.assertEqual(events["session-start"], "SessionStart")
        self.assertEqual(events["stop"], "Stop")
        tools = {fixture(name)["toolCall"]["name"] for name in FIXTURE_NAMES if name.startswith(("pre-", "post-"))}
        self.assertEqual(tools, {"run_command", "write_file", "edit_file"})

    def test_fixtures_hold_no_local_path_id_or_environment_name(self):
        for path in sorted(FIXTURES.glob("*.json")):
            text = path.read_text(encoding="utf-8")
            with self.subTest(fixture=path.name):
                self.assertNotRegex(text, r"/home/|/Users/|[A-Za-z]:\\\\|\.cache|\.gemini")
                self.assertNotRegex(text, r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}|call_[0-9]{6,}")
                for key in ("envNames", "procCwd", "PLUGIN_ROOT", "PLUGIN_DATA"):
                    self.assertNotIn(key, text)
                payload = json.loads(text)
                self.assertEqual(payload["conversationId"], "***MASKED***")
                self.assertEqual(payload["cwd"], "/workspace/project")


if __name__ == "__main__":
    unittest.main()
