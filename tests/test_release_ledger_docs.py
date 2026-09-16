"""Ledger format contract for docs/release-evidence-0.4.3.md (decision D1; spec AC113, AC116, AC117, AC129).

Tasks 83-85 write this format and the release envelope parses it when it fills live rows:
- Row ids are backticked lowercase snake_case in the first cell of the table under `## Required release rows`.
- Splitting a row line on `|` gives index 2 = BR3 required (`yes`/`no`) and index 3 = state.
- Annotations are bullets under one dated `### Annotations to historical rows (YYYY-MM-DD)` heading.
- The decision block is the first text fence after `## Publication decision`, one `key=value` per line,
  followed by a `| Key | Bound row |` table; `### Path verdicts` is the last section of the file.

The helpers are pure and return named violations, so the synthetic cases prove each rule fires.
"""
import re
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LEDGER = REPO / "docs" / "release-evidence-0.4.3.md"

# Byte-exact table lines 12 and 19 of docs/release-evidence-0.4.3.md at 5801cb9, whose blob is ORIGINAL_LEDGER_BLOB.
# The test reads the blob, not the commit: a history rewrite keeps the blob id but not the commit id (D25).
ORIGINAL_LEDGER_BLOB = "92b9c17a5913b1d62dbce4d4ce1a01b81087a0fe"
ORIGINAL_VERSION_ROW = (
    "| Version/changelog consistency | PASS: all declarations are 0.4.3 and both version/release checks exit zero"
    " | VERSION, README and both plugin manifests/marketplace agree; release check passes |"
)
ORIGINAL_SCANS_ROW = (
    "| Public source and artifact scans | Prepared source/archive scan passes: three inspected synthetic/documentation"
    " matches, zero unresolved findings or private host paths | Scan generated live artifacts after execution too |"
)
BR3_REQUIRED_ROWS = (
    "local_gate",
    "claude_routing_eval",
    "codex_routing_eval",
    "claude_pipeline_procedure",
    "codex_pipeline_procedure",
    "secret_scan",
    "clean_package_native_validation",
    "codex_discovery_16_8",
    "hook_trust_untrusted",
    "hook_trust_exact_definition",
    "hook_trust_retained_after_restart",
    "hook_trust_rereview_after_change",
    "hook_effects_allowed_denied",
    "hook_native_resume_compact",
    "hook_trust_list_records",
    "archive_verify",
    "archive_reproducibility",
    "pr_text_actions_review",
    "owner_skill_injection",
    "owner_resume",
    "owner_compaction",
)
ANNOTATION_TARGET_ROWS = ("current_version_declarations", "history_private_path_finding")
DECISION_KEYS = (
    "version",
    "scope",
    "local_gate",
    "claude_routing_eval",
    "codex_routing_eval",
    "claude_pipeline_procedure",
    "codex_pipeline_procedure",
    "secret_scan",
    "known_limitations_acknowledged",
    "verdict",
)
STATE_KEYS = DECISION_KEYS[2:8]
STATE_MAP = {"passed": "PASS", "failed": "FAIL", "blocked": "BLOCKED", "not-run": "not-run"}
ROW_STATES = ("PASS", "FAIL", "BLOCKED", "not-run", "GAP")
MEASUREMENT_TYPES = ("native live", "deterministic replay", "description classifier", "static gate")
PATH_LABELS = (
    "Claude own marketplace",
    "Claude community marketplace submission",
    "Codex personal marketplace",
    "OpenAI public directory",
)
ROWS_HEADER = "| Row id | BR3 required | State | Identity (definition) | Git commit | CLI version | OS | Model/effort | Measurement type | Evidence |"
ANNOTATION_HEADING = re.compile(r"^### Annotations to historical rows \(\d{4}-\d{2}-\d{2}\)$")
ADAPTER_LIMITS_HEADING = "### Limits of branch, review-result and strict evidence"
ADAPTER_LIMITS_LINK = "docs/runtime-adapter.md#limits-of-branch-review-result-and-strict-evidence"
ROW_FIELDS = ("br3", "state", "identity", "commit", "cli", "os", "model", "measurement", "evidence")


def _section(lines, start_index):
    """Lines after `start_index` up to (excluding) the next Markdown heading."""
    body = []
    for line in lines[start_index + 1 :]:
        if line.startswith("#"):
            break
        body.append(line)
    return body


def _row_cells(line):
    return [cell.strip() for cell in line.split("|")]


def _row_id(cell):
    match = re.fullmatch(r"`([a-z0-9_]+)`", cell)
    return match.group(1) if match else None


def required_rows(text):
    """Parse `## Required release rows`; return (rows, violations)."""
    lines = text.splitlines()
    try:
        start = lines.index("## Required release rows")
    except ValueError:
        return {}, ["rows_header_mismatch"]
    body = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        body.append(line)
    table = [line for line in body if line.startswith("|")]
    if not table or table[0] != ROWS_HEADER:
        return {}, ["rows_header_mismatch"]
    rows, violations = {}, []
    for line in table[2:]:
        cells = _row_cells(line)
        row_id = _row_id(cells[1]) if len(cells) > 1 else None
        if row_id is None:
            continue
        if row_id in rows:
            violations.append("duplicate_row:" + row_id)
            continue
        values = (cells[2:11] + [""] * 9)[:9]
        rows[row_id] = dict(zip(ROW_FIELDS, values))
    for row_id in BR3_REQUIRED_ROWS:
        if row_id not in rows:
            violations.append("missing_required_row:" + row_id)
    for row_id, row in rows.items():
        expected = "yes" if row_id in BR3_REQUIRED_ROWS else "no"
        if row["br3"] != expected:
            violations.append("br3_flag_mismatch:" + row_id)
        tokens = row["state"].split()
        if not tokens or tokens[0].rstrip(".,;:") not in ROW_STATES:
            violations.append("invalid_state:" + row_id)
        if row["measurement"] not in MEASUREMENT_TYPES:
            violations.append("invalid_measurement:" + row_id)
        if any(not row[field] for field in ("identity", "commit", "cli", "os", "model")):
            violations.append("unbound_row:" + row_id)
    return rows, violations


def _row_state(row):
    tokens = row["state"].split()
    return tokens[0].rstrip(".,;:") if tokens else ""


def annotation_violations(text):
    lines = text.splitlines()
    violations = []
    if ORIGINAL_VERSION_ROW not in lines:
        violations.append("missing_original_row:version")
    if ORIGINAL_SCANS_ROW not in lines:
        violations.append("missing_original_row:scans")
    headings = [i for i, line in enumerate(lines) if ANNOTATION_HEADING.match(line)]
    if not headings:
        violations.append("missing_annotation_section")
    else:
        bullets = [line for line in _section(lines, headings[0]) if line.startswith("- ")]
        version = [b for b in bullets if b.startswith("- **Version/changelog consistency**")]
        if not version or not all(x in version[0] for x in ("F5", "README.md:250", "0.4.2", "current_version_declarations")):
            violations.append("missing_annotation:version")
        scans = [b for b in bullets if b.startswith("- **Public source and artifact scans**")]
        if not scans or not all(x in scans[0] for x in ("not Git history", "history_private_path_finding")):
            violations.append("missing_annotation:scans")
    rows, _ = required_rows(text)
    for row_id in ANNOTATION_TARGET_ROWS:
        if row_id not in rows:
            violations.append("annotation_target_missing:" + row_id)
    return violations


def _paragraph_starts(lines):
    starts = []
    for i, line in enumerate(lines):
        if not line.strip() or line.startswith(("#", "|", "- ", "```")):
            continue
        if i == 0 or not lines[i - 1].strip():
            starts.append(line)
    return starts


def paragraph_citation_violations(text):
    """Annotations cite ledger paragraphs by their opening words; a line number is valid only at 5801cb9 (QUAL-18)."""
    lines = text.splitlines()
    headings = [i for i, line in enumerate(lines) if ANNOTATION_HEADING.match(line)]
    if not headings:
        return ["missing_annotation_section"]
    starts = _paragraph_starts(lines)
    violations = []
    for bullet in (line for line in _section(lines, headings[0]) if line.startswith("- ")):
        if re.search(r"\bline \d+", bullet) and "at 5801cb9" not in bullet:
            violations.append("line_reference_without_5801cb9")
        for phrase in re.findall(r'"([^"]+)"', bullet):
            if not any(start.startswith(phrase) for start in starts):
                violations.append("quoted_phrase_not_a_paragraph_start:" + phrase)
    return violations


GOOD_CITATION_LEDGER = "\n".join(
    [
        "# Release evidence",
        "",
        "### Annotations to historical rows (2026-09-15)",
        "",
        '- **Source-archive recipe (the paragraph beginning "The release source excludes"; line 60 at 5801cb9)**: superseded.',
        "",
        "The release source excludes private audit writeups.",
        "",
    ]
)


def decision_block_violations(ledger, version, runtime_adapter):
    lines = ledger.splitlines()
    try:
        start = lines.index("## Publication decision")
    except ValueError:
        return ["decision_block_missing"]
    fence_start = next((i for i in range(start + 1, len(lines)) if lines[i].strip() == "```text"), None)
    if fence_start is None:
        return ["decision_block_missing"]
    fence_end = next((i for i in range(fence_start + 1, len(lines)) if lines[i].strip() == "```"), None)
    if fence_end is None:
        return ["decision_block_missing"]
    pairs = [line.split("=", 1) for line in lines[fence_start + 1 : fence_end] if line.strip()]
    keys = [pair[0] for pair in pairs]
    values = {pair[0]: (pair[1] if len(pair) > 1 else "") for pair in pairs}
    tail = []
    for line in lines[fence_end + 1 :]:
        if line.startswith("## "):
            break
        tail.append(line)
    key_table = [line for line in tail if line.startswith("|")]
    violations = []
    if tuple(keys) != DECISION_KEYS:
        violations.append("keys_mismatch")
    if values.get("version") != version:
        violations.append("version_mismatch")
    if values.get("scope") != "Claude Code, Codex":
        violations.append("scope_mismatch")
    rows, _ = required_rows(ledger)
    for key in STATE_KEYS:
        value = values.get(key)
        if value not in STATE_MAP:
            violations.append("invalid_value:" + key)
        if key not in rows:
            violations.append("bound_row_missing:" + key)
        elif value in STATE_MAP and STATE_MAP[value] != _row_state(rows[key]):
            violations.append("key_row_mismatch:" + key)
        pattern = re.compile(r"^\|\s*" + re.escape(key) + r"\s*\|\s*`" + re.escape(key) + r"`\s*\|")
        if not any(pattern.match(line) for line in key_table):
            violations.append("binding_not_linked:" + key)
    codex_row = rows.get("codex_pipeline_procedure")
    if values.get("codex_pipeline_procedure") == "passed" and (codex_row is None or codex_row["measurement"] != "native live"):
        violations.append("codex_procedure_from_replay")
    if values.get("known_limitations_acknowledged") == "yes":
        adapter_lines = runtime_adapter.splitlines()
        if ADAPTER_LIMITS_HEADING not in adapter_lines or "strict_branch" not in runtime_adapter or "review-result" not in runtime_adapter:
            violations.append("known_limitations_without_adapter_limits")
        if not any(ADAPTER_LIMITS_LINK in line for line in key_table):
            violations.append("limitations_not_linked")
    verdict = values.get("verdict")
    if verdict not in ("publish", "do-not-publish"):
        violations.append("verdict_invalid")
    if verdict == "publish":
        for row_id in BR3_REQUIRED_ROWS:
            row = rows.get(row_id)
            if row is None or _row_state(row) != "PASS":
                violations.append("publish_with_nonpass_required_row:" + row_id)
            if row is None or not row["evidence"] or row["evidence"].startswith("not recorded"):
                violations.append("publish_without_inspected_evidence:" + row_id)
    return violations


def path_verdict_violations(text):
    lines = text.splitlines()
    try:
        start = lines.index("### Path verdicts")
    except ValueError:
        return ["missing_path_verdict:" + label for label in PATH_LABELS]
    body = _section(lines, start)
    violations = []
    for label in PATH_LABELS:
        matches = [line for line in body if line.startswith("- " + label + ":")]
        if len(matches) != 1:
            violations.append("missing_path_verdict:" + label)
            continue
        verdict = matches[0][len("- " + label + ":") :].strip()
        if verdict == "maintainer review pending -> no-go" or re.fullmatch(r"go \(maintainer review: https://\S+\)", verdict):
            continue
        if verdict.startswith("go"):
            violations.append("path_go_without_review:" + label)
        else:
            violations.append("missing_path_verdict:" + label)
    return violations


# --- synthetic ledger builder -------------------------------------------------------------------

GOOD_ADAPTER = ADAPTER_LIMITS_HEADING + "\n- `strict_branch` is the Codex branch report; `review-result` is Claude-only.\n"


def _row_line(row_id, state="not-run", measurement="static gate", evidence="not recorded (not-run)", commit="not recorded (not-run)"):
    br3 = "yes" if row_id in BR3_REQUIRED_ROWS else "no"
    identity = "not recorded (not-run)"
    model = "n/a"
    return f"| `{row_id}` | {br3} | {state} | {identity} | {commit} | not recorded (not-run) | not recorded (not-run) | {model} | {measurement} | {evidence} |"


def build_ledger(states=None, measurements=None, evidence=None, decision=None, heading="### Annotations to historical rows (2026-09-15)",
                 drop_rows=(), version_bullet=True, scans_bullet=True, path_lines=None):
    states = states or {}
    measurements = measurements or {}
    evidence = evidence or {}
    row_ids = list(BR3_REQUIRED_ROWS) + list(ANNOTATION_TARGET_ROWS)
    rows = [_row_line(r, states.get(r, "not-run"), measurements.get(r, "static gate"), evidence.get(r, "not recorded (not-run)"))
            for r in row_ids if r not in drop_rows]
    bullets = []
    if version_bullet:
        bullets.append("- **Version/changelog consistency**: contradicted by F5 (`README.md:250` read `0.4.2`); the current result is row `current_version_declarations` (AC85).")
    if scans_bullet:
        bullets.append("- **Public source and artifact scans**: scope was source and archive only, not Git history; the F4 finding is held by row `history_private_path_finding` (AC125).")
    decision = decision or {
        "version": "0.4.3",
        "scope": "Claude Code, Codex",
        "local_gate": "not-run",
        "claude_routing_eval": "not-run",
        "codex_routing_eval": "not-run",
        "claude_pipeline_procedure": "not-run",
        "codex_pipeline_procedure": "not-run",
        "secret_scan": "not-run",
        "known_limitations_acknowledged": "yes",
        "verdict": "do-not-publish",
    }
    if path_lines is None:
        path_lines = [f"- {label}: maintainer review pending -> no-go" for label in PATH_LABELS]
    parts = [
        "# Release evidence",
        "",
        "| Release requirement | Current result | Passing criterion |",
        "|---|---|---|",
        ORIGINAL_VERSION_ROW,
        ORIGINAL_SCANS_ROW,
        "",
        heading,
        "",
        *bullets,
        "",
        "## Required release rows",
        "",
        ROWS_HEADER,
        "|---|---|---|---|---|---|---|---|---|---|",
        *rows,
        "",
        "## Publication decision",
        "",
        "```text",
        *[f"{k}={v}" for k, v in decision.items()],
        "```",
        "",
        "| Key | Bound row |",
        "|---|---|",
        *[f"| {k} | `{k}` |" for k in STATE_KEYS],
        f"| known_limitations_acknowledged | {ADAPTER_LIMITS_LINK} |",
        "",
        "### Path verdicts",
        "",
        *path_lines,
        "",
    ]
    return "\n".join(parts)


def _pass_everything():
    states = {r: "PASS" for r in BR3_REQUIRED_ROWS}
    measurements = {r: "native live" for r in BR3_REQUIRED_ROWS}
    evidence = {r: "tests/artifacts/publication/x.json (inspected)" for r in BR3_REQUIRED_ROWS}
    decision = {
        "version": "0.4.3",
        "scope": "Claude Code, Codex",
        **{k: "passed" for k in STATE_KEYS},
        "known_limitations_acknowledged": "yes",
        "verdict": "publish",
    }
    return build_ledger(states=states, measurements=measurements, evidence=evidence, decision=decision)


def _decision(**overrides):
    base = {
        "version": "0.4.3",
        "scope": "Claude Code, Codex",
        "local_gate": "not-run",
        "claude_routing_eval": "not-run",
        "codex_routing_eval": "not-run",
        "claude_pipeline_procedure": "not-run",
        "codex_pipeline_procedure": "not-run",
        "secret_scan": "not-run",
        "known_limitations_acknowledged": "yes",
        "verdict": "do-not-publish",
    }
    base.update(overrides)
    return base


IDENTITY_CHECK_HEADING = "## Release identity check"
UTC_STAMP = re.compile(r"^- \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\b")
DEPENDENCY_CLAIM = "no skill relies on commands or agents"


def identity_check_violations(text):
    """Every bullet of the release identity check is a UTC-timestamped record of a run (plan Task 84, AC115)."""
    lines = text.splitlines()
    if IDENTITY_CHECK_HEADING not in lines:
        return ["missing_identity_check_section"]
    bullets = [line for line in _section(lines, lines.index(IDENTITY_CHECK_HEADING)) if line.startswith("- ")]
    violations = []
    if len(bullets) < 2:
        violations.append("missing_identity_recheck")
    for bullet in bullets:
        if not UTC_STAMP.match(bullet):
            violations.append("identity_check_without_utc_timestamp")
        if "not run" in bullet:
            violations.append("identity_check_not_run")
    return violations


def packet_dependency_violations(packet, skill_texts, command_names, agent_names):
    """The OpenAI packet states the no-commands/agents rule as a guide requirement and names each GAP."""
    violations = []
    for line in packet.splitlines():
        if DEPENDENCY_CLAIM in line.lower() and "requires" not in line:
            violations.append("dependency_claim_as_fact")
    gap_lines = [line for line in packet.splitlines() if "GAP" in line]
    joined = "\n".join(skill_texts)
    for name in command_names:
        if name in joined and not any(name in line for line in gap_lines):
            violations.append("missing_command_gap:" + name)
    for name in agent_names:
        if name in joined and not any(name in line for line in gap_lines):
            violations.append("missing_agent_gap:" + name)
    return violations


def _real(path):
    return (REPO / path).read_text(encoding="utf-8")


def _names(directory):
    return sorted(p.stem for p in (REPO / directory).glob("*.md") if p.stem.lower() != "readme")


def _skill_texts():
    return [p.read_text(encoding="utf-8") for p in sorted((REPO / "skills").rglob("*.md"))]


class TestLedgerAnnotations(unittest.TestCase):
    def test_annotation_rule_synthetic_cases(self):
        self.assertEqual(annotation_violations(build_ledger()), [])
        cases = [
            ("missing_annotation:version", build_ledger(version_bullet=False)),
            ("missing_annotation:scans", build_ledger(scans_bullet=False)),
            ("missing_annotation_section", build_ledger(heading="### Annotations to historical rows")),
            ("annotation_target_missing:current_version_declarations", build_ledger(drop_rows=("current_version_declarations",))),
            ("missing_original_row:version", build_ledger().replace(ORIGINAL_VERSION_ROW, ORIGINAL_VERSION_ROW.replace("PASS", "FAIL"))),
        ]
        for name, text in cases:
            with self.subTest(name=name):
                self.assertIn(name, annotation_violations(text))

    def test_real_ledger_carries_dated_annotations(self):
        self.assertEqual(annotation_violations(_real("docs/release-evidence-0.4.3.md")), [])

    def test_original_row_constants_match_5801cb9(self):
        present = subprocess.run(["git", "cat-file", "-e", ORIGINAL_LEDGER_BLOB], cwd=REPO, capture_output=True)
        if present.returncode != 0:
            self.skipTest(
                "the original 0.4.3 ledger blob 92b9c17 is not in this object store "
                "(shallow clone, extracted archive, or a history that does not contain it)"
            )
        proc = subprocess.run(
            ["git", "cat-file", "blob", ORIGINAL_LEDGER_BLOB],
            cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
        )
        lines = proc.stdout.splitlines()
        self.assertEqual(lines[11], ORIGINAL_VERSION_ROW)
        self.assertEqual(lines[18], ORIGINAL_SCANS_ROW)

    def test_annotation_cites_paragraphs_by_opening_words(self):
        self.assertEqual(paragraph_citation_violations(GOOD_CITATION_LEDGER), [])
        cases = [
            (
                "line_reference_without_5801cb9",
                GOOD_CITATION_LEDGER.replace('(the paragraph beginning "The release source excludes"; line 60 at 5801cb9)', "(paragraph at line 60)"),
            ),
            (
                "quoted_phrase_not_a_paragraph_start:release source excludes",
                GOOD_CITATION_LEDGER.replace('beginning "The release source excludes"', 'beginning "release source excludes"'),
            ),
        ]
        for name, text in cases:
            with self.subTest(name=name):
                self.assertIn(name, paragraph_citation_violations(text))
        self.assertEqual(paragraph_citation_violations(_real("docs/release-evidence-0.4.3.md")), [])


class TestRequiredRows(unittest.TestCase):
    def test_required_rows_parser_synthetic_cases(self):
        rows, violations = required_rows(build_ledger())
        self.assertEqual(violations, [])
        self.assertEqual(set(BR3_REQUIRED_ROWS) | set(ANNOTATION_TARGET_ROWS), set(rows))
        good = build_ledger()
        local = _row_line("local_gate")
        cases = [
            ("rows_header_mismatch", good.replace(ROWS_HEADER, ROWS_HEADER.replace("| Evidence |", "| Notes |"))),
            ("missing_required_row:owner_resume", build_ledger(drop_rows=("owner_resume",))),
            ("duplicate_row:local_gate", good.replace(local, local + "\n" + local)),
            ("br3_flag_mismatch:local_gate", good.replace(local, local.replace("| `local_gate` | yes |", "| `local_gate` | no |"))),
            ("invalid_state:local_gate", build_ledger(states={"local_gate": "clean"})),
            ("invalid_measurement:local_gate", build_ledger(measurements={"local_gate": "static history precheck"})),
            ("unbound_row:local_gate", good.replace(local, local.replace("| not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) |", "| not recorded (not-run) |  | not recorded (not-run) | not recorded (not-run) |"))),
        ]
        for name, text in cases:
            with self.subTest(name=name):
                self.assertIn(name, required_rows(text)[1])

    def test_real_required_rows_table_is_complete(self):
        rows, violations = required_rows(_real("docs/release-evidence-0.4.3.md"))
        self.assertEqual(violations, [])
        for row_id in ANNOTATION_TARGET_ROWS:
            self.assertIn(row_id, rows)


class TestDecisionBlock(unittest.TestCase):
    def test_decision_block_rule_synthetic_cases(self):
        self.assertEqual(decision_block_violations(build_ledger(), "0.4.3", GOOD_ADAPTER), [])
        self.assertEqual(decision_block_violations(_pass_everything(), "0.4.3", GOOD_ADAPTER), [])
        missing_secret = _decision()
        del missing_secret["secret_scan"]
        cases = [
            ("publish_with_nonpass_required_row:local_gate", build_ledger(decision=_decision(verdict="publish")), GOOD_ADAPTER, "0.4.3"),
            ("key_row_mismatch:local_gate", build_ledger(decision=_decision(local_gate="passed")), GOOD_ADAPTER, "0.4.3"),
            ("keys_mismatch", build_ledger(decision=missing_secret), GOOD_ADAPTER, "0.4.3"),
            ("invalid_value:secret_scan", build_ledger(decision=_decision(secret_scan="clean")), GOOD_ADAPTER, "0.4.3"),
            ("version_mismatch", build_ledger(decision=_decision(version="0.4.2")), GOOD_ADAPTER, "0.4.3"),
            ("scope_mismatch", build_ledger(decision=_decision(scope="Claude Code")), GOOD_ADAPTER, "0.4.3"),
            ("known_limitations_without_adapter_limits", build_ledger(), "no limits heading here", "0.4.3"),
            (
                "codex_procedure_from_replay",
                build_ledger(states={"codex_pipeline_procedure": "PASS"}, measurements={"codex_pipeline_procedure": "deterministic replay"},
                             decision=_decision(codex_pipeline_procedure="passed")),
                GOOD_ADAPTER,
                "0.4.3",
            ),
            ("verdict_invalid", build_ledger(decision=_decision(verdict="ship")), GOOD_ADAPTER, "0.4.3"),
            ("binding_not_linked:secret_scan", build_ledger().replace("| secret_scan | `secret_scan` |", "| secret_scan | see table |"), GOOD_ADAPTER, "0.4.3"),
            ("limitations_not_linked", build_ledger().replace(f"| known_limitations_acknowledged | {ADAPTER_LIMITS_LINK} |", "| known_limitations_acknowledged | adapter |"), GOOD_ADAPTER, "0.4.3"),
            ("decision_block_missing", build_ledger().replace("```text", "text"), GOOD_ADAPTER, "0.4.3"),
            (
                "publish_without_inspected_evidence:local_gate",
                _pass_everything().replace(
                    "| native live | tests/artifacts/publication/x.json (inspected) |\n| `claude_routing_eval`",
                    "| native live | not recorded (lost) |\n| `claude_routing_eval`",
                ),
                GOOD_ADAPTER,
                "0.4.3",
            ),
        ]
        for name, text, adapter, version in cases:
            with self.subTest(name=name):
                self.assertIn(name, decision_block_violations(text, version, adapter))

    def test_release_verdict_template_uses_decision_values(self):
        lines = _real("docs/release-readiness.md").splitlines()
        start = lines.index("## Release Verdict Template")
        fence_start = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == "```text")
        fence_end = next(i for i in range(fence_start + 1, len(lines)) if lines[i].strip() == "```")
        pairs = [line.split("=", 1) for line in lines[fence_start + 1 : fence_end] if line.strip()]
        self.assertEqual(tuple(pair[0] for pair in pairs), DECISION_KEYS)
        values = {pair[0]: pair[1] for pair in pairs}
        version = _real("VERSION").strip()
        self.assertEqual(values["version"], version)
        self.assertEqual([line for line in lines if line.startswith("version=")], ["version=" + version])
        self.assertEqual(values["scope"], "Claude Code, Codex")

        def offered(key):
            # The whole value is one `<a|b|...>` choice; nothing may follow the closing `>`.
            match = re.fullmatch(r"<([^<>]*)>", values[key])
            self.assertIsNotNone(match, f"{key}={values[key]}")
            return match.group(1).split("|")

        for key in STATE_KEYS:
            with self.subTest(key=key):
                self.assertEqual(sorted(offered(key)), sorted(STATE_MAP))
        self.assertEqual(offered("known_limitations_acknowledged"), ["yes", "no"])
        self.assertEqual(offered("verdict"), ["publish", "do-not-publish"])

    def test_real_decision_block_is_bound_to_rows(self):
        version = _real("VERSION").strip()
        violations = decision_block_violations(_real("docs/release-evidence-0.4.3.md"), version, _real("docs/runtime-adapter.md"))
        self.assertEqual(violations, [])

    def test_path_verdict_rule_synthetic_cases(self):
        self.assertEqual(path_verdict_violations(build_ledger()), [])
        reviewed = [f"- {label}: maintainer review pending -> no-go" for label in PATH_LABELS[:3]]
        reviewed.append("- OpenAI public directory: go (maintainer review: https://example.invalid/review/1)")
        self.assertEqual(path_verdict_violations(build_ledger(path_lines=reviewed)), [])
        go_without = [f"- {label}: maintainer review pending -> no-go" for label in PATH_LABELS[:3]] + ["- OpenAI public directory: go"]
        self.assertIn("path_go_without_review:OpenAI public directory", path_verdict_violations(build_ledger(path_lines=go_without)))
        missing = [f"- {label}: maintainer review pending -> no-go" for label in PATH_LABELS[1:]]
        self.assertIn("missing_path_verdict:Claude own marketplace", path_verdict_violations(build_ledger(path_lines=missing)))

    def test_real_path_verdicts_are_no_go_or_reviewed(self):
        self.assertEqual(path_verdict_violations(_real("docs/release-evidence-0.4.3.md")), [])


GOOD_IDENTITY_CHECK = "\n".join(
    [
        "## Release identity check",
        "",
        "- 2026-09-14T19:56:26Z: 0 remote tags; no collision.",
        "- 2026-09-16T18:36:39Z re-check: 0 remote tags, 0 GitHub releases; no collision.",
        "",
        "## Required release rows",
    ]
)


class TestReleaseIdentityCheck(unittest.TestCase):
    def test_identity_check_rule_synthetic_cases(self):
        self.assertEqual(identity_check_violations(GOOD_IDENTITY_CHECK), [])
        undated = GOOD_IDENTITY_CHECK.replace("- 2026-09-16T18:36:39Z re-check: 0 remote tags", "- 2026-09-16 re-check: 0 remote tags")
        cases = [
            ("missing_identity_check_section", GOOD_IDENTITY_CHECK.replace("## Release identity check", "## Identity")),
            ("missing_identity_recheck", GOOD_IDENTITY_CHECK.replace("- 2026-09-16T18:36:39Z re-check: 0 remote tags, 0 GitHub releases; no collision.\n", "")),
            ("identity_check_without_utc_timestamp", undated),
            ("identity_check_not_run", GOOD_IDENTITY_CHECK.replace("0 remote tags, 0 GitHub releases", "not run, no network")),
        ]
        for name, text in cases:
            with self.subTest(name=name):
                self.assertIn(name, identity_check_violations(text))

    def test_real_identity_check_records_a_dated_recheck(self):
        self.assertEqual(identity_check_violations(_real("docs/release-evidence-0.4.3.md")), [])


class TestOpenAIPacketDependencies(unittest.TestCase):
    GOOD = "\n".join(
        [
            "- The OpenAI guide requires that no skill relies on commands or agents (link).",
            "- GAP: pipeline step 16 names the `git-safety-check` command; skills name `code-reviewer` roles.",
        ]
    )
    SKILLS = ["Run the read-only git-safety-check command.", "Delegate to the code-reviewer agent."]

    def test_packet_dependency_rule_synthetic_cases(self):
        args = (self.SKILLS, ["git-safety-check"], ["code-reviewer"])
        self.assertEqual(packet_dependency_violations(self.GOOD, *args), [])
        fact = "- It has no MCP configuration, and no skill relies on commands or agents (link)."
        cases = [
            ("dependency_claim_as_fact", fact + "\n" + self.GOOD.splitlines()[1]),
            ("missing_command_gap:git-safety-check", self.GOOD.replace("`git-safety-check` command", "a command")),
            ("missing_agent_gap:code-reviewer", self.GOOD.replace("`code-reviewer` roles", "agent roles")),
        ]
        for name, text in cases:
            with self.subTest(name=name):
                self.assertIn(name, packet_dependency_violations(text, *args))
        self.assertEqual(packet_dependency_violations("no GAP needed", ["plain skill"], ["git-safety-check"], ["code-reviewer"]), [])

    def test_real_openai_packet_names_command_and_agent_gaps(self):
        violations = packet_dependency_violations(
            _real("docs/publication/openai-skills-only.md"), _skill_texts(), _names("commands"), _names("agents")
        )
        self.assertEqual(violations, [])

    def test_packet_names_skills_only_follow_up_owner(self):
        lines = _real("docs/publication/openai-skills-only.md").splitlines()
        owners = [line for line in lines if all(token in line for token in ("Owner:", "maintainer", "step 16"))]
        self.assertTrue(owners, "the OpenAI packet names no owner for the step 16 skills-only follow-up")


if __name__ == "__main__":
    unittest.main()
