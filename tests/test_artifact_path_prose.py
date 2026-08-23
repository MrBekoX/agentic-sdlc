"""T14 — dual-layout + evidence-role path prose across the doc set.

Asserts that the named documentation files describe BOTH artifact layouts
(flat back-compat + per-package canonical), the per-package evidence role
(per-package-only, overwrite-per-run, untracked/git-ignored, no validator,
written by the main finalize step — not the read-only auditor), and that
per-package plan change-detection is documented as a FILESYSTEM SCAN.

No doc may claim per-package plans are detectable via `git status` (DP-1):
the `docs/` tree is git-ignored, so the resolver scans the filesystem instead.

Assertions are scoped to the named files (not a repo-wide sweep) to avoid
brittleness, per the plan's T14 RED-test note.
"""
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]

# Dual-layout path form: every named file must describe the per-package canonical root.
PER_PACKAGE_PATH_FORM = "docs/agentic-sdlc/<slug>/"
EVIDENCE_PATH_FORM = "docs/agentic-sdlc/<slug>/evidence/<work_id>.md"

# Files that get dual-layout path prose (path form must appear). Includes the
# spec/plan authoring skills, which get path prose but not the full evidence role.
PER_PACKAGE_PATH_FILES = [
    "skills/agentic-sdlc-pipeline/SKILL.md",
    "skills/agentic-sdlc-pipeline/playbook.md",
    "skills/agentic-sdlc-pipeline/templates.md",
    "skills/spec-authoring/SKILL.md",
    "skills/plan-authoring/SKILL.md",
    "hooks/session-start-codex.mjs",
    "hooks/README.md",
    ".claude-plugin/README.md",
    ".codex-plugin/README.md",
    "README.md",
    "docs/release-readiness.md",
    "docs/testing.md",
    "docs/troubleshooting.md",
    "docs/skill-boundaries.md",
    "docs/runtime-adapter.md",
    "docs/claude-code-runtime.md",
    "docs/plugin-readme.md",
]

# Files that additionally carry the per-package evidence role (everything except
# the WHAT/HOW authoring skills, which only describe the artifact paths).
EVIDENCE_ROLE_FILES = [
    f for f in PER_PACKAGE_PATH_FILES
    if f not in ("skills/spec-authoring/SKILL.md", "skills/plan-authoring/SKILL.md")
]

EVIDENCE_ROLE_MARKERS = (
    EVIDENCE_PATH_FORM.lower(),
    "per-package",
    "overwrit",
    "git-ignored",
    "no validator",
    "not the read-only",
)

# A representative subset that must spell out the DP-1 change-detection mechanism.
FILESYSTEM_SCAN_FILES = [
    "README.md",
    "docs/plugin-readme.md",
    "docs/runtime-adapter.md",
    "docs/testing.md",
    "skills/agentic-sdlc-pipeline/playbook.md",
]

# Affirmative claims that per-package plans are git-status-detectable — forbidden
# everywhere (DP-1). Phrased to match only the WRONG claim, never the documented
# contrast ("filesystem scan, not a git status query").
FORBIDDEN_GIT_DETECT = (
    "detectable via git status",
    "detectable by git status",
    "detected by git status",
    "git status detects",
    "git-status-detectable",
    "git status can see per-package",
    "git status surfaces per-package",
)


def _read(rel):
    return (REPO / rel).read_text(encoding="utf-8")


class TestArtifactPathProse(unittest.TestCase):
    def test_docs_describe_per_package_layout(self):
        missing = [
            rel for rel in PER_PACKAGE_PATH_FILES
            if PER_PACKAGE_PATH_FORM not in _read(rel)
        ]
        self.assertEqual(missing, [], f"per-package path form missing from: {missing}")

    def test_docs_describe_evidence_role(self):
        missing = []
        for rel in EVIDENCE_ROLE_FILES:
            text = _read(rel).lower()
            for marker in EVIDENCE_ROLE_MARKERS:
                if marker not in text:
                    missing.append(f"{rel}: {marker!r}")
        self.assertEqual(missing, [], f"evidence-role markers missing: {missing}")

    def test_change_detection_documented_as_filesystem_scan(self):
        missing = [
            rel for rel in FILESYSTEM_SCAN_FILES
            if "filesystem scan" not in _read(rel).lower()
        ]
        self.assertEqual(missing, [], f"'filesystem scan' missing from: {missing}")

    def test_no_doc_claims_per_package_plans_are_git_status_detectable(self):
        offenders = []
        for rel in PER_PACKAGE_PATH_FILES:
            low = _read(rel).lower()
            for phrase in FORBIDDEN_GIT_DETECT:
                if phrase in low:
                    offenders.append(f"{rel}: {phrase!r}")
        self.assertEqual(offenders, [], f"git-status-detectable claim present: {offenders}")


if __name__ == "__main__":
    unittest.main()
