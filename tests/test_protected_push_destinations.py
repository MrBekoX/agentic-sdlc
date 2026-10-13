"""Protected push decisions follow destinations, not only the checked-out branch.

Commands are hook input data only: no push command, network or source commit runs.
Git setup and commits are confined to TemporaryDirectory fixtures.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
GIT = shutil.which("git")
HOOK = REPO / "hooks" / "branch-guard.mjs"


@unittest.skipIf(NODE is None or GIT is None, "node and git required")
class TestProtectedPushDestinations(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="push-targets-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        self.repo = self.make_repo(self.root / "primary")

    def git(self, *args, cwd=None):
        result = subprocess.run(
            [GIT, "-c", "core.hooksPath=" + str(self.root / "no-hooks"), *args],
            cwd=str(cwd or self.repo), env=self.env, capture_output=True,
            text=True, encoding="utf-8", timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def make_repo(self, path, *, protected=True):
        path.mkdir(parents=True)
        self.git("init", "-b", "feature/audit", cwd=path)
        self.git("config", "user.name", "Fixture", cwd=path)
        self.git("config", "user.email", "fixture@example.invalid", cwd=path)
        self.git("config", "commit.gpgsign", "false", cwd=path)
        self.git("commit", "--allow-empty", "-m", "fixture base", cwd=path)
        if protected:
            self.git("branch", "main", cwd=path)
            self.git("branch", "master", cwd=path)
        self.git("config", "remote.origin.url", "https://example.invalid/fixture.git", cwd=path)
        return path

    def run_hook(self, command, *, block=True, cwd=None, camel=False, env=None):
        hook_env = dict(self.env, AGENTIC_BRANCH_GUARD_BLOCK="true" if block else "false")
        hook_env.update(env or {})
        payload = {"cwd": str(cwd or self.repo), "tool_name": "Bash",
                   "toolInput" if camel else "tool_input": {"command": command}}
        result = subprocess.run(
            [NODE, str(HOOK)], input=json.dumps(payload), cwd=str(self.root), env=hook_env,
            capture_output=True, text=True, encoding="utf-8", timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def assert_denied(self, command, **kwargs):
        output = self.run_hook(command, **kwargs)
        self.assertEqual(output.get("hookSpecificOutput", {}).get("permissionDecision"), "deny",
                         f"protected destination not denied: {command}\n{output}")
        return output

    def test_feature_push_to_protected_destination_denies(self):
        commands = (
            "git push origin HEAD:main", "git push --force origin HEAD:refs/heads/main",
            "git push origin +HEAD:master", "git push origin main",
            "git push origin HEAD:feature/x HEAD:main", "git push origin :master",
            "git push --delete origin main", "git push origin refs/heads/master",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assert_denied(command)

    def test_default_mode_warns_and_force_prefix_is_recognized(self):
        warning = self.run_hook("git push origin HEAD:main", block=False)
        self.assertIn("main", warning.get("systemMessage", ""))
        self.assertNotIn("permissionDecision", warning.get("hookSpecificOutput", {}))
        denied = self.assert_denied("git push origin +HEAD:master")
        self.assertIn("FORCE-PUSH", denied["hookSpecificOutput"]["permissionDecisionReason"])

    def test_alias_forwards_destination_and_directory_context(self):
        self.git("config", "alias.pub", "push origin")
        for command in (
            "git pub HEAD:main",
            "git -c alias.one=two -c 'alias.two=push origin' one HEAD:main",
            "env FOO=1 timeout -k 1 2 git push origin HEAD:main",
            'bash -c "git push origin HEAD:main"',
        ):
            with self.subTest(command=command):
                self.assert_denied(command)
        nested = self.make_repo(self.root / "parent" / "child" / "child", protected=False)
        self.git("config", "remote.origin.push", "HEAD:main", cwd=nested)
        self.assert_denied('git -C parent -C child -C child push origin', cwd=self.root)

    def test_every_repository_and_literal_sensitive_path_is_inspected(self):
        other = self.make_repo(self.root / "space $() ` # repo", protected=False)
        self.assert_denied(
            f"git -C '{self.repo.as_posix()}' push origin HEAD:feature/x && "
            f"git -C '{other.as_posix()}' push origin HEAD:master", cwd=self.root,
        )
        self.assert_denied("bash -c 'git -C /never-read-by-this-hook push origin HEAD:main'")

    def test_configured_push_mapping_and_modes(self):
        self.git("config", "remote.origin.push", "HEAD:main")
        self.assert_denied("git push origin")
        self.assertEqual(self.run_hook("git push origin HEAD:feature/x"), {})
        self.git("config", "--unset-all", "remote.origin.push")
        self.assert_denied("git -c remote.origin.push=HEAD:master push origin")
        for command in ("git push --all origin", "git push origin :", "git push origin +:"):
            with self.subTest(command=command):
                self.assert_denied(command)
        self.git("config", "push.default", "upstream")
        self.git("config", "branch.feature/audit.remote", "origin")
        self.git("config", "branch.feature/audit.merge", "refs/heads/main")
        self.assert_denied("git push")
        self.git("config", "push.default", "simple")
        self.assertEqual(self.run_hook("git push"), {}, "Git rejects a differently named simple upstream")

    def test_source_only_ref_uses_remote_mapping(self):
        self.git("config", "remote.origin.push", "refs/heads/feature/audit:refs/heads/main")
        self.assert_denied("git push origin feature/audit")
        self.git("branch", "topic/main")
        self.assert_denied("git push origin 'refs/heads/topic/*:refs/heads/*'")
        self.assertEqual(self.run_hook("git push origin 'refs/heads/*:refs/heads/review/*'"), {})

    def test_push_remote_precedence(self):
        self.git("config", "remote.backup.url", "https://example.invalid/backup.git")
        self.git("config", "remote.backup.push", "HEAD:main")
        self.git("config", "branch.feature/audit.remote", "origin")
        self.git("config", "remote.pushDefault", "backup")
        self.assert_denied("git push")
        self.git("config", "branch.feature/audit.pushRemote", "origin")
        self.assertEqual(self.run_hook("git push"), {})
        self.assertEqual(self.run_hook("git push --repo=backup origin HEAD:feature/x"), {})

    def test_mirror_guards_remote_deletion_without_local_main(self):
        feature_only = self.make_repo(self.root / "feature-only", protected=False)
        self.assert_denied("git push --mirror origin", cwd=feature_only)
        self.assertIn("systemMessage", self.run_hook("git push --mirror origin", cwd=feature_only, block=False))
        self.git("config", "remote.origin.mirror", "true", cwd=feature_only)
        self.assert_denied("git push origin", cwd=feature_only)

    def test_all_without_protected_local_refs_is_silent(self):
        feature_only = self.make_repo(self.root / "feature-only", protected=False)
        self.assertEqual(self.run_hook("git push --all origin", cwd=feature_only), {})

    def test_option_values_tag_refs_and_readonly_mentions_are_not_destinations(self):
        commands = (
            "git push --push-option HEAD:main origin HEAD:feature/x",
            "git push -oHEAD:main origin HEAD:feature/x",
            "git push --force-with-lease=main:deadbeef origin HEAD:feature/x",
            "git push --receive-pack 'git push origin HEAD:main --force' origin HEAD:feature/x",
            "git push origin refs/tags/main:refs/tags/main", "git push origin tag main",
            "git push --tags origin", "git push origin HEAD:refs/heads/feature/main",
            "git status", "git log --oneline", "git commit -m 'git push origin HEAD:main --force'",
            "echo bash -c 'git push origin HEAD:main'",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(self.run_hook(command), {})

    def test_actual_force_options_and_negation_are_respected(self):
        forced = self.assert_denied("git push -fv origin HEAD:main")
        self.assertIn("FORCE-PUSH", forced["hookSpecificOutput"]["permissionDecisionReason"])
        not_forced = self.assert_denied("git push --force --no-force origin HEAD:main")
        self.assertNotIn("FORCE-PUSH", not_forced["hookSpecificOutput"]["permissionDecisionReason"])

    def test_legacy_protected_checkout_and_camel_envelope(self):
        self.assert_denied("git push origin HEAD:main", camel=True)
        self.git("switch", "main")
        self.assert_denied("git commit -m ordinary")
        self.assert_denied("git push")

    def test_unknown_state_preserves_nonblocking_fail_open(self):
        output = self.run_hook("git push", env={"PATH": ""})
        self.assertNotEqual(output.get("hookSpecificOutput", {}).get("permissionDecision"), "deny")
        output = self.run_hook("git push --unknown-mode origin '$TARGET'")
        self.assertNotEqual(output.get("hookSpecificOutput", {}).get("permissionDecision"), "deny")

    def test_explicit_source_simple_ignores_differently_named_upstream(self):
        self.git("config", "push.default", "simple")
        self.git("config", "branch.main.remote", "origin")
        self.git("config", "branch.main.merge", "refs/heads/review-main")
        self.assert_denied("git push origin main")

    def test_explicit_source_upstream_maps_even_to_another_push_remote(self):
        self.git("config", "remote.backup.url", "https://example.invalid/backup.git")
        self.git("config", "push.default", "upstream")
        self.git("config", "branch.feature/audit.remote", "origin")
        self.git("config", "branch.feature/audit.merge", "refs/heads/main")
        self.assert_denied("git push backup feature/audit")

    def test_git_boolean_mirror_values_are_not_lost(self):
        for value in ("2", "-1", "1k", "0x1", "077", "1g", "-1m", " 1"):
            with self.subTest(value=value):
                self.git("config", "remote.origin.mirror", value)
                self.assertEqual(self.git("config", "--type=bool", "--get", "remote.origin.mirror"), "true")
                self.assert_denied("git push origin")
        for value in ("false", "0", "0k", "0x0"):
            with self.subTest(value=value):
                self.git("config", "remote.origin.mirror", value)
                self.assertEqual(self.run_hook("git push origin"), {})
        self.git("config", "--unset-all", "remote.origin.mirror")
        with (self.repo / ".git" / "config").open("a", encoding="utf-8") as handle:
            handle.write('\n[remote "origin"]\n\tmirror\n')
        self.assertEqual(self.git("config", "--type=bool", "--get", "remote.origin.mirror"), "true")
        self.assert_denied("git push origin")

    def test_external_config_overrides_are_unknown_without_new_reads(self):
        module = (REPO / "hooks" / "git-invocation.mjs").as_uri()
        mapper = (REPO / "hooks" / "push-targets.mjs").as_uri()
        script = "import {resolveGitCommands} from " + json.dumps(module) + ";\n"
        script += "import {resolvePushTargets} from " + json.dumps(mapper) + ";\n"
        script += "const commands=" + json.dumps([
            "env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=remote.origin.push GIT_CONFIG_VALUE_0=HEAD:main git push origin",
            "GIT_DIR=/never-read git push origin", "git -c include.path=/never-read push origin",
        ]) + ";\n"
        script += "const out=commands.map(c=>{const p=resolveGitCommands(c,{lookup:()=>'',cwd:process.cwd()}).invocations.find(i=>i.subcommand==='push');return {known:p.readContextKnown,unresolved:resolvePushTargets(p,{available:true,branch:'feature/audit',config:[],refs:[],refsKnown:true}).unresolved};});process.stdout.write(JSON.stringify(out));"
        result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=self.repo, env=self.env,
                                capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        for index, row in enumerate(json.loads(result.stdout)):
            with self.subTest(index=index):
                self.assertFalse(row["known"])
                self.assertTrue(row["unresolved"])

    def test_readonly_directory_chain_cannot_hide_a_later_protected_push(self):
        command = "git " + " ".join("-C d" + str(i) for i in range(32000))
        command += " status; git push origin HEAD:main"
        # Five seconds is below the actual 15-second hook timeout. The old new-metadata
        # implementation exhausted that runtime budget while resolving read-only cwd paths.
        result = subprocess.run([NODE, str(HOOK)], cwd=self.root,
                                env=dict(self.env, PATH="", AGENTIC_BRANCH_GUARD_BLOCK="true"),
                                input=json.dumps({"cwd": str(self.repo), "tool_input": {"command": command}}),
                                capture_output=True, text=True, encoding="utf-8", timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_environment_context_uses_the_actual_command_boundary(self):
        module = (REPO / "hooks" / "git-invocation.mjs").as_uri()
        mapper = (REPO / "hooks" / "push-targets.mjs").as_uri()
        override = "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=remote.origin.push GIT_CONFIG_VALUE_0=HEAD:main "
        commands = ["sudo -p git env " + override + "git push origin", "> git " + override + "git push origin",
                    "sudo -p git git push origin", "> git git push origin"]
        script = "import {resolveGitCommands} from " + json.dumps(module) + ";\n"
        script += "import {resolvePushTargets} from " + json.dumps(mapper) + ";\n"
        script += "const out=" + json.dumps(commands) + ".map(c=>{const p=resolveGitCommands(c,{lookup:()=>'',cwd:process.cwd()}).invocations.find(i=>i.subcommand==='push');return {known:p.readContextKnown,result:resolvePushTargets(p,{available:true,refsKnown:true,branch:'feature/audit',refs:[],config:[]})};});process.stdout.write(JSON.stringify(out));"
        result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=self.repo, env=self.env,
                                capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        for index, row in enumerate(json.loads(result.stdout)):
            with self.subTest(command=commands[index]):
                self.assertEqual(row["known"], index >= 2)
                self.assertEqual(row["result"]["unresolved"], index < 2)
                self.assertEqual(row["result"]["targets"], [])

    def test_tag_source_with_unqualified_namespace_is_not_a_definite_branch(self):
        self.git("tag", "v1")
        output = self.run_hook("git push origin refs/tags/v1:main")
        self.assertNotEqual(output.get("hookSpecificOutput", {}).get("permissionDecision"), "deny")
        self.assert_denied("git push origin refs/tags/v1:refs/heads/main")

    def test_colonless_wildcard_includes_protected_local_refs(self):
        with self.subTest(source="caller"):
            self.assert_denied("git push origin 'refs/heads/*'")
        self.git("config", "remote.origin.push", "refs/heads/*")
        with self.subTest(source="configured"):
            self.assert_denied("git push origin")
        self.git("config", "--unset-all", "remote.origin.push")
        self.assertEqual(self.run_hook("git push origin 'refs/heads/feature/*'"), {})
        self.assertEqual(self.run_hook("git push origin 'refs/heads/*:refs/heads/review/*'"), {})

    def test_prune_matching_and_all_cover_missing_local_main(self):
        feature_only = self.make_repo(self.root / "prune-fixture", protected=False)
        for command in ("git push --prune origin :", "git push --prune --all origin",
                        "git push --prune origin 'refs/heads/*'"):
            with self.subTest(command=command):
                self.assert_denied(command, cwd=feature_only)
        for command in ("git push origin :", "git push --prune --no-prune origin :",
                        "git push --prune origin 'refs/heads/*:refs/heads/review/*'",
                        "git push --prune origin 'refs/heads/feature/*'"):
            with self.subTest(command=command):
                self.assertEqual(self.run_hook(command, cwd=feature_only), {})

    def test_configured_default_source_ref_is_not_caller_upstream_remapping(self):
        self.git("config", "push.default", "upstream")
        self.git("config", "branch.feature/audit.remote", "origin")
        self.git("config", "branch.feature/audit.merge", "refs/heads/main")
        self.git("config", "remote.origin.push", "refs/heads/feature/audit")
        self.assertEqual(self.run_hook("git push origin"), {}, "configured refspec keeps its same-name destination")

    def test_default_and_configured_prune_ranges_are_consistent(self):
        feature_only = self.make_repo(self.root / "configured-prune", protected=False)
        for key, spec in (("push.default", "matching"), ("remote.origin.push", ":"),
                          ("remote.origin.push", "refs/heads/*")):
            with self.subTest(key=key, spec=spec):
                self.git("config", key, spec, cwd=feature_only)
                self.assert_denied("git push --prune origin", cwd=feature_only)
                self.assertEqual(self.run_hook("git push origin", cwd=feature_only), {})
                self.assertEqual(self.run_hook("git push --prune --no-prune origin", cwd=feature_only), {})
        for spec in ("refs/heads/feature/*", "refs/heads/*:refs/heads/review/*"):
            with self.subTest(spec=spec):
                self.git("config", "remote.origin.push", spec, cwd=feature_only)
                self.assertEqual(self.run_hook("git push --prune origin", cwd=feature_only), {})

    def test_tag_ambiguity_and_failed_state_remain_unresolved(self):
        module = (REPO / "hooks" / "push-targets.mjs").as_uri()
        script = "import {resolvePushTargets} from " + json.dumps(module) + ";\n"
        script += "const out=[" + \
            "resolvePushTargets({args:['origin','refs/tags/v1:main']},{available:true,refsKnown:true,branch:'feature/audit',config:[],refs:['refs/tags/v1']})," + \
            "resolvePushTargets({args:['origin']},{available:false,refsKnown:false,branch:'feature/audit',config:[],refs:[]})," + \
            "resolvePushTargets({args:['origin']},{available:true,refsKnown:true,branch:'feature/audit',config:[],refs:[]})];" + \
            "process.stdout.write(JSON.stringify(out));"
        result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=self.repo, env=self.env,
                                capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        for index, row in enumerate(json.loads(result.stdout)):
            with self.subTest(index=index):
                self.assertEqual(row["targets"], [])
                self.assertEqual(row["unresolved"], index < 2)

    def test_git_refname_shorthand_resolves_protected_sources(self):
        for source in ("heads/main", "heads/master"):
            with self.subTest(source=source):
                self.assert_denied("git push origin " + source)
        self.git("config", "remote.origin.push", "heads/main")
        self.assert_denied("git push origin")

    def test_caller_head_does_not_match_configured_branch_source(self):
        self.git("config", "remote.origin.push", "refs/heads/feature/audit:refs/heads/main")
        self.assertEqual(self.run_hook("git push origin HEAD"), {})
        self.assert_denied("git push origin feature/audit")

    def test_negative_refspecs_exclude_protected_source_candidates(self):
        self.assertEqual(self.run_hook("git push origin 'refs/heads/*' '^refs/heads/main' '^refs/heads/master'"), {})
        self.assert_denied("git push origin 'refs/heads/*' '^refs/heads/main'")
        self.assertEqual(self.run_hook("git push origin 'refs/heads/*:refs/heads/review/*' '^refs/heads/main'"), {})

    def test_prune_patterns_preserve_case_insensitive_protection(self):
        feature_only = self.make_repo(self.root / "prune-capital", protected=False)
        for spec in ("refs/heads/M*", "refs/heads/topic/*:refs/heads/M*"):
            with self.subTest(spec=spec):
                self.assert_denied("git push --prune origin '" + spec + "'", cwd=feature_only)
        self.git("config", "remote.origin.push", "refs/heads/M*", cwd=feature_only)
        self.assert_denied("git push --prune origin", cwd=feature_only)
        self.assertEqual(self.run_hook("git push --prune origin 'refs/tags/M*'", cwd=feature_only), {})

    def test_unexpanded_operands_are_not_verified_safe(self):
        module = (REPO / "hooks" / "push-targets.mjs").as_uri()
        script = "import {resolvePushTargets} from " + json.dumps(module) + ";\n"
        script += "const out=resolvePushTargets({args:['origin','$TARGET']},{available:true,refsKnown:true,branch:'feature/audit',refs:[],config:[]});process.stdout.write(JSON.stringify(out));"
        result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=self.repo, env=self.env,
                                capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["targets"], [])
        self.assertTrue(output["unresolved"])

    def test_plus_source_skips_caller_mapping(self):
        self.git("config", "remote.origin.push", "refs/heads/main:refs/heads/review/main")
        with self.subTest(source="forced protected"):
            self.assert_denied("git push origin +main")
        self.assertEqual(self.run_hook("git push origin main"), {})
        self.git("config", "remote.origin.push", "refs/heads/feature/audit:refs/heads/main")
        with self.subTest(source="forced feature"):
            self.assertEqual(self.run_hook("git push origin +feature/audit"), {})

    def test_caller_mapping_requires_canonical_config_source(self):
        self.git("config", "remote.origin.push", "feature/audit:main")
        self.assertEqual(self.run_hook("git push origin feature/audit"), {})
        self.git("config", "remote.origin.push", "refs/heads/feature/audit:refs/heads/main")
        self.assert_denied("git push origin heads/feature/audit")

    def test_head_and_plus_source_skip_caller_upstream_remapping(self):
        self.git("config", "push.default", "upstream")
        self.git("config", "branch.feature/audit.remote", "origin")
        self.git("config", "branch.feature/audit.merge", "refs/heads/main")
        for source in ("HEAD", "+HEAD", "+feature/audit"):
            with self.subTest(source=source):
                self.assertEqual(self.run_hook("git push origin " + source), {})
        self.assert_denied("git push origin feature/audit")

    def test_negative_push_refspecs_filter_destinations_and_prune_ranges(self):
        self.git("branch", "topic/main")
        self.assert_denied("git push origin 'refs/heads/topic/*:refs/heads/*' '^refs/heads/topic/m*'")
        self.assertEqual(self.run_hook("git push origin 'refs/heads/topic/*:refs/heads/*' '^refs/heads/main'"), {})
        feature_only = self.make_repo(self.root / "excluded-prune", protected=False)
        self.assertEqual(self.run_hook("git push --prune origin 'refs/heads/*' '^refs/heads/*'", cwd=feature_only), {})
        self.git("config", "remote.origin.push", "refs/heads/*")
        self.git("config", "--add", "remote.origin.push", "^refs/heads/main")
        self.git("config", "--add", "remote.origin.push", "^refs/heads/master")
        self.assertEqual(self.run_hook("git push origin"), {})

    def test_force_caution_survives_protected_checkout_with_safe_destination(self):
        self.git("switch", "main")
        for command in ("git push --force origin HEAD:feature/safe", "git push origin +HEAD:feature/safe"):
            with self.subTest(command=command):
                denied = self.assert_denied(command)
                self.assertIn("FORCE-PUSH", denied["hookSpecificOutput"]["permissionDecisionReason"])

    def test_custom_namespace_mapping_and_ambiguous_source_state(self):
        self.git("update-ref", "refs/review/topic", "HEAD")
        self.git("config", "remote.origin.push", "refs/review/topic:refs/heads/main")
        self.assert_denied("git push origin refs/review/topic")
        module = (REPO / "hooks" / "push-targets.mjs").as_uri()
        script = "import {resolvePushTargets} from " + json.dumps(module) + ";\n"
        script += "const out=resolvePushTargets({args:['origin','main']},{available:true,refsKnown:true,branch:'feature/audit',refs:['refs/heads/main','refs/tags/main'],config:[]});process.stdout.write(JSON.stringify(out));"
        result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=self.repo, env=self.env,
                                capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["targets"], [])
        self.assertTrue(output["unresolved"])

    def test_caller_refs_do_not_inherit_default_destination_exclusions(self):
        self.git("config", "remote.origin.push", "refs/heads/main:refs/heads/review/main")
        self.git("config", "--add", "remote.origin.push", "^refs/heads/main")
        # The configured negative rejects caller remapping, not its final destination.
        self.assert_denied("git push origin main")
        self.assertEqual(self.run_hook("git push origin"), {})

    def test_pattern_fanout_cannot_hide_later_explicit_protected_target(self):
        module = (REPO / "hooks" / "push-targets.mjs").as_uri()
        script = "import {resolvePushTargets} from " + json.dumps(module) + ";\n"
        script += "const refs=Array.from({length:25000},(_,i)=>'refs/heads/feature/'+i);const args=['origin',...Array(5000).fill('refs/heads/*:refs/heads/review/*'),'HEAD:main'];const out=resolvePushTargets({args},{available:true,refsKnown:true,branch:'feature/0',refs,config:[]});process.stdout.write(JSON.stringify(out));"
        # Ref/argv sizes fit the hook's local-state/input caps. Five seconds is below
        # the wired timeout; scanning every local ref for every pattern loses the deny.
        result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=self.repo, env=self.env,
                                capture_output=True, text=True, encoding="utf-8", timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["targets"], ["main"])

    def test_configured_pattern_query_negatives_use_reverse_destination(self):
        self.git("branch", "topic/main")
        for mapping, negative, source, denied in (
            ("refs/heads/*:refs/heads/review/*", "^refs/heads/main", "main", False),
            ("refs/heads/topic/*:refs/heads/*", "^refs/heads/topic/main", "topic/main", True),
        ):
            with self.subTest(mapping=mapping):
                self.git("config", "--replace-all", "remote.origin.push", mapping)
                self.git("config", "--add", "remote.origin.push", negative)
                command = "git push origin " + source
                if denied:
                    self.assert_denied(command)
                    self.assert_denied("git push origin")
                else:
                    self.assertEqual(self.run_hook(command), {})
                    self.assertEqual(self.run_hook("git push origin"), {})

    def test_positive_negative_fanout_stays_within_hook_budget(self):
        positive = ["refs/heads/*:refs/heads/*"] * 4000
        negative = ["^refs/heads/review/" + str(i) for i in range(4000)]
        command = "git push --prune origin " + " ".join(positive + negative + ["HEAD:main"])
        self.assertLess(len(command.encode("utf-8")), 512 * 1024)
        payload = {"cwd": str(self.repo), "tool_input": {"command": command}}
        result = subprocess.run([NODE, str(HOOK)], cwd=self.root,
                                env=dict(self.env, PATH="", AGENTIC_BRANCH_GUARD_BLOCK="true"),
                                input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8", timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(self.run_hook(command + " '^refs/heads/*'", env={"PATH": ""}), {})

    def test_configured_query_fanout_preserves_late_known_target(self):
        module = (REPO / "hooks" / "push-targets.mjs").as_uri()
        script = "import {resolvePushTargets} from " + json.dumps(module) + ";\n"
        script += "const sources=Array.from({length:40},(_,i)=>'feature/'+i);const specs=[...Array(4000).fill('refs/heads/*:refs/heads/*'),...Array.from({length:4000},(_,i)=>'^refs/heads/review/'+i)];const config=specs.map(s=>['remote.origin.push',s]);const raw=config.map(([k,v])=>k+'\\n'+v+'\\0').join('');if(Buffer.byteLength(raw)>1024*1024)throw Error('fixture exceeds Git query cap');const out=resolvePushTargets({args:['origin',...sources,'HEAD:main']},{available:true,refsKnown:true,branch:sources[0],refs:sources.map(s=>'refs/heads/'+s),config});process.stdout.write(JSON.stringify(out));"
        result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=self.repo, env=self.env,
                                capture_output=True, text=True, encoding="utf-8", timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["targets"], ["main"])

    def test_mapping_work_exhaustion_is_unknown_without_hiding_explicit_target(self):
        module = (REPO / "hooks" / "push-targets.mjs").as_uri()
        script = "import {resolvePushTargets} from " + json.dumps(module) + ";\n"
        script += "const sources=Array.from({length:40},(_,i)=>'feature/'+i);const specs=['refs/heads/feature/*:refs/heads/feature/*',...Array.from({length:4000},(_,i)=>'refs/heads/topic'+i+'/*:refs/heads/*'),...Array.from({length:4000},(_,i)=>'^refs/heads/review'+i+'/*')];const config=specs.map(s=>['remote.origin.push',s]).concat([['push.default','upstream'],['branch.feature/0.remote','origin'],['branch.feature/0.merge','refs/heads/main']]);const raw=config.map(([k,v])=>k+'\\n'+v+'\\0').join('');if(Buffer.byteLength(raw)>1024*1024)throw Error('fixture exceeds Git query cap');const state={available:true,refsKnown:true,branch:sources[0],refs:sources.map(s=>'refs/heads/'+s),config};const out=[resolvePushTargets({args:['origin',...sources]},state),resolvePushTargets({args:['origin',...sources,'HEAD:main']},state)];process.stdout.write(JSON.stringify(out));"
        result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=self.repo, env=self.env,
                                capture_output=True, text=True, encoding="utf-8", timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        unknown, explicit = json.loads(result.stdout)
        self.assertEqual(unknown["targets"], [])
        self.assertTrue(unknown["unresolved"])
        self.assertEqual(explicit["targets"], ["main"])
        self.assertTrue(explicit["unresolved"])

    def test_unique_plus_named_ref_retains_raw_canonical_source(self):
        self.git("branch", "-m", "work/audit")
        self.git("branch", "+feature")
        self.git("branch", "feature")
        self.git("config", "remote.origin.push", "refs/heads/+feature:refs/heads/main")
        denied = self.assert_denied("git push origin +feature")
        self.assertNotIn("FORCE-PUSH", denied["hookSpecificOutput"]["permissionDecisionReason"],
                         "a matched literal plus-name rewritten by config is not a force prefix")
        self.git("config", "remote.origin.push", "refs/heads/+feature:refs/heads/review/feature")
        self.assertEqual(self.run_hook("git push origin +feature"), {})
        self.git("branch", "+solo")
        self.git("config", "remote.origin.push", "refs/heads/+solo:refs/heads/main")
        self.assert_denied("git push origin +solo")

    def test_delete_plus_named_target_does_not_strip_it_as_force(self):
        self.assertEqual(self.run_hook("git push --delete origin +main"), {})
        self.assert_denied("git push --delete origin main")

    def test_invalid_numeric_mirror_is_unresolved_and_bounded(self):
        module = (REPO / "hooks" / "push-targets.mjs").as_uri()
        script = "import {resolvePushTargets} from " + json.dumps(module) + ";\n"
        script += "const out=['2g','2147483648','9'.repeat(100000)].map(v=>resolvePushTargets({args:['origin']},{available:true,refsKnown:true,branch:'feature/audit',refs:['refs/heads/feature/audit'],config:[['remote.origin.mirror',v]]}));process.stdout.write(JSON.stringify(out));"
        result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=self.repo, env=self.env,
                                capture_output=True, text=True, encoding="utf-8", timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        for row in json.loads(result.stdout):
            self.assertEqual(row["targets"], [])
            self.assertTrue(row["unresolved"])


if __name__ == "__main__":
    unittest.main()
