"""Guards for the v0.3.0 originality / public-readiness work.

These lock the spec acceptance criteria:
- banned superpowers-derived headings absent from the runnable product surface (AC #1)
- the Assertion-contract sections present on full-conversion skills (AC #3)
- OpenCode/Kimi/GLM removed from skills, and only in future-work context in scoped docs (AC #2)
- .github maintenance files present with evidence fields (AC #8)
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# --- AC #1: banned terms absent from the runnable product surface ---
BANNED = ("Iron Law", "Red Flags", "Rationalizations")

# Runnable product surface only — NOT local audit reports, NOT this guard, NOT rationale spec/plan.
PRODUCT_SURFACE = [
    REPO / "skills",
    REPO / "hooks" / "session-start.mjs",
    REPO / "hooks" / "session-start-codex.mjs",
    REPO / "README.md",
    REPO / ".claude-plugin" / "README.md",
    REPO / ".codex-plugin" / "README.md",
    REPO / "docs" / "release-readiness.md",
    REPO / "docs" / "runtime-adapter.md",
    REPO / "docs" / "plugin-readme.md",
]


def _surface_files(paths):
    for p in paths:
        if p.is_dir():
            yield from p.rglob("*.md")
        elif p.exists():
            yield p


class TestBannedTermsAbsent(unittest.TestCase):
    def test_no_borrowed_headings_on_product_surface(self):
        hits = []
        for f in _surface_files(PRODUCT_SURFACE):
            text = f.read_text(encoding="utf-8")
            for term in BANNED:
                if term in text:
                    hits.append(f"{f.relative_to(REPO)}: {term}")
        self.assertEqual(hits, [], f"banned terms on product surface: {hits}")


# --- AC #3: Assertion-contract sections present on full-conversion skills ---
FULL_CONVERSION = [
    "root-cause-fix", "safe-refactor", "test-authoring", "security-audit",
    "code-quality-review", "implementasyon-control", "feature-build",
]
REQUIRED_SECTIONS = ("## Invariant", "## Tripwires", "## Proof", "## Excuse → check")


class TestAssertionContractSections(unittest.TestCase):
    def test_full_conversion_skills_have_all_sections(self):
        missing = []
        for name in FULL_CONVERSION:
            text = (REPO / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
            for section in REQUIRED_SECTIONS:
                if section not in text:
                    missing.append(f"{name}: {section}")
        self.assertEqual(missing, [], f"missing Assertion-contract sections: {missing}")


# --- AC #2: Claude+Codex-only scope ---
OTHER_RUNTIMES = ("OpenCode", "Kimi", "GLM")
FUTURE_MARKERS = ("future", "unsupported", "experimental", "deferred", "not a release target", "not release")
TRIMMED_SKILLS = [
    "using-agentic-sdlc", "spec-authoring", "plan-authoring", "dispatch-strategy",
    "mind-spark", "agentic-sdlc-pipeline",
]
SCOPED_DOCS = [
    REPO / "docs" / "runtime-adapter.md",
    REPO / "docs" / "release-readiness.md",
    REPO / "docs" / "plugin-readme.md",
]


class TestRuntimeScopeTrim(unittest.TestCase):
    def test_trimmed_skills_have_no_other_runtimes(self):
        bad = []
        for name in TRIMMED_SKILLS:
            for f in (REPO / "skills" / name).rglob("*.md"):
                text = f.read_text(encoding="utf-8")
                for term in OTHER_RUNTIMES:
                    if term in text:
                        bad.append(f"{f.relative_to(REPO)}: {term}")
        self.assertEqual(bad, [], f"unsupported runtimes still referenced in skills: {bad}")


class TestDocRuntimeScope(unittest.TestCase):
    def test_other_runtimes_only_in_future_work_context(self):
        bad = []
        for f in SCOPED_DOCS:
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if any(t in line for t in OTHER_RUNTIMES):
                    low = line.lower()
                    if not any(m in low for m in FUTURE_MARKERS):
                        bad.append(f"{f.relative_to(REPO)}:{i}: {line.strip()}")
        self.assertEqual(bad, [], f"runtime mention outside future-work context: {bad}")


# --- AC #8: .github maintenance files ---
class TestGithubMaintenance(unittest.TestCase):
    EXPECTED = [
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/ISSUE_TEMPLATE/bug_report.md",
        ".github/ISSUE_TEMPLATE/feature_request.md",
        ".github/ISSUE_TEMPLATE/config.yml",
        "CONTRIBUTING.md",
    ]

    def test_files_exist(self):
        missing = [p for p in self.EXPECTED if not (REPO / p).exists()]
        self.assertEqual(missing, [], f"missing maintenance files: {missing}")

    def test_pr_template_has_evidence_fields(self):
        pr = (REPO / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text(encoding="utf-8").lower()
        for field in ("test", "security", "evidence"):
            self.assertIn(field, pr)


class TestDepthForcingPresent(unittest.TestCase):
    def test_spec_plan_authoring_carry_depth_block(self):
        for name in ("spec-authoring", "plan-authoring"):
            text = (REPO / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("## Depth contract", text)
            self.assertIn("## Excuse → check".replace("→", "->"), text)  # arrow ASCII in these blocks
            self.assertIn("No placeholders", text)


if __name__ == "__main__":
    unittest.main()
