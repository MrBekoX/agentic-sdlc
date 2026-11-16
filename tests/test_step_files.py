"""The step files the flow manifests name (plan Task 16): skills/<skill>/steps/*.md.

A card prints the current step's file inline after its header (contract §14, design §5.13), so
these files are what the model reads at each step. They carry the work of the step, not the
orchestration: the runner and the manifests decide what runs next, so a step file names no skill
and no flow; the card's `delegate=` and `mechanism=` lines carry what differs per runtime, so a
step file has no runtime-specific branch. Each is at most 120 lines, and with the real card header
of every flow and work type that uses it, it fits the 8000-byte card without a cut.
"""
import json
import re
import shutil
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"
for folder in (REPO / "scripts", TESTS):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from test_sdlc_engine import SPEC_BODY, EngineCase  # noqa: E402
from sdlc_runner import card, engine, manifest  # noqa: E402

FLOWS = sorted(p for p in (REPO / "flows").glob("*.json") if p.name != "_shared.json")
FLOW_IDS = [p.stem for p in FLOWS]
SKILLS = sorted(p.name for p in (REPO / "skills").iterdir() if (p / "SKILL.md").is_file())
RUNTIME_NAMES = ("Claude Code", "Codex", "Kimi", "Grok", "ZCode", "Cursor", "Antigravity")
MAX_LINES = 120


def _flow(path):
    return json.loads(path.read_text(encoding="utf-8"))


def step_files():
    """Every step file a manifest names (the implement step names one per work type)."""
    found = set()
    for path in FLOWS:
        for step in _flow(path)["steps"]:
            value = step.get("file")
            if isinstance(value, dict):
                found.update(v for v in value.values() if isinstance(v, str))
            elif isinstance(value, str):
                found.add(value)
    return sorted(found)


def _text(rel):
    return (REPO / rel).read_text(encoding="utf-8")


class TestStepFiles(unittest.TestCase):
    def test_every_manifest_step_file_exists(self):
        for path in FLOWS:
            with self.subTest(flow=path.stem):
                self.assertEqual(manifest.validate_flow(_flow(path), REPO, check_files=True), [])

    def test_every_step_file_is_named_by_a_manifest(self):
        found = sorted(p.relative_to(REPO).as_posix() for p in REPO.glob("skills/*/steps/*.md"))
        self.assertEqual(found, step_files())

    def test_step_files_name_no_skill_or_flow(self):
        flow_ref = re.compile(r"\b(?:%s) flow\b|flows/" % "|".join(map(re.escape, FLOW_IDS)), re.I)
        for rel in step_files():
            text = _text(rel)
            with self.subTest(step=rel):
                for skill in SKILLS:
                    self.assertIsNone(re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(skill), text), skill)
                self.assertIsNone(flow_ref.search(text))

    def test_step_files_under_120_lines(self):
        for rel in step_files():
            with self.subTest(step=rel):
                self.assertLessEqual(len(_text(rel).splitlines()), MAX_LINES)

    def test_no_runtime_specific_branches_in_step_files(self):
        for rel in step_files():
            text = _text(rel)
            for name in RUNTIME_NAMES:
                with self.subTest(step=rel, runtime=name):
                    self.assertNotIn(name, text)

    def test_each_step_file_says_what_its_checks_need(self):
        # A `report` check needs its header line (and a verdict line where one is set); a
        # `run_recorded` check needs `sdlc run` with that label. The step file must say so, or the
        # model cannot pass the check from the card alone.
        for path in FLOWS:
            for step in _flow(path)["steps"]:
                value = step.get("file")
                pairs = list(value.items()) if isinstance(value, dict) else [(None, value)] if value else []
                for spec in step.get("done_when") or []:
                    for work_type, rel in pairs:
                        if work_type and spec.get("work_types") and work_type not in spec["work_types"]:
                            continue
                        with self.subTest(flow=path.stem, step=step["id"], check=spec["check"], file=rel):
                            text = _text(rel)
                            if spec["check"] == "report":
                                self.assertIn(spec["header"], text)
                                if spec.get("verdict"):
                                    self.assertIn(spec["verdict"], text)
                            elif spec["check"] == "run_recorded":
                                self.assertIn("--label %s" % spec["label"], text)
                                if spec.get("expect") == "fail":
                                    self.assertIn("--expect fail", text)


class TestCardBudget(EngineCase):
    """Every step of every flow and work type, rendered with its real card header."""

    def make_root(self, root, shared_edit=None):
        root = super().make_root(root, shared_edit)
        for rel in step_files():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(REPO / rel), str(target))
        return root

    def test_card_with_each_step_fits_budget(self):
        rendered = 0
        for path in FLOWS:
            flow = _flow(path)
            for work_type in flow["work_types"]:
                slug = "%s-%s" % (path.stem, work_type)
                extra = ()
                if path.stem == "plan":  # the plan flow starts from an approved spec it imports
                    spec = self.tmp / ("%s.md" % slug)
                    spec.write_bytes(("---\nwork_id: %s\nstatus: approved\n---\n" % slug + SPEC_BODY).encode("utf-8"))
                    extra = ("--spec-file", str(spec))
                with self.subTest(flow=path.stem, work_type=work_type, start=True):
                    self.start(*extra, flow=path.stem, work_type=work_type, work_id=slug)
                ctx = engine.load_context(self.project, self.root, slug)
                for step in ctx.flow["steps"]:
                    text = card.render(ctx, "do", step, {})
                    with self.subTest(flow=path.stem, work_type=work_type, step=step["id"]):
                        self.assertNotIn("[cut:", text)
                        self.assertNotIn("[step file missing", text)
                        self.assertLessEqual(len(text.encode("utf-8")), card.CARD_BUDGET)
                    rendered += 1
        self.assertGreater(rendered, 60)


if __name__ == "__main__":
    unittest.main()
