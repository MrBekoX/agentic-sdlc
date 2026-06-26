import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


@unittest.skipIf(NODE is None, "node not available")
class TestDestructiveCommandGuard(unittest.TestCase):
    def run_hook(self, command):
        proc = subprocess.run(
            [NODE, str(REPO / "hooks" / "destructive-command-guard.mjs")],
            input=json.dumps({"tool_input": {"command": command}}),
            capture_output=True,
            text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def test_blocks_git_reset_hard(self):
        out = self.run_hook("git reset --hard HEAD")
        decision = out["hookSpecificOutput"]["permissionDecision"]
        self.assertEqual(decision, "deny")

    def test_blocks_recursive_rm_forms(self):
        blocked = [
            "rm -rf ./tmp",
            "rm -fr ./tmp",
            "rm -r -f ./tmp",
            "rm --recursive --force ./tmp",
            "rm -r ./tmp",
            "rm -R ./tmp",
            "echo before; rm -r ./tmp",
            "git status && rm --recursive ./tmp",
            "(rm -rf ./tmp)",
            "{ rm -rf ./tmp; }",
            "echo $(rm -rf ./tmp)",
            "/bin/rm -rf ./tmp",
            "sudo rm -rf ./tmp",
            "command rm -rf ./tmp",
            "git status; sudo rm -rf ./tmp",
            "sudo -E rm -rf ./tmp",
            "sudo -u root rm -rf ./tmp",
            "sudo FOO=bar rm -rf ./tmp",
            "env FOO=bar rm -rf ./tmp",
            "env -u FOO rm -rf ./tmp",
            "rm.exe -rf ./tmp",
            "rm ./tmp -Recurse",
        ]
        for command in blocked:
            with self.subTest(command=command):
                out = self.run_hook(command)
                reason = out["hookSpecificOutput"]["permissionDecisionReason"]
                self.assertIn("rm-recursive", reason)

    def test_blocks_recursive_remove_item_forms(self):
        blocked = [
            "Remove-Item ./tmp -Recurse",
            "Remove-Item ./tmp -r",
            "Remove-Item ./tmp -Re",
            "Remove-Item ./tmp -Rec",
            "Remove-Item ./tmp -Recurse -Force",
            "Write-Output ok; Remove-Item ./tmp -Recurse",
            "ri ./tmp -Recurse",
            "del ./tmp -Recurse",
            "erase ./tmp -Recurse",
            "rd ./tmp -Recurse",
            "rmdir ./tmp -Recurse",
            "powershell -Command Remove-Item ./tmp -Recurse",
            "powershell -Command Remove-Item ./tmp -Re",
            'pwsh -c "Remove-Item ./tmp -Recurse"',
        ]
        for command in blocked:
            with self.subTest(command=command):
                out = self.run_hook(command)
                reason = out["hookSpecificOutput"]["permissionDecisionReason"]
                self.assertIn("powershell-remove-item-recurse", reason)

    def test_blocks_git_clean_fdx(self):
        out = self.run_hook("git clean -fdx")
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("git-clean-force", reason)

    def test_allows_non_destructive_commands(self):
        allowed = [
            "git status --short",
            "rm -f file.txt",
            "Remove-Item file.txt -Force",
            "ls -r",
            "rm file.txt; ls -r",
            "Remove-Item file.txt; Get-ChildItem -Recurse",
            "printf '; rm -rf ./tmp'",
            'echo "rm -rf ./tmp"',
            "Write-Output '; Remove-Item ./tmp -Recurse'",
        ]
        for command in allowed:
            with self.subTest(command=command):
                out = self.run_hook(command)
                self.assertEqual(out, {})

    # Regression: bypasses confirmed by the multi-lens-review run (2026-06-21).
    def test_blocks_git_global_option_bypasses(self):
        # git global options before the subcommand defeat an adjacency-only match.
        blocked = [
            ("git -C /tmp reset --hard", "git-reset-hard"),
            ("git -c core.pager=cat reset --hard HEAD", "git-reset-hard"),
            ("git --no-pager reset --hard", "git-reset-hard"),
            ("git -C /tmp clean -fdx", "git-clean-force"),
        ]
        for command, label in blocked:
            with self.subTest(command=command):
                out = self.run_hook(command)
                reason = out["hookSpecificOutput"]["permissionDecisionReason"]
                self.assertIn(label, reason)

    def test_blocks_quoted_command_name_bypass(self):
        # A quoted command NAME still runs the command in a shell: "rm", 'rm', r"m", rm""
        # all execute `rm`. The old stripQuoted() blanked quoted spans to spaces BEFORE
        # tokenizing, so the command name was lost and the recursive-rm / git checks never saw
        # it -> ALLOW. Quote-aware tokenization must normalize these back to the real command.
        blocked = [
            ('"rm" -rf ./tmp', "rm-recursive"),
            ("'rm' -rf ./tmp", "rm-recursive"),
            ('r"m" -rf ./tmp', "rm-recursive"),
            ('rm"" -rf ./tmp', "rm-recursive"),
            ('"git" reset --hard', "git-reset-hard"),
            ("'git' clean -fdx", "git-clean-force"),
            ('"rm" ./tmp -Recurse', "rm-recursive"),
        ]
        for command, label in blocked:
            with self.subTest(command=command):
                out = self.run_hook(command)
                reason = out["hookSpecificOutput"]["permissionDecisionReason"]
                self.assertIn(label, reason)

    def test_blocks_rm_long_recursive_flag_bundles(self):
        # Recursive short-flag bundles longer than 5 chars (the old arg.length<=5 cap).
        for command in ["rm -rfvvv ./tmp", "rm -vfrii ./tmp", "rm -fdrvv ./tmp"]:
            with self.subTest(command=command):
                out = self.run_hook(command)
                reason = out["hookSpecificOutput"]["permissionDecisionReason"]
                self.assertIn("rm-recursive", reason)

    def test_blocks_wrapped_recursive_rm(self):
        # Shell -c payloads, eval, and prefix wrappers that hide the real command.
        blocked = [
            'bash -c "rm -rf ./tmp"',
            "sh -c 'rm -rf ./tmp'",
            'zsh -c "rm -rf ./tmp"',
            'eval "rm -rf ./tmp"',
            "timeout 5 rm -rf ./tmp",
            "timeout -s KILL 5 rm -rf ./tmp",
            "nohup rm -rf ./tmp",
            "nice -n 10 rm -rf ./tmp",
            "nice rm -rf ./tmp",
            "setsid rm -rf ./tmp",
            "xargs rm -rf",
        ]
        for command in blocked:
            with self.subTest(command=command):
                out = self.run_hook(command)
                reason = out["hookSpecificOutput"]["permissionDecisionReason"]
                self.assertIn("rm-recursive", reason)

    def test_allows_wrappers_and_global_options_on_safe_commands(self):
        # False-positive boundary: wrappers / global options on non-destructive commands stay allowed.
        allowed = [
            "timeout 5 ls -la",
            "nice -n 10 ls",
            'bash -c "ls -la"',
            "sh -c 'echo hi'",
            "git -C /repo status",
            "git --no-pager log --oneline",
            "nohup sleep 30",
            "xargs ls",
            "time rm file.txt",
        ]
        for command in allowed:
            with self.subTest(command=command):
                out = self.run_hook(command)
                self.assertEqual(out, {})


@unittest.skipIf(NODE is None or shutil.which("git") is None, "node or git not available")
class TestBranchGuard(unittest.TestCase):
    def run_hook(self, command, cwd, block=False):
        env = os.environ.copy()
        if block:
            env["AGENTIC_BRANCH_GUARD_BLOCK"] = "true"
        proc = subprocess.run(
            [NODE, str(REPO / "hooks" / "branch-guard.mjs")],
            cwd=cwd,
            env=env,
            input=json.dumps({"tool_input": {"command": command}}),
            capture_output=True,
            text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def test_blocks_main_branch_when_strict_even_before_first_commit(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", "-b", "main"], cwd=td, check=True, capture_output=True)
            out = self.run_hook("git commit -m test", td, block=True)
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_warns_main_branch_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", "-b", "main"], cwd=td, check=True, capture_output=True)
            out = self.run_hook("git push origin main", td, block=False)
            self.assertIn("systemMessage", out)
            self.assertNotIn("hookSpecificOutput", out)


@unittest.skipIf(NODE is None, "node not available")
class TestCompletionClaimGuard(unittest.TestCase):
    HOOK = REPO / "hooks" / "completion-claim-guard.mjs"

    def _transcript(self, td, lines):
        path = Path(td) / "transcript.jsonl"
        path.write_text("\n".join(json.dumps(o) for o in lines), encoding="utf-8")
        return path

    def run_hook(self, lines, *, block=False, stop_active=False):
        with tempfile.TemporaryDirectory() as td:
            tpath = self._transcript(td, lines)
            env = os.environ.copy()
            if block:
                env["AGENTIC_COMPLETION_GATE_BLOCK"] = "true"
            proc = subprocess.run(
                [NODE, str(self.HOOK)],
                env=env,
                input=json.dumps({"transcript_path": str(tpath), "stop_hook_active": stop_active}),
                capture_output=True,
                text=True, encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = (proc.stdout or "").strip()
            return json.loads(out) if out else {}

    @staticmethod
    def _assistant(text):
        return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}

    @staticmethod
    def _gate_call():
        return {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Skill", "input": {"skill": "agentic-sdlc:completion-claim-gate"}}]}}

    def test_warns_on_claim_without_gate(self):
        out = self.run_hook([self._assistant("Feature complete. All tests passing.")])
        self.assertIn("systemMessage", out)
        self.assertNotIn("decision", out)

    def test_blocks_on_claim_without_gate_when_strict(self):
        out = self.run_hook([self._assistant("Implementation complete and ready to merge.")], block=True)
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("completion-claim-gate", out.get("reason", ""))

    def test_silent_when_gate_invoked(self):
        out = self.run_hook([self._gate_call(), self._assistant("Feature complete. All tests passing.")], block=True)
        self.assertEqual(out, {})

    def test_silent_without_claim(self):
        out = self.run_hook([self._assistant("Here is the current state; a couple of tests still fail.")], block=True)
        self.assertEqual(out, {})

    def test_loop_guard_allows_when_stop_hook_active(self):
        out = self.run_hook([self._assistant("Feature complete. All tests passing.")], block=True, stop_active=True)
        self.assertEqual(out, {})


@unittest.skipIf(NODE is None, "node not available")
class TestSessionStartHook(unittest.TestCase):
    def test_injects_agentic_sdlc_bootstrap(self):
        proc = subprocess.run(
            [NODE, str(REPO / "hooks" / "session-start.mjs")],
            cwd=REPO,
            capture_output=True,
            text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        context = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("AGENTIC_SDLC_BOOTSTRAP", context)
        self.assertIn("root skills/", context)
        self.assertIn("using-agentic-sdlc", context)
        self.assertIn("smallest sufficient skill", context)
        self.assertIn("agentic-sdlc-pipeline is only for full-envelope", context)
        self.assertIn("Route by semantic intent", context)
        self.assertIn("agentic-sdlc:mind-spark", context)
        self.assertIn("agentic-sdlc:plan-authoring", context)
        self.assertIn("never ask for bug details first", context)
        self.assertIn("agentic-sdlc:implementasyon-control", context)
        self.assertIn("agentic-sdlc:completion-claim-gate", context)
        self.assertIn("fresh evidence", context)
        self.assertIn("Skill tool", context)


@unittest.skipIf(NODE is None, "node not available")
class TestCodexSessionStartHook(unittest.TestCase):
    def test_injects_codex_specific_bootstrap_without_claude_tooling(self):
        proc = subprocess.run(
            [NODE, str(REPO / "hooks" / "session-start-codex.mjs")],
            cwd=REPO,
            capture_output=True,
            text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        context = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("AGENTIC_SDLC_CODEX_BOOTSTRAP", context)
        self.assertIn("AGENTIC-SDLC Codex plugin", context)
        self.assertIn("root skills/", context)
        self.assertIn("Codex does not expose Claude Code Skill, Workflow, or Agent transcript events", context)
        # Phase 1: the bootstrap now names the natively-wired command guards (AC6).
        self.assertIn("block natively via hooks-codex.json", context)
        self.assertIn("embedded author -> critic -> revise adapter", context)
        self.assertIn("${PLUGIN_ROOT}/skills/<skill>/SKILL.md", context)
        self.assertIn("Codex Adapter Gate", context)
        self.assertIn("docs/agentic-sdlc/specs/", context)
        self.assertIn("do not use spec.md or plan.md", context)
        self.assertIn("detect_context.py", context)
        self.assertIn("validate_artifacts.py", context)
        self.assertIn("do not run recursive cleanup deletes", context)
        self.assertIn("__pycache__", context)
        self.assertIn("completion-claim-gate", context)
        self.assertNotIn("Skill tool", context)
        self.assertNotIn("calling the Skill tool", context)
        # AP2c (AC15): flow-order is now wired, so the bootstrap must drop the "unwired" claim, name
        # the wired adapter, mark the AP2 envelope complete, and state the shared-env warn->block
        # coupling (AC16) — while preserving every assertion above.
        self.assertNotIn("Only flow-order path-gating remains unwired", context)
        self.assertIn("flow-order-guard-codex", context)
        self.assertIn("AP2", context)
        self.assertIn("AGENTIC_FLOW_GATE_BLOCK", context)
        self.assertIn("warn to block", context)


def _claude_loadable_hook_configs():
    """Hook config JSONs that Claude Code loads for this plugin: the file declared in
    .claude-plugin/plugin.json's `hooks` field, PLUS the default hooks/hooks.json if present
    (Claude Code auto-loads that filename regardless of the declaration -- that collision is the
    bug this guards). Returns existing paths only."""
    paths = []
    manifest = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    declared = manifest.get("hooks")
    if isinstance(declared, str):
        paths.append(REPO / declared.lstrip("./"))
    paths.append(REPO / "hooks" / "hooks.json")
    return [p for p in paths if p.exists()]


class TestRuntimeHookConfigSeparation(unittest.TestCase):
    """Claude Code auto-loads hooks/hooks.json by default, in ADDITION to the plugin.json-
    declared hooks-claude.json (confirmed by a WSL install). Claude Code substitutes
    ${CLAUDE_PLUGIN_ROOT}; the Codex variable ${PLUGIN_ROOT} is undefined here and resolves to
    empty -> /hooks/... -> MODULE_NOT_FOUND. So every hook config Claude can load must use ONLY
    ${CLAUDE_PLUGIN_ROOT}. The Codex config lives at hooks/hooks-codex.json, declared in
    .codex-plugin/plugin.json, where Claude never auto-loads it."""

    def test_claude_loadable_hooks_use_only_claude_plugin_root(self):
        # validate_hooks_json only checks that refs RESOLVE to a file -- it could not catch the
        # original bug, because the Codex session-start-codex.mjs happens to exist. This asserts
        # the stronger property: no Claude-loadable config carries ${PLUGIN_ROOT}, and every
        # ${CLAUDE_PLUGIN_ROOT}/<path> it references exists.
        configs = _claude_loadable_hook_configs()
        self.assertTrue(configs, "no Claude-loadable hook config found")
        ref_re = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([A-Za-z0-9_./-]+)")
        for cfg in configs:
            text = cfg.read_text(encoding="utf-8")
            rel = cfg.relative_to(REPO).as_posix()
            self.assertNotIn(
                "${PLUGIN_ROOT}", text,
                f"{rel} is loaded by Claude Code and must not use the Codex ${{PLUGIN_ROOT}} variable",
            )
            for ref in ref_re.findall(text):
                self.assertTrue(
                    (REPO / ref).exists(),
                    f"{rel} references ${{CLAUDE_PLUGIN_ROOT}}/{ref} which does not exist",
                )

    def test_codex_hook_config_present_and_declared(self):
        self.assertTrue((REPO / "hooks" / "hooks-codex.json").exists(), "Codex hook config missing")
        codex = json.loads((REPO / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(codex.get("hooks"), "./hooks/hooks-codex.json")

    def test_codex_config_uses_no_claude_plugin_root(self):
        # Symmetric to the Claude-side check: the Codex config resolves paths via ${PLUGIN_ROOT}
        # and must never carry the Claude variable (which is undefined on Codex).
        text = (REPO / "hooks" / "hooks-codex.json").read_text(encoding="utf-8")
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", text)
        self.assertIn("${PLUGIN_ROOT}", text)


@unittest.skipIf(NODE is None or shutil.which("git") is None, "node or git not available")
class TestScanCommitSecretScan(unittest.TestCase):
    """scan-commit.mjs blocks secrets ADDED in a commit, scanning with the HIGH set. The HIGH
    set used to recognize only 4 shapes (PEM header, AWS AKIA, password=, JSON credential), so
    a modern provider token on its own line committed unblocked, and key FILES were not caught
    by name at all. Values used here are synthetic (repeated 'a1B2' etc.), never real secrets."""

    HOOK = REPO / "hooks" / "scan-commit.mjs"

    def _scan(self, files):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", "-b", "main"], cwd=td, check=True, capture_output=True)
            for name, content in files.items():
                p = Path(td) / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
                subprocess.run(["git", "add", "--", name], cwd=td, check=True, capture_output=True)
            proc = subprocess.run(
                [NODE, str(self.HOOK)],
                cwd=td,
                input=json.dumps({"tool_input": {"command": "git commit -m test"}}),
                capture_output=True,
                text=True, encoding="utf-8",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def _assert_blocked(self, files):
        out = self._scan(files)
        self.assertEqual(
            out.get("hookSpecificOutput", {}).get("permissionDecision"),
            "deny",
            f"expected deny, got {out!r}",
        )
        return out

    def test_blocks_modern_provider_tokens_in_content(self):
        cases = {
            "github-pat": "TOKEN = " + "ghp_" + "a1B2" * 9,
            "github-fine-grained": "TOKEN = github_pat_" + "a1B2" * 12,
            "stripe": "STRIPE = " + "sk_live_" + "a1B2" * 5,
            "slack-bot": "SLACK = " + "xoxb-" + "1a2B3c4D5e6F",
            "slack-app": "SLACK = " + "xapp-1-" + "A1b2C3d4E5f6",
            "google-api": "GOOGLE = " + "AIza" + "a1B2" * 8 + "abc",
            "openai": "OPENAI = " + "sk-" + "a1B2" * 6,
            "jwt": "JWT = " + "eyJa1B2a1B2" + "." + "eyJc3D4c3D4" + "." + "e5F6e5F6",
        }
        for label, line in cases.items():
            with self.subTest(case=label):
                self._assert_blocked({"config.txt": line + "\n"})

    def test_blocks_bearer_token_on_commit(self):
        # bearer-token used to live only in BROAD (warn); scan-commit scans HIGH, so a commit
        # with a bearer token was not blocked. It must now be blocked at commit time.
        self._assert_blocked({"config.txt": "Authorization: Bearer " + "a1B2" * 6 + "\n"})

    def test_blocks_key_file_by_name(self):
        for name in ["deploy.pem", "server.key", "cert.p12", "id_rsa", ".npmrc", "secrets/id_ed25519"]:
            with self.subTest(name=name):
                self._assert_blocked({name: "opaque body — flagged by filename, not content\n"})

    def test_allows_clean_diff(self):
        out = self._scan({"notes.txt": "Just a normal note discussing rm -rf safety.\n"})
        self.assertEqual(out, {})

    def test_warns_non_blocking_when_git_diff_unreadable(self):
        # Outside a git repo `git diff --cached` errors -> fail-open. The commit is still allowed
        # (no deny), but the user must be WARNED it was not scanned, not silently passed as clean.
        with tempfile.TemporaryDirectory() as td:  # deliberately NOT a git repo
            proc = subprocess.run(
                [NODE, str(self.HOOK)],
                cwd=td,
                input=json.dumps({"tool_input": {"command": "git commit -m test"}}),
                capture_output=True,
                text=True, encoding="utf-8",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout) if proc.stdout.strip() else {}
            self.assertNotIn("hookSpecificOutput", out)  # not a deny
            self.assertIn("systemMessage", out)
            self.assertIn("NOT", out.get("systemMessage", ""))

    def test_does_not_print_secret_value(self):
        secret = "ghp_" + "a1B2" * 9
        out = self._assert_blocked({"config.txt": "TOKEN = " + secret + "\n"})
        self.assertNotIn(secret, json.dumps(out))


def _codex_bash_payload(command, cwd="/repo"):
    """A realistic Codex v0.142.0 PreToolUse(Bash) hook input (verified live, codex-cli 0.142.0):
    tool_name='Bash', tool_input.command carries the command, plus Codex's richer top-level keys.
    The command guards read only tool_name + tool_input.command, so the extra keys are inert."""
    return {
        "tool_name": "Bash",
        "hook_event_name": "PreToolUse",
        "cwd": cwd,
        "tool_input": {"command": command},
        "session_id": "probe-session",
        "tool_use_id": "tu_1",
        "turn_id": "turn_1",
        "model": "gpt-5.3-codex-spark",
        "permission_mode": "default",
        "transcript_path": "/tmp/none.jsonl",
    }


class TestCodexHookWiring(unittest.TestCase):
    """Phase 1 (AC2): Codex v0.142.0 natively supports BLOCKING PreToolUse hooks (verified live).
    The three command guards must be wired into hooks-codex.json with the SHELL-STRING command form
    (the args-array form does NOT run on Codex — verified), ${PLUGIN_ROOT} only, matcher 'Bash'."""

    WIRED = ["scan-commit.mjs", "destructive-command-guard.mjs", "branch-guard.mjs"]

    def _pretooluse_handlers(self):
        cfg = json.loads((REPO / "hooks" / "hooks-codex.json").read_text(encoding="utf-8"))
        out = []
        for block in cfg.get("hooks", {}).get("PreToolUse", []):
            for h in block.get("hooks", []):
                out.append((block.get("matcher"), h))
        return out

    def test_wires_three_command_guards(self):
        blob = json.dumps(self._pretooluse_handlers())
        for guard in self.WIRED:
            with self.subTest(guard=guard):
                self.assertIn(guard, blob, f"{guard} not wired in hooks-codex.json PreToolUse")

    def test_uses_shell_string_form_plugin_root_and_bash_matcher(self):
        handlers = self._pretooluse_handlers()
        self.assertTrue(handlers, "no PreToolUse handlers in hooks-codex.json")
        for matcher, h in handlers:
            with self.subTest(handler=h.get("command")):
                # Every PreToolUse handler TARGETS Bash: the command guards use matcher "Bash",
                # the write guard uses "Bash|apply_patch" (Phase 0c verified the combined regex
                # fires for both tools). assertIn — not assertEqual — accepts the apply_patch matcher.
                self.assertIn("Bash", matcher or "")
                self.assertNotIn("args", h, "Codex must use the shell-string form; args-array does not run")
                self.assertIn("node", h.get("command", ""))
                self.assertIn("${PLUGIN_ROOT}", h.get("command", ""))
                self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", h.get("command", ""))


@unittest.skipIf(NODE is None, "node not available")
class TestDestructiveCommandGuardCodexShape(unittest.TestCase):
    """AC4: the guard denies a destructive command fed in the Codex hook-input shape, end-to-end."""

    HOOK = REPO / "hooks" / "destructive-command-guard.mjs"

    def _run(self, command):
        proc = subprocess.run(
            [NODE, str(self.HOOK)],
            input=json.dumps(_codex_bash_payload(command)),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def test_codex_shaped_git_reset_hard_is_denied(self):
        out = self._run("git reset --hard HEAD")
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_codex_shaped_safe_command_allowed(self):
        self.assertEqual(self._run("git status --short"), {})


@unittest.skipIf(NODE is None or shutil.which("git") is None, "node or git not available")
class TestScanCommitCodexShape(unittest.TestCase):
    """AC4: scan-commit blocks a synthetic secret on a Codex-shaped commit input. Values are
    synthetic ('a1B2'-repeats), never real secrets."""

    HOOK = REPO / "hooks" / "scan-commit.mjs"

    def _scan(self, files):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", "-b", "main"], cwd=td, check=True, capture_output=True)
            for name, content in files.items():
                (Path(td) / name).write_text(content, encoding="utf-8")
                subprocess.run(["git", "add", "--", name], cwd=td, check=True, capture_output=True)
            proc = subprocess.run(
                [NODE, str(self.HOOK)],
                cwd=td,
                input=json.dumps(_codex_bash_payload("git commit -m x", cwd=td)),
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def test_codex_shaped_commit_with_secret_is_denied(self):
        out = self._scan({"config.txt": "TOKEN = " + "ghp_" + "a1B2" * 9 + "\n"})
        self.assertEqual(out.get("hookSpecificOutput", {}).get("permissionDecision"), "deny")

    def test_codex_shaped_clean_commit_allowed(self):
        self.assertEqual(self._scan({"notes.txt": "an ordinary note\n"}), {})

    def test_codex_deny_does_not_print_secret_value(self):
        secret = "ghp_" + "a1B2" * 9
        out = self._scan({"config.txt": "TOKEN = " + secret + "\n"})
        self.assertNotIn(secret, json.dumps(out))


@unittest.skipIf(NODE is None or shutil.which("git") is None, "node or git not available")
class TestBranchGuardCodexShape(unittest.TestCase):
    """AC4: branch-guard denies a protected-branch commit on a Codex-shaped input when the block
    env is set. branch-guard reads git state from the hook process cwd; Phase 0 verified Codex
    runs the hook in the working root, and this test sets cwd to the temp repo to exercise it."""

    HOOK = REPO / "hooks" / "branch-guard.mjs"

    def test_codex_shaped_protected_branch_commit_is_denied(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", "-b", "main"], cwd=td, check=True, capture_output=True)
            env = os.environ.copy()
            env["AGENTIC_BRANCH_GUARD_BLOCK"] = "true"
            proc = subprocess.run(
                [NODE, str(self.HOOK)],
                cwd=td,
                env=env,
                input=json.dumps(_codex_bash_payload("git commit -m x", cwd=td)),
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout) if proc.stdout.strip() else {}
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")


class TestCodexDocWiredSet(unittest.TestCase):
    """AC6: bind the hooks-scoped docs to the REAL wired set in hooks-codex.json. check_doc_consistency
    does not validate these doc bodies, so this is the gate-enforced lock against doc drift and
    against accidentally wiring a guard whose Codex contract is still unverified."""

    ALL_GUARDS = [
        "scan-commit.mjs", "destructive-command-guard.mjs", "branch-guard.mjs",
        "scan-write.mjs", "flow-order-guard.mjs", "completion-claim-guard.mjs", "flow-step-guard.mjs",
        # The Codex completion-claim adapter (different filename from the Claude base, so the doc-lock
        # would NOT see it via the base substring — DP7). Listing it makes the lock non-vacuous: it is
        # wired, so it must be named WIRED in the docs.
        "completion-claim-guard-codex.mjs",
        # The Codex flow-step adapter (AP2b): evidence-only Stop backstop. Same DP7 rationale — the
        # "-codex" infix means "flow-step-guard.mjs" is NOT a substring of it, so the deferred Claude
        # flow-step-guard.mjs stays classified deferred while this wired adapter must be named WIRED.
        "flow-step-guard-codex.mjs",
        # The Codex flow-order adapter (AP2c): env-gated opt-in PreToolUse pre-edit ordering gate.
        # Same DP7 rationale — "flow-order-guard.mjs" is NOT a substring of "flow-order-guard-codex.mjs"
        # ("-codex.mjs" vs ".mjs"), so the deferred Claude flow-order-guard.mjs stays classified
        # deferred while this wired adapter must be named WIRED in both docs.
        "flow-order-guard-codex.mjs",
    ]

    def _split(self):
        cfg_text = json.dumps(json.loads((REPO / "hooks" / "hooks-codex.json").read_text(encoding="utf-8")))
        wired = [g for g in self.ALL_GUARDS if g in cfg_text]
        deferred = [g for g in self.ALL_GUARDS if g not in cfg_text]
        return wired, deferred, cfg_text

    def test_wired_guards_named_in_docs(self):
        wired, _deferred, _ = self._split()
        ra = (REPO / "docs" / "runtime-adapter.md").read_text(encoding="utf-8")
        readme = (REPO / "hooks" / "README.md").read_text(encoding="utf-8")
        self.assertTrue(wired, "expected at least one Codex-wired command guard")
        for g in wired:
            with self.subTest(wired=g):
                self.assertIn(g, ra, f"{g} is wired on Codex but not named in docs/runtime-adapter.md")
                self.assertIn(g, readme, f"{g} is wired on Codex but not named in hooks/README.md")

    def test_deferred_guards_absent_from_config_and_marked_verify(self):
        _wired, deferred, cfg_text = self._split()
        ra_lines = (REPO / "docs" / "runtime-adapter.md").read_text(encoding="utf-8").splitlines()
        for g in deferred:
            with self.subTest(deferred=g):
                self.assertNotIn(g, cfg_text, f"{g} is deferred but present in hooks-codex.json")
                named = [ln for ln in ra_lines if g in ln]
                if named:
                    self.assertTrue(
                        any("VERIFY" in ln for ln in named),
                        f"{g} is deferred but its runtime-adapter.md line carries no VERIFY marker",
                    )

    def test_runtime_adapter_documents_shared_env_coupling(self):  # AC16
        # The single AGENTIC_FLOW_GATE_BLOCK switch both activates the AP2c flow-order pre-gate AND
        # escalates the AP2b flow-step Stop backstop from warn to block. The doc must state this
        # coupling on one flow-order-context line (the filename-only doc-lock did not verify the
        # coupling sentence exists).
        ra_lines = (REPO / "docs" / "runtime-adapter.md").read_text(encoding="utf-8").splitlines()
        coupling = [ln for ln in ra_lines
                    if "AGENTIC_FLOW_GATE_BLOCK" in ln and "also escalates" in ln and "warn to block" in ln]
        self.assertTrue(coupling, "runtime-adapter.md lacks the AP2c/AP2b shared-env coupling sentence")
        self.assertTrue(any("flow-order" in ln for ln in coupling),
                        "the shared-env coupling sentence is not stated in a flow-order context")
