"""Regression tests for the VA findings of the f430715 bug audit (validators, resolver, context probe,
eval graders). Each test is named after its finding id and failed on f430715.

Secrets are synthetic and built at run time; no credential-shaped literal is written here. Stub CLIs
are written to a temporary directory and put first on PATH, so no model CLI ever runs.
"""
import importlib.util
import json
import os
import secrets
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location("_audit_va_" + name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


va = _load("validate_artifacts")
rwp = _load("resolve_work_package")
dc = _load("detect_context")

from scripts import run_procedure_eval as rpe  # noqa: E402
from scripts import run_routing_eval as rre  # noqa: E402
from scripts import run_trigger_eval as rte  # noqa: E402


def run_script(name, *args, cwd=None, env=None, timeout=120):
    proc = subprocess.run([sys.executable, str(SCRIPTS / name), *map(str, args)], cwd=cwd or REPO, env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


SPEC = """\
---
work_id: demo
status: reviewed
---
# Spec: demo
## Problem
The login endpoint accepts empty passwords and returns a session token, which is wrong.
## Business Rules
Passwords must be non-empty; an empty password is rejected with a 400 status code always.
## Acceptance Criteria
- AC1: given an empty password, when POST /login, then returns 400
- AC2: given a valid password, when POST /login, then returns 200 and a token
## Edge Cases
Whitespace-only passwords are treated as empty; null body returns 400 as well here.
## Definition of Done
All acceptance criteria have passing tests and the suite is green on CI for main.
## Must-not-change
Existing successful logins keep working exactly as before with the same token format.
"""

PLAN_HEAD = """\
---
work_id: demo
spec: ../spec/demo.md
branch: feat/demo
status: reviewed
---
# Plan
"""

TASK = "Modify src/login.py. TDD: write failing test first.\nRun: `pytest tests/test_login.py`\n"


def _spec_criteria(criteria):
    """SPEC with the bullets of its acceptance-criteria section replaced by `criteria`."""
    head, _, rest = SPEC.partition("## Acceptance Criteria\n")
    _, _, tail = rest.partition("## Edge Cases\n")
    return head + "## Acceptance Criteria\n" + criteria + "## Edge Cases\n" + tail


class ValidatorCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args):
        rc, out, err = run_script("validate_artifacts.py", *args)
        self.assertEqual(err, "", "a traceback instead of a verdict")
        return rc, out.splitlines()


class TestVA1TaskBlockEnds(ValidatorCase):
    def test_va1_text_after_the_last_task_is_not_covered(self):
        spec = write(self.dir / "spec.md", SPEC)
        plan = write(self.dir / "plan.md", PLAN_HEAD + "## Task 1: reject empty\nCovers AC1. " + TASK
                     + "\n## Out of scope / deferred\nAC2 is NOT implemented by this plan.\n")
        rc, lines = self.cli("--mode", "plan", "--file", plan, "--spec", spec, "--strict")
        self.assertEqual(rc, 1, lines)
        self.assertIn("error=ac_not_covered:AC2", lines)
        self.assertIn("plan_ac_covered=1", lines)

    def test_va1_a_t_id_task_ends_at_the_next_heading(self):
        plan = PLAN_HEAD + "- **T1**: reject empty (AC1)\n" + TASK + "## Deferred\nAC2 waits for a later package.\n"
        result = va.check_plan(plan, SPEC)
        self.assertIn("ac_not_covered:AC2", result["warnings"], result)
        self.assertEqual(result["metrics"], {"plan_tasks": 1, "plan_ac_covered": 1})

    def test_va1_a_task_keeps_its_own_sub_headings(self):
        plan = (PLAN_HEAD + "## Task 1: reject empty (AC1)\n" + TASK + "### Also\nKeeps AC2 working.\n"
                + "## Task 2: keep valid (AC2)\n" + TASK)
        result = va.check_plan(plan, SPEC)
        self.assertEqual(result["metrics"], {"plan_tasks": 2, "plan_ac_covered": 2}, result)
        self.assertEqual(result["warnings"], [], result)
        # A deeper sub-heading of the last task stays in it as well.
        plan = PLAN_HEAD + "## Task 1: both (AC1)\n" + TASK + "#### Steps\nThen AC2.\n"
        self.assertEqual(va.check_plan(plan, SPEC)["metrics"]["plan_ac_covered"], 2)

    def test_va1_verification_after_the_task_section_is_not_the_tasks(self):
        plan = PLAN_HEAD + "## Task 1: both (AC1, AC2)\nModify src/login.py. TDD: RED first.\n## Verification\nRun: pytest\n"
        self.assertIn("task_no_verification", va.check_plan(plan, SPEC)["warnings"])

    def test_va1_the_runner_partition_still_holds_every_line(self):
        # gates.plan_tasks hashes the head and each `_iter_task_blocks` block; text after the last task
        # must stay inside a hashed block so an edit there is never an "appended task".
        body = "# Plan\n## Task 1: a (AC1)\n" + TASK + "## Security\nNotes.\n"
        blocks = va._iter_task_blocks(body)
        self.assertEqual(len(blocks), 1)
        self.assertIn("## Security\nNotes.", blocks[0][1])


class TestVA2Fences(ValidatorCase):
    def test_va2_sections_only_inside_a_fence_are_missing(self):
        spec = SPEC.split("## Business Rules")[0] + (
            "Here is the template we were given:\n```md\n## Business Rules\n## Acceptance Criteria\n"
            "## Edge Cases\n## Definition of Done\n## Must-not-change\n```\n")
        errors = va.check_spec(spec)["errors"]
        for slug in ("business-rules", "acceptance-criteria", "edge-cases", "definition-of-done", "must-not-change"):
            self.assertIn("missing_section:" + slug, errors)

    def test_va2_a_shell_comment_in_a_fence_is_not_a_heading(self):
        spec = SPEC.replace("## Problem\n", "## Problem\n```bash\n# reproduce the bug\ncurl -X POST localhost/login\n```\n")
        self.assertNotIn("thin_section:problem", va.check_spec(spec)["warnings"])

    def test_va2_design_sections_inside_a_fence_are_missing(self):
        design = "# Design\n```md\n## Intent\n## Non-goals\n## Approaches\n## Decisions\n```\n"
        self.assertEqual(sorted(va.check_design(design)["errors"]), sorted(
            "missing_section:" + slug for slug in ("intent", "non-goals", "approaches", "decisions")))


class TestVA3SecretLabels(ValidatorCase):
    def test_va3_labels_in_prose_are_not_secrets(self):
        spec = SPEC.replace(
            "Passwords must be non-empty; an empty password is rejected with a 400 status code always.",
            "Password: must be non-empty. Client secret: never written to logs. API_KEY: required in a header.")
        path = write(self.dir / "spec.md", spec)
        rc, lines = self.cli("--mode", "spec", "--file", path)
        self.assertEqual(rc, 0, lines)
        self.assertFalse([line for line in lines if "possible_secret" in line], lines)

    def test_va3_assignments_with_values_still_fire(self):
        value = "Zq" + secrets.token_hex(6) + "7"
        long_word = "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(24))
        for label, sep, operand in (("password", ": ", value), ("PASSWORD", "=", "'" + value + "'"),
                                    ("api_key", " = ", value), ("client_secret", ": ", value),
                                    ("api-key", ": ", "`" + value + "`"), ("secret", "=", long_word)):
            line = label + sep + operand
            with self.subTest(line=label + sep):
                result = va.scan_placeholders_and_secrets("# Notes\n" + line + "\n")
                self.assertEqual(result["errors"], ["possible_secret:2=***MASKED***"])
                self.assertNotIn(value, json.dumps(result))

    def test_va3_the_value_patterns_stay_linear(self):
        label = "pass" + "word:"  # assembled so this file holds no credential-shaped literal
        lines = [label + " " * 200000 + "x",
                 ((label + "abcdefghijklmno,") * 8000),
                 "secret:" + "a" * 200000,
                 "api_key=" + "b" * 15 + ";" + "api_key=" * 30000,
                 ("PASSWORD= " + "q" * 5 + " ") * 20000]
        for line in lines:
            start = time.perf_counter()
            va.scan_placeholders_and_secrets(line)
            self.assertLess(time.perf_counter() - start, 2.0, line[:40])


def _letters(n, alphabet="abcdefghijklmnopqrstuvwxyz"):
    return "".join(secrets.choice(alphabet) for _ in range(n))


def _fires(line):
    """True when the validator's secret scan flags `line`; the value is never printed."""
    result = va.scan_placeholders_and_secrets("# Notes\n" + line + "\n")
    return result["errors"] == ["possible_secret:2=***MASKED***"]


class TestR2VA1SecretValueShape(ValidatorCase):
    """R2-VA-1: the VA-3 prose exemption covers only an unquoted single dictionary-style word after `:`.
    A quoted value of 6+ characters and any value after `=` are secrets again."""

    def test_r2_va1_quoted_values_and_assignments_fire(self):
        quoted = _letters(5) + " " + _letters(5) + "!"
        letters = _letters(8)
        for label, operand in (("pass" + "word: ", '"' + quoted + '"'), ("pass" + "word: ", "'" + quoted + "'"),
                               ("secret: ", '"' + _letters(7) + '"'),
                               ("pass" + "word=", letters), ("api_key = ", letters), ("SECRET=", _letters(6)),
                               ("pass" + "word=", '"' + letters + '"'), ("pass" + "word=", "x"),
                               ("pass" + "word: ", _letters(40)), ("api_key: ", _letters(4) + "1" + _letters(3))):
            with self.subTest(label=label, shape=len(operand)):
                self.assertTrue(_fires(label + operand))

    def test_r2_va1_prose_labels_still_pass(self):
        pw = "Pass" + "word"  # assembled so this file holds no credential-shaped literal
        for line in (pw + ": must be non-empty.", "Client secret: never written to logs.",
                     "API_KEY: required in a header.", "Secret: per-tenant, rotated monthly.",
                     pw + ": case-insensitive comparison is not allowed.", "api_key: `X-Api-Key` header",
                     pw + ": 8+ characters", pw + ': "must" be set', pw + ": required, min twelve",
                     'The body is {"' + pw.lower() + '": ""}', pw.lower() + " = ''", pw + ":"):
            with self.subTest(line=line):
                self.assertFalse(_fires(line))
        path = write(self.dir / "spec.md", SPEC.replace(
            "Passwords must be non-empty; an empty password is rejected with a 400 status code always.",
            "Password: must be non-empty. Client secret: never written to logs. API_KEY: required in a header."))
        rc, lines = self.cli("--mode", "spec", "--file", path, "--strict")
        self.assertEqual(rc, 0, lines)

    def test_r2_va1_value_patterns_stay_linear(self):
        label = "pass" + "word"
        lines = [label + ":" + " " * 200000 + '"',
                 (label + ": " + "ab-" * 30) * 3000,
                 (label + ": " + "a" * 30 + " ") * 6000,
                 label + ': "' + "a" * 200000,
                 label + "=" + " " * 200000,
                 (label + ":" + "word." * 5 + " ") * 8000,
                 "secret: " + "a-" * 100000 + "1"]
        for line in lines:
            start = time.perf_counter()
            va.scan_placeholders_and_secrets(line)
            self.assertLess(time.perf_counter() - start, 2.0, line[:40])


class TestR3VA1ProseWordShape(ValidatorCase):
    """R3-VA-1: the prose-word exemption covers a lowercase or Capitalized word of at most three
    hyphen-joined parts; a longer passphrase, a mixed-case or all-caps value and a YAML block opener are
    secrets."""

    def test_r3_va1_passphrases_mixed_case_and_yaml_blocks_fire(self):
        pw = "pass" + "word"
        upper = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        operands = (
            "-".join(_letters(5) for _ in range(4)),                 # a four-part hyphen passphrase
            "-".join(_letters(4).capitalize() for _ in range(5)),     # Capitalized parts, five of them
            _letters(4) + secrets.choice(upper) + _letters(4),        # mixed case inside one word
            _letters(10, upper),                                      # all caps
            secrets.choice(upper) + _letters(3) + secrets.choice(upper) + _letters(4),
        )
        for label in (pw + ": ", "Secret: ", "api_key: "):
            for operand in operands:
                with self.subTest(label=label, shape=len(operand)):
                    self.assertTrue(_fires(label + operand))
        for line in (pw + ": |", pw + ":  >", "secret: |-", "api_key: >+ ", pw.capitalize() + ": |2"):
            with self.subTest(line=line):
                self.assertTrue(_fires(line))

    def test_r3_va1_listed_prose_labels_still_pass(self):
        pw = "Pass" + "word"  # assembled so this file holds no credential-shaped literal
        for line in (pw + ": must be non-empty.", "Secret: per-tenant, rotated monthly.",
                     "api_key: `X-Api-Key` header", pw + ": case-insensitive comparison is not allowed.",
                     "Client secret: never written to logs.", "API_KEY: required in a header.",
                     pw + ": Required, see the policy.", pw + ": | is not a value here",
                     pw + ": > 8 characters"):
            with self.subTest(line=line):
                self.assertFalse(_fires(line))

    def test_r3_va1_word_test_stays_linear(self):
        label = "pass" + "word: "
        lines = [label + "Ab-" * 100000,
                 (label + "abc-def-ghi-jkl ") * 12000,
                 label + "|" + " " * 200000 + "x",
                 (label + "> ") * 30000,
                 label + "A" * 200000]
        for line in lines:
            start = time.perf_counter()
            va.scan_placeholders_and_secrets(line)
            self.assertLess(time.perf_counter() - start, 2.0, line[:40])


def _alnum(n, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"):
    """n random characters that always hold a digit and a letter, so no degenerate run."""
    return secrets.choice("0123456789") + secrets.choice("abcdefghij") + "".join(
        secrets.choice(alphabet) for _ in range(n - 2))


class TestR2VA2ProviderTokens(ValidatorCase):
    """R2-VA-2: the validator recognizes the provider formats hooks/secret-patterns.mjs added in SW-1/SW-2."""

    def tokens(self):
        upper = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        b64url = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
        return {
            "aws-temporary": "AS" + "IA" + _alnum(16, upper).upper(),
            "anthropic": "sk-" + "ant-api03-" + _alnum(40, b64url),
            "anthropic-admin": "sk-" + "ant-admin01-" + _alnum(40, b64url),
            "openai-project": "sk-" + "proj-" + "ab_cd-" + _alnum(30, b64url),
            "openai-service": "sk-" + "svcacct-" + "x_" + _alnum(30, b64url),
            "openai-admin": "sk-" + "admin-" + "-_" + _alnum(30, b64url),
            "gitlab": "gl" + "pat-" + _alnum(20),
            "npm": "np" + "m_" + _alnum(36),
            "huggingface": "h" + "f_" + _letters(34, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"),
            "pgp-armored": "-----BEGIN PGP PRIV" + "ATE KEY BLOCK-----",
        }

    def test_r2_va2_new_provider_formats_are_secrets(self):
        for name, token in self.tokens().items():
            with self.subTest(form=name):
                self.assertTrue(_fires("Use " + token + " here"))
                self.assertTrue(_fires("TOKEN_VALUE=" + token if name != "pgp-armored" else token))

    def test_r2_va2_cli_masks_them(self):
        tokens = self.tokens()
        path = write(self.dir / "spec.md", SPEC.replace("which is wrong.", "which is wrong. " + tokens["npm"]))
        rc, lines = self.cli("--mode", "spec", "--file", path)
        self.assertEqual(rc, 1, lines)
        self.assertIn("error=possible_secret:7=***MASKED***", lines)
        self.assertNotIn(tokens["npm"], "\n".join(lines))

    def test_r2_va2_lookalikes_are_not_tokens(self):
        for line in ("hf_" + "a1" * 20, "the npm_" + "a" * 10 + " helper", "sk-ant-" + "notakey",
                     "-----BEGIN PGP PUBLIC KEY BLOCK-----"):
            with self.subTest(line=line[:20]):
                self.assertFalse(_fires(line))

    def test_r2_va2_provider_patterns_stay_linear(self):
        lines = ["sk-" + "ant-api03-" + "a" * 20 + " " + ("sk-" + "ant-") * 40000,
                 ("sk-" + "proj-" + "a" * 10 + " ") * 20000,
                 ("gl" + "pat-" + "a" * 10 + " ") * 20000,
                 ("h" + "f_" + "a" * 33 + "1") * 5000,
                 "-----BEGIN" + "A" * 200000,
                 ("-----BEGIN " + "A" * 30) * 5000]
        for line in lines:
            start = time.perf_counter()
            va.scan_placeholders_and_secrets(line)
            self.assertLess(time.perf_counter() - start, 2.0, line[:30])


class TestVA4DistinctCriteria(ValidatorCase):
    def test_va4_sub_ids_are_separate_obligations(self):
        spec = _spec_criteria("- AC1.1: given an empty password, when POST /login, then returns 400\n"
                              "- AC1.2: given a valid password, when POST /login, then returns 200\n")
        plan = PLAN_HEAD + "## Task 1: reject empty (AC1.1)\n" + TASK
        result = va.check_plan(plan, spec)
        self.assertIn("ac_not_covered:AC1.2", result["warnings"], result)
        self.assertEqual(result["metrics"]["plan_ac_covered"], 1)
        both = PLAN_HEAD + "## Task 1: reject empty (AC1.1, AC1.2)\n" + TASK
        self.assertEqual(va.check_plan(both, spec)["metrics"]["plan_ac_covered"], 2)

    def test_va4_a_duplicate_criterion_id_is_an_error(self):
        spec = _spec_criteria("- AC1: given an empty password, when POST /login, then returns 400\n"
                              "- AC-1: given a valid password, when POST /login, then returns 200\n")
        self.assertIn("ac_duplicate_id:AC-1", va.check_spec(spec)["errors"])
        path = write(self.dir / "spec.md", spec)
        rc, lines = self.cli("--mode", "spec", "--file", path)
        self.assertEqual(rc, 1, lines)
        self.assertIn("error=ac_duplicate_id:AC-1", lines)
        bold = _spec_criteria("- **AC2:** given an empty password, when POST /login, then returns 400\n"
                              "- `AC2` given a valid password, when POST /login, then returns 200\n")
        self.assertEqual(va.check_spec(bold)["errors"], ["ac_duplicate_id:AC2"])
        # A bullet that only refers to criteria labelled elsewhere is no second criterion.
        note = SPEC.replace("and a token\n", "and a token\n- Note: AC1 and AC2 share one fixture, so when it runs both pass\n")
        self.assertEqual(va.check_spec(note)["errors"], [])

    def test_va4_plain_ids_are_unchanged(self):
        self.assertEqual(va.check_spec(SPEC)["errors"], [])
        plan = PLAN_HEAD + "## Task 1: both. Covers AC1. Then AC-2.\n" + TASK
        self.assertEqual(va.check_plan(plan, SPEC)["metrics"]["plan_ac_covered"], 2)
        # A dotted run that is no sub-id is no id at all, like a run of more than six digits.
        self.assertEqual([m.group(0) for m in va.AC_ID_RE.finditer("AC1.2.3 AC3.1234567 AC4. AC5.6")],
                         ["AC4", "AC5.6"])


class TestNewRegexesStayLinear(unittest.TestCase):
    """The flow hooks run the validator on every artifact write, so a changed pattern must stay linear."""

    def test_va4_va12_va13_patterns_on_long_lines(self):
        n = 200000
        cases = (
            (lambda line: list(va.AC_ID_RE.finditer(line)), "AC1." * (n // 4)),
            (lambda line: list(va.AC_ID_RE.finditer(line)), "AC1" + ".1" * (n // 2)),
            (lambda line: list(va.AC_ID_RE.finditer(line)), "AC-A1." + "1" * n),
            (va.TASK_HEADING_RE.match, "## Task" + " " * n + "x"),
            (va.TASK_HEADING_NUMBER_RE.match, "## Task" + " " * n + "#"),
            (va.TASK_HEADING_NUMBER_RE.match, "## Task #" + " " * n + "x"),
            (va.AC_LABEL_PREFIX_RE.match, "- " + " " * n + "*" * n),
            (rte.SKILL_FIELD_RE.search, '{"skill": "' + "\\\\" * n),
            (rte.SKILL_FIELD_RE.search, '"skill":' * (n // 8)),
        )
        for scan, line in cases:
            start = time.perf_counter()
            scan(line)
            self.assertLess(time.perf_counter() - start, 2.0, line[:30])

    def test_task_tid_start_is_linear_on_a_long_run_of_blanks(self):
        # Found while fixing VA-12: `[\s>*\-#]*\*{0,2}\s*` retries every split of a blank run,
        # so a long run of blanks without a T-id took quadratic time on the flow-hook path.
        line = " " * 60000 + "x"
        start = time.perf_counter()
        self.assertIsNone(va.TASK_TID_START_RE.match(line))
        self.assertLess(time.perf_counter() - start, 1.0)
        for text, tid in (("- **T3** do it", "T3"), ("> * T12: x", "T12"), ("## T4 title", "T4"), ("**T5**", "T5")):
            with self.subTest(text=text):
                self.assertEqual(va.TASK_TID_START_RE.match(text).group(1), tid)


class TestVA5NoCriteria(ValidatorCase):
    PROSE = _spec_criteria("The system must behave correctly for every login attempt that it receives.\n")

    def test_va5_no_criterion_id_fails_the_sources_gate(self):
        path = write(self.dir / "spec.md", self.PROSE)
        rc, lines = self.cli("--mode", "spec", "--file", path, "--sources")
        self.assertEqual(rc, 1, lines)
        self.assertIn("error=ac_none", lines)

    def test_va5_no_criterion_id_warns_without_sources(self):
        self.assertIn("ac_none", va.check_spec(self.PROSE)["warnings"])
        path = write(self.dir / "spec.md", self.PROSE)
        rc, lines = self.cli("--mode", "spec", "--file", path, "--strict")
        self.assertEqual(rc, 1, lines)
        self.assertIn("error=ac_none", lines)
        self.assertNotIn("ac_none", va.check_spec(SPEC)["warnings"] + va.check_spec(SPEC)["errors"])


class TestVA6SubHeadings(ValidatorCase):
    def test_va6_criteria_under_a_sub_heading_are_read(self):
        spec = _spec_criteria("### Login\n"
                              "- AC1: given an empty password, when POST /login, then returns 400\n"
                              "- given a whitespace password, when POST /login, then returns 400\n"
                              "### Logout\n"
                              "- AC2: given a session, when POST /logout, then returns 204\n")
        warnings = va.check_spec(spec)["warnings"]
        self.assertIn("ac_missing_id:2", warnings)
        self.assertNotIn("thin_section:acceptance-criteria", warnings)


class TestVA12Ordering(ValidatorCase):
    def test_va12_task_headings_out_of_order_warn(self):
        for name, plan in (
                ("descending", PLAN_HEAD + "## Task 2: b (AC2)\n" + TASK + "## Task 1: a (AC1)\n" + TASK),
                ("repeated", PLAN_HEAD + "## Task 1: a (AC1)\n" + TASK + "## Task 1: b (AC2)\n" + TASK),
                ("T-numbered", PLAN_HEAD + "## Task T2 - b (AC2)\n" + TASK + "## Task T1 - a (AC1)\n" + TASK)):
            with self.subTest(case=name):
                self.assertIn("tasks_unordered", va.check_plan(plan, SPEC)["warnings"])
        ordered = PLAN_HEAD + "## Task 1: a (AC1)\n" + TASK + "## Task 2: b (AC2)\n" + TASK
        self.assertNotIn("tasks_unordered", va.check_plan(ordered, SPEC)["warnings"])


class TestVA13TaskHeadings(ValidatorCase):
    def test_va13_a_task_list_heading_is_not_a_task(self):
        for heading in ("## Task list", "## Task overview", "## Task List"):
            plan = (PLAN_HEAD + heading + "\n### Task 1: reject empty (AC1)\n" + TASK
                    + "### Task 2: keep valid (AC2)\n" + TASK)
            with self.subTest(heading=heading):
                result = va.check_plan(plan, SPEC)
                self.assertEqual(result["metrics"], {"plan_tasks": 2, "plan_ac_covered": 2}, result)
                self.assertEqual(result["warnings"], [], result)
        for heading in ("## Task 1", "## Task T3 - x", "## Task N: <title>", "## Task: x", "## Task (AC1)",
                        "## Task"):
            with self.subTest(heading=heading):
                self.assertEqual(va.check_plan(PLAN_HEAD + heading + "\n" + TASK, None)["metrics"]["plan_tasks"], 1)


class TestVA16ModeAll(ValidatorCase):
    def test_va16_mode_all_checks_the_frontmatter(self):
        text = SPEC.replace("work_id: demo\nstatus: reviewed\n", "status: wip\n") + "## Task 1: a (AC1, AC2)\n" + TASK
        path = write(self.dir / "all.md", text)
        rc, lines = self.cli("--mode", "all", "--file", path, "--spec", write(self.dir / "spec.md", SPEC))
        self.assertEqual(rc, 1, lines)
        for key in ("work_id", "spec", "branch"):
            self.assertIn("error=missing_frontmatter_key:" + key, lines)
        self.assertIn("error=invalid_status:wip", lines)


class TestVA18DeepCheck(ValidatorCase):
    def test_va18_a_deep_check_file_is_invalid_json_not_a_traceback(self):
        spec = write(self.dir / "spec.md", _spec_criteria(
            "- AC1: given an empty password, when POST /login, then returns 400 (source: request)\n"))
        check = self.dir / "spec.check.json"
        check.write_text('{"questions": ' + "[" * 100000 + "]" * 100000 + "}", encoding="utf-8")
        rc, lines = self.cli("--mode", "spec", "--file", spec, "--sources", "--check", check)
        self.assertEqual(rc, 1, lines)
        self.assertIn("error=check_unreadable:invalid_json", lines)


# ---- resolver --------------------------------------------------------------------------------

class ResolverCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.agentic = self.repo / "docs" / "agentic-sdlc"

    def tearDown(self):
        self.tmp.cleanup()

    def resolve(self, *args):
        rc, out, err = run_script("resolve_work_package.py", "--repo", self.repo, *args)
        self.assertEqual(err, "", "a traceback instead of a resolution")
        return rc, out.splitlines()


class TestVA10StrayFiles(ResolverCase):
    def setUp(self):
        super().setUp()
        write(self.agentic / "specs" / "demo.md", SPEC)
        write(self.agentic / "plans" / "demo.md", PLAN_HEAD.replace("../spec/demo.md", "../specs/demo.md")
              + "## Task 1: a (AC1, AC2)\n" + TASK)
        (self.agentic / "plans" / "other.md").write_bytes(b"---\nwork_id: other\nbranch: x\xff\xfe\n---\n")
        (self.agentic / "plans" / "folder.md").mkdir()

    def test_va10_a_stray_file_does_not_crash_branch_resolution(self):
        rc, lines = self.resolve("--branch", "feat/demo")
        self.assertEqual(rc, 0, lines)
        self.assertIn("plan=docs/agentic-sdlc/plans/demo.md", lines)

    def test_va10_an_unreadable_plan_is_a_failed_resolution(self):
        for name in ("other.md", "folder.md"):
            with self.subTest(plan=name):
                rc, lines = self.resolve("--plan", "docs/agentic-sdlc/plans/" + name)
                self.assertEqual(rc, 1, lines)
                self.assertIn("error=plan_unreadable", lines)

    def test_va10_spec_resolution_skips_the_stray_files(self):
        rc, lines = self.resolve("--spec", "docs/agentic-sdlc/specs/demo.md")
        self.assertEqual(rc, 0, lines)


class TestVA11NestedPlans(ResolverCase):
    def test_va11_a_plan_below_the_package_layout_is_outside_every_root(self):
        write(self.agentic / "bar" / "spec" / "other.md", SPEC.replace("work_id: demo", "work_id: other"))
        nested = write(self.agentic / "foo" / "plan" / "sub" / "other.md", PLAN_HEAD.replace(
            "work_id: demo", "work_id: other").replace("../spec/demo.md", "../../../bar/spec/other.md"))
        rc, lines = self.resolve("--plan", nested.relative_to(self.repo).as_posix())
        self.assertEqual(rc, 1, lines)
        self.assertIn("error=plan_outside_root", lines)
        self.assertFalse(rwp.recognized_root(self.repo, nested, "plan"))
        flat_nested = self.agentic / "plans" / "sub" / "x.md"
        self.assertFalse(rwp.recognized_root(self.repo, flat_nested, "plan"))
        self.assertTrue(rwp.recognized_root(self.repo, self.agentic / "foo" / "plan" / "other.md", "plan"))
        self.assertTrue(rwp.recognized_root(self.repo, self.agentic / "plans" / "x.md", "plan"))


# ---- context probe ---------------------------------------------------------------------------

class TestVA14DetectContextShapes(unittest.TestCase):
    CASES = (
        ("package.json", "[]"),
        ("package.json", '{"scripts": null, "dependencies": null}'),
        ("package.json", '{"scripts": 5, "dependencies": ["left-pad"]}'),
        ("composer.json", '{"name": "acme/app", "require": [], "require-dev": []}'),
        ("composer.json", "[1, 2]"),
        ("package.json", '{"dependencies": ' + "[" * 100000 + "]" * 100000 + "}"),
    )

    def test_va14_unexpected_json_shapes_exit_zero(self):
        for name, text in self.CASES:
            for probe in ("deps", "toolchain"):
                with tempfile.TemporaryDirectory() as td, self.subTest(manifest=name, text=text[:40], probe=probe):
                    write(Path(td) / name, text)
                    rc, out, err = run_script("detect_context.py", "--path", td, "--probe", probe)
                    self.assertEqual((rc, err), (0, ""), out + err)
                    if probe == "deps":
                        self.assertIn("deps_probe=stdlib_only", out.splitlines())
                    else:
                        self.assertNotIn("node", out.split("toolchains=")[-1])

    def test_va14_real_declarations_still_count(self):
        self.assertTrue(dc._parse_package_json('{"dependencies": {"left-pad": "1"}}'))
        self.assertTrue(dc._parse_composer_json('{"require": {"php": "8", "acme/x": "1"}}'))
        self.assertFalse(dc._parse_composer_json('{"require": {"php": "8"}}'))
        with tempfile.TemporaryDirectory() as td:
            write(Path(td) / "package.json", '{"scripts": {"test": "jest"}}')
            self.assertTrue(dc._node_toolchain(Path(td)))


# ---- procedure eval --------------------------------------------------------------------------

def _jsonl(*events):
    return "".join(json.dumps(event) + "\n" for event in events)


INIT = {"type": "system", "subtype": "init", "cwd": "/work", "model": "m"}


def _tool(tool_id, name, tool_input):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tool_id, "name": name,
                                                          "input": tool_input}]}}


def _result(tool_id, is_error=False, content="ok"):
    block = {"type": "tool_result", "tool_use_id": tool_id, "content": content}
    if is_error:
        block["is_error"] = True
    return {"type": "user", "message": {"content": [block]}}


def _final(text):
    return {"type": "result", "subtype": "success", "result": text, "is_error": False}


SPEC_PATH = "docs/agentic-sdlc/specs/demo.md"


class ProcedureCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "fixture").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def grade(self, case, events, *extra):
        eval_set = write(self.dir / "eval.json", json.dumps({"cases": [case]}))
        transcript = write(self.dir / "t.jsonl", _jsonl(*events))
        rc, out, err = run_script("run_procedure_eval.py", "--eval-set", eval_set, "--transcript", transcript,
                                  "--fixture-root", self.dir / "fixture", *extra)
        self.assertEqual(err, "", out + err)
        return rc, out.splitlines()


class TestVA7RequiredArtifacts(ProcedureCase):
    CASE = {"id": "artifact", "prompt": "write the spec", "required_artifacts": [SPEC_PATH]}

    def test_va7_a_failed_read_is_not_the_artifact(self):
        rc, lines = self.grade(self.CASE, [INIT, _tool("t1", "Read", {"file_path": SPEC_PATH}),
                                           _result("t1", True, "File does not exist."), _final("Done.")])
        self.assertEqual(rc, 1, lines)
        self.assertIn("error=artifact:missing_artifact:" + SPEC_PATH, lines)

    def test_va7_a_failed_write_is_not_the_artifact(self):
        rc, lines = self.grade(self.CASE, [INIT, _tool("w1", "Write", {"file_path": "/work/" + SPEC_PATH,
                                                                         "content": "x"}),
                                           _result("w1", True, "denied"), _final("Done.")])
        self.assertEqual(rc, 1, lines)
        self.assertIn("error=artifact:missing_artifact:" + SPEC_PATH, lines)

    def test_va7_a_written_artifact_still_counts(self):
        rc, lines = self.grade(self.CASE, [INIT, _tool("w1", "Write", {"file_path": "/work/" + SPEC_PATH,
                                                                         "content": "x"}),
                                           _result("w1"), _final("Done.")])
        self.assertEqual(rc, 0, lines)
        self.assertIn("procedure_eval=passed", lines)


class TestVA15QuotedStatus(ProcedureCase):
    CASE = {"id": "gate", "prompt": "stop at spec review", "strict": {"stop_at_gate": "spec-review"}}

    def _events(self, new_status):
        return [INIT,
                _tool("w1", "Write", {"file_path": "/work/" + SPEC_PATH,
                                      "content": "---\nwork_id: demo\nstatus: reviewed\n---\n# Spec\n"}),
                _result("w1"),
                _tool("e1", "Edit", {"file_path": "/work/" + SPEC_PATH, "old_string": "status: reviewed",
                                     "new_string": "status: " + new_status}),
                _result("e1"),
                _final("Waiting at the Spec Review gate.")]

    def test_va15_a_quoted_approved_status_is_read(self):
        for status in ('"approved"', "'approved'", "approved"):
            with self.subTest(status=status):
                rc, lines = self.grade(self.CASE, self._events(status), "--strict-evidence")
                self.assertEqual(rc, 1, lines)
                self.assertIn("error=gate:strict_spec_status_without_approval", lines)
        self.assertEqual(rpe._fragment_statuses('status: "approved"\nstatus: \'draft\''), ["approved", "draft"])


# ---- trigger / routing / behavior / codex / glm graders --------------------------------------

def _skill_stream(tool_input):
    raw = json.dumps(tool_input)
    return [
        json.dumps({"type": "stream_event", "event": {"type": "content_block_start", "index": 0,
                                                      "content_block": {"type": "tool_use", "id": "t1",
                                                                        "name": "Skill"}}}),
        json.dumps({"type": "stream_event", "event": {"type": "content_block_delta", "index": 0,
                                                      "delta": {"type": "input_json_delta",
                                                                "partial_json": raw[:len(raw) // 2]}}}),
        json.dumps({"type": "stream_event", "event": {"type": "content_block_delta", "index": 0,
                                                      "delta": {"type": "input_json_delta",
                                                                "partial_json": raw[len(raw) // 2:]}}}),
        json.dumps({"type": "stream_event", "event": {"type": "content_block_stop", "index": 0}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Skill",
                                                                   "input": tool_input}]}}),
    ]


class TestVA8SkillArgs(unittest.TestCase):
    TARGET = "feature-build"
    CLEAN = "feature-build-live-abcd1234"

    def _decide(self, lines):
        detector = rte.TriggerDetector(self.CLEAN, self.TARGET)
        streamed = next((d for d in (detector.feed(line) for line in lines) if d is not None), None)
        return streamed, rte.detect_trigger(lines, self.CLEAN, self.TARGET)

    def test_va8_another_skill_naming_the_target_in_its_args_is_no_trigger(self):
        lines = _skill_stream({"skill": "agentic-sdlc:using-agentic-sdlc", "args": "route; probably feature-build"})
        self.assertEqual(self._decide(lines), (False, False))
        args_first = _skill_stream({"args": "feature-build please", "skill": "agentic-sdlc:test-authoring"})
        self.assertEqual(self._decide(args_first), (False, False))

    def test_va8_the_target_skill_still_triggers(self):
        lines = _skill_stream({"skill": "agentic-sdlc:feature-build", "args": "add the endpoint"})
        self.assertEqual(self._decide(lines), (True, True))


class TestVA18RoutingFirstRoute(unittest.TestCase):
    @staticmethod
    def _call(tool_id, skill):
        return json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": tool_id, "name": "Skill", "input": {"skill": skill}}]}})

    def test_va18_the_expected_skill_must_be_the_first_route(self):
        routes = rre.collect_claude_routes([self._call("a", "agentic-sdlc:using-agentic-sdlc"),
                                            self._call("b", "agentic-sdlc:feature-build"),
                                            self._call("c", "agentic-sdlc:test-authoring")])
        self.assertEqual(routes, ["feature-build", "test-authoring"])
        ok, reason = rre.evaluate_route("test-authoring", routes, False)
        self.assertFalse(ok)
        self.assertEqual(reason, "expected_not_first")
        self.assertEqual(rre.evaluate_route("feature-build", routes, False), (True, None))
        self.assertEqual(rre.evaluate_route("mind-spark", routes, False), (False, "no_expected"))


def _stub_dir(name, body):
    """A directory holding an executable `name` shell stub; the caller puts it first on PATH."""
    root = Path(tempfile.mkdtemp(prefix="va-stub-"))
    stub = root / name
    stub.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return root


def _env_with(stub_root):
    env = dict(os.environ)
    env["PATH"] = str(stub_root) + os.pathsep + env.get("PATH", "")
    return env


@unittest.skipIf(os.name == "nt", "shell stubs need a POSIX shell")
class StubCliCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.stubs = []

    def tearDown(self):
        self.tmp.cleanup()
        for root in self.stubs:
            for child in root.iterdir():
                child.unlink()
            root.rmdir()

    def stub(self, name, body):
        root = _stub_dir(name, body)
        self.stubs.append(root)
        return _env_with(root)


class TestVA9BehaviorEval(StubCliCase):
    def run_eval(self, env, *extra):
        eval_set = write(self.dir / "eval.json", json.dumps({"cases": [
            {"id": "probe", "prompt": "p", "required_patterns": ["run"]}]}))
        return run_script("run_behavior_eval.py", "--eval-set", eval_set, *extra, env=env)

    def test_va9_a_failed_cli_run_is_unmeasured(self):
        env = self.stub("claude", "echo '{\"type\":\"result\",\"subtype\":\"success\",\"is_error\":true,"
                                  "\"result\":\"Invalid API key \\u00b7 Please run /login\"}'\nexit 1\n")
        rc, out, err = self.run_eval(env)
        self.assertEqual((rc, err), (3, ""), out + err)
        self.assertIn("behavior_eval=unmeasured", out.splitlines())
        self.assertNotIn("behavior_eval=passed", out)

    def test_va9_an_error_result_with_exit_zero_is_unmeasured(self):
        env = self.stub("claude", "echo '{\"type\":\"result\",\"is_error\":true,\"result\":\"please run login\"}'\n")
        rc, out, err = self.run_eval(env)
        self.assertEqual((rc, err), (3, ""), out + err)
        self.assertIn("behavior_eval=unmeasured", out.splitlines())

    def test_va9_a_timeout_is_unmeasured(self):
        env = self.stub("claude", "exec sleep 30\n")
        rc, out, err = self.run_eval(env, "--timeout", "1")
        self.assertEqual((rc, err), (3, ""), out + err)
        self.assertIn("behavior_eval=unmeasured", out.splitlines())

    def test_va9_a_measured_run_still_passes(self):
        env = self.stub("claude", "echo '{\"type\":\"result\",\"is_error\":false,\"result\":\"I will run it\"}'\n")
        rc, out, err = self.run_eval(env)
        self.assertEqual((rc, err), (0, ""), out + err)
        self.assertIn("behavior_eval=passed", out.splitlines())


NEGATIVE_QUERIES = json.dumps({"queries": [{"query": "Rename a local variable in utils.py", "should_trigger": False}]})


class TestVA17ClassifierRunners(StubCliCase):
    def run_codex(self, env):
        eval_set = write(self.dir / "neg.json", NEGATIVE_QUERIES)
        return run_script("run_codex_trigger_eval.py", "--skill-path", REPO / "skills" / "spec-authoring",
                          "--eval-set", eval_set, "--runs", "1", "--timeout", "20", env=env)

    def run_glm(self, env):
        eval_set = write(self.dir / "neg.json", NEGATIVE_QUERIES)
        return run_script("run_glm_trigger_eval.py", "--skill-path", REPO / "skills" / "spec-authoring",
                          "--eval-set", eval_set, "--runs", "1", "--timeout", "20", env=env)

    def test_va17_a_failed_codex_run_is_unmeasured(self):
        env = self.stub("codex", "cat >/dev/null\necho '{\"type\":\"error\",\"message\":\"401 Unauthorized\"}'\n"
                                 "echo '{\"type\":\"turn.failed\",\"error\":{\"message\":\"401 Unauthorized\"}}'\nexit 1\n")
        rc, out, err = self.run_codex(env)
        self.assertEqual((rc, err), (3, ""), out + err)
        self.assertIn("codex_trigger_eval=unmeasured", out.splitlines())

    def test_va17_a_codex_answer_is_still_measured(self):
        answer = json.dumps({"type": "item.completed", "item": {
            "type": "agent_message", "text": '{"skill":"safe-refactor","needs_dev_flow":false}'}})
        env = self.stub("codex", "cat >/dev/null\necho '%s'\n" % answer)
        rc, out, err = self.run_codex(env)
        self.assertEqual((rc, err), (0, ""), out + err)
        self.assertIn("codex_trigger_eval=passed", out.splitlines())

    def test_va17_a_failed_glm_run_is_unmeasured(self):
        env = self.stub("opencode", "echo '{\"type\":\"error\",\"error\":\"unauthorized\"}'\nexit 1\n")
        rc, out, err = self.run_glm(env)
        self.assertEqual((rc, err), (3, ""), out + err)
        self.assertIn("glm_trigger_eval=unmeasured", out.splitlines())

    def test_va17_a_glm_answer_is_still_measured(self):
        answer = json.dumps({"type": "text", "part": {"type": "text",
                                                      "text": '{"skill":"safe-refactor","needs_dev_flow":false}'}})
        env = self.stub("opencode", "echo '%s'\n" % answer)
        rc, out, err = self.run_glm(env)
        self.assertEqual((rc, err), (0, ""), out + err)
        self.assertIn("glm_trigger_eval=passed", out.splitlines())


if __name__ == "__main__":
    unittest.main()
