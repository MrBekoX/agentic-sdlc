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
