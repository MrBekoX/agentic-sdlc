"""Schema and coverage checks for the shared BR6 attribution case table (plan Task 0, D3).

The table is the only BR6 case source; slices B, C and GH read it read-only. These tests pin
its exact shape, its coverage of the spec's named command shapes and carrier variants, and the
column rules R1-R8 that tie every outcome column to the BR6 text, so a contradictory row fails
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
    "lastHasBackground",
    "inSafeGrammar",
    "orRun",
    "orRunAllRealRunners",
    "orRunHeadHasPipeOrBackground",
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
    "lastHasBackground",
    "inSafeGrammar",
    "orRunAllRealRunners",
    "orRunHeadHasPipeOrBackground",
    "runnerShape5801cb9",
    "strictAttributable",
)
TESTS_OUTCOMES = frozenset({"satisfied", "missing"})
ORDER_OUTCOMES = frozenset({"satisfied", "not-satisfied"})
ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# D25 word, segment and blank rows lie inside the grammar; test_named_word_segment_and_blank_rows pins them.
D25_FORGED_PREFIXES = ("edge-forged-word-", "edge-forged-segment-", "edge-forged-blank-")
# D27 runner-rule forgeries lie inside the grammar too; test_named_d27_rows pins them.
D27_FORGED_PREFIXES = ("edge-forged-append-", "edge-forged-escaped-separator-", "edge-forged-join-",
                       "edge-forged-value-blank-", "edge-forged-pipeline-mention-", "edge-forged-version-single-",
                       "edge-forged-red-python-")
# D28 launcher, option and script-option forgeries lie inside the grammar too; test_named_d28_rows pins them.
D28_FORGED_PREFIXES = ("edge-forged-launcher-list-", "edge-forged-option-", "edge-forged-script-option-")
# R11 (D27 operand rule): the operators of a plain-character command, longest first.
_PLAIN_OPERATOR = re.compile(r"(\|\||&&|\|&|;|&|\||\n)")
_WAITING_OPERATORS = frozenset({"&&", "||", "|", "|&"})


def _plain_well_formed(command):
    """True when every operator of a plain-character command has its operands (checked apart from both implementations).

    An operator other than newline right after a piece of only spaces and tabs has no left operand; an `&&`, `||`, `|`
    or `|&` still waiting for a non-blank piece at the end has no right operand.
    """
    pieces = _PLAIN_OPERATOR.split(command)
    pending = False
    pipe_pending = False
    for index in range(1, len(pieces), 2):
        before, operator = pieces[index - 1], pieces[index]
        if before.strip(" \t"):
            pending = pipe_pending = False
        elif operator != "\n":
            return False
        elif pipe_pending:
            return False  # D28: a newline while a `|` or `|&` waits
        if operator in _WAITING_OPERATORS:
            pending = True
            pipe_pending = operator in ("|", "|&")
    if pieces[-1].strip(" \t"):
        pending = False
    return not pending

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
        "pytest &",
        "pytest & wait",
        "pytest \\&& wait",
        "pytest \\>& wait",
        "pytest \\|& wait",
        "pytest |& tee log.txt",
        "pytest 2>&1",
        "pytest &> log.txt",
        'pytest -k "a&b"',
        "pytest # & wait",
        "pytest; echo EXIT=$? # ; pytest",
        "pytest; cat <<EOF\npytest",
        "pytest; echo $(echo x; pytest)",
        "pytest; echo ${x:-; pytest #}",
        "[[ x &&\npytest ||\npytest ]]",
        "pytest; (( x = 0,\npytest = 1 ))",
        "pytest() { true; }; pytest",
        "cd repo; eval 'pytest() { true; }'; pytest",
        "function pytest if true; then true; fi\npytest",
        "set -n; pytest",
        "set -n && pytest",
        "shopt -s expand_aliases\nalias pytest=true\npytest",
        "hash -p /usr/bin/true pytest; pytest",
        "trap 'exit 0' EXIT; pytest",
        "exit 0; pytest",
        "pytest; cat <<<x; pytest",
        "cd repo; pytest $(cat args)",
        "source .venv/bin/activate; pytest",
        "pytest $(cat args)",
        "true || pytest",
        "pytest --version || pytest",
        "pytest | tee log.txt || pytest",
        "pytest & wait || pytest",
        "pytest -x || pytest --lf",
        "cd repo; pytest > out.txt 2>&1",
        "cd repo; pytest -k \"a;b||c\" -m 'x # ; y'",
        "set -euo pipefail; pytest",
    ),
}

# R10 (D23): bash 5.2.37 `compgen -k` reserved words, its `compgen -b` builtins outside the safe set (`:`, true,
# false, cd, echo, pwd, export, set), and `set` (safe only in its errexit/nounset/pipefail forms). A command of plain
# words and characters none of which is in this set must lie inside the safe grammar.
R10_EXCLUDED_WORDS = frozenset({
    "!", "[[", "]]", "{", "}", "case", "coproc", "do", "done", "elif", "else", "esac", "fi", "for", "function",
    "if", "in", "select", "then", "time", "until", "while",
    ".", "[", "alias", "bg", "bind", "break", "builtin", "caller", "command", "compgen", "complete", "compopt",
    "continue", "declare", "dirs", "disown", "enable", "eval", "exec", "exit", "fc", "fg", "getopts", "hash",
    "help", "history", "jobs", "kill", "let", "local", "logout", "mapfile", "popd", "printf", "pushd", "read",
    "readarray", "readonly", "return", "shift", "shopt", "source", "suspend", "test", "times", "trap", "type",
    "typeset", "ulimit", "umask", "unalias", "unset", "wait",
    "set",
})
# R10 (D23): an assignment word, prefix or export argument, naming one of bash 5.2.37's integer-attributed variables
# (`declare -p`) evaluates its value as arithmetic, so a command holding one lies outside the grammar.
R10_INTEGER_ASSIGNMENT = re.compile(r"(?:BASHPID|EUID|HISTCMD|OPTIND|PPID|RANDOM|SRANDOM|UID)\+?=")

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
                    # D25 blank model: only space, tab and newline are blanks, so U+00A0 or U+3000 stays.
                    self.assertEqual(statement, statement.strip(" \t\n"), "a statement must be trimmed")
                    self.assertFalse(statement.startswith("#"), "comment-only statements are ignored")

                or_run = row["orRun"]
                self.assertIsInstance(or_run, list)
                self.assertTrue(or_run, "orRun must be non-empty")
                for operand in or_run:
                    self.assertIsInstance(operand, str)
                self.assertEqual(or_run, statements[-len(or_run):], "orRun must be a suffix of statements")

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

                command = row["command"]
                has_separator = ";" in command or "\n" in command or "||" in command
                attributed = (exit_code is None
                              or not has_separator
                              or (row["inSafeGrammar"]
                                  and ((len(row["statements"]) <= 1 and row["lastIsRealRunner"]
                                        and not row["lastVersionOrHelpOnly"])
                                       or (row["orRunAllRealRunners"] and not row["orRunHeadHasPipeOrBackground"]))))
                self.assertEqual(row["defaultTests"] == "satisfied",
                                 bool(baseline["codexStopTests"] == "satisfied" and attributed),
                                 "R4 defaultTests")

                strict = bool(row["inSafeGrammar"]
                              and row["orRunAllRealRunners"]
                              and not row["orRunHeadHasPipeOrBackground"]
                              and not row["lastHasPipe"]
                              and not row["lastHasBackground"]
                              and carrier["callEvents"] == 1
                              and carrier["outputRecords"] == 1
                              and type(exit_code) is int)
                self.assertEqual(row["strictAttributable"], strict, "R5 strictAttributable")
                self.assertEqual(row["strictTests"] == "satisfied",
                                 bool(row["strictAttributable"] and exit_code == 0),
                                 "R6 strictTests")

                if row["lastIsRealRunner"]:
                    self.assertTrue(shape, "R7 lastIsRealRunner implies runnerShape5801cb9")
                if row["lastHasBackground"]:
                    self.assertIn("&", row["statements"][-1], "R8 lastHasBackground needs a `&` in the last statement")
                if len(row["orRun"]) == 1:
                    self.assertEqual(row["orRunAllRealRunners"],
                                     row["lastIsRealRunner"] and not row["lastVersionOrHelpOnly"],
                                     "R9 a single-operand orRun is all real runners iff its last statement is")
                    self.assertFalse(row["orRunHeadHasPipeOrBackground"], "R9 a single-operand orRun has no head")
                plain_chars = not any(ch in "$(){}[]<>\\*?'\"#`" for ch in command)
                no_controls = not any((ord(ch) < 32 and ch not in "\t\n") or ord(ch) == 127 for ch in command)
                words = set(re.split(r"[ \t\n;|&]+", command))
                integer_assignment = any(R10_INTEGER_ASSIGNMENT.match(word) for word in words)
                if plain_chars and no_controls and not (words & R10_EXCLUDED_WORDS) and not integer_assignment:
                    self.assertIs(row["inSafeGrammar"], _plain_well_formed(command),
                                  "R10/R11 plain words lie inside the grammar exactly when every operator has operands")

    # Guards: a construct row (outside the D23 grammar) marked attributable, a trailing `||` forgery marked default
    # satisfied, a separator-free construct losing its 5801cb9 default, or a legitimate shape marked outside.
    def test_named_grammar_rows(self):
        rows = {row["id"]: row for row in _load()["rows"]}
        forged = [i for i in rows if i.startswith("edge-forged-")
                  and not i.startswith(D25_FORGED_PREFIXES + D27_FORGED_PREFIXES + D28_FORGED_PREFIXES)
                  and not i.startswith("edge-forged-oror-")]
        self.assertGreaterEqual(len(forged), 40)
        for row_id in forged:
            with self.subTest(id=row_id):
                self.assertIs(rows[row_id]["inSafeGrammar"], False)
                self.assertIs(rows[row_id]["strictAttributable"], False)
        # Expansion forgeries through printf, unset and `[`, closed by the minimized safe-builtin set.
        for row_id in ("edge-forged-printf-hash-table-tilde", "edge-forged-unset-arithmetic-subscript",
                       "edge-forged-bracket-hash-table-arithmetic"):
            with self.subTest(id=row_id):
                self.assertIs(rows[row_id]["inSafeGrammar"], False)
                self.assertEqual(rows[row_id]["defaultTests"], "missing")
                self.assertIs(rows[row_id]["strictAttributable"], False)
        oror = [i for i in rows if i.startswith("edge-forged-oror-")]
        self.assertEqual(len(oror), 5)
        for row_id in oror:
            with self.subTest(id=row_id):
                # `wait` is outside the safe builtins, so only the background-head operand lies outside the grammar.
                self.assertIs(rows[row_id]["inSafeGrammar"], row_id != "edge-forged-oror-background-head")
                self.assertEqual(rows[row_id]["defaultTests"], "missing")
                self.assertIs(rows[row_id]["strictAttributable"], False)
        # Disclosed false 'missing' rows: a builtin outside the minimized safe set together with a separator.
        for row_id in ("edge-outside-test-builtin", "edge-outside-printf-builtin", "edge-outside-unset-builtin",
                       "edge-outside-wait-builtin", "edge-outside-export-subscript-literal"):
            with self.subTest(id=row_id):
                self.assertIs(rows[row_id]["inSafeGrammar"], False)
                self.assertEqual(rows[row_id]["defaultTests"], "missing")
                self.assertIs(rows[row_id]["strictAttributable"], False)
        # Integer-attributed assignments (standalone, append, or an export argument whose name is not literal) evaluate
        # their value as arithmetic that writes BASH_CMDS; bash 5.2.37 exits 0 without running the runner.
        integer_forged = [i for i in rows if i.startswith("edge-forged-integer-")]
        self.assertEqual(len(integer_forged), 13)
        for row_id in integer_forged:
            with self.subTest(id=row_id):
                self.assertIs(rows[row_id]["inSafeGrammar"], False)
                self.assertEqual(rows[row_id]["defaultTests"], "missing")
                self.assertIs(rows[row_id]["strictAttributable"], False)
        for row_id in ("edge-outside-integer-random-number", "edge-outside-integer-random-prefix",
                       "edge-outside-export-quoted-argument"):
            with self.subTest(id=row_id):
                self.assertIs(rows[row_id]["inSafeGrammar"], False)
                self.assertEqual(rows[row_id]["defaultTests"], "missing")
                self.assertIs(rows[row_id]["strictAttributable"], False)
        for row_id in ("edge-inside-cd-tilde-oldpwd", "edge-inside-echo-tilde-oldpwd",
                       "edge-inside-echo-parameter-subscript-text", "edge-inside-colon-parameter-subscript-text",
                       "edge-inside-cd-quoted-parameter", "edge-inside-cdpath-subscript-text",
                       "edge-inside-set-cd-echo-before-runner", "edge-inside-seconds-assignment",
                       "edge-inside-lineno-assignment", "edge-inside-export-plain-arguments"):
            with self.subTest(id=row_id):
                self.assertIs(rows[row_id]["inSafeGrammar"], True)
                self.assertIs(rows[row_id]["strictAttributable"], True)
        for row_id in ("edge-single-statement-substitution", "edge-forged-hidden-pipe-ansi-c",
                       "edge-forged-set-noexec-andand"):
            with self.subTest(id=row_id):
                self.assertIs(rows[row_id]["inSafeGrammar"], False)
                self.assertEqual(rows[row_id]["defaultTests"], "satisfied")
                self.assertIs(rows[row_id]["strictAttributable"], False)
        for row_id in ("edge-oror-real-runners", "edge-redirect-out-and-stderr", "edge-quoted-separators-mixed",
                       "edge-set-errexit-pipefail", "edge-safe-builtins-before-runner"):
            with self.subTest(id=row_id):
                self.assertIs(rows[row_id]["inSafeGrammar"], True)
                self.assertIs(rows[row_id]["strictAttributable"], True)

    # Guards (D25): a forged word, segment or blank row inside the grammar marked attributable or default satisfied
    # after a separator, an inside row losing its attribution, or a blank row whose U+00A0/U+3000 prefix was trimmed.
    def test_named_word_segment_and_blank_rows(self):
        rows = {row["id"]: row for row in _load()["rows"]}
        word = [i for i in rows if i.startswith("edge-forged-word-")]
        segment = [i for i in rows if i.startswith("edge-forged-segment-")]
        blank = [i for i in rows if i.startswith("edge-forged-blank-")]
        self.assertEqual((len(word), len(segment), len(blank)), (15, 3, 4))
        for row_id in word + segment + ["edge-conservative-word-glob-without-slash"]:
            with self.subTest(id=row_id):
                row = rows[row_id]
                self.assertIs(row["inSafeGrammar"], True)
                self.assertIs(row["lastVersionOrHelpOnly"], True)
                self.assertIs(row["orRunAllRealRunners"], False)
                self.assertIs(row["strictAttributable"], False)
                expected = "satisfied" if row_id == "edge-forged-word-escaped-version-single" else "missing"
                self.assertEqual(row["defaultTests"], expected)
        for row_id, column in (("edge-forged-blank-nbsp-comment-background", "lastHasBackground"),
                               ("edge-forged-blank-ideographic-comment-background", "lastHasBackground"),
                               ("edge-forged-blank-nbsp-comment-pipe", "lastHasPipe"),
                               ("edge-forged-blank-nbsp-comment-pipe-head", "orRunHeadHasPipeOrBackground")):
            with self.subTest(id=row_id):
                row = rows[row_id]
                self.assertIs(row[column], True)
                self.assertIs(row["inSafeGrammar"], True)
                head = column == "orRunHeadHasPipeOrBackground"
                self.assertEqual(row["defaultTests"], "missing" if head else "satisfied")
                self.assertIs(row["strictAttributable"], False)
                self.assertIn(row["command"][0], (chr(0xA0), chr(0x3000)))
                self.assertEqual(row["statements"][0][0], row["command"][0])
        pipe_head = rows["edge-forged-blank-nbsp-comment-pipe-head"]
        self.assertEqual(pipe_head["orRun"], pipe_head["statements"])
        inside = [i for i in rows if i.startswith(("edge-inside-word-", "edge-inside-segment-"))]
        self.assertEqual(len(inside), 9)
        for row_id in inside:
            with self.subTest(id=row_id):
                self.assertIs(rows[row_id]["inSafeGrammar"], True)
                self.assertIs(rows[row_id]["strictAttributable"], True)
                self.assertEqual(rows[row_id]["strictTests"], "satisfied")
        self.assertEqual(rows["edge-forged-word-continuation-version"]["statements"], ["pytest", "pytest --version"])
        for row_id in ("edge-forged-word-escaped-version-oror", "edge-forged-word-redirect-glued-help-oror"):
            with self.subTest(id=row_id):
                self.assertEqual(rows[row_id]["orRun"], rows[row_id]["statements"])
        param = rows["edge-param-simple"]
        self.assertEqual((param["lastVersionOrHelpOnly"], param["orRunAllRealRunners"], param["defaultTests"],
                          param["strictAttributable"], param["strictTests"]), (True, False, "missing", False, "missing"))
        for row_id in ("edge-conservative-substitution-with-separator", "edge-single-statement-substitution",
                       "edge-forged-hidden-pipe-ansi-c"):
            with self.subTest(id=row_id):
                # D27: a statement outside the grammar runs no runner, so it is not version-only either.
                self.assertEqual((rows[row_id]["lastVersionOrHelpOnly"], rows[row_id]["orRunAllRealRunners"]),
                                 (False, False))

    # Guards (D27): a runner-rule forgery (NAME+=, escaped separator, joined line, blank inside an assignment value,
    # mention before a pipe, single-statement version run) marked attributable or default satisfied after a separator,
    # a syntax-error or non-runner-module RED marked attributable, or a bash-proven inside row losing its attribution.
    def test_named_d27_rows(self):
        rows = {row["id"]: row for row in _load()["rows"]}

        def ids(prefix):
            return [i for i in rows if i.startswith(prefix)]

        counts = {prefix: len(ids(prefix)) for prefix in (
            "edge-forged-append-", "edge-forged-escaped-separator-", "edge-forged-join-", "edge-forged-value-blank-",
            "edge-forged-pipeline-mention-", "edge-forged-version-single-", "edge-forged-red-",
            "edge-inside-runner-", "edge-inside-value-", "edge-inside-append-", "edge-inside-background-",
            "edge-conservative-redirect-")}
        self.assertEqual(counts, {
            "edge-forged-append-": 7, "edge-forged-escaped-separator-": 9, "edge-forged-join-": 4,
            "edge-forged-value-blank-": 8, "edge-forged-pipeline-mention-": 1, "edge-forged-version-single-": 3,
            "edge-forged-red-": 7, "edge-inside-runner-": 19, "edge-inside-value-": 2, "edge-inside-append-": 1,
            "edge-inside-background-": 1, "edge-conservative-redirect-": 1})
        self.assertEqual(len(rows), 321)

        forged = [i for i in rows if i.startswith(D27_FORGED_PREFIXES[:-1])]
        self.assertEqual(len(forged), 32)
        separator_free = {"edge-forged-append-single", "edge-forged-append-prefixed-single",
                          "edge-forged-escaped-separator-pipe", "edge-forged-escaped-separator-pipe-args",
                          "edge-forged-value-blank-escaped-space-single", "edge-forged-value-blank-nbsp-single"}
        version_single = set(ids("edge-forged-version-single-"))
        for row_id in forged:
            with self.subTest(id=row_id):
                row = rows[row_id]
                self.assertEqual(row["carrier"], {"callEvents": 1, "outputRecords": 1, "exitCode": 0,
                                                  "outputSummary": "1 failed"})
                self.assertEqual(row["specRefs"], ["EDGE-EXIT"])
                self.assertIs(row["inSafeGrammar"], True)
                self.assertIs(row["runnerShape5801cb9"], True)
                self.assertIs(row["strictAttributable"], False)
                self.assertIs(row["orRunAllRealRunners"], False)
                self.assertIs(row["orRunHeadHasPipeOrBackground"], False)
                runs = row_id == "edge-forged-pipeline-mention-version" or row_id in version_single
                self.assertIs(row["lastIsRealRunner"], runs)
                self.assertIs(row["lastVersionOrHelpOnly"], runs)
                self.assertIs(row["lastHasPipe"], row_id == "edge-forged-pipeline-mention-version")
                if row_id in version_single:
                    self.assertEqual(len(row["statements"]), 1)
                self.assertEqual(row["defaultTests"], "satisfied" if row_id in separator_free else "missing")
                separator = any(s in row["command"] for s in (";", "\n", "||"))
                self.assertIs(separator, row_id not in separator_free)
        # D27 column summary: the join rows and the single-command escaped-separator rows are one statement each,
        # and orRun is the last statement except for the four rows whose command holds an unescaped `||`.
        one_statement = ids("edge-forged-join-") + ["edge-forged-escaped-separator-" + suffix for suffix in (
            "semicolon", "semicolon-glued", "pipe", "pipe-args", "npm", "python-m")]
        self.assertEqual(len(one_statement), 10)
        oror_rows = {"edge-forged-append-oror", "edge-forged-escaped-separator-oror",
                     "edge-forged-value-blank-nbsp-oror", "edge-forged-join-comment-oror"}
        self.assertLessEqual(set(one_statement) | oror_rows, set(forged))
        for row_id in forged:
            with self.subTest(id=row_id, check="summary"):
                if row_id in one_statement:
                    self.assertEqual(len(rows[row_id]["statements"]), 1)
                if row_id not in oror_rows:
                    self.assertEqual(rows[row_id]["orRun"], rows[row_id]["statements"][-1:])
        self.assertEqual(rows["edge-forged-join-comment-oror"]["orRun"], ["echo x"])
        for row_id in ("edge-forged-append-oror", "edge-forged-escaped-separator-oror",
                       "edge-forged-value-blank-nbsp-oror"):
            with self.subTest(id=row_id):
                self.assertEqual(rows[row_id]["orRun"], rows[row_id]["statements"])

        red = ids("edge-forged-red-")
        syntax_error = [i for i in red if i != "edge-forged-red-python-module"]
        self.assertEqual(len(syntax_error), 6)
        for row_id in red:
            with self.subTest(id=row_id):
                row = rows[row_id]
                module = row_id == "edge-forged-red-python-module"
                self.assertEqual(row["carrier"]["exitCode"], 1)
                self.assertEqual(row["carrier"]["outputSummary"], "No module named jest" if module else "syntax error")
                self.assertIs(row["strictAttributable"], False)
                self.assertEqual(row["defaultTests"], "missing")
                self.assertIs(row["runnerShape5801cb9"], True)
                self.assertIs(row["inSafeGrammar"], module)
                runs = not module and row["statements"][-1] == "pytest"
                self.assertIs(row["lastIsRealRunner"], runs)
                self.assertIs(row["orRunAllRealRunners"], runs)
                self.assertEqual(row["baseline5801cb9"], {"claudeStopTests": "satisfied", "codexOrderGuard": "satisfied",
                                                          "codexStopTests": "missing"})
        self.assertEqual(rows["edge-forged-red-trailing-oror"]["statements"], ["pytest"])
        self.assertEqual(rows["edge-forged-red-leading-semicolon"]["statements"], ["pytest"])
        self.assertEqual(rows["edge-forged-red-trailing-andand"]["statements"], ["pytest &&"])
        self.assertEqual(rows["edge-forged-red-trailing-andand-newline"]["statements"], ["pytest &&"])
        self.assertEqual(rows["edge-forged-red-empty-andand-operand"]["statements"], ["pytest", "&& pytest"])
        self.assertEqual(rows["edge-forged-red-double-semicolon"]["statements"], ["true", "pytest"])

        inside = [i for i in rows if i.startswith(("edge-inside-runner-", "edge-inside-value-", "edge-inside-append-",
                                                   "edge-inside-background-"))]
        self.assertEqual(len(inside), 23)
        for row_id in inside:
            with self.subTest(id=row_id):
                row = rows[row_id]
                background = row_id == "edge-inside-background-head-runner"
                self.assertEqual(row["carrier"]["exitCode"], 0)
                for column in ("inSafeGrammar", "lastIsRealRunner", "orRunAllRealRunners", "runnerShape5801cb9"):
                    self.assertIs(row[column], True, column)
                self.assertEqual(row["defaultTests"], "satisfied")
                self.assertIs(row["lastHasBackground"], background)
                self.assertIs(row["strictAttributable"], not background)
                self.assertEqual(row["strictTests"], "missing" if background else "satisfied")

        conservative = rows["edge-conservative-redirect-before-runner"]
        self.assertEqual((conservative["inSafeGrammar"], conservative["lastIsRealRunner"],
                          conservative["defaultTests"], conservative["strictAttributable"]),
                         (True, False, "missing", False))
        for row_id in forged + inside + ["edge-conservative-redirect-before-runner"]:
            with self.subTest(id=row_id):
                self.assertEqual(set(rows[row_id]["baseline5801cb9"].values()), {"satisfied"})

    # Guards (D28, DP40): a newline after a waiting `|` read as a statement end, a `py -0` list or a Python-word
    # selector read as a runner, a version, help or skip-if-missing spelling read as a test run, or a script-name
    # runner (`npm run test:unit`) rejected.
    def test_named_d28_rows(self):
        rows = {row["id"]: row for row in _load()["rows"]}

        def ids(prefix):
            return [i for i in rows if i.startswith(prefix)]

        counts = {prefix: len(ids(prefix)) for prefix in (
            "edge-forged-pipe-newline-", "edge-forged-launcher-list-", "edge-forged-option-",
            "edge-forged-script-option-", "edge-red-", "edge-inside-join-", "edge-inside-selector-",
            "edge-inside-option-", "edge-inside-script-", "edge-conservative-selector-",
            "edge-conservative-pipe-newline-", "edge-conservative-option-")}
        self.assertEqual(counts, {
            "edge-forged-pipe-newline-": 5, "edge-forged-launcher-list-": 3, "edge-forged-option-": 22,
            "edge-forged-script-option-": 3, "edge-red-": 6, "edge-inside-join-": 1, "edge-inside-selector-": 3,
            "edge-inside-option-": 5, "edge-inside-script-": 10, "edge-conservative-selector-": 1,
            "edge-conservative-pipe-newline-": 1, "edge-conservative-option-": 5})
        separator_free = {"edge-forged-launcher-list-single", "edge-forged-option-pytest-cluster-single",
                          "edge-forged-option-npm-single"}
        forged = ids("edge-forged-pipe-newline-") + ids(D28_FORGED_PREFIXES)
        for row_id in forged:
            with self.subTest(id=row_id, check="carrier"):
                self.assertEqual(rows[row_id]["carrier"], {"callEvents": 1, "outputRecords": 1, "exitCode": 0,
                                                           "outputSummary": "1 failed"})
                self.assertEqual(rows[row_id]["specRefs"], ["EDGE-EXIT"])
        for row_id in ids("edge-forged-pipe-newline-"):
            with self.subTest(id=row_id):
                row = rows[row_id]
                self.assertEqual((row["inSafeGrammar"], row["defaultTests"], row["strictAttributable"]),
                                 (False, "missing", False))
                self.assertEqual(len(row["statements"]), 3)
                self.assertEqual((row["lastIsRealRunner"], row["orRunAllRealRunners"]), (True, True))
        for row_id in ids(D28_FORGED_PREFIXES):
            with self.subTest(id=row_id):
                row = rows[row_id]
                self.assertIs(row["inSafeGrammar"], True)
                self.assertIs(row["strictAttributable"], False)
                self.assertIs(row["orRunAllRealRunners"], False)
                self.assertEqual(row["defaultTests"], "satisfied" if row_id in separator_free else "missing")
                separator = any(s in row["command"] for s in (";", "\n", "||"))
                self.assertIs(separator, row_id not in separator_free)
                launcher = row_id.startswith("edge-forged-launcher-list-")
                self.assertEqual((row["lastIsRealRunner"], row["lastVersionOrHelpOnly"]),
                                 (False, False) if launcher else (True, True))
        for row_id in ids("edge-red-"):
            with self.subTest(id=row_id):
                row = rows[row_id]
                self.assertEqual(row["carrier"]["exitCode"], 1)
                self.assertTrue(row["carrier"]["outputSummary"].startswith(("Unknown option: -", "Unknown command: ")))
                self.assertEqual((row["inSafeGrammar"], row["lastIsRealRunner"], row["strictAttributable"],
                                  row["defaultTests"]), (True, False, False, "missing"))
                self.assertEqual(row["baseline5801cb9"]["codexStopTests"], "missing")
        for row_id in ids(("edge-inside-join-", "edge-inside-selector-", "edge-inside-option-",
                           "edge-inside-script-")):
            with self.subTest(id=row_id):
                row = rows[row_id]
                self.assertEqual(row["carrier"]["outputSummary"], "1 passed")
                self.assertEqual((row["inSafeGrammar"], row["lastIsRealRunner"], row["orRunAllRealRunners"],
                                  row["lastVersionOrHelpOnly"], row["runnerShape5801cb9"], row["defaultTests"],
                                  row["strictAttributable"], row["strictTests"]),
                                 (True, True, True, False, True, "satisfied", True, "satisfied"))
        for row_id in ids(("edge-conservative-selector-", "edge-conservative-pipe-newline-",
                           "edge-conservative-option-")):
            with self.subTest(id=row_id):
                row = rows[row_id]
                self.assertEqual(row["carrier"]["outputSummary"], "1 passed")
                self.assertEqual((row["defaultTests"], row["strictAttributable"]), ("missing", False))
                self.assertIs(row["runnerShape5801cb9"], row_id != "edge-conservative-selector-architecture")
        self.assertEqual(len(rows), 321)

    # Guards: a background job (`&`, including after an escaped operator character) marked attributable, or a
    # redirection, `|&`, quoted or commented `&` misread as a background job (D21).
    def test_named_background_rows(self):
        rows = {row["id"]: row for row in _load()["rows"]}
        for row_id in ("edge-background-trailing", "edge-background-then-wait", "edge-background-escaped-andand",
                       "edge-background-escaped-redirect", "edge-background-escaped-pipe"):
            with self.subTest(id=row_id):
                self.assertIs(rows[row_id]["lastHasBackground"], True)
                self.assertIs(rows[row_id]["strictAttributable"], False)
        for row_id in ("edge-pipe-ampersand", "edge-redirect-stderr-to-stdout", "edge-redirect-both-streams",
                       "edge-quoted-ampersand", "edge-comment-ampersand", "ac31-pipe-tail"):
            with self.subTest(id=row_id):
                self.assertIs(rows[row_id]["lastHasBackground"], False)


if __name__ == "__main__":
    unittest.main()
