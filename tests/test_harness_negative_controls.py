"""Every check the skill harness performs must be shown to fire.

`tests/skills/harness.py` is one of the four documented gate commands. It reports
`skills_eval=passed` and can emit 35 distinct failure keys. Measured before this file existed:
only 7 of those keys appeared anywhere under `tests/`, and most of those appearances were
comments or partial matches. Everything else was exercised only against the live, healthy
repository with `assertEqual(errors, [])`, which cannot tell a working check from a no-op.

That is not a hypothetical risk here. One check in that same file was found unreachable BY
CONSTRUCTION: its gating error sat behind `"settings.json" in txt and not
rglob("settings.json")`, and both conjuncts were false in practice, so it could never fire
whatever the documentation said. It had passed every gate run since it was written.

The structural cause was that the repo-wide validators resolved their inputs from module
globals, so no broken tree could be handed to them. They now take an optional root, defaulting
to exactly the previous behaviour.

Each control here does TWO things, because either alone proves less than it looks:

  1. a fixture tree with exactly ONE deliberate defect produces that defect's exact key;
  2. the SAME validator on the clean fixture produces nothing.

Without (2) a check that always fires would look correct. Without (1) the check might be a
no-op. And each control asserts the exact key rather than "some error appeared" - a neighbouring
check satisfies the weaker claim, which is precisely how a silenced check hides.
"""

import importlib.util
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HARNESS = REPO / "tests" / "skills" / "harness.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("harness_under_test", HARNESS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


h = _load_harness()

# Keys the harness can emit that no control here reaches, each with the reason. Asserted, so
# the list cannot grow silently - a new uncovered key fails the inventory test below.
UNREACHABLE = {
    "missing_skill_md":
        "run_all() iterates skill_names(), which only yields directories that already contain a "
        "SKILL.md, so this branch is dead on the live path. It is still reachable by calling "
        "validate_skill_structure directly, which is what the control below does.",
}

VALID_DESC = ("This skill should be used when a contributor needs a worked example of the "
              "harness fixture shape, and never in production routing.")


def _skill(root, name, frontmatter=None, body="# Title\n\nBody text.\n"):
    """Write one fixture skill and return its directory."""
    fm = {"name": name, "description": VALID_DESC} if frontmatter is None else frontmatter
    d = root / "skills" / name
    d.mkdir(parents=True, exist_ok=True)
    lines = ["---"] + ["%s: %s" % (k, v) for k, v in fm.items()] + ["---", ""]
    (d / "SKILL.md").write_text("\n".join(lines) + body, encoding="utf-8")
    return d


def _agent(root, stem, frontmatter=None):
    d = root / "agents"
    d.mkdir(parents=True, exist_ok=True)
    fm = ({"name": stem, "description": "A fixture agent contract."}
          if frontmatter is None else frontmatter)
    lines = ["---"] + ["%s: %s" % (k, v) for k, v in fm.items()] + ["---", "", "# Agent", ""]
    path = d / ("%s.md" % stem)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


class NegativeControl(unittest.TestCase):
    """Shared assertions: the defect produces its key, the clean fixture produces nothing."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def assertFires(self, key, result, where="errors"):
        errors, warnings = result
        bucket = errors if where == "errors" else warnings
        self.assertTrue(
            any(item.split(":")[0] == key for item in bucket),
            "expected %s in the %s, got errors=%s warnings=%s" % (key, where, errors, warnings),
        )

    def assertSilent(self, result):
        errors, warnings = result
        self.assertEqual(errors, [], "the clean fixture produced errors: %s" % errors)


class TestSkillStructureControls(NegativeControl):
    def test_missing_skill_md(self):
        d = self.root / "skills" / "example-skill"
        d.mkdir(parents=True)
        self.assertFires("missing_skill_md", h.validate_skill_structure(d))
        self.assertSilent(h.validate_skill_structure(_skill(self.root, "example-skill")))

    def test_no_frontmatter(self):
        d = self.root / "skills" / "example-skill"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("# No frontmatter here\n", encoding="utf-8")
        self.assertFires("no_frontmatter", h.validate_skill_structure(d))

    def test_bad_frontmatter_key(self):
        d = _skill(self.root, "example-skill",
                   {"name": "example-skill", "description": VALID_DESC, "argument-hint": "x"})
        self.assertFires("bad_frontmatter_key", h.validate_skill_structure(d))

    def test_no_name(self):
        d = _skill(self.root, "example-skill", {"description": VALID_DESC})
        self.assertFires("no_name", h.validate_skill_structure(d))

    def test_name_dir_mismatch(self):
        d = _skill(self.root, "example-skill",
                   {"name": "other-name", "description": VALID_DESC})
        self.assertFires("name_dir_mismatch", h.validate_skill_structure(d))

    def test_name_not_kebab(self):
        d = _skill(self.root, "Example_Skill",
                   {"name": "Example_Skill", "description": VALID_DESC})
        self.assertFires("name_not_kebab", h.validate_skill_structure(d))

    def test_name_too_long(self):
        long_name = "a" * 65
        d = _skill(self.root, long_name, {"name": long_name, "description": VALID_DESC})
        self.assertFires("name_too_long", h.validate_skill_structure(d))

    def test_no_description(self):
        d = _skill(self.root, "example-skill", {"name": "example-skill"})
        self.assertFires("no_description", h.validate_skill_structure(d))

    def test_angle_bracket_in_description(self):
        d = _skill(self.root, "example-skill",
                   {"name": "example-skill", "description": VALID_DESC + " Use <path>."})
        self.assertFires("angle_bracket_in_description", h.validate_skill_structure(d))

    def test_description_too_long(self):
        d = _skill(self.root, "example-skill",
                   {"name": "example-skill", "description": "x" * 1100})
        self.assertFires("description_too_long", h.validate_skill_structure(d))

    def test_imperative_description(self):
        d = _skill(self.root, "example-skill",
                   {"name": "example-skill", "description": "Use this to do the thing well."})
        self.assertFires("imperative_description", h.validate_skill_structure(d))

    def test_thin_description_is_a_warning(self):
        d = _skill(self.root, "example-skill",
                   {"name": "example-skill", "description": "short"})
        self.assertFires("thin_description", h.validate_skill_structure(d), where="warnings")

    def test_no_h1_title_is_a_warning(self):
        d = _skill(self.root, "example-skill", None, body="No heading in this body at all.\n")
        self.assertFires("no_h1_title", h.validate_skill_structure(d), where="warnings")

    def test_body_over_500_is_a_warning(self):
        d = _skill(self.root, "example-skill", None, body="# T\n" + ("line\n" * 600))
        self.assertFires("body_over_500", h.validate_skill_structure(d), where="warnings")


class TestAgentStructureControls(NegativeControl):
    def test_agent_no_frontmatter(self):
        d = self.root / "agents"
        d.mkdir(parents=True)
        path = d / "example-agent.md"
        path.write_text("# No frontmatter\n", encoding="utf-8")
        self.assertFires("agent_no_frontmatter", h.validate_agent_structure(path))
        self.assertSilent(h.validate_agent_structure(_agent(self.root, "example-agent")))

    def test_agent_unknown_key_is_a_warning(self):
        path = _agent(self.root, "example-agent",
                      {"name": "example-agent", "description": "d", "colour": "blue"})
        self.assertFires("agent_unknown_key", h.validate_agent_structure(path), where="warnings")

    def test_agent_no_name(self):
        path = _agent(self.root, "example-agent", {"description": "d"})
        self.assertFires("agent_no_name", h.validate_agent_structure(path))

    def test_agent_name_file_mismatch(self):
        path = _agent(self.root, "example-agent", {"name": "other", "description": "d"})
        self.assertFires("agent_name_file_mismatch", h.validate_agent_structure(path))

    def test_agent_no_description(self):
        path = _agent(self.root, "example-agent", {"name": "example-agent"})
        self.assertFires("agent_no_description", h.validate_agent_structure(path))


class TestIntegrationControls(NegativeControl):
    REG = {"skill": {"known-skill"}, "agent": set(), "workflow": set(),
           "command": set(), "script": set()}

    def test_missing_reference(self):
        d = _skill(self.root, "example-skill")
        entry = {"must_reference": [{"ref": "known-skill", "kind": "skill"}]}
        self.assertFires("missing_reference", h.validate_skill_integration(d, entry, self.REG))

    def test_dangling_reference(self):
        # The token APPEARS in the body but resolves to nothing in the registry.
        d = _skill(self.root, "example-skill", None,
                   body="# T\n\nSee ghost-skill for details.\n")
        entry = {"must_reference": [{"ref": "ghost-skill", "kind": "skill"}]}
        self.assertFires("dangling_reference", h.validate_skill_integration(d, entry, self.REG))

    def test_a_resolvable_reference_is_silent(self):
        d = _skill(self.root, "example-skill", None,
                   body="# T\n\nSee known-skill for details.\n")
        entry = {"must_reference": [{"ref": "known-skill", "kind": "skill"}]}
        self.assertSilent(h.validate_skill_integration(d, entry, self.REG))


class TestGoldenControls(NegativeControl):
    def test_golden_missing_skill(self):
        d = self.root / "skills" / "example-skill"
        d.mkdir(parents=True)
        self.assertFires("golden_missing_skill", h.validate_golden(d, {}))

    def test_description_drift(self):
        d = _skill(self.root, "example-skill")
        entry = {"description_must_include": ["a keyword that is not in the description"]}
        self.assertFires("description_drift", h.validate_golden(d, entry))

    def test_a_present_keyword_is_silent(self):
        d = _skill(self.root, "example-skill")
        self.assertSilent(h.validate_golden(d, {"description_must_include": ["harness"]}))


class TestPluginRootAndHookControls(NegativeControl):
    def _hooks(self, payload, name=None):
        (self.root / "hooks").mkdir(parents=True, exist_ok=True)
        for cfg in h.HOOK_CONFIGS:
            target = self.root / "hooks" / cfg
            if name is None or cfg == name:
                target.write_text(payload, encoding="utf-8")
            else:
                target.write_text("{}", encoding="utf-8")

    def test_plugin_root_ref_missing(self):
        _skill(self.root, "example-skill", None,
               body="# T\n\nRun `${CLAUDE_PLUGIN_ROOT}/scripts/does_not_exist.py`.\n")
        self._hooks("{}")
        self.assertFires("plugin_root_ref_missing", h.validate_plugin_root_refs(self.root))

    def test_a_resolvable_plugin_root_ref_is_silent(self):
        (self.root / "scripts").mkdir(parents=True)
        (self.root / "scripts" / "real.py").write_text("", encoding="utf-8")
        _skill(self.root, "example-skill", None,
               body="# T\n\nRun `${CLAUDE_PLUGIN_ROOT}/scripts/real.py`.\n")
        self._hooks("{}")
        self.assertSilent(h.validate_plugin_root_refs(self.root))

    def test_hooks_json_missing(self):
        (self.root / "hooks").mkdir(parents=True)
        self.assertFires("hooks_json_missing", h.validate_hooks_json(self.root))

    def test_hooks_json_invalid(self):
        self._hooks("{ not json")
        self.assertFires("hooks_json_invalid", h.validate_hooks_json(self.root))

    def test_hook_script_missing(self):
        self._hooks(json.dumps({
            "hooks": {"PreToolUse": [{"hooks": [
                {"command": 'node "${CLAUDE_PLUGIN_ROOT}/hooks/ghost.mjs"'}]}]}}))
        self.assertFires("hook_script_missing", h.validate_hooks_json(self.root))

    def test_a_wired_hook_script_is_silent(self):
        (self.root / "hooks").mkdir(parents=True, exist_ok=True)
        (self.root / "hooks" / "real.mjs").write_text("", encoding="utf-8")
        self._hooks(json.dumps({
            "hooks": {"PreToolUse": [{"hooks": [
                {"command": 'node "${CLAUDE_PLUGIN_ROOT}/hooks/real.mjs"'}]}]}}))
        self.assertSilent(h.validate_hooks_json(self.root))

    def test_codex_environment_loader_checks_both_command_fields(self):
        (self.root / "hooks").mkdir(parents=True, exist_ok=True)
        (self.root / "hooks" / "real.mjs").write_text("", encoding="utf-8")
        for field in ("command", "commandWindows"):
            with self.subTest(field=field):
                self._hooks(json.dumps({"hooks": {"SessionStart": [{"hooks": [{field:
                    "node -e \"const p=require('node:path').join(process.env.PLUGIN_ROOT,'hooks','ghost.mjs');\""
                }]}]}}))
                errors, warnings = h.validate_hooks_json(self.root)
                self.assertIn("hook_script_missing:hooks-codex.json:hooks/ghost.mjs", errors)
                self._hooks(json.dumps({"hooks": {"SessionStart": [{"hooks": [{field:
                    "node -e \"const p=require('node:path').join(process.env.PLUGIN_ROOT,'hooks','real.mjs');\""
                }]}]}}))
                self.assertSilent(h.validate_hooks_json(self.root))

    def test_grok_environment_loader_checks_missing_handler(self):
        self._hooks(json.dumps({"hooks": {"PreToolUse": [{"hooks": [{"command":
            "node -e \"const p=require('node:path').join(process.env.GROK_PLUGIN_ROOT,'hooks','ghost.mjs');\""
        }]}]}}), name="hooks-grok.json")
        errors, _ = h.validate_hooks_json(self.root)
        self.assertIn("hook_script_missing:hooks-grok.json:hooks/ghost.mjs", errors)
        (self.root / "hooks/ghost.mjs").write_text("// fixture", encoding="utf-8")
        self.assertSilent(h.validate_hooks_json(self.root))

    def test_zcode_argv_checks_missing_handler(self):
        self._hooks(json.dumps({"hooks": {"PreToolUse": [{"hooks": [{"command": "node",
            "args": ["${ZCODE_PLUGIN_ROOT}/hooks/ghost.mjs"]}]}]}}), name="hooks-zcode.json")
        errors, _ = h.validate_hooks_json(self.root)
        self.assertIn("hook_script_missing:hooks-zcode.json:hooks/ghost.mjs", errors)
        (self.root / "hooks/ghost.mjs").write_text("// fixture", encoding="utf-8")
        self.assertSilent(h.validate_hooks_json(self.root))


class TestWorkflowAgentControls(NegativeControl):
    def test_workflow_agent_missing(self):
        # `reg` is already injectable, so the control needs no fixture tree: an empty agent
        # registry makes every agentType the live workflows dispatch unresolvable.
        empty = {"skill": set(), "agent": set(), "workflow": set(),
                 "command": set(), "script": set()}
        result = h.validate_workflow_agent_types(empty)
        if not result[0]:
            self.skipTest("no workflow dispatches an agentType, so this key has no live source")
        self.assertFires("workflow_agent_missing", result)

    def test_the_real_registry_is_silent(self):
        self.assertSilent(h.validate_workflow_agent_types(h.registries()))


class TestSafetyGuardrailControls(NegativeControl):
    def test_safety_evidence_file_missing(self):
        data = {"scenarios": [{"id": "s1", "guardrail_evidence": [
            {"file": "does/not/exist.md", "contains": "anything"}]}]}
        self.assertFires("safety_evidence_file_missing",
                         h.validate_safety_guardrails(self.root, data))

    def test_safety_evidence_absent(self):
        (self.root / "docs").mkdir(parents=True)
        (self.root / "docs" / "guard.md").write_text("nothing relevant here", encoding="utf-8")
        data = {"scenarios": [{"id": "s1", "guardrail_evidence": [
            {"file": "docs/guard.md", "contains": "a phrase that is not present"}]}]}
        self.assertFires("safety_evidence_absent", h.validate_safety_guardrails(self.root, data))

    def test_safety_no_repo_guardrail_is_a_warning(self):
        data = {"scenarios": [{"id": "s1", "guardrail_evidence": []}]}
        self.assertFires("safety_no_repo_guardrail",
                         h.validate_safety_guardrails(self.root, data), where="warnings")

    def test_present_evidence_is_silent(self):
        (self.root / "docs").mkdir(parents=True)
        (self.root / "docs" / "guard.md").write_text("the needle is here", encoding="utf-8")
        data = {"scenarios": [{"id": "s1", "guardrail_evidence": [
            {"file": "docs/guard.md", "contains": "the needle"}]}]}
        self.assertSilent(h.validate_safety_guardrails(self.root, data))


class TestDocConsistencyControls(NegativeControl):
    def test_readme_claims_missing_plugin_manifest(self):
        (self.root / "README.md").write_text(
            "See .claude-plugin/plugin.json for the manifest.\n", encoding="utf-8")
        self.assertFires("readme_claims_missing_plugin_manifest",
                         h.check_doc_consistency(self.root), where="warnings")

    def test_readme_claims_missing_marketplace_json(self):
        (self.root / "README.md").write_text(
            "Install from marketplace.json in this repo.\n", encoding="utf-8")
        self.assertFires("readme_claims_missing_marketplace_json",
                         h.check_doc_consistency(self.root), where="warnings")

    def test_hooks_readme_references_missing_settings_json(self):
        (self.root / "hooks").mkdir(parents=True)
        (self.root / "hooks" / "README.md").write_text(
            "Wire the guards through settings.json.\n", encoding="utf-8")
        self.assertFires("hooks_readme_references_missing_settings_json",
                         h.check_doc_consistency(self.root))

    def test_a_consistent_tree_is_silent(self):
        (self.root / ".claude-plugin").mkdir(parents=True)
        (self.root / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
        (self.root / ".claude-plugin" / "marketplace.json").write_text("{}", encoding="utf-8")
        (self.root / "README.md").write_text(
            "See .claude-plugin/plugin.json and marketplace.json.\n", encoding="utf-8")
        (self.root / "hooks").mkdir(parents=True)
        (self.root / "hooks" / "README.md").write_text("No settings here.\n", encoding="utf-8")
        self.assertSilent(h.check_doc_consistency(self.root))


class TestConflictMarkerControls(NegativeControl):
    """A committed conflict marker must fail something.

    Merging ten branches left unresolved markers in two committed files, and BOTH survived a
    full 1445-test gate run. One of them was `docs/testing.md`, whose suite-map test read that
    exact file and passed - it matches table rows with a regex, and the rows on both sides of
    the marker still matched.
    """

    def _repo(self, files, track=True):
        """A scratch git repository containing `files`, staged unless `track` is False."""
        git = shutil.which("git")
        if git is None:
            self.skipTest("git not available - cannot build a tracked fixture set")
        run = lambda *a: subprocess.run([git, *a], cwd=self.root, check=True,
                                        capture_output=True)
        run("init", "-q", "-b", "main", ".")
        run("config", "user.email", "t@example.invalid")
        run("config", "user.name", "T")
        for rel, text in files.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        if track:
            run("add", "-A")
        return self.root

    def test_conflict_marker(self):
        marker = "<" * 7 + " HEAD"
        self._repo({"docs/note.md": "# Note\n" + marker + "\nleft\n"})
        result = h.validate_no_conflict_markers(self.root)
        self.assertFires("conflict_marker", result)
        # The path is named; the line is NOT echoed - a marker can sit in a file that also
        # holds sensitive text, and a gate that prints the region turns a slip into a leak.
        self.assertTrue(any("docs/note.md" in e for e in result[0]), result[0])
        self.assertFalse(any("left" in e for e in result[0]),
                         "the check echoed file contents: %s" % result[0])

    def test_prose_about_markers_is_not_a_marker(self):
        # This spec, this docstring and this repository's own lessons all discuss the strings.
        # A check that fired on them would be unusable in the repository that needs it.
        marker = "<" * 7
        self._repo({"docs/note.md":
                    "# Note\n\nA merge writes `" + marker + " HEAD` at the top of the region.\n"})
        self.assertSilent(h.validate_no_conflict_markers(self.root))

    def test_an_untracked_file_is_not_checked(self):
        marker = "<" * 7 + " HEAD"
        self._repo({"docs/note.md": "# Note\n"}, track=True)
        (self.root / "scratch.md").write_text(marker + "\n", encoding="utf-8")
        self.assertSilent(h.validate_no_conflict_markers(self.root))

    def test_a_heading_underline_is_not_a_marker(self):
        # `=======` is a Markdown heading underline. Gating on it would fire on ordinary docs,
        # so only the two distinctive forms count.
        self._repo({"docs/note.md": "Title\n" + "=" * 7 + "\n\nBody.\n"})
        self.assertSilent(h.validate_no_conflict_markers(self.root))

    def test_conflict_marker_scan_skipped(self):
        # A check that cannot enumerate its input has verified nothing; saying so is the same
        # honesty rule this repository applies to a missing `node`. A WARNING rather than a
        # raise, because the harness is a CLI - a unittest exception escaping it would be a
        # crash, not a report.
        original = h.shutil.which
        h.shutil.which = lambda name: None if name == "git" else original(name)
        try:
            result = h.validate_no_conflict_markers(self.root)
            self.assertFires("conflict_marker_scan_skipped", result, where="warnings")
            self.assertEqual(result[0], [], "a check that could not run must report no errors")
        finally:
            h.shutil.which = original


class TestAggregatorControls(unittest.TestCase):
    """`no_golden_entry` is emitted only inside run_all(), not by any separately callable
    validator, so its control injects the golden map rather than a fixture tree."""

    def test_no_golden_entry_is_a_warning(self):
        _errors, warnings, _metrics = h.run_all(golden={})
        self.assertTrue(
            any(w.split(":")[0] == "no_golden_entry" for w in warnings),
            "with an empty golden map every skill should be reported as unmapped, got %s"
            % warnings[:5],
        )

    def test_the_real_golden_map_is_silent_on_that_key(self):
        _errors, warnings, _metrics = h.run_all()
        offenders = [w for w in warnings if w.split(":")[0] == "no_golden_entry"]
        self.assertEqual(offenders, [],
                         "a shipped skill has no golden entry: %s" % offenders)


class TestEveryKeyIsCoveredOrDeclared(unittest.TestCase):
    """The inventory gate: a new failure key with neither a control nor a reason fails here."""

    KEY_RE = re.compile(r'(?:errors|warnings)\.append\(\s*f?"([a-z_0-9]+)')

    def _emitted_keys(self):
        source = HARNESS.read_text(encoding="utf-8")
        keys = set(self.KEY_RE.findall(source))
        # `f"body_over_500:..."` and `f"no_h1_title:..."` contain digits the pattern keeps; the
        # regex above already allows them. Nothing else needs special-casing.
        return keys

    def _covered_keys(self):
        text = Path(__file__).read_text(encoding="utf-8")
        covered = set(re.findall(r'assertFires\(\s*"([a-z_0-9]+)"', text))
        # Controls that assert a key directly rather than through the helper - currently only
        # the aggregator one, whose result shape is (errors, warnings, metrics).
        covered |= set(re.findall(r'w\.split\(":"\)\[0\] == "([a-z_0-9]+)"', text))
        return covered

    def test_every_emitted_key_has_a_control_or_a_reason(self):
        emitted = self._emitted_keys()
        uncovered = sorted(emitted - self._covered_keys() - set(UNREACHABLE))
        self.assertEqual(
            uncovered, [],
            "these harness failure keys have no negative control and no recorded reason, so "
            "nothing shows they can fire (%d): %s" % (len(uncovered), ", ".join(uncovered)),
        )

    def test_the_unreachable_list_carries_reasons_and_stays_current(self):
        for key, reason in sorted(UNREACHABLE.items()):
            with self.subTest(key=key):
                self.assertTrue(reason and len(reason) > 40,
                                "%s is declared unreachable with no real reason" % key)
                self.assertIn(key, self._emitted_keys(),
                              "%s is declared unreachable but the harness no longer emits it" % key)

    def test_the_key_scanner_finds_something(self):
        # A regex that silently matched nothing would make the coverage test pass by vacuity:
        # the empty set is a subset of everything.
        self.assertGreater(len(self._emitted_keys()), 25,
                           "the key scanner found almost nothing - it is probably no longer "
                           "matching how the harness appends its failures")


if __name__ == "__main__":
    unittest.main()
