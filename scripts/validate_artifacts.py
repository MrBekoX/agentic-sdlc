"""Deterministic spec/plan artifact validator.

Why this exists: a spec/plan gate should be machine-checkable, not a matter of
taste. This script reads a markdown artifact and emits sorted flat `key=value`
lines so the result is diffable, greppable, and stable across runs. It is the
deterministic counterpart to the adversarial `spec-plan-draft` loop.

Design constraints (from the approved plan):
- Pure stdlib only (argparse, re, pathlib, sys). No third-party imports.
- Read-only: no file writes, no shell, no path traversal beyond the given file.
- Secrets are MASKED, never printed — the value that tripped a pattern is
  replaced with ***MASKED*** so the validator can't become a leak channel.

Output contract:
- `emit()` prints sorted `key=value` lines, including `mode=<mode>` and
  `artifacts_validation=passed|failed`.
- `main()` returns exit 1 if any errors, else 0.
- `--strict` promotes every `warning=` to `error=` (warnings become gating).
"""

import argparse
import re
import sys
from pathlib import Path

# Required spec sections. The key is the canonical slug emitted in messages; the
# value is the substring we look for inside a heading (case-insensitive, after
# stripping numbering and trailing parentheticals). Order is irrelevant — we
# report by slug.
REQUIRED_SPEC_SECTIONS = {
    "problem": "problem",
    "business-rules": "business rules",
    "acceptance-criteria": "acceptance criteria",
    "edge-cases": "edge cases",
    "definition-of-done": "definition of done",
    "must-not-change": "must-not-change",
}

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
TASK_HEADING_RE = re.compile(r"^\s{0,3}#{2,4}\s*Task\b", re.IGNORECASE)
TASK_TID_RE = re.compile(r"\bT\d+\b")
TASK_TID_START_RE = re.compile(r"^[\s>*\-#]*\*{0,2}\s*(T\d+)\b")

# An acceptance-criterion id: `AC1`, `AC-1`, or a grouped `AC-A1` (pipeline specs use all three).
# `AC1` and `AC-1` name the same criterion, so ids are compared by `_ac_key`, never by spelling.
# The group letter needs the hyphen, so a word such as `ACE2` is not an id.
AC_ID_RE = re.compile(r"\bAC(?:-?(\d+)|-([A-Z])(\d+))\b")


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


def _acceptance_criteria(text):
    """Return [(index, line, nested)] for each bullet of the first acceptance-criteria section.

    The index is the bullet's 1-based position: `untestable_criterion:<n>` and
    `ac_missing_id:<n>` name the same bullet by it. `nested` is True for a bullet indented
    under another one. No section means no criteria.
    """
    needle = REQUIRED_SPEC_SECTIONS["acceptance-criteria"]
    for lineno, _raw, norm in _iter_headings(text):
        if needle in norm:
            body = _section_body(text, lineno)
            break
    else:
        return []
    criteria = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith(("-", "*")) or re.match(r"^\d+\.", stripped):
            indent = line[:len(line) - len(line.lstrip())]
            criteria.append((len(criteria) + 1, stripped, "\t" in indent or len(indent) >= 2))
    return criteria


def _unlabelled_criteria(text):
    """Indexes of the criteria the plan gate cannot check: a top-level bullet that reads as a
    criterion (it has a testable marker) and carries no `AC<n>` id.

    Real pipeline specs put a bold group heading, or a nested "Guards:"/"Variant:" line, inside the
    section. Neither is a criterion of its own, so neither is reported here. A top-level detail
    bullet that happens to say "when" still is, which is why only the spec check uses this.
    """
    return [index for index, line, nested in _acceptance_criteria(text)
            if not nested and TESTABLE_MARKERS.search(line) and not AC_ID_RE.search(line)]


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


def parse_frontmatter(text):
    """Return the leading `---` block as a dict, or {} when there is none.

    Only a block that OPENS ON THE FIRST LINE counts. Scanning for `---` anywhere would let a
    fenced example, a horizontal rule, or a document that merely discusses frontmatter satisfy
    the check from outside the block.

    Deliberately not a YAML parser: `key: value` on one line, matching what the resolver reads
    and what the skills tell authors to write. A nested or multi-line value is not frontmatter
    this pipeline uses.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    meta = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return meta
        key, sep, value = line.partition(":")
        if sep and key.strip():
            meta[key.strip()] = value.strip()
    return {}                                    # unterminated block: not frontmatter


def check_frontmatter(text, mode):
    """Errors for the required keys of `mode`. An empty value counts as missing."""
    required = FRONTMATTER_REQUIRED.get(mode)
    if not required:
        return []
    meta = parse_frontmatter(text)
    errors = [f"missing_frontmatter_key:{key}" for key in required if not meta.get(key)]
    status = meta.get("status")
    if status and status not in FRONTMATTER_STATUSES:
        errors.append(f"invalid_status:{status}")
    return errors


def check_spec(text):
    """Validate a spec artifact. Returns {'errors': [...], 'warnings': [...]}.

    Errors: a required section is absent.
    Warnings: a present section is thin (<40 non-blank chars before the next
    heading); an acceptance-criteria bullet lacks a testable marker or an `AC<n>`
    id (the plan gate checks coverage by id, so an unlabelled criterion is one
    it cannot check).
    """
    errors = []
    warnings = []

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
        if len(non_blank) < 40:
            warnings.append(f"thin_section:{slug}")

    # Per-criterion checks, scoped to the acceptance-criteria section body.
    for index, criterion, _nested in _acceptance_criteria(text):
        if not TESTABLE_MARKERS.search(criterion):
            warnings.append(f"untestable_criterion:{index}")
    warnings += [f"ac_missing_id:{index}" for index in _unlabelled_criteria(text)]

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


def _iter_task_blocks(text):
    """Split plan text into task blocks. Returns a list of (number, block_text).

    A task block starts at a "## Task N" heading or a line-leading "TN" marker (see
    the detector regexes). `number` is the integer used for ordering, taken from a
    'T\\d+' token when present, else None. Bare numbered list items and mid-prose
    task-id references are intentionally NOT task starts (they over-count real plans).
    """
    lines = text.splitlines()
    starts = []  # (line_index, number_or_None)
    for i, line in enumerate(lines):
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

    blocks = []
    for idx, (line_i, number) in enumerate(starts):
        end = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        block = "\n".join(lines[line_i:end])
        blocks.append((number, block))
    return blocks


def check_plan(text, spec_text):
    """Validate a plan artifact against the spec's acceptance criteria.

    AC ids are sourced from `spec_text` ONLY (DP-2): no mining from the plan body,
    because mining would reward spec/plan leakage. If `spec_text` is missing, we
    cannot judge coverage -> single `ac_source_missing` warning.

    Coverage must not pass by having nothing to check: a plan with no task block
    warns `plan_no_tasks`, and a spec that yields no id warns `ac_source_empty`.
    A single criterion without an id is reported by the spec check
    (`ac_missing_id:<n>`), not here: telling a criterion bullet from a detail
    bullet is a heuristic, and this check is the strict plan gate.
    """
    errors = []
    warnings = []
    metrics = {}

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

    # AC coverage — only when we have a canonical spec source.
    if spec_text is None:
        warnings.append("ac_source_missing")
        metrics["plan_ac_covered"] = 0
    else:
        # One obligation per criterion, reported in the spec's own spelling.
        spec_ids = {}
        for m in AC_ID_RE.finditer(spec_text):
            spec_ids.setdefault(_ac_key(m), m.group(0))
        if not spec_ids:
            warnings.append("ac_source_empty")
        cited = [{_ac_key(m) for m in AC_ID_RE.finditer(block)} for _, block in blocks]
        covered = 0
        for key in sorted(spec_ids):
            if any(key in ids for ids in cited):
                covered += 1
            else:
                warnings.append(f"ac_not_covered:{spec_ids[key]}")
        metrics["plan_ac_covered"] = covered

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


def run(mode, file_path, spec_path, strict):
    """Run the requested checks and return (exit_code, fields_dict).

    Kept separate from main() so callers/tests can drive it without argparse.
    """
    errors = []
    warnings = []
    metrics = {}

    file_text = _read(file_path)

    # The placeholder/secret scan runs in every mode, on the artifact under test.
    scan = scan_placeholders_and_secrets(file_text)
    errors += scan["errors"]
    warnings += scan["warnings"]

    # Frontmatter first: it is the cheapest check and the one the resolver will apply later.
    errors += check_frontmatter(file_text, mode)

    if mode in ("spec", "all"):
        spec_res = check_spec(file_text)
        errors += spec_res["errors"]
        warnings += spec_res["warnings"]

    if mode in ("plan", "all"):
        spec_text = _read(spec_path) if spec_path else None
        plan_res = check_plan(file_text, spec_text)
        errors += plan_res["errors"]
        warnings += plan_res["warnings"]
        metrics.update(plan_res["metrics"])

    # --strict: every warning becomes a gating error.
    if strict:
        errors += warnings
        warnings = []

    fields = {}
    fields["mode"] = mode
    for k, v in metrics.items():
        fields[k] = v
    # Each warning/error becomes its own complete line (value None -> printed
    # verbatim by emit()), so they sort alongside the scalar fields.
    for w in warnings:
        fields[f"warning={w}"] = None
    for e in errors:
        fields[f"error={e}"] = None
    fields["artifacts_validation"] = "failed" if errors else "passed"

    return (1 if errors else 0), fields


def build_parser():
    p = argparse.ArgumentParser(
        description="Deterministic spec/plan artifact validator (stdlib only)."
    )
    p.add_argument("--mode", choices=["spec", "plan", "all"], required=True)
    p.add_argument("--file", required=True, help="artifact under test")
    p.add_argument(
        "--spec",
        default=None,
        help="canonical acceptance-criteria source for plan/all mode (DP-2)",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="promote every warning to an error",
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
    code, fields = run(args.mode, args.file, args.spec, args.strict)
    emit(fields)
    return code


if __name__ == "__main__":
    sys.exit(main())
