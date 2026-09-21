"""The Test suite map in docs/testing.md must list every suite.

`docs/testing.md` is what a contributor reads to learn what the gate proves, and its map
presents itself as the inventory: "The local unittest layer is organized into coverage matrices
so each concern has a dedicated suite." It had 21 rows for 49 files, so more than half the
suite - including the largest security suite - was invisible to anyone reading it.

Nothing had gone wrong at any single moment; rows simply were not added as files were. That is
what makes it a drift problem rather than an authoring problem, and drift belongs in a test.

What this pins and what it does not: it asserts a row EXISTS for every suite, and that no row
names a file that has been deleted. It cannot judge whether a row's description is TRUE - that
stays a review obligation. A drift gate, not a truth gate.
"""

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "tests"
DOC = REPO / "docs" / "testing.md"

MAP_HEADING = "## Test suite map"

# Suites deliberately absent from the map. Each entry needs a reason: an omission should be a
# decision someone made, not one nobody noticed.
UNMAPPED = {
    "tests/test_superpowers_referenced_eval_prompt.py":
        "gitignored along with the agentic-sdlc-prompts/ folder it reads, so it exists only on "
        "a maintainer's machine. A row in a shipped document would describe a file most readers "
        "cannot open.",
}

ROW = re.compile(r"^\|\s*`(tests/[A-Za-z0-9_./-]+\.py)`\s*\|")


def _map_section():
    text = DOC.read_text(encoding="utf-8")
    start = text.index(MAP_HEADING)
    rest = text[start + len(MAP_HEADING):]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def _mapped_files():
    return [m.group(1) for m in (ROW.match(line) for line in _map_section().splitlines()) if m]


def _suite_files():
    return sorted("tests/" + p.name for p in TESTS.glob("test_*.py"))


class TestSuiteMapIsComplete(unittest.TestCase):
    def test_every_suite_has_a_row(self):
        missing = sorted(set(_suite_files()) - set(_mapped_files()) - set(UNMAPPED))
        self.assertEqual(
            missing, [],
            "these suites have no row in the Test suite map in docs/testing.md, so the map "
            "claims an inventory it does not have (%d missing): %s"
            % (len(missing), ", ".join(missing)),
        )

    def test_no_row_names_a_file_that_is_gone(self):
        present = set(_suite_files())
        dangling = sorted(rel for rel in _mapped_files() if rel not in present)
        self.assertEqual(
            dangling, [],
            "the Test suite map names files that no longer exist: " + ", ".join(dangling),
        )

    def test_every_unmapped_entry_carries_a_reason(self):
        # The exclusion list is the only way out of the map, so it must not become a silent
        # dumping ground: an entry without a reason is the drift this test exists to stop.
        for rel, reason in sorted(UNMAPPED.items()):
            with self.subTest(file=rel):
                self.assertTrue(reason and reason.strip(),
                                "%s is excluded from the map with no reason" % rel)
                # No existence assertion. An excluded file may legitimately be ABSENT here -
                # the current entry is gitignored, so it is missing from every clean clone and
                # from CI. Requiring it to exist would make this test fail everywhere except a
                # maintainer's machine, which is the opposite of what it is for.
                self.assertNotIn(rel, _mapped_files(),
                                 "%s is both excluded and given a row; pick one" % rel)

    def test_the_map_is_not_empty(self):
        # A parser that silently matched nothing would make the two checks above pass by
        # vacuity: an empty mapped set is a subset of everything, and has no dangling rows.
        self.assertGreater(len(_mapped_files()), 20,
                           "the map parser found almost no rows - it is probably not matching "
                           "the table format any more")


if __name__ == "__main__":
    unittest.main()
