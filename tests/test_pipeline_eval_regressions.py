"""Regression checks for the defects the 2026-10-22 live procedure eval found on 52a2ad1.

Six rows ran on the maintainer's WSL Claude Code (Haiku 5.5, low) and Codex (6-Luna, low); none passed
(audit root `agentic-sdlc-audit-v2.1`, README Part C). The transcripts traced each failure to plugin text:

- Claude, both pipeline rows: the saved spec failed `validate_artifacts.py --mode spec` with
  `missing_section:business-rules` because the `spec-plan-author` role names that section "Business / domain
  rules" (the validator looks for "business rules"), and with `missing_frontmatter_key:work_id` because neither
  template shows the frontmatter the validator requires. The main loop then wrote the file with a shell script,
  which the flow hooks and the strict grader do not see as an artifact write (`strict_step_missing:spec-written`).
  The gate-stop row also saved `status: draft` because the critic still had notes.
- Codex, gate-stop: "The required `dispatch-strategy` call isn't available in this runtime" - the call-order
  guard names only the Claude `Skill` call.
- Codex, router escalation: no subagent mechanism (`multi_agent_mode` empty), so the model stopped to ask
  instead of recording `Delegation Degraded` and running the role inline.
- Codex, pre-approved: "Your instruction says not to create a branch" - the prompt only asked to leave the
  changes uncommitted.

Like the rest of the text suites this is a drift gate, not a truth gate: it shows the instructions say the
right thing, not that a model follows them. Expectations are derived from the validator's own constants where
the defect was a disagreement with the validator, so the two cannot drift apart again.
"""

import importlib.util
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

PIPELINE = "skills/agentic-sdlc-pipeline/SKILL.md"
PLAYBOOK = "skills/agentic-sdlc-pipeline/playbook.md"
TEMPLATES = "skills/agentic-sdlc-pipeline/templates.md"
AUTHOR = "agents/spec-plan-author.md"
CRITIC = "agents/spec-plan-critic.md"
# Focused skills that open with the `dispatch-strategy` call-order guard.
GUARDED_FOCUSED_SKILLS = ("code-quality-review", "feature-build", "root-cause-fix", "safe-refactor",
                          "security-audit", "test-authoring")

BACKTICK_HEADING = re.compile(r"`##\s+([^`]+)`")


def load_validator():
    spec = importlib.util.spec_from_file_location("validate_artifacts", REPO / "scripts" / "validate_artifacts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = load_validator()


def read(rel):
    return (REPO / rel).read_bytes().decode("utf-8")


def paragraph(text, opener):
    """The paragraph (up to the next blank line) that starts with `opener`, or None."""
    start = text.find(opener)
    if start < 0:
        return None
    end = text.find("\n\n", start)
    return text[start:] if end < 0 else text[start:end]


def fenced_block_after(text, heading_prefix):
    """Body of the first fenced block after the line starting with `heading_prefix`."""
    at = text.find("\n" + heading_prefix)
    if at < 0:
        return None
    match = re.compile(r"```[a-z]*\n(.*?)```", re.S).search(text, at)
    return match.group(1) if match else None


class TestSpecHeadingsMatchValidator(unittest.TestCase):
    """The author drafts and the critic audits against the headings the validator requires."""

    def assert_names_every_required_heading(self, rel):
        headings = [h.strip().lower() for h in BACKTICK_HEADING.findall(read(rel))]
        self.assertTrue(headings, f"{rel} names no `## <heading>` for the spec")
        for slug, needle in VALIDATOR.REQUIRED_SPEC_SECTIONS.items():
            with self.subTest(file=rel, section=slug):
                self.assertTrue(any(needle in h for h in headings),
                                f"{rel} names no heading containing {needle!r} (validator slug {slug})")

    def test_author_names_the_validator_headings(self):
        self.assert_names_every_required_heading(AUTHOR)

    def test_critic_blocks_a_missing_validator_heading(self):
        self.assert_names_every_required_heading(CRITIC)

    def test_author_drops_the_wording_the_validator_misses(self):
        self.assertNotIn("Business / domain rules", read(AUTHOR))


class TestTemplatesCarryFrontmatter(unittest.TestCase):
    """The spec and plan templates open with the frontmatter keys the validator requires."""

    def test_templates_open_with_required_frontmatter(self):
        text = read(TEMPLATES)
        for mode, heading in (("spec", "## Spec (step 4"), ("plan", "## Plan (step 5")):
            with self.subTest(mode=mode):
                block = fenced_block_after(text, heading)
                self.assertIsNotNone(block, f"{TEMPLATES}: no fenced template after `{heading}`")
                meta = VALIDATOR.parse_frontmatter(block)
                for key in VALIDATOR.FRONTMATTER_REQUIRED[mode]:
                    self.assertIn(key, meta, f"{mode} template frontmatter lacks `{key}`")
                self.assertEqual(meta.get("status"), "reviewed")


def load_resolver():
    spec = importlib.util.spec_from_file_location("resolve_work_package",
                                                  REPO / "scripts" / "resolve_work_package.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestPlanTemplateResolves(unittest.TestCase):
    """A plan saved from the template resolves its spec.

    The resolver reads the plan's `spec:` relative to the plan's own folder, so a repo-relative value
    (`docs/agentic-sdlc/specs/<work_id>.md`) pointed at `plans/docs/agentic-sdlc/specs/...` and failed
    with `spec_outside_root`; implementation-control then stopped on every package saved from the template.
    """

    def test_saved_template_pair_resolves(self):
        import tempfile
        resolver = load_resolver()
        text = read(TEMPLATES)
        filled = {}
        for mode, heading, rel in (("spec", "## Spec (step 4", "docs/agentic-sdlc/specs/w1.md"),
                                   ("plan", "## Plan (step 5", "docs/agentic-sdlc/plans/w1.md")):
            block = fenced_block_after(text, heading)
            self.assertIsNotNone(block, f"{TEMPLATES}: no fenced template after `{heading}`")
            self.assertIn(f"`{rel.replace('w1', '<work_id>')}`", text, f"{TEMPLATES} no longer saves {mode} there")
            filled[rel] = block.replace("<work_id>", "w1").replace("<work branch>", "feat/w1")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel, body in filled.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body.encode("utf-8"))
            result = resolver.resolve(root.resolve(), plan_path=str(root / "docs/agentic-sdlc/plans/w1.md"),
                                      branch="feat/w1")
            self.assertEqual(result.errors, [], f"template pair does not resolve: {result.errors}")
            self.assertEqual(result.spec, (root / "docs/agentic-sdlc/specs/w1.md").resolve())


SAVE_OPENER = "**Saving the spec and plan.**"
SAVE_RULES = (
    "the workflow and the author return only the body",
    "`reviewed` means the author⇄critic loop has finished, not that the draft is approvable",
    "with the file-edit tool",
    "never a shell redirect or script",
)


class TestSaveRule(unittest.TestCase):
    def test_pipeline_states_how_the_artifacts_are_saved(self):
        text = read(PIPELINE)
        para = paragraph(text, SAVE_OPENER)
        self.assertIsNotNone(para, f"{PIPELINE} has no `{SAVE_OPENER}` paragraph")
        self.assertLess(text.index(SAVE_OPENER), text.index("**Approval receipt.**"))
        for rule in SAVE_RULES:
            with self.subTest(rule=rule[:40]):
                self.assertIn(rule, para)
        for key in VALIDATOR.FRONTMATTER_REQUIRED["spec"] + VALIDATOR.FRONTMATTER_REQUIRED["plan"]:
            with self.subTest(key=key):
                self.assertIn(f"`{key}`", para)

    def test_playbook_gates_name_the_file_edit_tool(self):
        text = read(PLAYBOOK)
        for opener in ("**Spec Review gate:**", "**Plan Review gate:**"):
            with self.subTest(gate=opener):
                para = paragraph(text, opener)
                self.assertIsNotNone(para)
                self.assertIn("with the file-edit tool", para.split("\n", 1)[0])


class TestCallOrderGuardIsRuntimeNeutral(unittest.TestCase):
    """A runtime without a `Skill` tool activates `dispatch-strategy` by reading its SKILL.md."""

    def test_pipeline_guard_names_the_codex_activation(self):
        para = paragraph(read(PIPELINE), "**Call-order guard:**")
        self.assertIsNotNone(para)
        self.assertIn("`Skill` -> `agentic-sdlc:dispatch-strategy`", para)
        self.assertIn("in Codex and the other adapters", para)
        self.assertIn("reading its `SKILL.md` counts", para)
        self.assertIn("A runtime without a `Skill` tool is not a reason to stop.", para)

    def test_focused_skill_guards_name_the_codex_activation(self):
        for skill in GUARDED_FOCUSED_SKILLS:
            with self.subTest(skill=skill):
                para = paragraph(read(f"skills/{skill}/SKILL.md"), f"After loading `{skill}`,")
                self.assertIsNotNone(para)
                self.assertIn("`Skill` -> `agentic-sdlc:dispatch-strategy`", para)
                self.assertIn("in a runtime without a `Skill` tool, read the installed "
                              "`dispatch-strategy` `SKILL.md`", para)


class TestDegradedPathContinues(unittest.TestCase):
    def test_missing_mechanism_is_not_a_stop(self):
        para = paragraph(read(PIPELINE), "## Runtime invocation contract")
        self.assertIsNotNone(para)
        self.assertIn("then perform the smallest safe fallback without weakening deterministic gates", para)
        self.assertIn("and continue the run in the same turn", para)
        self.assertIn("is never by itself a reason to stop or to ask the user", para)


class TestBranchCheckpointWording(unittest.TestCase):
    def test_publishing_limits_do_not_forbid_a_branch(self):
        para = paragraph(read(PIPELINE), "**Branch checkpoint (both runtimes):**")
        self.assertIsNotNone(para)
        self.assertIn("no-commit does not mean no-branch", para)
        self.assertIn("leave the changes uncommitted in the working tree", para)
        self.assertIn("limit publishing, not branching", para)


if __name__ == "__main__":
    unittest.main()
