"""T11 — evidence-persist wiring (prose) + AC24 overwrite behavior.

These tests pin the *documented* contract that the Final Implementation Report
is persisted to the per-package evidence path by the MAIN pipeline/finalize step
(never by the read-only implementation-auditor sub-agent), plus the resolver's
`evidence_path` overwrite/flat-rejection behavior (AC24/AC11).

The auditor-stays-read-only test guards against the write being (wrongly)
assigned to the read-only sub-agent (plan §0 / DP-6, contract at L3/L36).
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
RESOLVER = REPO / "scripts" / "resolve_work_package.py"

# The canonical per-package evidence path form, written verbatim into the prose.
EVIDENCE_PATH_FORM = "docs/agentic-sdlc/<slug>/evidence/<work_id>.md"

# The four prose files T11 wires the evidence-persist contract into.
PROSE_FILES = [
    REPO / "skills" / "agentic-sdlc-pipeline" / "playbook.md",
    REPO / "skills" / "agentic-sdlc-pipeline" / "SKILL.md",
    REPO / "skills" / "agentic-sdlc-pipeline" / "templates.md",
    REPO / "skills" / "implementation-control" / "SKILL.md",
]

# Markers each prose file must carry (lowercased substring match):
#  - the canonical evidence path form
#  - per-package-only + overwrite-in-place wording
#  - slug-from-resolver (the slug resolve_work_package.py emits, BR14/AC23)
#  - write-by-main-finalize-step, explicitly NOT the read-only auditor (§8/DP-6)
REQUIRED_MARKERS = (
    EVIDENCE_PATH_FORM.lower(),
    "per-package",
    "overwrit",
    "resolve_work_package.py",
    "finalize step",
    "not the read-only",
    "implementation-auditor",
)


def _load_resolver():
    spec = importlib.util.spec_from_file_location("resolve_work_package", RESOLVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestEvidencePersistProse(unittest.TestCase):
    def test_skills_document_per_package_evidence_path(self):
        missing = []
        for f in PROSE_FILES:
            text = f.read_text(encoding="utf-8").lower()
            for marker in REQUIRED_MARKERS:
                if marker not in text:
                    missing.append(f"{f.relative_to(REPO)}: {marker!r}")
        self.assertEqual(missing, [], f"evidence-persist prose missing markers: {missing}")


class TestAuditorStaysReadOnly(unittest.TestCase):
    def test_auditor_contract_stays_read_only(self):
        auditor = REPO / "agents" / "implementation-auditor.md"
        text = auditor.read_text(encoding="utf-8")
        # The L36 read-only limit must survive untouched.
        self.assertIn("never modify code", text)
        low = text.lower()
        # The read-only auditor must NOT gain an evidence-write instruction:
        # the per-package evidence path or any persist/overwrite directive would
        # mean the write was (wrongly) assigned to the read-only sub-agent.
        forbidden = ["docs/agentic-sdlc/<slug>/evidence/", "persist", "overwrit"]
        leaked = [tok for tok in forbidden if tok in low]
        self.assertEqual(leaked, [], f"auditor gained evidence-write wording: {leaked}")


class TestEvidenceRerunOverwrites(unittest.TestCase):
    def test_evidence_path_is_the_same_canonical_file_on_a_rerun(self):
        # Renamed. The old name claimed to pin rerun-OVERWRITE behaviour, but the overwrite was
        # performed by this test's own two `write_text` calls - no writer is under test here.
        # What it actually pins, and all it can pin, is that `evidence_path()` resolves to one
        # canonical path with no timestamp or run id, so a second run lands on the same file.
        # The finalize step that does the writing is covered by the pipeline suites.
        mod = _load_resolver()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            slug, work_id = "demo-pkg", "demo-pkg"

            first = mod.evidence_path(repo, slug, work_id)
            first.parent.mkdir(parents=True, exist_ok=True)
            first.write_text("run-1 evidence", encoding="utf-8")

            # A second run computes the SAME canonical path (no timestamp/run id).
            second = mod.evidence_path(repo, slug, work_id)
            self.assertEqual(first, second)
            second.write_text("run-2 evidence", encoding="utf-8")

            evidence_dir = repo / "docs" / "agentic-sdlc" / slug / "evidence"
            files = sorted(evidence_dir.glob("*.md"))
            self.assertEqual(
                len(files), 1, f"expected exactly one canonical evidence file, got {files}"
            )
            self.assertEqual(files[0].read_text(encoding="utf-8"), "run-2 evidence")

    def test_evidence_path_rejects_flat_slugless_call(self):
        mod = _load_resolver()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            # Flat resolutions report no slug → no evidence path (AC11).
            for bad_slug in (None, "", "specs", "Bad-Slug"):
                with self.assertRaises(ValueError):
                    mod.evidence_path(repo, bad_slug, "demo-pkg")


if __name__ == "__main__":
    unittest.main()
