"""Deterministic spec/plan artifact validator.

Why this exists: a spec/plan gate should be machine-checkable, not a matter of
taste. This script reads a markdown artifact and emits sorted flat `key=value`
lines so the result is diffable, greppable, and stable across runs. It is the
deterministic counterpart to the adversarial `spec-plan-draft` loop.

Design constraints (from the approved plan):
- Pure stdlib only (argparse, json, re, pathlib, sys). No third-party imports.
- Read-only: no file writes, no shell, no path traversal beyond the given file.
- Secrets are MASKED, never printed — the value that tripped a pattern is
  replaced with ***MASKED*** so the validator can't become a leak channel.

Output contract:
- `emit()` prints sorted `key=value` lines, including `mode=<mode>` and
  `artifacts_validation=passed|failed`.
- `main()` returns exit 1 if any errors, else 0.
- `--strict` promotes every `warning=` to `error=` (warnings become gating).
- `run(mode, file, spec, strict, design_path, check_path, sources, feedback_path, feedback_gates)`
  returns `(exit_code, fields)`. An artifact it cannot read is an error (`file_unreadable:<reason>`,
  `spec_unreadable:<reason>`, `design_unreadable:<reason>`, `check_unreadable:<reason>`), never an
  exception, so a caller that imports it gets a failed gate rather than a traceback. A feedback log
  it cannot read names no record, so each `F<n>` token is then an unknown source.
- Modes: `spec`, `plan`, `all`, and `design` (the intent step's `design.md`: four sections and
  decisions that carry an id and an owner). `--sources` makes every acceptance criterion of a spec,
  or of a spec-less plan, name where it came from (`(source: request, D1, Q2, F3)`).
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Required spec and design sections. The key is the canonical slug emitted in messages; the
# value is the substring we look for inside a heading (case-insensitive, after
# stripping numbering and trailing parentheticals). Order is irrelevant — we
# report by slug.
REQUIRED_DESIGN_SECTIONS = {
    "intent": "intent",
    "non-goals": "non-goals",
    "approaches": "approaches",
    "decisions": "decisions",
}

REQUIRED_SPEC_SECTIONS = {
    "problem": "problem",
    "business-rules": "business rules",
    "acceptance-criteria": "acceptance criteria",
    "edge-cases": "edge cases",
    "definition-of-done": "definition of done",
    "must-not-change": "must-not-change",
}

# A section whose body has fewer non-blank characters than this is thin (`thin_section:<slug>`).
THIN_SECTION_CHARS = 40

# A criterion is considered testable if it states an input->output relation or a
# concrete outcome. Cheap heuristic, but it catches the "should work well" class.
TESTABLE_MARKERS = re.compile(r"\b(given|when|then|returns|exit)\b|->|=>", re.IGNORECASE)

PLACEHOLDER_RE = re.compile(r"\b(TODO|TBD|FIXME|XXX)\b")

# DP-3: explicit secret patterns only — NO entropy detector. Each pattern is kept
# narrow so high-entropy prose (build hashes, correlation ids) does not fire.
# Provider-prefix tokens mirror hooks/secret-patterns.mjs (HIGH) so this validator and the
# commit/write guards recognize the same modern formats — keep the two lists in sync.
SECRET_PATTERNS = [
    re.compile(r"api[_-]?key\s*[:=]", re.IGNORECASE),
    re.compile(r"secret\s*[:=]", re.IGNORECASE),
    re.compile(r"password\s*[:=]", re.IGNORECASE),
    re.compile(r"token\s*[:=]\s*\S{12,}", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?:gh[posru]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40,})"),
    re.compile(r"(?:xox[baprs]|xapp)-[A-Za-z0-9-]{10,}", re.IGNORECASE),
    re.compile(r"(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9]{20,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
]

# A heading line: one-or-more '#' then text. We also accept the task forms below.
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*\S)\s*$")

# Plan task-block detectors. A task block starts at EITHER:
#   - a markdown heading whose text starts with "Task" ("## Task 3 — ..."), OR
#   - a T-id at the head of a line, after bullet/bold/heading marks ("- **T1 — ...**").
# Deliberately NOT a bare numbered list item ("1." is usually a decision point or a
# coverage note, not a task) and NOT a mid-prose ref ("AC1→T7" in a coverage line) —
# both over-counted real plans in dogfooding. The task convention is therefore
# "## Task N" headings or line-leading "TN" markers.
#
# Every numbered id this module reads (task `T<n>`, criterion `AC<n>`, decision `D<n>`, question
# `Q<n>`, feedback record `F<n>`) has 1 to ID_DIGITS digits. A longer run of digits is no id, so it is
# reported like any other malformed token instead of reaching int(), which refuses more than 4300 digits.
ID_DIGITS = 6
TASK_HEADING_RE = re.compile(r"^\s{0,3}#{2,4}\s*Task\b", re.IGNORECASE)
TASK_TID_RE = re.compile(r"\bT\d{1,%d}\b" % ID_DIGITS)
TASK_TID_START_RE = re.compile(r"^[\s>*\-#]*\*{0,2}\s*(T\d{1,%d})\b" % ID_DIGITS)

# An acceptance-criterion id: `AC1`, `AC-1`, or a grouped `AC-A1` (pipeline specs use all three).
# `AC1` and `AC-1` name the same criterion, so ids are compared by `_ac_key`, never by spelling.
# The group letter needs the hyphen, so a word such as `ACE2` is not an id.
AC_ID_RE = re.compile(r"\bAC(?:-?(\d{1,%d})|-([A-Z])(\d{1,%d}))\b" % (ID_DIGITS, ID_DIGITS))


def _ac_key(match):
    """('', 1) for `AC1`/`AC-1`/`AC01`; ('A', 1) for `AC-A1`."""
    if match.group(1) is not None:
        return ("", int(match.group(1)))
    return (match.group(2), int(match.group(3)))

FILE_REF_RE = re.compile(r"\b(Create|Modify)\b", re.IGNORECASE)
TDD_MARKER_RE = re.compile(r"\b(TDD|RED|failing test)\b", re.IGNORECASE)

# Quality checks (warnings; --strict promotes to errors). No count floors — these
# are calibrated by the regression fixtures: a genuinely deep artifact must stay
# clean, only stubs / deferrals / hand-wave trip them.
#
# A task carries a real verification if it shows a runnable signal: a "Run:" /
# "Verify:" / "Expect:" lead-in, an inline-code command (pytest/python/npm/...),
# or a fenced code block (the command/RED->GREEN expectation).
VERIFICATION_RE = re.compile(r"(?im)^\s*(?:run:|verify:|expect:)|`[^`]*\b(?:pytest|python|npm|cargo|go test|make)\b|```")
# A deferral hand-wave: a "Non-task step" pseudo-task, or "executed later/after ...
# gates" that pushes real work out of the plan instead of making it a task.
DEFERRAL_RE = re.compile(r"(?i)\bnon-task step\b|executed (?:later|after)[^.\n]*\bgates?\b")
# A security section exists when a heading mentions security; it is hand-wave when
# its body is only a bare dismissal ("no untrusted input", "safe string handling only").
SECURITY_HEADING_RE = re.compile(r"(?i)\bsecurity\b")
SECURITY_HANDWAVE_RE = re.compile(r"(?i)\bno untrusted input\b|\bsafe string handling only\b|\btreat (?:it|this|the change) as safe\b")


def _normalize_heading(text):
    """Strip leading '\\d+.' numbering and trailing '(...)' parentheticals.

    Why: real headings look like '## 7. Must-not-change (regression surface)'.
    We want a case-insensitive CONTAINS match on the meaningful core, so a
    numbered, annotated heading is still detected (resolves RN2).
    """
    t = text.strip()
    # Drop a leading numbering like "7." or "7.3." possibly repeated.
    t = re.sub(r"^(?:\d+\.)+\s*", "", t)
    # Drop a single trailing parenthetical group.
    t = re.sub(r"\s*\([^()]*\)\s*$", "", t)
    return t.strip().lower()


def _iter_headings(text):
    """Yield (lineno, raw_text, normalized_text) for every markdown heading."""
    for i, line in enumerate(text.splitlines(), start=1):
        m = HEADING_RE.match(line)
        if m:
            raw = m.group(1)
            yield i, raw, _normalize_heading(raw)


def _section_body(text, start_lineno):
    """Return the non-heading body text between a heading and the next heading."""
    lines = text.splitlines()
    body = []
    for line in lines[start_lineno:]:  # start_lineno is 1-based; slice skips the heading
        if HEADING_RE.match(line):
            break
        body.append(line)
    return "\n".join(body)


def _bullet_blocks(body):
    """[(index, line, nested, text)] for each bullet of a section body.

    The index is the bullet's 1-based position: `untestable_criterion:<n>` and
    `ac_missing_id:<n>` name the same bullet by it. `nested` is True for a bullet indented
    under another one. `line` is the bullet's first line; `text` adds the indented lines that
    continue it (a blank line does not end a bullet, an unindented line of prose does), so a tag
    wrapped onto the next line still belongs to its bullet. A nested bullet is a block of its own
    and never adds to the bullet above it.
    """
    blocks = []
    current = None
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        indent = line[:len(line) - len(line.lstrip())]
        if stripped.startswith(("-", "*")) or re.match(r"^\d+\.", stripped):
            blocks.append([len(blocks) + 1, stripped, "\t" in indent or len(indent) >= 2, stripped])
            current = blocks[-1]
        elif indent and current is not None:
            current[3] += "\n" + stripped
        else:
            current = None
    return [tuple(block) for block in blocks]


def _criterion_bullets(body):
    """[(index, line, nested)] for each bullet of a criteria section body (see `_bullet_blocks`)."""
    return [(index, line, nested) for index, line, nested, _text in _bullet_blocks(body)]


def _acceptance_criteria(text):
    """Return [(index, line, nested)] for each bullet of the first acceptance-criteria section.

    No section means no criteria.
    """
    needle = REQUIRED_SPEC_SECTIONS["acceptance-criteria"]
    for lineno, _raw, norm in _iter_headings(text):
        if needle in norm:
            return _criterion_bullets(_section_body(text, lineno))
    return []


def _unlabelled(criteria):
    """Indexes of the criteria the plan gate cannot check: a top-level bullet that reads as a
    criterion (it has a testable marker) and carries no `AC<n>` id.

    Real pipeline specs put a bold group heading, or a nested "Guards:"/"Variant:" line, inside the
    section. Neither is a criterion of its own, so neither is reported here. A top-level detail
    bullet that happens to say "when" still is, which is why only the criteria sources use this:
    the spec check, and a spec-less plan's own section (no spec check runs there).
    """
    return [index for index, line, nested in criteria
            if not nested and TESTABLE_MARKERS.search(line) and not AC_ID_RE.search(line)]


def _unlabelled_criteria(text):
    """`_unlabelled` over the first acceptance-criteria section of `text`."""
    return _unlabelled(_acceptance_criteria(text))


# Frontmatter the pipeline gates on. These MIRROR scripts/resolve_work_package.py, which
# rejects an artifact outright when one of its keys is missing or its status is unknown.
#
# Mirrored rather than imported: this validator is invoked standalone from the skills on both
# runtimes, and importing the resolver would pull its git and filesystem behaviour into a
# check that should only read one file. tests/test_validator_resolver_parity.py is what keeps
# the two copies equal - a divergence there is a failing test rather than a false green.
#
# They are ERRORS, not warnings promoted by --strict: a key whose absence is unconditionally
# fatal downstream is not a style preference. This gate used to parse no frontmatter at all,
# so it reported `artifacts_validation=passed` on a plan the suite then rejected with
# `plan_missing:branch`.
#
# Path semantics stay with the resolver: presence of `spec:` is checked here, where it points
# is not, because resolving it needs a repository root this tool does not take.
FRONTMATTER_REQUIRED = {
    "spec": ("work_id", "status"),
    "plan": ("work_id", "spec", "branch", "status"),
}
FRONTMATTER_STATUSES = {"draft", "reviewed", "approved", "in_progress", "ready_for_audit", "complete"}

# Spec-less plans (design §5.19; a plan outside bugfix since the hybrid spec/plan design). A plan is
# one only when its frontmatter carries BOTH `spec: none` and a `flow:` in SPECLESS_FLOWS;
# `spec: none` with any other flow is an error (`spec_none_requires_specless_flow`), so a refactor
# plan cannot drop its spec by writing `none`. Only a bugfix plan also needs a `## Bug` section. A
# spec-less plan given a spec anyway is an error too (`spec_none_with_spec`): the artifact under
# test must not decide whether the caller's spec is checked. Mirrored in
# scripts/resolve_work_package.py, which reports the same codes (there: a spec file in the plan's
# package); tests/test_validator_resolver_parity.py runs both on one fixture set.
SPEC_NONE = "none"
BUGFIX_FLOW = "bugfix"
SPECLESS_FLOWS = (BUGFIX_FLOW, "feature", "plan")

# A frontmatter value is echoed in an error only when it is a short lowercase word, the shape of a
# status. Anything else could be a pasted credential, so it is printed masked. A word may use any
# script (`hazır`); digits, uppercase and spaces are not part of a word here.
ECHOABLE_VALUE_RE = re.compile(r"^[^\W\d_](?:[^\W\d]|-){0,23}\Z")  # a letter, then letters, `_` or `-`


def _frontmatter_block(text):
    """(meta, errors) for the leading `---` block; ({}, []) when there is none.

    Only a block that OPENS ON THE FIRST LINE counts. Scanning for `---` anywhere would let a
    fenced example, a horizontal rule, or a document that merely discusses frontmatter satisfy
    the check from outside the block. The delimiters are whole lines: `---` with nothing before
    it (trailing spaces aside), so an indented `---` or a `----` line is neither opener nor closer.
    An unterminated block is not frontmatter.

    Deliberately not a YAML parser: `key: value` on one line, matching what the resolver reads
    and what the skills tell authors to write. Blank lines and `#` comment lines are skipped; any
    other line without a `:` or with an empty key is `invalid_frontmatter_line:<file line>`, as
    the resolver reports it, rather than a line one tool skips and the other rejects. Surrounding
    quotes are dropped the way the resolver drops them, so `status: "approved"` is `approved` to
    both tools rather than a gate failure the resolver would never report.
    """
    lines = text.splitlines()
    end = _frontmatter_end(lines)
    if end is None:
        return {}, []                            # no block, or an unterminated one: not frontmatter
    meta = {}
    errors = []
    for lineno, raw in enumerate(lines[1:end], start=2):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep or not key.strip():
            errors.append(f"invalid_frontmatter_line:{lineno}")
            continue
        meta[key.strip()] = value.strip().strip("\"'")
    return meta, errors


def _frontmatter_end(lines):
    """Index of the line that closes a block opening on `lines[0]`; None without a terminated block.

    `lines` may keep their line breaks: a delimiter is `---` once trailing whitespace is stripped.
    """
    if not lines or lines[0].rstrip() != "---":
        return None
    return next((i for i in range(1, len(lines)) if lines[i].rstrip() == "---"), None)


def _body(text):
    """The text after the block `_frontmatter_block` reads; the whole text when there is none.

    Headings, sections, tasks and AC ids are read from here only. Inside the block a `#` line is a
    comment and `- AC1: ...` is a `key: value` line, so neither may count as a heading, a task or a
    criterion; the runner's body fingerprint ignores the block too, so an edit confined to the
    block never changes a body verdict. The placeholder and secret scan still reads every line.
    """
    lines = text.splitlines(keepends=True)
    end = _frontmatter_end(lines)
    return text if end is None else "".join(lines[end + 1:])


def parse_frontmatter(text):
    """Return the leading `---` block as a dict, or {} when there is none (see `_frontmatter_block`)."""
    return _frontmatter_block(text)[0]


def _echo_value(value):
    """`value` when it is safe to print in an error line, else the mask."""
    if (ECHOABLE_VALUE_RE.match(value) and value == value.lower()
            and not any(pat.search(value) for pat in SECRET_PATTERNS)):
        return value
    return _mask(value)


def is_bugfix_plan(meta):
    """True for a spec-less bugfix plan: `flow: bugfix` together with `spec: none`."""
    return meta.get("spec") == SPEC_NONE and meta.get("flow") == BUGFIX_FLOW


def is_specless_plan(meta):
    """True for a plan that carries its own criteria: `spec: none` with a `flow:` in SPECLESS_FLOWS."""
    return meta.get("spec") == SPEC_NONE and meta.get("flow") in SPECLESS_FLOWS


def check_plan_kind(meta):
    """`spec: none` is accepted only with a spec-less flow; the resolver reports the same code."""
    if meta.get("spec") == SPEC_NONE and meta.get("flow") not in SPECLESS_FLOWS:
        return ["spec_none_requires_specless_flow"]
    return []


def check_frontmatter(text, mode):
    """Errors for the required keys of `mode`. An empty value counts as missing.

    An unknown status is named only when it is a plain word (`invalid_status:wip`); any other
    value is masked, so the gate never echoes a credential pasted into the frontmatter.
    """
    required = FRONTMATTER_REQUIRED.get(mode)
    if not required:
        return []
    meta, errors = _frontmatter_block(text)
    errors = errors + [f"missing_frontmatter_key:{key}" for key in required if not meta.get(key)]
    status = meta.get("status")
    if status and status not in FRONTMATTER_STATUSES:
        errors.append(f"invalid_status:{_echo_value(status)}")
    return errors


# A decision of `design.md`: a top-level bullet of the Decisions section that starts with `D<n>`
# (after the bullet mark and any bold or italic marks). Its owner is `(user)` or
# `(author's call: <reason>)`, with a straight or a typographic apostrophe and a reason in any script.
DECISION_ID_RE = re.compile(r"^D(\d{1,%d})\b" % ID_DIGITS)
DECISION_OWNER_RE = re.compile(r"\((?:user|author['\u2019]s call:\s*[^)\s][^)]*)\)", re.IGNORECASE)

# A criterion's origin: `(source: request, D1, Q2, F3)`, searched in the bullet's whole text. A token
# is `request`, a decision `D<n>` of design.md, a question `Q<n>` of the spec's check file, or a
# feedback record `F<n>`: the user's change request at a gate, the `reject` record whose `seq` is n in
# the package's feedback.jsonl.
SOURCE_TAG_RE = re.compile(r"\(source:([^)]*)\)", re.IGNORECASE)
SOURCE_TOKEN_RE = re.compile(r"^(?:request|([DQF])(\d{1,%d}))\Z" % ID_DIGITS)
CHECK_QUESTION_ID_RE = re.compile(r"^Q(\d{1,%d})\Z" % ID_DIGITS)
SOURCE_REQUEST = "request"
FEEDBACK_REJECT = "reject"


def _clean_text(text):
    """`text` without a leading byte-order mark (a file saved by an editor that adds one)."""
    return text[1:] if text.startswith("\ufeff") else text


def _section_text(text, needle):
    """The body of the first section whose heading holds `needle`; None when there is none."""
    for lineno, _raw, norm in _iter_headings(text):
        if needle in norm:
            return _section_body(text, lineno)
    return None


def _design_decisions(design_text):
    """[(index, id or None, text)] for each top-level bullet of the Decisions section of a design.

    `id` is the id as written (`D1`, `D01`); it is None for a bullet that does not start with one.
    No Decisions section means no decisions.
    """
    body = _section_text(_body(_clean_text(design_text)), REQUIRED_DESIGN_SECTIONS["decisions"])
    decisions = []
    for index, line, nested, text in _bullet_blocks(body or ""):
        if nested:
            continue
        label = re.sub(r"^(?:[-*]|\d+\.)\s*", "", line).lstrip("*_` ")
        match = DECISION_ID_RE.match(label)
        decisions.append((index, match.group(0) if match else None, text))
    return decisions


def _decision_key(decision_id):
    """`D1` and `D01` name the same decision."""
    return int(decision_id[1:])


def check_design(text):
    """Validate a `design.md`. Returns {'errors': [...], 'warnings': [...]}.

    Errors: a required section is absent (`missing_section:<slug>`: intent, non-goals,
    approaches, decisions); a top-level bullet of Decisions does not start with `D<n>`
    (`decision_missing_id:<index>`, the bullet's 1-based position among the section's bullets); two
    decisions share an id (`decision_duplicate_id:D<n>`, `D01` and `D1` being the same id); a
    decision carries neither `(user)` nor `(author's call: <reason>)` anywhere in its text
    (`decision_missing_owner:D<n>`).

    A byte-order mark and CRLF line ends are tolerated. Only the body after the frontmatter block
    is read (`_body`).
    """
    errors = []
    text = _body(_clean_text(text))
    for slug, needle in REQUIRED_DESIGN_SECTIONS.items():
        if _section_text(text, needle) is None:
            errors.append(f"missing_section:{slug}")
    seen = set()
    for index, decision_id, decision_text in _design_decisions(text):
        if decision_id is None:
            errors.append(f"decision_missing_id:{index}")
            continue
        if _decision_key(decision_id) in seen:
            errors.append(f"decision_duplicate_id:{decision_id}")
        seen.add(_decision_key(decision_id))
        if not DECISION_OWNER_RE.search(decision_text):
            errors.append(f"decision_missing_owner:{decision_id}")
    return {"errors": errors, "warnings": []}


def _check_questions(check_data):
    """The set of question numbers a check file names: `{1, 2}` for ids `Q1`, `Q2`."""
    found = set()
    for question in (check_data or {}).get("questions") or []:
        match = CHECK_QUESTION_ID_RE.match(str(question.get("id", ""))) if isinstance(question, dict) else None
        if match:
            found.add(int(match.group(1)))
    return found


def _feedback_numbers(feedback_text, gates=None):
    """The `seq` numbers a token `F<n>` may name: each `reject` record of a feedback log whose `gate`
    is one of `gates` (any gate when `gates` is empty or None).

    The log is JSON Lines, as the runner writes it, split the way the runner reads it (sdlc_runner/logs):
    on LF only, one trailing CR dropped. A quote is stored as it is, so a Unicode line break inside it
    (U+2028, U+2029, U+0085) is part of its record, never the end of a line. A line that is not a JSON
    object, and a record whose `seq` is not an integer, names nothing: the runner's own log checks guard
    the hash chain, so this reader skips what it cannot use and never raises. No text (no log, or one
    that could not be read) names nothing.
    """
    allowed = set(gates or ())
    found = set()
    for line in _clean_text(feedback_text or "").split("\n"):
        if line.endswith("\r"):
            line = line[:-1]
        try:
            record = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if not isinstance(record, dict) or record.get("kind") != FEEDBACK_REJECT:
            continue
        gate = record.get("gate")
        if allowed and not (isinstance(gate, str) and gate in allowed):
            continue
        seq = record.get("seq")
        if isinstance(seq, int) and not isinstance(seq, bool):
            found.add(seq)
    return found


def _sourced_criteria(blocks):
    """[(id match, tokens)] for each criterion among `blocks` (`_bullet_blocks`).

    A criterion is a top-level bullet that carries an AC id. Its tag is searched in the bullet's whole
    text (its first line and its indented continuation lines, not nested bullets); the tokens are the
    comma-separated parts of every tag, stripped, empty ones left out. The source check and the
    runner's gate card (`criterion_sources`) both read the criteria through here.
    """
    found = []
    for _index, line, nested, text in blocks:
        match = AC_ID_RE.search(line)
        if nested or not match:
            continue
        tokens = [token.strip() for tag in SOURCE_TAG_RE.findall(text) for token in tag.split(",")]
        found.append((match, [token for token in tokens if token]))
    return found


def _source_errors(blocks, decisions, questions, counted_text, feedback=frozenset()):
    """Errors for the criteria among `blocks` (`_bullet_blocks`) that do not name a known source.

    The criteria and their tokens are those of `_sourced_criteria`. `decisions`, `questions` and
    `feedback` are the numbers a token `D<n>` / `Q<n>` / `F<n>` may name; an empty set makes every
    such token unknown. `ac_no_source` (no tag, or a tag without a token), `ac_bad_source` (a token
    that is none of the four forms), `ac_unknown_source` (a well-formed token that names nothing),
    each followed by the criterion's id as written and, for the last two, the token.

    `counted_text` is the text the plan coverage takes its ids from (`_ac_coverage`). Each id there
    that is not the id of one of those top-level bullets is `ac_no_source:<id>` too: a criterion under
    a group bullet, in a table, in a heading or in another section is still one the plan must build,
    so formatting cannot take it out of the source rule.
    """
    errors = []
    bullet_keys = set()
    known = {"D": decisions, "Q": questions, "F": feedback}
    for match, tokens in _sourced_criteria(blocks):
        bullet_keys.add(_ac_key(match))
        ac = match.group(0)
        if not tokens:
            errors.append(f"ac_no_source:{ac}")
        for token in tokens:
            parsed = SOURCE_TOKEN_RE.match(token)
            if not parsed:
                errors.append(f"ac_bad_source:{ac}:{token}")
            elif parsed.group(1) and int(parsed.group(2)) not in known[parsed.group(1)]:
                errors.append(f"ac_unknown_source:{ac}:{token}")
    counted = {}
    for match in AC_ID_RE.finditer(counted_text):
        counted.setdefault(_ac_key(match), match.group(0))
    errors += [f"ac_no_source:{counted[key]}" for key in sorted(counted) if key not in bullet_keys]
    return errors


def _unfenced(text):
    """`text` without its fenced code lines (see `_fenced_lines`): a bullet in an example is no criterion."""
    lines = text.splitlines()
    fenced = _fenced_lines(lines)
    return "\n".join(line for i, line in enumerate(lines) if i not in fenced)


def _criteria_section(text):
    """The body of the first acceptance-criteria section of a spec body, None when there is none.

    It runs to the next heading of the same or a higher level, so a `### Login` sub-heading stays
    inside it; headings in code fences do not count. A spec-less plan's section is read the same way
    (`_own_criteria_sections`).
    """
    lines = text.splitlines()
    fenced = _fenced_lines(lines)
    headings = []  # (line_index, normalized text, level)
    for i, line in enumerate(lines):
        match = HEADING_RE.match(line)
        if match and i not in fenced:
            headings.append((i, _normalize_heading(match.group(1)), _heading_level(line)))
    needle = REQUIRED_SPEC_SECTIONS["acceptance-criteria"]
    section = next(((i, level) for i, norm, level in headings if needle in norm), None)
    if section is None:
        return None
    at, level = section
    end = next((i for i, _norm, lvl in headings if i > at and lvl <= level), len(lines))
    return "\n".join(lines[at + 1:end])


def _decision_numbers(design_text):
    """The decision numbers a design names; none without a design."""
    if design_text is None:
        return set()
    return {_decision_key(decision_id) for _index, decision_id, _text in _design_decisions(design_text) if decision_id}


def criterion_sources(text, mode):
    """[(id, [token, ...])] for each criterion the source check reads in an artifact, the id and the
    tokens as written; a criterion without a tag has no token.

    `mode` `spec`: the top-level bullets of the spec's acceptance-criteria section (`_criteria_section`).
    `plan`: those of a spec-less plan's own section (`_own_criteria_sections`); a plan checked against a
    spec has no criteria of its own, so it has none. Any other mode has none. The criteria and their
    tokens come from `_sourced_criteria`, as the check's do. The runner's gate card lists them.
    """
    text = _clean_text(text)
    if mode == "spec":
        section = _criteria_section(_body(text))
    elif mode == "plan":
        meta = parse_frontmatter(text)
        if not is_specless_plan(meta):
            return []
        section = _own_criteria_sections(_body(text), is_bugfix_plan(meta))[0]
    else:
        return []
    blocks = _bullet_blocks(_unfenced(section or ""))
    return [(match.group(0), tokens) for match, tokens in _sourced_criteria(blocks)]


def check_spec(text, design_text=None, check_data=None, require_sources=False, feedback_text=None,
               feedback_gates=None):
    """Validate a spec artifact. Returns {'errors': [...], 'warnings': [...]}.

    Errors: a required section is absent.
    Warnings: a present section is thin (<40 non-blank chars before the next
    heading); an acceptance-criteria bullet lacks a testable marker or an `AC<n>`
    id (the plan gate checks coverage by id, so an unlabelled criterion is one
    it cannot check).

    With `require_sources`, every criterion (a top-level bullet of the acceptance-criteria section
    that carries an `AC<n>` id; the section runs to the next heading of its own level, see
    `_criteria_section`) must name where it came from, `(source: request, D1, Q2, F3)`: `ac_no_source`,
    `ac_bad_source`, `ac_unknown_source` (see `_source_errors`). An id anywhere else in the spec body
    is counted by the plan coverage too, so it is `ac_no_source` unless it is also such a bullet.
    `design_text` is the design file's text (what `D<n>` may name), `check_data` the parsed check
    file (what `Q<n>` may name), and `feedback_text` the package's feedback log (what `F<n>` may name:
    a `reject` record at one of `feedback_gates`, any gate when none is given; see
    `_feedback_numbers`); without one, no token of its kind is known. Without `require_sources` the
    tag is ignored.

    Only the body after the frontmatter block is read (`_body`).
    """
    errors = []
    warnings = []

    text = _body(text)
    headings = list(_iter_headings(text))

    # Map each required section to the first heading that contains its substring.
    found = {}  # slug -> lineno
    for slug, needle in REQUIRED_SPEC_SECTIONS.items():
        for lineno, _raw, norm in headings:
            if needle in norm:
                found[slug] = lineno
                break

    for slug in REQUIRED_SPEC_SECTIONS:
        if slug not in found:
            errors.append(f"missing_section:{slug}")
            continue
        body = _section_body(text, found[slug])
        non_blank = "".join(ch for ch in body if not ch.isspace())
        if len(non_blank) < THIN_SECTION_CHARS:
            warnings.append(f"thin_section:{slug}")

    # Per-criterion checks, scoped to the acceptance-criteria section body.
    for index, criterion, _nested in _acceptance_criteria(text):
        if not TESTABLE_MARKERS.search(criterion):
            warnings.append(f"untestable_criterion:{index}")
    warnings += [f"ac_missing_id:{index}" for index in _unlabelled_criteria(text)]

    if require_sources:
        section = _criteria_section(text)
        errors += _source_errors(_bullet_blocks(_unfenced(section or "")), _decision_numbers(design_text),
                                 _check_questions(check_data), text,
                                 _feedback_numbers(feedback_text, feedback_gates))

    # Security hand-wave: only when a security section exists AND its short body is
    # nothing but a bare dismissal. A grounded note (which cites an input->sink, or
    # explains why no input reaches the code) is longer and does not trip this.
    for lineno, _raw, norm in headings:
        if SECURITY_HEADING_RE.search(norm):
            sec_body = _section_body(text, lineno)
            if SECURITY_HANDWAVE_RE.search(sec_body) and len("".join(sec_body.split())) < 120:
                warnings.append("security_handwave")
            break

    return {"errors": errors, "warnings": warnings}


def _mask(line):
    """Return a representation that proves a hit without leaking the value."""
    return "***MASKED***"


def _strip_inline_code(line):
    """Drop `inline code` spans so a placeholder shown as an example doesn't count."""
    return re.sub(r"`[^`]*`", "", line)


def _strip_fenced_code(text):
    """Return `text` with fenced code blocks removed.

    Same rationale as the placeholder scanner: a doc that *describes* or *bans* a
    pattern inside a ``` fence (e.g. this plan's own "## Non-task step" example, or
    the skill text that bans the deferral) is illustrative, not an actual deferral.
    Prose-level checks must not fire on those fenced examples.
    """
    out = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue  # drop the fence marker line itself
        if not in_fence:
            out.append(line)
    return "\n".join(out)


def scan_placeholders_and_secrets(text):
    """Scan every line for placeholders (warning) and secrets (error). Runs in every mode.

    Placeholders inside a fenced code block or an inline-code span are illustrative — a doc
    that merely *describes* the TODO/TBD tokens (e.g. this validator's own plan) shouldn't be
    flagged — so they're skipped. Secrets are scanned on EVERY line including code blocks,
    because a real credential pasted into a fence is still a leak; secret hits are reported
    with the value MASKED (the real text never reaches the output).
    """
    errors = []
    warnings = []
    in_fence = False
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue  # the fence marker line itself carries no finding
        # Placeholders: skip fenced code and inline-code spans (illustrative, not actionable).
        if not in_fence and PLACEHOLDER_RE.search(_strip_inline_code(line)):
            warnings.append(f"placeholder:{lineno}")
        # Secrets: always scan the full line — a secret in a code block is still a leak.
        for pat in SECRET_PATTERNS:
            if pat.search(line):
                errors.append(f"possible_secret:{lineno}={_mask(line)}")
                break  # one report per line is enough
    return {"errors": errors, "warnings": warnings}


def _fenced_lines(lines):
    """Indexes of the lines that are code: the ``` / ~~~ fence markers and every line between them.

    The same toggle as `_strip_fenced_code` and the placeholder scanner. Structure detectors skip
    these lines: a `# comment` in a shell snippet is not a heading, and a `T1 ...` line in an
    example is not a task.
    """
    fenced = set()
    in_fence = False
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            fenced.add(i)
        elif in_fence:
            fenced.add(i)
    return fenced


def _task_starts(lines):
    """[(line_index, number_or_None)] for every task-block start among `lines`, outside code fences."""
    fenced = _fenced_lines(lines)
    starts = []
    for i, line in enumerate(lines):
        if i in fenced:
            continue
        number = None
        is_start = False
        if TASK_HEADING_RE.match(line):
            is_start = True
            mtid = TASK_TID_RE.search(line)
            if mtid:
                number = int(mtid.group(0)[1:])
        else:
            mtid = TASK_TID_START_RE.match(line)
            if mtid:
                is_start = True
                number = int(mtid.group(1)[1:])
        if is_start:
            starts.append((i, number))
    return starts


def _iter_task_blocks(text):
    """Split plan text into task blocks. Returns a list of (number, block_text).

    A task block starts at a "## Task N" heading or a line-leading "TN" marker (see
    the detector regexes). `number` is the integer used for ordering, taken from a
    'T\\d+' token when present, else None. Bare numbered list items and mid-prose
    task-id references are intentionally NOT task starts (they over-count real plans).
    """
    lines = text.splitlines()
    starts = _task_starts(lines)

    blocks = []
    for idx, (line_i, number) in enumerate(starts):
        end = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        block = "\n".join(lines[line_i:end])
        blocks.append((number, block))
    return blocks


# The bug report of a bugfix plan: a heading that starts with the word "Bug" ("## Bug",
# "## 1. Bug (expected, actual, reproduction)"). Start-anchored so a task heading such as
# "## Task 2 — Fix the bug" never stands in for it.
BUG_HEADING_RE = re.compile(r"^bugs?\b")


def _heading_level(line):
    stripped = line.lstrip()
    return len(stripped) - len(stripped.lstrip("#"))


def _own_criteria_sections(text, bugfix=True):
    """(criteria_text or None, errors, warnings) for a spec-less plan.

    Headings are read outside code fences (a `# comment` in a shell snippet is not a heading), and
    task headings are never taken for either section. A section runs from its heading to the next
    heading of the same or a higher level, and never past the first task block.

    - Only a bugfix plan (`bugfix=True`) has a bug report. It is the first heading at level 2 or
      deeper, before the first task block, whose text starts with "Bug". The document title
      (level 1), a sub-heading inside a task and a section after the tasks are not the bug report
      (`missing_section:bug`). Design §5.19 has it carry expected, actual and reproduction, so a
      body under THIN_SECTION_CHARS non-blank characters warns `thin_section:bug`, as a thin spec
      section does.
    - The criteria are the body of the plan's own acceptance-criteria section. It must come before
      the first task block (`bugfix_ac_section_after_tasks` for a bugfix plan,
      `ac_section_after_tasks` for another one); one inside a task block would be "covered" by the
      very block that holds it.
    """
    lines = text.splitlines()
    fenced = _fenced_lines(lines)
    starts = _task_starts(lines)
    task_lines = {i for i, _number in starts}
    first_task = starts[0][0] if starts else len(lines)
    headings = []  # (line_index, normalized text, level)
    for i, line in enumerate(lines):
        match = HEADING_RE.match(line)
        if match and i not in task_lines and i not in fenced:
            headings.append((i, _normalize_heading(match.group(1)), _heading_level(line)))

    def section_end(at, level):
        return next((i for i, _norm, lvl in headings if at < i < first_task and lvl <= level), first_task)

    errors = []
    warnings = []
    if bugfix:
        bug = next(((i, level) for i, norm, level in headings
                    if i < first_task and level >= 2 and BUG_HEADING_RE.match(norm)), None)
        if bug is None:
            errors.append("missing_section:bug")
        else:
            bug_body = "\n".join(lines[bug[0] + 1:section_end(*bug)])
            if len("".join(bug_body.split())) < THIN_SECTION_CHARS:
                warnings.append("thin_section:bug")
    needle = REQUIRED_SPEC_SECTIONS["acceptance-criteria"]
    section = next(((i, level) for i, norm, level in headings if needle in norm), None)
    if section is None:
        errors.append("missing_section:acceptance-criteria")
        return None, errors, warnings
    at, level = section
    if at > first_task:
        errors.append("bugfix_ac_section_after_tasks" if bugfix else "ac_section_after_tasks")
        return None, errors, warnings
    return "\n".join(lines[at + 1:section_end(at, level)]), errors, warnings


def _ac_coverage(source_text, blocks, warnings):
    """Count the AC ids of `source_text` that some task block names; warn for the rest.

    One obligation per criterion, reported in the source's own spelling.
    """
    source_ids = {}
    for m in AC_ID_RE.finditer(source_text):
        source_ids.setdefault(_ac_key(m), m.group(0))
    if not source_ids:
        warnings.append("ac_source_empty")
    cited = [{_ac_key(m) for m in AC_ID_RE.finditer(block)} for _, block in blocks]
    covered = 0
    for key in sorted(source_ids):
        if any(key in ids for ids in cited):
            covered += 1
        else:
            warnings.append(f"ac_not_covered:{source_ids[key]}")
    return covered


def check_plan(text, spec_text, bugfix=False, own_criteria=False, design_text=None, require_sources=False,
               feedback_text=None, feedback_gates=None):
    """Validate a plan artifact against the spec's acceptance criteria.

    AC ids are sourced from `spec_text` ONLY (DP-2): no mining from the plan body,
    because mining would reward spec/plan leakage. If `spec_text` is missing, we
    cannot judge coverage -> single `ac_source_missing` warning.

    Coverage must not pass by having nothing to check: a plan with no task block
    warns `plan_no_tasks`, and a spec that yields no id warns `ac_source_empty`.
    A single criterion without an id is reported by the spec check
    (`ac_missing_id:<n>`), not here: telling a criterion bullet from a detail
    bullet is a heuristic, and this check is the strict plan gate.

    `bugfix=True` or `own_criteria=True` is the one exception to DP-2 (design §5.19): a spec-less
    plan has no spec, so `spec_text` is ignored and the ids come from the plan's own
    acceptance-criteria section, which must come before the first task block
    (`bugfix_ac_section_after_tasks` for a bugfix plan, `ac_section_after_tasks` for another one).
    That section is required (`missing_section:acceptance-criteria`), and so is a `## Bug` section
    for a bugfix plan only (`missing_section:bug`); see `_own_criteria_sections`. `bugfix=True`
    implies own criteria. Coverage is then judged exactly as against a spec. No spec
    check runs on that section, so its criteria without an id are reported here
    (`ac_missing_id:<n>`, fenced lines aside); otherwise they would drop out of the
    gate in silence.

    With `require_sources`, each of those own criteria must name where it came from,
    `(source: request, D1, F2)` (`ac_no_source`, `ac_bad_source`, `ac_unknown_source`; see
    `_source_errors`), and every id the coverage counts in that section must be such a criterion: an
    id in a table, a heading or a nested bullet is `ac_no_source`. `design_text` is what `D<n>` may
    name and `feedback_text` with `feedback_gates` what `F<n>` may name (as for a spec); a plan has no
    questions, so any `Q<n>` is unknown. A plan checked against a spec has no own criteria, so
    `require_sources` changes nothing for it.

    Only the bodies after the frontmatter blocks of the plan and the spec are read
    (`_body`): a task, a section or an id inside a block does not count.
    """
    errors = []
    warnings = []
    metrics = {}

    text = _body(text)
    if spec_text is not None:
        spec_text = _body(spec_text)
    blocks = _iter_task_blocks(text)
    metrics["plan_tasks"] = len(blocks)
    if not blocks:
        warnings.append("plan_no_tasks")

    # Per-task structural checks.
    for number, block in blocks:
        if not FILE_REF_RE.search(block):
            warnings.append("task_missing_file")
        if not TDD_MARKER_RE.search(block):
            warnings.append("task_missing_tdd")
        if not VERIFICATION_RE.search(block):
            warnings.append("task_no_verification")
    # Deferral scan runs on PROSE only — fenced code blocks AND inline-code spans
    # stripped, matching the placeholder scanner's illustrative-skip rule. A
    # "## Non-task step" shown inside a fence, or a `Non-task step` token named in
    # backticks (as this plan and the skill bodies do to describe/ban the pattern),
    # is illustrative, not a real deferral, so it must not trip the check.
    deferral_prose = "\n".join(
        _strip_inline_code(line) for line in _strip_fenced_code(text).splitlines()
    )
    if DEFERRAL_RE.search(deferral_prose):
        warnings.append("deferred_work")

    # Ordering: numbered tasks must be strictly increasing.
    numbers = [n for n, _ in blocks if n is not None]
    if any(b <= a for a, b in zip(numbers, numbers[1:])):
        warnings.append("tasks_unordered")

    # AC coverage — only when we have a canonical source: the spec, or a spec-less plan's own section.
    if bugfix or own_criteria:
        criteria, criteria_errors, criteria_warnings = _own_criteria_sections(text, bugfix)
        errors += criteria_errors
        warnings += criteria_warnings
        if criteria is None:
            metrics["plan_ac_covered"] = 0
        else:
            criteria_lines = criteria.splitlines()
            fenced = _fenced_lines(criteria_lines)
            unfenced = "\n".join(line for i, line in enumerate(criteria_lines) if i not in fenced)
            warnings += [f"ac_missing_id:{index}" for index in _unlabelled(_criterion_bullets(unfenced))]
            if require_sources:
                errors += _source_errors(_bullet_blocks(unfenced), _decision_numbers(design_text), set(), criteria,
                                         _feedback_numbers(feedback_text, feedback_gates))
            metrics["plan_ac_covered"] = _ac_coverage(criteria, blocks, warnings)
    elif spec_text is None:
        warnings.append("ac_source_missing")
        metrics["plan_ac_covered"] = 0
    else:
        metrics["plan_ac_covered"] = _ac_coverage(spec_text, blocks, warnings)

    return {"errors": errors, "warnings": warnings, "metrics": metrics}


def emit(fields):
    """Print sorted flat key=value lines.

    A value of None means the key is already a complete line (e.g. a
    'warning=ac_not_covered:AC2' entry) and is printed verbatim — this keeps
    warning/error lines on the same sorted plane as scalar fields.
    """
    for key in sorted(fields):
        if fields[key] is None:
            print(key)
        else:
            print(f"{key}={fields[key]}")


def _read(path):
    return Path(path).read_text(encoding="utf-8-sig")


def _read_artifact(path):
    """(text, None), or (None, reason) when the file cannot be read: missing | not_utf8 | error."""
    try:
        return _read(path), None
    except FileNotFoundError:
        return None, "missing"
    except UnicodeDecodeError:
        return None, "not_utf8"
    except (OSError, ValueError):
        return None, "error"


def _fields(mode, metrics, warnings, errors):
    fields = {"mode": mode}
    for k, v in metrics.items():
        fields[k] = v
    # Each warning/error becomes its own complete line (value None -> printed
    # verbatim by emit()), so they sort alongside the scalar fields.
    for w in warnings:
        fields[f"warning={w}"] = None
    for e in errors:
        fields[f"error={e}"] = None
    fields["artifacts_validation"] = "failed" if errors else "passed"
    return fields


def _read_check(path):
    """(check_data, None), or (None, reason): missing | not_utf8 | error | invalid_json | invalid_shape.

    The check file is JSON with `"questions": [{"id": "Q1", ...}, ...]`; a file without the key
    names no question.
    """
    text, unreadable = _read_artifact(path)
    if unreadable:
        return None, unreadable
    try:
        data = json.loads(text)
    except ValueError:
        return None, "invalid_json"
    if not isinstance(data, dict) or not isinstance(data.get("questions", []), list):
        return None, "invalid_shape"
    return data, None


def run(mode, file_path, spec_path, strict, design_path=None, check_path=None, sources=False,
        feedback_path=None, feedback_gates=None):
    """Run the requested checks and return (exit_code, fields_dict).

    Kept separate from main() so callers/tests can drive it without argparse. The gate passes when
    the exit code (`run(...)[0]`) is 0. An unreadable artifact, spec, design or check file is a
    failed gate with a named reason, never an exception.

    `sources` makes every criterion of a spec, or of a spec-less plan, name where it came from.
    `design_path` (the design file, what `D<n>` may name), `check_path` (the spec's check file,
    what `Q<n>` may name) and `feedback_path` (the package's feedback.jsonl, what `F<n>` may name: a
    `reject` record at one of `feedback_gates`, any gate when none is given) are read only then. A
    path that is None names nothing, so its tokens are unknown. A design or check file that cannot be
    read is an error; a feedback log that cannot be read names no record, like a missing one.
    """
    errors = []
    warnings = []
    metrics = {}

    file_text, unreadable = _read_artifact(file_path)
    if unreadable:
        return 1, _fields(mode, metrics, warnings, [f"file_unreadable:{unreadable}"])

    design_text = None
    check_data = None
    if sources and design_path:
        design_text, unreadable = _read_artifact(design_path)
        if unreadable:
            errors.append(f"design_unreadable:{unreadable}")
    if sources and check_path:
        check_data, unreadable = _read_check(check_path)
        if unreadable:
            errors.append(f"check_unreadable:{unreadable}")
    feedback_text = None
    if sources and feedback_path:
        feedback_text, _unreadable = _read_artifact(feedback_path)

    # The placeholder/secret scan runs in every mode, on the artifact under test.
    scan = scan_placeholders_and_secrets(file_text)
    errors += scan["errors"]
    warnings += scan["warnings"]

    # Frontmatter first: it is the cheapest check and the one the resolver will apply later.
    errors += check_frontmatter(file_text, mode)

    if mode == "design":
        design_res = check_design(file_text)
        errors += design_res["errors"]
        warnings += design_res["warnings"]

    if mode in ("spec", "all"):
        spec_res = check_spec(file_text, design_text, check_data, sources, feedback_text, feedback_gates)
        errors += spec_res["errors"]
        warnings += spec_res["warnings"]

    if mode in ("plan", "all"):
        # The plan's own frontmatter decides its kind. A spec-less plan is checked against its own
        # criteria. A --spec given for it anyway means the caller and the artifact disagree about
        # whether there is a spec; the artifact under test must not settle that by switching the
        # caller's spec off, so the gate fails (`spec_none_with_spec`) and the spec is not read.
        meta = parse_frontmatter(file_text)
        errors += check_plan_kind(meta)
        bugfix = is_bugfix_plan(meta)
        specless = is_specless_plan(meta)
        spec_text = None
        if spec_path and specless:
            errors.append("spec_none_with_spec")
        elif spec_path:
            spec_text, unreadable = _read_artifact(spec_path)
            if unreadable:
                errors.append(f"spec_unreadable:{unreadable}")
        plan_res = check_plan(file_text, spec_text, bugfix=bugfix, own_criteria=specless,
                              design_text=design_text, require_sources=sources,
                              feedback_text=feedback_text, feedback_gates=feedback_gates)
        errors += plan_res["errors"]
        warnings += plan_res["warnings"]
        metrics.update(plan_res["metrics"])

    # --strict: every warning becomes a gating error.
    if strict:
        errors += warnings
        warnings = []

    return (1 if errors else 0), _fields(mode, metrics, warnings, errors)


def build_parser():
    p = argparse.ArgumentParser(
        description="Deterministic spec/plan artifact validator (stdlib only)."
    )
    p.add_argument("--mode", choices=["spec", "plan", "all", "design"], required=True)
    p.add_argument("--file", required=True, help="artifact under test")
    p.add_argument(
        "--spec",
        default=None,
        help="canonical acceptance-criteria source for plan/all mode (DP-2); a spec-less plan "
             "(`spec: none` with `flow: bugfix`, `feature` or `plan`) takes none, and fails with "
             "`spec_none_with_spec` when one is given",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="promote every warning to an error",
    )
    p.add_argument(
        "--sources",
        action="store_true",
        help="require every criterion of a spec, or of a spec-less plan, to carry "
             "`(source: request, D<n>, Q<n>, F<n>)`",
    )
    p.add_argument("--design", default=None, help="design.md, what a source `D<n>` may name (with --sources)")
    p.add_argument(
        "--check",
        default=None,
        help="the spec's check file (JSON with `questions`), what a source `Q<n>` may name (with --sources)",
    )
    p.add_argument(
        "--feedback",
        default=None,
        help="the package's feedback.jsonl, what a source `F<n>` may name: the `reject` record whose "
             "`seq` is n (with --sources; a missing or unreadable file names no record)",
    )
    p.add_argument(
        "--feedback-gate",
        action="append",
        default=None,
        metavar="NAME",
        help="a gate whose reject records `F<n>` may name; repeatable; none given: any gate (with --sources)",
    )
    return p


def _utf8_output():
    """Print UTF-8 whatever the console code page: an echoed non-ASCII value must not crash a gate."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv=None):
    _utf8_output()
    args = build_parser().parse_args(argv)
    code, fields = run(args.mode, args.file, args.spec, args.strict,
                       design_path=args.design, check_path=args.check, sources=args.sources,
                       feedback_path=args.feedback, feedback_gates=args.feedback_gate)
    emit(fields)
    return code


if __name__ == "__main__":
    sys.exit(main())
