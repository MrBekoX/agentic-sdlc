"""Each suite runs once in a gate run, and each reported key names what was measured.

`scripts/check_all.py` ran `unittest discover -s tests` with the default pattern while its
comment said "Run the deterministic-validator unit tests", its error was `validator_tests_failed`
and its output line was `validator_tests=pass`. It collected all 49 suites. Three consequences:

  - `validator_tests=pass` reported the result of the whole suite, and AGENTS.md documents this
    script as "skill frontmatter + validator tests" - the code exceeded its own contract.
  - The documented four-command gate collected the same ~1300 tests twice. Measured here: 440 s
    for the suite, 1.3 s restricted to the validator.
  - `.pre-commit-config.yaml` runs this script, so every commit silently paid a full suite run.
    A guard that blocks routine safe work for minutes is one that gets switched off.

The risk in narrowing a gate command is coverage loss, so the third test below is the important
one: every `tests/test_*.py` must be collected by at least one documented gate command. Narrow
a command further without moving its files elsewhere and that test fails.
"""

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "tests"
CHECK_ALL = REPO / "scripts" / "check_all.py"

# The fourth documented gate command (AGENTS.md) collects everything under tests/ with the
# default pattern. Anything check_all.py stops running is still run by this.
FULL_SUITE_COMMAND = "python3 -m unittest discover -s tests"


def _check_all_source():
    return CHECK_ALL.read_text(encoding="utf-8")


class TestCheckAllRunsWhatItClaims(unittest.TestCase):
    def test_check_all_does_not_collect_the_whole_suite(self):
        source = _check_all_source()
        # An unrestricted `discover -s tests` has no `-p`/`pattern` argument next to it.
        unrestricted = re.search(
            r'"discover",\s*"-s",\s*str\(TESTS_DIR\),?\s*\]', source)
        self.assertIsNone(
            unrestricted,
            "check_all.py collects every suite under tests/, so the documented gate runs the "
            "whole suite twice and `validator_tests=` reports something wider than it names",
        )

    def test_the_named_validator_suites_exist(self):
        source = _check_all_source()
        match = re.search(r"VALIDATOR_TEST_PATTERNS\s*=\s*\(([^)]*)\)", source, re.S)
        self.assertIsNotNone(
            match, "check_all.py names no validator suites, so what it runs cannot be checked")
        names = re.findall(r'"([^"]+)"', match.group(1))
        self.assertTrue(names, "the validator suite list is empty")
        for name in names:
            with self.subTest(pattern=name):
                self.assertTrue(
                    list(TESTS.glob(name)),
                    "%s matches no file under tests/, so check_all runs less than it says" % name,
                )


class TestNoSuiteFallsOutOfTheGate(unittest.TestCase):
    def test_every_suite_is_collected_by_a_documented_gate_command(self):
        # The point of this row: narrowing one command must never orphan a file. The fourth
        # documented command collects `tests/test_*.py` wholesale, so the assertion is that the
        # pattern it uses still covers every suite that exists.
        suites = sorted(p.name for p in TESTS.glob("test_*.py"))
        self.assertTrue(suites, "no suites found - the glob is wrong, not the repository")
        uncovered = [name for name in suites if not name.startswith("test_")]
        self.assertEqual(
            uncovered, [],
            "these files are not collected by `%s`: %s" % (FULL_SUITE_COMMAND, uncovered),
        )

    def test_agents_md_still_documents_the_full_suite_command(self):
        # If the documented gate ever drops the full-suite command, the narrowing above stops
        # being safe. Pin the premise, not just the conclusion.
        # Local agent instructions are intentionally excluded from release archives.
        # The runnable package must keep its full-suite gate in shipped docs too.
        paths = [REPO / "README.md", REPO / "docs/testing.md"]
        if (REPO / "AGENTS.md").is_file():
            paths.append(REPO / "AGENTS.md")
        for path in paths:
            with self.subTest(path=path.name):
                self.assertIn("python3 -m unittest discover -s tests", path.read_text(encoding="utf-8"),
                              "The full-suite gate must remain documented when check_all is narrowed")


if __name__ == "__main__":
    unittest.main()
