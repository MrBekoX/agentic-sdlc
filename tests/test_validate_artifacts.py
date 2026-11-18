"""Tests for validate_artifacts.py — the deterministic spec/plan validator.

Each behavior is asserted BOTH in-process (call the functions directly) AND via
the subprocess CLI (exit code + exact key=value substrings). Stdlib `unittest`
only — runnable with `python -m unittest`.

The validator lives at ../scripts/validate_artifacts.py relative to this file.
We import it by path so the test suite stays independent of cwd / sys.path setup.
"""

import importlib.util
import json
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
---
work_id: sample-spec
status: draft
---

# Sample Spec

## 1. Problem
The reconciliation job double-counts refunds, so the daily ledger is wrong and
finance cannot close the books. We need a deterministic fix with clear rules.

## 2. Business rules
A refund reduces the gross total exactly once. Currency rounding follows the
banker's rounding rule. Each transaction id is unique within a settlement day.

## 3. Acceptance criteria
- AC1: Given a refund for an existing charge, when the job runs, then the gross total
  is reduced by the refund amount exactly once.
- AC2: Given a duplicate refund event, when the job runs, it returns the prior result
  and does not double-reduce the total.
- AC3: Given an empty settlement file, the job returns an empty ledger -> exit 0.

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

# The same spec written the way the authoring guidance allowed before ids were required:
# Given/When/Then bullets with no `AC<n>` label, so the plan gate has nothing to check (FM-4).
IDLESS_SPEC = COMPLETE_SPEC.replace("- AC1: ", "- ").replace("- AC2: ", "- ").replace("- AC3: ", "- ")


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
            "- AC3: Given an empty settlement file, the job returns an empty ledger -> exit 0.",
            "- AC3: The system should work well and be fast.",
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


# A full-coverage plan fixture. Plan tests use a dedicated mini spec rather than
# COMPLETE_SPEC so the AC ids and the tasks that cover them stay small and deterministic.
PLAN_SPEC = """\
---
work_id: mini
status: draft
---

# Mini Spec
## Acceptance criteria
- AC1: given a refund, then the total is reduced once.
- AC2: given a duplicate, it returns the prior result -> exit 0.
"""

PLAN_FULL = """\
---
work_id: mini
spec: ../specs/mini.md
branch: feat/mini
status: draft
---

# Mini Plan

## Task 1 — Reduce total once (AC1)
Create `src/ledger.py`. Write a failing test (RED) first, then the minimal fix.
Run: pytest tests/test_ledger.py

## Task 2 — Dedup refunds (AC2)
Modify `src/ledger.py`. TDD: add a failing test for the duplicate path, then GREEN.
Run: pytest tests/test_ledger.py
"""

PLAN_UNCOVERED = """\
---
work_id: mini
spec: ../specs/mini.md
branch: feat/mini
status: draft
---

# Mini Plan

## Task 1 — Reduce total once (AC1)
Create `src/ledger.py`. Write a failing test (RED) first, then the minimal fix.
"""

# A plan with 2 real tasks plus noise that a naive detector over-counts: a numbered
# decision-point list and a coverage line full of prose task-id references.
PLAN_NOISY = """\
---
work_id: mini
spec: ../specs/mini.md
branch: feat/mini
status: draft
---

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


# ---- frontmatter: the keys resolve_work_package.py rejects an artifact for ------------
# `validate_artifacts.py` is what the skills run as the deterministic gate
# (plan-authoring/SKILL.md:55; agentic-sdlc-pipeline/SKILL.md:130 calls a non-zero exit a
# blocked gate). `resolve_work_package.py` runs later, at implementation time, and rejects a
# plan with no `branch:`. The gate used to parse no frontmatter at all, so it returned
# `artifacts_validation=passed` on a plan the suite then failed with `plan_missing:branch` -
# which happened while writing another package in this repository.
#
# These are ERRORS, not warnings promoted by --strict: a key whose absence is unconditionally
# fatal downstream is not a style preference.


def _body_only(text):
    """The artifact WITHOUT its leading frontmatter block.

    The fixtures carry real frontmatter now, so a row that wants to test the absent-block case
    has to remove it explicitly rather than rely on the fixture not having one - which is how
    these two rows silently stopped testing anything the moment the fixtures were fixed.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "".join(lines[index + 1:]).lstrip("\n")
    return text


def _with_frontmatter(body, **keys):
    lines = ["---"]
    lines += ["{}: {}".format(k, v) for k, v in keys.items() if v is not None]
    lines += ["---", ""]
    return "\n".join(lines) + body


class TestFrontmatterRequirements(unittest.TestCase):
    def _write(self, tmp, text, name):
        p = Path(tmp) / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_plan_missing_branch_is_an_error_without_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._write(tmp, _with_frontmatter(
                _body_only(PLAN_FULL), work_id="w1", spec="../specs/w1.md", status="draft"),
                "plan.md")
            spec = self._write(tmp, _with_frontmatter(
                _body_only(PLAN_SPEC), work_id="w1", status="draft"), "spec.md")
            rc, out, err = run_cli("--mode", "plan", "--file", str(plan), "--spec", str(spec))
            self.assertNotEqual(rc, 0, out + err)
            self.assertIn("error=missing_frontmatter_key:branch", out)

    def test_spec_missing_work_id_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = self._write(
                tmp, _with_frontmatter(_body_only(COMPLETE_SPEC), status="draft"), "spec.md")
            rc, out, err = run_cli("--mode", "spec", "--file", str(spec))
            self.assertNotEqual(rc, 0, out + err)
            self.assertIn("error=missing_frontmatter_key:work_id", out)

    def test_no_frontmatter_block_names_every_required_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = self._write(tmp, _body_only(COMPLETE_SPEC), "spec.md")
            rc, out, err = run_cli("--mode", "spec", "--file", str(spec))
            self.assertNotEqual(rc, 0, out + err)
            self.assertIn("error=missing_frontmatter_key:work_id", out)
            self.assertIn("error=missing_frontmatter_key:status", out)

    def test_invalid_status_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = self._write(tmp, _with_frontmatter(
                _body_only(COMPLETE_SPEC), work_id="w1", status="nearly-done"), "spec.md")
            rc, out, err = run_cli("--mode", "spec", "--file", str(spec))
            self.assertNotEqual(rc, 0, out + err)
            self.assertIn("error=invalid_status:nearly-done", out)

    def test_approved_status_is_accepted_for_spec_and_plan(self):
        # `approved` is the approval receipt: the pipeline writes it only after a user approval
        # turn or explicit pre-approval text. Lifecycle: draft -> reviewed -> approved ->
        # in_progress -> ready_for_audit -> complete.
        self.assertIn("approved", va.FRONTMATTER_STATUSES)
        with tempfile.TemporaryDirectory() as tmp:
            spec = self._write(tmp, _with_frontmatter(
                _body_only(COMPLETE_SPEC), work_id="w1", status="approved"), "spec.md")
            rc, out, err = run_cli("--mode", "spec", "--file", str(spec), "--strict")
            self.assertNotIn("invalid_status", out, out + err)
            self.assertEqual(rc, 0, out + err)
            plan_spec = self._write(tmp, _with_frontmatter(
                _body_only(PLAN_SPEC), work_id="w1", status="approved"), "plan-spec.md")
            plan = self._write(tmp, _with_frontmatter(
                _body_only(PLAN_FULL), work_id="w1", spec="../specs/w1.md",
                branch="feature/w1", status="approved"), "plan.md")
            rc, out, err = run_cli(
                "--mode", "plan", "--file", str(plan), "--spec", str(plan_spec), "--strict")
            self.assertNotIn("invalid_status", out, out + err)
            self.assertEqual(rc, 0, out + err)

    def test_an_empty_value_counts_as_missing(self):
        # The resolver tests truthiness, not presence: `status:` with no value is not a status.
        with tempfile.TemporaryDirectory() as tmp:
            text = "---\nwork_id: w1\nstatus:\n---\n" + _body_only(COMPLETE_SPEC)
            spec = self._write(tmp, text, "spec.md")
            rc, out, err = run_cli("--mode", "spec", "--file", str(spec))
            self.assertNotEqual(rc, 0, out + err)
            self.assertIn("error=missing_frontmatter_key:status", out)

    def test_a_block_that_is_not_first_is_not_frontmatter(self):
        # A fenced example or a quoted block later in a document must not satisfy the check -
        # otherwise a document that merely DISCUSSES frontmatter would validate as having it.
        with tempfile.TemporaryDirectory() as tmp:
            text = _body_only(COMPLETE_SPEC) + "\n\n---\nwork_id: w1\nstatus: draft\n---\n"
            spec = self._write(tmp, text, "spec.md")
            rc, out, err = run_cli("--mode", "spec", "--file", str(spec))
            self.assertNotEqual(rc, 0, out + err)
            self.assertIn("error=missing_frontmatter_key:work_id", out)


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


# A plan with full frontmatter and no task at all, and one whose only task is unrelated to the
# spec. Both passed `--mode plan --strict` against an id-less spec (audit finding L3b-F4).
PLAN_EMPTY = """\
---
work_id: mini
spec: ../specs/mini.md
branch: feat/mini
status: draft
---

# Mini Plan
"""

PLAN_UNRELATED = """\
---
work_id: mini
spec: ../specs/mini.md
branch: feat/mini
status: draft
---

# Mini Plan

## Task 1 — Update README wording
Modify `README.md`. TDD: add a failing test (RED) for the wording check first.
Run: pytest tests/test_readme.py
"""

HYPHEN_SPEC = PLAN_SPEC.replace("- AC1:", "- AC-1:").replace("- AC2:", "- AC-2:")


def _warnings_with(prefix, warnings):
    return sorted(w for w in warnings if w.startswith(prefix))


class TestAcIdObligations(unittest.TestCase):
    """FM-4: the plan gate failed open when the spec gave it no `AC<n>` id to check.

    Coverage obligations are the ids mined from the spec. A spec written as plain Given/When/Then
    bullets, or with `AC-1`-style ids, produced none, so an empty plan or an unrelated one passed
    `--strict`. Contract 03 says every acceptance criterion maps to at least one task.
    """

    def _write(self, tmp, text, name):
        p = Path(tmp) / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_hyphenated_spec_ids_are_coverage_obligations(self):
        plan = PLAN_UNCOVERED.replace("(AC1)", "(AC-1)")
        result = va.check_plan(plan, HYPHEN_SPEC)
        self.assertEqual(_warnings_with("ac_not_covered:", result["warnings"]),
                         ["ac_not_covered:AC-2"], result["warnings"])

    def test_either_spelling_covers_the_other(self):
        # A plan citing `AC1` covers a spec's `AC-1`, and the reverse: one criterion, one number.
        hyphen_plan = PLAN_FULL.replace("(AC1)", "(AC-1)").replace("(AC2)", "(AC-2)")
        for plan, spec in ((PLAN_FULL, HYPHEN_SPEC), (hyphen_plan, PLAN_SPEC)):
            with self.subTest(spec_ids="AC-n" if spec is HYPHEN_SPEC else "ACn"):
                result = va.check_plan(plan, spec)
                self.assertEqual(result["metrics"]["plan_ac_covered"], 2, result)
                self.assertEqual(_warnings_with("ac_not_covered:", result["warnings"]), [])

    def test_spec_criterion_without_id_warns(self):
        result = va.check_spec(IDLESS_SPEC)
        self.assertEqual(_warnings_with("ac_missing_id:", result["warnings"]),
                         ["ac_missing_id:1", "ac_missing_id:2", "ac_missing_id:3"])
        labelled = va.check_spec(COMPLETE_SPEC)
        self.assertEqual(_warnings_with("ac_missing_id:", labelled["warnings"]), [])

    def test_only_the_unlabelled_criterion_is_named(self):
        # The index is the criterion's position, the same one `untestable_criterion:<n>` uses.
        mixed = COMPLETE_SPEC.replace("- AC2: ", "- ")
        self.assertEqual(_warnings_with("ac_missing_id:", va.check_spec(mixed)["warnings"]),
                         ["ac_missing_id:2"])

    def test_plan_gate_does_not_guess_unlabelled_criteria(self):
        # Telling a criterion bullet from a detail bullet is a heuristic. Real pipeline specs
        # split Given/When/Then over bullets under a bold `**AC-A1**` line, or add a "Guards:"
        # bullet that says "when", so the strict plan gate reports only what the ids show.
        mixed = COMPLETE_SPEC.replace("- AC2: ", "- ")
        self.assertEqual(_warnings_with("ac_missing_id:", va.check_plan(PLAN_FULL, mixed)["warnings"]), [])
        split = PLAN_SPEC.replace(
            "- AC1: given a refund, then the total is reduced once.",
            "**AC1 (refund)**\n- Given a refund\n- When the job runs\n- Then the total is reduced once.")
        result = va.check_plan(PLAN_FULL, split)
        self.assertEqual(_warnings_with("ac_missing_id:", result["warnings"]), [])
        self.assertEqual(result["metrics"]["plan_ac_covered"], 2, result)

    def test_detail_lines_are_not_unlabelled_criteria(self):
        # Shapes seen in real pipeline specs: a bold group heading, a nested "Guards:" or
        # "Variant:" bullet under a labelled criterion. None of them is a criterion of its own,
        # so none may block the strict plan gate as an unlabelled one.
        detailed = COMPLETE_SPEC.replace(
            "- AC1: Given a refund",
            "**Refunds**\n\n- AC1: Given a refund",
        ).replace(
            "  and does not double-reduce the total.\n",
            "  and does not double-reduce the total.\n"
            "  - Guards: a replayed event, when it arrives late, then reduces the total twice.\n",
        )
        self.assertEqual(_warnings_with("ac_missing_id:", va.check_spec(detailed)["warnings"]), [])
        self.assertEqual(_warnings_with("ac_missing_id:", va.check_plan(PLAN_FULL, detailed)["warnings"]), [])

    def test_grouped_ids_are_coverage_obligations(self):
        # `AC-A1` style: a letter group, then a number. A1 and B1 are different criteria.
        spec = PLAN_SPEC.replace("- AC1:", "- AC-A1:").replace("- AC2:", "- AC-B1:")
        plan = PLAN_FULL.replace("(AC1)", "(AC-A1)").replace("(AC2)", "(AC-A2)")
        result = va.check_plan(plan, spec)
        self.assertEqual(result["metrics"]["plan_ac_covered"], 1, result)
        self.assertEqual(_warnings_with("ac_not_covered:", result["warnings"]), ["ac_not_covered:AC-B1"])

    def test_words_that_start_with_ac_are_not_ids(self):
        spec = PLAN_SPEC + "\nThe ACE2 and ACK1 names in the domain glossary are not criteria.\n"
        result = va.check_plan(PLAN_FULL, spec)
        self.assertEqual(_warnings_with("ac_not_covered:", result["warnings"]), [])

    def test_plan_gate_fails_on_idless_spec(self):
        # The L3b-F4 repro: an unrelated one-task plan against an id-less spec.
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._write(tmp, PLAN_UNRELATED, "plan.md")
            spec = self._write(tmp, IDLESS_SPEC, "spec.md")
            rc, out, err = run_cli("--mode", "plan", "--file", str(plan), "--spec", str(spec), "--strict")
            self.assertNotEqual(rc, 0, out + err)
            self.assertIn("error=ac_source_empty", out)
            self.assertIn("artifacts_validation=failed", out)

    def test_plan_gate_fails_when_spec_names_no_ids(self):
        # Criteria written as prose, not bullets: no id and no bullet to name.
        prose = IDLESS_SPEC.replace(
            "- Given a refund for an existing charge", "Given a refund for an existing charge")
        prose = prose.replace("- Given a duplicate", "Given a duplicate").replace(
            "- Given an empty", "Given an empty")
        result = va.check_plan(PLAN_FULL, prose)
        self.assertIn("ac_source_empty", result["warnings"])
        self.assertEqual(result["metrics"]["plan_ac_covered"], 0)

    def test_plan_without_tasks_fails_strict(self):
        for spec_text in (PLAN_SPEC, None):
            with self.subTest(spec=spec_text is not None):
                result = va.check_plan(PLAN_EMPTY, spec_text)
                self.assertEqual(result["metrics"]["plan_tasks"], 0)
                self.assertIn("plan_no_tasks", result["warnings"])
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._write(tmp, PLAN_EMPTY, "plan.md")
            spec = self._write(tmp, IDLESS_SPEC, "spec.md")
            rc, out, err = run_cli("--mode", "plan", "--file", str(plan), "--spec", str(spec), "--strict")
            self.assertNotEqual(rc, 0, out + err)
            self.assertIn("error=plan_no_tasks", out)

    def test_labelled_spec_and_covering_plan_still_pass_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._write(tmp, PLAN_FULL, "plan.md")
            spec = self._write(tmp, HYPHEN_SPEC, "spec.md")
            rc, out, err = run_cli("--mode", "plan", "--file", str(plan), "--spec", str(spec), "--strict")
            self.assertEqual(rc, 0, out + err)
            self.assertIn("plan_ac_covered=2", out)


# ---- spec-less bugfix plans (design §5.19) --------------------------------------------
# A bugfix plan has no spec: its frontmatter carries `flow: bugfix` together with `spec: none`,
# and its acceptance criteria live in its own `## Acceptance Criteria` section, before the first
# task. DP-2 (ids come from the spec only) is relaxed for that plan and for no other.
BUGFIX_PLAN = """\
---
work_id: fix-refund
spec: none
flow: bugfix
branch: fix/refund
status: draft
---

# Bugfix plan: refunds counted twice

## Bug
Expected: a refund reduces the daily total once. Actual: the total is reduced twice when the
refund event is replayed. Reproduction: replay one refund event, then run the job.

## Acceptance Criteria
- AC1: Given a replayed refund event, when the job runs, then the total is reduced once.
- AC2: Given a single refund event, when the job runs, then the total is reduced once as today.

## Task 1 — Regression test for the replay (AC1)
Modify `tests/test_ledger.py`. TDD: add the failing replay test (RED) first.
Run: pytest tests/test_ledger.py

## Task 2 — Deduplicate refund events (AC1, AC2)
Modify `src/ledger.py`. TDD: the RED test from Task 1 turns GREEN; the single-event test stays green.
Run: pytest tests/test_ledger.py
"""

BUGFIX_AC_SECTION = """\
## Acceptance Criteria
- AC1: Given a replayed refund event, when the job runs, then the total is reduced once.
- AC2: Given a single refund event, when the job runs, then the total is reduced once as today.

"""

BUGFIX_BUG_SECTION = """\
## Bug
Expected: a refund reduces the daily total once. Actual: the total is reduced twice when the
refund event is replayed. Reproduction: replay one refund event, then run the job.

"""


def _bugfix_ac_after_tasks(plan=BUGFIX_PLAN):
    """The same plan with its criteria section moved below the last task."""
    assert BUGFIX_AC_SECTION in plan
    return plan.replace(BUGFIX_AC_SECTION, "") + "\n" + BUGFIX_AC_SECTION


class TestBugfixPlans(unittest.TestCase):
    def _write(self, tmp, text, name="plan.md"):
        p = Path(tmp) / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_bugfix_plan_ac_from_own_section_before_first_task(self):
        result = va.check_plan(BUGFIX_PLAN, None, bugfix=True)
        self.assertEqual(result["errors"], [], result)
        self.assertEqual(result["metrics"]["plan_ac_covered"], 2, result)
        self.assertNotIn("ac_source_missing", result["warnings"])
        self.assertEqual(_warnings_with("ac_not_covered:", result["warnings"]), [])
        # AC2 is named only by the criteria section, so dropping it from Task 2 uncovers it:
        # the obligations come from that section, not from the task blocks.
        partial = BUGFIX_PLAN.replace("(AC1, AC2)", "(AC1)")
        result = va.check_plan(partial, None, bugfix=True)
        self.assertEqual(_warnings_with("ac_not_covered:", result["warnings"]), ["ac_not_covered:AC2"])
        self.assertEqual(result["metrics"]["plan_ac_covered"], 1, result)
        # An id outside that section (here in the bug report) is not an obligation.
        cited_elsewhere = BUGFIX_PLAN.replace(
            "then run the job.\n", "then run the job. The old spec called it AC9.\n", 1)
        result = va.check_plan(cited_elsewhere, None, bugfix=True)
        self.assertEqual(_warnings_with("ac_not_covered:", result["warnings"]), [])
        self.assertEqual(result["metrics"]["plan_ac_covered"], 2, result)
        # The CLI decides the kind from the frontmatter: no --spec, no ac_source_missing.
        with tempfile.TemporaryDirectory() as tmp:
            rc, out, err = run_cli("--mode", "plan", "--file", str(self._write(tmp, BUGFIX_PLAN)))
            self.assertEqual(rc, 0, out + err)
            self.assertIn("plan_ac_covered=2", out)
            self.assertNotIn("ac_source_missing", out)
            self.assertIn("artifacts_validation=passed", out)

    def test_bugfix_ac_section_keeps_its_subheadings(self):
        # A criterion written as its own sub-heading stays inside the section.
        plan = BUGFIX_PLAN.replace(BUGFIX_AC_SECTION, (
            "## Acceptance Criteria\n"
            "### AC1 — replay\nGiven a replayed refund event, then the total is reduced once.\n"
            "### AC2 — single event\nGiven a single refund event, then the total is reduced once.\n\n"))
        result = va.check_plan(plan, None, bugfix=True)
        self.assertEqual(result["errors"], [], result)
        self.assertEqual(result["metrics"]["plan_ac_covered"], 2, result)

    def test_bugfix_plan_ac_section_after_first_task_fails(self):
        # A section inside a task block would be "covered" by the block that holds it.
        t_marker_plan = BUGFIX_PLAN.replace(
            "## Task 1 — Regression test for the replay (AC1)", "- **T1 — Regression test for the replay (AC1)**"
        ).replace("## Task 2 — Deduplicate refund events (AC1, AC2)", "- **T2 — Deduplicate refund events (AC1, AC2)**")
        for name, plan in (("task headings", BUGFIX_PLAN), ("T-id markers", t_marker_plan)):
            with self.subTest(form=name):
                self.assertEqual(va.check_plan(plan, None, bugfix=True)["errors"], [])
                result = va.check_plan(_bugfix_ac_after_tasks(plan), None, bugfix=True)
                self.assertIn("bugfix_ac_section_after_tasks", result["errors"], result)
        with tempfile.TemporaryDirectory() as tmp:
            rc, out, err = run_cli(
                "--mode", "plan", "--file", str(self._write(tmp, _bugfix_ac_after_tasks())))
            self.assertEqual(rc, 1, out + err)
            self.assertIn("error=bugfix_ac_section_after_tasks", out)
            self.assertIn("artifacts_validation=failed", out)

    def test_bugfix_plan_requires_bug_section(self):
        no_bug = BUGFIX_PLAN.replace(BUGFIX_BUG_SECTION, "")
        # A task heading that mentions the bug is a task, not the bug report.
        bug_in_task_only = no_bug.replace("Deduplicate refund events", "Fix the bug")
        for name, plan in (("no section", no_bug), ("named only by a task", bug_in_task_only)):
            with self.subTest(case=name):
                result = va.check_plan(plan, None, bugfix=True)
                self.assertIn("missing_section:bug", result["errors"], result)
        self.assertNotIn("missing_section:bug", va.check_plan(BUGFIX_PLAN, None, bugfix=True)["errors"])
        with tempfile.TemporaryDirectory() as tmp:
            rc, out, err = run_cli("--mode", "plan", "--file", str(self._write(tmp, no_bug)))
            self.assertEqual(rc, 1, out + err)
            self.assertIn("error=missing_section:bug", out)

    def test_bug_section_sits_below_the_title_and_before_the_tasks(self):
        # Only a level-2-or-deeper heading outside a code fence and before the first task is the
        # bug report. The document title, a sub-heading inside a task, a `#` comment in a fenced
        # snippet and a section after the last task each stood in for it.
        no_bug = BUGFIX_PLAN.replace(BUGFIX_BUG_SECTION, "")
        end_of_task_1 = "Run: pytest tests/test_ledger.py\n\n## Task 2"
        self.assertIn(end_of_task_1, no_bug)
        cases = (
            ("document title", no_bug.replace("# Bugfix plan: refunds counted twice",
                                              "# Bug fix plan: refunds counted twice")),
            ("sub-heading inside a task", no_bug.replace(end_of_task_1, (
                "### Bug repro steps\nReplay one refund event, then run the job twice.\n\n" + end_of_task_1))),
            ("fenced comment inside a task", no_bug.replace(end_of_task_1, (
                "```bash\n# bug: the replay is counted twice\n./replay.sh\n```\n\n" + end_of_task_1))),
            ("section after the tasks", no_bug + "\n" + BUGFIX_BUG_SECTION),
        )
        for name, plan in cases:
            with self.subTest(case=name):
                result = va.check_plan(plan, None, bugfix=True)
                self.assertIn("missing_section:bug", result["errors"], result)
                with tempfile.TemporaryDirectory() as tmp:
                    rc, out, err = run_cli("--mode", "plan", "--file", str(self._write(tmp, plan)), "--strict")
                    self.assertEqual(rc, 1, out + err)
                    self.assertIn("error=missing_section:bug", out.splitlines())
        # A deeper heading before the tasks is still the bug report.
        nested = BUGFIX_PLAN.replace("## Bug\n", "## Context\n### Bug\n")
        self.assertEqual(va.check_plan(nested, None, bugfix=True)["errors"], [])

    def test_thin_bug_section_warns(self):
        # Design §5.19: the bug report carries expected, actual and reproduction. An empty or
        # one-line section is thin, as a thin spec section is, and --strict gates it.
        self.assertNotIn("thin_section:bug", va.check_plan(BUGFIX_PLAN, None, bugfix=True)["warnings"])
        for name, body in (("empty", ""), ("one line", "Refunds are wrong.\n")):
            plan = BUGFIX_PLAN.replace(BUGFIX_BUG_SECTION, "## Bug\n" + body + "\n")
            with self.subTest(case=name):
                result = va.check_plan(plan, None, bugfix=True)
                self.assertNotIn("missing_section:bug", result["errors"], result)
                self.assertIn("thin_section:bug", result["warnings"], result)
                with tempfile.TemporaryDirectory() as tmp:
                    rc, out, err = run_cli("--mode", "plan", "--file", str(self._write(tmp, plan)), "--strict")
                    self.assertEqual(rc, 1, out + err)
                    self.assertIn("error=thin_section:bug", out.splitlines())

    def test_fenced_lines_do_not_end_the_ac_section(self):
        # A `#` comment or a `T<n>` line inside a code fence is code, not a heading or a task. It
        # ended the criteria section, so every id after the fence stopped being an obligation.
        partial = BUGFIX_PLAN.replace("(AC1, AC2)", "(AC1)")
        ac2 = "- AC2: Given a single refund event"
        self.assertIn(ac2, partial)
        snippets = (
            ("indented bash comment", "  ```bash\n  # replay the refund event twice\n  ./replay.sh\n  ```\n"),
            ("column-0 bash comment", "```bash\n# replay the refund event twice\n./replay.sh\n```\n"),
            ("tilde fence", "~~~sh\n# replay the refund event twice\n~~~\n"),
            ("task-id line", "```text\nT1 replays the event; T2 runs the job\n```\n"),
        )
        for name, snippet in snippets:
            plan = partial.replace(ac2, snippet + ac2)
            with self.subTest(case=name):
                result = va.check_plan(plan, None, bugfix=True)
                self.assertEqual(result["errors"], [], result)
                self.assertIn("ac_not_covered:AC2", result["warnings"], result)
                self.assertEqual(result["metrics"]["plan_tasks"], 2, result)
                with tempfile.TemporaryDirectory() as tmp:
                    rc, out, err = run_cli("--mode", "plan", "--file", str(self._write(tmp, plan)), "--strict")
                    self.assertEqual(rc, 1, out + err)
                    self.assertIn("error=ac_not_covered:AC2", out.splitlines())

    def test_fenced_task_lines_are_not_task_blocks(self):
        # A task shown inside a code fence (an example, a template) is not a task: it neither
        # counts toward plan_tasks nor covers an id. Feature plans share the task detector.
        example = "```markdown\n## Task 9 — Example task (AC1, AC2)\nModify `x.py`. TDD: RED first.\n```\n\n"
        plan = PLAN_UNCOVERED.replace("## Task 1", example + "## Task 1", 1)
        result = va.check_plan(plan, PLAN_SPEC)
        self.assertEqual(result["metrics"]["plan_tasks"], 1, result)
        self.assertIn("ac_not_covered:AC2", result["warnings"], result)
        self.assertNotIn("tasks_unordered", result["warnings"], result)

    def test_bugfix_unlabelled_criterion_is_reported(self):
        # The plan's own section is a bugfix plan's only criteria source and no spec check runs on
        # it, so a criterion without an id is reported here (`ac_missing_id:<n>`, the spec check's
        # code) instead of dropping out of the coverage gate in silence.
        chargeback = ("- Given a chargeback event, when the job runs, then the total is never "
                      "reduced below zero.\n")
        plan = BUGFIX_PLAN.replace("as today.\n", "as today.\n" + chargeback, 1)
        result = va.check_plan(plan, None, bugfix=True)
        self.assertEqual(_warnings_with("ac_missing_id:", result["warnings"]), ["ac_missing_id:3"], result)
        with tempfile.TemporaryDirectory() as tmp:
            rc, out, err = run_cli("--mode", "plan", "--file", str(self._write(tmp, plan)), "--strict")
            self.assertEqual(rc, 1, out + err)
            self.assertIn("error=ac_missing_id:3", out.splitlines())
        # A nested detail bullet and a bullet inside a fence are not criteria of their own.
        detail = BUGFIX_PLAN.replace("as today.\n", (
            "as today.\n  - Guard: when the event id repeats, then skip it.\n"
            "```text\n- when replayed, then once\n```\n"), 1)
        for name, text in (("plain", BUGFIX_PLAN), ("detail and fenced bullets", detail)):
            with self.subTest(case=name):
                warnings = va.check_plan(text, None, bugfix=True)["warnings"]
                self.assertEqual(_warnings_with("ac_missing_id:", warnings), [], warnings)

    def test_bugfix_plan_requires_ac_section(self):
        no_ac = BUGFIX_PLAN.replace(BUGFIX_AC_SECTION, "")
        result = va.check_plan(no_ac, None, bugfix=True)
        self.assertIn("missing_section:acceptance-criteria", result["errors"], result)
        self.assertEqual(result["metrics"]["plan_ac_covered"], 0)

    def test_bugfix_plan_strict_passes_when_covered(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out, err = run_cli("--mode", "plan", "--file", str(self._write(tmp, BUGFIX_PLAN)), "--strict")
            self.assertEqual(rc, 0, out + err)
            self.assertIn("artifacts_validation=passed", out)
            self.assertIn("plan_ac_covered=2", out)
            self.assertIn("plan_tasks=2", out)
            partial = self._write(tmp, BUGFIX_PLAN.replace("(AC1, AC2)", "(AC1)"), "partial.md")
            rc, out, err = run_cli("--mode", "plan", "--file", str(partial), "--strict")
            self.assertEqual(rc, 1, out + err)
            self.assertIn("error=ac_not_covered:AC2", out)

    def test_bugfix_plan_given_a_spec_fails_closed(self):
        # The caller passed a spec but the plan declares none. The plan under test must not decide
        # whether the caller's spec is checked, so the disagreement fails the gate (present or
        # absent spec alike). The runner passes no spec for a bugfix plan (contract §7).
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._write(tmp, BUGFIX_PLAN)
            spec = self._write(tmp, PLAN_SPEC + "- AC3: given a third case, then it returns 0.\n", "spec.md")
            for spec_arg in (spec, Path(tmp) / "absent.md"):
                with self.subTest(spec=spec_arg.name):
                    rc, out, err = run_cli("--mode", "plan", "--file", str(plan), "--spec", str(spec_arg),
                                           "--strict")
                    self.assertEqual(rc, 1, out + err)
                    self.assertIn("error=spec_none_with_spec", out.splitlines())
                    self.assertIn("artifacts_validation=failed", out.splitlines())
                    self.assertEqual(err, "")
            code, fields = va.run("plan", str(plan), None, True)
            self.assertEqual(code, 0, fields)

    def test_invalid_status_value_is_masked_when_secret_shaped(self):
        # `invalid_status:<value>` echoed the raw frontmatter value, next to the masked
        # `possible_secret` report for the same line.
        secret_val = "AKIA" + "IOSFODNN7EXAMPLE"
        plan = BUGFIX_PLAN.replace("status: draft", "status: " + secret_val)
        errors = va.check_frontmatter(plan, "plan")
        self.assertIn("invalid_status:***MASKED***", errors)
        self.assertNotIn(secret_val, " ".join(errors))
        with tempfile.TemporaryDirectory() as tmp:
            rc, out, err = run_cli("--mode", "plan", "--file", str(self._write(tmp, plan)))
            self.assertEqual(rc, 1, out + err)
            self.assertIn("error=invalid_status:***MASKED***", out.splitlines())
            self.assertNotIn(secret_val, out + err)
        # A plain wrong word is still named, so the author sees what to fix; anything that is not
        # a short word is masked.
        self.assertIn("invalid_status:wip", va.check_frontmatter(BUGFIX_PLAN.replace("status: draft", "status: wip"), "plan"))
        # A lowercase word in any script is still a word (tests/test_helper_encoding_portability.py
        # prints `hazır` on a cp1252 console); uppercase, digits and spaces are not.
        self.assertIn("invalid_status:hazır",
                      va.check_frontmatter(BUGFIX_PLAN.replace("status: draft", "status: hazır"), "plan"))
        for value in ("Hazır", "hazır1", "ab12cd"):
            with self.subTest(value=value):
                self.assertIn("invalid_status:***MASKED***",
                              va.check_frontmatter(BUGFIX_PLAN.replace("status: draft", "status: " + value), "plan"))
        self.assertIn("invalid_status:***MASKED***",
                      va.check_frontmatter(BUGFIX_PLAN.replace("status: draft", "status: in review"), "plan"))

    def test_frontmatter_delimiters_are_whole_lines(self):
        # Read the way the resolver reads it (tests/test_validator_resolver_parity.py runs both
        # command lines): `---` on a line of its own opens and closes the block, trailing spaces
        # aside; an indented `---` is not a delimiter.
        base = "---\nwork_id: w\nstatus: draft\n---\n# Body\n"
        self.assertEqual(va.parse_frontmatter(base), {"work_id": "w", "status": "draft"})
        self.assertEqual(va.parse_frontmatter("--- \nwork_id: w\n--- \n"), {"work_id": "w"})
        self.assertEqual(va.parse_frontmatter("  " + base), {}, "indented opener")
        self.assertEqual(va.parse_frontmatter(base.replace("\n---\n#", "\n  ---\n#")), {}, "indented closer")
        # A line that is neither `key: value` nor a `#` comment is an error naming its file line.
        cases = (
            ("colon-less line", base.replace("status: draft\n", "status: draft\nnotes\n"), 4),
            ("---- line inside the block", base.replace("status: draft\n", "status: draft\n----\nspec: none\n"), 4),
            ("empty key", base.replace("status: draft\n", ": x\nstatus: draft\n"), 3),
        )
        for name, text, lineno in cases:
            with self.subTest(case=name):
                self.assertIn(f"invalid_frontmatter_line:{lineno}", va.check_frontmatter(text, "spec"))
        comment = base.replace("status: draft\n", "# owner: payments\nstatus: draft\n")
        self.assertEqual(va.check_frontmatter(comment, "spec"), [])

    def test_non_bugfix_plan_keeps_dp2(self):
        # An acceptance-criteria section in a feature plan is not an id source (DP-2).
        own_section = "## Acceptance Criteria\n- AC3: Given a third case, when it runs, then it returns 0.\n\n"
        feature = PLAN_FULL.replace("## Task 1", own_section + "## Task 1", 1)
        result = va.check_plan(feature, PLAN_SPEC)
        self.assertEqual(result["errors"], [], result)
        self.assertEqual(result["metrics"]["plan_ac_covered"], 2, result)
        self.assertEqual(_warnings_with("ac_not_covered:", result["warnings"]), [])
        result = va.check_plan(feature, None)
        self.assertIn("ac_source_missing", result["warnings"])
        self.assertEqual(result["metrics"]["plan_ac_covered"], 0)
        self.assertEqual(_warnings_with("ac_not_covered:", result["warnings"]), [])
        # `flow: bugfix` with a real spec path is not a spec-less plan: the spec stays the source
        # and no bug section is asked for.
        flow_only = feature.replace("status: draft\n", "status: draft\nflow: bugfix\n", 1)
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._write(tmp, flow_only)
            spec = self._write(tmp, PLAN_SPEC, "spec.md")
            rc, out, err = run_cli("--mode", "plan", "--file", str(plan), "--spec", str(spec), "--strict")
            self.assertEqual(rc, 0, out + err)
            self.assertIn("plan_ac_covered=2", out)
            self.assertNotIn("AC3", out)
            self.assertNotIn("missing_section:bug", out)
            rc, out, err = run_cli("--mode", "plan", "--file", str(plan))
            self.assertIn("warning=ac_source_missing", out)

    def test_quoted_frontmatter_values_are_read_like_the_resolver(self):
        # The resolver drops surrounding quotes; the gate must not fail what it accepts.
        meta = va.parse_frontmatter('---\nstatus: "approved"\nspec: \'none\'\nflow: "bugfix"\n---\n')
        self.assertEqual(meta, {"status": "approved", "spec": "none", "flow": "bugfix"})
        with tempfile.TemporaryDirectory() as tmp:
            quoted = BUGFIX_PLAN.replace("status: draft", 'status: "approved"').replace(
                "spec: none", 'spec: "none"')
            rc, out, err = run_cli("--mode", "plan", "--file", str(self._write(tmp, quoted)), "--strict")
            self.assertEqual(rc, 0, out + err)
            self.assertNotIn("invalid_status", out)


# ---- the frontmatter block is not body ------------------------------------------------
# Headings, sections, tasks and AC ids are read from the body after the leading block only (the
# block `_frontmatter_block` reads: it opens on the first line and closes on a whole `---` line).
# Inside the block a `#` line is a comment and `- AC1: ...` is a `key: value` line, so the block
# parser accepts both; the scans used to read them as headings, tasks and ids anyway. The runner's
# body fingerprint (contract §5) ignores the block, so an edit confined to it must never change a
# body verdict. The placeholder and secret scan still reads every line.

SPEC_HEADINGS_IN_BLOCK = (
    "---\nwork_id: w1\nstatus: draft\n"
    "## Problem\n## Business rules\n## Acceptance criteria\n- AC1: Given x, when y, then z\n"
    "## Edge cases\n## Definition of done\n## Must-not-change\n"
    "---\n# Body\nOnly prose here: the sections above sit inside the frontmatter block.\n"
)

# Lines that are valid inside the block (comments or `key: value`) and look like body structure.
BODY_LOOKALIKES = (
    "## Problem\n## Acceptance Criteria\n- AC7: Given a, when b, then c\n"
    "## Bug\nExpected: once. Actual: twice. Reproduction: replay it.\n"
    "## Task 9 — Extra work (AC1, AC2, AC7)\n# T8 — another task (AC9)\n# AC9 dropped\n"
    "## Security\n# no untrusted input\n"
)


def _into_block(text, lines):
    """`text` with `lines` added at the end of its leading frontmatter block."""
    assert text.startswith("---\n"), text[:20]
    head, closer, rest = text.partition("\n---\n")
    assert closer, "no frontmatter closer"
    return head + "\n" + lines.rstrip("\n") + closer + rest


class TestFrontmatterIsNotBody(unittest.TestCase):
    def _write(self, tmp, text, name):
        p = Path(tmp) / name
        p.write_bytes(text.encode("utf-8"))
        return p

    def test_spec_sections_inside_the_block_are_not_sections(self):
        self.assertEqual(va.check_frontmatter(SPEC_HEADINGS_IN_BLOCK, "spec"), [])
        missing = ["missing_section:" + slug for slug in va.REQUIRED_SPEC_SECTIONS]
        self.assertEqual(va.check_spec(SPEC_HEADINGS_IN_BLOCK)["errors"], missing)
        with tempfile.TemporaryDirectory() as tmp:
            rc, out, err = run_cli("--mode", "spec", "--file", str(self._write(tmp, SPEC_HEADINGS_IN_BLOCK, "s.md")))
            self.assertEqual(rc, 1, out + err)
            for error in missing:
                self.assertIn("error=" + error, out.splitlines())

    def test_plan_tasks_inside_the_block_are_not_tasks(self):
        for name, line in (("task heading", "## Task 1 — Reduce total once (AC1, AC2) Modify x.py TDD RED"),
                           ("task id", "# T1 — Reduce total once (AC1, AC2) Modify x.py TDD RED")):
            plan = _into_block(_with_frontmatter(
                "\n# Mini Plan\nNo task block in the body.\n", work_id="mini", spec="../specs/mini.md",
                branch="feat/mini", status="draft"), line)
            with self.subTest(form=name):
                self.assertEqual(va.check_frontmatter(plan, "plan"), [])
                result = va.check_plan(plan, PLAN_SPEC)
                self.assertEqual(result["metrics"], {"plan_tasks": 0, "plan_ac_covered": 0}, result)
                self.assertIn("plan_no_tasks", result["warnings"], result)
                with tempfile.TemporaryDirectory() as tmp:
                    rc, out, err = run_cli("--mode", "plan", "--file", str(self._write(tmp, plan, "p.md")),
                                           "--spec", str(self._write(tmp, PLAN_SPEC, "s.md")), "--strict")
                    self.assertEqual(rc, 1, out + err)
                    self.assertIn("error=plan_no_tasks", out.splitlines())
                    self.assertIn("error=ac_not_covered:AC1", out.splitlines())

    def test_spec_ids_inside_the_block_are_not_obligations(self):
        # An id only in the spec's block is no obligation, and a spec whose ids all sit there has none.
        dropped = _into_block(PLAN_SPEC, "# AC9 was dropped from scope")
        result = va.check_plan(PLAN_FULL, dropped)
        self.assertEqual(_warnings_with("ac_not_covered:", result["warnings"]), [], result)
        self.assertEqual(result["metrics"]["plan_ac_covered"], 2, result)
        idless = PLAN_SPEC.replace("- AC1: ", "- ").replace("- AC2: ", "- ")
        ids_in_block_only = _into_block(idless, "# AC1\n- AC2: Given a duplicate, then exit 0")
        result = va.check_plan(PLAN_FULL, ids_in_block_only)
        self.assertIn("ac_source_empty", result["warnings"], result)
        self.assertEqual(result["metrics"]["plan_ac_covered"], 0, result)
        with tempfile.TemporaryDirectory() as tmp:
            rc, out, err = run_cli("--mode", "plan", "--file", str(self._write(tmp, PLAN_FULL, "p.md")),
                                   "--spec", str(self._write(tmp, ids_in_block_only, "s.md")), "--strict")
            self.assertEqual(rc, 1, out + err)
            self.assertIn("error=ac_source_empty", out.splitlines())

    def test_bugfix_sections_inside_the_block_do_not_count(self):
        body = BUGFIX_PLAN.replace(BUGFIX_BUG_SECTION, "").replace(BUGFIX_AC_SECTION, "")
        plan = _into_block(body, (
            "## Bug\nExpected: once. Actual: twice. Reproduction: replay one refund event, then run the job.\n"
            "## Acceptance Criteria\n- AC1: Given a replay, when the job runs, then once\n"
            "- AC2: Given one event, when the job runs, then once"))
        self.assertEqual(va.check_frontmatter(plan, "plan"), [])
        self.assertTrue(va.is_bugfix_plan(va.parse_frontmatter(plan)))
        result = va.check_plan(plan, None, bugfix=True)
        self.assertIn("missing_section:bug", result["errors"], result)
        self.assertIn("missing_section:acceptance-criteria", result["errors"], result)
        with tempfile.TemporaryDirectory() as tmp:
            rc, out, err = run_cli("--mode", "plan", "--file", str(self._write(tmp, plan, "p.md")))
            self.assertEqual(rc, 1, out + err)
            self.assertIn("error=missing_section:bug", out.splitlines())
            self.assertIn("error=missing_section:acceptance-criteria", out.splitlines())

    def test_a_block_only_edit_never_changes_a_body_verdict(self):
        cases = (
            ("spec", COMPLETE_SPEC, lambda text: va.check_spec(text)),
            ("spec with a security section", COMPLETE_SPEC + "\n## Security\nNo untrusted input.\n",
             lambda text: va.check_spec(text)),
            ("feature plan", PLAN_FULL, lambda text: va.check_plan(text, PLAN_SPEC)),
            ("feature plan, the spec's block edited", PLAN_SPEC, lambda text: va.check_plan(PLAN_FULL, text)),
            ("uncovered feature plan", PLAN_UNCOVERED, lambda text: va.check_plan(text, PLAN_SPEC)),
            ("bugfix plan", BUGFIX_PLAN, lambda text: va.check_plan(text, None, bugfix=True)),
            ("bugfix plan without sections",
             BUGFIX_PLAN.replace(BUGFIX_BUG_SECTION, "").replace(BUGFIX_AC_SECTION, ""),
             lambda text: va.check_plan(text, None, bugfix=True)),
        )
        for name, text, check in cases:
            edited = _into_block(text, BODY_LOOKALIKES)
            with self.subTest(case=name):
                self.assertEqual(va.parse_frontmatter(edited).get("status"), va.parse_frontmatter(text)["status"])
                self.assertEqual(check(edited), check(text))

    def test_the_body_is_the_runner_body(self):
        # The runner fingerprints `frontmatter.split(text)[1]` (contract §5); the validator's body
        # checks read `_body(text)`. They must be the same text, or a body edit could slip past the
        # fingerprint, or a fingerprinted change past the checks.
        scripts = str(SCRIPT.parent)
        sys.path.insert(0, scripts)
        try:
            from sdlc_runner import frontmatter
        finally:
            sys.path.remove(scripts)
        shapes = (
            ("plain", "---\nwork_id: w\n---\n# Body\n"),
            ("trailing spaces on the delimiters", "--- \nwork_id: w\n---  \n# Body\n"),
            ("no closer", "---\nwork_id: w\n# Body\n"),
            ("indented closer", "---\nwork_id: w\n  ---\n# Body\n---\nmore\n"),
            ("---- line", "---\nwork_id: w\n----\n---\n# Body\n"),
            ("invalid line in the block", "---\nnotes\n---\n# Body\n"),
            ("empty body", "---\nwork_id: w\n---\n"),
            ("closer is the last line, no newline", "---\nwork_id: w\n---"),
            ("a second block in the body", "---\na: 1\n---\n---\nb: 2\n---\n# Body\n"),
            ("not first", "\n---\na: 1\n---\n# Body\n"),
            ("line separator U+2028", "--- work_id: w --- # Body\n"),
            ("lone carriage returns", "---\rwork_id: w\r---\r# Body\r"),
        )
        for name, text in shapes + tuple((n, _into_block(t, BODY_LOOKALIKES)) for n, t in (
                ("spec", COMPLETE_SPEC), ("plan", PLAN_FULL), ("bugfix plan", BUGFIX_PLAN))):
            with self.subTest(shape=name):
                self.assertEqual(va._body(text), frontmatter.split(text)[1])

    def test_an_unterminated_block_is_body(self):
        # No closer: there is no block, so every line is body, as before.
        text = "---\n" + _body_only(COMPLETE_SPEC)
        self.assertEqual(va.parse_frontmatter(text), {})
        self.assertEqual(va.check_spec(text)["errors"], [])

    def test_the_block_is_still_scanned_for_placeholders_and_secrets(self):
        # The scan reads every line, and reports the file's own line numbers.
        secret = "AKIA" + "IOSFODNN7EXAMPLE"
        text = _into_block(COMPLETE_SPEC, "# TODO: owner\naws: " + secret)
        lines = text.splitlines()
        todo_line = lines.index("# TODO: owner") + 1
        secret_line = lines.index("aws: " + secret) + 1
        scan = va.scan_placeholders_and_secrets(text)
        self.assertIn("placeholder:%d" % todo_line, scan["warnings"])
        self.assertIn("possible_secret:%d=***MASKED***" % secret_line, scan["errors"])
        body_todo = text.replace("No change to the nightly schedule.", "No change to the nightly schedule. TBD")
        line = body_todo.splitlines().index("No change to the nightly schedule. TBD") + 1
        self.assertIn("placeholder:%d" % line, va.scan_placeholders_and_secrets(body_todo)["warnings"])


class TestRunInterface(unittest.TestCase):
    """`run(mode, file, spec, strict)` is imported, not spawned (scripts/run_procedure_eval.py, the
    runner's `validator` check). It returns `(exit_code, fields)`, and an artifact it cannot read is
    a failed gate with a named reason, never an exception out of the caller."""

    def test_run_returns_exit_code_and_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.md"
            plan.write_bytes(BUGFIX_PLAN.encode("utf-8"))
            result = va.run("plan", str(plan), None, True)
            self.assertIsInstance(result, tuple)
            code, fields = result
            self.assertEqual(code, 0, fields)
            self.assertEqual(fields["artifacts_validation"], "passed")

    def test_unreadable_artifact_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            undecodable = Path(tmp) / "bad.md"
            undecodable.write_bytes(b"---\nwork_id: \xff\n---\n")
            cases = (
                ("missing", Path(tmp) / "absent.md", "file_unreadable:missing"),
                ("not utf-8", undecodable, "file_unreadable:not_utf8"),
                ("a directory", Path(tmp), "file_unreadable:error"),
            )
            for name, path, error in cases:
                with self.subTest(case=name):
                    code, fields = va.run("plan", str(path), None, True)
                    self.assertEqual(code, 1, fields)
                    self.assertIn("error=" + error, fields)
                    self.assertEqual(fields["artifacts_validation"], "failed")
                    rc, out, err = run_cli("--mode", "plan", "--file", str(path), "--strict")
                    self.assertEqual(rc, 1, out + err)
                    self.assertIn("error=" + error, out.splitlines())
                    self.assertEqual(err, "", "a traceback instead of a failed gate")

    def test_unreadable_spec_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.md"
            plan.write_bytes(PLAN_FULL.encode("utf-8"))
            absent = Path(tmp) / "absent.md"
            code, fields = va.run("plan", str(plan), str(absent), True)
            self.assertEqual(code, 1, fields)
            self.assertIn("error=spec_unreadable:missing", fields)
            rc, out, err = run_cli("--mode", "plan", "--file", str(plan), "--spec", str(absent), "--strict")
            self.assertEqual(rc, 1, out + err)
            self.assertIn("error=spec_unreadable:missing", out.splitlines())
            self.assertEqual(err, "", "a traceback instead of a failed gate")


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




# ---- design mode, criterion sources and spec-less plans outside bugfix --------------------
# `design.md` is the intent step's artifact: four sections, decisions that carry an id and an
# owner. With `--sources`, every criterion of a spec (or of a spec-less plan) names where it came
# from. A plan with `spec: none` is no longer only a bugfix plan: `flow: feature` and `flow: plan`
# take their own acceptance criteria as well.
DESIGN_OK = """\
# Design: report export

## Intent
Users export a report as CSV so they stop copying numbers by hand every week.

## Non-goals
- No PDF or spreadsheet export in this change.

## Approaches
- A: stream the rows to the response. B: build the file in memory first.

## Decisions
- D1: The export is a CSV file. (user)
- D2: Rows are streamed to the response. (author's call: memory stays flat for large reports)
"""

FEATURE_PLAN = """\
---
work_id: feat-export
spec: none
flow: feature
branch: feat/export
status: draft
---

# Plan: report export

## Acceptance Criteria
- AC1: Given a report, when the user exports it, then a CSV file returns every visible row. (source: request)
- AC2: Given a large report, when it is exported, then rows are streamed. (source: D2)

## Task 1 — Export the report (AC1)
Modify `src/export.py`. TDD: add the failing export test (RED) first.
Run: pytest tests/test_export.py

## Task 2 — Stream the rows (AC1, AC2)
Modify `src/export.py`. TDD: the RED streaming test turns GREEN.
Run: pytest tests/test_export.py
"""

FEATURE_PLAN_AC_SECTION = """\
## Acceptance Criteria
- AC1: Given a report, when the user exports it, then a CSV file returns every visible row. (source: request)
- AC2: Given a large report, when it is exported, then rows are streamed. (source: D2)

"""

CURLY = chr(0x2019)  # the typographic apostrophe a word processor types for `'`


def _spec_with_criteria(criteria):
    """COMPLETE_SPEC with its acceptance-criteria section replaced by `criteria`."""
    head, _, rest = COMPLETE_SPEC.partition("## 3. Acceptance criteria\n")
    _, _, tail = rest.partition("## 4. Edge cases")
    return head + "## 3. Acceptance criteria\n" + criteria + "\n## 4. Edge cases" + tail


def _plan_with_criteria(criteria):
    return FEATURE_PLAN.replace(FEATURE_PLAN_AC_SECTION, "## Acceptance Criteria\n" + criteria + "\n")


def _ac_errors(result):
    return [e for e in result["errors"] if e.startswith("ac_")]


class TestDesignMode(unittest.TestCase):
    def test_design_requires_its_four_sections(self):
        self.assertEqual(va.check_design(DESIGN_OK), {"errors": [], "warnings": []})
        for slug, heading in (("intent", "## Intent"), ("non-goals", "## Non-goals"),
                              ("approaches", "## Approaches"), ("decisions", "## Decisions")):
            with self.subTest(section=slug):
                text = DESIGN_OK.replace(heading, "## Something else")
                self.assertIn("missing_section:" + slug, va.check_design(text)["errors"])
        self.assertEqual(list(va.REQUIRED_DESIGN_SECTIONS), ["intent", "non-goals", "approaches", "decisions"])

    def test_design_decisions_need_id_and_owner(self):
        text = DESIGN_OK.replace(
            "- D2: Rows are streamed to the response. (author's call: memory stays flat for large reports)\n",
            "- Rows are streamed to the response. (user)\n"
            "- D3: Files are named by report id.\n"
            "- D4: Dates are UTC. (author's call: )\n"
            "- **D5** Headers are always written. (user)\n")
        errors = va.check_design(text)["errors"]
        self.assertEqual(errors, ["decision_missing_id:2", "decision_missing_owner:D3", "decision_missing_owner:D4"])
        # A nested bullet is a detail of its decision, not a decision of its own.
        nested = DESIGN_OK.replace("(user)\n", "(user)\n  - because users asked for it\n")
        self.assertEqual(va.check_design(nested)["errors"], [])
        # An owner tag on a wrapped line counts.
        wrapped = DESIGN_OK.replace("is a CSV file. (user)", "is a CSV file.\n  (user)")
        self.assertEqual(va.check_design(wrapped)["errors"], [])

    def test_design_duplicate_decision_id_is_an_error(self):
        text = DESIGN_OK + "- D1: The export is also zipped. (user)\n"
        self.assertEqual(va.check_design(text)["errors"], ["decision_duplicate_id:D1"])
        # `D01` and `D1` name the same decision.
        text = DESIGN_OK + "- D01: The export is also zipped. (user)\n"
        self.assertEqual(va.check_design(text)["errors"], ["decision_duplicate_id:D01"])

    def test_design_owner_tags_tolerate_crlf_bom_and_curly_apostrophe(self):
        curly = DESIGN_OK.replace("author's call", "author" + CURLY + "s call")
        turkish_reason = "b" + chr(0xfc) + "y" + chr(0xfc) + "k raporlarda bellek sabit kal" + chr(0x131) + "r"
        turkish = curly.replace("memory stays flat for large reports", turkish_reason)
        for name, text in (("curly", curly), ("turkish reason", turkish),
                           ("crlf", DESIGN_OK.replace("\n", "\r\n")),
                           ("bom and crlf", chr(0xfeff) + turkish.replace("\n", "\r\n"))):
            with self.subTest(case=name):
                self.assertEqual(va.check_design(text), {"errors": [], "warnings": []})
        # The owner tag must be one of the two forms.
        bad = DESIGN_OK.replace("(user)", "(somebody)")
        self.assertEqual(va.check_design(bad)["errors"], ["decision_missing_owner:D1"])

    def test_cli_design_mode_and_sources_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            design = Path(tmp) / "design.md"
            design.write_bytes(DESIGN_OK.encode("utf-8"))
            rc, out, err = run_cli("--mode", "design", "--file", str(design), "--strict")
            self.assertEqual(rc, 0, out + err)
            self.assertIn("mode=design", out.splitlines())
            self.assertIn("artifacts_validation=passed", out.splitlines())
            design.write_bytes(DESIGN_OK.replace("(user)", "").encode("utf-8"))
            rc, out, err = run_cli("--mode", "design", "--file", str(design))
            self.assertEqual(rc, 1, out + err)
            self.assertIn("error=decision_missing_owner:D1", out.splitlines())
            # --sources, --design and --check drive a spec check.
            design.write_bytes(DESIGN_OK.encode("utf-8"))
            check = Path(tmp) / "w.check.json"
            check.write_bytes(b'{"questions": [{"id": "Q1"}]}')
            spec = Path(tmp) / "spec.md"
            spec.write_bytes(_spec_with_criteria(
                "- AC1: Given a refund, when the job runs, then the total drops once. (source: D1, Q1)\n"
            ).encode("utf-8"))
            rc, out, err = run_cli("--mode", "spec", "--file", str(spec), "--sources",
                                   "--design", str(design), "--check", str(check))
            self.assertEqual(rc, 0, out + err)
            self.assertNotIn("error=ac_", out)
            rc, out, err = run_cli("--mode", "spec", "--file", str(spec), "--sources", "--design", str(design))
            self.assertEqual(rc, 1, out + err)
            self.assertIn("error=ac_unknown_source:AC1:Q1", out.splitlines())
            rc, out, err = run_cli("--mode", "spec", "--file", str(spec), "--sources",
                                   "--design", str(Path(tmp) / "absent.md"))
            self.assertEqual(rc, 1, out + err)
            self.assertIn("error=design_unreadable:missing", out.splitlines())
            check.write_bytes(b"{not json")
            rc, out, err = run_cli("--mode", "spec", "--file", str(spec), "--sources", "--check", str(check))
            self.assertEqual(rc, 1, out + err)
            self.assertIn("error=check_unreadable:invalid_json", out.splitlines())


class TestCriterionSources(unittest.TestCase):
    CHECK = {"questions": [{"id": "Q1", "text": "Which format?"}, {"id": "Q2"}]}

    def test_spec_sources_are_ignored_without_the_flag(self):
        spec = _spec_with_criteria(
            "- AC1: Given a refund, when the job runs, then the total drops once.\n"
            "- AC2: Given a replay, when the job runs, then the total drops once. (source: guess)\n")
        plain = va.check_spec(spec)
        self.assertEqual(_ac_errors(plain), [])
        self.assertEqual(va.check_spec(spec, DESIGN_OK, self.CHECK), plain)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spec.md"
            path.write_bytes(spec.encode("utf-8"))
            rc, out, err = run_cli("--mode", "spec", "--file", str(path))
            self.assertEqual(rc, 0, out + err)

    def test_spec_criterion_without_source_fails_with_sources(self):
        spec = _spec_with_criteria(
            "- AC1: Given a refund, when the job runs, then the total drops once. (source: request)\n"
            "- AC2: Given a replay, when the job runs, then the total drops once.\n"
            "- A detail bullet that carries no id and so is no criterion.\n"
            "  - AC9: a nested bullet is a detail, not a criterion\n")
        result = va.check_spec(spec, DESIGN_OK, self.CHECK, require_sources=True)
        # AC9 sits on a nested bullet, so it is no criterion of its own, yet a plan would still have to
        # cover it: it needs a top-level bullet with a source as well.
        self.assertEqual(_ac_errors(result), ["ac_no_source:AC2", "ac_no_source:AC9"])
        self.assertNotIn("ac_no_source:AC2", va.check_spec(spec, DESIGN_OK, self.CHECK)["errors"])
        # An empty tag names nothing.
        empty = spec.replace("then the total drops once.\n- A detail", "then the total drops once. (source: )\n- A detail")
        self.assertEqual(_ac_errors(va.check_spec(empty, DESIGN_OK, self.CHECK, require_sources=True)),
                         ["ac_no_source:AC2", "ac_no_source:AC9"])

    def test_spec_source_on_a_wrapped_line_counts(self):
        spec = _spec_with_criteria(
            "- AC1: Given a refund for an existing charge, when the job runs, then the gross\n"
            "  total is reduced once. (source: request,\n"
            "  D2)\n"
            "- AC-A2: Given a replay, when the job runs, then the total drops once.\n"
            "  (source: D1)\n")
        result = va.check_spec(spec, DESIGN_OK, self.CHECK, require_sources=True)
        self.assertEqual(_ac_errors(result), [])
        # A tag on a NESTED bullet is not the criterion's own.
        nested = spec.replace("  (source: D1)\n", "  - (source: D1)\n")
        self.assertEqual(_ac_errors(va.check_spec(nested, DESIGN_OK, self.CHECK, require_sources=True)),
                         ["ac_no_source:AC-A2"])

    def test_spec_source_must_name_a_known_decision_or_question(self):
        spec = _spec_with_criteria(
            "- AC1: Given a refund, when the job runs, then the total drops once. (source: D9)\n"
            "- AC2: Given a replay, when the job runs, then the total drops once. (source: Q3, Q1, D1)\n")
        result = va.check_spec(spec, DESIGN_OK, self.CHECK, require_sources=True)
        self.assertEqual(_ac_errors(result), ["ac_unknown_source:AC1:D9", "ac_unknown_source:AC2:Q3"])
        # No design file: no decision is known. No check file: no question is known.
        result = va.check_spec(spec, None, None, require_sources=True)
        self.assertEqual(_ac_errors(result), [
            "ac_unknown_source:AC1:D9", "ac_unknown_source:AC2:Q3",
            "ac_unknown_source:AC2:Q1", "ac_unknown_source:AC2:D1"])
        # `request` needs neither file.
        only_request = _spec_with_criteria(
            "- AC1: Given a refund, when the job runs, then the total drops once. (source: request)\n")
        self.assertEqual(_ac_errors(va.check_spec(only_request, None, None, require_sources=True)), [])

    def test_spec_bad_source_token_is_an_error(self):
        spec = _spec_with_criteria(
            "- AC1: Given a refund, when the job runs, then the total drops once. (source: guess, request)\n"
            "- AC2: Given a replay, when the job runs, then the total drops once. (source: d1, Q)\n")
        result = va.check_spec(spec, DESIGN_OK, self.CHECK, require_sources=True)
        self.assertEqual(_ac_errors(result), ["ac_bad_source:AC1:guess", "ac_bad_source:AC2:d1", "ac_bad_source:AC2:Q"])

    def test_specless_plan_criterion_needs_a_request_or_decision_source(self):
        plan = _plan_with_criteria(
            "- AC1: Given a report, when the user exports it, then a CSV file returns every row.\n"
            "- AC2: Given a large report, when it is exported, then rows are streamed. (source: Q1)\n"
            "- AC3: Given an empty report, when it is exported, then only the header row returns. (source: D7)\n")
        result = va.check_plan(plan, None, own_criteria=True, design_text=DESIGN_OK, require_sources=True)
        self.assertEqual(_ac_errors(result), [
            "ac_no_source:AC1", "ac_unknown_source:AC2:Q1", "ac_unknown_source:AC3:D7"])
        self.assertEqual(_ac_errors(va.check_plan(plan, None, own_criteria=True, design_text=DESIGN_OK)), [])
        # A bugfix plan's own criteria are sourced the same way.
        bugfix = va.check_plan(BUGFIX_PLAN, None, bugfix=True, design_text=None, require_sources=True)
        self.assertEqual(_ac_errors(bugfix), ["ac_no_source:AC1", "ac_no_source:AC2"])
        # With a design file, D2 counts; without one, none does.
        self.assertEqual(_ac_errors(va.check_plan(FEATURE_PLAN, None, own_criteria=True, design_text=DESIGN_OK,
                                                  require_sources=True)), [])
        self.assertEqual(_ac_errors(va.check_plan(FEATURE_PLAN, None, own_criteria=True, design_text=None,
                                                  require_sources=True)), ["ac_unknown_source:AC2:D2"])

    def test_plan_sources_change_nothing_with_a_spec(self):
        # A plan checked against a spec has no own criteria, so there is nothing to source.
        spec = "## Acceptance criteria\n- AC1: Given a, when b, then c.\n- AC2: Given d, when e, then f.\n"
        plan = ("# Plan\n## Task 1 (AC1)\nModify `a.py`. TDD: RED first.\nRun: pytest a\n"
                "## Task 2 (AC2)\nModify `b.py`. TDD: RED first.\nRun: pytest b\n")
        self.assertEqual(va.check_plan(plan, spec),
                         va.check_plan(plan, spec, design_text=DESIGN_OK, require_sources=True))
        # The plan's own unsourced section is not read when a spec is the source and own_criteria is off.
        self.assertEqual(va.check_plan(BUGFIX_PLAN, spec, require_sources=True),
                         va.check_plan(BUGFIX_PLAN, spec))


class TestSourcesCannotBeFormattedAway(unittest.TestCase):
    """Every id the coverage check counts is a criterion the plan must build, so with sources on each
    one needs a top-level bullet of the criteria section that names its source. A sub-heading, a group
    bullet, a table or a heading does not take a criterion out of the source rule."""

    def specless_plan(self, criteria):
        """FEATURE_PLAN with its criteria section body replaced by `criteria`, tasks unchanged."""
        return _plan_with_criteria(criteria)

    def run_plan_cli(self, plan):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.md"
            path.write_bytes(plan.encode("utf-8"))
            design = Path(tmp) / "design.md"
            design.write_bytes(DESIGN_OK.encode("utf-8"))
            return run_cli("--mode", "plan", "--file", str(path), "--strict", "--sources", "--design", str(design))

    def test_spec_criteria_under_sub_headings_need_sources(self):
        spec = _spec_with_criteria(
            "### Login\n"
            "- AC1: Given a refund, when the job runs, then the total drops once. (source: request)\n\n"
            "### Export\n"
            "- AC2: Given a replay, when the job runs, then the total drops once.\n"
            "- AC3: Given an empty file, when the job runs, then it returns an empty ledger. (source: D9)\n")
        result = va.check_spec(spec, DESIGN_OK, None, require_sources=True)
        self.assertEqual(_ac_errors(result), ["ac_no_source:AC2", "ac_unknown_source:AC3:D9"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spec.md"
            path.write_bytes(spec.encode("utf-8"))
            rc, out, err = run_cli("--mode", "spec", "--file", str(path), "--sources")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("error=ac_no_source:AC2", out.splitlines())
        self.assertIn("error=ac_unknown_source:AC3:D9", out.splitlines())
        # The section still ends at the next heading of its own level.
        self.assertNotIn("ac_no_source:AC1", result["errors"])

    def test_spec_criterion_nested_under_a_group_bullet_needs_its_own_bullet(self):
        spec = _spec_with_criteria(
            "- Export rules:\n"
            "  - AC1: Given a refund, when the job runs, then the total drops once. (source: request)\n"
            "- AC2: Given a replay, when the job runs, then the total drops once. (source: request)\n")
        self.assertEqual(_ac_errors(va.check_spec(spec, DESIGN_OK, None, require_sources=True)),
                         ["ac_no_source:AC1"])

    def test_spec_criterion_outside_the_criteria_section_needs_a_source(self):
        # The plan coverage reads every id of the spec, so an id written under another heading is a
        # criterion too.
        spec = _spec_with_criteria(
            "- AC1: Given a refund, when the job runs, then the total drops once. (source: request)\n")
        spec = spec.replace("## 4. Edge cases\n", "## 4. Edge cases\n- AC4: Given an empty file, when the job "
                                                  "runs, then it returns an empty ledger.\n")
        self.assertEqual(_ac_errors(va.check_spec(spec, DESIGN_OK, None, require_sources=True)),
                         ["ac_no_source:AC4"])

    def test_specless_plan_criteria_in_a_table_need_sources(self):
        plan = self.specless_plan(
            "| Id | Criterion | Source |\n|---|---|---|\n"
            "| AC1 | Given a report, when the user exports it, then a CSV file returns every row. | request |\n"
            "| AC2 | Given a large report, when it is exported, then rows are streamed. | D9 |\n")
        result = va.check_plan(plan, None, own_criteria=True, design_text=DESIGN_OK, require_sources=True)
        self.assertEqual(_ac_errors(result), ["ac_no_source:AC1", "ac_no_source:AC2"])
        self.assertEqual(result["metrics"]["plan_ac_covered"], 2)  # coverage still counts both
        rc, out, err = self.run_plan_cli(plan)
        self.assertEqual(rc, 1, out + err)
        self.assertIn("error=ac_no_source:AC1", out.splitlines())
        self.assertIn("artifacts_validation=failed", out.splitlines())

    def test_specless_plan_criteria_as_headings_need_sources(self):
        plan = self.specless_plan(
            "### AC1: Given a report, when the user exports it, then a CSV file returns every row. (source: request)\n"
            "### AC2: Given a large report, when it is exported, then rows are streamed.\n")
        result = va.check_plan(plan, None, own_criteria=True, design_text=DESIGN_OK, require_sources=True)
        self.assertEqual(_ac_errors(result), ["ac_no_source:AC1", "ac_no_source:AC2"])
        rc, out, err = self.run_plan_cli(plan)
        self.assertEqual(rc, 1, out + err)
        self.assertIn("error=ac_no_source:AC2", out.splitlines())

    def test_specless_plan_criterion_nested_under_a_group_bullet_needs_its_own_bullet(self):
        plan = self.specless_plan(
            "- Export:\n"
            "  - AC1: Given a report, when the user exports it, then a CSV file returns every row. (source: request)\n"
            "- AC2: Given a large report, when it is exported, then rows are streamed. (source: D2)\n")
        result = va.check_plan(plan, None, own_criteria=True, design_text=DESIGN_OK, require_sources=True)
        self.assertEqual(_ac_errors(result), ["ac_no_source:AC1"])

    def test_well_formed_criteria_still_pass(self):
        self.assertEqual(_ac_errors(va.check_plan(FEATURE_PLAN, None, own_criteria=True, design_text=DESIGN_OK,
                                                  require_sources=True)), [])
        rc, out, err = self.run_plan_cli(FEATURE_PLAN)
        self.assertEqual(rc, 0, out + err)
        spec = _spec_with_criteria(
            "- AC1: Given a refund, when the job runs, then the total drops once. (source: request)\n"
            "- AC2: Given a replay, when the job runs, then it returns the prior result, unlike AC1. (source: D1)\n")
        self.assertEqual(_ac_errors(va.check_spec(spec, DESIGN_OK, None, require_sources=True)), [])


class TestLongIdsAreReportedNotRaised(unittest.TestCase):
    """An id is 1 to 6 digits. A longer run of digits is no id, so it is reported like any other bad
    token; int() is never handed thousands of digits (Python refuses more than 4300)."""

    LONG = "1" * 5000

    def test_long_decision_id_is_a_decision_without_an_id(self):
        design = DESIGN_OK.replace("- D2:", "- D%s:" % self.LONG)
        self.assertEqual(va.check_design(design)["errors"], ["decision_missing_id:2"])
        self.assertEqual(va.check_design(DESIGN_OK.replace("- D2:", "- D123456:"))["errors"], [])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design.md"
            path.write_bytes(design.encode("utf-8"))
            rc, out, err = run_cli("--mode", "design", "--file", str(path))
        self.assertEqual((rc, err), (1, ""), out + err)
        self.assertIn("error=decision_missing_id:2", out.splitlines())

    def test_long_source_token_is_a_bad_source(self):
        for kind in ("D", "Q"):
            with self.subTest(kind=kind):
                spec = _spec_with_criteria(
                    "- AC1: Given a refund, when the job runs, then the total drops once. (source: %s%s)\n"
                    % (kind, self.LONG))
                errors = _ac_errors(va.check_spec(spec, DESIGN_OK, {"questions": [{"id": "Q1"}]},
                                                  require_sources=True))
                self.assertEqual(errors, ["ac_bad_source:AC1:%s%s" % (kind, self.LONG)])

    def test_long_check_question_id_names_no_question(self):
        check = {"questions": [{"id": "Q" + self.LONG}, {"id": "Q123456"}, {"id": "Q1"}]}
        self.assertEqual(va._check_questions(check), {1, 123456})

    def test_long_criterion_id_is_no_id(self):
        spec = _spec_with_criteria(
            "- AC%s: Given a refund, when the job runs, then the total drops once. (source: request)\n" % self.LONG)
        result = va.check_spec(spec, DESIGN_OK, None, require_sources=True)
        self.assertIn("ac_missing_id:1", result["warnings"])
        plan = ("# Plan\n## Task 1 (AC%s)\nModify `a.py`. TDD: RED first.\nRun: pytest a\n" % self.LONG)
        result = va.check_plan(plan, spec)
        self.assertEqual(result["metrics"]["plan_ac_covered"], 0)
        self.assertIn("ac_source_empty", result["warnings"])
        self.assertEqual(va.check_plan(plan.replace("AC" + self.LONG, "AC123456"),
                                       spec.replace("AC" + self.LONG, "AC123456"))["metrics"]["plan_ac_covered"], 1)

    def test_long_task_id_is_no_task_number(self):
        plan = "# Plan\n## Task T%s\nModify `a.py`. TDD: RED first.\nRun: pytest a\n" % self.LONG
        result = va.check_plan(plan, None)
        self.assertEqual(result["metrics"]["plan_tasks"], 1)  # still a `## Task` heading, with no number
        self.assertEqual(va.check_plan("# Plan\nT%s first\n" % self.LONG, None)["metrics"]["plan_tasks"], 0)


def _feedback(*records):
    """A feedback.jsonl body: a dict is one JSON line, a string is written as it is (a malformed line)."""
    return "".join((record if isinstance(record, str) else json.dumps(record)) + "\n" for record in records)


# What `sdlc reject` leaves in a package: a change request at the spec gate, one at the plan gate, then a
# record of another kind.
FEEDBACK = _feedback(
    {"seq": 1, "kind": "reject", "gate": "spec-review", "quote": "Name the export file too."},
    {"seq": 2, "kind": "reject", "gate": "plan-review", "quote": "Split the task in two."},
    {"seq": 3, "kind": "note", "gate": "spec-review", "quote": "Not a change request."},
)


class TestFeedbackSources(unittest.TestCase):
    """`F<n>` names the reject record whose `seq` is n in the package's feedback.jsonl, at one of the
    gates given (any gate when none is): a criterion added or changed on the user's change request at a
    gate cites it. Every other F number is an unknown source; the reader never raises."""

    GATES = ["spec-review"]

    def spec(self, tag):
        return _spec_with_criteria(
            "- AC1: Given a refund, when the job runs, then the total drops once. (source: request)\n"
            "- AC2: Given a replay, when the job runs, then the export file is named. (source: %s)\n" % tag)

    def errors(self, tag, feedback=FEEDBACK, gates=GATES):
        return _ac_errors(va.check_spec(self.spec(tag), DESIGN_OK, None, require_sources=True,
                                        feedback_text=feedback, feedback_gates=gates))

    def run_spec(self, tmp, tag, feedback_path, gates=GATES):
        spec = Path(tmp) / "spec.md"
        spec.write_bytes(self.spec(tag).encode("utf-8"))
        code, fields = va.run("spec", str(spec), None, False, sources=True, feedback_path=feedback_path,
                              feedback_gates=gates)
        return code, sorted(key for key in fields if key.startswith("error="))

    def test_a_reject_record_of_the_gate_is_a_source(self):
        self.assertEqual(self.errors("F1"), [])
        self.assertEqual(self.errors("request, F01"), [])  # F01 and F1 name the same record
        self.assertEqual(self.errors("f1, F"), ["ac_bad_source:AC2:f1", "ac_bad_source:AC2:F"])
        # Without the flag the tag is not read at all.
        self.assertEqual(_ac_errors(va.check_spec(self.spec("F9"), feedback_text=FEEDBACK)), [])

    def test_an_unknown_seq_is_an_unknown_source(self):
        self.assertEqual(self.errors("F9"), ["ac_unknown_source:AC2:F9"])
        self.assertEqual(self.errors("F1, F4"), ["ac_unknown_source:AC2:F4"])

    def test_a_reject_record_at_another_gate_is_unknown(self):
        self.assertEqual(self.errors("F2"), ["ac_unknown_source:AC2:F2"])
        self.assertEqual(self.errors("F2", gates=["plan-review"]), [])
        self.assertEqual(self.errors("F1", gates=["plan-review"]), ["ac_unknown_source:AC2:F1"])
        self.assertEqual(self.errors("F1, F2", gates=["spec-review", "plan-review"]), [])
        # No gate given: a reject record at any gate counts.
        self.assertEqual(self.errors("F1, F2", gates=None), [])
        self.assertEqual(self.errors("F1, F2", gates=[]), [])

    def test_a_record_of_another_kind_is_unknown(self):
        self.assertEqual(self.errors("F3"), ["ac_unknown_source:AC2:F3"])
        self.assertEqual(self.errors("F3", gates=None), ["ac_unknown_source:AC2:F3"])

    def test_a_missing_or_unreadable_feedback_file_names_no_record(self):
        self.assertEqual(self.errors("F1", feedback=None), ["ac_unknown_source:AC2:F1"])
        self.assertEqual(self.errors("F1", feedback=""), ["ac_unknown_source:AC2:F1"])
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "feedback.jsonl"
            good.write_bytes(FEEDBACK.encode("utf-8"))
            self.assertEqual(self.run_spec(tmp, "F1", str(good)), (0, []))
            not_utf8 = Path(tmp) / "not-utf8.jsonl"
            not_utf8.write_bytes(b"\xff\xfe" + FEEDBACK.encode("utf-8"))
            # A folder cannot be read as a file. None of these is an error of its own: the token is unknown.
            for name, path in (("missing", str(Path(tmp) / "absent.jsonl")), ("folder", tmp),
                               ("not utf-8", str(not_utf8)), ("not given", None)):
                with self.subTest(feedback=name):
                    self.assertEqual(self.run_spec(tmp, "F1", path), (1, ["error=ac_unknown_source:AC2:F1"]))

    def test_a_quote_with_unicode_line_breaks_keeps_its_record(self):
        # The runner stores a quote as it is (UTF-8, no ASCII escapes) and reads its logs split on LF
        # only, so U+2028, U+2029 and U+0085 inside a quote do not end the record's line.
        scripts = str(SCRIPT.parent)
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from sdlc_runner import logs

        quote = ("Name the export file" + chr(0x2028) + "and say" + chr(0x2029) + "where it goes" + chr(0x85)
                 + "too.")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feedback.jsonl"
            for text in (quote, "And the date."):
                logs.append(path, {"kind": "reject", "gate": "spec-review", "quote": text, "fingerprint": "0" * 16})
            raw = path.read_bytes()
            for char in (chr(0x2028), chr(0x2029), chr(0x85)):
                self.assertIn(char.encode("utf-8"), raw)  # written raw, as the runner writes it
            self.assertEqual([record["quote"] for record in logs.read(path)], [quote, "And the date."])
            self.assertEqual(va._feedback_numbers(raw.decode("utf-8"), self.GATES), {1, 2})
            self.assertEqual(self.run_spec(tmp, "F1, F2", str(path)), (0, []))

    def test_a_malformed_line_is_skipped(self):
        feedback = _feedback(
            "not json",
            '{"seq": 4, "kind": "reject", "gate": "spec-review"',
            "[1, 2]",
            '"a string"',
            "",
            {"seq": True, "kind": "reject", "gate": "spec-review"},
            {"seq": "5", "kind": "reject", "gate": "spec-review"},
            {"seq": 6.0, "kind": "reject", "gate": "spec-review"},
            {"seq": 7, "kind": "reject", "gate": ["spec-review"]},
            {"kind": "reject", "gate": "spec-review"},
            '{"seq": %s, "kind": "reject", "gate": "spec-review"}' % ("9" * 5000),
            "[" * 100000 + "]" * 100000,
            {"seq": 8, "kind": "reject", "gate": "spec-review"},
        )
        self.assertEqual(va._feedback_numbers(feedback, ["spec-review"]), {8})
        self.assertEqual(self.errors("F8", feedback=feedback), [])
        for seq in (1, 4, 5, 6, 7):
            with self.subTest(seq=seq):
                self.assertEqual(self.errors("F%d" % seq, feedback=feedback), ["ac_unknown_source:AC2:F%d" % seq])
        # CRLF line ends and a byte-order mark are the same log.
        self.assertEqual(va._feedback_numbers(chr(0xFEFF) + FEEDBACK.replace("\n", "\r\n"), None), {1, 2})

    def test_a_long_digit_run_is_reported_not_raised(self):
        long = "F" + "1" * 5000
        self.assertEqual(self.errors(long), ["ac_bad_source:AC2:%s" % long])
        self.assertEqual(self.errors("F1234567"), ["ac_bad_source:AC2:F1234567"])
        six = _feedback({"seq": 123456, "kind": "reject", "gate": "spec-review"})
        self.assertEqual(self.errors("F123456", feedback=six), [])

    def test_cli_feedback_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / "spec.md"
            spec.write_bytes(self.spec("F1, F2").encode("utf-8"))
            feedback = Path(tmp) / "feedback.jsonl"
            feedback.write_bytes(FEEDBACK.encode("utf-8"))
            base = ("--mode", "spec", "--file", str(spec), "--sources", "--feedback", str(feedback))
            rc, out, err = run_cli(*base)  # no gate given: any gate counts
            self.assertEqual(rc, 0, out + err)
            rc, out, err = run_cli(*base, "--feedback-gate", "spec-review")
            self.assertEqual(rc, 1, out + err)
            self.assertEqual([line for line in out.splitlines() if line.startswith("error=")],
                             ["error=ac_unknown_source:AC2:F2"])
            rc, out, err = run_cli(*base, "--feedback-gate", "spec-review", "--feedback-gate", "plan-review")
            self.assertEqual(rc, 0, out + err)
            # Without --feedback no record is known.
            rc, out, err = run_cli("--mode", "spec", "--file", str(spec), "--sources")
            self.assertEqual(rc, 1, out + err)
            self.assertIn("error=ac_unknown_source:AC2:F1", out.splitlines())
            # Without --sources both flags are ignored, as --design and --check are.
            rc, out, err = run_cli("--mode", "spec", "--file", str(spec), "--feedback", str(Path(tmp) / "absent.jsonl"),
                                   "--feedback-gate", "spec-review")
            self.assertEqual(rc, 0, out + err)
            self.assertNotIn("error=", out)

    def test_a_specless_plan_cites_a_feedback_record(self):
        plan = _plan_with_criteria(
            "- AC1: Given a report, when the user exports it, then a CSV file returns every visible row. "
            "(source: request)\n"
            "- AC2: Given a large report, when it is exported, then rows are streamed. (source: D2, F2)\n")
        result = va.check_plan(plan, None, own_criteria=True, design_text=DESIGN_OK, require_sources=True,
                               feedback_text=FEEDBACK, feedback_gates=["plan-review"])
        self.assertEqual(_ac_errors(result), [])
        result = va.check_plan(plan, None, own_criteria=True, design_text=DESIGN_OK, require_sources=True,
                               feedback_text=FEEDBACK, feedback_gates=["spec-review"])
        self.assertEqual(_ac_errors(result), ["ac_unknown_source:AC2:F2"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.md"
            path.write_bytes(plan.encode("utf-8"))
            design = Path(tmp) / "design.md"
            design.write_bytes(DESIGN_OK.encode("utf-8"))
            feedback = Path(tmp) / "feedback.jsonl"
            feedback.write_bytes(FEEDBACK.encode("utf-8"))
            base = ("--mode", "plan", "--file", str(path), "--strict", "--sources", "--design", str(design),
                    "--feedback", str(feedback))
            rc, out, err = run_cli(*base, "--feedback-gate", "plan-review")
            self.assertEqual(rc, 0, out + err)
            rc, out, err = run_cli(*base, "--feedback-gate", "spec-review")
            self.assertEqual(rc, 1, out + err)
            self.assertIn("error=ac_unknown_source:AC2:F2", out.splitlines())


class TestCriterionSourcesList(unittest.TestCase):
    """`criterion_sources` lists the criteria the source check reads, each with its tokens as written:
    the runner's gate card shows them to the user (hybrid design §4.4)."""

    def test_spec_criteria_with_their_sources(self):
        spec = _spec_with_criteria(
            "### Export\n"
            "- AC1: Given a refund, when the job runs, then the total drops once. (source: request,  D2 )\n"
            "- AC-A2: Given a replay, when the job runs, then the total\n"
            "  drops once. (source: F1)\n"
            "  - AC9: a nested bullet is a detail, not a criterion (source: D1)\n"
            "- AC3: Given an empty file, when the job runs, then it returns an empty ledger.\n"
            "- AC4: Given a refund twice, when the job runs, then it counts once. (source: guess, )\n"
            "- A detail bullet without an id.\n"
            "```\n- AC7: Given an example in a fence, then nothing. (source: request)\n```\n")
        expected = [("AC1", ["request", "D2"]), ("AC-A2", ["F1"]), ("AC3", []), ("AC4", ["guess"])]
        self.assertEqual(va.criterion_sources(spec, "spec"), expected)
        self.assertEqual(va.criterion_sources(chr(0xFEFF) + spec.replace("\n", "\r\n"), "spec"), expected)
        # The criteria are those the source check reads. The nested and the fenced id are no criterion,
        # so the check reports them as ids without a criterion bullet of their own.
        self.assertEqual(_ac_errors(va.check_spec(spec, DESIGN_OK, None, require_sources=True,
                                                  feedback_text=FEEDBACK, feedback_gates=["spec-review"])),
                         ["ac_no_source:AC3", "ac_bad_source:AC4:guess", "ac_no_source:AC7", "ac_no_source:AC9"])
        self.assertEqual(va.criterion_sources(COMPLETE_SPEC.replace("## 3. Acceptance criteria", "## 3. Rules"),
                                              "spec"), [])

    def test_plan_criteria_only_for_a_specless_plan(self):
        self.assertEqual(va.criterion_sources(FEATURE_PLAN, "plan"), [("AC1", ["request"]), ("AC2", ["D2"])])
        # A plan checked against a spec has no criteria of its own.
        with_spec = FEATURE_PLAN.replace("spec: none", "spec: ../spec/feat-export.md")
        self.assertEqual(va.criterion_sources(with_spec, "plan"), [])
        # A section after the tasks is not read, as the source check does not read it.
        late = FEATURE_PLAN.replace(FEATURE_PLAN_AC_SECTION, "") + "\n" + FEATURE_PLAN_AC_SECTION
        self.assertEqual(va.criterion_sources(late, "plan"), [])
        self.assertEqual(va.criterion_sources(DESIGN_OK, "design"), [])


class TestSpeclessPlans(unittest.TestCase):
    def test_specless_feature_plan_takes_its_own_criteria(self):
        result = va.check_plan(FEATURE_PLAN, None, own_criteria=True)
        self.assertEqual(result["errors"], [], result)
        self.assertEqual(result["metrics"]["plan_ac_covered"], 2, result)
        self.assertNotIn("ac_source_missing", result["warnings"])
        # Without own_criteria a plan has no source for its coverage (the spec rule is unchanged).
        plain = va.check_plan(FEATURE_PLAN, None)
        self.assertIn("ac_source_missing", plain["warnings"])
        # AC2 is named only by the criteria section, so dropping it from Task 2 uncovers it.
        partial = FEATURE_PLAN.replace("(AC1, AC2)", "(AC1)")
        result = va.check_plan(partial, None, own_criteria=True)
        self.assertEqual(_warnings_with("ac_not_covered:", result["warnings"]), ["ac_not_covered:AC2"])
        # A criterion with no id is reported, as for a bugfix plan.
        idless = _plan_with_criteria(
            "- Given a report, when the user exports it, then a CSV file returns every row.\n")
        self.assertIn("ac_missing_id:1", va.check_plan(idless, None, own_criteria=True)["warnings"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.md"
            path.write_bytes(FEATURE_PLAN.encode("utf-8"))
            rc, out, err = run_cli("--mode", "plan", "--file", str(path), "--strict")
            self.assertEqual(rc, 0, out + err)
            self.assertIn("plan_ac_covered=2", out)
            self.assertNotIn("ac_source_missing", out)

    def test_specless_plan_flow_is_accepted(self):
        self.assertEqual(va.SPECLESS_FLOWS, ("bugfix", "feature", "plan"))
        for flow in ("bugfix", "feature", "plan"):
            with self.subTest(flow=flow):
                meta = {"spec": "none", "flow": flow}
                self.assertEqual(va.check_plan_kind(meta), [])
                self.assertTrue(va.is_specless_plan(meta))
        # is_bugfix_plan keeps its meaning.
        self.assertTrue(va.is_bugfix_plan({"spec": "none", "flow": "bugfix"}))
        self.assertFalse(va.is_bugfix_plan({"spec": "none", "flow": "feature"}))
        self.assertFalse(va.is_specless_plan({"spec": "../spec/x.md", "flow": "feature"}))
        self.assertFalse(va.is_specless_plan({"flow": "feature"}))

    def test_specless_feature_plan_needs_no_bug_section(self):
        self.assertNotIn("## Bug", FEATURE_PLAN)
        self.assertEqual(va.check_plan(FEATURE_PLAN, None, own_criteria=True)["errors"], [])
        # A bugfix plan still does.
        no_bug = BUGFIX_PLAN.replace(BUGFIX_BUG_SECTION, "")
        result = va.check_plan(no_bug, None, bugfix=True, own_criteria=True)
        self.assertIn("missing_section:bug", result["errors"], result)
        # And a feature plan still needs its criteria section.
        none = FEATURE_PLAN.replace(FEATURE_PLAN_AC_SECTION, "")
        self.assertEqual(va.check_plan(none, None, own_criteria=True)["errors"],
                         ["missing_section:acceptance-criteria"])

    def test_specless_feature_plan_criteria_after_tasks_is_an_error(self):
        late = FEATURE_PLAN.replace(FEATURE_PLAN_AC_SECTION, "") + "\n" + FEATURE_PLAN_AC_SECTION
        result = va.check_plan(late, None, own_criteria=True)
        self.assertEqual(result["errors"], ["ac_section_after_tasks"], result)
        # The bugfix code is unchanged for a bugfix plan.
        self.assertIn("bugfix_ac_section_after_tasks",
                      va.check_plan(_bugfix_ac_after_tasks(), None, bugfix=True)["errors"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.md"
            path.write_bytes(late.encode("utf-8"))
            rc, out, err = run_cli("--mode", "plan", "--file", str(path))
            self.assertEqual(rc, 1, out + err)
            self.assertIn("error=ac_section_after_tasks", out.splitlines())

    def test_spec_none_with_another_flow_reports_the_new_code(self):
        for flow in ("refactor", "test", "feature-x", ""):
            with self.subTest(flow=flow), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "plan.md"
                path.write_bytes(FEATURE_PLAN.replace("flow: feature", "flow: " + flow).encode("utf-8"))
                rc, out, err = run_cli("--mode", "plan", "--file", str(path))
                self.assertEqual(rc, 1, out + err)
                self.assertIn("error=spec_none_requires_specless_flow", out.splitlines())
                self.assertNotIn("spec_none_requires_flow_bugfix", out)
        # A spec-less feature plan given a spec anyway is `spec_none_with_spec`, as a bugfix plan is.
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.md"
            plan.write_bytes(FEATURE_PLAN.encode("utf-8"))
            spec = Path(tmp) / "spec.md"
            spec.write_bytes(COMPLETE_SPEC.encode("utf-8"))
            rc, out, err = run_cli("--mode", "plan", "--file", str(plan), "--spec", str(spec))
            self.assertEqual(rc, 1, out + err)
            self.assertIn("error=spec_none_with_spec", out.splitlines())


if __name__ == "__main__":
    unittest.main()
