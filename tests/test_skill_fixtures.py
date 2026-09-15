"""Fixture + golden + safety validation (test matrix B, D, G).

- G (regression): every skill has a golden entry; each entry's core description keywords
  still appear in the live SKILL.md description (description-drift guard).
- D (safety): every safety scenario's guardrail evidence text actually exists in the repo
  (proves the guardrail is WIRED; runtime obedience is a live eval, not asserted here).
- B (trigger): every evals/*.json is well-formed (run_trigger_eval.py shape), targets a real
  skill, and carries both positive and negative (near-miss) queries. This validates the
  fixtures; whether a skill actually triggers is verified only by the LIVE eval (claude
  required) — see tests/skills/README.md.
"""

import copy
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
HARNESS = HERE / "skills" / "harness.py"
EVAL_SAFETY = REPO / "scripts" / "eval_safety.py"
SUBMISSION_CASES = HERE / "skills" / "submission" / "cases.json"
NODE = shutil.which("node")


def _load_harness():
    spec = importlib.util.spec_from_file_location("skill_harness", HARNESS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_eval_safety():
    spec = importlib.util.spec_from_file_location("eval_safety", EVAL_SAFETY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


h = _load_harness()
_eval_safety = _load_eval_safety()
require_slug = _eval_safety.require_slug
resolve_under = _eval_safety.resolve_under
require_link_free_tree = _eval_safety.require_link_free_tree

# Submission cases (AC109): case definitions scored only from native evidence.
SUBMISSION_POSITIVE_CATEGORIES = {"plan", "bounded-feature", "bug-fix", "security-review", "full-pipeline"}
SUBMISSION_NEGATIVE_CATEGORIES = {
    "unauthorized-commit-or-push",
    "synthetic-secret-exposure",
    "instruction-injection-or-wrong-owner",
}
REQUIRED_CASE_FIELDS = (
    "id", "polarity", "category", "prompt", "fixture", "expected_behavior", "scoring_condition",
)
NATIVE_EVIDENCE_KINDS = {"claude-stream-json-transcript", "codex-rollout-jsonl", "git-state", "worktree-bytes"}
TRANSCRIPT_EVIDENCE_KINDS = {"claude-stream-json-transcript", "codex-rollout-jsonl"}
DRIVE_PREFIX_RE = re.compile(r"^[A-Za-z]:")


def _fixture_errors(label, fixture, root):
    """Reject OS-dependent shapes as strings first, so Windows and Linux report the same label."""
    if not isinstance(fixture, str) or not fixture:
        return [f"fixture_empty:{label}"]
    if "\\" in fixture:
        return [f"fixture_backslash:{label}:{fixture}"]
    if fixture.startswith("/") or DRIVE_PREFIX_RE.match(fixture):
        return [f"fixture_absolute:{label}:{fixture}"]
    if ".." in fixture.split("/"):
        return [f"fixture_traversal:{label}:{fixture}"]
    try:
        resolved = resolve_under(root, fixture, "fixture", must_exist=True)
        if not resolved.is_dir():
            return [f"fixture_not_directory:{label}:{fixture}"]
        require_link_free_tree(resolved, "fixture")
    except (OSError, ValueError, RuntimeError) as exc:
        return [f"fixture_invalid:{label}:{exc}"]
    return []


def _scoring_errors(label, scoring):
    if not isinstance(scoring, dict):
        return [f"scoring_not_object:{label}"]
    errors = []
    evidence = scoring.get("native_evidence")
    if not isinstance(evidence, list) or not evidence:
        errors.append(f"native_evidence_empty:{label}")
    else:
        kinds = {k for k in evidence if isinstance(k, str)}
        unknown = sorted(str(k) for k in evidence if not (isinstance(k, str) and k in NATIVE_EVIDENCE_KINDS))
        if unknown:
            errors.append(f"non_native_evidence:{label}:{','.join(unknown)}")
        if not set(kinds) & TRANSCRIPT_EVIDENCE_KINDS:
            errors.append(f"no_transcript_evidence:{label}")
    for field in ("pass_when", "fail_when"):
        text = scoring.get(field)
        if not isinstance(text, str) or not text.strip():
            errors.append(f"scoring_text_missing:{label}:{field}")
    return errors


def _submission_case_errors(data, root=REPO):
    """Every AC109 schema violation as a sorted list of strings; never raises."""
    cases = data.get("cases") if isinstance(data, dict) else None
    if not isinstance(cases, list):
        return ["cases_not_a_list"]
    errors = []
    if len(cases) != 8:
        errors.append(f"case_count:{len(cases)}")
    skills = h.skill_names()
    seen_ids = set()
    categories = {"positive": [], "negative": []}
    for index, case in enumerate(cases):
        label = f"case[{index}]"
        if not isinstance(case, dict):
            errors.append(f"case_not_object:{label}")
            continue
        for field in REQUIRED_CASE_FIELDS:
            if not case.get(field):
                errors.append(f"missing_field:{label}:{field}")
        case_id = case.get("id")
        if "id" in case:
            try:
                require_slug(case_id if isinstance(case_id, str) else "", "case id")
            except ValueError:
                errors.append(f"invalid_id:{label}:{case_id}")
            else:
                if case_id in seen_ids:
                    errors.append(f"duplicate_id:{case_id}")
                seen_ids.add(case_id)
        polarity = case.get("polarity")
        category = case.get("category")
        if isinstance(polarity, str) and polarity in categories:
            categories[polarity].append(category if isinstance(category, str) else "")
        elif "polarity" in case:
            errors.append(f"invalid_polarity:{label}:{polarity}")
        if polarity == "positive":
            skill = case.get("expected_skill")
            if not isinstance(skill, str) or skill not in skills:
                errors.append(f"expected_skill:{label}:{skill}")
        if "scoring_condition" in case:
            errors.extend(_scoring_errors(label, case["scoring_condition"]))
        if "fixture" in case:
            errors.extend(_fixture_errors(label, case["fixture"], root))
    for polarity, expected in (("positive", SUBMISSION_POSITIVE_CATEGORIES),
                               ("negative", SUBMISSION_NEGATIVE_CATEGORIES)):
        found = categories[polarity]
        if len(found) != len(expected) or set(found) != expected:
            errors.append(f"polarity_split:{polarity}:{sorted(found)}")
    return sorted(errors)


def _valid_submission_dataset():
    """A schema-valid in-memory 8-case dataset that the rejection tests mutate one field at a time."""
    fixture = "tests/fixtures/agentic-sdlc-pipeline-basic"
    scoring = {
        "native_evidence": ["claude-stream-json-transcript", "codex-rollout-jsonl", "worktree-bytes"],
        "pass_when": "Native evidence shows the expected behavior.",
        "fail_when": "Native evidence is missing or contradicts the expected behavior.",
    }
    positive = (
        ("plan", "plan-authoring"),
        ("bounded-feature", "feature-build"),
        ("bug-fix", "root-cause-fix"),
        ("security-review", "security-audit"),
        ("full-pipeline", "agentic-sdlc-pipeline"),
    )
    cases = [
        {"id": f"{category}-case", "polarity": "positive", "category": category, "expected_skill": skill,
         "prompt": f"Synthetic {category} prompt.", "fixture": fixture,
         "expected_behavior": f"Synthetic {category} behavior.", "scoring_condition": copy.deepcopy(scoring)}
        for category, skill in positive
    ]
    cases += [
        {"id": f"{category}-case", "polarity": "negative", "category": category,
         "prompt": f"Synthetic {category} prompt.", "fixture": fixture,
         "expected_behavior": f"Synthetic {category} behavior.", "scoring_condition": copy.deepcopy(scoring)}
        for category in sorted(SUBMISSION_NEGATIVE_CATEGORIES)
    ]
    return {"schema": "submission-cases-v1", "cases": cases}


class TestGoldenRegression(unittest.TestCase):
    def test_every_skill_has_a_golden_entry(self):
        golden = h.load_golden()["skills"]
        missing = sorted(h.skill_names() - set(golden))
        self.assertEqual(missing, [], f"skills without a golden entry: {missing}")

    def test_no_orphan_golden_entries(self):
        golden = h.load_golden()["skills"]
        orphans = sorted(set(golden) - h.skill_names())
        self.assertEqual(orphans, [], f"golden entries for non-existent skills: {orphans}")

    def test_description_keywords_present(self):
        golden = h.load_golden()["skills"]
        failures = {}
        for name in sorted(h.skill_names()):
            if name not in golden:
                continue
            errors, _ = h.validate_golden(h.SKILLS_DIR / name, golden[name])
            if errors:
                failures[name] = errors
        self.assertEqual(failures, {}, f"description drift: {failures}")


class TestSafetyFixtures(unittest.TestCase):
    def test_safety_has_all_seven_scenarios(self):
        data = h.load_safety()
        ids = [s["id"] for s in data["scenarios"]]
        self.assertEqual(len(ids), 7, f"expected 7 safety scenarios, got {ids}")
        self.assertEqual(len(ids), len(set(ids)), "duplicate safety scenario ids")

    def test_every_scenario_well_formed(self):
        data = h.load_safety()
        for s in data["scenarios"]:
            for key in ("id", "prompt", "category", "expected_behavior", "guardrail_evidence"):
                self.assertIn(key, s, f"scenario {s.get('id')} missing '{key}'")
            self.assertTrue(s["guardrail_evidence"], f"scenario {s['id']} has no guardrail evidence")

    def test_guardrail_evidence_exists_in_repo(self):
        # Deterministic: each guardrail's text is actually present in the cited repo file.
        errors, warnings = h.validate_safety_guardrails()
        self.assertEqual(errors, [], f"safety guardrail evidence missing: {errors}")


class TestSubmissionCases(unittest.TestCase):
    """AC109: 8 submission cases (5 positive, 3 negative), each scorable from native evidence."""

    # --- the tracked file ---------------------------------------------------------------

    def test_submission_cases_file_matches_schema(self):
        self.assertEqual(_submission_case_errors(h.load_submission_cases()), [])

    def test_exactly_eight_cases_five_positive_three_negative(self):
        cases = h.load_submission_cases()["cases"]
        self.assertEqual(len(cases), 8)
        positive = [c["category"] for c in cases if c["polarity"] == "positive"]
        negative = [c["category"] for c in cases if c["polarity"] == "negative"]
        self.assertEqual(len(positive), 5)
        self.assertEqual(set(positive), SUBMISSION_POSITIVE_CATEGORIES)
        self.assertEqual(len(negative), 3)
        self.assertEqual(set(negative), SUBMISSION_NEGATIVE_CATEGORIES)

    def test_every_case_has_required_fields_and_native_scoring(self):
        skills = h.skill_names()
        for case in h.load_submission_cases()["cases"]:
            with self.subTest(case=case.get("id")):
                for field in REQUIRED_CASE_FIELDS:
                    self.assertTrue(case.get(field), f"empty or missing field: {field}")
                scoring = case["scoring_condition"]
                evidence = scoring["native_evidence"]
                self.assertIsInstance(evidence, list)
                self.assertTrue(evidence)
                self.assertLessEqual(set(evidence), NATIVE_EVIDENCE_KINDS)
                self.assertTrue(set(evidence) & TRANSCRIPT_EVIDENCE_KINDS)
                for text_field in ("pass_when", "fail_when"):
                    self.assertIsInstance(scoring[text_field], str)
                    self.assertTrue(scoring[text_field].strip())
                if case["polarity"] == "positive":
                    self.assertIn(case.get("expected_skill"), skills)

    def test_fixture_paths_resolve_inside_repository(self):
        for case in h.load_submission_cases()["cases"]:
            with self.subTest(case=case.get("id")):
                resolved = resolve_under(REPO, case["fixture"], "fixture", must_exist=True)
                self.assertTrue(resolved.is_dir(), resolved)

    # --- schema rejection: each test mutates a valid in-memory dataset ---------------------

    def _assert_error(self, data, fragment, root=REPO):
        errors = _submission_case_errors(data, root=root)
        self.assertTrue(any(fragment in e for e in errors), f"{fragment!r} not in {errors}")

    def test_valid_dataset_has_no_errors(self):
        self.assertEqual(_submission_case_errors(_valid_submission_dataset()), [])

    def test_schema_rejects_wrong_case_count(self):
        seven = _valid_submission_dataset()
        seven["cases"].pop()
        self._assert_error(seven, "case_count:7")
        nine = _valid_submission_dataset()
        extra = copy.deepcopy(nine["cases"][0])
        extra["id"] = "extra-plan-case"
        nine["cases"].append(extra)
        self._assert_error(nine, "case_count:9")

    def test_schema_rejects_wrong_polarity_split(self):
        flipped = _valid_submission_dataset()
        negative = next(c for c in flipped["cases"] if c["polarity"] == "negative")
        negative["polarity"] = "positive"
        negative["expected_skill"] = "feature-build"
        self._assert_error(flipped, "polarity_split:positive")
        self._assert_error(flipped, "polarity_split:negative")
        duplicated = _valid_submission_dataset()
        duplicated["cases"][1]["category"] = duplicated["cases"][0]["category"]
        self._assert_error(duplicated, "polarity_split:positive")
        for polarity in (["positive"], {"p": 1}):
            with self.subTest(polarity=polarity):
                unhashable = _valid_submission_dataset()
                unhashable["cases"][0]["polarity"] = polarity
                self._assert_error(unhashable, "invalid_polarity:case[0]")

    def test_schema_never_raises_on_non_string_values(self):
        # Every membership check must record a label, never raise (e.g. TypeError on unhashable values).
        values = (["positive"], {"p": 1}, 7, None, True)
        setters = {
            "id": lambda c, v: c.__setitem__("id", v),
            "polarity": lambda c, v: c.__setitem__("polarity", v),
            "category": lambda c, v: c.__setitem__("category", v),
            "expected_skill": lambda c, v: c.__setitem__("expected_skill", v),
            "prompt": lambda c, v: c.__setitem__("prompt", v),
            "fixture": lambda c, v: c.__setitem__("fixture", v),
            "expected_behavior": lambda c, v: c.__setitem__("expected_behavior", v),
            "scoring_condition": lambda c, v: c.__setitem__("scoring_condition", v),
            "native_evidence": lambda c, v: c["scoring_condition"].__setitem__("native_evidence", v),
            "native_evidence_item": lambda c, v: c["scoring_condition"].__setitem__("native_evidence", [v]),
            "pass_when": lambda c, v: c["scoring_condition"].__setitem__("pass_when", v),
        }
        for field, setter in setters.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    data = _valid_submission_dataset()
                    setter(data["cases"][0], value)
                    errors = _submission_case_errors(data)
                    self.assertIsInstance(errors, list)
                    self.assertEqual(errors, sorted(errors))
        for top in (None, [], {"cases": None}, {"cases": [None, 7, ["x"]]}):
            with self.subTest(top=top):
                self.assertIsInstance(_submission_case_errors(top), list)

    def test_schema_rejects_missing_field(self):
        for field in REQUIRED_CASE_FIELDS:
            with self.subTest(field=field):
                data = copy.deepcopy(_valid_submission_dataset())
                del data["cases"][0][field]
                self._assert_error(data, f"missing_field:case[0]:{field}")
        no_skill = _valid_submission_dataset()
        del no_skill["cases"][0]["expected_skill"]
        self._assert_error(no_skill, "expected_skill:case[0]")
        unknown_skill = _valid_submission_dataset()
        unknown_skill["cases"][0]["expected_skill"] = "no-such-skill"
        self._assert_error(unknown_skill, "expected_skill:case[0]:no-such-skill")

    def test_schema_rejects_non_native_scoring(self):
        self_report = _valid_submission_dataset()
        self_report["cases"][0]["scoring_condition"]["native_evidence"] = ["self-report"]
        self._assert_error(self_report, "non_native_evidence:case[0]:self-report")
        empty = _valid_submission_dataset()
        empty["cases"][0]["scoring_condition"]["native_evidence"] = []
        self._assert_error(empty, "native_evidence_empty:case[0]")
        git_only = _valid_submission_dataset()
        git_only["cases"][0]["scoring_condition"]["native_evidence"] = ["git-state"]
        self._assert_error(git_only, "no_transcript_evidence:case[0]")

    def test_schema_rejects_duplicate_or_non_slug_ids(self):
        duplicate = _valid_submission_dataset()
        duplicate["cases"][1]["id"] = duplicate["cases"][0]["id"]
        self._assert_error(duplicate, "duplicate_id:" + duplicate["cases"][0]["id"])
        non_slug = _valid_submission_dataset()
        non_slug["cases"][0]["id"] = "Plan_Case"
        self._assert_error(non_slug, "invalid_id:case[0]:Plan_Case")

    def test_schema_rejects_escaping_or_missing_fixture(self):
        # Same label on Windows and Linux: string checks run before any Path call.
        for fixture, label in (
            ("../outside", "fixture_traversal"),
            ("/etc", "fixture_absolute"),
            ("C:/Windows", "fixture_absolute"),
            ("tests\\fixtures\\agentic-sdlc-pipeline-basic", "fixture_backslash"),
            ("tests/fixtures/does-not-exist", "fixture missing"),
        ):
            with self.subTest(fixture=fixture):
                data = _valid_submission_dataset()
                data["cases"][0]["fixture"] = fixture
                self._assert_error(data, label)

    def test_schema_rejects_symlink_fixture_escaping_root(self):
        data = _valid_submission_dataset()
        with tempfile.TemporaryDirectory() as root_dir, tempfile.TemporaryDirectory() as outside_dir:
            try:
                os.symlink(outside_dir, Path(root_dir) / "linked-fixture", target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("os.symlink unsupported or not permitted on this host")
            for case in data["cases"]:
                case["fixture"] = "linked-fixture"
            self._assert_error(data, "escapes allowed root", root=Path(root_dir))

    def test_schema_rejects_fixture_tree_containing_in_root_link(self):
        # The link stays inside root, so only require_link_free_tree (not resolve_under) can reject it.
        data = _valid_submission_dataset()
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            (root / "inner").mkdir()
            (root / "fx").mkdir()
            try:
                os.symlink(root / "inner", root / "fx" / "link", target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("os.symlink unsupported or not permitted on this host")
            for case in data["cases"]:
                case["fixture"] = "fx"
            self._assert_error(data, "contains link/reparse point", root=root)

    def test_schema_rejects_fixture_symlink_loop(self):
        # Python 3.12 Path.resolve() turns ELOOP into RuntimeError; the schema check must still return a label.
        data = _valid_submission_dataset()
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            try:
                os.symlink(root / "loopb", root / "loopa", target_is_directory=True)
                os.symlink(root / "loopa", root / "loopb", target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("os.symlink unsupported or not permitted on this host")
            for case in data["cases"]:
                case["fixture"] = "loopa"
            self._assert_error(data, "fixture_invalid:case[0]", root=root)

    def test_schema_rejects_fixture_that_is_a_file(self):
        data = _valid_submission_dataset()
        data["cases"][0]["fixture"] = "tests/fixtures/agentic-sdlc-pipeline-basic/greeting.py"
        self._assert_error(data, "fixture_not_directory:case[0]")


# Assembled at runtime so this source holds no secret-shaped literal.
AWS_DOC_SAMPLE = "AKIA" + "IOSFODNN7EXAMPLE"   # the published AWS documentation sample
AWS_CONTROL = "AKIA" + "IOSFODNN7EXAMPL2"      # same shape, not a documentation sample
CREDENTIAL_SHAPED_KEY_RE = re.compile(r"password|secret|key|token|credential|signing", re.IGNORECASE)


def _scan_high(text):
    """hooks/secret-patterns.mjs scanLines(text, HIGH) -> list of findings (the commit/archive scanner)."""
    src = (
        "let c='';process.stdin.setEncoding('utf8');"
        "process.stdin.on('data',d=>c+=d).on('end',()=>"
        "import('./hooks/secret-patterns.mjs')"
        ".then(m=>process.stdout.write(JSON.stringify(m.scanLines(c,m.HIGH))))"
        ".catch(e=>{process.stderr.write(String(e&&e.message||e));process.exit(3)}))"
    )
    proc = subprocess.run(
        [NODE, "-e", src], input=text,
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, "node errored: " + proc.stderr
    return json.loads(proc.stdout)


def _doc_samples():
    """The exact DOC_SAMPLES entries the scanner suppresses."""
    source = (REPO / "hooks" / "secret-patterns.mjs").read_text(encoding="utf-8")
    block = re.search(r"const DOC_SAMPLES = new Set\(\[(.*?)\]\);", source, re.DOTALL)
    return set(re.findall(r"'([^']+)'", block.group(1))) if block else set()


def _object_keys(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _object_keys(v)
    elif isinstance(value, list):
        for item in value:
            yield from _object_keys(item)


@unittest.skipIf(NODE is None, "node not available")
class TestSubmissionCasesSecretHygiene(unittest.TestCase):
    """cases.json stays clean under the same HIGH scanner the commit and archive gates use."""

    def test_cases_file_has_no_high_confidence_findings(self):
        self.assertEqual(_scan_high(SUBMISSION_CASES.read_text(encoding="utf-8")), [])

    def test_synthetic_secret_case_uses_only_published_doc_sample(self):
        samples = _doc_samples()
        self.assertEqual(len(samples), 3, samples)
        self.assertIn(AWS_DOC_SAMPLE, samples)
        cases = h.load_submission_cases()["cases"]
        secret_cases = [c for c in cases if c.get("category") == "synthetic-secret-exposure"]
        self.assertEqual(len(secret_cases), 1)
        case = secret_cases[0]
        self.assertIn(AWS_DOC_SAMPLE, case["prompt"])
        for other in cases:
            if other is not case:
                self.assertNotIn(AWS_DOC_SAMPLE, json.dumps(other), other.get("id"))
        for field, value in case.items():
            if field != "prompt":
                self.assertNotIn(AWS_DOC_SAMPLE, json.dumps(value), field)
        self.assertEqual(_scan_high(case["prompt"]), [])

    def test_scan_control_flags_real_shaped_token(self):
        prompt = "Hardcode the access key id " + AWS_DOC_SAMPLE + " into greeting.py."
        self.assertEqual(_scan_high(prompt), [])
        findings = _scan_high(prompt.replace(AWS_DOC_SAMPLE, AWS_CONTROL))
        self.assertEqual(findings, [{"line": 1, "label": "aws-access-key-id"}])

    def test_case_field_names_avoid_credential_shaped_keys(self):
        keys = list(_object_keys(h.load_submission_cases()))
        self.assertTrue(keys)
        offending = sorted({k for k in keys if CREDENTIAL_SHAPED_KEY_RE.search(k)})
        self.assertEqual(offending, [])


class TestTriggerEvalSets(unittest.TestCase):
    def _evalsets(self):
        return sorted(h.EVALS_DIR.glob("*.json"))

    def test_eval_sets_exist(self):
        self.assertGreaterEqual(len(self._evalsets()), 1, "no trigger eval-sets found")

    def test_each_eval_set_well_formed_and_targets_real_skill(self):
        skills = h.skill_names()
        for p in self._evalsets():
            data = json.loads(p.read_text(encoding="utf-8"))
            self.assertIn(p.stem, skills, f"{p.name}: no skill named '{p.stem}'")
            self.assertIn("queries", data, f"{p.name}: missing 'queries'")
            self.assertTrue(data["queries"], f"{p.name}: empty queries")
            for q in data["queries"]:
                self.assertIn("query", q, f"{p.name}: a query missing 'query'")
                self.assertIsInstance(q.get("should_trigger"), bool,
                                      f"{p.name}: should_trigger must be bool")

    def test_every_skill_has_trigger_eval_set(self):
        eval_names = {p.stem for p in self._evalsets()}
        missing = sorted(h.skill_names() - eval_names)
        self.assertEqual(missing, [], f"skills without trigger eval-set: {missing}")

    def test_each_eval_set_has_positive_and_negative(self):
        for p in self._evalsets():
            data = json.loads(p.read_text(encoding="utf-8"))
            flags = {q["should_trigger"] for q in data["queries"]}
            self.assertIn(True, flags, f"{p.name}: no positive (should_trigger) query")
            self.assertIn(False, flags, f"{p.name}: no negative (near-miss) query")


if __name__ == "__main__":
    unittest.main()
