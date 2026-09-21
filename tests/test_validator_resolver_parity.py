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
"""

import importlib.util
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"


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


if __name__ == "__main__":
    unittest.main()
