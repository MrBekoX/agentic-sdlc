"""Stdlib secret masker for everything the runner records: argv, output tails, quotes.

A port of hooks/secret-patterns.mjs: the pattern list (`BROAD` = `HIGH` + `assigned-secret`), the
per-match collector `lineMatches` and the durable `redactSecrets`. The runner never shells out to
Node, so scripts/sensitive_redaction.py (a Node adapter) is not used here.

Each pattern keeps its JS regex literal verbatim (`Pattern.source`); the Python regex is translated
from it, and the value-group plan is derived from it the way `planFor` does in the .mjs.
tests/test_sdlc_mask_parity.py pins the sources against the .mjs and cross-checks the output with
Node when it is installed. JS semantics kept by the translation:
* JS regexes without the `u` flag use ASCII `\\b`, `\\w` and case folding -> re.ASCII;
* JS `\\s` is wider than ASCII whitespace -> an explicit character class;
* `$` without the `m` flag is the end of input -> `\\Z`;
* a value's minimum length counts UTF-16 code units, as JS string lengths do.

Like `redactSecrets`, masking ignores the per-line allow markers (an annotation may let a fixture
into source control; it never lets a secret into a log) and keeps exact published samples and
structural placeholders.
"""
from __future__ import annotations

import re

MASK = "***MASKED***"

# JS \s (and the characters String.prototype.trim removes).
_WS_BODY = "\t\n\x0b\x0c\r \xa0  -     　﻿"
_WS = "[" + _WS_BODY + "]"
_TRIM = "\t\n\x0b\x0c\r \xa0 " + "".join(chr(c) for c in range(0x2000, 0x200B)) + "    　﻿"

# Verbatim JS literals from hooks/secret-patterns.mjs (pinned by tests/test_sdlc_mask_parity.py).
_HIGH_SOURCES = (
    ("private-key", r"/-----BEGIN[A-Z0-9 ]*PRIVATE KEY-----/", None),
    ("aws-access-key-id", r"/(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}/", None),
    ("github-token", r"/(?<![A-Za-z0-9])(?:gh[posru]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40,})/", None),
    ("slack-token", r"/(?<![A-Za-z0-9])(?:xox[baprs]|xapp)-[A-Za-z0-9-]{10,}/i", None),
    ("stripe-key", r"/(?<![A-Za-z0-9])(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}/", None),
    ("google-api-key", r"/(?<![A-Za-z0-9])AIza[0-9A-Za-z_\-]{35}/", None),
    ("openai-key", r"/(?<![A-Za-z0-9])sk-(?:proj-)?[A-Za-z0-9]{20,}/", None),
    ("jwt", r"/\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/", None),
    ("bearer-token", r"/\bbearer\s+[A-Za-z0-9._\-]{20,}/i", None),
    ("password-literal",
     r'''/(?<![A-Za-z0-9])(?:(?<!_)(?:password|pwd|passwd|sa_password|mssql_sa_password)|db_password|pgpassword|mysql_pwd|aws_secret_access_key)["']?\s*[:=]\s*["']?([^;"'\s]{6,})/i''', 1),
    ("url-credential",
     r'''/(?<![A-Za-z0-9])[a-z][a-z0-9+.-]{0,31}:\/\/[^\s:@\/?#\[\]]{0,256}:([^\s@\/?#\[\]]{6,})@/i''', 1),
    ("json-credential",
     r'/"[^"]*(?:password|secret|key|token|credential|signing)[^"]*"\s*:\s*"([^"]{16,})"/i', 1),
)
_BROAD_EXTRA_SOURCES = (
    ("assigned-secret",
     r'''/\b(?:api[_-]?key|apikey|secret|access[_-]?token|client[_-]?secret|auth[_-]?token)\b\s*[:=]\s*["']?([A-Za-z0-9_\-.]{16,})/i''',
     1),
)
TEMPLATE_VALUE_SOURCES = (
    r'''/^["']?<[^<>]*>["']?$/''',
    r'''/^["']?\$\{[^{}]*\}["']?$/''',
    r'''/^["']?\$[A-Za-z_]\w*["']?$/''',
    r'''/^["']?%[A-Za-z_]\w*%["']?$/''',
    r"/^\*+$/",
    r"/^\*\*\*MASKED\*\*\*$/",
    r'''/^["']?(?:process\.env|os\.environ|System\.getenv|getenv|env)\b/i''',
    r'''/^["']?(?:change[_-]?me|placeholder|dummy|todo|fixme|redacted|masked|secret_here)\b/i''',
    r'''/^["']?your[_-]?\w*\b/i''',
    r'''/^["']?x+["']?$/i''',
)
# Published vendor documentation samples, matched exactly (built in pieces so this file does not
# carry the whole strings that GitHub secret scanning flags).
DOC_SAMPLES = frozenset([
    "AKIA" + "IOSFODNN7EXAMPLE",
    "AIza" + "SyDaGmWKa4JsXZ-HjGw7ISLn_3namBGewQe",
    "sk_" + "test_" + "4eC39HqLyjWDarjtT1zdp7dc",
])

# planFor's helpers, applied to the JS sources exactly as the .mjs applies them.
_LEADING_ANCHOR = re.compile(r"^(?:\(\?<!\[A-Za-z0-9\]\)|\\b)")
_VALUE_GROUP = re.compile(r"\((\[(?:\\.|[^\]\\])+\])\{(\d+),\}\)")
_OTHER_CAPTURE = re.compile(r"(?:^|[^\\])\((?!\?)")
_LETTER_OR_DIGIT = re.compile(r"[A-Za-z0-9]")
_PEM = re.compile(r"-----BEGIN ([A-Z0-9 ]*PRIVATE KEY)-----[\s\S]*?(?:-----END \1-----|\Z)")
_LINE_SPLIT = re.compile(r"(\r?\n)")
_LABELLED = re.compile(r"\*\*\*MASKED:[a-z0-9-]+\*\*\*")
_PASSTHROUGH_ESCAPES = set("bBwWdD.-/\\[](){}*+?|^$'\"")


def _split_literal(literal: str):
    end = literal.rindex("/")
    return literal[1:end], literal[end + 1:]


def _translate(js: str) -> str:
    """JS regex body (no `u` flag) -> Python regex body under re.ASCII."""
    out = []
    in_class = False
    i = 0
    while i < len(js):
        c = js[i]
        if c == "\\":
            nxt = js[i + 1]
            if nxt == "s":
                out.append(_WS_BODY if in_class else _WS)
            elif nxt in _PASSTHROUGH_ESCAPES:
                out.append(c + nxt)
            else:
                raise ValueError("untranslated JS escape \\%s in %r" % (nxt, js))
            i += 2
            continue
        if c == "[" and not in_class:
            in_class = True
        elif c == "]" and in_class:
            in_class = False
        elif c == "$" and not in_class:
            out.append(r"\Z")
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _compile(js_body: str, flags: int):
    return re.compile(_translate(js_body), flags)


class _ValuePlan:
    __slots__ = ("prefix", "sticky_prefix", "run", "min", "tail")

    def __init__(self, prefix, sticky_prefix, run, minimum, tail):
        self.prefix = prefix
        self.sticky_prefix = sticky_prefix
        self.run = run
        self.min = minimum
        self.tail = tail


class Pattern:
    """One pattern family: `label`, its JS `source`, `value_group`, `high` and the compiled forms."""

    def __init__(self, label: str, source: str, value_group, high: bool):
        self.label = label
        self.source = source
        self.value_group = value_group
        self.high = high
        body, js_flags = _split_literal(source)
        self.flags = re.ASCII | (re.IGNORECASE if "i" in js_flags else 0)
        self.regex = _compile(body, self.flags)
        self.sticky = None
        self.value = None
        anchor = _LEADING_ANCHOR.match(body)
        groups = list(_VALUE_GROUP.finditer(body)) if value_group else []
        if len(groups) == 1:
            group = groups[0]
            prefix, tail = body[:group.start()], body[group.end():]
            if not _OTHER_CAPTURE.search(prefix) and not _OTHER_CAPTURE.search(tail):
                self.value = _ValuePlan(
                    _compile(prefix, self.flags),
                    _compile(prefix[anchor.end():], self.flags) if anchor else None,
                    _compile(group.group(1) + "*", self.flags),
                    int(group.group(2)),
                    _compile(tail, self.flags) if tail else None,
                )
        elif not value_group and anchor:
            self.sticky = _compile(body[anchor.end():], self.flags)

    def __repr__(self) -> str:
        return "Pattern(%r)" % self.label


PATTERNS = [Pattern(label, source, group, True) for label, source, group in _HIGH_SOURCES] + [
    Pattern(label, source, group, False) for label, source, group in _BROAD_EXTRA_SOURCES
]
HIGH = [p for p in PATTERNS if p.high]
_TEMPLATE_VALUE = [_compile(_split_literal(s)[0], re.ASCII | (re.IGNORECASE if _split_literal(s)[1] else 0))
                   for s in TEMPLATE_VALUE_SOURCES]


def looks_placeholder(value) -> bool:
    """A captured value that is wholly a template (`<...>`, `${X}`, `$X`, `***`, `xxxx`, ...)."""
    if not value:
        return True
    text = str(value).strip(_TRIM)
    return any(rx.search(text) for rx in _TEMPLATE_VALUE)


def is_degenerate_token(token: str) -> bool:
    """A repeated or sequential run rather than a random token (Meli et al., NDSS 2019)."""
    t = str(token)
    if len(t) < 12:
        return False
    freq = {}
    for c in t:
        freq[c] = freq.get(c, 0) + 1
    if max(freq.values()) / len(t) >= 0.7:
        return True
    if len(freq) <= 2:
        return True
    run = best = 1
    for i in range(1, len(t)):
        d = ord(t[i]) - ord(t[i - 1])
        run = run + 1 if d in (1, -1) else 1
        best = max(best, run)
    return best / len(t) >= 0.6


def _utf16_len(text: str) -> int:
    return len(text) + sum(1 for c in text if ord(c) > 0xFFFF)


def _suppressed(p: Pattern, match) -> bool:
    if p.value_group:
        return looks_placeholder(match.group(p.value_group))
    return match.group(0) in DOC_SAMPLES or is_degenerate_token(match.group(0))


def _value_match_at(line: str, v: _ValuePlan, value_start: int, run: list):
    # run caches the last value-class run [from, end): a start inside it shares its end.
    if not (run[0] <= value_start <= run[1]):
        r = v.run.match(line, value_start)
        run[0] = value_start
        run[1] = value_start + (len(r.group(0)) if r else 0)
    # The .mjs compares UTF-16 units in O(1). A code point is one or two units, so the units are
    # counted (a walk over the run) only when the code-point length alone falls short; counting
    # them on every prefix hit made a long line with many hits quadratic.
    if run[1] - value_start < v.min and _utf16_len(line[value_start:run[1]]) < v.min:
        return None
    end = run[1]
    if v.tail is not None:
        t = v.tail.match(line, run[1])
        if t is None:
            return None
        end += len(t.group(0))
    return end, line[value_start:run[1]]


def line_matches(line: str, patterns) -> list:
    """Every match on one line as (pattern index, start, end, suppressed); port of `lineMatches`."""
    out = []
    seen = set()
    boundaries = []
    queued = set()
    runs = [[-1, -2] for _ in patterns]

    def push(index, start, end, suppressed):
        if (index, start) in seen:
            return
        seen.add((index, start))
        out.append((index, start, end, suppressed))

    def boundary_at(end):
        if end < len(line) and _LETTER_OR_DIGIT.match(line[end]) and end not in queued:
            queued.add(end)
            boundaries.append(end)

    for index, p in enumerate(patterns):
        if p.value is not None:
            v = p.value
            pos = 0
            while True:
                m = v.prefix.search(line, pos)
                if m is None:
                    break
                hit = _value_match_at(line, v, m.end(), runs[index])
                if hit:
                    push(index, m.start(), hit[0], looks_placeholder(hit[1]))
                pos = m.start() + 1  # every prefix start, not only the one after a whole match
            continue
        pos = 0
        while pos <= len(line):
            m = p.regex.search(line, pos)
            if m is None:
                break
            if m.end() == m.start():
                pos = m.start() + 1
                continue
            push(index, m.start(), m.end(), _suppressed(p, m))
            if not p.value_group:
                boundary_at(m.end())
            pos = m.end()
    k = 0
    while k < len(boundaries):
        at = boundaries[k]
        for index, p in enumerate(patterns):
            if p.value is not None and p.value.sticky_prefix is not None:
                v = p.value
                m = v.sticky_prefix.match(line, at)
                hit = _value_match_at(line, v, at + len(m.group(0)), runs[index]) if m else None
                if hit:
                    push(index, at, hit[0], looks_placeholder(hit[1]))
            elif p.sticky is not None:
                m = p.sticky.match(line, at)
                if m and m.group(0):
                    push(index, at, at + len(m.group(0)), _suppressed(p, m))
                    boundary_at(at + len(m.group(0)))
        k += 1
    return out


def _redact_line(line: str, patterns) -> str:
    redacted = line
    matches = None  # recomputed only after a pass changed the line
    for index, p in enumerate(patterns):
        if matches is None:
            matches = line_matches(redacted, patterns)
        hits = sorted((m for m in matches if m[0] == index and not m[3]), key=lambda m: m[1])
        if not hits:
            continue
        rebuilt = []
        copied = 0
        for _index, start, end, _suppressed_flag in hits:
            if start < copied:  # starts inside a span this pass already masked: extend over it
                copied = max(copied, end)
                continue
            rebuilt.append(redacted[copied:start])
            rebuilt.append("***MASKED:" + p.label + "***")
            copied = end
        redacted = "".join(rebuilt) + redacted[copied:]
        matches = None
    return redacted


def redact_labelled(text, patterns=None) -> str:
    """`redactSecrets(text, patterns)` from the .mjs: masks read `***MASKED:<label>***`.

    `patterns` defaults to PATTERNS (every family, as BROAD); pass HIGH for the .mjs default.
    """
    patterns = PATTERNS if patterns is None else patterns
    text = _PEM.sub("***MASKED:private-key***", "" if text is None else str(text))
    parts = _LINE_SPLIT.split(text)
    return "".join(part if part in ("\n", "\r\n") else _redact_line(part, patterns) for part in parts)


def mask_text(text, patterns=None) -> str:
    """Replace every secret match with `***MASKED***` (all families by default)."""
    return _LABELLED.sub(MASK, redact_labelled(text, patterns))
