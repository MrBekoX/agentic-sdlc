"""Tests for validate_artifacts.py — the deterministic spec/plan validator.

Each behavior is asserted BOTH in-process (call the functions directly) AND via
the subprocess CLI (exit code + exact key=value substrings). Stdlib `unittest`
only — runnable with `python -m unittest`.

The validator lives at ../scripts/validate_artifacts.py relative to this file.
We import it by path so the test suite stays independent of cwd / sys.path setup.
"""

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "validate_artifacts.py"


def _load_module():
    """Load validate_artifacts.py by path so tests don't depend on cwd.

    Register it in sys.modules too, so the in-method `from validate_artifacts
    import ...` statements resolve to this same instance.
    """
    spec = importlib.util.spec_from_file_location("validate_artifacts", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules["validate_artifacts"] = mod
    return mod


va = _load_module()


def run_cli(*args):
    """Run the validator via subprocess; return (returncode, stdout, stderr)."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True, encoding="utf-8",
    )
    return proc.returncode, proc.stdout, proc.stderr


# A complete, scanner-clean spec fixture. Deliberately contains NO TODO/TBD/FIXME/XXX
# tokens and NO secret-shaped lines, so the placeholder/secret scanner stays silent.
COMPLETE_SPEC = """\
# Sample Spec

## 1. Problem
The reconciliation job double-counts refunds, so the daily ledger is wrong and
finance cannot close the books. We need a deterministic fix with clear rules.

## 2. Business rules
A refund reduces the gross total exactly once. Currency rounding follows the
banker's rounding rule. Each transaction id is unique within a settlement day.

## 3. Acceptance criteria
- Given a refund for an existing charge, when the job runs, then the gross total
  is reduced by the refund amount exactly once.
- Given a duplicate refund event, when the job runs, it returns the prior result
  and does not double-reduce the total.
- Given an empty settlement file, the job returns an empty ledger -> exit 0.

## 4. Edge cases
Empty file, null amount, a refund larger than the original charge, and two
refunds for the same charge arriving out of order are all handled explicitly.

## 5. Definition of done
All acceptance criteria pass in CI; the full suite is green; the runbook is
updated; and finance signs off on a sample day.

## 7. Must-not-change (regression surface)
The existing settlement file format and the public ledger API stay identical.
No change to the nightly schedule.
"""


class TestCli(unittest.TestCase):
    def test_cli_unknown_mode_exits_2(self):
        # argparse rejects an invalid choice with exit code 2 (usage error).
        rc, out, err = run_cli("--mode", "bogus", "--file", str(SCRIPT))
        self.assertEqual(rc, 2)

    def test_emit_lines_are_sorted_key_value(self):
        # emit() must print sorted flat key=value lines, one per line.
        from io import StringIO

        buf = StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            va.emit({"mode": "spec", "artifacts_validation": "passed", "zebra": "1"})
        finally:
            sys.stdout = old
        lines = [ln for ln in buf.getvalue().splitlines() if ln]
        self.assertEqual(lines, sorted(lines))
        for ln in lines:
            self.assertIn("=", ln)
        self.assertIn("artifacts_validation=passed", lines)
        self.assertIn("mode=spec", lines)


class TestSpecChecks(unittest.TestCase):
    def _write(self, tmp, text, name="spec.md"):
        p = Path(tmp) / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_spec_missing_mustnotchange_exits_nonzero(self):
        spec_no_mnc = COMPLETE_SPEC.replace(
            "## 7. Must-not-change (regression surface)",
            "## 7. Notes",
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write(tmp, spec_no_mnc)
            # In-process
            result = va.check_spec(spec_no_mnc)
            self.assertTrue(
                any(e.startswith("missing_section:must-not-change") for e in result["errors"]),
                result["errors"],
            )
            # CLI
            rc, out, err = run_cli("--mode", "spec", "--file", str(p))
            self.assertNotEqual(rc, 0)
            self.assertIn("artifacts_validation=failed", out)
            self.assertIn("error=missing_section:must-not-change", out)

    def test_complete_spec_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write(tmp, COMPLETE_SPEC)
            rc, out, err = run_cli("--mode", "spec", "--file", str(p))
            self.assertEqual(rc, 0, out + err)
            self.assertIn("artifacts_validation=passed", out)
            self.assertIn("mode=spec", out)

    def test_numbered_annotated_headings_detected(self):
        # A heading like "## 7. Must-not-change (regression surface)" must be
        # detected: strip leading "7." numbering and trailing "(...)" before match.
        result = va.check_spec(COMPLETE_SPEC)
        self.assertFalse(
            any(e.startswith("missing_section:must-not-change") for e in result["errors"]),
            result["errors"],
        )
        # And the numbered "Acceptance criteria" / "Business rules" too.
        for missing in ("missing_section:business-rules", "missing_section:acceptance-criteria"):
            self.assertFalse(
                any(e.startswith(missing) for e in result["errors"]), result["errors"]
            )

    def test_vague_criterion_warns(self):
        # An acceptance-criteria bullet with no testable marker warns.
        vague = COMPLETE_SPEC.replace(
            "- Given an empty settlement file, the job returns an empty ledger -> exit 0.",
            "- The system should work well and be fast.",
        )
        result = va.check_spec(vague)
        self.assertTrue(
            any(w.startswith("untestable_criterion:") for w in result["warnings"]),
            result["warnings"],
        )


class TestScanner(unittest.TestCase):
    def _write(self, tmp, text, name="art.md"):
        p = Path(tmp) / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_placeholder_warns_strict_fails(self):
        text = COMPLETE_SPEC + "\n\n## Notes\nTODO: finish the runbook.\n"
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write(tmp, text)
            # Non-strict: placeholder is a warning, spec is otherwise complete -> exit 0.
            rc, out, err = run_cli("--mode", "spec", "--file", str(p))
            self.assertEqual(rc, 0, out + err)
            self.assertIn("warning=placeholder:", out)
            # Strict: every warning becomes an error -> non-zero.
            rc2, out2, err2 = run_cli("--mode", "spec", "--file", str(p), "--strict")
            self.assertNotEqual(rc2, 0)
            self.assertIn("error=placeholder:", out2)
            self.assertIn("artifacts_validation=failed", out2)

    def test_secret_is_masked_never_printed(self):
        secret_val = "AKIA" + "IOSFODNN7EXAMPLE"  # AKIA + 16 chars — matches the AWS key pattern.
        text = COMPLETE_SPEC + f"\n\n## Config\naws_key = {secret_val}\n"
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write(tmp, text)
            rc, out, err = run_cli("--mode", "spec", "--file", str(p))
            self.assertNotEqual(rc, 0)
            self.assertIn("error=possible_secret:", out)
            self.assertIn("***MASKED***", out)
            # The real secret value must never appear in any output stream.
            self.assertNotIn(secret_val, out)
            self.assertNotIn(secret_val, err)

    def test_high_entropy_prose_does_not_fire(self):
        # Random-looking but non-secret prose must NOT trip the scanner (no entropy
        # detector by design — DP-3 uses explicit patterns only).
        text = COMPLETE_SPEC + (
            "\n\n## Appendix\n"
            "The build hash zxQ9vKpLmN3rTwAa appears in the artifact manifest and\n"
            "the correlation id f8Hj2Lq7Pw is logged for tracing. Neither is a credential.\n"
        )
        result = va.scan_placeholders_and_secrets(text)
        self.assertFalse(
            any(e.startswith("possible_secret:") for e in result["errors"]),
            result["errors"],
        )

    def test_modern_provider_tokens_flagged_and_masked(self):
        # Sync with hooks/secret-patterns.mjs HIGH: provider-prefix tokens must trip the scanner
        # even on a bare `value = <token>` line (no api_key/secret/token keyword). Values are
        # synthetic (repeated 'a1B2'), never real secrets, and must be masked in any output.
        tokens = [
            "ghp_" + "a1B2" * 9,
            "github_pat_" + "a1B2" * 12,
            "xoxb-" + "1a2B3c4D5e6F",
            "sk_live_" + "a1B2" * 5,
            "AIza" + "a1B2" * 8 + "abc",
            "sk-" + "a1B2" * 6,
            ".".join(["eyJa1B2a1B2", "eyJc3D4c3D4", "e5F6e5F6"]),
        ]
        for token in tokens:
            with self.subTest(token=token[:8]):
                text = COMPLETE_SPEC + f"\n\n## Config\nvalue = {token}\n"
                result = va.scan_placeholders_and_secrets(text)
                self.assertTrue(
                    any(e.startswith("possible_secret:") for e in result["errors"]),
                    f"{token[:8]}... not flagged: {result['errors']}",
                )
                self.assertTrue(
                    all(token not in e for e in result["errors"]),
                    f"raw token leaked into error output for {token[:8]}...",
                )

    def test_complete_spec_still_exits_zero_after_scanner(self):
        # The clean fixture must remain scanner-clean: no placeholder, no secret.
        result = va.scan_placeholders_and_secrets(COMPLETE_SPEC)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["warnings"], [])

    def test_placeholder_in_code_skipped_but_prose_flagged(self):
        # A doc that DESCRIBES the tokens (inline-code + a fenced example) must not be
        # flagged; only the real prose leftover counts as a placeholder.
        text = (
            COMPLETE_SPEC
            + "\n\n## Scanner\n"
            + "The scanner matches `TODO|TBD|FIXME|XXX` tokens.\n"   # inline-code -> skipped
            + "```\nTODO: illustrative example only\n```\n"           # fenced -> skipped
            + "Leftover: TODO write the runbook.\n"                   # prose -> flagged
        )
        result = va.scan_placeholders_and_secrets(text)
        ph = [w for w in result["warnings"] if w.startswith("placeholder:")]
        self.assertEqual(len(ph), 1, result["warnings"])

    def test_secret_in_fenced_block_still_flagged(self):
        # Security must not be weakened: a real secret inside a code fence is still a leak.
        secret_val = "AKIA" + "IOSFODNN7EXAMPLE"
        text = COMPLETE_SPEC + f"\n\n## Example\n```\naws_key = {secret_val}\n```\n"
        result = va.scan_placeholders_and_secrets(text)
        self.assertTrue(
            any(e.startswith("possible_secret:") for e in result["errors"]),
            result["errors"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write(tmp, COMPLETE_SPEC)
            rc, out, err = run_cli("--mode", "spec", "--file", str(p))
            self.assertEqual(rc, 0, out + err)
            self.assertIn("artifacts_validation=passed", out)


# A full-coverage plan fixture: every AC in COMPLETE_SPEC (none here) — we use a
# dedicated mini spec for plan tests so AC ids are deterministic.
PLAN_SPEC = """\
# Mini Spec
## Acceptance criteria
- AC1: given a refund, then the total is reduced once.
- AC2: given a duplicate, it returns the prior result -> exit 0.
"""

PLAN_FULL = """\
# Mini Plan

## Task 1 — Reduce total once (AC1)
Create `src/ledger.py`. Write a failing test (RED) first, then the minimal fix.
Run: pytest tests/test_ledger.py

## Task 2 — Dedup refunds (AC2)
Modify `src/ledger.py`. TDD: add a failing test for the duplicate path, then GREEN.
Run: pytest tests/test_ledger.py
"""

PLAN_UNCOVERED = """\
# Mini Plan

## Task 1 — Reduce total once (AC1)
Create `src/ledger.py`. Write a failing test (RED) first, then the minimal fix.
"""

# A plan with 2 real tasks plus noise that a naive detector over-counts: a numbered
# decision-point list and a coverage line full of prose task-id references.
PLAN_NOISY = """\
# Mini Plan

## Task 1 — Reduce total once (AC1)
Create `src/ledger.py`. Write a failing test (RED) first.

## Task 2 — Dedup refunds (AC2)
Modify `src/ledger.py`. TDD: failing test then GREEN.

## Decision points
1. DP-1: pick option A — this numbered item is not a task.
2. DP-2: pick option B — neither is this.

## Coverage
AC1->T1 and AC2->T2 (prose task-id refs, not task starts).
"""


class TestPlanChecks(unittest.TestCase):
    def _write(self, tmp, text, name):
        p = Path(tmp) / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_plan_uncovered_ac_strict_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._write(tmp, PLAN_UNCOVERED, "plan.md")
            spec = self._write(tmp, PLAN_SPEC, "spec.md")
            # In-process: AC2 uncovered -> warning.
            result = va.check_plan(PLAN_UNCOVERED, PLAN_SPEC)
            self.assertTrue(
                any(w == "ac_not_covered:AC2" for w in result["warnings"]),
                result["warnings"],
            )
            # CLI strict: warning promoted to error -> non-zero.
            rc, out, err = run_cli(
                "--mode", "plan", "--file", str(plan), "--spec", str(spec), "--strict"
            )
            self.assertNotEqual(rc, 0)
            self.assertIn("error=ac_not_covered:AC2", out)
            self.assertIn("artifacts_validation=failed", out)

    def test_plan_uncovered_ac_nonstrict_exits_zero_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._write(tmp, PLAN_UNCOVERED, "plan.md")
            spec = self._write(tmp, PLAN_SPEC, "spec.md")
            rc, out, err = run_cli(
                "--mode", "plan", "--file", str(plan), "--spec", str(spec)
            )
            self.assertEqual(rc, 0, out + err)
            self.assertIn("warning=ac_not_covered:AC2", out)
            self.assertIn("artifacts_validation=passed", out)

    def test_plan_without_spec_warns_ac_source_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._write(tmp, PLAN_FULL, "plan.md")
            # In-process: no spec text -> ac_source_missing warning, no AC mining.
            result = va.check_plan(PLAN_FULL, None)
            self.assertIn("ac_source_missing", result["warnings"])
            self.assertFalse(
                any(w.startswith("ac_not_covered:") for w in result["warnings"]),
                result["warnings"],
            )
            # CLI without --spec.
            rc, out, err = run_cli("--mode", "plan", "--file", str(plan))
            self.assertEqual(rc, 0, out + err)
            self.assertIn("warning=ac_source_missing", out)

    def test_plan_full_coverage_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._write(tmp, PLAN_FULL, "plan.md")
            spec = self._write(tmp, PLAN_SPEC, "spec.md")
            rc, out, err = run_cli(
                "--mode", "plan", "--file", str(plan), "--spec", str(spec), "--strict"
            )
            self.assertEqual(rc, 0, out + err)
            self.assertIn("artifacts_validation=passed", out)
            self.assertIn("plan_ac_covered=2", out)
            self.assertIn("plan_tasks=2", out)

    def test_plan_numbered_and_prose_refs_not_counted(self):
        # Regression: a numbered decision-point list and a prose "AC1->T1" coverage
        # line must NOT be counted as task blocks (they over-counted real plans).
        result = va.check_plan(PLAN_NOISY, PLAN_SPEC)
        self.assertEqual(result["metrics"]["plan_tasks"], 2, result["metrics"])
        # Both ACs are covered by the two real task headings -> no ac_not_covered.
        self.assertFalse(
            any(w.startswith("ac_not_covered:") for w in result["warnings"]),
            result["warnings"],
        )


class TestModeAll(unittest.TestCase):
    def _write(self, tmp, text, name):
        p = Path(tmp) / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_mode_all_merges_spec_and_plan(self):
        # --mode all runs spec checks on --file AND plan checks (ACs from --spec),
        # merging both into one sorted block with mode=all.
        with tempfile.TemporaryDirectory() as tmp:
            # The --file is a plan that we also spec-check; it will be missing spec
            # sections (errors) AND its plan coverage is checked against --spec.
            plan = self._write(tmp, PLAN_UNCOVERED, "plan.md")
            spec = self._write(tmp, PLAN_SPEC, "spec.md")
            rc, out, err = run_cli(
                "--mode", "all", "--file", str(plan), "--spec", str(spec)
            )
            self.assertIn("mode=all", out)
            # Spec checks fired on --file (plan is missing required spec sections).
            self.assertIn("error=missing_section:", out)
            # Plan checks fired too (AC2 uncovered -> warning).
            self.assertIn("warning=ac_not_covered:AC2", out)
            # Output is one sorted block.
            lines = [ln for ln in out.splitlines() if ln and "=" in ln]
            self.assertEqual(lines, sorted(lines))


class TestQualityChecks(unittest.TestCase):
    """Deterministic QUALITY warnings (no count floors), calibrated by fixtures."""

    def test_plan_task_without_verification_warns(self):
        from validate_artifacts import check_plan
        plan = "## Task 1 - do it\nCreate greeting.py. TDD: add a RED test.\n"  # no Run/command
        res = check_plan(plan, "AC1")
        assert "task_no_verification" in res["warnings"]

    def test_plan_deferral_phrase_warns(self):
        from validate_artifacts import check_plan
        plan = "## Task 1 - thing\nModify x. TDD: RED test.\nRun: pytest\n\n## Non-task step\nSecurity executed after the implementation in the core-workflow gates.\n"
        res = check_plan(plan, "AC1")
        assert "deferred_work" in res["warnings"]

    def test_spec_security_handwave_warns(self):
        from validate_artifacts import check_spec
        spec = ("# S\n## Problem\np p p p p p p p p p p p p p p p\n## Business Rules\nb b b b b b b b b b\n"
                "## Acceptance Criteria\n- AC1: given x when y then z\n## Edge Cases\ne e e e e e e e e e\n"
                "## Security\nNo untrusted input; treat as safe string handling only.\n"
                "## Definition of Done\nd d d d d d d d d d\n## Must-not-change\nm m m m m m m m m m\n")
        res = check_spec(spec)
        assert "security_handwave" in res["warnings"]

    def test_deep_reference_artifacts_stay_clean(self):
        # The committed deep reference must not trip the new quality checks (calibration).
        from validate_artifacts import check_plan, check_spec
        # uses the same compact content shape as the deep fixture; counts not asserted.
        spec = ("# Spec\n## Problem\nThe greet function hardcodes punctuation here clearly.\n"
                "## Business Rules\nDefault output is unchanged when no suffix is given here.\n"
                "## Acceptance Criteria\n- AC1: Given Ada and no suffix, when greet runs, then returns Hello, Ada!.\n"
                "## Edge Cases\nEmpty suffix returns Hello, Ada with no trailing punctuation here.\n"
                "## Definition of Done\nTests for AC1 pass and default behaviour is preserved here.\n"
                "## Must-not-change\nThe single-argument call path keeps the exclamation mark here.\n")
        plan = ("# Plan\n## Task 1 - Failing test (AC1)\nModify test_greeting.py. TDD: RED test for greet.\nRun: pytest test_greeting.py\n")
        sres = check_spec(spec)
        pres = check_plan(plan, spec)
        assert "security_handwave" not in sres["warnings"]
        assert "task_no_verification" not in pres["warnings"]
        assert "deferred_work" not in pres["warnings"]


if __name__ == "__main__":
    unittest.main()
