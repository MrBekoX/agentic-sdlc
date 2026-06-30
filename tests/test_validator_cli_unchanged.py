"""AC17 — validator CLI characterization (T13, GREEN-only, no RED).

This is a non-regression invariant, not a missing behavior: ``validate_artifacts.py``
is in the must-not-change set and must stay path-agnostic. A flat
(``docs/agentic-sdlc/specs/x.md``) and a per-package (``docs/agentic-sdlc/x/spec/x.md``)
spec of EQUAL content must produce an identical exit code and verdict — the validator
emits no path, so nothing layout-specific can leak into the result — and the
``--mode/--file/--spec/--strict`` flags must still parse. If a later task ever couples
the validator to layout, this pins the regression.

Self-contained: the validator is loaded/invoked by path, like the resolver tests.
"""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO = HERE.parent
VALIDATOR = REPO / "scripts" / "validate_artifacts.py"

# A complete spec so the non-strict verdict is `passed`; identical bytes are written
# under both layouts, so any warnings/errors (and their line numbers) match exactly.
SPEC_BODY = """---
work_id: x
status: reviewed
---

# X Spec

## 1. Problem
The resolver and its consumers must deterministically identify one spec/plan pair and
must never select an artifact by modification time. This states the concrete problem.

## 2. Business rules
- BR1 — Artifacts live under a recognized root and are paired by frontmatter work_id.
- BR2 — Selection never depends on file modification time, in either layout.

## 3. Acceptance criteria
- AC1. Given an explicit plan path, when the resolver runs, then it returns that plan
  and the spec named by its frontmatter.
- AC2. Given a path outside the recognized roots, when the resolver runs, then it
  exits failed and never partial-guesses.

## 4. Edge cases
- An empty spec directory with zero markdown files is treated as role-absent, not an
  error condition the resolver must report.
- A symlink whose target resolves outside the roots is rejected after resolution.

## 5. Definition of done
- Resolver unit tests cover explicit plan, explicit spec, branch match, and traversal
  rejection, and the full local gate passes for both layouts.

## 6. Must-not-change
- The content validator keeps its existing path-agnostic CLI contract and is never
  asked to understand the artifact layout.
"""


def _load_validator():
    spec = importlib.util.spec_from_file_location("validate_artifacts", VALIDATOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _validate(file_path, *extra):
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR), "--mode", "spec", "--file", str(file_path), *extra],
        capture_output=True, text=True, encoding="utf-8",
    )
    return proc.returncode, proc.stdout, proc.stderr


class TestValidatorCliUnchanged(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_equal_layouts(self):
        flat = self.root / "docs" / "agentic-sdlc" / "specs" / "x.md"
        per_package = self.root / "docs" / "agentic-sdlc" / "x" / "spec" / "x.md"
        for f in (flat, per_package):
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(SPEC_BODY, encoding="utf-8")
        return flat, per_package

    def test_validator_verdict_is_layout_agnostic(self):
        flat, per_package = self._write_equal_layouts()
        rc_flat, out_flat, err_flat = _validate(flat)
        rc_pp, out_pp, err_pp = _validate(per_package)
        # Identical content under either layout → identical exit code and full output
        # (the validator never echoes the path).
        self.assertEqual(rc_flat, rc_pp, f"flat={out_flat+err_flat}\npp={out_pp+err_pp}")
        self.assertEqual(out_flat, out_pp)
        # And the verdict itself is the same `passed` line regardless of layout.
        self.assertIn("artifacts_validation=passed", out_flat)
        self.assertIn("artifacts_validation=passed", out_pp)
        self.assertEqual(rc_flat, 0, out_flat + err_flat)

    def test_validator_verdict_layout_agnostic_under_strict(self):
        flat, per_package = self._write_equal_layouts()
        rc_flat, out_flat, _ = _validate(flat, "--strict")
        rc_pp, out_pp, _ = _validate(per_package, "--strict")
        # --strict promotes warnings to errors equally; the layout must not change the
        # outcome for equal content.
        self.assertEqual(rc_flat, rc_pp)
        self.assertEqual(out_flat, out_pp)

    def test_cli_flags_still_parse(self):
        # The --mode/--file/--spec/--strict surface must remain intact (path-agnostic).
        mod = _load_validator()
        ns = mod.build_parser().parse_args(
            ["--mode", "spec", "--file", "a.md", "--spec", "b.md", "--strict"]
        )
        self.assertEqual(ns.mode, "spec")
        self.assertEqual(ns.file, "a.md")
        self.assertEqual(ns.spec, "b.md")
        self.assertTrue(ns.strict)


if __name__ == "__main__":
    unittest.main()
