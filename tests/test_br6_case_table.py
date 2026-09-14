"""Schema and coverage checks for the shared BR6 attribution case table (plan Task 0, D3).

The table is the only BR6 case source; slices B, C and GH read it read-only. These tests pin
its exact shape, its coverage of the spec's named command shapes and carrier variants, and the
column rules R1-R7 that tie every outcome column to the BR6 text, so a contradictory row fails
here before it can propagate into a consumer suite.
"""
import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TABLE = REPO / "tests" / "fixtures" / "transcripts" / "br6-attribution-cases.json"

TEST_COMMAND_SOURCE = "hooks/flow-requirements.json#testCommand"
TOP_LEVEL_KEYS = frozenset({"schema", "testCommandSource", "rows"})
REQUIRED_COLUMNS = frozenset({
    "id",
    "command",
    "specRefs",
    "carrier",
    "statements",
    "lastIsRealRunner",
    "lastVersionOrHelpOnly",
    "lastHasPipe",
    "runnerShape5801cb9",
    "defaultTests",
    "strictAttributable",
    "strictTests",
    "baseline5801cb9",
})
CARRIER_KEYS = frozenset({"callEvents", "outputRecords", "exitCode", "outputSummary"})
BASELINE_KEYS = frozenset({"claudeStopTests", "codexOrderGuard", "codexStopTests"})
ALLOWED_REFS = frozenset({
    "AC28", "AC29", "AC30", "AC31", "AC35", "AC41", "AC42", "AC44",
    "AC69", "AC118", "AC123", "AC130", "EDGE-EXIT",
})
BOOL_COLUMNS = (
    "lastIsRealRunner",
    "lastVersionOrHelpOnly",
    "lastHasPipe",
    "runnerShape5801cb9",
    "strictAttributable",
)
TESTS_OUTCOMES = frozenset({"satisfied", "missing"})
ORDER_OUTCOMES = frozenset({"satisfied", "not-satisfied"})
ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

SPEC_SHAPES = {
    "AC28": ("pytest; echo EXIT=$?",),
    "AC30": ("pytest; echo EXIT=$?",),
    "AC29": (
        "cd repo && pytest",
        "cd repo; pytest",
        "export X=1; pytest",
        'pytest -k "a;b"',
        "pytest; pytest",
        "pytest;",
        "pytest ; ",
        "pytest \\\n-q",
        "pytest\n# done",
    ),
    "AC31": ("pytest | tee log.txt", "pytest 2>&1 | tail -n 50"),
    "AC118": (
        "pytest; pytest --version",
        "pytest; pytest --help",
        "pytest; pytest -V",
        "pytest; python -m pytest --version",
        "pytest; npm test -- --help",
        "pytest\necho done",
        "pytest || true",
        "pytest && echo ok",
        "pytest && pytest --version",
    ),
    "AC41": ("pytest --version", "pytest"),
    "AC42": (
        "pytest --version",
        "cd repo && pytest --version",
        "pytest | tee log.txt",
        "pytest 2>&1 | tail -n 50",
        "pytest",
        "pytest; echo EXIT=$?",
    ),
    "AC44": ("pytest",),
    "AC69": ("python -m pytest -q", "python -m pytest -q; echo EXIT=$?", "pytest"),
    "AC123": ("pytest; echo EXIT=$?", "pytest"),
    "AC35": ("pytest",),
    "EDGE-EXIT": (
        "pytest; cd ..",
        "cd repo; pytest; echo x",
        "pytest; pytest --version",
        "pytest; pytest -h",
        "pytest; pytest -V",
        "pytest; python -m pytest --version",
        "pytest; npm test -- --help",
        "pytest; pytest --version -q",
        "pytest; pytest -k help",
        "pytest\necho done",
        "pytest || true",
        "pytest && pytest --version",
        "pytest --version && pytest",
        "cd repo && pytest --version",
        "pytest; echo EXIT=$?",
        "pytest 2>&1 | tail -n 50",
        "pytest --version",
        "echo pytest",
        'bash -c "pytest; true"',
        "pytest -k 'a;b'",
    ),
}

# (command, callEvents, outputRecords, exitCode)
CARRIER_VARIANTS = (
    ("pytest; echo EXIT=$?", 1, 1, 0),
    ("pytest; echo EXIT=$?", 1, 1, 1),
    ("pytest; echo EXIT=$?", 1, 0, None),
    ("pytest", 1, 1, 0),
    ("pytest", 1, 1, 1),
    ("pytest", 1, 0, None),
    ("pytest", 1, 1, None),
    ("pytest", 2, 1, 0),
    ("pytest", 1, 2, 0),
)


def _load():
    # Read on every call (no class cache) so a missing table fails each test on its own.
    return json.loads(TABLE.read_bytes().decode("utf-8"))


def _carrier_key(row):
    carrier = row["carrier"]
    return (row["command"], carrier["callEvents"], carrier["outputRecords"], carrier["exitCode"])


class TestBR6CaseTable(unittest.TestCase):
    # Guards: a table written with CRLF, invalid UTF-8 bytes, or no trailing newline.
    def test_table_file_exists_lf_utf8(self):
        self.assertTrue(TABLE.is_file(), f"missing BR6 case table: {TABLE.relative_to(REPO).as_posix()}")
        data = TABLE.read_bytes()
        data.decode("utf-8")  # strict decode raises on invalid UTF-8
        self.assertNotIn(b"\r", data, "the table must use LF line endings only")
        self.assertTrue(data.endswith(b"\n"), "the table must end with a newline")

    # Guards: an extra or renamed top-level key, a schema bump, or a moved testCommand source.
    def test_top_level_shape(self):
        table = _load()
        self.assertIsInstance(table, dict)
        self.assertEqual(set(table), TOP_LEVEL_KEYS)
        self.assertIs(type(table["schema"]), int)
        self.assertEqual(table["schema"], 1)
        self.assertEqual(table["testCommandSource"], TEST_COMMAND_SOURCE)
        self.assertIsInstance(table["rows"], list)
        self.assertTrue(table["rows"], "rows must be a non-empty list")

    # Guards: a reused id (consumers key subtests by id) or a non-kebab-case id.
    def test_row_ids_unique_and_well_formed(self):
        ids = [row.get("id") for row in _load()["rows"]]
        malformed = [i for i in ids if not (isinstance(i, str) and ID_PATTERN.fullmatch(i))]
        self.assertEqual(malformed, [], f"ids that are not kebab-case: {malformed}")
        repeated = sorted({i for i in ids if isinstance(i, str) and ids.count(i) > 1})
        self.assertEqual(repeated, [], f"ids used more than once: {repeated}")

    # Guards: a missing/extra column, a stringly boolean, an out-of-enum outcome, or a carrier
    # whose exit code or summary contradicts its output-record count.
    def test_rows_have_exact_columns_types_and_enums(self):
        for row in _load()["rows"]:
            with self.subTest(id=row.get("id")):
                self.assertEqual(set(row), REQUIRED_COLUMNS)

                command = row["command"]
                self.assertIsInstance(command, str)
                self.assertTrue(command, "command must be non-empty")
                self.assertNotIn("\r", command, "command newlines must be LF")

                refs = row["specRefs"]
                self.assertIsInstance(refs, list)
                self.assertTrue(refs, "specRefs must be non-empty")
                for ref in refs:
                    self.assertIn(ref, ALLOWED_REFS)

                carrier = row["carrier"]
                self.assertIsInstance(carrier, dict)
                self.assertEqual(set(carrier), CARRIER_KEYS)
                self.assertIs(type(carrier["callEvents"]), int)
                self.assertGreaterEqual(carrier["callEvents"], 1)
                self.assertIs(type(carrier["outputRecords"]), int)
                self.assertGreaterEqual(carrier["outputRecords"], 0)
                exit_code = carrier["exitCode"]
                self.assertTrue(exit_code is None or (type(exit_code) is int and exit_code in (0, 1)),
                                f"exitCode must be 0, 1 or null, got {exit_code!r}")
                summary = carrier["outputSummary"]
                self.assertTrue(summary is None or isinstance(summary, str),
                                f"outputSummary must be a string or null, got {summary!r}")
                if carrier["outputRecords"] == 0:
                    self.assertIsNone(exit_code, "no output record means no exit code")
                    self.assertIsNone(summary, "no output record means no output summary")

                statements = row["statements"]
                self.assertIsInstance(statements, list)
                self.assertTrue(statements, "statements must be non-empty")
                for statement in statements:
                    self.assertIsInstance(statement, str)
                    self.assertTrue(statement, "a statement must be non-empty")
                    self.assertEqual(statement, statement.strip(), "a statement must be trimmed")
                    self.assertFalse(statement.startswith("#"), "comment-only statements are ignored")

                for column in BOOL_COLUMNS:
                    self.assertIs(type(row[column]), bool, f"{column} must be a JSON boolean")
                self.assertIn(row["defaultTests"], TESTS_OUTCOMES)
                self.assertIn(row["strictTests"], TESTS_OUTCOMES)

                baseline = row["baseline5801cb9"]
                self.assertIsInstance(baseline, dict)
                self.assertEqual(set(baseline), BASELINE_KEYS)
                self.assertIn(baseline["claudeStopTests"], TESTS_OUTCOMES)
                self.assertIn(baseline["codexOrderGuard"], ORDER_OUTCOMES)
                self.assertIn(baseline["codexStopTests"], TESTS_OUTCOMES)

    # Guards: two rows describing the same input with possibly different expected outcomes.
    def test_command_carrier_pairs_unique(self):
        seen = {}
        for row in _load()["rows"]:
            seen.setdefault(_carrier_key(row), []).append(row["id"])
        duplicates = {key: ids for key, ids in seen.items() if len(ids) > 1}
        self.assertEqual(duplicates, {}, f"rows sharing (command, callEvents, outputRecords, exitCode): {duplicates}")

    # Guards: a spec-named shape silently dropped or untagged, leaving a consumer AC uncovered.
    def test_named_spec_shapes_present(self):
        present = {(ref, row["command"]) for row in _load()["rows"] for ref in row["specRefs"]}
        missing = [(ref, command) for ref, commands in SPEC_SHAPES.items()
                   for command in commands if (ref, command) not in present]
        self.assertEqual(missing, [], f"spec shapes with no row carrying that ref: {missing}")

    # Guards: a carrier-count or exit-code variant removed, so strict count checks lose a case.
    def test_named_carrier_variants_present(self):
        have = {_carrier_key(row) for row in _load()["rows"]}
        missing = [variant for variant in CARRIER_VARIANTS if variant not in have]
        self.assertEqual(missing, [], f"carrier variants with no row: {missing}")

    # Guards: AC130 comparison coverage drifting from the AC28 and AC118 trailing shapes.
    def test_ac130_rows_equal_ac28_and_ac118_commands(self):
        tagged = {row["command"] for row in _load()["rows"] if "AC130" in row["specRefs"]}
        expected = set(SPEC_SHAPES["AC28"]) | set(SPEC_SHAPES["AC118"])
        self.assertEqual(tagged, expected)

    # Guards: an outcome column that contradicts BR6, e.g. a trailing `; echo` row marked default
    # satisfied, a pipeline marked strictly attributable, or a 5801cb9 baseline column that does not
    # follow the runner shape and exit code.
    def test_outcome_columns_follow_br6_rules(self):
        for row in _load()["rows"]:
            with self.subTest(id=row.get("id")):
                carrier = row["carrier"]
                baseline = row["baseline5801cb9"]
                shape = row["runnerShape5801cb9"]
                exit_code = carrier["exitCode"]

                self.assertEqual(baseline["claudeStopTests"] == "satisfied", shape, "R1 claudeStopTests")
                self.assertEqual(baseline["codexOrderGuard"] == "satisfied", shape, "R2 codexOrderGuard")
                codex_stop = bool(shape and (exit_code is None or exit_code == 0))
                self.assertEqual(baseline["codexStopTests"] == "satisfied", codex_stop, "R3 codexStopTests")

                attributed = (exit_code is None
                              or len(row["statements"]) <= 1
                              or (row["lastIsRealRunner"] and not row["lastVersionOrHelpOnly"]))
                self.assertEqual(row["defaultTests"] == "satisfied",
                                 bool(baseline["codexStopTests"] == "satisfied" and attributed),
                                 "R4 defaultTests")

                strict = bool(row["lastIsRealRunner"]
                              and not row["lastVersionOrHelpOnly"]
                              and not row["lastHasPipe"]
                              and carrier["callEvents"] == 1
                              and carrier["outputRecords"] == 1
                              and type(exit_code) is int)
                self.assertEqual(row["strictAttributable"], strict, "R5 strictAttributable")
                self.assertEqual(row["strictTests"] == "satisfied",
                                 bool(row["strictAttributable"] and exit_code == 0),
                                 "R6 strictTests")

                if row["lastIsRealRunner"]:
                    self.assertTrue(shape, "R7 lastIsRealRunner implies runnerShape5801cb9")


if __name__ == "__main__":
    unittest.main()
