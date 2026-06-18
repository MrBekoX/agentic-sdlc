"""Integration validation: every cross-reference resolves (test matrix F).

Asserts the wiring between skills/agents/workflows/commands/hooks/scripts is intact:
- golden must_reference entries both APPEAR in the SKILL.md and RESOLVE to a real component
  (e.g. agentic-sdlc-pipeline -> root-cause-fix/feature-build/safe-refactor/test-authoring, implementasyon-control ->
  implementation-auditor, spec-plan-draft workflow -> spec-plan-author/critic agents).
- every ${CLAUDE_PLUGIN_ROOT}/<path> referenced in skills/hooks resolves to a real repo file.
- hooks.json is valid JSON and each referenced .mjs exists.
- README / hooks-README claims match the real tree (settings.json reference is gating;
  the .claude-plugin manifest claim is a non-gating warning, reported below).
"""

import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
HARNESS = HERE / "skills" / "harness.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("skill_harness", HARNESS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


h = _load_harness()


class TestSkillCrossReferences(unittest.TestCase):
    def setUp(self):
        self.reg = h.registries()
        self.golden = h.load_golden()["skills"]

    def test_every_golden_reference_appears_and_resolves(self):
        failures = {}
        for name in sorted(h.skill_names()):
            if name not in self.golden:
                continue
            errors, _ = h.validate_skill_integration(
                h.SKILLS_DIR / name, self.golden[name], self.reg
            )
            if errors:
                failures[name] = errors
        self.assertEqual(failures, {}, f"cross-reference errors: {failures}")

    def test_dev_flow_delegates_to_four_work_flows(self):
        # The Onion-center contract: agentic-sdlc-pipeline must reference the four core work-flows it delegates to.
        text = (h.SKILLS_DIR / "agentic-sdlc-pipeline" / "SKILL.md").read_text(encoding="utf-8")
        for flow in ("root-cause-fix", "feature-build", "safe-refactor", "test-authoring"):
            self.assertIn(flow, text, f"agentic-sdlc-pipeline no longer references {flow}")

    def test_dev_flow_forbids_manual_substitutes_for_eval_gates(self):
        text = (h.SKILLS_DIR / "agentic-sdlc-pipeline" / "SKILL.md").read_text(encoding="utf-8")
        for phrase in (
            "Manual Read/Glob/ls exploration does not replace detect_context.py.",
            "Manual review text does not replace validate_artifacts.py.",
            "Manual TDD/edit/test work does not replace the selected core work-flow Skill call.",
        ):
            self.assertIn(phrase, text)

    def test_pipeline_references_runtime_adapter_and_non_claude_runtimes(self):
        text = (h.SKILLS_DIR / "agentic-sdlc-pipeline" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("runtime-adapter.md", text)
        self.assertIn("OpenCode", text)
        self.assertIn("Kimi Code", text)
        self.assertIn("Portable capability", text)

    def test_adapter_dependent_skills_do_not_make_workflow_unconditional(self):
        skills = [
            "dispatch-strategy",
            "spec-authoring",
            "plan-authoring",
            "mind-spark",
            "security-audit",
            "code-quality-review",
            "implementasyon-control",
        ]
        for skill in skills:
            text = (h.SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
            with self.subTest(skill=skill):
                if "Workflow" in text or "workflow" in text:
                    self.assertRegex(text, r"Claude Code|runtime|adapter|unavailable|degraded")

    def test_implementasyon_control_references_auditor_agent(self):
        text = (h.SKILLS_DIR / "implementasyon-control" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("implementation-auditor", text)
        self.assertIn("implementation-auditor", h.agent_names())

    def test_standalone_spec_plan_descriptions_do_not_trigger_internal_workflow(self):
        for skill in ("spec-authoring", "plan-authoring"):
            art = h.load_markdown_artifact(h.SKILLS_DIR / skill / "SKILL.md")
            desc = h.frontmatter_value(art["frontmatter"], "description")
            self.assertNotIn("spec-plan-draft", desc)

    def test_using_router_prioritizes_intent_over_domain_nouns(self):
        text = (h.SKILLS_DIR / "using-agentic-sdlc" / "SKILL.md").read_text(encoding="utf-8")
        for phrase in (
            "semantic intent before domain nouns",
            "Do not rely on exact keywords or the prompt language",
            "Any-language brainstorming",
            "option exploration",
            "not generic `brainstorming`",
            "even when the prompt mentions a bug",
            "never ask for bug details first",
            "after details arrive",
            "Any-language end-to-end/full-envelope prompts",
            "not `mind-spark`",
            "Any-language test-only requests",
            "before reading files",
            "Any-language behavior-preserving refactor prompts",
            "before Glob/Read/file-existence checks",
            "Any-language received-review-feedback prompts",
            "not a fresh `code-quality-review`",
            "Any-language orchestration decision prompts",
            "`dispatch-strategy` before answering",
            "Do not choose a mechanism directly",
            "same-purpose process skill",
            "superpowers:brainstorming",
            "Any-language clear implementation prompts",
            "`feature-build`",
            "Any-language final audit or process audit prompt",
            "not a passive session preference",
            "the audit intent requires a Skill call",
            "do not answer from memory",
            "invoke it anyway before clarifying",
        ):
            self.assertIn(phrase, text)

    def test_dispatch_strategy_description_covers_orchestration_decisions_before_answering(self):
        art = h.load_markdown_artifact(h.SKILLS_DIR / "dispatch-strategy" / "SKILL.md")
        desc = h.frontmatter_value(art["frontmatter"], "description")
        for phrase in (
            "in any language",
            "main loop",
            "sub-agent",
            "dynamic-workflow",
            "agent-team",
            "which orchestration mode to choose",
            "before answering",
        ):
            self.assertIn(phrase, desc)

    def test_mind_spark_description_covers_language_independent_brainstorming_intent(self):
        art = h.load_markdown_artifact(h.SKILLS_DIR / "mind-spark" / "SKILL.md")
        desc = h.frontmatter_value(art["frontmatter"], "description")
        for phrase in (
            "AGENTIC-SDLC pre-spec intent gate",
            "mind-spark brainstorming",
            "in any language",
            "explore options",
            "discuss direction",
            "supersedes generic brainstorming",
        ):
            self.assertIn(phrase, desc)

    def test_plan_authoring_handles_underspecified_plan_only_prompts_after_activation(self):
        text = (h.SKILLS_DIR / "plan-authoring" / "SKILL.md").read_text(encoding="utf-8")
        art = h.load_markdown_artifact(h.SKILLS_DIR / "plan-authoring" / "SKILL.md")
        desc = h.frontmatter_value(art["frontmatter"], "description")
        self.assertIn("underspecified plan-only prompts", desc)
        self.assertIn("no-direct-fix prompts", desc)
        self.assertIn("Activate before asking for missing bug details", desc)
        self.assertIn("stay in `plan-authoring`", text)
        self.assertIn("do not defer activation", text)

    def test_implementasyon_control_description_covers_final_flow_audit_prompts(self):
        art = h.load_markdown_artifact(h.SKILLS_DIR / "implementasyon-control" / "SKILL.md")
        desc = h.frontmatter_value(art["frontmatter"], "description")
        self.assertIn("pre-final audit", desc)
        self.assertIn("in any language", desc)
        self.assertIn("spec-plan-TDD-security flow", desc)
        self.assertIn("not passive session preferences", desc)
        self.assertIn("report missing evidence", desc)

    def test_test_authoring_description_requires_activation_before_file_reads(self):
        art = h.load_markdown_artifact(h.SKILLS_DIR / "test-authoring" / "SKILL.md")
        desc = h.frontmatter_value(art["frontmatter"], "description")
        self.assertIn("before inspecting code", desc)
        self.assertIn("test-only prompts", desc)


class TestRuntimePaths(unittest.TestCase):
    def test_all_plugin_root_refs_resolve(self):
        errors, _ = h.validate_plugin_root_refs()
        self.assertEqual(errors, [], f"dangling ${{CLAUDE_PLUGIN_ROOT}} refs: {errors}")

    def test_hooks_json_valid_and_scripts_exist(self):
        errors, _ = h.validate_hooks_json()
        self.assertEqual(errors, [], f"hooks.json errors: {errors}")

    def test_workflow_agent_types_resolve(self):
        errors, _ = h.validate_workflow_agent_types(h.registries())
        self.assertEqual(errors, [], f"workflow agentType errors: {errors}")

    def test_spec_plan_workflow_agent_types_are_plugin_qualified(self):
        text = (h.WORKFLOWS_DIR / "spec-plan-draft.js").read_text(encoding="utf-8")
        self.assertIn("agentType:'agentic-sdlc:spec-plan-author'", text)
        self.assertIn("agentType:'agentic-sdlc:spec-plan-critic'", text)
        self.assertNotIn("agentType:'spec-plan-author'", text)
        self.assertNotIn("agentType:'spec-plan-critic'", text)

    def test_spec_plan_workflow_supports_smoke_eval_mode(self):
        text = (h.WORKFLOWS_DIR / "spec-plan-draft.js").read_text(encoding="utf-8")
        self.assertIn("depth === 'smoke'", text)
        self.assertIn("maxRevisionRounds", text)


class TestDocConsistency(unittest.TestCase):
    def test_hooks_readme_does_not_reference_missing_settings_json(self):
        # The hooks are wired in hooks.json; a stale `settings.json` reference is a doc bug.
        errors, _ = h.check_doc_consistency()
        gating = [e for e in errors]
        self.assertEqual(
            gating, [],
            f"doc-consistency errors: {gating}",
        )

    def test_runtime_adapter_doc_exists_and_names_supported_runtimes(self):
        path = h.REPO / "docs" / "runtime-adapter.md"
        self.assertTrue(path.exists(), "docs/runtime-adapter.md is required for cross-runtime adapter behavior")
        text = path.read_text(encoding="utf-8")
        for phrase in (
            "Portable capability",
            "Claude Code",
            "Codex",
            "OpenCode",
            "Kimi Code",
            "Degraded fallback",
            "agentic-sdlc-pipeline",
            "spec-plan-draft",
        ):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
