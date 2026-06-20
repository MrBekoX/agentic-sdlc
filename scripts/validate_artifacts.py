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
SECRET_PATTERNS = [
    re.compile(r"api[_-]?key\s*[:=]", re.IGNORECASE),
    re.compile(r"secret\s*[:=]", re.IGNORECASE),
    re.compile(r"password\s*[:=]", re.IGNORECASE),
    re.compile(r"token\s*[:=]\s*\S{12,}", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
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

AC_ID_RE = re.compile(r"\bAC\d+\b")

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


def check_spec(text):
    """Validate a spec artifact. Returns {'errors': [...], 'warnings': [...]}.

    Errors: a required section is absent.
    Warnings: a present section is thin (<40 non-blank chars before the next
    heading); an acceptance-criteria bullet lacks a testable marker.
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

    # Testable-criteria check, scoped to the acceptance-criteria section body.
    if "acceptance-criteria" in found:
        ac_body = _section_body(text, found["acceptance-criteria"])
        index = 0
        for line in ac_body.splitlines():
            stripped = line.strip()
            if stripped.startswith(("-", "*")) or re.match(r"^\d+\.", stripped):
                index += 1
                if not TESTABLE_MARKERS.search(stripped):
                    warnings.append(f"untestable_criterion:{index}")

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
    """
    errors = []
    warnings = []
    metrics = {}

    blocks = _iter_task_blocks(text)
    metrics["plan_tasks"] = len(blocks)

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
        ac_ids = sorted(set(AC_ID_RE.findall(spec_text)), key=lambda s: int(s[2:]))
        covered = 0
        for ac in ac_ids:
            ac_re = re.compile(r"\b" + re.escape(ac) + r"\b")
            if any(ac_re.search(block) for _, block in blocks):
                covered += 1
            else:
                warnings.append(f"ac_not_covered:{ac}")
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
    return Path(path).read_text(encoding="utf-8")


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


def main(argv=None):
    args = build_parser().parse_args(argv)
    code, fields = run(args.mode, args.file, args.spec, args.strict)
    emit(fields)
    return code


if __name__ == "__main__":
    sys.exit(main())
