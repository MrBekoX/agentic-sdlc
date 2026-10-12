"""ZCode output-schema contract for every guard script the ZCode wire runs.

Why this suite exists: a marketplace install runs these scripts on machines
this repo does not control, and ZCode parses hook stdout as JSON against its
documented key set. The two official sources disagree on strictness - the
live hook doc (fetched 2026-10-08) says "unknown fields are ignored" while a
known field with a wrong type or a mismatched event name fails the run, and
the bundled zcode-guide `diagnosing-hooks` skill says the schema is strict:
"any extra key fails validation ... its effect was discarded and the run
marked failed" (pitfall 8). Under EITHER reading the current output is broken
on ZCode:

  - a deny payload that also carries the advisory top-level `systemMessage`
    (a Claude Code convention, not in ZCode's documented set) is at best
    carrying a no-op key and at worst a failed run with the deny discarded;
  - a warn payload that carries ONLY `systemMessage` is at best silently
    dropped (the guard's entire output is lost - the same observable gap the
    2026-09-20 scan-write fix closed for PostToolUse) and at worst a failed
    run.

The contract pinned here: under ZCode the scripts emit ONLY documented keys.
Decisions stay in `hookSpecificOutput` (hookEventName + permissionDecision +
permissionDecisionReason); warn text moves into
`hookSpecificOutput.additionalContext`, the documented model-visible channel.

ZCode mode is detected two independent, documented ways - the runtime injects
ZCODE_PLUGIN_ROOT into plugin hook processes as an environment variable, and
the ZCode wire passes a literal `--zcode-runtime` argv element. No other
runtime's wire sets either marker, so their output must stay byte-identical
to before; the Claude-mode tests at the bottom pin that.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
HOOKS = REPO / "hooks"
NODE = shutil.which("node")
GIT = shutil.which("git")

# Synthetic high-confidence token: matches the github-token HIGH pattern.
SECRET = "ghp_" + "a1B2" * 9

DECISION_KEYS = {"hookEventName", "permissionDecision", "permissionDecisionReason"}
ADVISORY_KEYS = {"hookEventName", "additionalContext"}


def hook_env(extra=None):
    env = dict(os.environ)
    # A dev shell exporting this would flip the branch-guard warn paths into
    # denies; the fixtures pin the default warn behavior explicitly.
    env.pop("AGENTIC_BRANCH_GUARD_BLOCK", None)
    if extra:
        env.update(extra)
    return env


def zcode_env(extra=None):
    return hook_env({"ZCODE_PLUGIN_ROOT": str(REPO), **(extra or {})})


def plain_env(extra=None):
    env = hook_env(extra)
    env.pop("ZCODE_PLUGIN_ROOT", None)
    return env


def run_hook(script, payload, env, marker=False, cwd=None):
    args = [NODE, str(HOOKS / script)]
    if marker:
        args.append("--zcode-runtime")
    proc = subprocess.run(
        args, input=json.dumps(payload), cwd=str(cwd or REPO),
        capture_output=True, text=True, encoding="utf-8", env=env,
    )
    assert proc.returncode == 0, f"{script} exited {proc.returncode}: {proc.stderr}"
    return json.loads(proc.stdout) if proc.stdout.strip() else {}


def assert_documented_keys_only(test, out, hso_keys):
    # The whole ZCode-mode contract: no top-level key outside the documented
    # set (today that means exactly hookSpecificOutput), and the
    # hookSpecificOutput carries only the documented fields of its shape.
    test.assertEqual(set(out), {"hookSpecificOutput"}, out)
    hso = out["hookSpecificOutput"]
    test.assertEqual(set(hso), hso_keys, hso)
    test.assertNotIn("systemMessage", json.dumps(out))


def git_repo(path, branch, staged_body=None):
    subprocess.run(["git", "init", "-b", branch], cwd=str(path),
                   check=True, capture_output=True)
    if staged_body is not None:
        (Path(path) / "config.txt").write_text(staged_body + "\n", encoding="utf-8")
        subprocess.run(["git", "add", "--", "config.txt"], cwd=str(path),
                       check=True, capture_output=True)


@unittest.skipIf(NODE is None, "node not available")
class TestZcodeModeOutput(unittest.TestCase):
    """Every wired emission path under ZCode markers emits documented keys only."""

    def test_destructive_deny_is_decision_only(self):
        payload = {"tool_name": "Bash", "hook_event_name": "PreToolUse",
                   "tool_input": {"command": "rm -rf build"}}
        out = run_hook("destructive-command-guard.mjs", payload,
                       zcode_env(), marker=True)
        assert_documented_keys_only(self, out, DECISION_KEYS)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PreToolUse")

    def test_destructive_clean_stays_silent(self):
        payload = {"tool_name": "Bash", "hook_event_name": "PreToolUse",
                   "tool_input": {"command": "ls -la"}}
        out = run_hook("destructive-command-guard.mjs", payload,
                       zcode_env(), marker=True)
        self.assertEqual(out, {})

    def test_branch_guard_warn_moves_into_additional_context(self):
        if GIT is None:
            self.skipTest("git not available")
        with tempfile.TemporaryDirectory() as td:
            git_repo(td, branch="main")
            payload = {"tool_name": "Bash", "hook_event_name": "PreToolUse",
                       "tool_input": {"command": "git commit -m wip"}, "cwd": td}
            out = run_hook("branch-guard.mjs", payload, zcode_env(), marker=True, cwd=td)
            assert_documented_keys_only(self, out, ADVISORY_KEYS)
            self.assertIn("main", out["hookSpecificOutput"]["additionalContext"])

    def test_branch_guard_block_is_decision_only(self):
        if GIT is None:
            self.skipTest("git not available")
        with tempfile.TemporaryDirectory() as td:
            git_repo(td, branch="main")
            payload = {"tool_name": "Bash", "hook_event_name": "PreToolUse",
                       "tool_input": {"command": "git commit -m wip"}, "cwd": td}
            env = zcode_env({"AGENTIC_BRANCH_GUARD_BLOCK": "true"})
            out = run_hook("branch-guard.mjs", payload, env, marker=True, cwd=td)
            assert_documented_keys_only(self, out, DECISION_KEYS)
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_commit_secret_deny_is_decision_only(self):
        if GIT is None:
            self.skipTest("git not available")
        with tempfile.TemporaryDirectory() as td:
            git_repo(td, branch="feature", staged_body="TOKEN = " + SECRET)
            payload = {"tool_name": "Bash", "hook_event_name": "PreToolUse",
                       "tool_input": {"command": "git commit -m wip"}, "cwd": td}
            out = run_hook("scan-commit.mjs", payload, zcode_env(), marker=True, cwd=td)
            assert_documented_keys_only(self, out, DECISION_KEYS)
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_commit_unreadable_repo_warn_becomes_additional_context(self):
        # The fail-open warning ("this commit was NOT scanned") emitted only
        # `systemMessage`; on ZCode that was the guard's entire output lost.
        with tempfile.TemporaryDirectory() as td:
            payload = {"tool_name": "Bash", "hook_event_name": "PreToolUse",
                       "tool_input": {"command": "git commit -m wip"}, "cwd": td}
            out = run_hook("scan-commit.mjs", payload, zcode_env(), marker=True, cwd=td)
            assert_documented_keys_only(self, out, ADVISORY_KEYS)
            self.assertIn("NOT scanned", out["hookSpecificOutput"]["additionalContext"])

    def test_write_scan_keeps_single_documented_advisory(self):
        payload = {"hook_event_name": "PostToolUse", "tool_name": "Write",
                   "tool_input": {"file_path": "notes.txt", "content": "TOKEN = " + SECRET}}
        out = run_hook("scan-write.mjs", payload, zcode_env(), marker=True)
        assert_documented_keys_only(self, out, ADVISORY_KEYS)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        self.assertNotIn("permissionDecision", json.dumps(out))

    def test_session_start_stays_schema_clean(self):
        # Already clean today; pinned so a regression cannot reintroduce the
        # advisory key through the one hook every session sees.
        payload = {"hook_event_name": "SessionStart", "source": "startup"}
        out = run_hook("session-start.mjs", payload, zcode_env(), marker=True)
        assert_documented_keys_only(self, out, {"hookEventName", "additionalContext"})
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")

    def test_detection_works_by_env_without_marker(self):
        # The runtime injects ZCODE_PLUGIN_ROOT as an env var; the argv marker
        # is the wire-side backup, not a dependency.
        payload = {"tool_name": "Bash", "hook_event_name": "PreToolUse",
                   "tool_input": {"command": "rm -rf build"}}
        out = run_hook("destructive-command-guard.mjs", payload, zcode_env())
        assert_documented_keys_only(self, out, DECISION_KEYS)

    def test_detection_works_by_marker_without_env(self):
        payload = {"tool_name": "Bash", "hook_event_name": "PreToolUse",
                   "tool_input": {"command": "rm -rf build"}}
        out = run_hook("destructive-command-guard.mjs", payload, plain_env(), marker=True)
        assert_documented_keys_only(self, out, DECISION_KEYS)


@unittest.skipIf(NODE is None, "node not available")
class TestOtherRuntimesKeepTheirChannels(unittest.TestCase):
    """No marker, no env -> byte-for-byte the pre-fix payloads."""

    def test_destructive_deny_keeps_system_message(self):
        payload = {"tool_name": "Bash", "hook_event_name": "PreToolUse",
                   "tool_input": {"command": "rm -rf build"}}
        out = run_hook("destructive-command-guard.mjs", payload, plain_env())
        self.assertTrue(out.get("systemMessage"))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_branch_guard_warn_keeps_system_message_only(self):
        if GIT is None:
            self.skipTest("git not available")
        with tempfile.TemporaryDirectory() as td:
            git_repo(td, branch="main")
            payload = {"tool_name": "Bash", "hook_event_name": "PreToolUse",
                       "tool_input": {"command": "git commit -m wip"}, "cwd": td}
            out = run_hook("branch-guard.mjs", payload, plain_env(), cwd=td)
            self.assertEqual(set(out), {"systemMessage"}, out)

    def test_commit_warn_keeps_system_message_only(self):
        with tempfile.TemporaryDirectory() as td:
            payload = {"tool_name": "Bash", "hook_event_name": "PreToolUse",
                       "tool_input": {"command": "git commit -m wip"}, "cwd": td}
            out = run_hook("scan-commit.mjs", payload, plain_env(), cwd=td)
            self.assertEqual(set(out), {"systemMessage"}, out)

    def test_write_scan_keeps_both_channels(self):
        payload = {"hook_event_name": "PostToolUse", "tool_name": "Write",
                   "tool_input": {"file_path": "notes.txt", "content": "TOKEN = " + SECRET}}
        out = run_hook("scan-write.mjs", payload, plain_env())
        self.assertTrue(out.get("systemMessage"))
        self.assertEqual(out["hookSpecificOutput"]["additionalContext"],
                         out["systemMessage"])


if __name__ == "__main__":
    unittest.main()
