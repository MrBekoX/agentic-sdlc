"""The two tools that validate a work package must agree on what a valid one is.

`scripts/validate_artifacts.py` is what the skills run as the deterministic gate
(`skills/plan-authoring/SKILL.md:55`; `skills/agentic-sdlc-pipeline/SKILL.md:130` calls a
non-zero exit a blocked gate). `scripts/resolve_work_package.py` runs later, at implementation
time, and rejects an artifact outright when a required frontmatter key is missing.

They disagreed: the validator parsed no frontmatter at all, so it returned
`artifacts_validation=passed` on a plan the suite then rejected with `plan_missing:branch`.

The validator deliberately does NOT import the resolver - it is invoked standalone from the
skills on both runtimes, and importing the resolver would pull its git and filesystem behaviour
into a check that should read one file. So the constants are mirrored, and this test is what
stops them drifting apart again: a divergence is a failing test rather than a false green.

What this pins: the two sets are EQUAL. Not that either is correct - the resolver remains the
authority, and path semantics stay there on purpose.

Equal constants are not equal behaviour: the two tools parse frontmatter with separate code. So
the behavioural fixtures below run real plans through BOTH command lines and require the same
verdict - quoting, delimiters (whole `---` lines only: an indented one or a `----` line is not a
delimiter), comment and colon-less lines, and the spec-less bugfix pair (`flow: bugfix` with
`spec: none`, design §5.19), which both accept only together and never beside a package spec.
"""

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
VALIDATOR = SCRIPTS / "validate_artifacts.py"
RESOLVER = SCRIPTS / "resolve_work_package.py"

FEATURE_SPEC = """\
---
work_id: feat-x
status: approved
---

# Spec
## Acceptance criteria
- AC1: Given a refund, when the job runs, then the total is reduced once.
"""

FEATURE_FRONTMATTER = """\
---
work_id: feat-x
spec: ../spec/feat-x.md
branch: feat/x
status: approved
---
"""

FEATURE_BODY = """
# Plan

## Task 1 — Reduce the total once (AC1)
Modify `src/ledger.py`. TDD: write the failing test (RED) first.
Run: pytest tests/test_ledger.py
"""

BUGFIX_FRONTMATTER = """\
---
work_id: fix-x
spec: none
flow: bugfix
branch: fix/x
status: approved
---
"""

BUGFIX_BODY = """
# Bugfix plan

## Bug
Expected: a replayed refund reduces the total once. Actual: twice. Reproduction: replay it.

## Acceptance Criteria
- AC1: Given a replayed refund event, when the job runs, then the total is reduced once.

## Task 1 — Deduplicate refund events (AC1)
Modify `src/ledger.py`. TDD: write the failing replay test (RED) first.
Run: pytest tests/test_ledger.py
"""

SPECLESS_BODY = """
# Plan

## Acceptance Criteria
- AC1: Given a replayed refund event, when the job runs, then the total is reduced once. (source: request)

## Task 1 — Deduplicate refund events (AC1)
Modify `src/ledger.py`. TDD: write the failing replay test (RED) first.
Run: pytest tests/test_ledger.py
"""

SPEC_NONE_ERROR = "spec_none_requires_specless_flow"
SPEC_GIVEN_ERROR = "spec_none_with_spec"

FEATURE_CLOSER = "status: approved\n---\n"

# Keys after a `----` line: the resolver ended the block there, the validator read on (last value
# wins), so each tool judged a different plan. Both orders, the bugfix keys after or before it.
SMUGGLED_BUGFIX_KEYS = FEATURE_FRONTMATTER.replace(
    FEATURE_CLOSER, "status: approved\n----\nspec: none\nflow: bugfix\n---\n")
SMUGGLED_FEATURE_KEYS = """\
---
work_id: feat-x
branch: feat/x
status: approved
spec: none
flow: bugfix
----
spec: ../spec/feat-x.md
flow: feature
---
"""

# kind -> (package slug, plan body, write the package spec and pass it to the validator as --spec)
KINDS = {
    "feature": ("feat-x", FEATURE_BODY, True),
    "bugfix": ("fix-x", BUGFIX_BODY, False),
    # A spec-less plan outside bugfix: its own criteria, no `## Bug` section.
    "specless": ("fix-x", SPECLESS_BODY, False),
    # A bugfix body in a package that holds a spec, given to the validator as the hook does.
    "bugfix-beside-spec": ("feat-x", BUGFIX_BODY, True),
}

# (name, kind, plan frontmatter, both accept?, an error code both must print)
PARITY_FIXTURES = (
    ("plain feature plan", "feature", FEATURE_FRONTMATTER, True, None),
    ("quoted status", "feature",
     FEATURE_FRONTMATTER.replace("status: approved", 'status: "approved"'), True, None),
    ("quoted spec path", "feature",
     FEATURE_FRONTMATTER.replace("spec: ../spec/feat-x.md", "spec: '../spec/feat-x.md'"), True, None),
    ("trailing spaces on both delimiters", "feature", FEATURE_FRONTMATTER.replace("---\n", "--- \n"),
     True, None),
    ("comment line in the block", "feature",
     FEATURE_FRONTMATTER.replace("branch: feat/x\n", "branch: feat/x\n# owner: payments\n"), True, None),
    ("---- opener", "feature", "-" + FEATURE_FRONTMATTER, False, None),
    ("indented opener", "feature", "  " + FEATURE_FRONTMATTER, False, None),
    ("indented closer", "feature", FEATURE_FRONTMATTER.replace(FEATURE_CLOSER, "status: approved\n  ---\n"),
     False, None),
    ("---- closer", "feature", FEATURE_FRONTMATTER.replace(FEATURE_CLOSER, "status: approved\n----\n"),
     False, None),
    ("colon-less line", "feature", FEATURE_FRONTMATTER.replace("branch: feat/x\n", "branch: feat/x\nnotes\n"),
     False, None),
    ("---- line, bugfix keys after it", "bugfix-beside-spec", SMUGGLED_BUGFIX_KEYS, False, None),
    ("---- line, bugfix keys before it", "bugfix-beside-spec", SMUGGLED_FEATURE_KEYS, False, None),
    ("spec none + flow bugfix", "bugfix", BUGFIX_FRONTMATTER, True, None),
    ("quoted spec none + flow bugfix", "bugfix",
     BUGFIX_FRONTMATTER.replace("spec: none", 'spec: "none"').replace("flow: bugfix", "flow: 'bugfix'"),
     True, None),
    ("spec none + flow feature", "specless", BUGFIX_FRONTMATTER.replace("flow: bugfix", "flow: feature"),
     True, None),
    ("spec none + flow plan", "specless", BUGFIX_FRONTMATTER.replace("flow: bugfix", "flow: plan"),
     True, None),
    ("spec none + flow refactor, spec-less body", "specless",
     BUGFIX_FRONTMATTER.replace("flow: bugfix", "flow: refactor"), False, SPEC_NONE_ERROR),
    ("spec none beside a package spec, flow feature", "bugfix-beside-spec",
     BUGFIX_FRONTMATTER.replace("work_id: fix-x", "work_id: feat-x").replace("flow: bugfix", "flow: feature"),
     False, SPEC_GIVEN_ERROR),
    ("spec none, missing flow", "bugfix", BUGFIX_FRONTMATTER.replace("flow: bugfix\n", ""), False,
     SPEC_NONE_ERROR),
    ("spec none, another flow", "bugfix", BUGFIX_FRONTMATTER.replace("flow: bugfix", "flow: refactor"),
     False, SPEC_NONE_ERROR),
    # A plan cannot opt out of the spec its package holds by declaring `spec: none`.
    ("spec none beside a package spec", "bugfix-beside-spec",
     BUGFIX_FRONTMATTER.replace("work_id: fix-x", "work_id: feat-x"), False, SPEC_GIVEN_ERROR),
)


def _run(argv):
    proc = subprocess.run([sys.executable, *map(str, argv)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60)
    return proc.returncode, proc.stdout, proc.stderr


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def run_both(root, kind, frontmatter):
    """Write one package under `root` and run both command lines on its plan.

    Returns {"validator": (rc, stdout, stderr), "resolver": (rc, stdout, stderr)}. The validator
    runs `--strict`, the gate the pipeline applies; the resolver resolves the plan explicitly.
    """
    slug, body, with_spec = KINDS[kind]
    package = Path(root) / "docs" / "agentic-sdlc" / slug
    plan = _write(package / "plan" / (slug + ".md"), frontmatter + body)
    validator_argv = [VALIDATOR, "--mode", "plan", "--file", plan, "--strict"]
    if with_spec:
        validator_argv += ["--spec", _write(package / "spec" / (slug + ".md"), FEATURE_SPEC)]
    return {
        "validator": _run(validator_argv),
        "resolver": _run([RESOLVER, "--repo", root, "--plan", plan]),
    }


def _load(name):
    path = SCRIPTS / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestValidatorResolverParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = _load("validate_artifacts")
        cls.resolver = _load("resolve_work_package")

    def test_plan_required_keys_match(self):
        self.assertEqual(
            tuple(self.validator.FRONTMATTER_REQUIRED["plan"]),
            tuple(self.resolver.PLAN_REQUIRED),
            "the gate and the resolver disagree about a plan's required frontmatter, so the "
            "gate can pass an artifact the resolver will reject",
        )

    def test_spec_required_keys_match(self):
        self.assertEqual(
            tuple(self.validator.FRONTMATTER_REQUIRED["spec"]),
            tuple(self.resolver.SPEC_REQUIRED),
            "the gate and the resolver disagree about a spec's required frontmatter",
        )

    def test_allowed_statuses_match(self):
        self.assertEqual(
            set(self.validator.FRONTMATTER_STATUSES),
            set(self.resolver.STATUSES),
            "the gate and the resolver disagree about which statuses are valid",
        )

    def test_the_sets_are_not_empty(self):
        # An empty set on both sides would satisfy every assertion above by vacuity, and a
        # refactor that renamed a constant would produce exactly that if the loader returned a
        # stub. Cheap insurance against the failure mode this whole file exists to prevent.
        self.assertTrue(self.resolver.PLAN_REQUIRED)
        self.assertTrue(self.resolver.SPEC_REQUIRED)
        self.assertTrue(self.resolver.STATUSES)
        self.assertIn("branch", self.validator.FRONTMATTER_REQUIRED["plan"])

    def test_bugfix_pair_constants_match(self):
        for name in ("SPEC_NONE", "BUGFIX_FLOW", "SPECLESS_FLOWS"):
            with self.subTest(constant=name):
                self.assertEqual(getattr(self.validator, name), getattr(self.resolver, name))
        self.assertEqual((self.resolver.SPEC_NONE, self.resolver.BUGFIX_FLOW), ("none", "bugfix"))
        self.assertEqual(self.resolver.SPECLESS_FLOWS, ("bugfix", "feature", "plan"))


class TestBehaviouralParity(unittest.TestCase):
    """The same plan gets the same verdict from both command lines."""

    def test_spec_none_requires_a_specless_flow(self):
        for name, flow_line in (("missing flow", ""), ("another flow", "flow: refactor\n")):
            with self.subTest(case=name), tempfile.TemporaryDirectory() as tmp:
                frontmatter = BUGFIX_FRONTMATTER.replace("flow: bugfix\n", flow_line)
                results = run_both(tmp, "bugfix", frontmatter)
                for tool, (rc, out, err) in results.items():
                    self.assertEqual(rc, 1, f"{tool}: {out}{err}")
                    self.assertIn("error=" + SPEC_NONE_ERROR, out.splitlines(), f"{tool}: {out}{err}")
                    self.assertEqual(err, "", f"{tool} wrote to stderr")

    def test_parity_fixtures_both_clis(self):
        for name, kind, frontmatter, accepted, shared_error in PARITY_FIXTURES:
            with self.subTest(fixture=name), tempfile.TemporaryDirectory() as tmp:
                results = run_both(tmp, kind, frontmatter)
                v_rc, v_out, v_err = results["validator"]
                r_rc, r_out, r_err = results["resolver"]
                detail = f"\nvalidator:\n{v_out}{v_err}\nresolver:\n{r_out}{r_err}"
                self.assertEqual("artifacts_validation=passed" in v_out.splitlines(), accepted, detail)
                self.assertEqual("work_package_resolution=passed" in r_out.splitlines(), accepted, detail)
                self.assertEqual((v_rc, r_rc), (0, 0) if accepted else (1, 1), detail)
                self.assertEqual((v_err, r_err), ("", ""), detail)
                if shared_error:
                    self.assertIn("error=" + shared_error, v_out.splitlines(), detail)
                    self.assertIn("error=" + shared_error, r_out.splitlines(), detail)
                if accepted and kind == "bugfix":
                    self.assertIn("spec=none", r_out.splitlines(), detail)
                    self.assertIn("plan_ac_covered=1", v_out.splitlines(), detail)


if __name__ == "__main__":
    unittest.main()
